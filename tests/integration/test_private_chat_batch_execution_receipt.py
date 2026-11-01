"""Guarded private receipt publication; current source and GPU completion are synthetic."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.local_embedding_control_artifacts import (
    batch_execution_receipt_publication_key,
)
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_workflow.embedding_batch_execution_receipt import (
    PRIVATE_CHAT_BATCH_EXECUTION_RECEIPT_SCHEMA_REF,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.integration.test_private_chat_query_policy_persistence import controls as controls
from tests.integration.test_private_chat_query_policy_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.embedding_batch_execution_fixtures import execution_case
from tests.unit.private_chat_batch_plan_fixtures import private_planning_case
from tests.unit.test_private_chat_query_basis import TEXT

pytestmark = pytest.mark.integration


@pytest.fixture
def executed():
    return execution_case(planned=private_planning_case(batch_id="embeddingbatch_" + uuid4().hex))


def test_concurrent_private_receipt_publishers_keep_one_revision_and_exact_schema(
    controls, executed
):
    request_sha = executed.frames.request.parent_request_sha256
    allocation_sha = "sha256:" + uuid4().hex * 2
    key = batch_execution_receipt_publication_key(request_sha, allocation_sha)
    barrier = Barrier(3)

    def publish(_index):
        barrier.wait(timeout=15)
        return controls.publish_batch_execution_receipt(executed.receipt, idempotency_key=key)

    with ThreadPoolExecutor(max_workers=3) as pool:
        saved = tuple(pool.map(publish, range(3)))
    assert saved[0] == saved[1] == saved[2]
    assert saved[0].member.schema_ref == PRIVATE_CHAT_BATCH_EXECUTION_RECEIPT_SCHEMA_REF
    assert (
        controls.find_batch_execution_receipt(
            parent_request_sha256=request_sha, allocation_record_sha256=allocation_sha
        )
        == saved[0].member
    )
    assert (
        controls.publish_batch_execution_receipt(executed.receipt, idempotency_key=key) == saved[0]
    )
    with Session(controls.publisher.engine) as session:
        assert (
            session.scalar(
                select(func.count()).select_from(JobRecord).where(JobRecord.idempotency_key == key)
            )
            == 1
        )
        job = session.get(JobRecord, saved[0].owner_job_id)
        revision = session.get(ArtifactRevisionRecord, saved[0].member.artifact_revision_id)
        assert job.status == "SUCCEEDED" and revision.job_id == job.job_id
        assert TEXT.encode() not in canonical_json_bytes(job.request)
        assert TEXT.encode() not in canonical_json_bytes(revision.result)


def test_private_receipt_key_cannot_be_replaced_by_public_receipt(controls, executed):
    key = "private-receipt-family:" + uuid4().hex
    saved = controls.publish_batch_execution_receipt(executed.receipt, idempotency_key=key)
    with pytest.raises(ControlPlaneError) as error:
        controls.publish_batch_execution_receipt(execution_case().receipt, idempotency_key=key)
    assert error.value.code == "CONTROL_FILE_SET_CONFLICT"
    assert controls.publish_batch_execution_receipt(executed.receipt, idempotency_key=key) == saved


def test_private_extra_question_is_rejected_before_job_or_artifact_creation(controls, executed):
    key = "invalid-private-receipt:" + uuid4().hex
    malformed = executed.receipt.model_copy(update={"question": TEXT})
    with pytest.raises(ValueError) as error:
        controls.publish_batch_execution_receipt(malformed, idempotency_key=key)
    assert TEXT not in str(error.value)
    with Session(controls.publisher.engine) as session:
        assert (
            session.scalar(
                select(func.count()).select_from(JobRecord).where(JobRecord.idempotency_key == key)
            )
            == 0
        )
