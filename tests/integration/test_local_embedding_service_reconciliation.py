"""Actual guarded publication/submission SQL; deliberately synthetic IAM/population.

No installed service authentication, genuine source admission or model is claimed.
The shared service-owner fixture uses local temporary files, never production NAS.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from eom_catalog_service.embedding_registry_indexing_authority import (
    CatalogIndexingRegistrySourceAuthority,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingBindingLookupKey,
    EmbeddingRegistryLookup,
    MissingEmbeddingBindings,
    PreparedEmbeddingBindingLookup,
    SelectedEmbeddingSources,
)
from eom_catalog_service.settings import CatalogSettings
from eom_operator_identity import LocalIndexingServiceReference
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.local_embedding_control_artifacts import (
    LocalEmbeddingControlArtifactPublisher,
)
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_orchestrator.native_embedding_index_systemd import FixedNativeIndexLauncher
from eom_workflow_runner import local_embedding_service_reconciliation as application
from eom_workflow_runner.document_embedding_cpu_execution import FixedCpuDocumentEmbeddingExecution
from eom_workflow_runner.local_embedding_native_executor import CatalogNativeEmbeddingExecutor
from eom_workflow_runner.local_embedding_owner_admission import (
    CatalogLocalEmbeddingOwnerAdmission,
    LocalEmbeddingOwnerConfiguration,
)
from eom_workflow_runner.local_embedding_service_reconciliation import ReconciliationState
from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowInstanceRecord
from eom_workflow_runner.repository import (
    CommandExecutionFamily,
    NativeCommandActorSelection,
    claim_command_candidate,
    import_workflow_definition,
    peek_command_candidate,
)
from sqlalchemy import event, select

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import source_binding
from tests.unit.test_local_embedding_control_artifacts import NOW
from tests.unit.test_local_embedding_runner_admission import scope_fixture
from tests.unit.test_local_embedding_service_owner import service_owner as service_owner
from tests.unit.test_local_indexing_runtime_admission import installed as installed
from tests.unit.test_postgres_local_indexing_fence import case as case

pytestmark = pytest.mark.integration


@pytest.fixture
def reconciliation(guarded_engine, service_owner, tmp_path, monkeypatch):
    c = service_owner
    settings = replace(c.publisher.settings, staging_root=tmp_path / "postgres-staging")
    publisher = ControlFileSetPublisher(guarded_engine, settings)
    # Test-only provenance isolates retained cohorts without deleting history.
    source_commit = uuid4().hex + "a" * 8
    controls = LocalEmbeddingControlArtifactPublisher(publisher, source_commit=source_commit)
    saved_policy = controls.publish_service_policy(
        c.fixture.policy, idempotency_key="test-service-policy:" + uuid4().hex, created_at=NOW
    )
    owner = CatalogLocalEmbeddingOwnerAdmission.for_indexing_service(
        guarded_engine,
        LocalEmbeddingOwnerConfiguration(
            c.owner.configuration.registry, saved_policy.member, saved_policy.semantic_sha256
        ),
        source_authority=c.source_authority,
        settings=CatalogSettings(nas_artifact_root=settings.nas_artifact_root),
    )
    request = c.scope.request
    caller = owner.registry_caller(request)
    query = EmbeddingRegistryLookup(
        request.corpus_id,
        request.namespace,
        request.graph_snapshot,
        request.access_policy_revision_id,
        request.access_policy_sha256,
    )

    def authorize(session, supplied_caller, selected):
        return c.source_authority.authorize_scope(
            session, supplied_caller, selected, owner.configuration.registry
        )

    def lookup(session, supplied_caller, selected):
        authorize(session, supplied_caller, selected)
        return c.current

    def selected_lookup(session, supplied_caller, selected):
        assert type(selected) is SelectedEmbeddingSources
        selected.__post_init__()
        authorize(session, supplied_caller, selected.scope)
        targets = set(selected.source_revision_ids)
        assert targets.issubset(source.item_revision_id for source in c.current.sources)
        return replace(
            c.current,
            sources=tuple(s for s in c.current.sources if s.item_revision_id in targets),
            entries=tuple(
                e
                for e in c.current.entries
                if e.profile.source_basis.source.item_revision_id in targets
            ),
        )

    def current_lookup(gate, session, configuration):
        gate.authorize_scope(session, caller, query, configuration)
        return query

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
    observation = SimpleNamespace(missing=keys, previous=None)

    def prepare(session, supplied_caller, selected, verifier):
        assert verifier is owner.catalog
        authorize(session, supplied_caller, selected)
        missing_ids = {key.item_revision_id for key in observation.missing}
        return PreparedEmbeddingBindingLookup(
            MissingEmbeddingBindings(observation.missing, (), len(c.current.sources), len(keys)),
            c.current,
            tuple(
                source_binding(entry, view=request.namespace.view, space=request.space)
                for entry in c.current.entries
                if entry.profile.source_basis.source.item_revision_id not in missing_ids
            ),
        )

    def predecessor(session, supplied_caller, selected):
        authorize(session, supplied_caller, selected)
        return observation.previous

    monkeypatch.setattr(owner.catalog, "authorize_scope", authorize)
    monkeypatch.setattr(owner.catalog, "resolve_lookup", lookup)
    monkeypatch.setattr(owner.catalog, "resolve_selected_sources", selected_lookup)
    monkeypatch.setattr(CatalogIndexingRegistrySourceAuthority, "current_lookup", current_lookup)
    monkeypatch.setattr(application, "prepare_missing_embedding_bindings", prepare)
    monkeypatch.setattr(owner.catalog, "resolve_indexing_namespace_predecessor", predecessor)
    _scope, compiled = scope_fixture()
    with publisher.sessions.begin() as session:
        import_workflow_definition(session, compiled)
    launcher = Mock(spec=FixedNativeIndexLauncher)
    executor = CatalogNativeEmbeddingExecutor(
        owner=owner,
        publisher=publisher,
        execution_backend=FixedCpuDocumentEmbeddingExecution(launcher),
        runtime_profile=c.fixture.policy.profiles[0],
        source_commit=source_commit,
    )
    app = application.LocalEmbeddingServiceReconciliation(executor)
    return SimpleNamespace(
        app=app, publisher=publisher, launcher=launcher, source=c, observation=observation
    )


def test_actual_independent_roots_reconcile_one_workflow_and_start(reconciliation):
    c = reconciliation
    barrier = Barrier(2)

    def run(_ordinal):
        barrier.wait(timeout=30)
        return c.app.run_once()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = tuple(pool.map(run, range(2)))
    assert {first.state, second.state} == {ReconciliationState.QUEUED, ReconciliationState.REPLAYED}
    assert first.workflow_id == second.workflow_id and first.command_id == second.command_id
    with c.publisher.sessions() as session:
        workflow = session.get(WorkflowInstanceRecord, first.workflow_id)
        commands = tuple(
            session.scalars(
                select(WorkflowCommandRecord).where(
                    WorkflowCommandRecord.workflow_id == first.workflow_id
                )
            )
        )
        assert workflow.created_actor_type == "local_indexing_service"
        assert len(commands) == 1 and commands[0].command_id == first.command_id
    c.launcher.run.assert_not_called()


def test_actual_prepared_pointer_survives_stop_but_cannot_cache_source_authority(
    reconciliation, monkeypatch
):
    c = reconciliation
    first = c.app.preparation.prepare_once()
    assert first.request is not None and first.observed.state is ReconciliationState.PREPARED
    key = "local-embedding-reconcile:" + first.request.request_sha256.removeprefix("sha256:")
    pointer = first.request.source_plan
    with c.publisher.sessions() as session:
        assert (
            session.scalar(
                select(WorkflowInstanceRecord).where(WorkflowInstanceRecord.idempotency_key == key)
            )
            is None
        )
        revision = session.get(ArtifactRevisionRecord, pointer.artifact_revision_id)
        assert revision is not None
        assert session.get(JobRecord, revision.job_id).status == "SUCCEEDED"
    assert c.app.preparation.prepare_once() == first
    # Simulate retaining only the immutable request after a stop, not a live grant.
    monkeypatch.setattr(c.app.preparation, "prepare_once", lambda: first)
    c.source.deny = True
    with pytest.raises(ValueError, match="FORBIDDEN"):
        c.app.run_once()
    with c.publisher.sessions() as session:
        assert (
            session.scalar(
                select(WorkflowInstanceRecord).where(WorkflowInstanceRecord.idempotency_key == key)
            )
            is None
        )
        assert session.get(ArtifactRevisionRecord, pointer.artifact_revision_id) is not None
    c.source.deny = False
    submitted, replay = c.app.run_once(), c.app.run_once()
    assert submitted.state is ReconciliationState.QUEUED
    assert replay.state is ReconciliationState.REPLAYED
    assert submitted.workflow_id == replay.workflow_id
    with c.publisher.sessions() as session:
        workflow = session.get(WorkflowInstanceRecord, submitted.workflow_id)
        assert workflow.initial_request == first.request.model_dump(mode="json")
    c.launcher.run.assert_not_called()


@pytest.mark.parametrize("partial", [False, True])
def test_actual_independent_roots_submit_one_metadata_refresh_without_encoding(
    reconciliation, partial
):
    c = reconciliation
    c.observation.missing = c.observation.missing[1:] if partial else ()
    barrier = Barrier(2)

    def run(_ordinal):
        barrier.wait(timeout=30)
        return c.app.run_once()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = tuple(pool.map(run, range(2)))
    assert {first.state, second.state} == {ReconciliationState.QUEUED, ReconciliationState.REPLAYED}
    assert first.workflow_id == second.workflow_id and first.command_id == second.command_id
    assert first.missing_binding_count == second.missing_binding_count == (1 if partial else 0)
    assert first.index_refresh_reason == second.index_refresh_reason == "MISSING_NAMESPACE_INDEX"
    with c.publisher.sessions() as session:
        workflow = session.get(WorkflowInstanceRecord, first.workflow_id)
        assert workflow.initial_request["schema_version"] == "local-embedding-workflow-request/1.3"
        selected = peek_command_candidate(
            session,
            family=CommandExecutionFamily.LOCAL_EMBEDDING,
            workflow_id=workflow.workflow_id,
            actor_selection=NativeCommandActorSelection(
                "local_indexing_service",
                workflow.created_actor_id,
                c.source.scope.request.namespace,
            ),
        )
        assert selected is not None and selected.command_id == first.command_id
    c.launcher.run.assert_not_called()


def test_actual_exact_service_revision_preserves_other_pending_work_and_claims_once(reconciliation):
    c = reconciliation
    submitted = c.app.run_once()
    request = c.source.scope.request
    audit = request.actor_context
    reference = LocalIndexingServiceReference(
        service_id=audit.service_id,
        service_revision_id=audit.service_revision_id,
        service_identity_sha256=audit.service_identity_sha256,
    )
    selected = NativeCommandActorSelection(
        "local_indexing_service", reference.service_id, request.namespace, reference
    )
    statements = []

    def capture(_connection, _cursor, statement, parameters, _context, _many):
        statements.append((statement, parameters))

    event.listen(c.publisher.engine, "before_cursor_execute", capture)
    try:
        with c.publisher.sessions() as session:
            for changed in (
                {"service_revision_id": "localindexservicerev_" + uuid4().hex},
                {"service_identity_sha256": "sha256:" + uuid4().hex * 2},
            ):
                assert (
                    peek_command_candidate(
                        session,
                        family=CommandExecutionFamily.LOCAL_EMBEDDING,
                        workflow_id=submitted.workflow_id,
                        actor_selection=replace(
                            selected, service=reference.model_copy(update=changed)
                        ),
                    )
                    is None
                )
            original = peek_command_candidate(
                session,
                family=CommandExecutionFamily.LOCAL_EMBEDDING,
                workflow_id=submitted.workflow_id,
                actor_selection=selected,
            )
            assert original is not None and original.command_id == submitted.command_id
    finally:
        event.remove(c.publisher.engine, "before_cursor_execute", capture)
    assert len(statements) == 3
    with c.publisher.engine.connect() as connection:
        for statement, parameters in statements:
            plan = connection.exec_driver_sql(
                "EXPLAIN (FORMAT JSON) " + statement, parameters
            ).scalar_one()
            assert plan[0]["Plan"]["Node Type"] == "Limit"
            assert "workflow_events" not in statement

    gate = Barrier(2)

    def claim(ordinal):
        with c.publisher.sessions.begin() as session:
            candidate = peek_command_candidate(
                session,
                family=CommandExecutionFamily.LOCAL_EMBEDDING,
                workflow_id=submitted.workflow_id,
                actor_selection=selected,
            )
            assert candidate == original
            gate.wait(timeout=30)
            command = claim_command_candidate(
                session,
                candidate,
                runner_id="revision-test-" + str(ordinal),
                lease_seconds=60,
                local_embedding_owner=c.app.executor.owner,
                local_embedding_executor=c.app.executor,
            )
            return None if command is None else command.command_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(claim, range(2)))
    assert sorted(results, key=lambda value: value or "") == [None, submitted.command_id]
    with c.publisher.sessions() as session:
        command = session.get(WorkflowCommandRecord, submitted.command_id)
        assert command.state == "LEASED" and command.attempts == command.lease_generation == 1
    c.launcher.run.assert_not_called()


def test_actual_bounded_submission_revalidates_only_its_selected_targets(reconciliation):
    c = reconciliation
    app = application.LocalEmbeddingServiceReconciliation(c.app.executor, maximum_targets=1)
    result = app.run_once()
    assert result.state is ReconciliationState.QUEUED
    assert result.eligible_source_count == 2 and result.selected_target_count == 1
    assert app.run_once().state is ReconciliationState.REPLAYED
    c.launcher.run.assert_not_called()


def test_actual_service_namespace_queue_selection_cannot_take_another_view(reconciliation):
    c = reconciliation
    result = c.app.run_once()
    request = c.source.scope.request
    namespace = request.namespace
    other = namespace.model_copy(
        update={"view": "METADATA_ONLY" if namespace.view != "METADATA_ONLY" else "CONTENT_ONLY"}
    )
    statements = []

    def capture(_connection, _cursor, statement, parameters, _context, _many):
        statements.append((statement, parameters))

    event.listen(c.publisher.engine, "before_cursor_execute", capture)
    try:
        with c.publisher.sessions() as session:
            for selected_namespace, expected in ((namespace, True), (other, False)):
                selected = peek_command_candidate(
                    session,
                    family=CommandExecutionFamily.LOCAL_EMBEDDING,
                    # Retained synthetic cohorts deliberately reuse one service
                    # ID. Scope this assertion to its immutable Workflow rather
                    # than deleting old pending test evidence to change FIFO.
                    workflow_id=result.workflow_id,
                    actor_selection=NativeCommandActorSelection(
                        "local_indexing_service",
                        request.actor_context.service_id,
                        selected_namespace,
                    ),
                )
                assert (selected is not None) is expected
                if selected is not None:
                    assert selected.command_id == result.command_id
    finally:
        event.remove(c.publisher.engine, "before_cursor_execute", capture)
    assert len(statements) == 2
    with c.publisher.engine.connect() as connection:
        for statement, parameters in statements:
            plan = connection.exec_driver_sql(
                "EXPLAIN (FORMAT JSON) " + statement, parameters
            ).scalar_one()
            assert plan[0]["Plan"]["Node Type"] == "Limit"
            assert "initial_request" in statement and "workflow_events" not in statement
    with c.publisher.sessions() as session:
        command = session.get(WorkflowCommandRecord, result.command_id)
        assert command.state == "PENDING" and command.attempts == 0
    c.launcher.run.assert_not_called()


def test_actual_submission_root_rollback_keeps_plan_and_replays_same_control(
    reconciliation, monkeypatch
):
    c = reconciliation
    original = application.start_local_embedding_in_session
    observed = []

    def fail_after_savepoint(*args, **kwargs):
        result = original(*args, **kwargs)
        observed.append(
            (
                result.workflow.workflow_id,
                result.command.command_id,
                result.workflow.initial_request["source_plan"]["artifact_revision_id"],
            )
        )
        raise RuntimeError("synthetic after actual submission savepoint")

    monkeypatch.setattr(application, "start_local_embedding_in_session", fail_after_savepoint)
    with pytest.raises(RuntimeError, match="savepoint"):
        c.app.run_once()
    with c.publisher.sessions() as session:
        assert session.get(WorkflowInstanceRecord, observed[0][0]) is None
        assert session.get(WorkflowCommandRecord, observed[0][1]) is None
        revision = session.get(ArtifactRevisionRecord, observed[0][2])
        saved_plan = session.get(JobRecord, revision.job_id)
        assert saved_plan.status == "SUCCEEDED"
        assert saved_plan.request["source_commit"] == c.app.controls.source_commit
        original_plan_id = saved_plan.job_id
    monkeypatch.setattr(application, "start_local_embedding_in_session", original)
    started = c.app.run_once()
    assert started.state is ReconciliationState.QUEUED
    assert c.app.run_once().state is ReconciliationState.REPLAYED
    with c.publisher.sessions() as session:
        assert session.get(JobRecord, original_plan_id).status == "SUCCEEDED"
        workflow = session.get(WorkflowInstanceRecord, started.workflow_id)
        assert workflow.initial_request["source_plan"]["artifact_revision_id"] == observed[0][2]
    c.launcher.run.assert_not_called()
