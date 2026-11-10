"""Private output history imports exact selections without inventing content usage."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_private_output_library_reuses_reads_and_preserves_replay_and_owner() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for presentation checks")
    result = subprocess.run(
        [
            node,
            "--experimental-default-type=module",
            str(Path(__file__).with_name("curated_output_library_checks.mjs")),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "curated_output_library=PASS" in result.stdout
