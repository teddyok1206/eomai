import shutil
import subprocess
from pathlib import Path

import pytest


def test_saved_assembly_delivery_replay_and_status_in_browser_module():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node browser-module harness unavailable")
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [node, "--experimental-default-type=module", "tests/web_gui/item_db_delivery_checks.mjs"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "item_db_delivery=PASS" in result.stdout
