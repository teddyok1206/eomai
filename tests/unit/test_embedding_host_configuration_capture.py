"""Stdlib/bootstrap versus schema-adapter parity; synthetic file/kernel ports only."""

from __future__ import annotations

import dataclasses
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.embedding_host_configuration import (
    EmbeddingHostConfigurationPointer,
    parse_host_configuration_pointer,
)
from eom_catalog_service import embedding_host_configuration_capture as capture
from eom_catalog_service import embedding_host_configuration_files as adapter
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.test_embedding_host_configuration_files import _fixture, _mount_ports, _write


def test_actual_no_site_import_excludes_contracts_third_party_models_and_storage() -> None:
    root = Path(capture.__file__).parent.parent
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-c",
            """
import sys
assert sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode
sys.path.insert(0,sys.argv[1])
import eom_catalog_service.embedding_host_configuration_capture as capture
for forbidden in ('pydantic','jsonschema','eom_catalog_contracts','eom_identifiers',
                  'torch','transformers','numpy','sqlalchemy','psycopg'):
 assert not any(name==forbidden or name.startswith(forbidden+'.') for name in sys.modules)
assert hasattr(capture,'capture_snapshot_embedding_host')
print('STDLIB_SNAPSHOT_CAPTURE_IMPORT=PASS')
""",
            str(root),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "STDLIB_SNAPSHOT_CAPTURE_IMPORT=PASS"


def test_bootstrap_and_runtime_share_exact_snapshot_and_kernel_witness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    pin = capture.parse_host_configuration_snapshot_pin(fixture.pointer.model_dump(mode="json"))
    core = capture.resolve_host_configuration_snapshot(pin)
    runtime = fixture.resolve()
    assert core.snapshot_raw == fixture.manifest.read_bytes()
    assert core.cache_identity == runtime.cache_identity and core.cache_path == runtime.cache_path
    assert core.host_seed_sha256 == runtime.host_seed_sha256
    assert (
        core.cache_byte_count == runtime.cache_byte_count
        and core.cache_sha256 == runtime.cache_sha256
    )
    state = _mount_ports(monkeypatch, fixture)
    low = capture.require_host_configuration_snapshot_mount(core)
    high = adapter.require_host_configuration_snapshot_mount(runtime)
    assert type(low) is capture.EmbeddingHostSnapshotMount
    assert type(high) is adapter.EmbeddingHostSnapshotMount
    assert adapter.EmbeddingHostSnapshotMount is capture.EmbeddingHostSnapshotMount
    assert (low.mount_id, low.namespace_identity) == (high.mount_id, high.namespace_identity)
    low.assert_unchanged()
    high.assert_unchanged()
    assert state["mountinfo_calls"] == 2


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("schema_ref", "eom://wrong/1.0"),
        ("configuration_id", "../escape"),
        ("configuration_revision_id", "embeddinghostconfigrev_latest"),
        ("manifest_byte_count", True),
        ("manifest_byte_count", 1.0),
        ("manifest_byte_count", 0),
        ("manifest_byte_count", 8193),
        ("manifest_raw_sha256", "sha256:" + "A" * 64),
        ("snapshot_sha256", None),
        ("path", "/tmp/untrusted"),
        ("authority", "ADMIN"),
    ),
)
def test_bootstrap_pointer_and_pydantic_contract_reject_the_same_invalid_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: Any
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    body = fixture.pointer.model_dump(mode="json")
    body[field] = value
    with pytest.raises(capture.HostConfigurationSnapshotError, match="POINTER_INVALID"):
        capture.parse_host_configuration_snapshot_pin(body)
    with pytest.raises((ValueError, SchemaError)):
        parse_host_configuration_pointer(body)


@pytest.mark.parametrize(
    "fault",
    (
        "extra",
        "version",
        "stamp",
        "noncanonical_stamp",
        "cache_bool",
        "cache_path",
        "cache_extra",
        "baseline",
        "seed",
        "semantic",
        "wrong_identity",
        "newline",
    ),
)
def test_both_readers_reject_corrupted_or_rehashed_manifest_without_live_cache_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    body = fixture.resolve().snapshot.model_dump(mode="json")
    if fault == "extra":
        body["authority"] = "ADMIN"
    elif fault == "version":
        body["schema_version"] = "embedding-host-configuration-snapshot/1.1"
    elif fault in {"stamp", "noncanonical_stamp"}:
        body["captured_at"] = "not-a-time" if fault == "stamp" else "2026-10-16T06:25:21+00:00"
    elif fault == "cache_bool":
        body["loader_cache"]["byte_count"] = True
    elif fault == "cache_path":
        body["loader_cache"]["member_name"] = "../ld.so.cache"
    elif fault == "cache_extra":
        body["loader_cache"]["approved"] = True
    elif fault in {"baseline", "seed"}:
        body["baseline_host_seed_sha256" if fault == "baseline" else "host_seed_sha256"] = (
            "sha256:" + "e" * 64
        )
    elif fault == "wrong_identity":
        body["configuration_id"] = "embeddinghostconfig_" + "e" * 32
    if fault == "semantic":
        body["snapshot_sha256"] = "sha256:" + "e" * 64
    else:
        body["snapshot_sha256"] = content_sha256(
            {key: value for key, value in body.items() if key != "snapshot_sha256"}
        )
    raw = canonical_json_bytes(body) + (b"\n" if fault == "newline" else b"")
    _write(fixture.manifest, raw)
    pointer_body = fixture.pointer.model_dump(mode="json")
    pointer_body.update(
        manifest_byte_count=len(raw),
        manifest_raw_sha256=sha256_bytes(raw),
        snapshot_sha256=body["snapshot_sha256"],
    )
    fixture.pointer = EmbeddingHostConfigurationPointer.model_validate(pointer_body)
    pin = capture.parse_host_configuration_snapshot_pin(pointer_body)
    for operation in (lambda: capture.resolve_host_configuration_snapshot(pin), fixture.resolve):
        with pytest.raises(capture.HostConfigurationSnapshotError):
            operation()


def test_constructed_bootstrap_pin_cannot_bypass_checks_before_file_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    pin = capture.parse_host_configuration_snapshot_pin(fixture.pointer.model_dump(mode="json"))
    object.__setattr__(pin, "manifest_byte_count", True)
    with pytest.raises(capture.HostConfigurationSnapshotError, match="POINTER_INVALID"):
        capture.resolve_host_configuration_snapshot(pin)
    with pytest.raises(ValueError):
        dataclasses.replace(pin, manifest_raw_sha256="unknown")
