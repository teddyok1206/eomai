"""Guarded PostgreSQL publisher/plan, synthetic child/source and root-output proof."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from uuid import uuid4

import pytest
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.local_embedding_control_artifacts import BATCH_EXECUTION_RECEIPT_ARTIFACT_TYPE
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_orchestrator.settings import Settings
from eom_workflow.embedding_batch_execution_receipt import EmbeddingBatchExecutionReceipt
from eom_workflow.embedding_batch_plan import EmbeddingBatchPlanRequest
from sqlalchemy import func, select

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.embedding_batch_publication_fixtures import publication_case
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_batch_plan_admission import source_case

pytestmark = pytest.mark.integration


@pytest.fixture
def case_factory(guarded_engine, tmp_path, monkeypatch):
    nas = tmp_path / "nas"
    nas.mkdir()
    publisher = ControlFileSetPublisher(
        guarded_engine, Settings(staging_root=tmp_path / "staging", nas_artifact_root=nas)
    )

    def create(stage="BOUND"):
        value = source_case(tmp_path, monkeypatch, publisher=publisher, key=uuid4().hex)
        value.request = EmbeddingBatchPlanRequest.model_validate(
            seal(
                value.request.model_dump(mode="json")
                | {
                    "batch_id": "embeddingbatch_" + uuid4().hex,
                },
                "request_sha256",
            )
        )
        value = publication_case(value, monkeypatch, stage=stage)
        with publisher.sessions() as session:
            value.base_revisions = session.scalar(
                select(func.count()).select_from(ArtifactRevisionRecord)
            )
        return value

    return create


@pytest.fixture
def published_case(case_factory):
    return case_factory()


def read_receipt(value, saved):
    with value.publisher.sessions() as session, session.begin():
        pointer = saved.member
        reader = PinnedArtifactReadContext(
            session, CatalogSettings(nas_artifact_root=value.publisher.settings.nas_artifact_root)
        )
        reader.prefetch(((pointer.artifact_id, pointer.artifact_revision_id),))
        return reader.read_pinned(
            **pointer.model_dump(mode="python"),
            expected_artifact_types=(BATCH_EXECUTION_RECEIPT_ARTIFACT_TYPE,),
            expected_primary_file="receipt.json",
            max_bytes=512 * 1024,
        ).payload


def test_original_parent_bound_execution_publishes_one_exact_receipt_and_not_child_success(
    published_case,
):
    value = published_case
    first = value.operation.publish(value.channel, value.verified)
    assert value.operation.publish(value.channel, value.verified) == first
    assert (
        EmbeddingBatchExecutionReceipt.model_validate_json(read_receipt(value, first))
        == value.receipt
    )
    with value.publisher.sessions() as session, session.begin():
        assert value.store.read(session) == value.history
        assert (
            session.scalar(select(func.count()).select_from(ArtifactRevisionRecord))
            == value.base_revisions + 1
        )
        jobs = tuple(
            session.scalars(
                select(JobRecord).where(
                    JobRecord.job_id.in_(
                        (
                            value.saved_selection.owner_job_id,
                            value.saved_policy.owner_job_id,
                            value.history.job_id,
                            first.owner_job_id,
                        )
                    )
                )
            )
        )
        # 2 control publishers + parent plan + 1 receipt publisher, no native child Jobs.
        assert len(jobs) == 4
        assert session.get(JobRecord, first.owner_job_id).status == "SUCCEEDED"
        for job in jobs:
            raw = canonical_json_bytes(job.request)
            assert len(raw) < 16 * 1024
            assert b'"vectors":' not in raw and b'"text":' not in raw


@pytest.mark.parametrize("stage", ("ALLOCATED", "ROUTED", "FAILED"))
def test_planning_or_failed_parent_is_not_computation_success(case_factory, stage):
    value = case_factory(stage)
    with pytest.raises(ValueError):
        value.operation.publish(value.channel, value.verified)
    with value.publisher.sessions() as session, session.begin():
        assert value.store.read(session) == value.history
        assert (
            session.scalar(select(func.count()).select_from(ArtifactRevisionRecord))
            == value.base_revisions
        )


@pytest.mark.parametrize("source", ("parent", "child"))
def test_replay_is_not_a_current_permission_grant_and_keeps_original_receipt(
    published_case, source
):
    value = published_case
    saved = value.operation.publish(value.channel, value.verified)
    if source == "parent":
        value.denied = True
    else:
        value.source_denied = True
    with pytest.raises((ValueError, PermissionError)):
        value.operation.publish(value.channel, value.verified)
    assert read_receipt(value, saved) == canonical_json_bytes(value.receipt.model_dump(mode="json"))
    value.denied = value.source_denied = False
    assert value.operation.publish(value.channel, value.verified) == saved


def test_late_authority_failure_preserves_committed_technical_receipt_not_child_completion(
    published_case, monkeypatch
):
    value = published_case
    original = value.operation.controls.publish_batch_execution_receipt
    saved = []

    def revoke_after_commit(*args, **kwargs):
        result = original(*args, **kwargs)
        saved.append(result)
        value.source_denied = True
        return result

    monkeypatch.setattr(
        value.operation.controls, "publish_batch_execution_receipt", revoke_after_commit
    )
    with pytest.raises(PermissionError):
        value.operation.publish(value.channel, value.verified)
    assert len(saved) == 1
    with value.publisher.sessions() as session, session.begin():
        assert session.get(JobRecord, saved[0].owner_job_id).status == "SUCCEEDED"
        assert value.store.read(session) == value.history
    value.source_denied = False
    monkeypatch.setattr(value.operation.controls, "publish_batch_execution_receipt", original)
    assert value.operation.publish(value.channel, value.verified) == saved[0]


def test_same_original_execution_key_cannot_switch_receipt_or_scope(published_case):
    value = published_case
    saved = value.operation.publish(value.channel, value.verified)
    changed = value.receipt.model_dump(mode="json")
    changed["children"][0]["result_sha256"] = "sha256:" + "f" * 64
    changed = EmbeddingBatchExecutionReceipt.model_validate(seal(changed, "receipt_sha256"))
    # Existing canonical publisher rejects a different payload at the original key.
    with value.publisher.sessions() as session:
        key = session.get(JobRecord, saved.owner_job_id).idempotency_key
    with pytest.raises(ControlPlaneError):
        value.operation.controls.publish_batch_execution_receipt(changed, idempotency_key=key)
    forged_batch = value.verified.staged.batch.model_copy(
        update={
            "scope": value.verified.staged.batch.scope.model_copy(
                update={"actor_id": "operator_foreign"}
            )
        }
    )
    forged = replace(value.verified, staged=replace(value.verified.staged, batch=forged_batch))
    with pytest.raises(ValueError):
        value.operation.publish(value.channel, forged)
    assert value.operation.publish(value.channel, value.verified) == saved


def test_two_publishers_converge_on_one_original_receipt_and_do_not_dispatch_again(published_case):
    value = published_case
    barrier = Barrier(2)

    def publish():
        barrier.wait(timeout=10)
        return value.operation.publish(value.channel, value.verified)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result(timeout=30) for future in [pool.submit(publish) for _ in range(2)]]
    assert results[0] == results[1]
    with value.publisher.sessions() as session, session.begin():
        assert value.store.read(session) == value.history
        assert (
            session.scalar(select(func.count()).select_from(ArtifactRevisionRecord))
            == value.base_revisions + 1
        )


def test_interruption_before_publication_keeps_parent_and_no_receipt(published_case, monkeypatch):
    value = published_case
    original = value.operation.controls.publish_batch_execution_receipt

    def interrupted(*_args, **_kwargs):
        raise KeyboardInterrupt("synthetic owner interruption before canonical commit")

    monkeypatch.setattr(value.operation.controls, "publish_batch_execution_receipt", interrupted)
    with pytest.raises(KeyboardInterrupt):
        value.operation.publish(value.channel, value.verified)
    with value.publisher.sessions() as session, session.begin():
        assert value.store.read(session) == value.history
        assert (
            session.scalar(select(func.count()).select_from(ArtifactRevisionRecord))
            == value.base_revisions
        )
    monkeypatch.setattr(value.operation.controls, "publish_batch_execution_receipt", original)
    assert read_receipt(
        value, value.operation.publish(value.channel, value.verified)
    ) == canonical_json_bytes(value.receipt.model_dump(mode="json"))
