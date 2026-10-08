"""Execute request controls and handlers, including permission/readiness composition."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "apps/web_gui/eom_web_gui/static"


def test_request_buttons_require_draft_and_serialize_analysis(tmp_path: Path) -> None:
    permission = tmp_path / "permissions.mjs"
    permission.write_bytes((STATIC / "studio-permissions.js").read_bytes())
    source = (STATIC / "app.js").read_text()
    controls = source[
        source.index("function syncDraftControls()") : source.index(
            "function syncMaterialPanelCount()"
        )
    ]
    analyze = source[
        source.index("async function analyzeDraft()") : source.index("function fillDraft(")
    ]
    submit = source[
        source.index("async function submitDraft()") : source.index("function installWorkflow()")
    ]
    script = r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const {hasPermission, applyPermissionVisibility} = await import(PERMISSIONS);
const elements = new Map();
const ids = ['draft-analyze','draft-submit','draft-save',
  'request-text','draft-message','draft-state'];
for (const id of ids) {
  elements.set('#'+id, {disabled: ['draft-submit','draft-save'].includes(id), value: '',
    dataset: {requiredPermission: 'workflow:start'}, setAttribute() {},
    focus() {this.focused=true;}});
}
const operator = {effective_permissions: ['workflow:start']};
applyPermissionVisibility({querySelectorAll: () => [...elements.values()]}, operator);
// Authorization must not undo the initial no-draft guard.
assert.equal(elements.get('#draft-submit').disabled, true);
let resolveAnalysis;
const calls = [];
const context = {
  state: {operator, draft: null, draftAnalysisPending: false, draftSubmissionPending: false,
    curriculumSelection: {}, variationSourceEntry: null},
  $: id => elements.get(id), hasPermission,
  normalizeAuthoringGuidance: value => value.normalize('NFC').replace(/\s+/gu,' ').trim(),
  showMessage: (node, text) => {node.textContent = text;}, setStatus() {}, fillDraft() {},
  api: (path, options) => {
    calls.push({path, options});
    return new Promise(resolve => {resolveAnalysis = resolve;});
  },
  saveDraft: async () => false,
};
vm.createContext(context); vm.runInContext(SOURCE, context);
context.syncDraftControls();
assert.equal(elements.get('#draft-analyze').disabled, false);
await context.submitDraft();
assert.match(elements.get('#draft-message').textContent, /요청 분석/);
assert.equal(calls.length, 0);
elements.get('#request-text').value = '짧음';
await context.analyzeDraft(); assert.equal(calls.length, 0);
assert.match(elements.get('#draft-message').textContent, /10~2,000/);
elements.get('#request-text').value = '통합과학   전류와 전압의 관계 문항을 만들어줘.';
const pending = context.analyzeDraft();
assert.equal(elements.get('#draft-analyze').disabled, true);
assert.equal(elements.get('#draft-submit').disabled, true);
assert.match(elements.get('#draft-analyze').textContent, /분석 중/);
await context.analyzeDraft(); await context.submitDraft();
assert.equal(calls.length, 1);
assert.equal(calls[0].options.body.original_request_text,
  '통합과학 전류와 전압의 관계 문항을 만들어줘.');
resolveAnalysis({request_draft_id: 'test'}); await pending;
assert.equal(elements.get('#draft-analyze').disabled, false);
assert.equal(elements.get('#draft-submit').disabled, false);
// A rejected save must restore controls without creating another submission.
await context.submitDraft();
assert.equal(context.state.draftSubmissionPending, false);
assert.equal(elements.get('#draft-submit').disabled, false);
assert.equal(calls.length, 1);
context.state.operator = {effective_permissions: []}; context.syncDraftControls();
await context.analyzeDraft(); await context.submitDraft();
assert.equal(elements.get('#draft-analyze').disabled, true);
assert.equal(elements.get('#draft-submit').disabled, true);
assert.equal(calls.length, 1);
// An analysis failure still makes retry available, and never invents a draft.
context.state.operator = operator; context.state.draft = null;
context.api = async () => {throw new Error('TEST_UNAVAILABLE');};
await context.analyzeDraft();
assert.equal(context.state.draftAnalysisPending, false);
assert.equal(elements.get('#draft-analyze').disabled, false);
assert.equal(elements.get('#draft-submit').disabled, true);
assert.match(elements.get('#draft-message').textContent, /TEST_UNAVAILABLE/);
""".replace("PERMISSIONS", json.dumps(permission.as_uri())).replace(
        "SOURCE", json.dumps(controls + analyze + submit)
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
