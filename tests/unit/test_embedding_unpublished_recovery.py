"""Distinct success/unpublished failure metadata; no numerical or maintenance authority."""

from pathlib import Path

import pytest
from eom_identifiers import sha256_bytes
from eom_workflow import embedding_encoding_recovery as recovery
from eom_workflow import embedding_unpublished_recovery as unpublished

from tests.unit.embedding_encoding_recovery_fixtures import unpublished_failure
from tests.unit.embedding_encoding_reservation_fixtures import reservation_fixture
from tests.unit.inference_transfer_embedding_fixtures import seal


@pytest.fixture
def failure():
    fixture = reservation_fixture("a")
    return unpublished_failure(
        fixture.association.owned_jobs[0], fixture.association.intent.native_launch_job_id
    )


def test_distinct_schema_is_mirrored_and_does_not_reinterpret_old_failure(failure):
    root = Path(__file__).resolve().parents[2]
    name = "embedding-encoding-recovery-v2.schema.json"
    raw = (root / "schemas/workflow" / name).read_bytes()
    assert raw == (root / "packages/workflow/eom_workflow/resources" / name).read_bytes()
    assert sha256_bytes(raw) == unpublished.UNPUBLISHED_RECOVERY_SCHEMA_SHA256
    assert recovery.parse_supported_encoding_failure(failure) == failure
    kind = recovery.encoding_failure_disposition(failure)
    assert kind.code == unpublished.UNPUBLISHED_ENCODING_FAILURE_CODE
    assert failure.root.original_outcome == "SUCCEEDED"
    assert failure.root.controller_outcome == "FAILED"
    with pytest.raises(ValueError):
        recovery.KnownFailedEmbeddingEncoding.model_validate(failure.model_dump(mode="json"))


@pytest.mark.parametrize(
    "fault",
    [
        "worker_failed",
        "controller_succeeded",
        "controller_missing",
        "retained",
        "bool",
        "float",
        "extra",
        "hash",
        "utc",
        "version",
    ],
)
def test_changed_or_ambiguous_outcomes_are_not_recovery_proof(failure, fault):
    body = failure.model_dump(mode="json")
    if fault == "worker_failed":
        body["root"]["original_outcome"] = "FAILED"
    elif fault == "controller_succeeded":
        body["root"]["controller_outcome"] = "SUCCEEDED"
    elif fault == "controller_missing":
        body["root"].pop("controller_invocation_id")
    elif fault in {"retained", "bool", "float"}:
        body["root"]["stored_descriptors"] = {"retained": 1, "bool": False, "float": 0.0}[fault]
    elif fault == "extra":
        body["root"]["admin"] = True
    elif fault == "utc":
        body["root"]["retired_at"] = "2026-10-25T12:00:00+09:00"
    elif fault == "version":
        body["schema_version"] = "embedding-encoding-recovery/1.0"
    with pytest.raises(ValueError):
        if fault != "float":
            body = seal(body, "event_sha256")
        if fault == "hash":
            body["event_sha256"] = "sha256:" + "0" * 64
        recovery.parse_supported_encoding_failure(body)


@pytest.mark.parametrize("value", [False, 0.0, 1, -1])
def test_standalone_root_metadata_does_not_coerce_invalid_descriptors(failure, value):
    body = failure.root.model_dump(mode="json") | {"stored_descriptors": value}
    with pytest.raises(ValueError):
        unpublished.RetiredUnpublishedEmbeddingResult.model_validate(body)


@pytest.mark.parametrize("generation", [1, True, 1.0, 0])
def test_unpublished_command_has_its_own_hash_and_strict_original_generation(failure, generation):
    fixture = reservation_fixture("a")
    body = dict(
        schema_version=unpublished.UNPUBLISHED_RECOVERY_PROTOCOL,
        record_type="RECOVER",
        workflow_id=fixture.association.intent.workflow_id,
        workflow_request_sha256=fixture.request.request_sha256,
        command_id=fixture.association.intent.command_id,
        lease_generation=generation,
        root=failure.root.model_dump(mode="json"),
    )
    if type(generation) is int and generation == 1:
        body = seal(body, "command_sha256")
        value = recovery.parse_supported_failure_recovery(body)
        assert value.root == failure.root
        with pytest.raises(ValueError):
            recovery.NativeEmbeddingFailureRecoveryCommand.model_validate(body)
    else:
        with pytest.raises(ValueError):
            if type(generation) is float:
                body["command_sha256"] = "sha256:" + "0" * 64
            else:
                body = seal(body, "command_sha256")
            recovery.parse_supported_failure_recovery(body)
