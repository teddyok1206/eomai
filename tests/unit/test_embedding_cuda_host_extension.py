"""Pure metadata closure does not execute the candidate or grant GPU admission."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.embedding_cuda_host_extension import (
    CUDA_HOST_MANIFEST_REF,
    CUDA_HOST_SCHEMA,
    CudaHostExtensionPointer,
    CudaHostExtensionSnapshot,
    CudaHostLibraryMember,
    cuda_host_extension_bytes,
    parse_cuda_host_extension_bytes,
    validate_cuda_host_extension_pointer,
)
from eom_catalog_contracts.embedding_host_configuration import (
    host_configuration_snapshot_bytes,
    parse_host_configuration_snapshot,
)
from eom_catalog_contracts.validation import (
    CATALOG_SCHEMA_RESOURCES,
    load_schema,
    validate_contract,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.test_embedding_host_configuration_contracts import snapshot_body, snapshot_pointer

ROOT = Path(__file__).resolve().parents[2]
ERRORS = (ValueError, SchemaError)
MEMBERS = (
    ("CUDA_DRIVER", "libcuda.so.1", 96_284_520),
    ("RDMACM", "librdmacm.so.1", 122_144),
    ("IBVERBS", "libibverbs.so.1", 138_032),
    ("MLX5", "libmlx5.so.1", 545_464),
    ("NL_CORE", "libnl-3.so.200", 1),
    ("NL_ROUTE", "libnl-route-3.so.200", 1),
)


def rehash(body: dict[str, Any]) -> dict[str, Any]:
    body["host_seed_sha256"] = content_sha256(
        {
            name: body[name]
            for name in ("base_host_seed_sha256", "driver_release", "libraries", "loader_cache")
        }
    )
    body["snapshot_sha256"] = content_sha256(
        {name: value for name, value in body.items() if name != "snapshot_sha256"}
    )
    return body


def body() -> dict[str, Any]:
    base = parse_host_configuration_snapshot(snapshot_body())
    return rehash(
        {
            "schema_version": "embedding-cuda-host-extension/1.0",
            "configuration_id": "embeddingcudahost_" + "1" * 32,
            "configuration_revision_id": "embeddingcudahostrev_" + "2" * 32,
            "captured_at": "2026-10-16T15:45:00Z",
            "base_configuration": snapshot_pointer(base).model_dump(mode="json"),
            "base_host_seed_sha256": base.host_seed_sha256,
            "driver_release": "580.126.09",
            "libraries": [
                {
                    "role": role,
                    "member_name": name,
                    "byte_count": size,
                    "sha256": "sha256:" + "3" * 64,
                }
                for role, name, size in MEMBERS
            ],
            "loader_cache": base.loader_cache.model_dump(mode="json"),
        }
    )


def pointer(snapshot: CudaHostExtensionSnapshot) -> CudaHostExtensionPointer:
    raw = cuda_host_extension_bytes(snapshot)
    return CudaHostExtensionPointer(
        schema_ref=CUDA_HOST_MANIFEST_REF,
        configuration_id=snapshot.configuration_id,
        configuration_revision_id=snapshot.configuration_revision_id,
        manifest_byte_count=len(raw),
        manifest_raw_sha256=sha256_bytes(raw),
        snapshot_sha256=snapshot.snapshot_sha256,
    )


def validate(snapshot: CudaHostExtensionSnapshot, ref: CudaHostExtensionPointer | None = None):
    base = parse_host_configuration_snapshot(snapshot_body())
    return validate_cuda_host_extension_pointer(
        ref or pointer(snapshot),
        snapshot,
        cuda_host_extension_bytes(snapshot),
        base,
        host_configuration_snapshot_bytes(base),
    )


def test_schema_mirror_export_and_canonical_pointer_closure():
    schema = load_schema(CUDA_HOST_SCHEMA)
    Draft202012Validator.check_schema(schema)
    resource = CATALOG_SCHEMA_RESOURCES[CUDA_HOST_SCHEMA]
    raw_schema = (ROOT / resource.canonical_path).read_bytes()
    assert (
        raw_schema
        == (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(raw_schema) == resource.sha256
    snapshot = CudaHostExtensionSnapshot.model_validate(body())
    assert parse_cuda_host_extension_bytes(cuda_host_extension_bytes(snapshot)) == snapshot
    assert validate(snapshot) == snapshot
    assert pointer(snapshot).manifest_raw_sha256 != snapshot.snapshot_sha256
    import eom_catalog_contracts as public

    assert public.CudaHostExtensionSnapshot is CudaHostExtensionSnapshot


def test_manifest_identity_is_not_runtime_seed_and_bytes_are_immutable():
    first = CudaHostExtensionSnapshot.model_validate(body())
    changed = body()
    changed.update(
        configuration_revision_id="embeddingcudahostrev_" + "4" * 32,
        captured_at="2026-10-16T15:46:00Z",
    )
    second = CudaHostExtensionSnapshot.model_validate(rehash(changed))
    assert first.host_seed_sha256 == second.host_seed_sha256
    assert first.snapshot_sha256 != second.snapshot_sha256
    with pytest.raises(ValueError):
        first.driver_release = "580.126.10"


@pytest.mark.parametrize(
    "field", ("base_host_seed_sha256", "driver_release", "libraries", "loader_cache")
)
def test_runtime_member_change_requires_new_seed(field):
    changed = body()
    if field == "libraries":
        changed[field][0]["sha256"] = "sha256:" + "9" * 64
    elif field == "loader_cache":
        changed[field]["sha256"] = "sha256:" + "9" * 64
    else:
        changed[field] = "580.126.10" if field == "driver_release" else "sha256:" + "9" * 64
    with pytest.raises(ValueError):
        CudaHostExtensionSnapshot.model_validate(changed)
    assert (
        CudaHostExtensionSnapshot.model_validate(rehash(changed)).host_seed_sha256
        != body()["host_seed_sha256"]
    )


@pytest.mark.parametrize(
    "fault", ("missing", "duplicate", "reordered", "extra", "path", "soname", "oversize")
)
def test_schema_and_values_reject_wrong_member_set_before_execution(fault):
    changed = body()
    rows = changed["libraries"]
    if fault == "missing":
        rows.pop()
    elif fault == "duplicate":
        rows[1] = rows[0].copy()
    elif fault == "reordered":
        rows.reverse()
    elif fault == "extra":
        rows.append(rows[0].copy())
    elif fault == "path":
        rows[1]["member_name"] = "../librdmacm.so.1"
    elif fault == "soname":
        rows[1]["member_name"] = "libcuda.so.1"
    else:
        rows[1]["byte_count"] = 8 * 1024 * 1024 + 1
    rehash(changed)
    with pytest.raises(SchemaError):
        validate_contract(CUDA_HOST_SCHEMA, changed)
    with pytest.raises(ERRORS):
        CudaHostExtensionSnapshot.model_validate(changed)


@pytest.mark.parametrize("bad", (True, False, 1.0, "1", 0, -1, None, 128 * 1024 * 1024 + 1))
def test_member_sizes_reject_coercion_and_overflow_in_root_and_standalone_values(bad):
    changed = body()
    changed["libraries"][0]["byte_count"] = bad
    with pytest.raises(ERRORS):
        CudaHostExtensionSnapshot.model_validate(changed)
    with pytest.raises(ERRORS):
        CudaHostLibraryMember.model_validate(changed["libraries"][0])


@pytest.mark.parametrize(
    "field",
    (
        "configuration_id",
        "configuration_revision_id",
        "manifest_byte_count",
        "manifest_raw_sha256",
        "snapshot_sha256",
    ),
)
def test_pointer_exact_revision_raw_hash_size_and_semantic_hash(field):
    snapshot = CudaHostExtensionSnapshot.model_validate(body())
    ref = pointer(snapshot).model_dump(mode="json")
    if field == "manifest_byte_count":
        ref[field] += 1
    elif field in {"configuration_id", "configuration_revision_id"}:
        ref[field] = ref[field][:-32] + "9" * 32
    else:
        ref[field] = "sha256:" + "9" * 64
    with pytest.raises(ValueError):
        validate(snapshot, CudaHostExtensionPointer.model_validate(ref))


def test_base_seed_cannot_be_forged_even_with_rehashed_extension():
    changed = body()
    changed["base_host_seed_sha256"] = "sha256:" + "9" * 64
    with pytest.raises(ValueError):
        validate(CudaHostExtensionSnapshot.model_validate(rehash(changed)))


@pytest.mark.parametrize(
    "field",
    (
        "configuration_id",
        "configuration_revision_id",
        "manifest_byte_count",
        "manifest_raw_sha256",
        "snapshot_sha256",
    ),
)
def test_wrong_base_pointer_is_rejected_without_latest_substitution(field):
    changed = body()
    ref = changed["base_configuration"]
    if field == "manifest_byte_count":
        ref[field] += 1
    elif field in {"configuration_id", "configuration_revision_id"}:
        ref[field] = ref[field][:-32] + "9" * 32
    else:
        ref[field] = "sha256:" + "9" * 64
    with pytest.raises(ValueError):
        validate(CudaHostExtensionSnapshot.model_validate(rehash(changed)))


@pytest.mark.parametrize(
    "field,bad",
    (
        ("captured_at", "2026-10-17T00:45:00+09:00"),
        ("captured_at", "2026-10-16T15:45:00"),
        ("driver_release", "latest"),
        ("driver_release", "580.126.09/../"),
        ("configuration_revision_id", "latest"),
    ),
)
def test_closed_identity_driver_and_utc_values(field, bad):
    changed = body()
    changed[field] = bad
    with pytest.raises(ERRORS):
        CudaHostExtensionSnapshot.model_validate(rehash(changed))


@pytest.mark.parametrize("field", ("host_seed_sha256", "snapshot_sha256"))
def test_semantic_and_runtime_hashes_cannot_be_substituted(field):
    changed = body()
    changed[field] = "sha256:" + "9" * 64
    with pytest.raises(ValueError):
        CudaHostExtensionSnapshot.model_validate(changed)


@pytest.mark.parametrize("raw", (b"[" * 1500 + b"]" * 1500, b"\xff", b"{}", b" " * 8193))
def test_raw_manifest_bounds_encoding_and_shape(raw):
    with pytest.raises(ERRORS):
        parse_cuda_host_extension_bytes(raw)


def test_duplicate_json_keys_noncanonical_bytes_and_corrupt_copies_are_rejected():
    snapshot = CudaHostExtensionSnapshot.model_validate(body())
    raw = cuda_host_extension_bytes(snapshot)
    for bad in (
        b" " + raw,
        raw[:-1] + b',"driver_release":"580.126.09"}',
        json.dumps(body()).encode(),
    ):
        with pytest.raises(ERRORS):
            parse_cuda_host_extension_bytes(bad)
    bad_member = snapshot.libraries[0].model_copy(update={"byte_count": True})
    with pytest.raises(ERRORS):
        cuda_host_extension_bytes(
            snapshot.model_copy(update={"libraries": (bad_member, *snapshot.libraries[1:])})
        )
    assert raw == canonical_json_bytes(snapshot.model_dump(mode="json"))


def test_all_predecessor_resource_metadata_and_bytes_remain_unchanged():
    previous = {
        name: asdict(value)
        for name, value in CATALOG_SCHEMA_RESOURCES.items()
        if name
        not in {
            CUDA_HOST_SCHEMA,
            "embedding-cuda-host-extension-v1.1",
            "embedding-native-runtime-config-v1.2",
            "embedding-prefix-audit-input-v1.2",
            "embedding-native-cuda-probe",
            "embedding-native-cuda-probe-lease-ready",
            "system-rag-exam-observation",
            "system-rag-exam-observation-read",
        }
    }
    # Pinned after independently inspecting the current predecessor registry.
    assert len(previous) == 322
    assert content_sha256(previous) == (
        "sha256:99eb601c6b5fbd7e21bb57c7c6b52cf43b7c6839905333836a277dc580449953"
    )
    for name in previous:
        resource = CATALOG_SCHEMA_RESOURCES[name]
        raw = (ROOT / resource.canonical_path).read_bytes()
        assert sha256_bytes(raw) == resource.sha256
        assert (
            raw
            == (
                ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
            ).read_bytes()
        )
