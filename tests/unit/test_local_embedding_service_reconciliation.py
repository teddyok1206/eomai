"""Actual local control/Workflow persistence; explicitly synthetic Catalog/IAM.

SQLite is not PostgreSQL concurrency or service-runtime proof. No model is run.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest
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
from eom_workflow_runner import local_embedding_service_reconciliation as application
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
    current = SimpleNamespace(keys=keys, published=True, unavailable=False)

    def current_lookup(gate, session, configuration):
        gate.authorize_scope(session, c.owner.registry_caller(request), query, configuration)
        return query if current.published else None

    def prepare(session, caller, actual_query, verifier):
        assert actual_query == query and verifier is c.owner.catalog
        c.source_authority.authorize_scope(session, caller, query, c.owner.configuration.registry)
        return PreparedEmbeddingBindingLookup(
            MissingEmbeddingBindings(
                current.keys,
                (),
                len(c.current.sources),
                0 if current.unavailable else len(c.current.entries),
            ),
            c.current,
        )

    monkeypatch.setattr(CatalogIndexingRegistrySourceAuthority, "current_lookup", current_lookup)
    monkeypatch.setattr(application, "prepare_missing_embedding_bindings", prepare)
    launcher = Mock(spec=FixedNativeIndexLauncher)
    executor = CatalogNativeEmbeddingExecutor(
        owner=c.owner,
        publisher=c.publisher,
        launcher=launcher,
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


def test_bounded_targets_are_stable_and_exclude_already_bound_sources(reconciliation):
    c = reconciliation
    c.current.keys = c.current.keys[1:]
    c.app.maximum_targets = 1
    result = c.app.run_once()
    assert result.missing_binding_count == result.selected_target_count == 1
    with c.source.publisher.sessions() as session:
        workflow = session.get(WorkflowInstanceRecord, result.workflow_id)
        plan_pointer = workflow.initial_request["source_plan"]
        revision = session.get(ArtifactRevisionRecord, plan_pointer["artifact_revision_id"])
        assert revision is not None
        actual = c.source.owner.resolve_submission(
            session,
            application.parse_local_embedding_service_workflow_request(workflow.initial_request),
        )
        assert tuple(source.item_revision_id for source in actual.plan.sources) == (
            c.current.keys[0].item_revision_id,
        )


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


def test_terminal_failed_history_is_returned_not_replaced(reconciliation):
    c = reconciliation
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


@pytest.mark.parametrize("limit", [0, -1, True, 1025])
def test_reconciliation_limit_is_typed_and_bounded(reconciliation, limit):
    with pytest.raises(ValueError, match="CONFIGURATION_INVALID"):
        application.LocalEmbeddingServiceReconciliation(
            reconciliation.app.executor, maximum_targets=limit
        )
