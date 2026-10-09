"""Pinned, local-only math rendering at the browser presentation boundary."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_preview_math_dependency_bytes_and_license_are_pinned() -> None:
    static = ROOT / "apps/web_gui/eom_web_gui/static"
    for name, digest in {
        "vendor-katex-0.19.0.js": (
            "e5bc26598084ad869939ecaa262673814f26ed586312a409b5f8427c01e4f681"
        ),
        "vendor-katex-LICENSE.txt": (
            "766ccc1f306c885aa45542a9846bbd0a505b27a0374f146778171c2254ce18e3"
        ),
    }.items():
        assert hashlib.sha256((static / name).read_bytes()).hexdigest() == digest


def test_preview_math_local_only_and_bounded_dom_boundary() -> None:
    source = (ROOT / "apps/web_gui/eom_web_gui/static/preview-math.js").read_text()
    for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "fetch(", "https://"):
        assert forbidden not in source
    assert 'output: "mathml"' in source
    assert "trust: false" in source
    assert "maxExpand: 100" in source
    assert "macros: {}" in source
    assert "createTextNode" in source


def test_preview_math_actual_browser_fields_safety_and_fallback() -> None:
    if not os.environ.get("EOM_WEB_PLAYWRIGHT_MODULE"):
        pytest.skip("Opt-in existing Playwright environment is required")
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not available")
    result = subprocess.run(
        [node, str(ROOT / "tests/web_gui/preview_math_browser_checks.mjs")],
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "preview_math_browser=PASS" in result.stdout
