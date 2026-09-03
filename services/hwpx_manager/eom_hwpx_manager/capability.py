"""Sanitized fixed-command Kordoc runtime capability probe."""

from __future__ import annotations

import grp
import json
import os
import pwd
import stat
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from eom_hwpx_manager.settings import HwpxSettings

MAX_CAPABILITY_OUTPUT_BYTES = 16 * 1024
SYSTEMCTL = Path("/usr/bin/systemctl")
RUNNER_UNIT = "eom-hwpx-application-runner.service"
BUILDER_UNIT_PATH = Path("/etc/systemd/system/eom-hwpx-kordoc@.service")
QUESTION_TEMPLATE_BUILDER_UNIT_PATH = Path("/etc/systemd/system/eom-hwpx-builder@.service")
CONTENT_TEAM_BUILDER_UNIT_PATH = Path("/etc/systemd/system/eom-hwpx-content-team@.service")
RUNNER_UNIT_PATH = Path("/etc/systemd/system/eom-hwpx-application-runner.service")
MANAGER_SOCKET_PATH = Path("/run/eom-hwpx-api/manager.sock")
REQUIRED_BUILDER_DIRECTIVES = frozenset(
    {
        "User=eom-hwpx",
        "Group=eom-hwpx",
        "PrivateNetwork=true",
        "NoNewPrivileges=true",
        "CapabilityBoundingSet=",
        "ExecStart=/srv/eom/conda/envs/eom-hwpx/bin/eom-hwpx render-kordoc "
        "--request request.json --result result.json",
        "InaccessiblePaths=/mnt/nas",
        "ReadWritePaths=/srv/eom/hwpx-workspaces/%i",
    }
)
REQUIRED_QUESTION_TEMPLATE_BUILDER_DIRECTIVES = frozenset(
    {
        "User=eom-hwpx",
        "Group=eom-hwpx",
        "PrivateNetwork=true",
        "NoNewPrivileges=true",
        "CapabilityBoundingSet=",
        "RestrictSUIDSGID=true",
        "ExecStart=/srv/eom/conda/envs/eom-hwpx/bin/eom-hwpx render "
        "--request request.json --result result.json",
        "InaccessiblePaths=/mnt/nas",
        "ReadWritePaths=/srv/eom/hwpx-workspaces/%i",
    }
)
REQUIRED_CONTENT_TEAM_BUILDER_DIRECTIVES = frozenset(
    {
        "User=eom-hwpx",
        "Group=eom-hwpx",
        "PrivateNetwork=true",
        "PrivateTmp=true",
        "NoNewPrivileges=true",
        "CapabilityBoundingSet=",
        "RestrictSUIDSGID=true",
        "ExecStart=/srv/eom/conda/envs/eom-hwpx/bin/eom-hwpx render-content-team "
        "--request request.json --result result.json",
        "InaccessiblePaths=/mnt/nas",
        "InaccessiblePaths=/home/eom/EOM",
        "InaccessiblePaths=/home/eom/EOMIS",
        "ReadWritePaths=/srv/eom/hwpx-workspaces/%i",
    }
)
REQUIRED_RUNNER_DIRECTIVES = frozenset(
    {
        "User=eom-hwpx-manager",
        "Group=eom-api",
        "SupplementaryGroups=eom eom-hwpx",
        "RuntimeDirectory=eom-hwpx-api",
        "RuntimeDirectoryMode=0750",
        "StateDirectory=eom-hwpx-api",
        "StateDirectoryMode=0700",
        "WorkingDirectory=/var/lib/eom-hwpx-api",
        "Environment=HOME=/var/lib/eom-hwpx-api",
        "Environment=EOM_STAGING_ROOT=/var/lib/eom-hwpx-api/staging",
        "NoNewPrivileges=true",
        "CapabilityBoundingSet=",
        "ExecStart=/srv/eom/conda/envs/eom-api/bin/eom-hwpx-application-runner serve",
        "ReadWritePaths=/run/eom-hwpx-api",
        "ReadWritePaths=/var/lib/eom-hwpx-api",
        "InaccessiblePaths=/var/lib/eom-hwpx",
        "InaccessiblePaths=/etc/eom-api",
    }
)


@dataclass(frozen=True)
class HwpxCapability:
    state: str
    renderer: str
    renderer_version: str
    native_equations: bool
    native_tables: bool
    manager_registered: bool
    detail_code: str


class HwpxCapabilityService:
    def __init__(
        self,
        settings: HwpxSettings | None = None,
        *,
        manager_registered: bool = True,
        isolation_preflight: Callable[[], tuple[bool, str]] | None = None,
    ) -> None:
        self.settings = settings or HwpxSettings.from_environment()
        self.manager_registered = manager_registered
        self.isolation_preflight = isolation_preflight or fixed_builder_isolation_preflight

    def inspect(self) -> HwpxCapability:
        binary = self.settings.builder_binary
        try:
            metadata = binary.lstat()
        except OSError:
            return self._result("PREPARED_NOT_DEPLOYED", "HWPX_BUILDER_NOT_DEPLOYED")
        if (
            not stat.S_ISREG(metadata.st_mode)
            or binary.is_symlink()
            or not os.access(binary, os.X_OK)
        ):
            return self._result("DEGRADED", "HWPX_BUILDER_LAYOUT_INVALID")
        try:
            completed = subprocess.run(
                [str(binary), "kordoc-capabilities"],
                capture_output=True,
                timeout=10,
                check=False,
                env={"PATH": "/usr/bin:/bin", "HOME": "/var/lib/eom-hwpx"},
            )
        except (OSError, subprocess.SubprocessError):
            return self._result("DEGRADED", "HWPX_CAPABILITY_PROBE_FAILED")
        if completed.returncode != 0:
            return self._result("PREPARED_NOT_DEPLOYED", "HWPX_KORDOC_RUNTIME_NOT_DEPLOYED")
        if len(completed.stdout) > MAX_CAPABILITY_OUTPUT_BYTES:
            return self._result("DEGRADED", "HWPX_CAPABILITY_RESPONSE_INVALID")
        try:
            value = json.loads(completed.stdout)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._result("DEGRADED", "HWPX_CAPABILITY_RESPONSE_INVALID")
        if not isinstance(value, dict) or (
            value.get("status") != "READY"
            or value.get("kordoc_version") != "4.9.0"
            or value.get("offline_required") is not True
            or not isinstance(value.get("node_major"), int)
            or value["node_major"] != 22
        ):
            return self._result("DEGRADED", "HWPX_CAPABILITY_INTEGRITY_MISMATCH")
        if not self.manager_registered:
            return self._result("DEGRADED", "HWPX_MANAGER_NOT_REGISTERED")
        isolation_ready, isolation_detail = self.isolation_preflight()
        if not isolation_ready:
            state = (
                "PREPARED_NOT_DEPLOYED"
                if isolation_detail == "HWPX_ISOLATED_BUILDER_NOT_DEPLOYED"
                else "DEGRADED"
            )
            return self._result(state, isolation_detail)
        return self._result("READY", "HWPX_READY")

    def _result(self, state: str, detail: str) -> HwpxCapability:
        ready = state == "READY"
        return HwpxCapability(
            state=state,
            renderer="kordoc",
            renderer_version="4.9.0",
            native_equations=ready,
            native_tables=ready,
            manager_registered=self.manager_registered,
            detail_code=detail,
        )


def fixed_builder_isolation_preflight() -> tuple[bool, str]:
    """Verify the fixed installed unit boundary without starting a unit or build."""
    for path, required in (
        (BUILDER_UNIT_PATH, REQUIRED_BUILDER_DIRECTIVES),
        (
            QUESTION_TEMPLATE_BUILDER_UNIT_PATH,
            REQUIRED_QUESTION_TEMPLATE_BUILDER_DIRECTIVES,
        ),
        (
            CONTENT_TEAM_BUILDER_UNIT_PATH,
            REQUIRED_CONTENT_TEAM_BUILDER_DIRECTIVES,
        ),
        (RUNNER_UNIT_PATH, REQUIRED_RUNNER_DIRECTIVES),
    ):
        try:
            metadata = path.lstat()
            lines = frozenset(path.read_text(encoding="utf-8").splitlines())
        except (OSError, UnicodeError):
            return False, "HWPX_ISOLATED_BUILDER_NOT_DEPLOYED"
        if (
            not stat.S_ISREG(metadata.st_mode)
            or path.is_symlink()
            or metadata.st_uid != 0
            or metadata.st_gid != 0
            or stat.S_IMODE(metadata.st_mode) != 0o644
            or not required.issubset(lines)
        ):
            return False, "HWPX_ISOLATED_BUILDER_LAYOUT_INVALID"
    if not SYSTEMCTL.is_file() or not os.access(SYSTEMCTL, os.X_OK):
        return False, "HWPX_ISOLATED_BUILDER_LAYOUT_INVALID"
    for operation in ("is-active", "is-enabled"):
        try:
            completed = subprocess.run(
                [str(SYSTEMCTL), operation, "--quiet", RUNNER_UNIT],
                capture_output=True,
                timeout=5,
                check=False,
                env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin"},
            )
        except (OSError, subprocess.SubprocessError):
            return False, "HWPX_MANAGER_RUNTIME_UNAVAILABLE"
        if completed.returncode != 0:
            return False, "HWPX_ISOLATED_BUILDER_NOT_DEPLOYED"
    try:
        socket_metadata = MANAGER_SOCKET_PATH.lstat()
        api_gid = grp.getgrnam("eom-api").gr_gid
        manager_uid = pwd.getpwnam("eom-hwpx-manager").pw_uid
    except (KeyError, OSError):
        return False, "HWPX_MANAGER_RUNTIME_UNAVAILABLE"
    if (
        not stat.S_ISSOCK(socket_metadata.st_mode)
        or MANAGER_SOCKET_PATH.is_symlink()
        or socket_metadata.st_uid != manager_uid
        or socket_metadata.st_gid != api_gid
        or stat.S_IMODE(socket_metadata.st_mode) != 0o660
    ):
        return False, "HWPX_MANAGER_RUNTIME_UNAVAILABLE"
    return True, "HWPX_ISOLATED_BUILDER_READY"
