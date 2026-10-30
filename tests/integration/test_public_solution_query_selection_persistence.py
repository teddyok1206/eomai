"""Guarded PG public preparation concurrency/recovery; IAM/source/index leaves synthetic."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock
from uuid import uuid4

import pytest
from eom_catalog_contracts.reference_query_prepare import ReferenceQueryPrepareRequestV4
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.models import JobRecord
from eom_orchestrator.settings import Settings
from eom_workflow.reference_query_routed_preparation import routed_reference_query_preparation_key
from sqlalchemy import select

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_public_solution_query_owner_configuration import public as public
from tests.unit.test_public_solution_query_selection import public_selection_case
from tests.unit.test_reference_query_owner_admission import source as source
from tests.unit.test_reference_query_routed_owner_configuration import selected as selected

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def prepared(guarded_engine, tmp_path, monkeypatch, public):
    assert guarded_engine.dialect.name == "postgresql"
    artifacts = tmp_path / "pg-artifacts"
    artifacts.mkdir(mode=0o700)
    publisher = ControlFileSetPublisher(
        guarded_engine,
        Settings(
            staging_root=tmp_path / "pg-staging",
            workspace_root=tmp_path,
            nas_artifact_root=artifacts,
        ),
    )
    return public_selection_case(
        tmp_path,
        monkeypatch,
        public,
        publisher=publisher,
        identity=uuid4().hex,
    )


def test_public_prepare_same_key_concurrently_returns_one_original_revision_without_dispatch(
    prepared,
):
    value, barrier = prepared, Barrier(2)

    def prepare():
        barrier.wait(timeout=10)
        return value.app.prepare_public(value.request)

    with ThreadPoolExecutor(max_workers=2) as pool:
        one, two = tuple(pool.map(lambda _ordinal: prepare(), range(2)))
    assert one.manifest == two.manifest and one.preparation == two.preparation
    assert one.selection == two.selection
    assert one.selection.schema_version == "embedding-batch-plan/1.4"
    key = routed_reference_query_preparation_key(
        value.app.cpu.identity.capture.operator_id,
        value.request.idempotency_key,
    )
    with value.publisher.sessions() as session:
        rows = tuple(session.scalars(select(JobRecord).where(JobRecord.idempotency_key == key)))
        assert len(rows) == 1 and rows[0].status == "SUCCEEDED"
        assert (
            session.scalar(
                select(JobRecord.job_id)
                .where(
                    JobRecord.task_type == "embedding_batch_plan",
                    JobRecord.request["batch_id"].astext == one.preparation.parent.batch_id,
                )
                .limit(1)
            )
            is None
        )


def test_public_prepare_after_interruption_reuses_original_selection_and_checks_current_authority(
    prepared,
    monkeypatch,
):
    value = prepared
    original = value.app.controls.publish_public_routed_reference_query_preparation
    monkeypatch.setattr(
        value.app.controls,
        "publish_public_routed_reference_query_preparation",
        Mock(side_effect=RuntimeError("synthetic interruption")),
    )
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        value.app.prepare_public(value.request)
    monkeypatch.setattr(
        value.app.controls, "publish_public_routed_reference_query_preparation", original
    )
    heads, index_reads = value.heads.call_count, value.index_reads.call_count
    one = value.app.prepare_public(value.request)
    assert value.app.prepare_public(value.request).manifest == one.manifest
    assert value.heads.call_count == heads and value.index_reads.call_count == index_reads
    value.deny = True
    with pytest.raises(ValueError, match="PUBLIC_SOURCE_DENIED"):
        value.app.prepare_public(value.request)


def test_public_same_key_changed_intent_cannot_publish_or_allocate_another_work(prepared):
    one = prepared.app.prepare_public(prepared.request)
    other = ReferenceQueryPrepareRequestV4.model_validate(
        seal(
            prepared.request.model_dump(mode="json") | {"top_k": 9},
            "request_sha256",
        )
    )
    with pytest.raises(ValueError, match="ROUTED_SELECTION_INVALID"):
        prepared.app.prepare_public(other)
    assert prepared.app.prepare_public(prepared.request).manifest == one.manifest
