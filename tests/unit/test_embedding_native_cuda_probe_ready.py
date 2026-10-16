"""Pre-init wire metadata only; not PID1 acceptance, GPU or worker execution."""

from __future__ import annotations

from pathlib import Path

import pytest
from eom_catalog_contracts.embedding_native_cuda_probe import (
    CUDA_PROBE_READY_SCHEMA,
    MAX_CUDA_PROBE_READY_BYTES,
    NativeCudaProbeLeaseReady,
    NativeCudaProbeResult,
    parse_native_cuda_probe_input,
    parse_native_cuda_probe_lease_ready,
    parse_native_cuda_probe_result,
    validate_native_cuda_probe_progression,
    validate_native_cuda_probe_ready_association,
    validate_native_cuda_probe_ready_references,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_identifiers import canonical_json_bytes, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.test_embedding_native_cuda_probe import case as case

ROOT = Path(__file__).resolve().parents[2]
INVALID = (ValueError, TypeError, SchemaError)


@pytest.fixture
def ready_case(case):
    request, raw, result, references = case
    shared = (
        "execution_id",
        "input_raw_sha256",
        "pid",
        "start_time_ticks",
        "worker_uid",
        "worker_gid",
        "supplementary_gids",
        "payload_file_set_sha256",
        "resource_fds",
    )
    source = result.model_dump(mode="json")
    ready = NativeCudaProbeLeaseReady.model_validate(
        {
            **{name: source[name] for name in shared},
            "schema_version": "embedding-native-cuda-probe-lease-ready/1.0",
            "evidence_state": "RETENTION_REQUESTED_NOT_CUDA_ADMITTED",
            "configuration": request.configuration.model_dump(mode="json"),
            "fdstore_name": "eom-gpu0-lease",
            "expected_device_capture": source["device_capture"],
            "cuda_initialization_calls": 0,
            "cuda_synchronize_calls": 0,
            "model_constructor_calls": 0,
            "tokenizer_constructor_calls": 0,
            "forward_calls": 0,
        }
    )
    return request, raw, ready, result, references


def test_additive_schema_and_exact_ready_configuration_then_final_progression(ready_case):
    request, raw, ready, result, refs = ready_case
    resource = CATALOG_SCHEMA_RESOURCES[CUDA_PROBE_READY_SCHEMA]
    canonical = (ROOT / resource.canonical_path).read_bytes()
    assert sha256_bytes(canonical) == resource.sha256
    assert (
        canonical
        == (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    Draft202012Validator.check_schema(load_schema(CUDA_PROBE_READY_SCHEMA))
    assert parse_native_cuda_probe_lease_ready(canonical_json_bytes(ready)) == ready
    validate_native_cuda_probe_ready_references(request, raw, ready, **refs)
    validate_native_cuda_probe_progression(request, raw, ready, result)
    assert not hasattr(ready, "assert_owned")


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
@pytest.mark.parametrize("value", (1, False, 0.0))
def test_no_initialization_or_coerced_counts_before_owner_ack(ready_case, field, value):
    body = ready_case[2].model_dump(mode="json") | {field: value}
    with pytest.raises(INVALID):
        NativeCudaProbeLeaseReady.model_validate(body)


@pytest.mark.parametrize(
    "field,value",
    (
        ("evidence_state", "ADMITTED"),
        ("evidence_state", "OBSERVED_NOT_ADMITTED"),
        ("fdstore_name", "another-lease"),
        ("accepted", True),
        ("worker_uid", 0),
        ("worker_gid", 2468),
        ("supplementary_gids", []),
        ("supplementary_gids", [2468, 999]),
        ("pid", True),
        ("start_time_ticks", 0),
        ("terminal_main_pid", 0),
    ),
)
def test_ready_cannot_claim_authority_termination_or_wrong_identity(ready_case, field, value):
    with pytest.raises(INVALID):
        NativeCudaProbeLeaseReady.model_validate(
            ready_case[2].model_dump(mode="json") | {field: value}
        )


@pytest.mark.parametrize(
    "field,value",
    (
        ("pid", 124),
        ("start_time_ticks", 988),
        ("worker_uid", 3457),
        ("worker_gid", 3457),
        ("execution_id", "e" * 32),
        ("input_raw_sha256", "sha256:" + "e" * 64),
    ),
)
def test_no_process_or_input_substitution_after_first_ack(ready_case, field, value):
    request, raw, ready, original, _ = ready_case
    changed = NativeCudaProbeResult.model_validate(
        original.model_dump(mode="json") | {field: value}
    )
    with pytest.raises(INVALID):
        validate_native_cuda_probe_progression(request, raw, ready, changed)


def test_resource_fd_replacement_is_rejected_even_if_both_frames_individually_valid(ready_case):
    request, raw, ready, original, _ = ready_case
    body = original.model_dump(mode="json")
    body["resource_fds"]["lease_fd"] = 99
    changed = NativeCudaProbeResult.model_validate(body)
    with pytest.raises(ValueError, match="PHASE_SUBSTITUTION"):
        validate_native_cuda_probe_progression(request, raw, ready, changed)


def test_expected_uuid_is_not_silently_rebased_at_ready_or_final_phase(ready_case):
    request, raw, original, result, refs = ready_case
    body = original.model_dump(mode="json")
    body["expected_device_capture"]["gpu_uuid"] = "GPU-eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    changed = NativeCudaProbeLeaseReady.model_validate(body)
    with pytest.raises(ValueError, match="READY_REFERENCE"):
        validate_native_cuda_probe_ready_references(request, raw, changed, **refs)
    with pytest.raises(ValueError, match="PHASE_SUBSTITUTION"):
        validate_native_cuda_probe_progression(request, raw, changed, result)


def test_ready_configuration_and_raw_input_are_immutable(ready_case):
    request, raw, ready, _, _ = ready_case
    body = ready.model_dump(mode="json")
    body["configuration"]["configuration_revision_id"] = "embeddingnativeconfigrev_" + "e" * 32
    changed = NativeCudaProbeLeaseReady.model_validate(body)
    with pytest.raises(ValueError, match="READY_ASSOCIATION"):
        validate_native_cuda_probe_ready_association(request, raw, changed)
    with pytest.raises(ValueError):
        validate_native_cuda_probe_ready_association(request, raw + b"\n", ready)


def test_ready_and_old_input_result_parsers_never_accept_each_others_frames(ready_case):
    _, raw, ready, result, _ = ready_case
    for parser, value in (
        (parse_native_cuda_probe_input, canonical_json_bytes(ready)),
        (parse_native_cuda_probe_result, canonical_json_bytes(ready)),
        (parse_native_cuda_probe_lease_ready, raw),
        (parse_native_cuda_probe_lease_ready, canonical_json_bytes(result)),
    ):
        with pytest.raises(INVALID):
            parser(value)


@pytest.mark.parametrize("fault", ("extra", "nested", "oversize", "duplicate", "deep"))
def test_raw_and_constructed_frames_cannot_bypass_closed_metadata(ready_case, fault):
    ready = ready_case[2]
    if fault == "extra":
        value = ready.model_copy(update={"grant": True})
    elif fault == "nested":
        value = ready.model_copy(
            update={"resource_fds": ready.resource_fds.model_copy(update={"grant": True})}
        )
    else:
        raw = {
            "oversize": b"x" * (MAX_CUDA_PROBE_READY_BYTES + 1),
            "duplicate": b'{"a":1,"a":1}',
            "deep": b'{"a":' + b"[" * 17 + b"0" + b"]" * 17 + b"}",
        }[fault]
        with pytest.raises(INVALID):
            parse_native_cuda_probe_lease_ready(raw)
        return
    with pytest.raises(INVALID):
        NativeCudaProbeLeaseReady.model_validate(value)


def test_published_input_result_schema_bytes_remain_unchanged():
    resource = CATALOG_SCHEMA_RESOURCES["embedding-native-cuda-probe"]
    assert sha256_bytes((ROOT / resource.canonical_path).read_bytes()) == (
        "sha256:ee3b8ad46c92cf88995f351b63072fdccc0283457b49d614626bc3dab633cd8c"
    )
