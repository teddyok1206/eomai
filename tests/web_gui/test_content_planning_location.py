"""Excel URLs contain only pinned identities; restoration reuses authenticated reads."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


def _check(name: str, marker: str, *, browser: bool = False) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for presentation checks")
    if browser and not os.environ.get("EOM_WEB_PLAYWRIGHT_MODULE"):
        pytest.skip("Browser checks require the opt-in Playwright environment")
    result = subprocess.run(
        [node, "--experimental-default-type=module", str(Path(__file__).with_name(name))],
        capture_output=True,
        text=True,
        timeout=90 if browser else 30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert marker in result.stdout


def test_location_values_are_validated_and_contain_no_authority_or_draft():
    _check("content_planning_location_checks.mjs", "content_planning_location=PASS")


def test_reload_pins_history_and_ignores_late_owner_and_background_responses():
    _check(
        "content_planning_location_browser_checks.mjs",
        "CONTENT_PLANNING_LOCATION_BROWSER=PASS",
        browser=True,
    )
