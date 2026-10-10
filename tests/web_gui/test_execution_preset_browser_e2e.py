"""Opt-in actual browser test of the admin model editor; service boundary is synthetic."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_model_editor_real_browser_lifecycle_replays_stale_responses_and_mobile() -> None:
    if not os.environ.get("EOM_WEB_PLAYWRIGHT_MODULE"):
        pytest.skip("Opt-in check requires an existing Playwright environment")
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the actual model editor browser check")
    result = subprocess.run(
        [node, str(ROOT / "tests/web_gui/execution_preset_browser_checks.mjs")],
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "execution_preset_browser=PASS live_writes=0 model_calls=0" in result.stdout
