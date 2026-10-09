"""Local-only guide copy, real browser interaction and release asset coverage."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "apps/web_gui/eom_web_gui/static"


def test_guide_mode_is_default_off_and_uses_only_local_text() -> None:
    html = (STATIC / "index.html").read_text()
    app = (STATIC / "app.js").read_text()
    mode = (STATIC / "guide-mode.js").read_text()
    content = (STATIC / "guide-content.js").read_text()
    assert 'role="switch" aria-checked="false"' in html
    assert 'id="guide-tooltip" class="guide-tooltip" role="tooltip" hidden' in html
    assert 'import {installGuideMode} from "./guide-mode.js";' in app
    assert app.index("  installGuideMode();", app.index("async function boot()")) < app.index(
        "  await initializeSession();", app.index("async function boot()")
    )
    for forbidden in (
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "fetch(",
        "XMLHttpRequest",
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "preventDefault",
        "stopPropagation",
    ):
        assert forbidden not in mode + content
    assert "textContent = value.description" in mode
    assert "new Map" in content
    assert "MutationObserver" not in mode + content


def test_guide_copy_covers_all_studio_views_without_new_capabilities() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for guide copy checks")
    program = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(process.argv[1], 'utf8');
const source = fs.readFileSync(process.argv[2], 'utf8').replace('export function', 'function');
const context = {};vm.createContext(context);
vm.runInContext(source+'\nthis.views=views;this.controls=controls;this.fields=fields;'+
 'this.actions=actions;this.lists=lists;this.formActions=formActions;',context);
const names = new Set([...html.matchAll(/data-view-target="([a-z-]+)"/g)].map(v=>v[1]));
assert.equal(context.views.size,names.size);
for(const name of names){
 const value=context.views.get(name);
 assert.ok(value && value.title.length>0 && value.description.length>40,name);
 assert.ok(Object.isFrozen(value),name);
}
for(const [id,value] of context.controls){
 assert.ok(html.includes('id="'+id+'"'), 'stale help ID: '+id);
 assert.ok(value.description.length>=30,id);
}
assert.match(context.views.get('hwpx').description,/제작/);
assert.match(context.views.get('hwpx').description,/별개/);
assert.match(context.controls.get('mock-exam-hwpx-submit').description,/하나의 한글 파일/);
assert.match(context.controls.get('pdf-review-correction-submit').description,
 /PDF 원본을 직접 고치는 기능은 아닙니다/);
const values=[...context.views.values(),...context.controls.values(),
 ...context.actions.values(),...context.lists.values(),...context.formActions.values(),
 ...[...context.fields.values()].flatMap(group=>[...group.values()])];
for(const value of values){
 assert.doesNotMatch(value.description,/GraphRAG|broker|receipt|스키마|불변|해시|정본 문항|계약/);
}
console.log('guide_copy=PASS');
"""
    result = subprocess.run(
        [node, "-e", program, str(STATIC / "index.html"), str(STATIC / "guide-content.js")],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "guide_copy=PASS" in result.stdout


def test_guide_mode_real_browser_default_hover_focus_and_unchanged_actions() -> None:
    if not os.environ.get("EOM_WEB_PLAYWRIGHT_MODULE"):
        pytest.skip("Opt-in existing Playwright environment is required")
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for actual browser checks")
    result = subprocess.run(
        [node, str(ROOT / "tests/web_gui/guide_mode_browser_checks.mjs")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "guide_mode_browser=PASS" in result.stdout
