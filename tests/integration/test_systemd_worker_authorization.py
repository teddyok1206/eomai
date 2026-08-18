from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.workflow_privileged
ROOT = Path(__file__).resolve().parents[2]


def test_installed_fixed_worker_authorization_boundary() -> None:
    if os.environ.get("EOM_RUN_SYSTEMD_WORKER_AUTHORIZATION") != "1":
        pytest.skip("set EOM_RUN_SYSTEMD_WORKER_AUTHORIZATION=1 after operator installation")
    subprocess.run(
        [str(ROOT / "scripts/workflow/verify_systemd_worker_authorization.sh")],
        cwd=ROOT,
        check=True,
        timeout=180,
    )
