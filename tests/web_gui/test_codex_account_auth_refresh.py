"""Execute the actual browser polling code with isolated authentication responses."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "apps/web_gui/eom_web_gui/static/app.js"


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
