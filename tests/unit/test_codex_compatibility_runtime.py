from __future__ import annotations

import hashlib
import os
import platform
import stat
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_orchestrator import codex_compatibility_runtime as runtime
from eom_orchestrator.control_service import ControlPlaneError
from eom_workflow.codex_compatibility import compatibility_contract_sha256


@pytest.fixture
def protected_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, Path, Path, dict[Path, dict[str, int]]]:
    distribution_root = tmp_path / "distribution"
    launcher = distribution_root / "bin" / "codex.js"
    native = (
        distribution_root
        / "node_modules"
        / "@openai"
        / "codex-linux-x64"
        / "vendor"
        / "x86_64-unknown-linux-musl"
        / "bin"
        / "codex"
    )
    worker = tmp_path / "libexec" / "worker"
    for path, payload in (
        (launcher, b"launcher"),
        (native, b"native executable"),
        (worker, b"worker"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        path.chmod(0o755)
    codex_link = tmp_path / "link-bin" / "codex"
    codex_link.parent.mkdir()
    codex_link.symlink_to(launcher)
    monkeypatch.setattr(runtime, "CODEX_BINARY", codex_link)
    monkeypatch.setattr(runtime, "WORKER_EXECUTABLE", worker)
    monkeypatch.setattr(runtime, "WORKER_EXECUTABLE_SHA256", hashlib.sha256(b"worker").hexdigest())
    monkeypatch.setattr(runtime, "_DISTRIBUTION_ROOT", distribution_root)
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(runtime, "observe_codex_cli_surface", lambda: ("0.160.0", frozenset()))
    overrides: dict[Path, dict[str, int]] = {}
    actual_lstat = Path.lstat

    def trusted_lstat(path: Path) -> Any:
        actual = actual_lstat(path)
        values = {
            name: getattr(actual, name)
            for name in (
                "st_mode",
                "st_uid",
                "st_gid",
                "st_nlink",
                "st_size",
                "st_dev",
                "st_ino",
                "st_mtime_ns",
                "st_ctime_ns",
            )
        }
        values.update(st_uid=0, st_gid=0)
        # The fixture is synthetic root-protected storage, not an assertion that /tmp
        # or the real unprivileged test owner is safe for installed runtime artifacts.
        if stat.S_ISDIR(actual.st_mode):
            values["st_mode"] = stat.S_IFDIR | 0o755
        values.update(overrides.get(path, {}))
        return SimpleNamespace(**values)

    monkeypatch.setattr(Path, "lstat", trusted_lstat)
    return launcher, native, worker, codex_link, overrides


def test_runtime_binds_native_binary_not_only_launcher_and_worker(
    protected_runtime: tuple[Path, Path, Path, Path, dict[Path, dict[str, int]]],
) -> None:
    launcher, native, worker, _, _ = protected_runtime

    guard = runtime.observe_compatibility_runtime_guard()

    assert guard.runtime.cli_version == "0.160.0"
    assert (
        guard.runtime.cli_launcher_sha256
        == "sha256:" + hashlib.sha256(launcher.read_bytes()).hexdigest()
    )
    assert (
        guard.runtime.cli_binary_sha256
        == "sha256:" + hashlib.sha256(native.read_bytes()).hexdigest()
    )
    assert (
        guard.runtime.worker_exec_sha256
        == "sha256:" + hashlib.sha256(worker.read_bytes()).hexdigest()
    )
    assert guard.runtime.contract_sha256 == compatibility_contract_sha256()
    assert guard.launcher == launcher and guard.native_binary == native
    guard.assert_current()
    assert runtime.observe_compatibility_runtime() == guard.runtime
    with pytest.raises(FrozenInstanceError):
        guard.launcher = native  # type: ignore[misc]


@pytest.mark.parametrize("component", [0, 1, 2])
def test_guard_rejects_any_executable_changed_after_hashing(
    protected_runtime: tuple[Path, Path, Path, Path, dict[Path, dict[str, int]]], component: int
) -> None:
    guard = runtime.observe_compatibility_runtime_guard()
    path = protected_runtime[:3][component]
    path.write_bytes(path.read_bytes() + b"changed")

    with pytest.raises(ControlPlaneError) as error:
        guard.assert_current()

    assert error.value.code == "CONTROL_COMPATIBILITY_RUNTIME_CHANGED"


def test_runtime_epoch_includes_cli_surface_observation(
    protected_runtime: tuple[Path, Path, Path, Path, dict[Path, dict[str, int]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, native, _, _, _ = protected_runtime

    def concurrent_update() -> tuple[str, frozenset[str]]:
        native.write_bytes(b"new binary while the old CLI version was observed")
        return "0.160.0", frozenset()

    monkeypatch.setattr(runtime, "observe_codex_cli_surface", concurrent_update)

    with pytest.raises(ControlPlaneError) as error:
        runtime.observe_compatibility_runtime_guard()

    assert error.value.code == "CONTROL_COMPATIBILITY_RUNTIME_INVALID"


def test_guard_rejects_launcher_link_retargeting(
    protected_runtime: tuple[Path, Path, Path, Path, dict[Path, dict[str, int]]],
) -> None:
    _, native, _, link, _ = protected_runtime
    guard = runtime.observe_compatibility_runtime_guard()
    link.unlink()
    link.symlink_to(native)

    with pytest.raises(ControlPlaneError) as error:
        guard.assert_current()

    assert error.value.code == "CONTROL_COMPATIBILITY_RUNTIME_CHANGED"


@pytest.mark.parametrize(
    "override",
    [
        {"st_uid": 1000},
        {"st_gid": 1000},
        {"st_mode": stat.S_IFDIR | 0o775},
        {"st_mode": stat.S_IFLNK | 0o777},
    ],
)
def test_guard_rejects_unsafe_cli_link_ancestor_separate_from_target_ancestry(
    protected_runtime: tuple[Path, Path, Path, Path, dict[Path, dict[str, int]]],
    override: dict[str, int],
) -> None:
    _, _, _, link, overrides = protected_runtime
    guard = runtime.observe_compatibility_runtime_guard()
    overrides[link.parent] = override

    with pytest.raises(ControlPlaneError) as error:
        guard.assert_current()

    assert error.value.code == "CONTROL_COMPATIBILITY_RUNTIME_CHANGED"


def test_unsafe_cli_link_parent_is_rejected_before_executing_surface_observation(
    protected_runtime: tuple[Path, Path, Path, Path, dict[Path, dict[str, int]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, _, link, overrides = protected_runtime
    overrides[link.parent] = {"st_mode": stat.S_IFDIR | 0o775}
    observations: list[str] = []

    def observe() -> tuple[str, frozenset[str]]:
        observations.append("must not execute through unsafe parent")
        return "0.160.0", frozenset()

    monkeypatch.setattr(runtime, "observe_codex_cli_surface", observe)

    with pytest.raises(ControlPlaneError):
        runtime.observe_compatibility_runtime_guard()

    assert not observations


@pytest.mark.parametrize(
    "override",
    [
        {"st_uid": 1000},
        {"st_gid": 1000},
        {"st_mode": stat.S_IFREG | 0o775},
        {"st_mode": stat.S_IFREG | 0o757},
        {"st_mode": stat.S_IFLNK | 0o777},
        {"st_nlink": 2},
        {"st_size": 0},
        {"st_size": 512 * 1024 * 1024 + 1},
    ],
)
def test_observation_rejects_unsafe_protected_file_metadata(
    protected_runtime: tuple[Path, Path, Path, Path, dict[Path, dict[str, int]]],
    override: dict[str, int],
) -> None:
    _, native, _, _, overrides = protected_runtime
    overrides[native] = override

    with pytest.raises(ControlPlaneError) as error:
        runtime.observe_compatibility_runtime_guard()

    assert error.value.code == "CONTROL_COMPATIBILITY_RUNTIME_INVALID"


@pytest.mark.parametrize(
    "override",
    [
        {"st_uid": 1000},
        {"st_gid": 1000},
        {"st_mode": stat.S_IFDIR | 0o775},
        {"st_mode": stat.S_IFLNK | 0o777},
    ],
)
def test_observation_rejects_unsafe_ancestor_metadata(
    protected_runtime: tuple[Path, Path, Path, Path, dict[Path, dict[str, int]]],
    override: dict[str, int],
) -> None:
    _, native, _, _, overrides = protected_runtime
    overrides[native.parent] = override

    with pytest.raises(ControlPlaneError) as error:
        runtime.observe_compatibility_runtime_guard()

    assert error.value.code == "CONTROL_COMPATIBILITY_RUNTIME_INVALID"


def test_unreleased_worker_hash_fails_closed(
    protected_runtime: tuple[Path, Path, Path, Path, dict[Path, dict[str, int]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime, "WORKER_EXECUTABLE_SHA256", "0" * 64)

    with pytest.raises(ControlPlaneError) as error:
        runtime.observe_compatibility_runtime_guard()

    assert error.value.code == "CONTROL_COMPATIBILITY_RUNTIME_INVALID"


def test_unsupported_native_layout_fails_closed(
    protected_runtime: tuple[Path, Path, Path, Path, dict[Path, dict[str, int]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "machine", lambda: "unreviewed-architecture")

    with pytest.raises(ControlPlaneError) as error:
        runtime.observe_compatibility_runtime_guard()

    assert error.value.code == "CONTROL_COMPATIBILITY_RUNTIME_INVALID"


def test_hash_rejects_change_between_identity_check_and_open(
    protected_runtime: tuple[Path, Path, Path, Path, dict[Path, dict[str, int]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, native, _, _, _ = protected_runtime
    actual_fstat = os.fstat

    def changed_fstat(descriptor: int) -> Any:
        metadata = actual_fstat(descriptor)
        return SimpleNamespace(st_dev=metadata.st_dev, st_ino=metadata.st_ino + 1)

    monkeypatch.setattr(os, "fstat", changed_fstat)

    with pytest.raises(ValueError, match="before read"):
        runtime._protected_hash(native)


def test_hash_rejects_in_place_change_during_read(
    protected_runtime: tuple[Path, Path, Path, Path, dict[Path, dict[str, int]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, native, _, _, _ = protected_runtime
    actual_read = os.read
    changed = False

    def mutate_on_read(descriptor: int, size: int) -> bytes:
        nonlocal changed
        chunk = actual_read(descriptor, size)
        if not changed:
            changed = True
            native.write_bytes(b"mutated native executable")
        return chunk

    monkeypatch.setattr(os, "read", mutate_on_read)

    with pytest.raises(ValueError, match="during read"):
        runtime._protected_hash(native)


def test_guard_identity_recheck_does_not_rehash_large_immutable_files(
    protected_runtime: tuple[Path, Path, Path, Path, dict[Path, dict[str, int]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = runtime.observe_compatibility_runtime_guard()

    def forbid_read(*_: object) -> None:
        raise AssertionError("immutable runtime must not be rehashed for every case")

    monkeypatch.setattr(os, "read", forbid_read)
    guard.assert_current()
