"""Opt-in real browser regression for the single-editor item request form."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_request_draft_real_browser_controls_snapshot_races_and_mobile_layout() -> None:
    if not os.environ.get("EOM_WEB_PLAYWRIGHT_MODULE"):
        pytest.skip("Opt-in browser check requires an existing Playwright test environment")
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the actual request form browser check")
    result = subprocess.run(
        [node, str(ROOT / "tests/web_gui/request_draft_browser_checks.mjs")],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "request_draft_browser=PASS" in result.stdout
    assert "live_writes=0" in result.stdout
