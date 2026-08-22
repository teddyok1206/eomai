from __future__ import annotations

import os
import subprocess
import sys


def test_standalone_hwpx_runner_resolves_every_application_build_foreign_key() -> None:
    probe = """
import eom_hwpx_manager.runner
from eom_hwpx_manager.models import HwpxApplicationBuildRecord

for foreign_key in HwpxApplicationBuildRecord.__table__.foreign_keys:
    foreign_key.column
"""
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        check=False,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )

    assert completed.returncode == 0, completed.stderr
