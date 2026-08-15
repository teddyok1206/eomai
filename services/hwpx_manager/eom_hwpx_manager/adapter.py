"""Run the installed HWPX wheel in a file-only transient systemd sandbox."""

from __future__ import annotations

import json
import os
import pwd
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eom_hwpx_manager.errors import HwpxManagerError, HwpxManagerErrorCode
from eom_hwpx_manager.settings import HwpxSettings

MAX_CAPTURE_BYTES = 1024 * 1024
MAX_RESULT_BYTES = 2 * 1024 * 1024


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

    def stage_file(self, workspace: Path, relative_path: str, source: Path) -> Path:
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts or "\\" in relative_path:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_FAILED, "unsafe workspace file name"
            )
        try:
            source_stat = source.lstat()
        except OSError as exc:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_REFERENCE_MISSING, "required input file is missing"
            ) from exc
        if not stat.S_ISREG(source_stat.st_mode) or source.is_symlink():
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILDER_FAILED, "input is not a regular file"
            )
        target = workspace / relative
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copyfile(source, target)
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
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
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
