"""Protocol-only untrusted CUDA readiness; no actual PID1, native Job or model."""

from pathlib import Path

import pytest
from eom_catalog_contracts.embedding_benchmark_cuda_ready import (
    BENCHMARK_CUDA_READY_SCHEMA,
    MAX_BENCHMARK_CUDA_READY_BYTES,
    BenchmarkCudaReady,
    benchmark_cuda_ready_bytes,
    parse_benchmark_cuda_ready,
    validate_benchmark_cuda_ready,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_identifiers import canonical_json_bytes, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.embedding_benchmark_cuda_ready_fixtures import benchmark_cuda_ready
from tests.unit.inference_transfer_embedding_fixtures import seal

INVALID = (ValueError, TypeError, SchemaError)


def test_schema_pin_mirror_and_pure_linkage_never_grant_compute():
    invocation, ready = benchmark_cuda_ready()
    root = Path(__file__).resolve().parents[2]
    resource = CATALOG_SCHEMA_RESOURCES[BENCHMARK_CUDA_READY_SCHEMA]
    raw = (root / resource.canonical_path).read_bytes()
    assert sha256_bytes(raw) == resource.sha256
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    Draft202012Validator.check_schema(load_schema(BENCHMARK_CUDA_READY_SCHEMA))
    assert parse_benchmark_cuda_ready(benchmark_cuda_ready_bytes(ready)) == ready
    validate_benchmark_cuda_ready(
        invocation,
        ready,
        configuration=ready.configuration,
        receipt_raw_sha256=ready.receipt_raw_sha256,
        expected_device=ready.expected_device_capture,
    )
    assert not hasattr(ready, "assert_owned") and not hasattr(ready, "root_ack")


@pytest.mark.parametrize(
    "field",
    (
        "cuda_initialization_calls",
        "cuda_synchronize_calls",
        "model_constructor_calls",
        "tokenizer_constructor_calls",
        "forward_calls",
    ),
)
@pytest.mark.parametrize("value", (1, False, 0.0, "0", None))
def test_counts_are_exact_zero_before_root_ack_not_coerced(field, value):
    _, ready = benchmark_cuda_ready()
    body = ready.model_dump(mode="json") | {field: value}
    with pytest.raises(INVALID):
        BenchmarkCudaReady.model_validate(body)


@pytest.mark.parametrize(
    "field,value",
    (
        ("pid", True),
        ("pid", 0),
        ("worker_uid", 0),
        ("worker_gid", 0),
        ("supplementary_gids", []),
        ("supplementary_gids", [1234]),
        ("supplementary_gids", [2468, 2468]),
        ("supplementary_gids", [False]),
        ("fdstore_name", "other"),
        ("job_id", "fake"),
        ("execution_id", "latest"),
        ("receipt_raw_sha256", "sha256:" + "E" * 64),
        ("evidence_state", "ADMITTED"),
        ("root_ack", True),
    ),
)
def test_closed_metadata_rejects_invalid_identity_or_permission_claim(field, value):
    _, ready = benchmark_cuda_ready()
    body = ready.model_dump(mode="json") | {field: value}
    with pytest.raises(INVALID):
        BenchmarkCudaReady.model_validate(body)


@pytest.mark.parametrize("fault", ("alias", "hash", "duplicate_json", "trailing", "huge"))
def test_raw_bytes_and_fd_aliases_are_not_repaired(fault):
    _, ready = benchmark_cuda_ready()
    body = ready.model_dump(mode="json")
    if fault == "alias":
        body["resource_fds"]["lease_fd"] = body["resource_fds"]["nvidia0_fd"]
        raw = canonical_json_bytes(seal(body, "ready_sha256"))
    elif fault == "hash":
        body["pid"] += 1
        raw = canonical_json_bytes(body)
    elif fault == "duplicate_json":
        raw = b'{"schema_version":"other",' + benchmark_cuda_ready_bytes(ready)[1:]
    elif fault == "trailing":
        raw = benchmark_cuda_ready_bytes(ready) + b"\n"
    else:
        raw = b"x" * (MAX_BENCHMARK_CUDA_READY_BYTES + 1)
    with pytest.raises(INVALID):
        parse_benchmark_cuda_ready(raw)


@pytest.mark.parametrize(
    "field",
    (
        "job_id",
        "execution_id",
        "invocation_raw_sha256",
        "configuration",
        "receipt_raw_sha256",
        "expected_device_capture",
    ),
)
def test_valid_rehashed_readiness_cannot_bind_another_job_runtime_or_physical_device(field):
    invocation, ready = benchmark_cuda_ready()
    body = ready.model_dump(mode="json")
    if field == "configuration":
        body[field]["configuration_revision_id"] = "embeddingnativeconfigrev_" + "0" * 32
    elif field == "expected_device_capture":
        body[field]["gpu_uuid"] = "GPU-99999999-2222-3333-4444-555555555555"
    else:
        body[field] = (
            "job_" + "0" * 32
            if field == "job_id"
            else "0" * 32
            if field == "execution_id"
            else "sha256:" + "0" * 64
        )
    changed = BenchmarkCudaReady.model_validate(seal(body, "ready_sha256"))
    with pytest.raises(ValueError, match="ASSOCIATION"):
        validate_benchmark_cuda_ready(
            invocation,
            changed,
            configuration=ready.configuration,
            receipt_raw_sha256=ready.receipt_raw_sha256,
            expected_device=ready.expected_device_capture,
        )
