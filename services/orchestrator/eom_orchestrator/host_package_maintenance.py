"""Observe fixed host package jobs before capturing a new protected numerical runtime."""

import subprocess


class HostPackageMaintenancePending(RuntimeError):
    code = "BACKGROUND_HOST_MAINTENANCE_PENDING"


def require_host_package_maintenance_idle() -> None:
    """Never stop system updates, acquire authority or call a model.

    Host ldconfig can replace a file beneath an existing file bind mount. New
    captures wait for the fixed OS maintenance jobs; actual mount/hash checks
    still decide whether a runtime is safe. Unknown observation is not READY.
    """
    try:
        result = subprocess.run(
            (
                "/usr/bin/systemctl",
                "show",
                "apt-daily.service",
                "apt-daily-upgrade.service",
                "--property=ActiveState",
                "--value",
            ),
            capture_output=True,
            check=False,
            timeout=3,
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
        )
    except (OSError, subprocess.TimeoutExpired):
        raise HostPackageMaintenancePending(HostPackageMaintenancePending.code) from None
    states = result.stdout.split()
    if (
        result.returncode != 0
        or len(result.stdout) > 128
        or len(states) != 2
        or not set(states) <= {b"inactive", b"failed"}
    ):
        raise HostPackageMaintenancePending(HostPackageMaintenancePending.code)
