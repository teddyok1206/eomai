from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.embedding_installed_runtime_proof import (
    INSTALLED_RUNTIME_PROOF_SCHEMA,
    EmbeddingInstalledRuntimeProof,
    EmbeddingRuntimeProfile,
    installed_runtime_proof_bytes,
    parse_installed_runtime_proof,
    validate_installed_runtime_proof_pointer,
)
from eom_catalog_contracts.validation import (
    CATALOG_SCHEMA_RESOURCES,
    load_schema,
    validate_contract,
)
from eom_identifiers import sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaError
from pydantic import ValidationError

from tests.unit.embedding_installed_runtime_fixtures import proof_pointer, runtime_proof
from tests.unit.inference_transfer_embedding_fixtures import seal

ROOT = Path(__file__).resolve().parents[2]


def test_proof_schema_registered_packaged_mirror_is_exact_2020_12() -> None:
    resource = CATALOG_SCHEMA_RESOURCES[INSTALLED_RUNTIME_PROOF_SCHEMA]
    raw = (ROOT / resource.canonical_path).read_bytes()
    assert (
        raw
        == (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(raw) == resource.sha256
    schema = load_schema(INSTALLED_RUNTIME_PROOF_SCHEMA)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("profile", ["CPU_INDEX_FP32", "CUDA_INDEX_FP32"])
def test_exact_proof_roundtrip_distinct_semantic_raw_hash_and_frozen(
    profile: EmbeddingRuntimeProfile,
) -> None:
    proof = runtime_proof(profile)
    pointer = proof_pointer(proof)
    assert parse_installed_runtime_proof(proof.model_dump(mode="json")) == proof
    validate_contract(INSTALLED_RUNTIME_PROOF_SCHEMA, pointer.model_dump(mode="json"))
    validate_installed_runtime_proof_pointer(proof, pointer, installed_runtime_proof_bytes(proof))
    assert pointer.proof_sha256 != pointer.proof_raw_sha256
    assert len(proof.numeric_libraries) == (20 if profile == "CUDA_INDEX_FP32" else 5)
    with pytest.raises(ValidationError):
        proof.profile = "CPU_INDEX_FP32"


@pytest.mark.parametrize(
    "fault",
    [
        "missing_numpy",
        "duplicate",
        "order",
        "version",
        "profile",
        "build",
        "authority",
        "path",
        "archive_path",
        "script_path",
    ],
)
def test_bad_proof_closure_is_rejected_after_resealing(fault: str) -> None:
    body = runtime_proof().model_dump(mode="json")
    if fault == "missing_numpy":
        body["numeric_libraries"].pop(0)
    elif fault == "duplicate":
        body["numeric_libraries"][1] = body["numeric_libraries"][0]
    elif fault == "order":
        body["numeric_libraries"].reverse()
    elif fault == "version":
        body["numeric_libraries"][3]["version"] = "2.7.1+cu128"
    elif fault == "profile":
        body["profile"] = "CUDA_INDEX_FP32"
    elif fault == "build":
        body["torch_build_cuda_version"] = "12.8"
    elif fault in {"authority", "path"}:
        body[fault] = "ADMIN" if fault == "authority" else "/worker-chosen"
    elif fault == "archive_path":
        body["numeric_libraries"][0]["archive"]["wheel_filename"] = "../escape.whl"
    else:
        body["numeric_libraries"][0]["console_scripts"] = [
            {"name": "../escape", "sha256": "sha256:" + "a" * 64, "size_bytes": 1}
        ]
    with pytest.raises((ValueError, JsonSchemaError)):
        parse_installed_runtime_proof(seal(body, "proof_sha256"))


@pytest.mark.parametrize("value", [True, 1.0, "1"])
def test_numeric_size_is_strict_not_bool_float_or_string(value: Any) -> None:
    body = runtime_proof().model_dump(mode="json")
    body["numeric_libraries"][0]["archive"]["size_bytes"] = value
    with pytest.raises(ValueError):
        EmbeddingInstalledRuntimeProof.model_validate(body)


def test_frozen_copy_hash_bypass_and_wrong_pointer_raw_fail() -> None:
    proof = runtime_proof()
    forged = proof.model_copy(update={"proof_sha256": "sha256:" + "f" * 64})
    with pytest.raises(ValueError):
        installed_runtime_proof_bytes(forged)
    with pytest.raises(ValueError):
        validate_installed_runtime_proof_pointer(
            proof, proof_pointer(proof), installed_runtime_proof_bytes(proof) + b"\n"
        )
