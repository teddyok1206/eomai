"""Opt-in account layout and action checks; all accounts and mutations are synthetic."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


def test_operator_accounts_browser_groups_actions_without_changing_permissions() -> None:
    if not os.environ.get("EOM_WEB_PLAYWRIGHT_MODULE"):
        pytest.skip("Opt-in browser check requires the existing Playwright environment")
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the account layout browser check")
    result = subprocess.run(
        [node, str(Path(__file__).with_name("operator_accounts_browser_checks.mjs"))],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "operator_accounts_browser=PASS" in result.stdout
    assert "live_writes=0" in result.stdout
