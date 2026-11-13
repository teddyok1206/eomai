"""Actual review callbacks keep their selected owner and replay references."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("mode", ["mutations", "recovery"])
def test_document_review_browser_ownership_and_recovery(mode: str) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the isolated document review callback checks")
    result = subprocess.run(
        [
            node,
            "--experimental-default-type=module",
            str(Path(__file__).with_name("document_review_recovery_checks.mjs")),
            mode,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "=PASS" in result.stdout
