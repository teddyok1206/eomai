"""Private actual source admission with guarded PG parent history; no live IAM/GPU.

Controls, source projection bytes, transactions and concurrent claims are real.
Chat repository and current IAM/public DOCUMENT ports are explicit synthetic seams.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from eom_orchestrator.embedding_batch_plan_store import EmbeddingBatchPlanStore
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.models import JobRecord
from eom_orchestrator.settings import Settings
from eom_workflow.embedding_batch_plan import EmbeddingBatchFailure
from eom_workflow_runner.embedding_batch_allocation_candidate import (
    new_embedding_batch_allocation_candidate,
)
from eom_workflow_runner.embedding_batch_execution import (
    CatalogEmbeddingBatchExecution,
    ExistingEmbeddingBatchExecution,
)
from sqlalchemy import func, select

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_private_chat_batch_plan_admission import make_private_batch_admission_case

pytestmark = pytest.mark.integration


@pytest.fixture(params=(True, False))
def admitted(guarded_engine, tmp_path, monkeypatch, request):
    nas = tmp_path / "nas"
    nas.mkdir()
    publisher = ControlFileSetPublisher(
        guarded_engine,
        Settings(staging_root=tmp_path / "staging", nas_artifact_root=nas, workspace_root=tmp_path),
    )
    value = make_private_batch_admission_case(
        tmp_path, monkeypatch, cpu_index=request.param, publisher=publisher, key=uuid4().hex
    )
    value.store = EmbeddingBatchPlanStore(value.request, value.selection, value.routing)
    value.allocation = new_embedding_batch_allocation_candidate(value.request, value.routing)
    return value


def test_concurrent_private_parent_admissions_allocate_one_original_and_preserve_replay(admitted):
    value = admitted
    barrier = Barrier(2)

    def allocate():
        with (
            value.publisher.sessions.begin() as session,
            value.owner.admit(session, value.request),
        ):
            barrier.wait(timeout=20)
            return value.store.allocate(session, value.allocation)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(allocate) for _ in range(2)]
        result = [future.result(timeout=60) for future in futures]
    assert sorted(created for _, created in result) == [False, True]
    assert result[0][0] == result[1][0]
    with value.publisher.sessions.begin() as session, value.owner.admit(session, value.request):
        assert value.store.allocate(session, value.allocation) == (result[0][0], False)
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobRecord)
                .where(JobRecord.idempotency_key == value.store.key)
            )
            == 1
        )


@pytest.mark.parametrize("failure", ("interruption", "late_source", "late_chat"))
def test_private_parent_interruption_or_late_revocation_rolls_back_allocation(admitted, failure):
    value = admitted
    with (
        pytest.raises((ValueError, RuntimeError)),
        value.publisher.sessions.begin() as session,
        value.owner.admit(session, value.request),
    ):
        value.store.allocate(session, value.allocation)
        if failure == "interruption":
            raise RuntimeError("synthetic interruption before dispatch")
        if failure == "late_source":
            value.fault.value = "public"
        else:
            value.chat.repository.revoked = True
    value.fault.value = None
    value.chat.repository.revoked = False
    with value.publisher.sessions.begin() as session, value.owner.admit(session, value.request):
        assert value.store.read(session) is None
        assert session.get(JobRecord, value.saved_selection.owner_job_id).status == "SUCCEEDED"


def test_private_failed_original_is_observed_without_dispatch_or_history_reinterpretation(admitted):
    value = admitted
    failure = EmbeddingBatchFailure.model_validate(
        seal(
            dict(
                schema_version="embedding-batch-plan/1.0",
                message_type="FAILED",
                request_sha256=value.request.request_sha256,
                error_code="SOURCE_REVOKED",
                evidence=value.request.selection_manifest.model_dump(mode="json"),
            ),
            "record_sha256",
        )
    )
    with value.publisher.sessions.begin() as session, value.owner.admit(session, value.request):
        value.store.allocate(session, value.allocation)
        original = value.store.record_failure(session, failure)
    operation = CatalogEmbeddingBatchExecution(
        value.owner, value.publisher, source_commit="a" * 40, controller_release="b" * 40
    )
    with operation.open(value.request, value.allocation) as result:
        assert type(result) is ExistingEmbeddingBatchExecution
        assert result.history == original and result.history.state == "FAILED"
    with value.publisher.sessions.begin() as session, value.owner.admit(session, value.request):
        assert value.store.read(session) == original
