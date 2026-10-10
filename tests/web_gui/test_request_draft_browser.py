"""Execute the one-editor request flow without network or model invocations."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "apps/web_gui/eom_web_gui/static"

HARNESS = r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const guidance = '통합과학   전류와 전압의 관계 문항을 만들어줘.';
const normalizedGuidance = '통합과학 전류와 전압의 관계 문항을 만들어줘.';
const draftId = 'requestdraft_' + '1'.repeat(32);
const specHash = '2'.repeat(64);
const workflowId = 'workflow_' + '3'.repeat(32);
const sourceRevisionId = 'itemrev_' + '4'.repeat(32);
const field = (value = '') => ({
  value, disabled: false, checked: false, textContent: '', dataset: {},
  listeners: new Map(),
  focus() {this.focused = true;}, setAttribute() {},
  addEventListener(type, handler) {this.listeners.set(type, handler);},
});
const nodes = new Map();
for (const id of ['draft-new', 'draft-save', 'draft-submit', 'request-text', 'draft-message',
  'draft-state', 'draft-id', 'draft-sha', 'workflow-id',
  'past-exam-variation-clear', 'past-exam-variation-field', 'past-exam-variation-source',
  'material-panel-count-field', 'image-supporting-data-field']) {
  nodes.set('#' + id, field());
}
nodes.get('#request-text').value = guidance;
const formFields = {
  authoring_guidance: nodes.get('#request-text'),
  topic: field('전류와 전압'),
  item_format: field('multiple_choice'), task_type: field('conceptual'),
  difficulty: field('medium'), material_form: field('AUTO'),
  material_panel_count: field('1'), image_supporting_data: field('NONE'),
  source_intake_batch_id: field(),
  knowledge_grounding: field(),
  curriculum_large_unit_key: field('eom.is.large.3'),
  curriculum_middle_unit_key: field('eom.is.middle.3-2'),
  curriculum_small_unit_key: field(),
};
let axes = null;
const axisInputs = ['CONTEXT', 'DIFFICULTY', 'DISTRACTORS', 'REASONING_PATH',
  'REPRESENTATION', 'VALUES'].map(value => field(value));
nodes.get('#past-exam-variation-field').querySelectorAll = () => axisInputs;
let validForm = true;
const form = {
  elements: formFields,
  listeners: new Map(),
  reportValidity: () => validForm,
  checkValidity: () => validForm,
  querySelectorAll: () => axes
    ? axes.map(value => ({value, checked: true}))
    : axisInputs.filter(input => input.checked),
  addEventListener(type, handler) {this.listeners.set(type, handler);},
  reset() {
    for (const input of Object.values(formFields)) {input.value = ''; input.checked = false;}
    formFields.item_format.value = 'multiple_choice';
    formFields.task_type.value = 'conceptual';
    formFields.difficulty.value = 'medium';
    formFields.material_form.value = 'AUTO';
    formFields.material_panel_count.value = '1';
    formFields.image_supporting_data.value = 'NONE';
    for (const input of axisInputs) input.checked = false;
  },
};
nodes.set('#draft-form', form);
const unit = {key: 'eom.is.middle.3-2', label: '물질의 성질', code: '3-(2)'};
const variationEntry = {
  item_id: 'item_' + '7'.repeat(32), item_revision_id: sourceRevisionId,
  occurrence_display_label: '기출 시험', item_number: 17,
  curriculum_units: [{unit_key: unit.key}],
};
const calls = [];
let failUpdate = false;
let failedSubmission = false;
let apiOverride = null;
const state = {
  operator: {effective_permissions: ['workflow:start']}, draft: null,
  draftAction: null, draftEditorRevision: 0,
  curriculumSelection: {large: 'eom.is.large.3', middle: unit.key, small: ''},
  curriculumOutline: {subject_label: '통합과학', units: [unit],
    graph_grounding_available: true},
  curriculumUnitsByKey: new Map([[unit.key, unit]]), variationSourceEntry: null,
};
let workflowLoads = 0;
let visibleView = null;
class StudioApiError extends Error {
  constructor(message, code) {super(message); this.code = code;}
}
const context = {
  state, console, StudioApiError,
  $: selector => {
    assert.ok(nodes.has(selector), 'unexpected DOM reference: ' + selector);
    return nodes.get(selector);
  },
  hasPermission: (operator, permission) =>
    operator?.effective_permissions?.includes(permission) === true,
  deepestCurriculumUnitKey: selection => selection.small || selection.middle || selection.large,
  curriculumAncestors: (units, key) => ({large: 'eom.is.large.3', middle: key, small: ''}),
  setCurriculumSelection: selection => {state.curriculumSelection = {...selection};},
  syncCurriculumSelectorAvailability() {}, syncGraphGroundingCapability() {},
  showMessage: (node, text) => {node.textContent = text;},
  setStatus: (node, tone, icon, text) => {node.textContent = text;},
  showView: view => {visibleView = view;},
  loadWorkflow: async () => {workflowLoads++;},
  api: async (path, options) => {
    calls.push({path, options});
    if (apiOverride) return apiOverride(path, options);
    if (path === '/request-drafts') return {
      request_draft_id: draftId, draft_spec_sha256: specHash,
      original_request_text: options.body.original_request_text,
      original_request_sha256: '5'.repeat(64),
    };
    if (options.method === 'PUT') {
      if (failUpdate) throw new Error('TEST_SAVE_UNAVAILABLE');
      return {...state.draft, ...options.body, draft_spec_sha256: specHash};
    }
    if (path.endsWith('/submissions')) {
      if (failedSubmission) throw new Error('TEST_SUBMISSION_UNAVAILABLE');
      return {command: {resource_id: workflowId}, replayed: false};
    }
    throw new Error('unexpected API request: ' + path);
  },
};
vm.createContext(context);
vm.runInContext(SOURCE, context);
const submissionCalls = () => calls.filter(call => call.path.endsWith('/submissions'));
const plain = value => JSON.parse(JSON.stringify(value));
"""


def _run_browser_checks(checks: str) -> None:
    source = (STATIC / "app.js").read_text(encoding="utf-8")
    request_functions = source[
        source.index("function installRequestDraft()") : source.index("function installWorkflow()")
    ]
    program = HARNESS.replace("SOURCE", json.dumps(request_functions)) + checks
    result = subprocess.run(
        ["node", "--input-type=module", "-e", program],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_new_request_starts_directly_and_submits_exact_editor_snapshot() -> None:
    _run_browser_checks(
        r"""
context.syncDraftControls();
assert.equal(nodes.get('#draft-submit').disabled, false);
assert.equal(nodes.get('#draft-save').disabled, false);
await context.submitDraft();
assert.equal(calls.length, 3);
assert.equal(calls[0].path, '/request-drafts');
assert.equal(calls[0].options.body.original_request_text, normalizedGuidance);
assert.equal(calls[1].options.method, 'PUT');
assert.equal(calls[1].options.body.authoring_guidance, normalizedGuidance);
assert.equal(calls[1].options.body.subject, '통합과학');
assert.equal(calls[1].options.body.choice_count, 5);
assert.equal(calls[1].options.body.equation_required, true);
assert.equal(calls[1].options.body.quality_profile, 'balanced');
assert.equal('quality_profile' in formFields, false);
const presetFields = ['execution_preset_key', 'execution_preset_revision_id',
  'model', 'reasoning_effort'];
for (const field of presetFields) {
  assert.equal(field in calls[1].options.body, false);
  assert.equal(field in calls[2].options.body, false);
}
assert.equal(calls[1].options.body.curriculum_selected_unit_key, unit.key);
assert.equal(calls[1].options.body.topic, '전류와 전압');
assert.equal(calls[1].options.body.material_requirement.form, 'AUTO');
assert.equal(calls[2].options.body.idempotency_key, `studio:${draftId}:${specHash}`);
assert.equal(nodes.get('#workflow-id').value, workflowId);
assert.equal(workflowLoads, 1);
assert.equal(visibleView, 'workflow');
assert.equal(state.draftAction, null);
assert.equal(nodes.get('#draft-submit').disabled, false);
// Server defaults must not overwrite the user's only instruction editor.
assert.equal(formFields.authoring_guidance.value, guidance);
"""
    )


def test_resumed_draft_retains_legacy_metadata_without_a_preset_control() -> None:
    _run_browser_checks(
        r"""
await context.saveDraft();
state.draft = {...state.draft, quality_profile: 'deep'};
const savedId = state.draft.request_draft_id;
const savedSourceHash = state.draft.original_request_sha256;
context.fillDraft(state.draft);
assert.equal('quality_profile' in formFields, false);
assert.equal(context.draftUpdateBody().quality_profile, 'deep');
await context.submitDraft();
assert.equal(state.draft.request_draft_id, savedId);
assert.equal(state.draft.original_request_sha256, savedSourceHash);
const savedUpdate = calls.filter(call => call.options.method === 'PUT').at(-1);
assert.equal(savedUpdate.options.body.quality_profile, 'deep');
assert.deepEqual(plain(submissionCalls()[0].options.body), {
  idempotency_key: `studio:${savedId}:${specHash}`,
});
context.resetDraftEditor();
formFields.authoring_guidance.value = normalizedGuidance;
assert.equal(context.draftUpdateBody().quality_profile, 'balanced');
"""
    )


def test_save_and_submit_share_one_busy_guard_without_duplicate_drafts() -> None:
    _run_browser_checks(
        r"""
let resolveCreate;
apiOverride = (path, options) => path === '/request-drafts'
  ? new Promise(resolve => {resolveCreate = resolve;})
  : options.method === 'PUT'
    ? Promise.resolve({...state.draft, ...options.body, draft_spec_sha256: specHash})
    : Promise.resolve({command: {resource_id: workflowId}, replayed: false});
const pending = context.submitDraft();
assert.equal(state.draftAction, 'SUBMIT');
assert.equal(nodes.get('#draft-submit').disabled, true);
assert.equal(nodes.get('#draft-save').disabled, true);
await context.submitDraft();
await context.saveDraft();
assert.equal(calls.length, 1);
resolveCreate({request_draft_id: draftId, draft_spec_sha256: specHash});
await pending;
assert.equal(submissionCalls().length, 1);
assert.equal(calls.filter(call => call.path === '/request-drafts').length, 1);
assert.equal(state.draftAction, null);
"""
    )


def test_save_failure_preserves_created_identity_and_retry_does_not_create_again() -> None:
    _run_browser_checks(
        r"""
failUpdate = true;
await context.submitDraft();
assert.equal(state.draft.request_draft_id, draftId);
assert.equal(submissionCalls().length, 0);
assert.equal(state.draftAction, null);
assert.equal(nodes.get('#draft-submit').disabled, false);
assert.match(nodes.get('#draft-message').textContent, /TEST_SAVE_UNAVAILABLE/);
failUpdate = false;
await context.submitDraft();
assert.equal(calls.filter(call => call.path === '/request-drafts').length, 1);
assert.equal(calls.filter(call => call.options.method === 'PUT').length, 2);
assert.equal(submissionCalls().length, 1);
assert.equal(submissionCalls()[0].options.body.idempotency_key, `studio:${draftId}:${specHash}`);
"""
    )


def test_edit_during_preparation_never_submits_stale_snapshot_or_overwrites_editor() -> None:
    _run_browser_checks(
        r"""
let resolveCreate;
apiOverride = (path, options) => path === '/request-drafts'
  ? new Promise(resolve => {resolveCreate = resolve;})
  : Promise.resolve({...state.draft, ...options.body, draft_spec_sha256: specHash});
const pending = context.submitDraft();
formFields.authoring_guidance.value = '사용자가 새로 수정한 통합과학 문항 출제 요구입니다.';
formFields.topic.value = '사용자가 바꾼 주제';
formFields.difficulty.value = 'hard';
state.draftEditorRevision++;
resolveCreate({request_draft_id: draftId, draft_spec_sha256: specHash});
await pending;
assert.equal(submissionCalls().length, 0);
assert.equal(state.draftAction, null);
assert.equal(formFields.authoring_guidance.value,
  '사용자가 새로 수정한 통합과학 문항 출제 요구입니다.');
assert.equal(formFields.topic.value, '사용자가 바꾼 주제');
assert.equal(formFields.difficulty.value, 'hard');
// The next explicit click saves and submits the new snapshot with the same draft identity.
apiOverride = null;
await context.submitDraft();
assert.equal(calls.filter(call => call.path === '/request-drafts').length, 1);
assert.equal(submissionCalls().length, 1);
const lastUpdate = calls.filter(call => call.options.method === 'PUT').at(-1);
assert.equal(lastUpdate.options.body.topic, '사용자가 바꾼 주제');
assert.equal(lastUpdate.options.body.difficulty, 'hard');
assert.equal(lastUpdate.options.body.authoring_guidance,
  '사용자가 새로 수정한 통합과학 문항 출제 요구입니다.');
"""
    )


def test_submission_failure_retry_reuses_same_full_hash_key() -> None:
    _run_browser_checks(
        r"""
failedSubmission = true;
await context.submitDraft();
assert.equal(state.draftAction, null);
assert.match(nodes.get('#draft-message').textContent, /TEST_SUBMISSION_UNAVAILABLE/);
const firstKey = submissionCalls()[0].options.body.idempotency_key;
failedSubmission = false;
await context.submitDraft();
assert.equal(calls.filter(call => call.path === '/request-drafts').length, 1);
assert.equal(submissionCalls().length, 2);
assert.equal(submissionCalls()[1].options.body.idempotency_key, firstKey);
assert.equal(firstKey, `studio:${draftId}:${specHash}`);
"""
    )


def test_permissions_and_invalid_editor_prevent_all_preparation_and_submission() -> None:
    _run_browser_checks(
        r"""
state.operator = {effective_permissions: []};
context.syncDraftControls();
assert.equal(nodes.get('#draft-submit').disabled, true);
assert.equal(nodes.get('#draft-save').disabled, true);
await context.submitDraft(); await context.saveDraft();
assert.equal(calls.length, 0);
state.operator = {effective_permissions: ['workflow:start']};
formFields.authoring_guidance.value = '짧음';
await context.submitDraft(); await context.saveDraft();
assert.equal(calls.length, 0);
formFields.authoring_guidance.value = '가'.repeat(2001);
await context.submitDraft(); await context.saveDraft();
assert.equal(calls.length, 0);
formFields.authoring_guidance.value = guidance;
validForm = false;
await context.submitDraft(); await context.saveDraft();
assert.equal(calls.length, 0);
assert.equal(state.draftAction, null);
"""
    )


def test_variation_submission_reuses_exact_source_and_sorted_axes() -> None:
    _run_browser_checks(
        r"""
state.draft = {request_draft_id: draftId, draft_spec_sha256: specHash,
  original_request_sha256: '6'.repeat(64),
  past_exam_variation: {source_item_revision_id: sourceRevisionId,
    variation_axes: ['CONTEXT', 'REASONING_PATH']}};
state.variationSourceEntry = {item_revision_id: sourceRevisionId};
axes = ['REASONING_PATH', 'CONTEXT'];
formFields.knowledge_grounding.checked = true;
formFields.material_form.value = 'TABLE';
formFields.material_panel_count.value = '2';
await context.submitDraft();
assert.equal(calls.filter(call => call.path === '/request-drafts').length, 0);
assert.deepEqual(plain(calls[0].options.body.past_exam_variation), {
  source_item_revision_id: sourceRevisionId,
  variation_axes: ['CONTEXT', 'REASONING_PATH'],
});
assert.equal(calls[0].options.body.knowledge_grounding, true);
assert.equal(calls[0].options.body.material_requirement.form, 'TABLE');
assert.equal(calls[0].options.body.material_requirement.panel_count, 2);
assert.equal(state.draft.original_request_sha256, '6'.repeat(64));
assert.equal(state.variationSourceEntry.item_revision_id, sourceRevisionId);
assert.equal(submissionCalls().length, 1);
"""
    )


def test_empty_variation_axes_and_missing_grounding_unit_fail_before_any_write() -> None:
    _run_browser_checks(
        r"""
state.variationSourceEntry = {item_revision_id: sourceRevisionId};
formFields.knowledge_grounding.checked = true;
assert.throws(() => context.draftUpdateBody(), /변형 축/);
state.variationSourceEntry = null;
state.curriculumSelection = {large: '', middle: '', small: ''};
assert.throws(() => context.draftUpdateBody(), /대단원|중단원|단원/);
await context.submitDraft();
assert.equal(calls.length, 0);
"""
    )


def test_editor_mapping_uses_optional_topic_fallback_and_material_contract() -> None:
    _run_browser_checks(
        r"""
formFields.topic.value = '';
assert.equal(context.draftUpdateBody().topic, unit.label);
state.curriculumSelection = {large: '', middle: '', small: ''};
assert.equal(context.draftUpdateBody().topic, normalizedGuidance);
state.curriculumOutline = null;
assert.equal(context.draftUpdateBody().subject, '통합과학');
formFields.material_form.value = 'MIXED';
formFields.material_panel_count.value = '1';
assert.deepEqual(plain(context.draftUpdateBody().material_requirement), {
  schema_version: 'content-team-material-requirement/2.0', form: 'MIXED',
  panel_count: 2, image_supporting_data: null,
});
formFields.material_form.value = 'IMAGE';
formFields.image_supporting_data.value = 'NONE';
assert.equal(context.draftUpdateBody().material_requirement.image_supporting_data, 'NONE');
"""
    )


def test_save_prepares_editor_without_starting_a_workflow() -> None:
    _run_browser_checks(
        r"""
await context.saveDraft();
assert.equal(calls.length, 2);
assert.equal(calls[0].path, '/request-drafts');
assert.equal(calls[1].options.method, 'PUT');
assert.equal(submissionCalls().length, 0);
assert.equal(workflowLoads, 0);
assert.equal(state.draftAction, null);
assert.equal(formFields.authoring_guidance.value, guidance);
assert.equal(nodes.get('#draft-id').textContent, draftId);
assert.equal(nodes.get('#draft-sha').textContent, specHash);
"""
    )


def test_variation_loading_excludes_other_actions_and_edits_cancel_before_create() -> None:
    _run_browser_checks(
        r"""
let resolveMaterial;
apiOverride = () => new Promise(resolve => {resolveMaterial = resolve;});
const pending = context.beginPastExamVariation(variationEntry);
assert.equal(state.draftAction, 'VARIATION');
assert.equal(nodes.get('#draft-save').disabled, true);
assert.equal(nodes.get('#draft-submit').disabled, true);
await context.saveDraft(); await context.submitDraft();
await assert.rejects(context.beginPastExamVariation(variationEntry), /처리 중/);
assert.equal(calls.length, 1);
assert.match(calls[0].path, /material-requirement$/);
formFields.authoring_guidance.value = '기출을 불러오는 중에 사용자가 수정한 요구입니다.';
state.draftEditorRevision++;
resolveMaterial({form: 'TABLE', panel_count: 1, image_supporting_data: null});
await assert.rejects(pending, /초안이 변경/);
assert.equal(calls.length, 1);
assert.equal(state.draft, null);
assert.equal(state.variationSourceEntry, null);
assert.equal(state.draftAction, null);
assert.equal(nodes.get('#draft-submit').disabled, false);
assert.equal(formFields.authoring_guidance.value,
  '기출을 불러오는 중에 사용자가 수정한 요구입니다.');
"""
    )


def test_edit_during_variation_create_preserves_prior_draft_and_source() -> None:
    _run_browser_checks(
        r"""
const originalDraft = {request_draft_id: 'requestdraft_' + '8'.repeat(32),
  draft_spec_sha256: specHash};
const previousSource = {item_revision_id: 'itemrev_' + '9'.repeat(32)};
state.draft = originalDraft;
state.variationSourceEntry = previousSource;
let resolveCreate;
apiOverride = path => path.endsWith('/material-requirement')
  ? Promise.resolve({form: 'IMAGE', panel_count: 1, image_supporting_data: 'NONE'})
  : new Promise(resolve => {resolveCreate = resolve;});
const pending = context.beginPastExamVariation(variationEntry);
await new Promise(resolve => setImmediate(resolve));
assert.equal(calls.length, 2);
assert.equal(calls[1].path, '/request-drafts');
formFields.authoring_guidance.value = '사용자가 최종 선택한 다른 문항 제작 요구입니다.';
state.draftEditorRevision++;
resolveCreate({request_draft_id: draftId, draft_spec_sha256: specHash});
await assert.rejects(pending, /초안이 변경/);
assert.equal(state.draft, originalDraft);
assert.equal(state.variationSourceEntry, previousSource);
assert.equal(state.draftAction, null);
assert.equal(submissionCalls().length, 0);
assert.equal(formFields.authoring_guidance.value,
  '사용자가 최종 선택한 다른 문항 제작 요구입니다.');
"""
    )


def test_pending_save_prevents_variation_replacing_its_draft() -> None:
    _run_browser_checks(
        r"""
let resolveCreate;
apiOverride = (path, options) => path === '/request-drafts'
  ? new Promise(resolve => {resolveCreate = resolve;})
  : Promise.resolve({...state.draft, ...options.body, draft_spec_sha256: specHash});
const pending = context.saveDraft();
assert.equal(state.draftAction, 'SAVE');
await assert.rejects(context.beginPastExamVariation(variationEntry), /처리 중/);
assert.equal(calls.length, 1);
resolveCreate({request_draft_id: draftId, draft_spec_sha256: specHash});
await pending;
assert.equal(state.draft.request_draft_id, draftId);
assert.equal(state.variationSourceEntry, null);
assert.equal(state.draftAction, null);
assert.equal(submissionCalls().length, 0);
"""
    )


def test_clear_variation_intent_survives_late_save_response() -> None:
    _run_browser_checks(
        r"""
state.draft = {request_draft_id: draftId, draft_spec_sha256: specHash,
  past_exam_variation: {source_item_revision_id: sourceRevisionId,
    variation_axes: ['CONTEXT', 'REASONING_PATH']}};
state.variationSourceEntry = variationEntry;
formFields.knowledge_grounding.checked = true;
for (const input of axisInputs) {
  input.checked = ['CONTEXT', 'REASONING_PATH'].includes(input.value);
}
context.installRequestDraft();
let resolveUpdate;
apiOverride = () => new Promise(resolve => {resolveUpdate = resolve;});
const pending = context.submitDraft();
assert.equal(calls.length, 1);
const oldSnapshot = calls[0].options.body;
assert.equal(oldSnapshot.past_exam_variation.source_item_revision_id, sourceRevisionId);
nodes.get('#past-exam-variation-clear').listeners.get('click')();
assert.equal(state.variationSourceEntry, null);
assert.equal(axisInputs.some(input => input.checked), false);
resolveUpdate({...state.draft, ...oldSnapshot, draft_spec_sha256: specHash});
await pending;
assert.equal(submissionCalls().length, 0);
// A late stored DTO describes the old save, not the current editor's source intent.
assert.equal(state.draft.past_exam_variation.source_item_revision_id, sourceRevisionId);
assert.equal(context.draftUpdateBody().past_exam_variation, null);
apiOverride = null;
await context.submitDraft();
const newSnapshot = calls.filter(call => call.options.method === 'PUT').at(-1).options.body;
assert.equal(newSnapshot.past_exam_variation, null);
assert.equal(submissionCalls().length, 1);
"""
    )


def test_real_editor_input_and_change_events_invalidate_prepared_snapshot() -> None:
    _run_browser_checks(
        r"""
context.installRequestDraft();
const initialRevision = state.draftEditorRevision;
form.listeners.get('input')({target: formFields.authoring_guidance});
form.listeners.get('change')({target: formFields.difficulty});
assert.equal(state.draftEditorRevision, initialRevision + 2);
assert.equal(nodes.get('#draft-state').textContent, '작성 중');
"""
    )


def test_new_draft_reset_is_guarded_and_next_start_creates_a_fresh_request() -> None:
    _run_browser_checks(
        r"""
context.installRequestDraft();
await context.saveDraft();
const savedDraft = state.draft;
const savedText = formFields.authoring_guidance.value;
state.draftAction = 'SUBMIT';
context.resetDraftEditor();
assert.equal(state.draft, savedDraft);
assert.equal(formFields.authoring_guidance.value, savedText);
state.draftAction = null;
nodes.get('#draft-new').listeners.get('click')();
assert.equal(state.draft, null);
assert.equal(state.variationSourceEntry, null);
assert.equal(formFields.authoring_guidance.value, '');
assert.equal(formFields.topic.value, '');
assert.equal(nodes.get('#draft-id').textContent, '-');
assert.equal(nodes.get('#draft-sha').textContent, '-');
assert.equal(axisInputs.some(input => input.checked), false);
assert.equal(submissionCalls().length, 0);
formFields.authoring_guidance.value = '새 초안으로 작성한 두 번째 통합과학 문항 요구입니다.';
await context.submitDraft();
assert.equal(calls.filter(call => call.path === '/request-drafts').length, 2);
assert.equal(submissionCalls().length, 1);
assert.equal(state.draftAction, null);
"""
    )
