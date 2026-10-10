"""Protected executable identity for maintenance-only Codex compatibility evidence."""

from __future__ import annotations

import hashlib
import os
import platform
import stat
from dataclasses import dataclass
from pathlib import Path

from eom_workflow.codex_compatibility import (
    CodexCompatibilityRuntime,
    compatibility_contract_sha256,
)

from eom_orchestrator.capability_observer import observe_codex_cli_surface
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.worker_auth import CODEX_BINARY
from eom_orchestrator.worker_systemd import WORKER_EXECUTABLE, WORKER_EXECUTABLE_SHA256

_DISTRIBUTION_ROOT = Path("/usr/local/lib/node_modules/@openai/codex")
_NATIVE_PACKAGES = {
    "x86_64": ("codex-linux-x64", "x86_64-unknown-linux-musl"),
    "aarch64": ("codex-linux-arm64", "aarch64-unknown-linux-musl"),
}
_MAX_EXECUTABLE_BYTES = 512 * 1024 * 1024


def _native_binary() -> Path:
    try:
        package, triple = _NATIVE_PACKAGES[platform.machine()]
    except KeyError as exc:
        raise ControlPlaneError(
            "CONTROL_COMPATIBILITY_RUNTIME_INVALID", "unsupported Codex installation layout"
        ) from exc
    return (
        _DISTRIBUTION_ROOT
        / "node_modules"
        / "@openai"
        / package
        / "vendor"
        / triple
        / "bin"
        / "codex"
    )


def _assert_protected_ancestors(path: Path) -> None:
    for parent in path.parents:
        parent_stat = parent.lstat()
        if (
            not stat.S_ISDIR(parent_stat.st_mode)
            or parent_stat.st_uid != 0
            or parent_stat.st_gid != 0
            or stat.S_IMODE(parent_stat.st_mode) & 0o022
        ):
            raise ValueError("unsafe protected executable ancestor")


def _identity(path: Path) -> tuple[int, int, int, int, int, int]:
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_gid != 0
        or stat.S_IMODE(metadata.st_mode) & 0o022
        or not 0 < metadata.st_size <= _MAX_EXECUTABLE_BYTES
        or metadata.st_nlink != 1
    ):
        raise ValueError("unsafe protected executable")
    _assert_protected_ancestors(path)
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
        metadata.st_mode,
    )


def _protected_hash(path: Path) -> str:
    before = _identity(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(descriptor)
        if (metadata.st_dev, metadata.st_ino) != before[:2]:
            raise ValueError("protected executable changed before read")
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        if _identity(path) != before:
            raise ValueError("protected executable changed during read")
        return "sha256:" + digest.hexdigest()
    finally:
        os.close(descriptor)


@dataclass(frozen=True, slots=True)
class CodexCompatibilityRuntimeGuard:
    """One hash pass per epoch; O(1) immutable file-identity checks before each launch."""

    runtime: CodexCompatibilityRuntime
    launcher: Path
    native_binary: Path
    identities: tuple[tuple[int, int, int, int, int, int], ...]

    def assert_current(self) -> None:
        try:
            _assert_protected_ancestors(CODEX_BINARY)
            link = CODEX_BINARY.lstat()
            if (
                link.st_uid != 0
                or link.st_gid != 0
                or CODEX_BINARY.resolve(strict=True) != self.launcher
                or tuple(
                    _identity(path)
                    for path in (self.launcher, self.native_binary, WORKER_EXECUTABLE)
                )
                != self.identities
            ):
                raise ValueError("Codex runtime changed")
        except (OSError, ValueError) as exc:
            raise ControlPlaneError(
                "CONTROL_COMPATIBILITY_RUNTIME_CHANGED", "Codex runtime changed during maintenance"
            ) from exc


def observe_compatibility_runtime_guard() -> CodexCompatibilityRuntimeGuard:
    try:
        _assert_protected_ancestors(CODEX_BINARY)
        link_metadata = CODEX_BINARY.lstat()
        if link_metadata.st_uid != 0 or link_metadata.st_gid != 0:
            raise ValueError("unsafe protected Codex launcher reference")
        launcher = CODEX_BINARY.resolve(strict=True)
        binary = _native_binary()
        paths = (launcher, binary, WORKER_EXECUTABLE)
        before = tuple(_identity(path) for path in paths)
        # Version/help observation belongs inside the same immutable file epoch as hashing.
        version, _flags = observe_codex_cli_surface()
        hashes = tuple(_protected_hash(path) for path in paths)
        after = tuple(_identity(path) for path in paths)
        if before != after or hashes[2] != "sha256:" + WORKER_EXECUTABLE_SHA256:
            raise ValueError("installed worker executable differs from released adapter")
        runtime = CodexCompatibilityRuntime(
            cli_version=version,
            cli_launcher_sha256=hashes[0],
            cli_binary_sha256=hashes[1],
            worker_exec_sha256=hashes[2],
            contract_sha256=compatibility_contract_sha256(),
        )
        guard = CodexCompatibilityRuntimeGuard(runtime, launcher, binary, after)
        guard.assert_current()
        return guard
    except (OSError, ValueError) as exc:
        raise ControlPlaneError(
            "CONTROL_COMPATIBILITY_RUNTIME_INVALID", "protected Codex runtime is unavailable"
        ) from exc


def observe_compatibility_runtime() -> CodexCompatibilityRuntime:
    """Public root-installer observation; never infer identity from a version string alone."""

    return observe_compatibility_runtime_guard().runtime
