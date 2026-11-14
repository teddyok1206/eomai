"""Read-only systemd proof for the fixed material preparation runtime and its children."""

import os
import subprocess

_CHILD_PATTERNS = (
    "eom-material-office-*.service",
    "eom-material-pdf-*.service",
    "eom-creative-pdf-*.service",
    "eom-office-converter@*.service",
)


def _observe(arguments: list[str], *, maximum: int) -> bytes:
    try:
        result = subprocess.run(
            ["/usr/bin/systemctl", *arguments],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=10,
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError("MATERIAL_PREPARATION_SERVICE_DRAIN_REQUIRED") from error
    if result.returncode or len(result.stdout) > maximum or len(result.stderr) > 4096:
        raise ValueError("MATERIAL_PREPARATION_SERVICE_DRAIN_REQUIRED")
    return result.stdout


class StoppedMaterialPreparationService:
    """No caller-provided PID/lease/authority, no service start/stop, no global GPU drain."""

    def require_quiescent(self) -> None:
        if os.geteuid() != 0:
            raise ValueError("MATERIAL_PREPARATION_MAINTENANCE_OWNER_REQUIRED")
        raw = _observe(
            [
                "show",
                "eom-material-learning.service",
                "--no-pager",
                "--property=LoadState,ActiveState,SubState,MainPID,ControlPID,Job",
            ],
            maximum=4096,
        )
        try:
            values = dict(line.split("=", 1) for line in raw.decode("ascii").splitlines())
        except (UnicodeError, ValueError) as error:
            raise ValueError("MATERIAL_PREPARATION_SERVICE_DRAIN_REQUIRED") from error
        if (
            set(values) != {"LoadState", "ActiveState", "SubState", "MainPID", "ControlPID", "Job"}
            or values["LoadState"] != "loaded"
            or values["ActiveState"] != "inactive"
            or values["SubState"] != "dead"
            or values["MainPID"] != "0"
            or values["ControlPID"] != "0"
            or values["Job"]
        ):
            raise ValueError("MATERIAL_PREPARATION_SERVICE_DRAIN_REQUIRED")
        children = _observe(
            [
                "list-units",
                "--state=running,activating,deactivating",
                "--no-legend",
                "--plain",
                "--no-pager",
                *_CHILD_PATTERNS,
            ],
            maximum=65536,
        )
        if children.strip():
            raise ValueError("MATERIAL_PREPARATION_CHILD_DRAIN_REQUIRED")
