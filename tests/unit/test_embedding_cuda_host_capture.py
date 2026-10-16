"""Synthetic file and kernel ports; no protected publication, ELF execution or GPU grant."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.embedding_cuda_host_extension import (
    CudaHostExtensionPointer,
    CudaHostExtensionSnapshot,
    parse_cuda_host_extension_bytes,
)
from eom_catalog_service import embedding_cuda_host_capture as capture
from eom_catalog_service import embedding_cuda_host_files as adapter
from eom_catalog_service import embedding_host_configuration_capture as base_capture
from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots
from eom_catalog_service.embedding_runtime_host_closure import embedding_host_loader_cache_routes
from eom_identifiers import canonical_json_bytes, sha256_bytes
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.test_embedding_cuda_host_extension import body, pointer, rehash
from tests.unit.test_embedding_host_configuration_files import (
    _fixture as base_fixture,
)
from tests.unit.test_embedding_host_configuration_files import _mount_ports, _write
from tests.unit.test_embedding_runtime_host_closure import _cache


@dataclass
class Fixture:
    manifest: Path
    cache: Path
    libraries: tuple[Path, ...]
    pointer: CudaHostExtensionPointer
    base_manifest: Path

    def resolve(self):
        return adapter.resolve_cuda_host_extension(self.pointer)

    def repin(self, document: dict[str, Any]) -> None:
        raw = canonical_json_bytes(rehash(document))
        _write(self.manifest, raw)
        # Allows corruption fixtures rejected by both readers, not an acceptance grant.
        self.pointer = CudaHostExtensionPointer.model_validate(
            self.pointer.model_dump(mode="json")
            | {
                "manifest_byte_count": len(raw),
                "manifest_raw_sha256": sha256_bytes(raw),
                "snapshot_sha256": document["snapshot_sha256"],
            }
        )


def fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Fixture:
    base = base_fixture(tmp_path / "base", monkeypatch)
    observed = base.resolve()
    document = body()
    document["base_configuration"] = base.pointer.model_dump(mode="json")
    document["base_host_seed_sha256"] = observed.host_seed_sha256
    root = tmp_path / "cuda"
    directory = root / document["configuration_id"] / document["configuration_revision_id"]
    directory.mkdir(parents=True, mode=0o700)
    for parent in (root, directory.parent):
        parent.chmod(0o700)
    libraries = []
    for row in document["libraries"]:
        path = directory / row["member_name"]
        raw = b"not-an-executable-test-member:" + row["role"].encode()
        row.update(byte_count=len(raw), sha256=sha256_bytes(raw))
        _write(path, raw)
        libraries.append(path)
    cache = _cache(
        tuple(
            (name, path, 0x303, 0, 0)
            for name, path in (
                *embedding_host_loader_cache_routes(),
                *(
                    (row["member_name"], str(directory / row["member_name"]))
                    for row in document["libraries"]
                ),
            )
        )
    )
    document["loader_cache"].update(byte_count=len(cache), sha256=sha256_bytes(cache))
    snapshot = CudaHostExtensionSnapshot.model_validate(rehash(document))
    manifest, member = directory / "snapshot.json", directory / "ld.so.cache"
    _write(manifest, canonical_json_bytes(snapshot.model_dump(mode="json")))
    _write(member, cache)
    monkeypatch.setattr(capture, "_ROOT", root)
    monkeypatch.setattr(
        capture,
        "NumericalRuntimeFileSnapshots",
        lambda _: NumericalRuntimeFileSnapshots(os.geteuid()),
    )
    return Fixture(manifest, member, tuple(libraries), pointer(snapshot), base.manifest)


def test_no_site_capture_import_has_no_model_contract_storage_or_execution_dependency():
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
sys.path.insert(0,sys.argv[1])
import eom_catalog_service.embedding_cuda_host_capture
for name in ('pydantic','jsonschema','eom_catalog_contracts','eom_identifiers',
             'torch','transformers','numpy','sqlalchemy','psycopg'):
 assert not any(k==name or k.startswith(name+'.') for k in sys.modules)
print('CUDA_CAPTURE_STDLIB=PASS')
""",
            str(root),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "CUDA_CAPTURE_STDLIB=PASS"


def test_schema_and_bootstrap_share_exact_root_capture_without_rehash_on_recheck(
    tmp_path, monkeypatch
):
    value = fixture(tmp_path, monkeypatch)
    actual_read = NumericalRuntimeFileSnapshots.read
    actual_verify = NumericalRuntimeFileSnapshots.verify
    limits: dict[str, int] = {}

    def read(files, path, **kwargs):
        assert path not in value.libraries, "library bytes must not be retained or duplicated"
        return actual_read(files, path, **kwargs)

    def verify(files, path, **kwargs):
        if path in value.libraries:
            limits[path.name] = kwargs["maximum"]
        return actual_verify(files, path, **kwargs)

    monkeypatch.setattr(NumericalRuntimeFileSnapshots, "read", read)
    monkeypatch.setattr(NumericalRuntimeFileSnapshots, "verify", verify)
    core = capture.resolve_cuda_host_extension(
        capture.parse_cuda_host_extension_pin(value.pointer.model_dump(mode="json"))
    )
    high = value.resolve()
    assert core.snapshot_raw == value.manifest.read_bytes()
    assert core.host_seed_sha256 == high.snapshot.host_seed_sha256
    assert high.captured.cache_identity == core.cache_identity
    assert tuple(row.member_name for row in core.libraries) == tuple(
        path.name for path in value.libraries
    )
    assert not hasattr(core, "approved") and not hasattr(core, "library_bytes")
    assert limits.pop("libcuda.so.1") == 128 * 1024 * 1024
    assert len(limits) == 5 and set(limits.values()) == {8 * 1024 * 1024}
    monkeypatch.setattr(
        os,
        "open",
        lambda *args, **kwargs: pytest.fail("epoch recheck cannot reopen or rehash bytes"),
    )
    core.assert_unchanged()
    high.assert_unchanged()


@pytest.mark.parametrize(
    "fault",
    (
        "library_missing",
        "manifest_missing",
        "cache_missing",
        "library_hash",
        "cache_hash",
        "manifest_hash",
        "library_mode",
        "library_link",
        "library_hardlink",
        "extra",
        "extra_directory",
        "base_changed",
        "base_seed",
    ),
)
def test_bad_or_dangling_files_never_substitute_latest_or_repair(tmp_path, monkeypatch, fault):
    value = fixture(tmp_path, monkeypatch)
    member = value.libraries[0]
    if fault.endswith("missing"):
        {
            "library_missing": member,
            "manifest_missing": value.manifest,
            "cache_missing": value.cache,
        }[fault].unlink()
    elif fault.endswith("hash"):
        target = {
            "library_hash": member,
            "cache_hash": value.cache,
            "manifest_hash": value.manifest,
        }[fault]
        raw = target.read_bytes()
        _write(target, b"x" + raw[1:])
    elif fault == "library_mode":
        member.chmod(0o644)
    elif fault == "library_link":
        member.rename(member.with_name("retained"))
        member.symlink_to("retained")
    elif fault == "library_hardlink":
        member.with_name("hardlink").hardlink_to(member)
    elif fault == "extra":
        _write(member.with_name("undeclared.so"), b"untrusted")
    elif fault == "extra_directory":
        member.with_name("undeclared").mkdir()
    elif fault == "base_changed":
        _write(value.base_manifest, b"changed")
    else:
        document = parse_cuda_host_extension_bytes(value.manifest.read_bytes()).model_dump(
            mode="json"
        )
        document["base_host_seed_sha256"] = "sha256:" + "9" * 64
        value.repin(document)
    with pytest.raises(capture.CudaHostExtensionError):
        value.resolve()


@pytest.mark.parametrize("fault", ("library", "cache", "manifest", "base", "namespace"))
def test_retained_file_and_ancestor_epochs_detect_later_change(tmp_path, monkeypatch, fault):
    value = fixture(tmp_path, monkeypatch)
    selected = value.resolve()
    if fault == "namespace":
        _write(value.manifest.parent / "late.so", b"later")
    else:
        _write(
            {
                "library": value.libraries[0],
                "cache": value.cache,
                "manifest": value.manifest,
                "base": value.base_manifest,
            }[fault],
            b"later",
        )
    with pytest.raises(capture.CudaHostExtensionError, match="CHANGED"):
        selected.assert_unchanged()


@pytest.mark.parametrize(
    "fault", ("unknown", "duplicate", "missing", "wrong_revision", "abi", "hardware", "osversion")
)
def test_closed_cuda_cache_rejects_routes_even_when_metadata_hashes_are_recomputed(
    tmp_path, monkeypatch, fault
):
    value = fixture(tmp_path, monkeypatch)
    rows = [(name, path, 0x303, 0, 0) for name, path in embedding_host_loader_cache_routes()]
    rows.extend((path.name, str(path), 0x303, 0, 0) for path in value.libraries)
    name, path, abi, version, hardware = rows[-1]
    if fault == "unknown":
        rows.append(("unknown.so.1", "/tmp/unknown.so.1", 0x303, 0, 0))
    elif fault == "duplicate":
        rows.append(rows[-1])
    elif fault == "missing":
        rows.pop()
    else:
        rows[-1] = (
            name,
            path + ".wrong" if fault == "wrong_revision" else path,
            0x301 if fault == "abi" else abi,
            1 if fault == "osversion" else version,
            1 if fault == "hardware" else hardware,
        )
    raw = _cache(tuple(rows))
    _write(value.cache, raw)
    document = parse_cuda_host_extension_bytes(value.manifest.read_bytes()).model_dump(mode="json")
    document["loader_cache"].update(byte_count=len(raw), sha256=sha256_bytes(raw))
    value.repin(document)
    with pytest.raises(capture.CudaHostExtensionError, match="CACHE_"):
        value.resolve()


def test_kernel_witness_is_for_cuda_cache_not_base_cpu_cache(tmp_path, monkeypatch):
    value = fixture(tmp_path, monkeypatch)
    selected = value.resolve().captured
    assert selected.cache_identity != selected.base_configuration.cache_identity
    state = _mount_ports(monkeypatch, value)
    witness = base_capture.require_host_configuration_snapshot_mount(selected)
    assert witness.mount_id == 77 and state["mountinfo_calls"] == 1
    witness.assert_unchanged()
    state["readonly"] = False
    with pytest.raises(base_capture.HostConfigurationSnapshotError, match="MOUNT_"):
        witness.assert_unchanged()


@pytest.mark.parametrize(
    "field,bad",
    (
        ("manifest_byte_count", True),
        ("schema_ref", "latest"),
        ("configuration_id", "../escape"),
        ("configuration_revision_id", "latest"),
        ("path", "/tmp/override"),
    ),
)
def test_invalid_bootstrap_and_schema_pointer_fail_before_any_file_read(
    tmp_path, monkeypatch, field, bad
):
    value = fixture(tmp_path, monkeypatch)
    raw = value.pointer.model_dump(mode="json")
    raw[field] = bad
    monkeypatch.setattr(
        os, "open", lambda *args, **kwargs: pytest.fail("invalid pointer must not open files")
    )
    with pytest.raises(capture.CudaHostExtensionError, match="POINTER_INVALID"):
        capture.parse_cuda_host_extension_pin(raw)
    with pytest.raises((ValueError, SchemaError)):
        CudaHostExtensionPointer.model_validate(raw)


@pytest.mark.parametrize(
    "fault", ("duplicate_member", "order", "bool_size", "timestamp", "extra", "duplicate_key")
)
def test_stdlib_and_schema_manifest_readers_reject_the_same_corrupt_bytes(
    tmp_path, monkeypatch, fault
):
    value = fixture(tmp_path, monkeypatch)
    document = parse_cuda_host_extension_bytes(value.manifest.read_bytes()).model_dump(mode="json")
    if fault == "duplicate_member":
        document["libraries"][1] = document["libraries"][0].copy()
    elif fault == "order":
        document["libraries"].reverse()
    elif fault == "bool_size":
        document["libraries"][0]["byte_count"] = True
    elif fault == "timestamp":
        document["captured_at"] = "2026-10-16T15:45:00+00:00"
    elif fault == "extra":
        document["authority"] = "ADMIN"
    value.repin(document)
    raw = value.manifest.read_bytes()
    if fault == "duplicate_key":
        raw = raw[:-1] + b',"driver_release":"580.126.09"}'
    with pytest.raises((ValueError, SchemaError)):
        parse_cuda_host_extension_bytes(raw)
    with pytest.raises(capture.CudaHostExtensionError):
        capture._manifest(
            raw, capture.parse_cuda_host_extension_pin(value.pointer.model_dump(mode="json"))
        )


@pytest.mark.parametrize(
    "attribute", ("security.capability", "system.posix_acl_access", "system.posix_acl_default")
)
def test_unexpected_permissions_never_become_cuda_execution_authority(
    tmp_path, monkeypatch, attribute
):
    value = fixture(tmp_path, monkeypatch)
    actual = os.listxattr

    def names(path, **kwargs):
        return [attribute] if path == value.libraries[0] else actual(path, **kwargs)

    monkeypatch.setattr(os, "listxattr", names)
    with pytest.raises(capture.CudaHostExtensionError, match="PERMISSION_INVALID"):
        value.resolve()


def test_constructed_pin_is_revalidated_before_opening_files(tmp_path, monkeypatch):
    value = fixture(tmp_path, monkeypatch)
    pin = capture.parse_cuda_host_extension_pin(value.pointer.model_dump(mode="json"))
    object.__setattr__(pin, "manifest_byte_count", True)
    monkeypatch.setattr(
        os, "open", lambda *args, **kwargs: pytest.fail("invalid pin cannot open files")
    )
    with pytest.raises(capture.CudaHostExtensionError, match="POINTER_INVALID"):
        capture.resolve_cuda_host_extension(pin)


@pytest.mark.parametrize("raw", (b"\xff", b"[" * 1500 + b"]" * 1500, b"x" * 8193))
def test_raw_parser_rejects_untrusted_encoding_depth_and_overflow(tmp_path, monkeypatch, raw):
    value = fixture(tmp_path, monkeypatch)
    with pytest.raises(capture.CudaHostExtensionError):
        capture._manifest(
            raw, capture.parse_cuda_host_extension_pin(value.pointer.model_dump(mode="json"))
        )
