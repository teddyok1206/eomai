"""Closed evidence is metadata, not root authority or an invented retirement."""

from pathlib import Path

import pytest
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_workflow.embedding_unbound_control_failure import (
    UNBOUND_CONTROL_FAILURE_SCHEMA_SHA256,
    UnboundEmbeddingControlFailure,
)


def proof_document(**updates):
    body = (
        dict(
            schema_version="embedding-unbound-control-failure/1.0",
            parent_plan_job_id="job_" + "a" * 32,
            parent_request_sha256="sha256:" + "b" * 64,
            allocation_attempt_id="embeddingallocation_" + "c" * 32,
            allocation_request_sha256="sha256:" + "d" * 64,
            controller_invocation_id="e" * 32,
            controller_pid=123,
            boot_id="00000000-0000-0000-0000-000000000001",
            allocation_raw_sha256="sha256:" + "1" * 64,
            launch_raw_sha256="sha256:" + "2" * 64,
            descriptor_raw_sha256="sha256:" + "3" * 64,
            controller_outcome="FAILED",
            compute_state="NOT_GRANTED",
            observed_at="2026-10-24T00:00:00Z",
        )
        | updates
    )
    return body | {"evidence_sha256": content_sha256(body)}


def test_schema_packaging_hash_and_immutable_roundtrip():
    root = Path(__file__).resolve().parents[2]
    source = root / "schemas/workflow/embedding-unbound-control-failure-v1.schema.json"
    installed = root / "packages/workflow/eom_workflow/resources" / source.name
    assert source.read_bytes() == installed.read_bytes()
    assert sha256_bytes(source.read_bytes()) == UNBOUND_CONTROL_FAILURE_SCHEMA_SHA256
    proof = UnboundEmbeddingControlFailure.model_validate(proof_document())
    assert UnboundEmbeddingControlFailure.model_validate_json(canonical_json_bytes(proof)) == proof
    with pytest.raises(ValueError):
        proof.controller_pid = 456


@pytest.mark.parametrize(
    "updates",
    (
        {"controller_pid": True},
        {"controller_pid": "123"},
        {"controller_pid": 0},
        {"boot_id": "latest"},
        {"parent_plan_job_id": "job_unknown"},
        {"controller_invocation_id": ""},
        {"controller_outcome": "SUCCEEDED"},
        {"compute_state": "BUSY"},
        {"authority": "ROOT"},
        {"observed_at": "2026-10-24T00:00:00+09:00"},
    ),
)
def test_forged_ambiguous_or_coerced_evidence_rejected(updates):
    with pytest.raises(ValueError):
        UnboundEmbeddingControlFailure.model_validate(proof_document(**updates))


def test_hash_mismatch_and_validated_model_copy_cannot_bypass_schema():
    proof = UnboundEmbeddingControlFailure.model_validate(proof_document())
    with pytest.raises(ValueError):
        UnboundEmbeddingControlFailure.model_validate(
            proof.model_copy(update={"controller_pid": 456})
        )
    with pytest.raises(ValueError):
        UnboundEmbeddingControlFailure.model_validate(
            proof_document() | {"evidence_sha256": "sha256:" + "0" * 64}
        )
