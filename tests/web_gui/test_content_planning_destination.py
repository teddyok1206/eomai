"""Read-only DB-first destination input uses existing pinned Catalog queries."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


def test_destination_picker_pagination_pins_occurrences_and_owner_races() -> None:
    node = shutil.which("node")
    if not node or not os.environ.get("EOM_WEB_PLAYWRIGHT_MODULE"):
        pytest.skip("Destination browser checks require the opt-in Playwright environment")
    result = subprocess.run(
        [node, str(Path(__file__).with_name("content_planning_destination_browser_checks.mjs"))],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "CONTENT_PLANNING_DESTINATION_BROWSER=PASS writes=0" in result.stdout
