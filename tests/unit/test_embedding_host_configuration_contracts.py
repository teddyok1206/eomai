"""Schema-first tiny installation metadata; no host, model, DB or device admission."""

from __future__ import annotations

import copy
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from eom_catalog_contracts.embedding_host_configuration import (
    HOST_CONFIGURATION_MANIFEST_REF,
    HOST_CONFIGURATION_SCHEMA,
    HOST_CONFIGURATION_SCHEMA_REF,
    MAX_HOST_CONFIGURATION_BYTES,
    EmbeddingHostConfigurationPointer,
    EmbeddingHostConfigurationSnapshot,
    host_configuration_snapshot_bytes,
    parse_host_configuration_pointer,
    parse_host_configuration_snapshot,
    parse_host_configuration_snapshot_bytes,
    validate_host_configuration_pointer,
)
from eom_catalog_contracts.validation import (
    CATALOG_SCHEMA_RESOURCES,
    load_schema,
    validate_contract,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

ROOT = Path(__file__).resolve().parents[2]
ERRORS = (ValueError, SchemaError)


def snapshot_body() -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": "embedding-host-configuration-snapshot/1.0",
        "configuration_id": "embeddinghostconfig_" + "1" * 32,
        "configuration_revision_id": "embeddinghostconfigrev_" + "2" * 32,
        "captured_at": "2026-10-16T06:25:21Z",
        "baseline_host_seed_sha256": "sha256:" + "3" * 64,
        "host_seed_sha256": "sha256:" + "4" * 64,
        "loader_cache": {
            "role": "LD_SO_CACHE",
            "member_name": "ld.so.cache",
            "byte_count": 45467,
            "sha256": "sha256:" + "5" * 64,
        },
    }
    return body | {"snapshot_sha256": content_sha256(body)}


def snapshot_pointer(
    snapshot: EmbeddingHostConfigurationSnapshot,
) -> EmbeddingHostConfigurationPointer:
    raw = host_configuration_snapshot_bytes(snapshot)
    return EmbeddingHostConfigurationPointer(
        schema_ref=HOST_CONFIGURATION_MANIFEST_REF,
        configuration_id=snapshot.configuration_id,
        configuration_revision_id=snapshot.configuration_revision_id,
        manifest_byte_count=len(raw),
        manifest_raw_sha256=sha256_bytes(raw),
        snapshot_sha256=snapshot.snapshot_sha256,
    )


@pytest.mark.parametrize(
    "raw", (b"[" * 1500 + b"]" * 1500, b"\xff"), ids=("deep-array", "invalid-utf8")
)
def test_bounded_bytes_cannot_leak_recursion_or_unicode_parser_failures(raw: bytes) -> None:
    with pytest.raises(ValueError):
        parse_host_configuration_snapshot_bytes(raw)


def test_closed_2020_12_schema_mirror_raw_pin_and_package_exports() -> None:
    schema = load_schema(HOST_CONFIGURATION_SCHEMA)
    Draft202012Validator.check_schema(schema)
    assert schema["$id"] == HOST_CONFIGURATION_SCHEMA_REF
    assert all(
        schema["$defs"][name]["additionalProperties"] is False
        for name in ("snapshot", "pointer", "loaderCache")
    )
    resource = CATALOG_SCHEMA_RESOURCES[HOST_CONFIGURATION_SCHEMA]
    raw = (ROOT / resource.canonical_path).read_bytes()
    assert (
        raw
        == (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(raw) == resource.sha256
    import eom_catalog_contracts as public

    assert public.EmbeddingHostConfigurationSnapshot is EmbeddingHostConfigurationSnapshot
    assert public.validate_host_configuration_pointer is validate_host_configuration_pointer


def test_canonical_snapshot_pointer_revision_semantic_and_raw_hash_are_separate() -> None:
    snapshot = parse_host_configuration_snapshot(snapshot_body())
    raw = host_configuration_snapshot_bytes(snapshot)
    pointer = snapshot_pointer(snapshot)
    assert pointer.schema_ref == HOST_CONFIGURATION_MANIFEST_REF
    assert pointer.manifest_raw_sha256 != pointer.snapshot_sha256
    assert snapshot.configuration_id != snapshot.configuration_revision_id
    assert parse_host_configuration_snapshot_bytes(raw) == snapshot
    assert parse_host_configuration_pointer(pointer) == pointer
    assert validate_host_configuration_pointer(pointer, snapshot, raw) == snapshot
    validate_contract(HOST_CONFIGURATION_SCHEMA, snapshot.model_dump(mode="json"))
    validate_contract(HOST_CONFIGURATION_SCHEMA, pointer.model_dump(mode="json"))
    assert raw == canonical_json_bytes(snapshot.model_dump(mode="json"))
    with pytest.raises(ValueError):
        snapshot.host_seed_sha256 = "sha256:" + "0" * 64


def test_every_predecessor_schema_registry_entry_and_mirror_is_unchanged() -> None:
    # Independent development-time AST read of source692b6808, not a runtime Git lookup.
    previous = {
        name: resource
        for name, resource in CATALOG_SCHEMA_RESOURCES.items()
        if name not in {HOST_CONFIGURATION_SCHEMA, "embedding-native-runtime-config-v1.1"}
    }
    assert len(previous) == 316
    assert content_sha256({name: asdict(resource) for name, resource in previous.items()}) == (
        "sha256:6635684a61730ef6734ebd1ad07add8690b638f0fe460a4e9c2f4245e1071193"
    )
    for resource in previous.values():
        canonical = (ROOT / resource.canonical_path).read_bytes()
        packaged = (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
        assert canonical == packaged and sha256_bytes(canonical) == resource.sha256


@pytest.mark.parametrize(
    "field",
    (
        "manifest_byte_count",
        "manifest_raw_sha256",
        "snapshot_sha256",
        "configuration_id",
        "configuration_revision_id",
    ),
)
def test_pointer_requires_exact_byte_revision_and_semantic_closure(field: str) -> None:
    snapshot = parse_host_configuration_snapshot(snapshot_body())
    pointer = snapshot_pointer(snapshot)
    body = pointer.model_dump(mode="json")
    if field == "manifest_byte_count":
        body[field] += 1
    elif field == "configuration_id":
        body[field] = "embeddinghostconfig_" + "9" * 32
    elif field == "configuration_revision_id":
        body[field] = "embeddinghostconfigrev_" + "9" * 32
    else:
        body[field] = "sha256:" + "9" * 64
    with pytest.raises(ValueError):
        validate_host_configuration_pointer(
            parse_host_configuration_pointer(body),
            snapshot,
            host_configuration_snapshot_bytes(snapshot),
        )


@pytest.mark.parametrize("bad", (True, False, 45467.0, "45467", None, -1, 0, 131073))
def test_cache_byte_count_rejects_coercion_and_overflow_before_model_validation(
    bad: object,
) -> None:
    body = snapshot_body()
    body["loader_cache"]["byte_count"] = bad
    with pytest.raises(ERRORS):
        parse_host_configuration_snapshot(body)
    snapshot = parse_host_configuration_snapshot(snapshot_body())
    corrupt = snapshot.model_copy(
        update={"loader_cache": snapshot.loader_cache.model_copy(update={"byte_count": bad})}
    )
    with pytest.raises(ERRORS):
        host_configuration_snapshot_bytes(corrupt)


@pytest.mark.parametrize(
    "field,bad",
    (
        ("schema_version", "embedding-host-configuration-snapshot/2.0"),
        ("configuration_id", "../../other"),
        ("configuration_revision_id", "latest"),
        ("captured_at", "2026-10-16T15:25:21+09:00"),
        ("captured_at", "2026-10-16T06:25:21"),
        ("captured_at", "not-a-time"),
        ("baseline_host_seed_sha256", "version-only"),
        ("host_seed_sha256", b"not a string"),
        ("snapshot_sha256", "sha256:" + "0" * 64),
    ),
)
def test_snapshot_version_id_timestamp_and_hash_are_not_guessable(field: str, bad: object) -> None:
    body = snapshot_body()
    body[field] = bad
    with pytest.raises(ERRORS):
        parse_host_configuration_snapshot(body)


@pytest.mark.parametrize(
    "field,bad",
    (
        ("role", "APPROVED"),
        ("member_name", "/etc/ld.so.cache"),
        ("member_name", "../ld.so.cache"),
        ("sha256", "latest"),
    ),
)
def test_fixed_file_role_and_name_cannot_inject_a_path_or_authority(
    field: str, bad: object
) -> None:
    body = snapshot_body()
    body["loader_cache"][field] = bad
    body["snapshot_sha256"] = content_sha256(
        {k: v for k, v in body.items() if k != "snapshot_sha256"}
    )
    with pytest.raises(ERRORS):
        parse_host_configuration_snapshot(body)


@pytest.mark.parametrize("level", ("snapshot", "cache", "pointer"))
@pytest.mark.parametrize("extra", ("path", "actor_id", "approved", "device", "bytes"))
def test_unknown_payload_authority_and_paths_are_closed(level: str, extra: str) -> None:
    snapshot = parse_host_configuration_snapshot(snapshot_body())
    body = (
        snapshot_body()
        if level != "pointer"
        else snapshot_pointer(snapshot).model_dump(mode="json")
    )
    target = body["loader_cache"] if level == "cache" else body
    target[extra] = "not part of the protocol"
    with pytest.raises(ERRORS):
        (
            parse_host_configuration_pointer
            if level == "pointer"
            else parse_host_configuration_snapshot
        )(body)


@pytest.mark.parametrize(
    "mutation", ("extra", "missing", "nested_extra", "nested_missing", "cycle")
)
def test_constructed_or_copied_models_cannot_bypass_raw_validation(mutation: str) -> None:
    snapshot = parse_host_configuration_snapshot(snapshot_body())
    if mutation == "extra":
        corrupt = snapshot.model_copy(update={"approved": True})
    elif mutation == "missing":
        body = snapshot.model_dump(mode="python")
        del body["host_seed_sha256"]
        corrupt = EmbeddingHostConfigurationSnapshot.model_construct(**body)
    elif mutation == "nested_extra":
        corrupt = snapshot.model_copy(
            update={"loader_cache": snapshot.loader_cache.model_copy(update={"path": "/tmp/other"})}
        )
    elif mutation == "nested_missing":
        body = snapshot.loader_cache.model_dump(mode="python")
        del body["sha256"]
        corrupt = snapshot.model_copy(
            update={"loader_cache": type(snapshot.loader_cache).model_construct(**body)}
        )
    else:
        body = copy.deepcopy(snapshot_body())
        body["loader_cache"] = body
        with pytest.raises(ValueError):
            parse_host_configuration_snapshot(body)
        return
    with pytest.raises(ERRORS):
        host_configuration_snapshot_bytes(corrupt)


@pytest.mark.parametrize(
    "variant",
    (
        "newline",
        "pretty",
        "duplicate",
        "nested_duplicate",
        "float",
        "nan",
        "overflow",
        "list",
        "mutable",
    ),
)
def test_external_bytes_are_canonical_bounded_unique_and_integer_only(variant: str) -> None:
    snapshot = parse_host_configuration_snapshot(snapshot_body())
    raw = host_configuration_snapshot_bytes(snapshot)
    if variant == "newline":
        raw += b"\n"
    elif variant == "pretty":
        raw = json.dumps(snapshot.model_dump(mode="json"), indent=2).encode()
    elif variant == "duplicate":
        raw = raw.replace(b"{", b'{"captured_at":"2026-10-16T06:25:21Z",', 1)
    elif variant == "nested_duplicate":
        raw = raw.replace(b'"loader_cache":{', b'"loader_cache":{"role":"LD_SO_CACHE",')
    elif variant in {"float", "nan"}:
        raw = raw.replace(
            b'"byte_count":45467', b'"byte_count":' + (b"45467.0" if variant == "float" else b"NaN")
        )
    elif variant == "overflow":
        raw = b" " * (MAX_HOST_CONFIGURATION_BYTES + 1)
    elif variant == "list":
        raw = b"[]"
    else:
        with pytest.raises(ValueError):
            parse_host_configuration_snapshot_bytes(cast(bytes, bytearray(raw)))
        with pytest.raises(ValueError):
            validate_host_configuration_pointer(
                snapshot_pointer(snapshot), snapshot, cast(bytes, bytearray(raw))
            )
        return
    with pytest.raises(ERRORS):
        parse_host_configuration_snapshot_bytes(raw)


def test_python_utc_value_is_supported_without_accepting_a_naive_datetime() -> None:
    body = snapshot_body()
    body["captured_at"] = datetime(2026, 10, 16, 6, 25, 21, tzinfo=UTC)
    assert parse_host_configuration_snapshot(body).captured_at.utcoffset() == timedelta(0)
    body["captured_at"] = datetime(2026, 10, 16, 6, 25, 21)
    with pytest.raises(ValueError):
        parse_host_configuration_snapshot(body)
