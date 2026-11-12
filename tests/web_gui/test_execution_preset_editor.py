from __future__ import annotations

import json
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("case", ["out_of_order", "navigation", "session", "permission", "error"])
def test_admin_settings_refresh_does_not_restore_stale_preset_state(case: str) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the administrator refresh race regression")
    source = (ROOT / "apps/web_gui/eom_web_gui/static/app.js").read_text(encoding="utf-8")
    start = source.index("async function loadAdminSettings() {")
    end = source.index("\nfunction scheduleAnalysisBatchRefresh", start)
    script = f"""
import assert from 'node:assert/strict';
const state = {{adminSettingsRequestSequence:0,navigationVersion:0,executionPresets:[]}};
let admin = true;
const hasAdminRole = () => admin;
const $ = () => ({{}});
const rendered = [], received = [], messages = [], requests = [];
const renderExecutionPresets = values => rendered.push(values);
const presetEditor = {{setPresets: values => received.push(values)}};
const chatModelEditor = {{refresh: async () => undefined}};
const showMessage = (_node, message) => messages.push(message);
const loadOperatorAccounts = async () => undefined;
const api = () => new Promise((resolve,reject) => requests.push({{resolve,reject}}));
{source[start:end]}
const older = loadAdminSettings();
const scenario = {json.dumps(case)};
if (scenario === 'out_of_order' || scenario === 'error') {{
  const newer = loadAdminSettings();
  requests[1].resolve(['newer']);
  await newer;
  if (scenario === 'error') requests[0].reject(new Error('STALE_FAILURE'));
  else requests[0].resolve(['older']);
  await older;
  assert.deepEqual(state.executionPresets, ['newer']);
  assert.deepEqual(rendered, [['newer']]);
  assert.deepEqual(received, [['newer']]);
  assert.equal(messages.length, 1);
}} else {{
  if (scenario === 'navigation') state.navigationVersion++;
  else if (scenario === 'session') state.adminSettingsRequestSequence++;
  else admin = false;
  requests[0].resolve(['obsolete']);
  await older;
  assert.deepEqual(state.executionPresets, []);
  assert.deepEqual(rendered, []);
  assert.deepEqual(received, []);
  assert.deepEqual(messages, []);
}}
"""
    completed = subprocess.run(
        [node, "--input-type=module", "--eval", script],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def _artifact(seed: str) -> dict[str, str]:
    return {
        "artifact_id": "artifact_" + seed * 32,
        "artifact_revision_id": "rev_" + seed * 32,
        "sha256": "sha256:" + seed * 64,
        "schema_ref": "eom.test/1.0",
        "media_type": "application/json",
        "logical_name": "manifest.json",
    }


def _bundle(kind: str, seed: str) -> dict[str, object]:
    return {
        "bundle_id": f"{kind}bundle_" + seed * 32,
        "bundle_revision_id": f"{kind}rev_" + seed * 32,
        "manifest_artifact": _artifact(seed),
        "manifest_sha256": "sha256:" + seed * 64,
    }


def _preset() -> dict[str, object]:
    return {
        "preset_id": "execpreset_" + "1" * 32,
        "preset_key": "standard-item",
        "current_revision_id": "execpresetrev_" + "2" * 32,
        "state": "ACTIVE",
        "revisions": [
            {
                "schema_version": "execution-preset-revision/1.0",
                "preset_revision_id": "execpresetrev_" + "2" * 32,
                "revision_number": 4,
                "display_name": "표준 문항 제작",
                "description": "검증된 표준 실행 정책",
                "capacity_policy_revision_id": "capacityrev_" + "3" * 32,
                "general_knowledge_policy": "ALLOW_WITH_PROVENANCE",
                "compatible_workflow_protocols": ["workflow-role/1.3.0"],
                "content_sha256": "sha256:" + "4" * 64,
                "retrieval_policy": None,
                "role_policies": [
                    {
                        "role": "authoring",
                        "model_candidates": [
                            {"model": "gpt-5.6-terra", "reasoning_effort": "xhigh"},
                            {"model": "gpt-5.6-sol", "reasoning_effort": "high"},
                        ],
                        "instruction_bundle": _bundle("instr", "5"),
                        "reference_bundle": _bundle("ref", "6"),
                        "worker_pool_key": "item-workers",
                        "timeout_seconds": 1800,
                        "sandbox": "read-only",
                        "network": "disabled",
                        "evidence_access": None,
                    }
                ],
                "evaluations": [],
                "server_only_value": "must-not-be-copied",
            }
        ],
    }


def test_guided_editor_preserves_pointers_and_requires_a_new_review(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not available for the browser helper regression")
    module = tmp_path / "execution-preset-editor.mjs"
    module.write_bytes(
        (ROOT / "apps/web_gui/eom_web_gui/static/execution-preset-editor.js").read_bytes()
    )
    script = f"""
import {{
  candidateOptionValue,
  guidedPresetBases,
  reviewedPresetDraft,
}} from {json.dumps(module.as_uri())};
let input = "";
for await (const chunk of process.stdin) input += chunk;
const preset = JSON.parse(input);
const bases = guidedPresetBases([preset]);
if (bases.length !== 1) throw new Error("EDITABLE_BASE_MISSING");
const base = bases[0];
if (base.preset_revision_id !== preset.current_revision_id) throw new Error("CURRENT_NOT_PINNED");
if ("server_only_value" in base.draft) throw new Error("UNREVIEWED_FIELD_COPIED");
if (base.draft.role_policies[0].instruction_bundle.bundle_revision_id !==
    "instrrev_" + "5".repeat(32)) {{
  throw new Error("INSTRUCTION_POINTER_NOT_PRESERVED");
}}
const selected = {{model: "gpt-5.6-sol", reasoning_effort: "xhigh"}};
if (candidateOptionValue(selected.model, selected.reasoning_effort) !== "gpt-5.6-sol::xhigh"
    || candidateOptionValue("model:local", "high") !== "model%3Alocal::high") {{
  throw new Error("CANDIDATE_OPTION_KEY_INVALID");
}}
for (const [model, effort] of [["model with spaces", "high"], ["model-a", "unsupported"]]) {{
  let rejected = false;
  try {{ candidateOptionValue(model, effort); }} catch (error) {{
    rejected = error.message === "PRESET_MODEL_CANDIDATE_INVALID";
  }}
  if (!rejected) throw new Error("INVALID_CANDIDATE_OPTION_NOT_REJECTED");
}}
const draft = reviewedPresetDraft(base.draft, {{
  display_name: "표준 문항 제작 · 고정",
  description: base.draft.description,
  general_knowledge_policy: base.draft.general_knowledge_policy,
  role_policies: [{{
    role: "authoring",
    model_candidates: [selected, {{model: "gpt-5.6-sol", reasoning_effort: "high"}}],
    timeout_seconds: 1800,
  }}],
}});
if (draft.role_policies[0].timeout_seconds !== 1800) throw new Error("TIMEOUT_NOT_PRESERVED");
if (draft.role_policies[0].reference_bundle.bundle_revision_id !== "refrev_" + "6".repeat(32)) {{
  throw new Error("REFERENCE_POINTER_NOT_PRESERVED");
}}
let unchangedFailed = false;
try {{ reviewedPresetDraft(base.draft, {{
  display_name: base.draft.display_name,
  description: base.draft.description,
  general_knowledge_policy: base.draft.general_knowledge_policy,
  role_policies: base.draft.role_policies,
}}); }} catch (error) {{ unchangedFailed = error.message === "PRESET_DRAFT_HAS_NO_CHANGES"; }}
if (!unchangedFailed) throw new Error("UNCHANGED_DRAFT_NOT_REJECTED");
let duplicateFailed = false;
try {{ reviewedPresetDraft(base.draft, {{
  display_name: "변경",
  description: base.draft.description,
  general_knowledge_policy: base.draft.general_knowledge_policy,
  role_policies: [{{
    role: "authoring",
    model_candidates: [selected, selected],
    timeout_seconds: 1800,
  }}],
}}); }} catch (error) {{
  duplicateFailed = error.message === "PRESET_MODEL_CANDIDATES_DUPLICATED";
}}
if (!duplicateFailed) throw new Error("DUPLICATE_CANDIDATE_NOT_REJECTED");
const v2 = structuredClone(preset);
v2.revisions[0].schema_version = "execution-preset-revision/2.0";
v2.revisions[0].retrieval_policy = {{access_policy_revision_id: "accessrev_ignored"}};
if (guidedPresetBases([v2]).length !== 0) throw new Error("INVALID_V2_OFFERED_FOR_EDITOR");
"""
    completed = subprocess.run(
        [node, "--input-type=module", "--eval", script],
        check=False,
        input=json.dumps(_preset()),
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr


def _grounded_preset() -> dict[str, object]:
    value = deepcopy(_preset())
    revision = value["revisions"][0]
    revision["schema_version"] = "execution-preset-revision/2.0"
    revision["state"] = "RELEASED"
    revision["retrieval_policy"] = {
        "access_policy_revision_id": "accessrev_" + "a" * 32,
        "access_policy_sha256": "sha256:" + "b" * 64,
        "allowed_corpus_keys": ["exam_corpus"],
        "allowed_query_kinds": ["ITEM_PREPARATION"],
        "allowed_source_classes": ["PAST_EXAM", "TEXTBOOK"],
        "maximum_budget": {
            "max_documents": 8,
            "max_item_revisions": 8,
            "max_graph_nodes": 32,
            "max_claims": 16,
            "max_context_tokens": 4000,
        },
    }
    authoring = revision["role_policies"][0]
    authoring["model_candidates"] = [{"model": "model-a", "reasoning_effort": "high"}]
    authoring["evidence_access"] = "EVIDENCE_CONTEXT"
    review = deepcopy(authoring)
    review["role"] = "review"
    review["model_candidates"] = [
        {"model": "model-a", "reasoning_effort": "medium"},
        {"model": "model-b", "reasoning_effort": "xhigh"},
    ]
    image = deepcopy(authoring)
    image["role"] = "image"
    image["evidence_access"] = "NONE"
    revision["role_policies"] = [authoring, review, image]
    return value


def test_model_editor_offers_every_current_preset_role(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the preset selection regression")
    module = tmp_path / "execution-preset-editor.mjs"
    module.write_bytes(
        (ROOT / "apps/web_gui/eom_web_gui/static/execution-preset-editor.js").read_bytes()
    )
    script = f"""
import assert from 'node:assert/strict';
import {{guidedPresetBases}} from {json.dumps(module.as_uri())};
let input = ''; for await (const chunk of process.stdin) input += chunk;
const preset = JSON.parse(input);
const before = JSON.stringify(preset);
for (const role of ['authoring', 'review', 'support', 'image', 'item_management']) {{
  const value = structuredClone(preset);
  const current = value.revisions[0];
  current.role_policies = [{{...current.role_policies[0], role}}];
  // Edit the actual current policy, never an unrelated historical authoring policy.
  const historical = structuredClone(preset.revisions[0]);
  historical.preset_revision_id = 'execpresetrev_' + '9'.repeat(32);
  historical.revision_number = 1;
  value.revisions.unshift(historical);
  const bases = guidedPresetBases([value]);
  assert.equal(bases.length, 1);
  if (bases.length) assert.equal(bases[0].preset_revision_id, preset.current_revision_id);
}}
assert.equal(guidedPresetBases([{{...preset, state:'RETIRED'}}]).length, 0);
assert.equal(guidedPresetBases([{{...preset, current_revision_id:null}}]).length, 0);
assert.equal(JSON.stringify(preset), before);
"""
    completed = subprocess.run(
        [node, "--input-type=module", "--eval", script],
        check=False,
        input=json.dumps(_grounded_preset()),
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr


def test_preset_cards_hide_history_without_mutating_pinned_revisions(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the preset presentation regression")
    module = tmp_path / "execution-preset-editor.mjs"
    module.write_bytes(
        (ROOT / "apps/web_gui/eom_web_gui/static/execution-preset-editor.js").read_bytes()
    )
    source = (ROOT / "apps/web_gui/eom_web_gui/static/app.js").read_text(encoding="utf-8")
    start = source.index("function renderExecutionPresets(presets) {")
    end = source.index("\nasync function deprecatePreset", start)
    script = f"""
import assert from 'node:assert/strict';
import {{guidedPresetBases}} from {json.dumps(module.as_uri())};
let input = ''; for await (const chunk of process.stdin) input += chunk;
const preset = JSON.parse(input), current = preset.revisions[0];
const revision = (number, state, seed) => ({{...structuredClone(current),
 preset_revision_id:'execpresetrev_' + seed.repeat(32), revision_number:number,
 display_name:'OLD_OR_DRAFT_' + number, state}});
preset.revisions = [revision(1,'DRAFT','8'), revision(2,'RELEASED','9'),
 revision(7,'DRAFT','a'), current, revision(5,'DRAFT','b')];
const support = structuredClone(preset);
support.preset_id = 'execpreset_' + 'c'.repeat(32);
support.revisions.find(value => value.preset_revision_id === support.current_revision_id)
 .role_policies = [{{...current.role_policies[0],role:'support'}}];
const retired = {{...preset, state:'RETIRED'}};
const missingCurrent = {{...preset, current_revision_id:'execpresetrev_'+'e'.repeat(32)}};
const noCurrent = {{...preset, current_revision_id:null}};
const values = [preset, support, retired, missingCurrent, noCurrent];
const before = JSON.stringify(values);
const node = () => ({{children:[],append(...items){{this.children.push(...items);}},
 replaceChildren(...items){{this.children=[...items];}}}});
const root = node();
const document = {{createElement:node}};
const $ = () => root;
const controlCard = (title,state) => {{const card=node(),details=node();
 Object.assign(card,{{title,state,details}});return {{card,details}};}};
const addControlDetail = (details,label,value) => details.append({{label,value}});
const technicalDisclosure = (label,value) => ({{label,value}});
const actionButton = (label,action) => ({{label,action}});
const presetRoleLabel = value => value;
const inspected = [], deprecated = [];
const presetEditor = {{inspectDraft:(...args)=>inspected.push(args)}};
const deprecatePreset = (...args) => deprecated.push(args);
{source[start:end]}
renderExecutionPresets(values);
assert.equal(root.children.length, 2);
for (const card of root.children) {{
 assert.equal(card.title, current.display_name);
 assert.equal(card.details.children.some(value=>value.label==='고정 버전 수'), false);
 assert.equal(card.children[0].value['현재 고정 버전 ID'], preset.current_revision_id);
}}
const actions = root.children[0].children.at(-1).children;
assert.deepEqual(actions.map(value=>value.label), ['초안 확인·적용','사용 중단']);
actions[0].action();
assert.equal(inspected[0][1].revision_number, 7);
actions[1].action();
assert.deepEqual(deprecated, [[preset.preset_id,current.revision_number]]);
assert.deepEqual(root.children[1].children.at(-1).children.map(value=>value.label),
  ['초안 확인·적용','사용 중단']);
assert.equal(JSON.stringify(values), before);
// Consumed drafts behind the current release are not pending settings.
renderExecutionPresets([{{...preset,revisions:preset.revisions.filter(value=>value.revision_number<=4)}}]);
assert.deepEqual(root.children[0].children.at(-1).children.map(value=>value.label), ['사용 중단']);
renderExecutionPresets([retired,missingCurrent,noCurrent]);
assert.equal(root.children.length, 1);
assert.equal(root.children[0].textContent, '사용 중인 실행 설정이 없습니다.');
"""
    completed = subprocess.run(
        [node, "--input-type=module", "--eval", script],
        check=False,
        input=json.dumps(_grounded_preset()),
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(
    "case",
    [
        "v2_preservation",
        "fixed_timeout",
        "fixed_other_role",
        "missing_evidence",
        "v1_mixed_policy",
        "unsupported_efforts",
        "options_revision",
        "options_pool",
        "options_catalog_entitlement",
        "matching_evaluation",
    ],
)
def test_grounded_model_editor_exact_policy_and_admission_helpers(
    tmp_path: Path, case: str
) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the model editor contract helper")
    module = tmp_path / "execution-preset-editor.mjs"
    module.write_bytes(
        (ROOT / "apps/web_gui/eom_web_gui/static/execution-preset-editor.js").read_bytes()
    )
    script = f"""
import assert from 'node:assert/strict';
import {{guidedPresetBases, reviewedPresetDraft, approvedPresetModelOptions,
  candidateOptionValue, presetCandidateLabel, presetValidationSucceeded}}
  from {json.dumps(module.as_uri())};
let input = ''; for await (const chunk of process.stdin) input += chunk;
const preset = JSON.parse(input);
const base = guidedPresetBases([preset])[0]; assert.ok(base);
const edits = {{display_name: base.draft.display_name, description: base.draft.description,
  general_knowledge_policy: base.draft.general_knowledge_policy,
  role_policies: structuredClone(base.draft.role_policies)}};
edits.role_policies[0].model_candidates[0] = {{model: 'model-b', reasoning_effort: 'high'}};
const options = {{preset_revision_id: base.preset_revision_id, catalog_is_entitlement: false,
  roles: base.draft.role_policies.map(policy => ({{role: policy.role,
    worker_pool_key: policy.worker_pool_key,
    candidates: [{{model: 'model-a', reasoning_effort: 'medium'}},
      {{model: 'model-b', reasoning_effort: 'high'}}]}}))}};
const scenario = {json.dumps(case)};
if (scenario === 'v2_preservation') {{
  const result = reviewedPresetDraft(base.draft, edits);
  assert.equal(result.target_revision_schema_version, 'execution-preset-revision/2.0');
  assert.deepEqual(result.retrieval_policy, base.draft.retrieval_policy);
  for (let index = 0; index < result.role_policies.length; index++) {{
    const before = base.draft.role_policies[index], after = result.role_policies[index];
    for (const key of ['instruction_bundle','reference_bundle','worker_pool_key',
      'timeout_seconds','sandbox','network','evidence_access']) {{
      assert.deepEqual(after[key], before[key]);
    }}
  }}
  assert.deepEqual(result.role_policies[1], base.draft.role_policies[1]);
  assert.equal(presetCandidateLabel('review', 0), '기본 검토');
  assert.equal(presetCandidateLabel('review', 1), '강화 검토');
}} else if (scenario === 'fixed_timeout') {{
  edits.role_policies[0].timeout_seconds++;
  assert.throws(() => reviewedPresetDraft(base.draft, edits), /PRESET_FIXED_POLICY_CHANGED/);
}} else if (scenario === 'fixed_other_role') {{
  edits.role_policies[2].model_candidates[0] = {{model: 'model-b', reasoning_effort: 'high'}};
  assert.equal(reviewedPresetDraft(base.draft, edits).role_policies[2]
    .model_candidates[0].model, 'model-b');
}} else if (scenario === 'missing_evidence') {{
  preset.revisions[0].role_policies[0].evidence_access = null;
  assert.equal(guidedPresetBases([preset]).length, 0);
}} else if (scenario === 'v1_mixed_policy') {{
  preset.revisions[0].schema_version = 'execution-preset-revision/1.0';
  assert.equal(guidedPresetBases([preset]).length, 0);
}} else if (scenario === 'unsupported_efforts') {{
  for (const effort of ['max','ultra']) {{
    assert.throws(() => candidateOptionValue('model-b', effort));
  }}
}} else if (scenario === 'options_revision') {{
  options.preset_revision_id = 'execpresetrev_' + 'f'.repeat(32);
  assert.throws(() => approvedPresetModelOptions(base, options), /PRESET_MODEL_OPTIONS_STALE/);
}} else if (scenario === 'options_pool') {{
  options.roles[0].worker_pool_key = 'wrong-workers';
  assert.throws(() => approvedPresetModelOptions(base, options), /PRESET_MODEL_OPTIONS_INVALID/);
}} else if (scenario === 'options_catalog_entitlement') {{
  options.catalog_is_entitlement = true;
  assert.throws(() => approvedPresetModelOptions(base, options), /PRESET_MODEL_OPTIONS_STALE/);
}} else if (scenario === 'matching_evaluation') {{
  const target = {{validation_id:'job_'+'1'.repeat(32),
    preset_revision_id:'execpresetrev_'+'2'.repeat(32),base_revision_id:base.preset_revision_id}};
  const passed = {{...target, preset_policy_sha256:'sha256:'+'4'.repeat(64),
    scope:'NON_LIVE',quality_evaluated:false,
    status:'SUCCEEDED',evaluation_id:'preseteval_'+'5'.repeat(32),completed_at:'2026-10-09T00:00:00Z',cases_total:12,cases_passed:12}};
  assert.equal(presetValidationSucceeded(passed,target),true);
  for (const change of [{{preset_revision_id:'execpresetrev_'+'9'.repeat(32)}},
    {{base_revision_id:'execpresetrev_'+'8'.repeat(32)}},{{quality_evaluated:true}},
    {{scope:'LIVE_ONE_SHOT'}},{{cases_passed:11}},{{evaluation_id:null}},{{error_code:'ERROR'}}]) {{
    assert.equal(presetValidationSucceeded({{...passed,...change}},target),false);
  }}
}}
"""
    completed = subprocess.run(
        [node, "--input-type=module", "--eval", script],
        input=json.dumps(_grounded_preset()),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
