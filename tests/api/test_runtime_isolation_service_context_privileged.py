from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from eom_api.runtime_isolation_verifier import PROBE_INVENTORY, AccessExpectation, ResultCode

pytestmark = [pytest.mark.privileged, pytest.mark.api_service_live]
INSTALLED_VERIFIER = Path("/usr/local/libexec/eom-api/verify-runtime-isolation")


def test_installed_runtime_verifier_uses_service_context() -> None:
    if os.environ.get("EOM_RUN_API_RUNTIME_ISOLATION_PRIVILEGED") != "1":
        pytest.skip("set the explicit privileged runtime-isolation marker after deployment")
    if os.geteuid() != 0:
        pytest.skip("the installed runtime-isolation verifier requires an authorized root operator")

    assert INSTALLED_VERIFIER.is_file()
    assert not INSTALLED_VERIFIER.is_symlink()
    host_root_worker_home_control = os.access("/srv/eom/worker-homes", os.R_OK)

    completed = subprocess.run(
        (str(INSTALLED_VERIFIER),),
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert host_root_worker_home_control, (
        "external-root control must remain a non-verdict observation"
    )
    assert completed.returncode == 0, completed.stderr
    expected = {
        f"{ResultCode.PASS_ALLOWED.value} {probe.logical_name}"
        if probe.expectation is AccessExpectation.ALLOWED
        else f"{ResultCode.PASS_DENIED.value} {probe.logical_name}"
        for probe in PROBE_INVENTORY
    }
    assert expected <= set(completed.stdout.splitlines())
    assert "Application API runtime isolation verified." in completed.stdout.splitlines()
    assert completed.stderr == ""
