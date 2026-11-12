"""Execute the actual browser polling code with isolated authentication responses."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "apps/web_gui/eom_web_gui/static/app.js"


def test_quota_badge_is_neutral_only_for_fresh_ready_usage() -> None:
    node = shutil.which("node")
    assert node is not None
    source = APP.read_text(encoding="utf-8")
    function = source[
        source.index("function codexAccountDisplayState(") : source.index(
            "function renderCodexUsage("
        )
    ]
    script = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const context = {};
vm.createContext(context);
vm.runInContext(FUNCTION, context);
const now = Date.parse('2026-10-28T04:00:00Z');
const account = {
  state: 'READY',
  usage_observation: {
    observed_at: '2026-10-28T03:59:00Z',
    windows: [{used_percent: 100, resets_at: '2026-10-28T05:00:00Z'}],
  },
};
assert.equal(context.codexAccountDisplayState(account, now), 'USAGE_EXHAUSTED');
assert.equal(context.codexAccountDisplayState({...account, state: 'DEGRADED'}, now), 'DEGRADED');
assert.equal(
  context.codexAccountDisplayState({...account, state: 'AUTH_REQUIRED'}, now), 'AUTH_REQUIRED'
);
assert.equal(context.codexAccountDisplayState(account, now + 16 * 60 * 1000), 'READY');
assert.equal(context.codexAccountDisplayState({...account, usage_observation: {
  ...account.usage_observation, windows: [{used_percent: 100, resets_at: '2026-10-28T03:59:59Z'}],
}}, now), 'READY');
assert.equal(context.codexAccountDisplayState({...account, usage_observation: {
  ...account.usage_observation, windows: [{used_percent: 99, resets_at: '2026-10-28T05:00:00Z'}],
}}, now), 'READY');
""".replace("FUNCTION", json.dumps(function))
    completed = subprocess.run([node, "-e", script], capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr


def test_usage_refresh_remains_available_when_exhausted_or_capability_limited() -> None:
    node = shutil.which("node")
    assert node is not None
    source = APP.read_text(encoding="utf-8")
    function = source[
        source.index("async function refreshCodexAccount(") : source.index(
            "function renderCodexAccounts("
        )
    ]
    assert "usageButton.disabled" not in source
    script = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const calls = [];
const context = {
  loadCodexAccounts: async () => calls.push('READ_ONLY'),
  modelCatalogObservation: {observe: async () => calls.push('OBSERVE')},
  $: () => ({}), showMessage: () => {},
};
vm.createContext(context);
vm.runInContext(FUNCTION, context);
(async () => {
  const exhausted = {
    state: 'DEGRADED', active_lease_count: 0,
    usage_observation: {windows: [{used_percent: 100}]},
  };
  await context.refreshCodexAccount(exhausted);
  await context.refreshCodexAccount({...exhausted, active_lease_count: 1});
  await context.refreshCodexAccount({...exhausted, assignment_purpose: 'GENERAL_CHAT',
    active_chat_count: 1, chat_runtime_state: 'BUSY'});
  await context.refreshCodexAccount({...exhausted, assignment_purpose: 'GENERAL_CHAT',
    active_chat_count: 1, chat_runtime_state: 'UNAVAILABLE'});
  await context.refreshCodexAccount({...exhausted, active_auth_enrollment_id: 'authflow_test'});
  assert.deepEqual(calls, [
    'OBSERVE', 'READ_ONLY', 'OBSERVE', 'READ_ONLY', 'OBSERVE', 'READ_ONLY',
    'OBSERVE', 'READ_ONLY', 'READ_ONLY',
  ]);
})().catch((error) => { console.error(error); process.exitCode = 1; });
""".replace("FUNCTION", json.dumps(function))
    completed = subprocess.run([node, "-e", script], capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr


def test_reserved_chat_slot_display_and_login_busy_guard_use_real_chat_occupation() -> None:
    node = shutil.which("node")
    assert node is not None
    source = APP.read_text(encoding="utf-8")
    functions = (
        source[source.index("function codexSlotCard(") : source.index("function addControlDetail(")]
        + source[
            source.index("function renderCodexAccounts(") : source.index(
                "function clearCodexDeviceChallenge("
            )
        ]
    )
    script = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
class Element {
  constructor() { this.children=[];this.dataset={};this.disabled=false;
    this.classes=new Set();this.classList={add:name=>this.classes.add(name)}; }
  append(...values) { this.children.push(...values); }
  replaceChildren(...values) { this.children=[...values]; }
  setAttribute() {}
}
const root=new Element(),summary=new Element();
const context = {
  document:{createElement:()=>new Element()},
  $:selector=>selector==='#codex-account-list'?root:summary,
  $$:()=>[],
  workerSlotLabel:key=>key,
  codexAccountDisplayState:account=>account.state,
  setStatus:(node,_tone,_icon,text)=>{node.textContent=text;},
  setStateStatus:(node,_domain,state)=>{node.textContent=state;},
  statePresentation:(_domain,state)=>({label:state}),
  addControlDetail:(node,label,value)=>node.append({label,value}),
  renderCodexUsage:()=>new Element(),
  actionButton:(label,action)=>Object.assign(new Element(),{label,action}),
  refreshCodexAccount:()=>{},sendAccountCommand:()=>{},
  resumeCodexReauthentication:()=>{},openCodexReauthentication:()=>{},
};
vm.createContext(context);
vm.runInContext(FUNCTIONS, context);
const account = {binding_id:'test',slot_key:'slot06',state:'READY',capabilities:[],
 active_lease_count:0,assignment_purpose:'GENERAL_CHAT',active_chat_count:0,
 chat_runtime_state:'READY'};
for (const [state,count,label,active] of [
 ['READY',0,'대화 대기',false],['BUSY',1,'답변 중',true],
 ['UNAVAILABLE',1,'대화 상태 확인 필요',false],['UNAVAILABLE',0,'대화 준비 중',false],
]) {
 context.renderCodexAccounts([{...account,chat_runtime_state:state,active_chat_count:count}]);
 const card=root.children[0],header=card.children[0],body=card.children[1];
 assert.equal(header.children[1].textContent,'slot06 · ChatGPT 전용');
 assert.equal(header.children[2].textContent,label);
 assert.equal(card.classes.has('is-active'),active);
 const actions=body.children.at(-1).children;
 assert.equal(actions[0].label,'상태·사용량 새로고침');
 assert.equal(actions[0].disabled,false);
 assert.equal(actions.at(-1).label,'계정 로그인 변경');
 assert.equal(actions.at(-1).disabled,Boolean(count));
 assert.equal(body.children[0].children.find(value=>value.label==='진행 중인 작업').value,0);
 assert.equal(summary.textContent.includes('작업 중'),active);
}
context.renderCodexAccounts([{...account,assignment_purpose:'GENERAL_WORK',
 chat_runtime_state:null,active_chat_count:0,active_lease_count:1}]);
assert.equal(root.children[0].children[0].children[1].textContent,'slot06');
assert.equal(root.children[0].children[0].children[2].textContent,'1개 작업 중');
assert.equal(root.children[0].children[1].children.at(-1).children.at(-1).disabled,true);
assert.equal(account.active_lease_count,0);
""".replace("FUNCTIONS", json.dumps(functions))
    result = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, check=False, timeout=10
    )
    assert result.returncode == 0, result.stderr


def test_expired_usage_window_does_not_claim_zero_remaining_after_reset() -> None:
    node = shutil.which("node")
    assert node is not None
    source = APP.read_text(encoding="utf-8")
    function = source[
        source.index("function renderCodexUsage(") : source.index(
            "async function refreshCodexAccount("
        )
    ]
    script = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
class Element {
  constructor() { this.children = []; this.textContent = ''; }
  append(...children) { this.children.push(...children); }
  setAttribute() {}
}
const context = {
  document: {createElement: () => new Element()},
  usageWindowLabel: () => '주간 사용량',
  formatSeoulDateTime: () => '표시 시각',
};
vm.createContext(context);
vm.runInContext(FUNCTION, context);
const usage = (resets_at) => ({
  plan_type: 'plus', observed_at: '2026-10-27T00:00:00Z',
  windows: [{limit_id: 'codex', used_percent: 100, resets_at}],
});
const percent = (result) => result.children[1].children[0].children[1].textContent;
assert.match(percent(context.renderCodexUsage(usage('2020-01-01T00:00:00Z'))), /새로고침 필요/);
assert.doesNotMatch(percent(context.renderCodexUsage(usage('2020-01-01T00:00:00Z'))), /0% 남음/);
assert.match(percent(context.renderCodexUsage(usage('2099-01-01T00:00:00Z'))), /0% 남음/);
""".replace("FUNCTION", json.dumps(function))
    completed = subprocess.run([node, "-e", script], capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr


def test_model_verification_keeps_polling_without_asking_for_device_login_again() -> None:
    node = shutil.which("node")
    assert node is not None
    source = APP.read_text(encoding="utf-8")
    functions = source[
        source.index("async function pollCodexAuthEnrollment(") : source.index(
            "async function revealCodexDeviceChallenge("
        )
    ]
    script = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const elements = new Map();
const messages = [], requests = [], timers = [];
let stateName = 'VERIFYING', cleared = 0, reloads = 0, accountState = 'READY';
const context = {
  state: {codexAuthEnrollmentId: 'authflow_test'},
  api: async (path) => {
    requests.push(path);
    return {state: stateName, binding_id: 'binding', challenge_available: false};
  },
  $: (key) => { if (!elements.has(key)) elements.set(key, {}); return elements.get(key); },
  statePresentation: () => ({label: 'state'}),
  showMessage: (...args) => messages.push(args[1]),
  clearCodexDeviceChallenge: () => ++cleared,
  setStatus: () => {},
  loadCodexAccounts: async () => {
    ++reloads; context.state.codexAccounts = [{binding_id: 'binding', state: accountState}];
  },
  window: {setTimeout: (fn, delay) => timers.push(delay)},
};
vm.createContext(context);
vm.runInContext(FUNCTIONS, context);
(async () => {
  await context.pollCodexAuthEnrollment('authflow_test');
  assert.equal(elements.get('#codex-reauth-state').textContent, '로그인 및 모델 사용 확인 중');
  assert.equal(timers[0], 2000);
  assert.ok(messages.some((message) => message.includes('다시 로그인할 필요는 없습니다')));
  assert.equal(cleared, 1);
  stateName = 'SUCCEEDED';
  await context.pollCodexAuthEnrollment('authflow_test');
  assert.equal(reloads, 1);
  assert.equal(timers.length, 1);
  // A later administrator stop is not evidence that model verification failed.
  accountState = 'DISABLED';
  await context.pollCodexAuthEnrollment('authflow_test');
  assert.ok(messages.at(-1).includes('사용 중지 또는 제한 상태'));
  assert.ok(!messages.at(-1).includes('모델이 확인되지 않아'));
  assert.ok(requests.every((path) => path.endsWith('/authflow_test')));
})().catch((error) => { console.error(error); process.exitCode = 1; });
""".replace("FUNCTIONS", json.dumps(functions))
    completed = subprocess.run([node, "-e", script], capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr


def test_denied_slot_reads_stop_polling_and_remove_cached_management_actions() -> None:
    node = shutil.which("node")
    assert node is not None, "Node is required for the browser behavior gate"
    source = APP.read_text(encoding="utf-8")
    functions = source[
        source.index("function scheduleCodexAccountRefresh()") : source.index(
            "async function loadCodexControlPlane()"
        )
    ]
    script = r"""
const assert = require("node:assert/strict");
const vm = require("node:vm");
const source = FUNCTIONS;
function setup(api) {
  const pendingTimers = [];
  const cardList = {
    children: ["cached privileged actions"],
    replaceChildren(...children) { this.children = children; },
    append(child) { this.children.push(child); },
  };
  const context = {
    state: {codexAccounts: ["cached account"], codexAccountRequestSequence: 0},
    window: {
      clearTimeout() {},
      setTimeout(fn, delay) { pendingTimers.push({fn, delay}); return 1; },
    },
    hasAdminRole: () => true,
    $: (selector) => selector === "#codex-account-list" ? cardList : {},
    api,
    setStatus: () => {},
    showMessage: () => {},
    renderCodexAccounts: () => {},
    actionButton: (label, action) => ({label, action}),
    logout: () => {},
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  return {context, pendingTimers, cardList};
}
(async () => {
  const denials = [
    "AUTH_REAUTHENTICATION_REQUIRED", "PERMISSION_DENIED", "AUTH_PASSWORD_CHANGE_REQUIRED",
  ];
  for (const code of denials) {
    const view = setup(async () => { throw {code, message: code}; });
    await view.context.loadCodexAccounts();
    assert.equal(view.pendingTimers.length, 0, code);
    assert.equal(view.context.state.codexAccounts.length, 0, code);
    if (code === "AUTH_REAUTHENTICATION_REQUIRED") {
      assert.equal(view.cardList.children.length, 1);
      assert.equal(view.cardList.children[0].label, "로그아웃 후 다시 로그인");
      assert.equal(view.cardList.children[0].action, view.context.logout);
    } else {
      assert.equal(view.cardList.children.length, 0);
    }
  }
  const retryableReads = [
    async () => ["fresh account"],
    async () => { throw {code: "HTTP_503", message: "temporary"}; },
  ];
  for (const api of retryableReads) {
    const view = setup(api);
    await view.context.loadCodexAccounts();
    assert.equal(view.pendingTimers.length, 1);
    assert.equal(view.pendingTimers[0].delay, 5000);
  }
  // An old success must not undo a newer authentication denial.
  let resolveOld;
  let callCount = 0;
  const race = setup(() => ++callCount === 1
    ? new Promise((resolve) => { resolveOld = resolve; })
    : Promise.reject({code: "AUTH_REAUTHENTICATION_REQUIRED", message: "fresh auth"}));
  const old = race.context.loadCodexAccounts();
  await race.context.loadCodexAccounts();
  resolveOld(["stale account"]);
  await old;
  assert.equal(race.context.state.codexAccounts.length, 0);
  assert.equal(race.pendingTimers.length, 0);
})().catch((error) => { console.error(error); process.exitCode = 1; });
""".replace("FUNCTIONS", json.dumps(functions))
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
