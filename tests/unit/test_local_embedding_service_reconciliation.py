"""Actual local control/Workflow persistence; explicitly synthetic Catalog/IAM.

SQLite is not PostgreSQL concurrency or service-runtime proof. No model is run.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest
from eom_catalog_service.embedding_incremental_plan import RegisteredEmbeddingRow
from eom_catalog_service.embedding_registry_indexing_authority import (
    CatalogIndexingRegistrySourceAuthority,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingBindingLookupKey,
    EmbeddingRegistryLookup,
    MissingEmbeddingBindings,
    PreparedEmbeddingBindingLookup,
)
from eom_orchestrator.models import ArtifactRevisionRecord, Base, JobRecord
from eom_orchestrator.native_embedding_index_systemd import FixedNativeIndexLauncher
from eom_workflow.local_embedding_request import parse_local_embedding_executable_request
from eom_workflow_runner import local_embedding_service_reconciliation as application
from eom_workflow_runner.document_embedding_cpu_execution import FixedCpuDocumentEmbeddingExecution
from eom_workflow_runner.local_embedding_native_executor import CatalogNativeEmbeddingExecutor
from eom_workflow_runner.local_embedding_service_reconciliation import ReconciliationState
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
)
from eom_workflow_runner.repository import import_workflow_definition
from sqlalchemy import Table, func, select

from tests.unit.inference_transfer_embedding_fixtures import (
    index_manifest,
    index_pointer,
    source_binding,
)
from tests.unit.test_local_embedding_runner_admission import scope_fixture
from tests.unit.test_local_embedding_service_owner import service_owner as service_owner
from tests.unit.test_local_indexing_runtime_admission import installed as installed
from tests.unit.test_postgres_local_indexing_fence import case as case


@pytest.fixture
def reconciliation(service_owner, monkeypatch):
    c = service_owner
    _scope, compiled = scope_fixture()
    Base.metadata.create_all(
        c.publisher.engine,
        tables=[
            cast(Table, model.__table__)
            for model in (
                WorkflowDefinitionRecord,
                WorkflowInstanceRecord,
                WorkflowCommandRecord,
                WorkflowEventRecord,
            )
        ],
    )
    with c.publisher.sessions.begin() as session:
        import_workflow_definition(session, compiled)
    request = c.scope.request
    query = EmbeddingRegistryLookup(
        request.corpus_id,
        request.namespace,
        request.graph_snapshot,
        request.access_policy_revision_id,
        request.access_policy_sha256,
    )
    keys = tuple(
        EmbeddingBindingLookupKey(
            demand.source_revision_id,
            request.graph_snapshot.graph_snapshot_revision_id,
            request.access_policy_revision_id,
            request.namespace.recipe_sha256,
            request.namespace.view,
            request.namespace.projection_version,
            demand.solution_evidence.base_analysis_run_id,
            demand.profile.profile_revision_id,
            demand.solution_evidence.solution_analysis_run_id,
            demand.encoding.encoding_sha256,
        )
        for demand in c.fixture.base.plan.demands
    )
    full_bindings = tuple(
        sorted(
            (
                source_binding(entry, view=request.namespace.view, space=request.space)
                for entry in c.current.entries
            ),
            key=lambda value: value.source.item_revision_id,
        )
    )
    existing_index = index_manifest(
        *full_bindings, view=request.namespace.view, space=request.space
    )
    current = SimpleNamespace(
        keys=keys,
        published=True,
        unavailable=False,
        previous=(index_pointer(existing_index), existing_index),
    )

    def current_lookup(gate, session, configuration):
        gate.authorize_scope(session, c.owner.registry_caller(request), query, configuration)
        return query if current.published else None

    def prepare(session, caller, actual_query, verifier):
        assert actual_query == query and verifier is c.owner.catalog
        c.source_authority.authorize_scope(session, caller, query, c.owner.configuration.registry)
        missing_ids = {key.item_revision_id for key in current.keys}
        bindings = (
            ()
            if current.unavailable
            else tuple(
                source_binding(entry, view=request.namespace.view, space=request.space)
                for entry in c.current.entries
                if entry.profile.source_basis.source.item_revision_id not in missing_ids
            )
        )
        return PreparedEmbeddingBindingLookup(
            MissingEmbeddingBindings(
                current.keys,
                tuple(
                    RegisteredEmbeddingRow(binding.encoding, binding.row_ref)
                    for binding in {
                        value.encoding.encoding_sha256: value for value in bindings
                    }.values()
                ),
                len(c.current.sources),
                0 if current.unavailable else len(c.current.entries),
            ),
            c.current,
            bindings,
        )

    monkeypatch.setattr(CatalogIndexingRegistrySourceAuthority, "current_lookup", current_lookup)
    monkeypatch.setattr(application, "prepare_missing_embedding_bindings", prepare)
    monkeypatch.setattr(
        c.owner.catalog,
        "resolve_indexing_namespace_predecessor",
        lambda session, caller, query: current.previous,
    )
    launcher = Mock(spec=FixedNativeIndexLauncher)
    executor = CatalogNativeEmbeddingExecutor(
        owner=c.owner,
        publisher=c.publisher,
        execution_backend=FixedCpuDocumentEmbeddingExecution(launcher),
        runtime_profile=c.fixture.policy.profiles[0],
        source_commit="a" * 40,
    )
    app = application.LocalEmbeddingServiceReconciliation(executor)
    return SimpleNamespace(source=c, current=current, app=app, launcher=launcher)


def counts(c):
    with c.source.publisher.sessions() as session:
        return tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (WorkflowInstanceRecord, WorkflowCommandRecord, JobRecord)
        )


def test_observation_replays_actual_plan_and_atomic_workflow_without_model(reconciliation):
    c = reconciliation
    before = counts(c)
    first, second = c.app.run_once(), c.app.run_once()
    assert first.state is ReconciliationState.QUEUED
    assert second.state is ReconciliationState.REPLAYED
    assert first.workflow_id == second.workflow_id and first.command_id == second.command_id
    assert first.missing_binding_count == first.selected_target_count == 2
    assert counts(c) == (1, 1, before[2] + 1)
    c.launcher.run.assert_not_called()
    with c.source.publisher.sessions() as session:
        workflow = session.get(WorkflowInstanceRecord, first.workflow_id)
        assert workflow.created_actor_type == "local_indexing_service"
        assert workflow.initial_request["schema_version"] == "local-embedding-workflow-request/1.2"
        assert workflow.created_actor_id == c.source.fixture.grant.service.service_id


def test_preparation_needs_no_numerical_executor_and_replays_the_original_plan(reconciliation):
    c = reconciliation
    before = counts(c)
    preparation = application.LocalEmbeddingServicePreparation(
        c.app.owner,
        c.source.publisher,
        c.app.executor.runtime_profile,
        source_commit=c.app.controls.source_commit,
    )
    c.launcher.reset_mock()
    first, replay = preparation.prepare_once(), preparation.prepare_once()
    assert first == replay and first.request is not None
    assert first.observed.state is ReconciliationState.PREPARED
    assert first.observed.workflow_id is None and first.observed.command_id is None
    assert counts(c) == (0, 0, before[2] + 1)
    assert c.launcher.mock_calls == []
    submitted = c.app.run_once()
    assert submitted.state is ReconciliationState.QUEUED
    assert counts(c) == (1, 1, before[2] + 1)
    with c.source.publisher.sessions() as session:
        workflow = session.get(WorkflowInstanceRecord, submitted.workflow_id)
        assert workflow.initial_request == first.request.model_dump(mode="json")


def test_revocation_between_preparation_and_start_is_not_cached_authority(
    reconciliation, monkeypatch
):
    c = reconciliation
    before = counts(c)
    prepare = c.app.preparation.prepare_once

    def revoke_after_preparation():
        value = prepare()
        c.source.deny = True
        return value

    monkeypatch.setattr(c.app.preparation, "prepare_once", revoke_after_preparation)
    with pytest.raises(ValueError, match="FORBIDDEN"):
        c.app.run_once()
    assert counts(c) == (0, 0, before[2] + 1)
    c.launcher.run.assert_not_called()


def test_preparation_rechecks_source_authority_after_immutable_plan_publication(
    reconciliation, monkeypatch
):
    c = reconciliation
    before = counts(c)
    publish = c.app.controls.publish_observed_source_plan

    def revoke_after_publish(*args, **kwargs):
        saved = publish(*args, **kwargs)
        c.source.deny = True
        return saved

    monkeypatch.setattr(c.app.controls, "publish_observed_source_plan", revoke_after_publish)
    with pytest.raises(ValueError, match="FORBIDDEN"):
        c.app.preparation.prepare_once()
    assert counts(c) == (0, 0, before[2] + 1)
    c.launcher.run.assert_not_called()


def test_matching_original_targets_does_not_reselect_the_current_missing_queue(reconciliation):
    c = reconciliation
    prepared = c.app.preparation.prepare_once()
    assert prepared.request is not None
    c.current.keys = ()
    assert c.app.preparation.prepare_once().request is None
    matched = c.app.preparation.prepare_matching(c.app.preparation, prepared.request)
    assert matched == prepared.request
    c.launcher.run.assert_not_called()


def test_matching_original_selection_still_rechecks_current_source_authority(reconciliation):
    c = reconciliation
    prepared = c.app.preparation.prepare_once()
    assert prepared.request is not None
    before = counts(c)
    c.source.deny = True
    with pytest.raises(ValueError, match="FORBIDDEN"):
        c.app.preparation.prepare_matching(c.app.preparation, prepared.request)
    assert counts(c) == before
    c.launcher.run.assert_not_called()


def test_bounded_targets_are_stable_and_exclude_already_bound_sources(reconciliation):
    c = reconciliation
    c.current.keys = c.current.keys[1:]
    binding = source_binding(
        c.source.current.entries[0],
        view=c.source.scope.request.namespace.view,
        space=c.source.scope.request.space,
    )
    partial = index_manifest(binding, view=binding.view, space=c.source.scope.request.space)
    c.current.previous = index_pointer(partial), partial
    c.app.maximum_targets = 1
    result = c.app.run_once()
    assert result.missing_binding_count == result.selected_target_count == 1
    assert result.index_refresh_reason is None
    with c.source.publisher.sessions() as session:
        workflow = session.get(WorkflowInstanceRecord, result.workflow_id)
        assert workflow.initial_request["schema_version"] == "local-embedding-workflow-request/1.2"
        plan_pointer = workflow.initial_request["source_plan"]
        revision = session.get(ArtifactRevisionRecord, plan_pointer["artifact_revision_id"])
        assert revision is not None
        actual = c.source.owner.resolve_submission(
            session,
            parse_local_embedding_executable_request(workflow.initial_request),
        )
        assert tuple(source.item_revision_id for source in actual.plan.sources) == (
            c.current.keys[0].item_revision_id,
        )


def test_partial_new_namespace_refresh_precedes_missing_vector_seed(reconciliation):
    c = reconciliation
    c.current.keys, c.current.previous = c.current.keys[1:], None
    observed = c.app.run_once()
    assert observed.state is ReconciliationState.QUEUED
    assert observed.missing_binding_count == observed.selected_target_count == 1
    assert observed.index_refresh_reason == "MISSING_NAMESPACE_INDEX"
    with c.source.publisher.sessions() as session:
        workflow = session.get(WorkflowInstanceRecord, observed.workflow_id)
        request = parse_local_embedding_executable_request(workflow.initial_request)
        assert request.schema_version == "local-embedding-workflow-request/1.3"
        assert request.reconciliation_basis.eligible_source_count == 2
        assert request.reconciliation_basis.available_binding_count == 1
        scope = c.source.owner.resolve_submission(session, request)
        assert scope.plan.sources[0].item_revision_id != c.current.keys[0].item_revision_id
    c.launcher.run.assert_not_called()


@pytest.mark.parametrize("kind", ["complete", "report", "view", "empty", "no_graph"])
def test_no_missing_work_does_not_create_jobs_or_empty_artifacts(reconciliation, kind):
    c = reconciliation
    c.current.keys = ()
    if kind in {"report", "empty"}:
        c.source.current = replace(c.source.current, entries=())
    if kind == "empty":
        c.source.current = replace(c.source.current, sources=())
    if kind == "no_graph":
        c.current.published = False
    if kind == "view":
        c.current.unavailable = True
    before = counts(c)
    result = c.app.run_once()
    assert (
        result.state
        is {
            "complete": ReconciliationState.UP_TO_DATE,
            "report": ReconciliationState.WAITING_FOR_SOLUTION_REPORT,
            "view": ReconciliationState.VIEW_UNAVAILABLE,
            "empty": ReconciliationState.NO_ELIGIBLE_SOURCE,
            "no_graph": ReconciliationState.NO_PUBLISHED_GRAPH,
        }[kind]
    )
    assert result.workflow_id is None and counts(c) == before
    if kind == "report":
        assert len(result.missing_report_revision_ids) == 2


def test_revocation_denies_even_noop_and_does_not_invent_success(reconciliation):
    c = reconciliation
    c.current.keys = ()
    c.source.deny = True
    before = counts(c)
    with pytest.raises(ValueError, match="FORBIDDEN"):
        c.app.run_once()
    assert counts(c) == before


@pytest.mark.parametrize("kind", ["missing", "withdrawal"])
def test_registered_bindings_refresh_missing_or_changed_namespace_without_model(
    reconciliation, kind
):
    c = reconciliation
    c.current.keys = ()
    if kind == "missing":
        c.current.previous = None
    else:
        c.source.current = replace(
            c.source.current,
            sources=c.source.current.sources[:1],
            entries=c.source.current.entries[:1],
        )
    before = counts(c)
    first, second = c.app.run_once(), c.app.run_once()
    assert first.state is ReconciliationState.QUEUED
    assert second.state is ReconciliationState.REPLAYED
    assert first.workflow_id == second.workflow_id and first.command_id == second.command_id
    assert first.index_refresh_reason == (
        "MISSING_NAMESPACE_INDEX" if kind == "missing" else "INDEX_MEMBERSHIP_CHANGED"
    )
    assert first.missing_binding_count == 0 and first.selected_target_count == 1
    assert first.reusable_encoding_count > 0
    assert counts(c) == (1, 1, before[2] + 1)
    with c.source.publisher.sessions() as session:
        workflow = session.get(WorkflowInstanceRecord, first.workflow_id)
        request = parse_local_embedding_executable_request(workflow.initial_request)
        assert request.schema_version == "local-embedding-workflow-request/1.3"
        basis = request.reconciliation_basis
        assert (
            basis.eligible_source_count
            == basis.available_binding_count
            == (2 if kind == "missing" else 1)
        )
        assert (basis.previous_index_manifest is None) is (kind == "missing")
    c.launcher.run.assert_not_called()


def test_same_witness_plan_but_new_membership_is_not_old_success_equivalent(reconciliation):
    """Terminal fixtures are synthetic; no production state is repaired."""
    c = reconciliation
    c.current.keys, c.current.previous = (), None
    first = c.app.run_once()
    with c.source.publisher.sessions.begin() as session:
        workflow = session.get(WorkflowInstanceRecord, first.workflow_id)
        command = session.get(WorkflowCommandRecord, first.command_id)
        workflow.state, command.state = "COMPLETED", "SUCCEEDED"
        old_plan = workflow.initial_request["source_plan"]
    c.source.current = replace(
        c.source.current,
        sources=c.source.current.sources[:1],
        entries=c.source.current.entries[:1],
    )
    second = c.app.run_once()
    assert second.state is ReconciliationState.QUEUED
    assert first.workflow_id != second.workflow_id and first.command_id != second.command_id
    with c.source.publisher.sessions() as session:
        workflow = session.get(WorkflowInstanceRecord, second.workflow_id)
        assert workflow.initial_request["source_plan"] == old_plan
        assert workflow.initial_request["reconciliation_basis"]["eligible_source_count"] == 1
        assert session.get(WorkflowInstanceRecord, first.workflow_id).state == "COMPLETED"
    c.launcher.run.assert_not_called()


def test_missing_head_still_requires_current_permission_and_leaves_no_work(reconciliation):
    c = reconciliation
    c.current.keys, c.current.previous, c.source.deny = (), None, True
    before = counts(c)
    with pytest.raises(ValueError, match="FORBIDDEN"):
        c.app.run_once()
    assert counts(c) == before
    c.launcher.run.assert_not_called()


def test_accepted_report_arrival_becomes_new_work_without_fake_coverage(reconciliation):
    c = reconciliation
    original_lookup, original_keys = c.source.current, c.current.keys
    c.source.current = replace(original_lookup, entries=())
    c.current.keys = ()
    before = counts(c)
    waiting = c.app.run_once()
    assert waiting.state is ReconciliationState.WAITING_FOR_SOLUTION_REPORT
    assert counts(c) == before
    c.source.current, c.current.keys = original_lookup, original_keys
    assert c.app.run_once().state is ReconciliationState.QUEUED
    assert counts(c) == (1, 1, before[2] + 1)


def test_late_revocation_after_plan_commit_prevents_submission(reconciliation, monkeypatch):
    c = reconciliation
    publish = c.app.controls.publish_observed_source_plan

    def revoke_after_publish(*args, **kwargs):
        value = publish(*args, **kwargs)
        c.source.deny = True
        return value

    monkeypatch.setattr(c.app.controls, "publish_observed_source_plan", revoke_after_publish)
    before = counts(c)
    with pytest.raises(ValueError, match="FORBIDDEN"):
        c.app.run_once()
    assert counts(c) == (0, 0, before[2] + 1)
    c.launcher.run.assert_not_called()


def test_plan_survives_failure_before_submission_and_retry_reuses_it(reconciliation, monkeypatch):
    c = reconciliation
    original = application.start_local_embedding_in_session

    def fail_before_start(*args, **kwargs):
        raise RuntimeError("synthetic before native submission")

    monkeypatch.setattr(application, "start_local_embedding_in_session", fail_before_start)
    before = counts(c)
    with pytest.raises(RuntimeError, match="before native"):
        c.app.run_once()
    assert counts(c) == (0, 0, before[2] + 1)
    monkeypatch.setattr(application, "start_local_embedding_in_session", original)
    assert c.app.run_once().state is ReconciliationState.QUEUED
    assert counts(c) == (1, 1, before[2] + 1)


@pytest.mark.parametrize("refresh", [False, True])
def test_terminal_failed_history_is_returned_not_replaced(reconciliation, refresh):
    c = reconciliation
    if refresh:
        c.current.keys, c.current.previous = (), None
    first = c.app.run_once()
    # Unit-only terminal-state fixture; no production/history repair operation.
    with c.source.publisher.sessions.begin() as session:
        session.get(WorkflowInstanceRecord, first.workflow_id).state = "FAILED"
        session.get(WorkflowCommandRecord, first.command_id).state = "FAILED"
    before = counts(c)
    same = c.app.run_once()
    assert same.state is ReconciliationState.TERMINAL_INCOMPLETE
    assert same.workflow_id == first.workflow_id and same.command_id == first.command_id
    assert same.workflow_state == same.command_state == "FAILED"
    assert counts(c) == before


def test_new_key_does_not_bypass_successful_equivalence_for_same_original_intent(reconciliation):
    """Actual SQLite Runner reuse; terminal fixtures are synthetic, not production repair."""
    c = reconciliation
    first = c.app.run_once()
    with c.source.publisher.sessions.begin() as session:
        workflow = session.get(WorkflowInstanceRecord, first.workflow_id)
        command = session.get(WorkflowCommandRecord, first.command_id)
        assert workflow is not None and command is not None
        workflow.state = "COMPLETED"
        command.state = "SUCCEEDED"
    before = counts(c)
    with c.source.publisher.sessions.begin() as session:
        workflow = session.get(WorkflowInstanceRecord, first.workflow_id)
        assert workflow is not None
        definition = session.get(WorkflowDefinitionRecord, workflow.definition_id)
        assert definition is not None
        result = application.start_local_embedding_in_session(
            session,
            definition=definition,
            request=parse_local_embedding_executable_request(workflow.initial_request),
            idempotency_key="synthetic-new-key-must-not-rerun-success",
            actor_type=workflow.created_actor_type,
            actor_id=workflow.created_actor_id,
            owner=c.app.owner,
            executor=c.app.executor,
        )
        assert isinstance(result, application.LocalEmbeddingWorkflowSubmitted)
        assert result.workflow.workflow_id == first.workflow_id
        assert result.command.command_id == first.command_id
        assert not result.workflow_created and not result.command_created
    assert counts(c) == before
    c.launcher.run.assert_not_called()


@pytest.mark.parametrize("limit", [0, -1, True, 1025])
def test_reconciliation_limit_is_typed_and_bounded(reconciliation, limit):
    with pytest.raises(ValueError, match="CONFIGURATION_INVALID"):
        application.LocalEmbeddingServiceReconciliation(
            reconciliation.app.executor, maximum_targets=limit
        )
