"""Opt-in real browser checks for the repository's table/detail DB workspace."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_item_db_table_filters_pinned_detail_and_responsive_layout() -> None:
    if not os.environ.get("EOM_WEB_PLAYWRIGHT_MODULE"):
        pytest.skip("Opt-in browser check requires an existing Playwright test environment")
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the actual DB browser check")
    result = subprocess.run(
        [node, str(ROOT / "tests/web_gui/item_db_browser_checks.mjs")],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "item_db_browser=PASS live_writes=0" in result.stdout
