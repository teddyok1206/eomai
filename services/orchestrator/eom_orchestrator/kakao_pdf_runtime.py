"""Fixed root-installed unit launch, mirroring the existing native-exam preparer boundary."""

from __future__ import annotations

import grp
import os
import pwd
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from eom_kakao_archive_contracts import RenderCommand, sha256

from .kakao_pdf_files import KakaoPdfExecutionError, read_local
from .native_exam_preparation import require_native_exam_runtime_python

KAKAO_WORKSPACE_ROOT = Path("/var/lib/eom-catalog-api/staging/kakao-render")
KAKAO_PYTHON = Path("/srv/eom/conda/envs/eom-kakao-pdf/bin/python")
KAKAO_TEMPLATE = Path("/etc/systemd/system/eom-kakao-pdf@.service")
KAKAO_ENVIRONMENT = Path("/etc/eom/kakao-pdf.env")
KAKAO_WORKER = "eom-kakao-render"


@dataclass(frozen=True, slots=True)
class FixedKakaoPdfLauncher:
    template_sha256: str
    renderer_release_sha256: str

    def run(self, command: RenderCommand, workspace: Path) -> None:
        self._installed(command, workspace)
        unit = f"eom-kakao-pdf@{command.execution.attempt_id}.service"
        before = _show(unit)
        if (
            before.get("FragmentPath") != str(KAKAO_TEMPLATE)
            or before.get("DropInPaths")
            or before.get("User") != KAKAO_WORKER
            or before.get("Group") != KAKAO_WORKER
            or before.get("ActiveState") not in {"inactive", "failed"}
            or before.get("ExecMainStartTimestampMonotonic", "0") != "0"
        ):
            raise KakaoPdfExecutionError("KAKAO_PDF_UNIT_NOT_FRESH")
        try:
            completed = subprocess.run(
                ["/usr/bin/systemctl", "--no-ask-password", "start", unit],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=190,
            )
        except subprocess.TimeoutExpired:
            # No resubmission or automatic cleanup: the service may still own the attempt.
            raise KakaoPdfExecutionError("KAKAO_PDF_EXECUTION_UNCERTAIN") from None
        self._installed(command, workspace)
        after = _show(unit)
        if (
            completed.returncode != 0
            or after.get("ActiveState") != "active"
            or after.get("SubState") != "exited"
            or after.get("Result") != "success"
            or after.get("ExecMainStatus") != "0"
            or after.get("ExecMainStartTimestampMonotonic", "0") == "0"
            or not re.fullmatch(r"[0-9a-f]{32}", after.get("InvocationID", ""))
        ):
            raise KakaoPdfExecutionError("KAKAO_PDF_WORKER_FAILED")
        # Retain the success observation until read, then stop the owned cgroup before
        # any output is accepted. Bind mounts disappear; host attempt bytes remain.
        try:
            stopped = subprocess.run(
                ["/usr/bin/systemctl", "--no-ask-password", "stop", unit],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            raise KakaoPdfExecutionError("KAKAO_PDF_EXECUTION_UNCERTAIN") from None
        if stopped.returncode != 0:
            raise KakaoPdfExecutionError("KAKAO_PDF_EXECUTION_UNCERTAIN")

    def _installed(self, command: RenderCommand, workspace: Path) -> None:
        if (
            workspace != KAKAO_WORKSPACE_ROOT / command.execution.attempt_id
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", self.template_sha256)
            or self.renderer_release_sha256 != command.renderer_release_sha256
        ):
            raise KakaoPdfExecutionError("KAKAO_PDF_RUNTIME_INVALID")
        try:
            if (
                pwd.getpwnam(KAKAO_WORKER).pw_uid == os.geteuid()
                or grp.getgrnam(KAKAO_WORKER).gr_gid == 0
            ):
                raise ValueError("worker identity invalid")
            require_native_exam_runtime_python(KAKAO_PYTHON)
            raw = read_local(KAKAO_TEMPLATE.parent, KAKAO_TEMPLATE.name, limit=16384, uid=0, gid=0)
            env = read_local(
                KAKAO_ENVIRONMENT.parent, KAKAO_ENVIRONMENT.name, limit=1024, uid=0, gid=0
            )
            for path in (KAKAO_TEMPLATE.parent, KAKAO_ENVIRONMENT.parent):
                info = path.lstat()
                if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                    raise ValueError("unsafe configuration parent")
        except (OSError, ValueError, KeyError):
            raise KakaoPdfExecutionError("KAKAO_PDF_RUNTIME_UNTRUSTED") from None
        expected = f"EOM_KAKAO_RENDER_RELEASE_SHA256={self.renderer_release_sha256}\n".encode(
            "ascii"
        )
        if sha256(raw) != self.template_sha256 or env != expected:
            raise KakaoPdfExecutionError("KAKAO_PDF_RELEASE_MISMATCH")


def _show(unit: str) -> dict[str, str]:
    try:
        result = subprocess.run(
            [
                "/usr/bin/systemctl",
                "show",
                unit,
                "--no-pager",
                "--property=FragmentPath,DropInPaths,User,Group,ActiveState,SubState,Result,ExecMainStatus,ExecMainStartTimestampMonotonic,InvocationID",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
        if result.returncode or len(result.stdout) > 16384:
            raise ValueError("unit observation failed")
        return dict(
            line.split("=", 1) for line in result.stdout.decode("utf-8").splitlines() if "=" in line
        )
    except (ValueError, subprocess.TimeoutExpired):
        raise KakaoPdfExecutionError("KAKAO_PDF_UNIT_UNAVAILABLE") from None
