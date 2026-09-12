"""Run the installed HWPX wheel in a file-only transient systemd sandbox."""

from __future__ import annotations

import hashlib
import json
import os
import pwd
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eom_hwpx_manager.errors import HwpxManagerError, HwpxManagerErrorCode
from eom_hwpx_manager.settings import HwpxSettings

MAX_CAPTURE_BYTES = 1024 * 1024
MAX_RESULT_BYTES = 2 * 1024 * 1024


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def copy_stable_regular_file(
    source: Path,
    target: Path,
    *,
    expected_sha256: str | None = None,
) -> str:
    """Copy one untrusted source through stable fds into one fresh workspace file."""

    read_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    write_flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    source_fd = -1
    target_fd = -1
    target_created = False
    succeeded = False
    try:
        source_fd = os.open(source, read_flags)
        opened = os.fstat(source_fd)
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError("source is not a regular file")
        target_fd = os.open(target, write_flags, 0o600)
        target_created = True
        digest = hashlib.sha256()
        remaining = opened.st_size
        while remaining:
            chunk = os.read(source_fd, min(remaining, 1024 * 1024))
            if not chunk:
                raise ValueError("source was truncated while staging")
            digest.update(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(target_fd, view)
                if written <= 0:
                    raise OSError("staged file write made no progress")
                view = view[written:]
            remaining -= len(chunk)
        if os.read(source_fd, 1):
            raise ValueError("source grew while staging")
        copied_sha256 = "sha256:" + digest.hexdigest()
        finalized_source = os.fstat(source_fd)
        staged = os.fstat(target_fd)
        if (
            _stat_identity(opened) != _stat_identity(finalized_source)
            or not stat.S_ISREG(staged.st_mode)
            or staged.st_size != opened.st_size
            or (expected_sha256 is not None and copied_sha256 != expected_sha256)
        ):
            raise ValueError("staged file differs from its pinned source")
        os.fsync(target_fd)
        succeeded = True
        return copied_sha256
    finally:
        if target_fd >= 0:
            os.close(target_fd)
        if source_fd >= 0:
            os.close(source_fd)
        if target_created and not succeeded:
            target.unlink(missing_ok=True)


def read_stable_regular_file(
    path: Path,
    *,
    max_bytes: int,
) -> bytes:
    """Read one bounded untrusted file without following its final path component."""

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or not 0 < opened.st_size <= max_bytes:
            raise ValueError("file metadata is outside the accepted boundary")
        chunks: list[bytes] = []
        remaining = opened.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                raise ValueError("file was truncated while reading")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise ValueError("file grew while reading")
        if _stat_identity(opened) != _stat_identity(os.fstat(descriptor)):
            raise ValueError("file identity changed while reading")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def hash_stable_regular_file(path: Path, *, max_bytes: int) -> str:
    """Hash one bounded regular file while proving its fd identity is stable."""

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or not 0 < opened.st_size <= max_bytes:
            raise ValueError("file metadata is outside the accepted boundary")
        digest = hashlib.sha256()
        remaining = opened.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                raise ValueError("file was truncated while hashing")
            digest.update(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise ValueError("file grew while hashing")
        if _stat_identity(opened) != _stat_identity(os.fstat(descriptor)):
            raise ValueError("file identity changed while hashing")
        return "sha256:" + digest.hexdigest()
    finally:
        os.close(descriptor)


@dataclass(frozen=True)
class BuilderRun:
    exit_code: int
    workspace: Path
    stdout_path: Path
    stderr_path: Path
    unit_name: str


class HwpxBuilderAdapter:
    def __init__(self, settings: HwpxSettings) -> None:
        self.settings = settings

    def create_workspace(self, workspace_id: str) -> Path:
        if not workspace_id.replace("_", "").isalnum():
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_FAILED, "invalid workspace identifier"
            )
        workspace = self.settings.workspace_root / workspace_id
        if workspace.exists():
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_FAILED, "builder workspace already exists"
            )
        workspace.mkdir(mode=0o700, parents=False)
        account = pwd.getpwnam(self.settings.builder_user)
        os.chown(workspace, account.pw_uid, account.pw_gid)
        return workspace

    def stage_file(
        self,
        workspace: Path,
        relative_path: str,
        source: Path,
        *,
        expected_sha256: str | None = None,
    ) -> Path:
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts or "\\" in relative_path:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_FAILED, "unsafe workspace file name"
            )
        target = workspace / relative
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            copy_stable_regular_file(source, target, expected_sha256=expected_sha256)
        except FileNotFoundError as exc:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_REFERENCE_MISSING, "required input file is missing"
            ) from exc
        except (OSError, ValueError) as exc:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_FAILED,
                "input could not be staged as a pinned regular file",
            ) from exc
        account = pwd.getpwnam(self.settings.builder_user)
        os.chown(target.parent, account.pw_uid, account.pw_gid)
        os.chown(target, account.pw_uid, account.pw_gid)
        target.chmod(0o400)
        return target

    def write_json(self, workspace: Path, relative_path: str, value: dict[str, Any]) -> Path:
        target = workspace / relative_path
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        account = pwd.getpwnam(self.settings.builder_user)
        os.chown(target.parent, account.pw_uid, account.pw_gid)
        os.chown(target, account.pw_uid, account.pw_gid)
        target.chmod(0o400)
        return target

    def run(
        self, workspace: Path, operation: str, arguments: list[str], log_root: Path
    ) -> BuilderRun:
        unit_name = f"eom-hwpx-{operation}-{workspace.name.replace('_', '-')[:48]}"
        home = Path("/var/lib/eom-hwpx")
        argv = [
            "/usr/bin/systemd-run",
            "--quiet",
            "--wait",
            "--pipe",
            "--collect",
            "--service-type=exec",
            f"--unit={unit_name}",
            f"--uid={self.settings.builder_user}",
            f"--gid={self.settings.builder_user}",
            f"--working-directory={workspace}",
            f"--setenv=HOME={home}",
            "--property=NoNewPrivileges=yes",
            "--property=PrivateNetwork=yes",
            "--property=PrivateTmp=yes",
            "--property=ProtectSystem=strict",
            "--property=ProtectHome=yes",
            "--property=ProtectKernelTunables=yes",
            "--property=ProtectKernelModules=yes",
            "--property=ProtectControlGroups=yes",
            "--property=RestrictSUIDSGID=yes",
            "--property=LockPersonality=yes",
            "--property=RestrictRealtime=yes",
            "--property=InaccessiblePaths=/mnt/nas",
            "--property=InaccessiblePaths=/root/.codex",
            "--property=InaccessiblePaths=/srv/eom/worker-homes",
            "--property=InaccessiblePaths=/var/run/docker.sock",
            "--property=InaccessiblePaths=/etc/eom",
            "--property=InaccessiblePaths=/home/eom/EOM",
            "--property=InaccessiblePaths=/usr/local/bin/codex",
            f"--property=ReadWritePaths={workspace}",
            "--property=UMask=0077",
            f"--property=MemoryMax={self.settings.memory_max}",
            "--property=TasksMax=64",
            "--property=CPUQuota=200%",
            str(self.settings.builder_binary),
            operation,
            *arguments,
        ]
        log_root.mkdir(mode=0o750, parents=True, exist_ok=True)
        stdout = log_root / f"hwpx-{operation}.stdout.log"
        stderr = log_root / f"hwpx-{operation}.stderr.log"
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                timeout=self.settings.timeout_seconds,
                check=False,
                env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"},
            )
        except subprocess.TimeoutExpired as exc:
            subprocess.run(
                ["/usr/bin/systemctl", "stop", f"{unit_name}.service"],
                capture_output=True,
                timeout=30,
                check=False,
            )
            self._capture(stdout, exc.stdout)
            self._capture(stderr, exc.stderr)
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_TIMEOUT, "HWPX builder timed out"
            ) from exc
        except OSError as exc:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_UNAVAILABLE, "HWPX builder could not start"
            ) from exc
        self._capture(stdout, completed.stdout)
        self._capture(stderr, completed.stderr)
        return BuilderRun(completed.returncode, workspace, stdout, stderr, unit_name)

    @staticmethod
    def load_json(path: Path, workspace: Path) -> dict[str, Any]:
        try:
            file_stat = path.lstat()
        except OSError as exc:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_RESULT_MISSING, "builder result is missing"
            ) from exc
        if (
            not stat.S_ISREG(file_stat.st_mode)
            or path.is_symlink()
            or file_stat.st_size > MAX_RESULT_BYTES
            or not path.resolve().is_relative_to(workspace.resolve())
        ):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_RESULT_INVALID, "builder result file is unsafe"
            )
        try:
            value = json.loads(read_stable_regular_file(path, max_bytes=MAX_RESULT_BYTES))
        except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_RESULT_INVALID, "builder result is invalid JSON"
            ) from exc
        if not isinstance(value, dict):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_RESULT_INVALID, "builder result must be an object"
            )
        return value

    @staticmethod
    def _capture(path: Path, value: bytes | str | None) -> None:
        if value is None:
            data = b""
        elif isinstance(value, str):
            data = value.encode("utf-8", errors="replace")
        else:
            data = value
        path.write_bytes(data[-MAX_CAPTURE_BYTES:])
        path.chmod(0o600)
