"""Execute the actual browser polling code with isolated authentication responses."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "apps/web_gui/eom_web_gui/static/app.js"


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
    requests.push(path); return {state: stateName, binding_id: 'binding', challenge_available: false};
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
