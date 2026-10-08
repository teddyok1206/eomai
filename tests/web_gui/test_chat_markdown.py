"""Safe semantic DOM output; no real browser or model consumption in this suite."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.web_gui.test_general_chat import chat_module

ROOT = Path(__file__).resolve().parents[2]


def test_pinned_markdown_dependency_and_license_are_unchanged():
    root = ROOT / "apps/web_gui/eom_web_gui/static"
    for name, expected in {
        "vendor-marked-18.1.0.js": (
            "054d73b676031dc8e60e247ef228044fbeebe10af14bac1a6e53852f80f826e5"
        ),
        "vendor-marked-LICENSE.txt": (
            "8e3a3f82f59a60958f56ca08f445647c32a4733dc7ca6c2c46f6eb898471ab9c"
        ),
    }.items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected


def test_markdown_dom_formatting_security_copy_and_bounded_fallback(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node unavailable")
    chat_module(tmp_path)
    result = subprocess.run(
        [
            node,
            str(ROOT / "tests/web_gui/chat_markdown_checks.mjs"),
            (tmp_path / "chat-markdown.js").as_uri(),
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "CHAT_MARKDOWN=PASS" in result.stdout


def test_renderer_has_no_html_sink_or_remote_resource_loader():
    source = (ROOT / "apps/web_gui/eom_web_gui/static/chat-markdown.js").read_text()
    for forbidden in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "fetch(",
        'element("img")',
    ):
        assert forbidden not in source
    assert "createTextNode" in source
    assert (
        "renderChatMarkdown"
        in (ROOT / "apps/web_gui/eom_web_gui/static/general-chat.js").read_text()
    )
