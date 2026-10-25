"""Schema and immutable retry identity only; no actual root proof or producer execution."""

from pathlib import Path

import pytest
from eom_identifiers import content_sha256, sha256_bytes
from eom_orchestrator.embedding_encoding_reservation_storage import (
    EmbeddingEncodingReservationError,
    owned_job,
)
from eom_orchestrator.models import JobRecord
from eom_workflow import embedding_encoding_recovery as recovery

from tests.unit.embedding_encoding_recovery_fixtures import declaration, known_failure
from tests.unit.embedding_encoding_reservation_fixtures import reservation_fixture
from tests.unit.inference_transfer_embedding_fixtures import seal


def test_recovery_schema_mirror_and_pinned_packaged_hash():
    root = Path(__file__).resolve().parents[2]
    name = "embedding-encoding-recovery-v1.schema.json"
    raw = (root / "schemas/workflow" / name).read_bytes()
    assert raw == (root / "packages/workflow/eom_workflow/resources" / name).read_bytes()
    assert sha256_bytes(raw) == recovery.ENCODING_RECOVERY_SCHEMA_SHA256
    schema = recovery.embedding_encoding_recovery_schema()
    schema.clear()
    assert (
        recovery.embedding_encoding_recovery_schema()["$id"]
        == recovery.ENCODING_RECOVERY_SCHEMA_REF
    )


@pytest.mark.parametrize(
    "fault", ("hash", "false", "descriptors", "success", "unknown", "utc", "extra", "size")
)
def test_unproven_or_changed_failure_metadata_rejected(fault):
    fixture = reservation_fixture("a")
    value = known_failure(
        fixture.association.owned_jobs[0], fixture.association.intent.native_launch_job_id
    )
    body = value.model_dump(mode="json")
    if fault == "false":
        body["root"]["stored_descriptors"] = False
    elif fault == "descriptors":
        body["root"]["stored_descriptors"] = 1
    elif fault == "success":
        body["root"]["original_outcome"] = "SUCCEEDED"
    elif fault == "unknown":
        body["schema_version"] = "embedding-encoding-recovery/99.0"
    elif fault == "utc":
        body["root"]["retired_at"] = "2026-10-25T14:31:15+09:00"
    elif fault == "extra":
        body["root"]["role"] = "ADMIN"
    elif fault == "size":
        body["log"] = "a" * recovery.ENCODING_RECOVERY_MAX_BYTES
    body = seal(body, "event_sha256")
    if fault == "hash":
        body["event_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError):
        recovery.KnownFailedEmbeddingEncoding.model_validate(body)


@pytest.mark.parametrize(
    "fault", ("limit", "zero", "bool", "root", "successor", "request", "artifact")
)
def test_retry_limit_and_original_relation_cannot_be_forged(fault):
    value = declaration(reservation_fixture("a").association.owned_jobs[0])
    body = value.model_dump(mode="json")
    if fault in {"limit", "zero", "bool"}:
        body["attempt"] = {"limit": 4, "zero": 0, "bool": True}[fault]
    elif fault == "root":
        body["attempt"] = 2
    elif fault == "successor":
        body["successor"] = body["predecessor"]
    elif fault == "request":
        body["successor"]["request_sha256"] = "sha256:" + "0" * 64
    else:
        body["successor"]["allocated_artifact_id"] = body["predecessor"]["allocated_artifact_id"]
    with pytest.raises(ValueError):
        recovery.EmbeddingEncodingRetryDeclaration.model_validate(seal(body, "event_sha256"))


def test_one_failed_predecessor_has_one_deterministic_retry_key_not_a_new_encoding_identity():
    owned = reservation_fixture("a").association.owned_jobs[0]
    first, competing = declaration(owned), declaration(owned, seed="e")
    assert (
        first.successor != competing.successor
        and first.storage_idempotency_key == competing.storage_idempotency_key
    )
    assert len(first.storage_idempotency_key) <= 128
    assert first.encoding_sha256 == owned.request.encoding.encoding_sha256
    assert first.storage_idempotency_key != owned.request.idempotency_key
    reference = first.successor
    job = JobRecord(
        job_id=reference.job_id,
        protocol_version="embedding-encoding-job/1.0",
        task_type="native_embedding_encoding",
        idempotency_key=first.storage_idempotency_key,
        request=owned.request.model_dump(mode="json"),
        request_hash=content_sha256(
            dict(
                protocol_version="embedding-encoding-job/1.0",
                task_type="native_embedding_encoding",
                request=owned.request.model_dump(mode="json"),
            )
        ),
        status="CREATED",
        logical_artifact_id=reference.allocated_artifact_id,
        revision_id=reference.allocated_artifact_revision_id,
    )
    assert owned_job(job, first).request == owned.request
    with pytest.raises(EmbeddingEncodingReservationError):
        owned_job(job)
    with pytest.raises(EmbeddingEncodingReservationError):
        owned_job(job, competing)


@pytest.mark.parametrize("fault", (None, "generation", "extra", "hash"))
def test_maintenance_command_pins_exact_original_generation_but_is_not_authority(fault):
    fixture = reservation_fixture("a")
    failure = known_failure(
        fixture.association.owned_jobs[0], fixture.association.intent.native_launch_job_id
    )
    body = dict(
        schema_version=recovery.ENCODING_RECOVERY_PROTOCOL,
        record_type="RECOVER",
        workflow_id=fixture.association.intent.workflow_id,
        workflow_request_sha256=fixture.request.request_sha256,
        command_id=fixture.association.intent.command_id,
        lease_generation=1,
        root=failure.root.model_dump(mode="json"),
    )
    if fault == "generation":
        body["lease_generation"] = True
    elif fault == "extra":
        body["approved"] = True
    body = seal(body, "command_sha256")
    if fault == "hash":
        body["command_sha256"] = "sha256:" + "0" * 64
    if fault:
        with pytest.raises(ValueError):
            recovery.NativeEmbeddingFailureRecoveryCommand.model_validate(body)
    else:
        value = recovery.NativeEmbeddingFailureRecoveryCommand.model_validate(body)
        assert value.root == failure.root and value.lease_generation == 1
