"""Whole-shell presentation checks; no production calls, model use or DB writes."""

import os
import re
import shutil
import subprocess
from pathlib import Path
from xml.etree import ElementTree

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "apps/web_gui/eom_web_gui/static"


def test_later_controls_reuse_workbench_tokens_and_keep_consequences_visible() -> None:
    css = (STATIC / "styles.css").read_text()
    html = (STATIC / "index.html").read_text()
    map_css = (STATIC / "knowledge-map.css").read_text()
    assert ':where(input:not([type="checkbox"]):not([type="radio"]):not([type="hidden"])' in css
    assert "var(--line," not in css
    assert "var(--surface-soft," not in css
    assert "gradient(" not in map_css
    assert ".map-legend button { min-height: 40px" in map_css
    assert "원본 보존 · 위치 표시 · 주석 패널" in html
    assert "원본 보존 · 수정 글자 빨간색" in html
    assert "이 자료를 내부 학습·문항 등록·검색에 사용할 권한이 있습니다." in html
    assert "아직 합본 파일을 만들거나 문항을 승인하지 않습니다." in html
    assert "<summary>학습 기술 정보</summary>" in html


def test_navigation_uses_one_local_line_icon_system_without_losing_labels() -> None:
    html = (STATIC / "index.html").read_text()
    buttons = re.findall(
        r'<button\b[^>]*class="[^"]*\bnav-item\b[^"]*"[^>]*>(.*?)</button>',
        html,
        re.DOTALL,
    )
    assert len(buttons) == 17
    for button in buttons:
        icons = re.findall(r"<svg\b.*?</svg>", button, re.DOTALL)
        assert len(icons) == 1
        icon = ElementTree.fromstring(icons[0])
        assert "nav-icon" in icon.attrib["class"].split()
        assert icon.attrib["viewBox"] == "0 0 24 24"
        assert icon.attrib["aria-hidden"] == "true"
        assert not any(node.tag in {"image", "text", "use"} for node in icon.iter())
        assert re.sub(r"<[^>]+>", "", button.replace(icons[0], "")).strip()


def test_exact_id_disclosure_preserves_existing_controls_and_default_closed_state() -> None:
    html = (STATIC / "index.html").read_text()
    disclosure = re.search(
        r'(<details\b[^>]*class="global-opener"[^>]*>)(.*?)</details>', html, re.DOTALL
    )
    assert disclosure is not None
    assert re.search(r"\sopen(?:\s|=|>)", disclosure.group(1)) is None
    assert "<summary>ID로 열기</summary>" in disclosure.group(2)
    for identity in ("global-id", "global-load"):
        assert html.count(f'id="{identity}"') == 1
        assert f'id="{identity}"' in disclosure.group(2)
    assert 'class="sr-only">문항 제작, 문항, HWPX ID</span>' in disclosure.group(2)


def test_all_views_share_browser_form_focus_and_responsive_rules() -> None:
    if not os.environ.get("EOM_WEB_PLAYWRIGHT_MODULE"):
        pytest.skip("Opt-in existing Playwright environment is required")
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the actual GUI check")
        return
    result = subprocess.run(
        [node, str(ROOT / "tests/web_gui/gui_principle_browser_checks.mjs")],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "gui_principle_browser=PASS" in result.stdout
