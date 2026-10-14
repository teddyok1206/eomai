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
)
from eom_catalog_service.settings import CatalogSettings
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.local_embedding_control_artifacts import (
    LocalEmbeddingControlArtifactPublisher,
)
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_orchestrator.native_embedding_index_systemd import FixedNativeIndexLauncher
from eom_workflow_runner import local_embedding_service_reconciliation as application
from eom_workflow_runner.local_embedding_native_executor import CatalogNativeEmbeddingExecutor
from eom_workflow_runner.local_embedding_owner_admission import (
    CatalogLocalEmbeddingOwnerAdmission,
    LocalEmbeddingOwnerConfiguration,
)
from eom_workflow_runner.local_embedding_service_reconciliation import ReconciliationState
from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowInstanceRecord
from eom_workflow_runner.repository import import_workflow_definition
from sqlalchemy import select

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
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

    def prepare(session, supplied_caller, selected, verifier):
        assert verifier is owner.catalog
        authorize(session, supplied_caller, selected)
        return PreparedEmbeddingBindingLookup(
            MissingEmbeddingBindings(keys, (), len(c.current.sources), len(keys)), c.current
        )

    monkeypatch.setattr(owner.catalog, "authorize_scope", authorize)
    monkeypatch.setattr(owner.catalog, "resolve_lookup", lookup)
    monkeypatch.setattr(CatalogIndexingRegistrySourceAuthority, "current_lookup", current_lookup)
    monkeypatch.setattr(application, "prepare_missing_embedding_bindings", prepare)
    _scope, compiled = scope_fixture()
    with publisher.sessions.begin() as session:
        import_workflow_definition(session, compiled)
    launcher = Mock(spec=FixedNativeIndexLauncher)
    executor = CatalogNativeEmbeddingExecutor(
        owner=owner,
        publisher=publisher,
        launcher=launcher,
        runtime_profile=c.fixture.policy.profiles[0],
        source_commit=source_commit,
    )
    app = application.LocalEmbeddingServiceReconciliation(executor)
    return SimpleNamespace(app=app, publisher=publisher, launcher=launcher, source=c)


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
