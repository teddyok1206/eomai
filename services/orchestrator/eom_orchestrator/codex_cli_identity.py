"""One protected installed CLI identity boundary for maintenance and native chat."""

from __future__ import annotations

import hashlib
import os
import platform
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from eom_protocol.general_chat_worker_messages import CodexCliIdentity

DISTRIBUTION_ROOT = Path("/usr/local/lib/node_modules/@openai/codex")
_NATIVE_PACKAGES = {
    "x86_64": ("codex-linux-x64", "x86_64-unknown-linux-musl"),
    "aarch64": ("codex-linux-arm64", "aarch64-unknown-linux-musl"),
}
_MAX_EXECUTABLE_BYTES = 512 * 1024 * 1024
FileEpoch = tuple[int, int, int, int, int, int]


def native_binary_path(distribution_root: Path) -> Path:
    try:
        package, triple = _NATIVE_PACKAGES[platform.machine()]
    except KeyError as exc:
        raise ValueError("unsupported Codex installation layout") from exc
    return (
        distribution_root
        / "node_modules"
        / "@openai"
        / package
        / "vendor"
        / triple
        / "bin"
        / "codex"
    )


def assert_protected_ancestors(path: Path) -> None:
    for parent in path.parents:
        metadata = parent.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_gid != 0
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            raise ValueError("unsafe protected executable ancestor")


def protected_launcher_target(reference: Path) -> Path:
    assert_protected_ancestors(reference)
    metadata = reference.lstat()
    if metadata.st_uid != 0 or metadata.st_gid != 0:
        raise ValueError("unsafe protected Codex launcher reference")
    target = reference.resolve(strict=True)
    protected_file_identity(target)
    return target


def protected_file_identity(path: Path) -> FileEpoch:
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
    assert_protected_ancestors(path)
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
        metadata.st_mode,
    )


def protected_file_hash(path: Path) -> str:
    before = protected_file_identity(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(descriptor)
        if (metadata.st_dev, metadata.st_ino) != before[:2]:
            raise ValueError("protected executable changed before read")
        digest = hashlib.sha256()
        size = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            size += len(chunk)
            if size > before[2]:
                raise ValueError("protected executable changed during read")
            digest.update(chunk)
        if size != before[2] or protected_file_identity(path) != before:
            raise ValueError("protected executable changed during read")
        return "sha256:" + digest.hexdigest()
    finally:
        os.close(descriptor)


@dataclass(frozen=True, slots=True)
class CodexCliIdentityGuard:
    identity: CodexCliIdentity
    launcher_reference: Path
    launcher: Path
    native_binary: Path
    epochs: tuple[FileEpoch, FileEpoch]

    def assert_unchanged(self) -> None:
        """Metadata only: never rehash an immutable binary on each chat turn."""
        if (
            protected_launcher_target(self.launcher_reference) != self.launcher
            or (protected_file_identity(self.launcher), protected_file_identity(self.native_binary))
            != self.epochs
        ):
            raise ValueError("Codex executable identity changed")


def capture_codex_cli_identity(launcher: Path) -> CodexCliIdentityGuard:
    """Observe installed version and bytes in one epoch; never activate this selection."""
    target = protected_launcher_target(launcher)
    if target != DISTRIBUTION_ROOT / "bin" / "codex.js":
        raise ValueError("unsupported Codex launcher layout")
    native = native_binary_path(DISTRIBUTION_ROOT)
    before = (protected_file_identity(target), protected_file_identity(native))
    version = subprocess.run(
        [str(launcher), "--version"],
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "NO_COLOR": "1"},
        cwd="/",
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )
    if version.returncode != 0 or len(version.stdout) > 128:
        raise ValueError("Codex version unavailable")
    match = re.fullmatch(rb"codex-cli ([0-9]+\.[0-9]+\.[0-9]+)\n?", version.stdout)
    if match is None:
        raise ValueError("unsupported Codex version")
    identity = CodexCliIdentity(
        cli_version=match[1].decode("ascii"),
        cli_launcher_sha256=protected_file_hash(target),
        cli_binary_sha256=protected_file_hash(native),
    )
    guard = CodexCliIdentityGuard(identity, launcher, target, native, before)
    guard.assert_unchanged()
    return guard
