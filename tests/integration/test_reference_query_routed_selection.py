"""Actual PG selection/publication replay with explicitly synthetic IAM/source/index leaves."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock
from uuid import uuid4

import pytest
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.models import JobRecord
from eom_orchestrator.settings import Settings
from eom_workflow.reference_query_routed_preparation import routed_reference_query_preparation_key
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
