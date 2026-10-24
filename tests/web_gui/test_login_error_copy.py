from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def test_login_errors_distinguish_credentials_throttling_and_service_failure() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed to exercise the actual login handler")
    script = Path(__file__).with_name("login_error_checks.mjs")
    result = subprocess.run([node, str(script)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert "login_error_copy=PASS" in result.stdout
