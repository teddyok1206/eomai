import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import vm from "node:vm";

const source = await readFile(new URL("../../apps/web_gui/eom_web_gui/static/login.js", import.meta.url), "utf8");
for (const [status, expected] of [[401, "사용자 이름 또는 비밀번호"], [429, "로그인 시도가 많아"], [503, "지금 로그인할 수 없습니다"]]) {
  const button = {disabled: false};
  const error = {textContent: ""};
  let handler;
  const form = {
    elements: {username: {value: "TEST_ONLY"}, password: {value: "TEST_ONLY password"}},
    querySelector: () => button,
    addEventListener: (_, value) => { handler = value; },
  };
  const context = vm.createContext({
    document: {querySelector: selector => selector === "#login-form" ? form : error},
    window: {location: {replace: () => assert.fail("An unsuccessful login must not navigate")}},
    fetch: async () => ({ok: false, status, json: async () => ({request_id: "webreq_" + "a".repeat(24)})}),
  });
  vm.runInContext(source, context);
  await handler({preventDefault() {}});
  assert.ok(error.textContent.includes(expected));
  assert.ok(error.textContent.includes("문의 번호: webreq_"));
  assert.equal(button.disabled, false);
  assert.equal(form.elements.password.value, "");
}
console.log("login_error_copy=PASS");
