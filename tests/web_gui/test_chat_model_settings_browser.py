"""Opt-in browser lifecycle; service boundary is synthetic and no model is used."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


def test_chat_model_settings_real_browser_replay_duplicate_click_and_logout():
    if not os.environ.get("EOM_WEB_PLAYWRIGHT_MODULE") or not shutil.which("node"):
        pytest.skip("existing opt-in Playwright environment required")
    path = Path(__file__).with_name("chat_model_settings_browser_checks.mjs")
    result = subprocess.run(
        ["node", str(path)], env=os.environ, text=True, capture_output=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
    assert "chat_model_settings_browser=PASS model_calls=0 live_writes=0" in result.stdout
