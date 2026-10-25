"""Actual PG selection/publication replay with explicitly synthetic IAM/source/index leaves."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock
from uuid import uuid4

import pytest
from eom_orchestrator.embedding_batch_plan_store import EmbeddingBatchPlanStore
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.models import JobRecord
from eom_orchestrator.settings import Settings
from eom_workflow.reference_query_routed_preparation import routed_reference_query_preparation_key
from eom_workflow_runner.reference_query_prepare_application import NativeReferenceQueryPreparation
from eom_workflow_runner.reference_query_routed_execution import (
    drive_routed_reference_queries_once,
    observe_routed_reference_queries,
)
from eom_workflow_runner.reference_query_routed_runtime import RoutedReferenceQuerySession
from sqlalchemy import select

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.test_reference_query_owner_admission import source as source
from tests.unit.test_reference_query_routed_owner_configuration import selected as selected
from tests.unit.test_reference_query_routed_selection import selection_case

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def routed(guarded_engine, tmp_path, monkeypatch, selected):
    artifact_root = tmp_path / "pg-artifacts"
    artifact_root.mkdir(mode=0o700)
    publisher = ControlFileSetPublisher(
        guarded_engine,
        Settings(
            staging_root=tmp_path / "pg-staging",
            workspace_root=tmp_path,
            nas_artifact_root=artifact_root,
        ),
    )
    return selection_case(tmp_path, monkeypatch, selected, publisher=publisher)


def test_concurrent_same_intent_returns_same_pins_without_allocation_or_model(routed):
    key, barrier = "pg-routed-functional:" + uuid4().hex, Barrier(2)

    def prepare():
        barrier.wait(timeout=10)
        return routed.app.prepare(routed.requests, idempotency_key=key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        one, two = tuple(pool.map(lambda _ordinal: prepare(), range(2)))
    assert one.manifest == two.manifest
    assert one.preparation == two.preparation and one.selection == two.selection
    with routed.publisher.sessions.begin() as session:
        original = routed_reference_query_preparation_key(
            routed.owners[0].identity.capture.operator_id, key
        )
        rows = tuple(
            session.scalars(select(JobRecord).where(JobRecord.idempotency_key == original))
        )
        assert len(rows) == 1 and rows[0].status == "SUCCEEDED"
        assert not session.scalar(
            select(JobRecord.job_id)
            .where(
                JobRecord.task_type == "embedding_batch_plan",
                JobRecord.request["batch_id"].astext == one.preparation.parent.batch_id,
            )
            .limit(1)
        )


def test_interrupted_selection_publication_survives_restart_then_current_denial(
    routed, monkeypatch
):
    key = "pg-routed-functional:" + uuid4().hex
    publish = routed.app.controls.publish_routed_reference_query_preparation
    monkeypatch.setattr(
        routed.app.controls,
        "publish_routed_reference_query_preparation",
        Mock(side_effect=RuntimeError("synthetic interruption")),
    )
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        routed.app.prepare(routed.requests, idempotency_key=key)
    monkeypatch.setattr(routed.app.controls, "publish_routed_reference_query_preparation", publish)
    for owner in routed.owners:
        monkeypatch.setattr(
            owner.catalog,
            "prepare_reference_query_context_in_session",
            Mock(side_effect=AssertionError("no new mutable head lookup after restart")),
        )
    first = routed.app.prepare(routed.requests, idempotency_key=key)
    assert routed.app.prepare(routed.requests, idempotency_key=key).manifest == first.manifest
    routed.deny = True
    with pytest.raises(ValueError, match="SYNTHETIC_ACTUAL_SOURCE_DENIED"):
        routed.app.prepare(routed.requests, idempotency_key=key)
    with routed.publisher.sessions.begin() as session:
        original = routed_reference_query_preparation_key(
            routed.owners[0].identity.capture.operator_id, key
        )
        assert (
            session.scalar(select(JobRecord.status).where(JobRecord.idempotency_key == original))
            == "SUCCEEDED"
        )


def routed_session(value):
    cpu = Mock(spec=NativeReferenceQueryPreparation)
    cpu.owner = value.app.cpu
    return RoutedReferenceQuerySession(cpu, value.app)


def test_original_preparation_without_workflow_is_truthfully_pending_in_postgres(routed):
    prepared = routed.app.prepare(routed.requests, idempotency_key="pg-routed-read:" + uuid4().hex)
    observed = observe_routed_reference_queries(routed_session(routed), prepared)
    assert observed.state == "PENDING" and observed.device is None
    assert len(observed.children) == len(routed.requests)
    assert all(child.workflow_id is None and child.selection is None for child in observed.children)
    routed.deny = True
    with pytest.raises(ValueError, match="SYNTHETIC_ACTUAL_SOURCE_DENIED"):
        observe_routed_reference_queries(routed_session(routed), prepared)


def test_concurrent_reobservation_of_allocated_unknown_never_dispatches_or_rekeys(
    routed, monkeypatch
):
    from eom_workflow_runner.reference_query_routed_selection import (
        PreparedRoutedReferenceQuerySelection,
    )

    prepared = routed.app.prepare(
        routed.requests, idempotency_key="pg-routed-unknown:" + uuid4().hex
    )
    allocation = prepared.allocation_candidate()
    with (
        routed.publisher.sessions.begin() as session,
        prepared.operation.admission.admit(session, prepared.preparation.parent) as sources,
    ):
        store = EmbeddingBatchPlanStore(
            prepared.preparation.parent, sources.selection, sources.policy
        )
        original, created = store.allocate(session, allocation)
        assert created and original.route is None
    forbidden = Mock(side_effect=AssertionError("unknown original must not allocate again"))
    monkeypatch.setattr(PreparedRoutedReferenceQuerySelection, "allocation_candidate", forbidden)
    barrier = Barrier(2)

    def inspect():
        barrier.wait(timeout=10)
        return drive_routed_reference_queries_once(routed_session(routed), prepared)

    with ThreadPoolExecutor(max_workers=2) as pool:
        one, two = tuple(pool.map(lambda _i: inspect(), range(2)))
    assert one == two and one.state == "PENDING" and one.device is None
    forbidden.assert_not_called()
    with (
        routed.publisher.sessions.begin() as session,
        prepared.operation.admission.admit(session, prepared.preparation.parent) as sources,
    ):
        assert (
            EmbeddingBatchPlanStore(
                prepared.preparation.parent, sources.selection, sources.policy
            ).read(session)
            == original
        )
