"""Synthetic filesystem/kernel ports, not root mount or native installation admission."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_catalog_contracts.embedding_host_configuration import (
    EmbeddingHostConfigurationPointer,
    host_configuration_snapshot_bytes,
    parse_host_configuration_snapshot,
)
from eom_catalog_service import embedding_host_configuration_files as snapshots
from eom_catalog_service import embedding_runtime_host_closure as host
from eom_catalog_service.embedding_runtime_files import (
    InstalledRuntimeProofError,
    NumericalRuntimeFileSnapshots,
)
from eom_identifiers import content_sha256, sha256_bytes

from tests.unit.test_embedding_host_configuration_contracts import snapshot_body, snapshot_pointer
from tests.unit.test_embedding_runtime_host_closure import _cache
from tests.unit.test_embedding_runtime_host_closure import _fixture as host_fixture


def _write(path: Path, raw: bytes) -> None:
    if path.exists():
        path.chmod(0o600)
    path.write_bytes(raw)
    path.chmod(0o444)


@dataclass
class Fixture:
    root: Path
    manifest: Path
    cache: Path
    pointer: EmbeddingHostConfigurationPointer

    def resolve(self) -> snapshots.ResolvedEmbeddingHostConfiguration:
        return snapshots.resolve_host_configuration_snapshot(self.pointer)


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Fixture:
    tmp_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp_path.chmod(0o700)
    root = tmp_path / "snapshots"
    body = snapshot_body()
    directory = root / body["configuration_id"] / body["configuration_revision_id"]
    directory.mkdir(mode=0o700, parents=True)
    for parent in (root, directory.parent):
        parent.chmod(0o700)
    cache = _cache(
        (
            *(
                (name, "/lib/x86_64-linux-gnu/" + name, 0x303, 0, 0)
                for name in sorted(host._SONAMES)
                if name != "ld-linux-x86-64.so.2"
            ),
            ("libunrelated.so.1", "/lib/x86_64-linux-gnu/libunrelated.so.1", 0x303, 0, 0),
        )
    )
    body["loader_cache"].update(byte_count=len(cache), sha256=sha256_bytes(cache))
    body["baseline_host_seed_sha256"] = host.FIXED_EMBEDDING_HOST_SEED_SHA256
    body["host_seed_sha256"] = host.embedding_host_configuration_seed(
        cache_byte_count=len(cache), cache_sha256=sha256_bytes(cache)
    )
    body["snapshot_sha256"] = content_sha256(
        {k: v for k, v in body.items() if k != "snapshot_sha256"}
    )
    snapshot = parse_host_configuration_snapshot(body)
    manifest, member = directory / "snapshot.json", directory / "ld.so.cache"
    _write(manifest, host_configuration_snapshot_bytes(snapshot))
    _write(member, cache)
    monkeypatch.setattr(snapshots, "_ROOT", root)
    # Actual nonroot files/FDs are used; this source fixture grants no real root identity.
    monkeypatch.setattr(
        snapshots,
        "NumericalRuntimeFileSnapshots",
        lambda owner_uid: NumericalRuntimeFileSnapshots(os.geteuid()),
    )
    return Fixture(root, manifest, member, snapshot_pointer(snapshot))


def test_exact_snapshot_materialization_has_no_live_cache_or_authority_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    resolved = fixture.resolve()
    assert resolved.pointer == fixture.pointer and resolved.cache_path == fixture.cache
    assert resolved.cache_identity[:2] == (fixture.cache.stat().st_dev, fixture.cache.stat().st_ino)
    actual_open = os.open

    def denied_rehash(path: Any, *args: Any, **kwargs: Any) -> int:
        if path in {fixture.cache, fixture.manifest}:
            pytest.fail("immutable re-observation must not reopen/hash the payload")
        return actual_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", denied_rehash)
    for _ in range(3):
        resolved.assert_unchanged()
    assert not hasattr(resolved, "approved") and not hasattr(resolved, "cache_bytes")


@pytest.mark.parametrize(
    "fault",
    (
        "missing_manifest",
        "missing_cache",
        "manifest_link",
        "cache_link",
        "manifest_hardlink",
        "cache_hardlink",
        "manifest_mode",
        "cache_mode",
        "ancestor_mode",
        "manifest_hash",
        "cache_hash",
        "cache_shape",
    ),
)
def test_missing_stale_unsafe_and_corrupted_materialization_fails_explicitly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    if fault in {"missing_manifest", "missing_cache"}:
        (fixture.manifest if fault == "missing_manifest" else fixture.cache).unlink()
    elif fault in {"manifest_link", "cache_link"}:
        member = fixture.manifest if fault == "manifest_link" else fixture.cache
        retained = member.with_name(member.name + ".retained")
        member.rename(retained)
        member.symlink_to(retained)
    elif fault in {"manifest_hardlink", "cache_hardlink"}:
        member = fixture.manifest if fault == "manifest_hardlink" else fixture.cache
        member.with_name(member.name + ".hardlink").hardlink_to(member)
    elif fault in {"manifest_mode", "cache_mode"}:
        (fixture.manifest if fault == "manifest_mode" else fixture.cache).chmod(0o644)
    elif fault == "ancestor_mode":
        fixture.root.chmod(0o777)
    elif fault in {"manifest_hash", "cache_hash"}:
        member = fixture.manifest if fault == "manifest_hash" else fixture.cache
        raw = member.read_bytes()
        _write(member, b"x" + raw[1:])
    else:
        # Valid pointer/hash but not a valid closed loader cache; raw pin is not parser admission.
        raw = b"x" * fixture.cache.stat().st_size
        _write(fixture.cache, raw)
        body = snapshot_body()
        body["loader_cache"].update(byte_count=len(raw), sha256=sha256_bytes(raw))
        body["baseline_host_seed_sha256"] = host.FIXED_EMBEDDING_HOST_SEED_SHA256
        body["host_seed_sha256"] = host.embedding_host_configuration_seed(
            cache_byte_count=len(raw), cache_sha256=sha256_bytes(raw)
        )
        body["snapshot_sha256"] = content_sha256(
            {k: v for k, v in body.items() if k != "snapshot_sha256"}
        )
        snapshot = parse_host_configuration_snapshot(body)
        _write(fixture.manifest, host_configuration_snapshot_bytes(snapshot))
        fixture.pointer = snapshot_pointer(snapshot)
    with pytest.raises(snapshots.HostConfigurationSnapshotError) as error:
        fixture.resolve()
    assert error.value.code.startswith("HOST_CONFIGURATION_")
    if fault.endswith("hash"):
        assert error.value.code == "HOST_CONFIGURATION_HASH_MISMATCH"
    elif fault.startswith("missing"):
        assert error.value.code == "HOST_CONFIGURATION_MISSING"


@pytest.mark.parametrize("acl", ("system.posix_acl_access", "system.posix_acl_default"))
def test_named_or_default_acl_never_expands_installed_snapshot_permission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    acl: str,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(os, "listxattr", lambda *args, **kwargs: [acl])
    with pytest.raises(snapshots.HostConfigurationSnapshotError, match="PERMISSION_INVALID"):
        fixture.resolve()


@pytest.mark.parametrize("fault", ("cache", "manifest", "ancestor", "replacement"))
def test_resolution_rechecks_retained_epochs_and_never_repairs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    resolved = fixture.resolve()
    if fault in {"cache", "manifest"}:
        _write(fixture.cache if fault == "cache" else fixture.manifest, b"changed")
    elif fault == "ancestor":
        fixture.root.chmod(0o777)
    else:
        fixture.cache.rename(fixture.cache.with_name("retained"))
        _write(fixture.cache, b"changed")
    with pytest.raises(snapshots.HostConfigurationSnapshotError, match="CHANGED"):
        resolved.assert_unchanged()


def _mount_ports(monkeypatch: pytest.MonkeyPatch, fixture: Fixture) -> dict[str, Any]:
    state: dict[str, Any] = {
        "id": 77,
        "readonly": True,
        "namespace": (99, 101),
        "mountinfo_calls": 0,
    }
    monkeypatch.setattr(snapshots, "_CACHE", fixture.cache)
    monkeypatch.setattr(snapshots, "_mount_namespace_identity", lambda: state["namespace"])
    monkeypatch.setattr(
        os, "fstatvfs", lambda _: SimpleNamespace(f_flag=os.ST_RDONLY if state["readonly"] else 0)
    )

    def read(path: Path, *, maximum: int, owner_uid: int) -> bytes:
        assert owner_uid == os.geteuid() and path.parent.name in {str(os.getpid()), "fdinfo"}
        if path.name == "mountinfo":
            assert maximum == 1024**2
            state["mountinfo_calls"] += 1
            raw = state.get(
                "mountinfo", f"77 1 1:1 / {fixture.cache} ro - ext4 /dev/synthetic rw\n".encode()
            )
        else:
            assert maximum == 4096 and path.parent.name == "fdinfo" and path.name.isdigit()
            raw = state.get(
                "fdinfo", f"pos:\t0\nflags:\t0100000\nmnt_id:\t{state['id']}\nino:\t1\n".encode()
            )
        assert type(raw) is bytes
        return raw

    monkeypatch.setattr(snapshots, "read_live_runtime_os_file", read)
    return state


def test_mount_witness_requires_exact_binding_and_uses_small_own_fd_rechecks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    resolved = fixture.resolve()
    state = _mount_ports(monkeypatch, fixture)
    evidence = snapshots.require_host_configuration_snapshot_mount(resolved)
    assert evidence.mount_id == 77 and evidence.parent_mount_id == 1
    for _ in range(3):
        evidence.assert_unchanged()
    assert state["mountinfo_calls"] == 1
    assert not hasattr(evidence, "approved")


@pytest.mark.parametrize(
    "fault",
    (
        "writable",
        "missing",
        "duplicate",
        "wrong_record_id",
        "not_number",
        "oversize_id",
        "duplicate_fd_id",
        "changed_inode",
    ),
)
def test_missing_wrong_writable_or_malformed_mount_never_counts_as_runtime_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    resolved = fixture.resolve()
    state = _mount_ports(monkeypatch, fixture)
    if fault == "writable":
        state["readonly"] = False
    elif fault in {"missing", "duplicate", "wrong_record_id"}:
        line = f"77 1 1:1 / {fixture.cache} ro - ext4 /dev/synthetic rw\n".encode()
        state["mountinfo"] = (
            b""
            if fault == "missing"
            else line * 2
            if fault == "duplicate"
            else line.replace(b"77 1", b"78 1")
        )
    elif fault in {"not_number", "oversize_id", "duplicate_fd_id"}:
        state["fdinfo"] = {
            "not_number": b"mnt_id: invalid\n",
            "oversize_id": b"mnt_id: 999999999999\n",
            "duplicate_fd_id": b"mnt_id: 77\nmnt_id: 77\n",
        }[fault]
    else:
        copy = fixture.cache.with_name("same-bytes-different-inode")
        _write(copy, fixture.cache.read_bytes())
        monkeypatch.setattr(snapshots, "_CACHE", copy)
    with pytest.raises(snapshots.HostConfigurationSnapshotError, match="MOUNT"):
        snapshots.require_host_configuration_snapshot_mount(resolved)


@pytest.mark.parametrize("fault", ("namespace", "remount", "writable"))
def test_mounted_capture_detects_namespace_remount_or_permission_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    state = _mount_ports(monkeypatch, fixture)
    evidence = snapshots.require_host_configuration_snapshot_mount(fixture.resolve())
    state[{"namespace": "namespace", "remount": "id", "writable": "readonly"}[fault]] = (
        (99, 102) if fault == "namespace" else 78 if fault == "remount" else False
    )
    with pytest.raises(snapshots.HostConfigurationSnapshotError, match="MOUNT"):
        evidence.assert_unchanged()


@pytest.mark.parametrize("field", ("baseline_host_seed_sha256", "host_seed_sha256"))
def test_self_hashed_manifest_cannot_substitute_unrelated_host_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    body = fixture.resolve().snapshot.model_dump(mode="json")
    body[field] = "sha256:" + "e" * 64
    body["snapshot_sha256"] = content_sha256(
        {key: value for key, value in body.items() if key != "snapshot_sha256"}
    )
    changed = parse_host_configuration_snapshot(body)
    _write(fixture.manifest, host_configuration_snapshot_bytes(changed))
    fixture.pointer = snapshot_pointer(changed)
    with pytest.raises(snapshots.HostConfigurationSnapshotError, match="SEED_PIN_INVALID"):
        fixture.resolve()


def test_snapshot_and_legacy_capture_share_all_host_guards_without_changing_legacy_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = host_fixture(tmp_path / "host", monkeypatch)
    (tmp_path / "host").chmod(0o700)
    monkeypatch.setattr(host, "FIXED_EMBEDDING_HOST_SEED_SHA256", original.expected)
    monkeypatch.setattr(snapshots, "FIXED_EMBEDDING_HOST_SEED_SHA256", original.expected)
    fixture = _fixture(tmp_path / "snapshot", monkeypatch)
    resolved = fixture.resolve()
    target = resolved.snapshot.host_seed_sha256
    assert target != original.expected
    # Synthetic kernel witness below is not a real pre-exec binding. The independently
    # tested mount adapter owns that proof; this test exercises shared host capture.
    calls: list[None] = []
    monkeypatch.setattr(
        snapshots.EmbeddingHostSnapshotMount, "assert_unchanged", lambda _: calls.append(None)
    )
    witness = snapshots.EmbeddingHostSnapshotMount(resolved, 77, 1, (99, 101))
    _write(original.cache, fixture.cache.read_bytes())
    assert host._hash(host._seed_bytes()) == original.expected
    with pytest.raises(InstalledRuntimeProofError, match="FILE_SIZE_INVALID"):
        original.capture()
    closure = snapshots.capture_snapshot_embedding_host(
        expected_seed_sha256=target, files=original.files, snapshot_mount=witness
    )
    assert closure.seed_sha256 == target and len(calls) >= 2
    closure.assert_current()
    _write(original.library, b"modified library")
    with pytest.raises(InstalledRuntimeProofError):
        closure.assert_current()
    with pytest.raises(InstalledRuntimeProofError):
        closure.close()
    assert closure._closed


@pytest.mark.parametrize("fault", ("expected_seed", "baseline", "manifest_seed", "mount_drift"))
def test_snapshot_capture_rejects_invalid_selection_before_opening_host_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    state = _mount_ports(monkeypatch, fixture)
    witness = snapshots.require_host_configuration_snapshot_mount(fixture.resolve())
    expected = witness.configuration.snapshot.host_seed_sha256
    if fault == "expected_seed":
        expected = "sha256:" + "e" * 64
    elif fault == "mount_drift":
        state["id"] = 78
    else:
        field = "baseline_host_seed_sha256" if fault == "baseline" else "host_seed_sha256"
        forged = witness.configuration.snapshot.model_copy(update={field: "sha256:" + "e" * 64})
        object.__setattr__(witness.configuration, "snapshot", forged)

    def denied(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("invalid snapshot selection must not open host tools")

    monkeypatch.setattr(host, "_capture_embedding_host", denied)
    with pytest.raises((InstalledRuntimeProofError, snapshots.HostConfigurationSnapshotError)):
        snapshots.capture_snapshot_embedding_host(
            expected_seed_sha256=expected,
            files=NumericalRuntimeFileSnapshots(os.geteuid()),
            snapshot_mount=witness,
        )
