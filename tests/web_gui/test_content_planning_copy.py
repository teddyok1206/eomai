"""Copy helpers use metadata-only pinned read and the existing write contract."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_selected_copy_browser_values():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the browser copy checks")
    result = subprocess.run(
        [
            node,
            "--experimental-default-type=module",
            str(Path(__file__).with_name("content_planning_copy_checks.mjs")),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "content_planning_copy=PASS" in result.stdout
