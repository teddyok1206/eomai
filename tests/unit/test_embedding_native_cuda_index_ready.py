"""Synthetic INDEX readiness/linkage only; no root ACK, model, source grant or device."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.embedding_native_cuda_index_ready import (
    MAX_NATIVE_CUDA_INDEX_READY_BYTES,
    NATIVE_CUDA_INDEX_READY_SCHEMA,
    NativeCudaIndexReady,
    native_cuda_index_ready_bytes,
    parse_native_cuda_index_ready,
    validate_native_cuda_index_ready,
)
from eom_catalog_contracts.inference_transfer_embedding import IncrementalEmbeddingInput
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_identifiers import canonical_json_bytes, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.embedding_installed_runtime_fixtures import runtime_proof
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.local_embedding_admission_fixtures import NativeAdmissionFixture, native_fixture

INVALID = (ValueError, TypeError, SchemaError)


@pytest.fixture(scope="module")
def selected() -> tuple[NativeAdmissionFixture, NativeCudaIndexReady]:
    fixture = native_fixture(device="CUDA")
    body = {
        "schema_version": "embedding-native-cuda-index-ready/1.0",
        "purpose": "INDEX",
        "evidence_state": "RETENTION_REQUESTED_NOT_COMPUTE_ADMITTED",
        "execution_id": "a" * 32,
        "job_id": fixture.association.intent.native_launch_job_id,
        "launch_association_sha256": fixture.association.association_sha256,
        "input_raw_sha256": fixture.association.owned_input.sha256,
        "request_sha256": fixture.association.owned_input_request_sha256,
        "input_set_sha256": fixture.association.owned_input_set_sha256,
        "configuration": {
            "configuration_id": "embeddingnativeconfig_" + "a" * 32,
            "configuration_revision_id": "embeddingnativeconfigrev_" + "b" * 32,
            "configuration_sha256": "sha256:" + "c" * 64,
            "configuration_raw_sha256": "sha256:" + "d" * 64,
        },
        "receipt_raw_sha256": "sha256:" + "e" * 64,
        "fdstore_name": "eom-gpu0-lease",
        "pid": 123,
        "start_time_ticks": 999,
        "worker_uid": 1234,
        "worker_gid": 1234,
        "supplementary_gids": [2468],
        "resource_fds": {
            "nvidia0_fd": 10,
            "nvidiactl_fd": 11,
            "nvidia_uvm_fd": 12,
            "nvidia_uvm_tools_fd": 13,
            "lease_fd": 14,
        },
        "expected_device_capture": runtime_proof("CUDA_INDEX_FP32").device_capture.model_dump(
            mode="json"
        ),
        "cuda_initialization_calls": 0,
        "cuda_synchronize_calls": 0,
        "model_constructor_calls": 0,
        "tokenizer_constructor_calls": 0,
        "forward_calls": 0,
    }
    return fixture, NativeCudaIndexReady.model_validate(seal(body, "ready_sha256"))


def selection(ready: NativeCudaIndexReady) -> dict[str, Any]:
    return {
        "execution_id": ready.execution_id,
        "native_launch_job_id": ready.job_id,
        "launch_association_sha256": ready.launch_association_sha256,
        "input_raw_sha256": ready.input_raw_sha256,
        "configuration": ready.configuration,
        "receipt_raw_sha256": ready.receipt_raw_sha256,
        "expected_device": ready.expected_device_capture,
    }


def test_frozen_schema_resource_and_real_workflow_fixture_linkage(
    selected: tuple[NativeAdmissionFixture, NativeCudaIndexReady],
) -> None:
    fixture, ready = selected
    root = Path(__file__).resolve().parents[2]
    resource = CATALOG_SCHEMA_RESOURCES[NATIVE_CUDA_INDEX_READY_SCHEMA]
    raw = (root / resource.canonical_path).read_bytes()
    assert sha256_bytes(raw) == resource.sha256
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    Draft202012Validator.check_schema(load_schema(NATIVE_CUDA_INDEX_READY_SCHEMA))
    assert parse_native_cuda_index_ready(native_cuda_index_ready_bytes(ready)) == ready
    assert len(native_cuda_index_ready_bytes(ready)) < MAX_NATIVE_CUDA_INDEX_READY_BYTES
    assert len({ready.input_raw_sha256, ready.request_sha256, ready.input_set_sha256}) == 3
    # The caller owns the real Workflow value; Catalog receives only its exact selection.
    assert fixture.association.owned_input.sha256 == sha256_bytes(
        canonical_json_bytes(fixture.native_input.model_dump(mode="json"))
    )
    validate_native_cuda_index_ready(fixture.native_input, ready, **selection(ready))
    for attribute in ("assert_owned", "root_ack", "source_grant", "admission_granted"):
        assert not hasattr(ready, attribute)
    with pytest.raises(ValueError):
        ready.pid = 456


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
def test_pre_ml_counters_are_exact_zero_not_coerced(
    selected: tuple[NativeAdmissionFixture, NativeCudaIndexReady], field: str, value: Any
) -> None:
    _, ready = selected
    with pytest.raises(INVALID):
        NativeCudaIndexReady.model_validate(ready.model_dump(mode="json") | {field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("purpose", "BENCHMARK"),
        ("purpose", "QUERY"),
        ("schema_version", "embedding-benchmark-cuda-ready/1.0"),
        ("evidence_state", "ADMITTED"),
        ("root_ack", True),
        ("source_grant", True),
        ("pid", True),
        ("pid", 0),
        ("pid", 2147483648),
        ("start_time_ticks", False),
        ("start_time_ticks", 0),
        ("worker_uid", 0),
        ("worker_gid", 0),
        ("supplementary_gids", []),
        ("supplementary_gids", [1234]),
        ("supplementary_gids", [2468, 2468]),
        ("supplementary_gids", [False]),
        ("fdstore_name", "other"),
        ("job_id", "fake"),
        ("execution_id", "a" * 32 + "\n"),
        ("input_raw_sha256", "sha256:" + "E" * 64),
    ),
)
def test_closed_claims_do_not_accept_coercion_authority_or_other_purposes(
    selected: tuple[NativeAdmissionFixture, NativeCudaIndexReady], field: str, value: Any
) -> None:
    _, ready = selected
    body = ready.model_dump(mode="json") | {field: value}
    with pytest.raises(INVALID):
        NativeCudaIndexReady.model_validate(seal(body, "ready_sha256"))


@pytest.mark.parametrize("fault", ("alias", "fd_type", "fd_range", "extra", "hash"))
def test_forged_nested_resources_or_semantic_hash_fail(
    selected: tuple[NativeAdmissionFixture, NativeCudaIndexReady], fault: str
) -> None:
    _, ready = selected
    body = ready.model_dump(mode="json")
    if fault == "alias":
        body["resource_fds"]["lease_fd"] = body["resource_fds"]["nvidia0_fd"]
    elif fault == "fd_type":
        body["resource_fds"]["lease_fd"] = "14"
    elif fault == "fd_range":
        body["resource_fds"]["lease_fd"] = 2
    elif fault == "extra":
        body["configuration"]["admission_granted"] = True
    else:
        body["pid"] += 1
    if fault != "hash":
        body = seal(body, "ready_sha256")
    with pytest.raises(INVALID):
        NativeCudaIndexReady.model_validate(body)


@pytest.mark.parametrize("fault", ("duplicate_json", "trailing", "huge", "non_bytes"))
def test_untrusted_ready_raw_must_be_bounded_canonical_unique_json(
    selected: tuple[NativeAdmissionFixture, NativeCudaIndexReady], fault: str
) -> None:
    _, ready = selected
    raw: Any = native_cuda_index_ready_bytes(ready)
    if fault == "duplicate_json":
        raw = b'{"purpose":"QUERY",' + raw[1:]
    elif fault == "trailing":
        raw += b"\n"
    elif fault == "huge":
        raw = b"x" * (MAX_NATIVE_CUDA_INDEX_READY_BYTES + 1)
    else:
        raw = raw.decode()
    with pytest.raises(INVALID):
        parse_native_cuda_index_ready(raw)


@pytest.mark.parametrize(
    "field",
    (
        "execution_id",
        "job_id",
        "launch_association_sha256",
        "input_raw_sha256",
        "request_sha256",
        "input_set_sha256",
        "configuration",
        "receipt_raw_sha256",
        "expected_device_capture",
    ),
)
def test_valid_rehashed_ready_cannot_select_other_input_job_installation_or_device(
    selected: tuple[NativeAdmissionFixture, NativeCudaIndexReady], field: str
) -> None:
    fixture, ready = selected
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
    changed = NativeCudaIndexReady.model_validate(seal(body, "ready_sha256"))
    with pytest.raises(ValueError, match="ASSOCIATION"):
        validate_native_cuda_index_ready(fixture.native_input, changed, **selection(ready))


@pytest.mark.parametrize("field", ("batch_size", "threads", "cpu", "different_rows"))
def test_another_valid_request_cannot_be_accepted_even_when_readiness_is_resealed(
    selected: tuple[NativeAdmissionFixture, NativeCudaIndexReady], field: str
) -> None:
    fixture, ready = selected
    request_body = fixture.native_input.model_dump(mode="json")
    if field in {"batch_size", "threads"}:
        request_body[field] = 2
        request = IncrementalEmbeddingInput.model_validate(seal(request_body, "request_sha256"))
    else:
        request = native_fixture("c", device="CPU" if field == "cpu" else "CUDA").native_input
    body = ready.model_dump(mode="json") | {
        "input_raw_sha256": sha256_bytes(canonical_json_bytes(request.model_dump(mode="json"))),
        "request_sha256": request.request_sha256,
        "input_set_sha256": request.input_set_sha256,
    }
    changed = NativeCudaIndexReady.model_validate(seal(body, "ready_sha256"))
    selected_values = selection(ready)
    if field in {"batch_size", "threads", "cpu"}:
        # Even a caller that selected those exact bytes cannot turn a nonfixed recipe CUDA.
        selected_values["input_raw_sha256"] = changed.input_raw_sha256
    with pytest.raises(ValueError, match="ASSOCIATION"):
        validate_native_cuda_index_ready(request, changed, **selected_values)


@pytest.mark.parametrize("fault", ("ready_copy", "nested_copy", "request_copy"))
def test_constructed_or_copied_values_are_revalidated_without_lossy_dump(
    selected: tuple[NativeAdmissionFixture, NativeCudaIndexReady], fault: str
) -> None:
    fixture, ready = selected
    request = fixture.native_input
    changed = ready
    if fault == "ready_copy":
        changed = ready.model_copy(update={"cuda_initialization_calls": False})
    elif fault == "nested_copy":
        changed = ready.model_copy(
            update={"resource_fds": ready.resource_fds.model_copy(update={"lease_fd": "14"})}
        )
    else:
        request = request.model_copy(update={"threads": True})
    with pytest.raises(INVALID):
        validate_native_cuda_index_ready(request, changed, **selection(ready))


def test_catalog_contract_does_not_import_workflow_or_runtime_authority() -> None:
    root = Path(__file__).resolve().parents[2]
    path = root / (
        "packages/catalog_contracts/eom_catalog_contracts/embedding_native_cuda_index_ready.py"
    )
    tree = ast.parse(path.read_text())
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)] + [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    assert not any(
        name.startswith(("eom_workflow", "eom_orchestrator", "eom_catalog_service", "sqlalchemy"))
        or name in {"os", "subprocess", "socket", "torch", "transformers", "eom_gpu_lease"}
        for name in imports
    )
