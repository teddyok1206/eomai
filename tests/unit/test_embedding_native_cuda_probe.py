"""Synthetic closed probe metadata, never GPU initialization, root admission or model use."""

from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import pytest
from eom_catalog_contracts.embedding_native_cpu_probe import (
    NativeCpuProbeDenials,
    NativeProbeFilesystemDenials,
    parse_native_cpu_probe_input,
    parse_native_cpu_probe_result,
)
from eom_catalog_contracts.embedding_native_cuda_probe import (
    CUDA_PROBE_SCHEMA,
    MAX_CUDA_PROBE_BYTES,
    NativeCudaProbeInput,
    NativeCudaProbeResult,
    parse_native_cuda_probe_input,
    parse_native_cuda_probe_result,
    validate_native_cuda_probe_association,
    validate_native_cuda_probe_references,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_identifiers import canonical_json_bytes, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.embedding_native_runtime_config_fixtures import native_config_metadata
from tests.unit.test_embedding_cuda_installation_evidence import metadata
from tests.unit.test_embedding_native_cpu_probe import metadata as cpu_metadata

ROOT = Path(__file__).resolve().parents[2]
INVALID = (ValueError, TypeError, SchemaError)


@pytest.fixture(scope="module")
def case():
    facts = metadata()
    receipt, bundle = facts["receipt"], facts["bundle"]
    request = NativeCudaProbeInput.model_validate(
        {
            "schema_version": "embedding-native-cuda-probe-input/1.0",
            "execution_id": "b" * 32,
            "profile": "CUDA_INDEX_FP32",
            "configuration": receipt.configuration.model_dump(mode="json"),
            "installed_proof": receipt.installed_proof.model_dump(mode="json"),
            "payload": bundle.payload_pointer.model_dump(mode="json"),
            "shared_lease_gid": 2468,
        }
    )
    raw = canonical_json_bytes(request)
    result = NativeCudaProbeResult.model_validate(
        {
            "schema_version": "embedding-native-cuda-probe-result/1.0",
            "evidence_state": "OBSERVED_NOT_ADMITTED",
            "recipe": "NATIVE_CUDA_FIXED_UNIT_NO_MODEL_NO_FORWARD_NEGATIVES/1.0",
            "execution_id": request.execution_id,
            "input_raw_sha256": sha256_bytes(raw),
            "pid": 123,
            "start_time_ticks": 987,
            "worker_uid": 3456,
            "worker_gid": 3456,
            "supplementary_gids": [2468],
            "checked_model_members": len(bundle.payload_model_spec.files) + 1,
            "payload_file_set_sha256": request.payload.file_set_sha256,
            "denials": {name: "DENIED" for name in NativeProbeFilesystemDenials.model_fields},
            "numerical_runtime": bundle.numerical_runtime.model_dump(mode="json"),
            "device_capture": facts["proof"].device_capture.model_dump(mode="json"),
            "resource_fds": {
                name: fd
                for fd, name in enumerate(
                    (
                        "nvidia0_fd",
                        "nvidiactl_fd",
                        "nvidia_uvm_fd",
                        "nvidia_uvm_tools_fd",
                        "lease_fd",
                    ),
                    10,
                )
            },
            "cuda_initialization_calls": 1,
            "cuda_synchronize_calls": 1,
            "model_constructor_calls": 0,
            "tokenizer_constructor_calls": 0,
            "forward_calls": 0,
        }
    )
    references = {
        "configuration": facts["config"],
        "configuration_raw": facts["config_raw"],
        "bundle": bundle,
        "bundle_raw": facts["bundle_raw"],
        "proof": facts["proof"],
        "proof_raw": facts["proof_raw"],
    }
    return request, raw, result, references


def test_schema_defined_first_mirrored_and_exact_reference_roundtrip(case):
    request, raw, result, references = case
    resource = CATALOG_SCHEMA_RESOURCES[CUDA_PROBE_SCHEMA]
    canonical = (ROOT / resource.canonical_path).read_bytes()
    packaged = (
        ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
    ).read_bytes()
    assert canonical == packaged and sha256_bytes(canonical) == resource.sha256
    Draft202012Validator.check_schema(load_schema(CUDA_PROBE_SCHEMA))
    assert parse_native_cuda_probe_input(raw) == request
    assert parse_native_cuda_probe_result(canonical_json_bytes(result)) == result
    assert result.evidence_state == "OBSERVED_NOT_ADMITTED"
    assert not hasattr(result, "assert_owned")
    validate_native_cuda_probe_references(request, raw, result, **references)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("profile", "CPU_INDEX_FP32"),
        ("shared_lease_gid", True),
        ("shared_lease_gid", 0),
        ("shared_lease_gid", "2468"),
        ("role", "ADMIN"),
        ("prefix", "/tmp/other-prefix"),
        ("command", "anything"),
        ("grant", True),
    ),
)
def test_input_has_no_coerced_authority_or_arbitrary_execution_fields(case, field, value):
    body = case[0].model_dump(mode="json")
    body[field] = value
    with pytest.raises(INVALID):
        NativeCudaProbeInput.model_validate(body)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("evidence_state", "SEALED_INSTALLATION_EVIDENCE"),
        ("recipe", "NATIVE_CPU_FIXED_UNIT_NO_MODEL_NO_FORWARD_NEGATIVES/1.0"),
        ("pid", True),
        ("start_time_ticks", 0),
        ("worker_uid", 0),
        ("worker_gid", 2468),
        ("supplementary_gids", []),
        ("supplementary_gids", [2468, 3456]),
        ("supplementary_gids", [True]),
        ("cuda_initialization_calls", 0),
        ("cuda_synchronize_calls", True),
        ("model_constructor_calls", 1),
        ("tokenizer_constructor_calls", 1),
        ("forward_calls", 1),
        ("forward_calls", False),
        ("terminal_cgroup_member_count", 0),
        ("sealed_at_utc", "2026-10-16T20:00:00Z"),
    ),
)
def test_result_cannot_admit_compute_or_claim_unobserved_termination(case, field, value):
    body = case[2].model_dump(mode="json")
    body[field] = value
    with pytest.raises(INVALID):
        NativeCudaProbeResult.model_validate(body)


@pytest.mark.parametrize("fault", ("alias", "negative", "stdio", "extra", "boolean", "gpu_denial"))
def test_descriptor_hints_are_bounded_unique_and_distinct_from_cpu_gpu_denial(case, fault):
    body = case[2].model_dump(mode="json")
    if fault == "alias":
        body["resource_fds"]["lease_fd"] = body["resource_fds"]["nvidia0_fd"]
    elif fault == "negative":
        body["resource_fds"]["lease_fd"] = -1
    elif fault == "stdio":
        body["resource_fds"]["lease_fd"] = 1
    elif fault == "boolean":
        body["resource_fds"]["lease_fd"] = True
    elif fault == "extra":
        body["resource_fds"]["grant"] = "CUDA_OWNER"
    else:
        body["denials"]["gpu"] = "DENIED"
    with pytest.raises(INVALID):
        NativeCudaProbeResult.model_validate(body)


@pytest.mark.parametrize("fault", ("root", "nested", "missing"))
def test_copied_constructed_model_fields_do_not_bypass_schema(case, fault):
    result = case[2]
    if fault == "root":
        changed = result.model_copy(update={"grant": True})
    elif fault == "nested":
        changed = result.model_copy(
            update={"resource_fds": result.resource_fds.model_copy(update={"grant": True})}
        )
    else:
        values = result.model_dump()
        values.pop("start_time_ticks")
        changed = NativeCudaProbeResult.model_construct(**values)
    with pytest.raises(INVALID):
        NativeCudaProbeResult.model_validate(changed)


@pytest.mark.parametrize("fault", ("execution", "raw", "payload", "group"))
def test_same_execution_raw_payload_and_expected_lease_group_are_required(case, fault):
    request, raw, original, _ = case
    body = original.model_dump(mode="json")
    body[
        {
            "execution": "execution_id",
            "raw": "input_raw_sha256",
            "payload": "payload_file_set_sha256",
            "group": "supplementary_gids",
        }[fault]
    ] = {
        "execution": "c" * 32,
        "raw": "sha256:" + "f" * 64,
        "payload": "sha256:" + "f" * 64,
        "group": [9999],
    }[fault]
    result = NativeCudaProbeResult.model_validate(body)
    with pytest.raises(ValueError, match="ASSOCIATION"):
        validate_native_cuda_probe_association(request, raw, result)


@pytest.mark.parametrize("member", ("configuration_raw", "bundle_raw", "proof_raw"))
def test_raw_reference_drift_fails_without_new_revision_fallback(case, member):
    request, raw, result, references = case
    changed = references | {member: references[member] + b"\n"}
    with pytest.raises(INVALID):
        validate_native_cuda_probe_references(request, raw, result, **changed)


def test_cuda_device_uuid_is_closed_even_when_numeric_device_is_identical(case):
    request, raw, result, references = case
    body = result.model_dump(mode="json")
    body["device_capture"]["gpu_uuid"] = "GPU-ffffffff-ffff-ffff-ffff-ffffffffffff"
    changed = NativeCudaProbeResult.model_validate(body)
    with pytest.raises(ValueError, match="REFERENCE"):
        validate_native_cuda_probe_references(request, raw, changed, **references)


@pytest.mark.parametrize("count", (2, 8, 32))
def test_checked_members_must_match_the_pinned_payload_not_just_the_range(case, count):
    request, raw, result, references = case
    assert count != result.checked_model_members
    changed = NativeCudaProbeResult.model_validate(
        result.model_dump(mode="json") | {"checked_model_members": count}
    )
    with pytest.raises(ValueError, match="REFERENCE"):
        validate_native_cuda_probe_references(request, raw, changed, **references)


def test_configuration_legacy_family_cannot_admit_cuda_probe(case):
    request, raw, result, references = case
    old, _, _ = native_config_metadata("CUDA_INDEX_FP32")
    with pytest.raises(ValueError, match="CONFIGURATION"):
        validate_native_cuda_probe_references(
            request, raw, result, **(references | {"configuration": old})
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("configuration_id", "embeddingnativeconfig_" + "f" * 32),
        ("configuration_revision_id", "embeddingnativeconfigrev_" + "f" * 32),
        ("configuration_sha256", "sha256:" + "f" * 64),
        ("configuration_raw_sha256", "sha256:" + "f" * 64),
    ),
)
def test_configuration_identity_revision_semantic_and_raw_pins_are_separate(case, field, value):
    request, _, result, references = case
    body = request.model_dump(mode="json")
    body["configuration"][field] = value
    changed = NativeCudaProbeInput.model_validate(body)
    raw = canonical_json_bytes(changed)
    reported = NativeCudaProbeResult.model_validate(
        result.model_dump(mode="json") | {"input_raw_sha256": sha256_bytes(raw)}
    )
    validate_native_cuda_probe_association(changed, raw, reported)
    with pytest.raises(INVALID):
        validate_native_cuda_probe_references(changed, raw, reported, **references)


def test_another_payload_with_identical_file_set_is_not_same_logical_model(case):
    request, _, result, references = case
    body = request.model_dump(mode="json")
    body["payload"]["model_id"] = "embeddingmodel_" + "f" * 32
    changed = NativeCudaProbeInput.model_validate(body)
    raw = canonical_json_bytes(changed)
    reported = NativeCudaProbeResult.model_validate(
        result.model_dump(mode="json") | {"input_raw_sha256": sha256_bytes(raw)}
    )
    validate_native_cuda_probe_association(changed, raw, reported)
    with pytest.raises(ValueError, match="REFERENCE"):
        validate_native_cuda_probe_references(changed, raw, reported, **references)


@pytest.mark.parametrize(
    "raw",
    (
        b"{}\n",
        b' {"a":1}',
        b'{"a":1,"a":1}',
        b'{"a":1.0}',
        b'{"a":NaN}',
        b'{"a":' + b"[" * 17 + b"0" + b"]" * 17 + b"}",
        b'{"a":123456789012345678901}',
        b"\xff",
        b"[]",
        b"x" * (MAX_CUDA_PROBE_BYTES + 1),
    ),
)
def test_external_json_is_bounded_canonical_before_typed_construction(raw):
    with pytest.raises(INVALID):
        parse_native_cuda_probe_input(raw)


def test_cpu_schema_empty_groups_and_canonical_results_are_preserved():
    request, raw, result = cpu_metadata()
    resource = CATALOG_SCHEMA_RESOURCES["embedding-native-cpu-probe"]
    assert sha256_bytes((ROOT / resource.canonical_path).read_bytes()) == (
        "sha256:133d5989acda16ec9f63fc10cbd5f57b114c4c816214c01bcb2e064eab2e14b3"
    )
    assert set(NativeCpuProbeDenials.model_fields) == set(
        NativeProbeFilesystemDenials.model_fields
    ) | {"gpu"}
    assert result.supplementary_gids == ()
    assert parse_native_cpu_probe_input(raw) == request
    assert parse_native_cpu_probe_result(canonical_json_bytes(result)) == result
    for parser, value in (
        (parse_native_cuda_probe_input, raw),
        (parse_native_cuda_probe_result, canonical_json_bytes(result)),
    ):
        with pytest.raises(INVALID):
            parser(value)
    old_body = copy.deepcopy(result.model_dump(mode="json"))
    old_body["supplementary_gids"] = [2468]
    with pytest.raises(INVALID):
        type(result).model_validate(old_body)


def test_contract_import_has_no_runtime_gpu_database_or_orchestrator_side_effects():
    code = """
import sys
import eom_catalog_contracts.embedding_native_cuda_probe
for name in ('torch', 'transformers', 'eom_gpu_lease', 'sqlalchemy', 'eom_orchestrator'):
    assert name not in sys.modules
print('PURE_CONTRACT_IMPORT=PASS')
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=15
    )
    assert result.stdout.strip() == "PURE_CONTRACT_IMPORT=PASS" and not result.stderr
