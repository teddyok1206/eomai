import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import {createCuratedDeliveryControl} from "../../apps/web_gui/eom_web_gui/static/item-db-delivery.js";
globalThis.crypto = webcrypto;

class Element {
  constructor() { this.children = []; this.attributes = {}; this.events = {}; this.isConnected = true; }
  append(...children) { this.children.push(...children); }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, callback) { this.events[name] = callback; }
}
const document = {createElement() { return new Element(); }};
const entry = {assembly_id: `assembly_${"a".repeat(32)}`, assembly_revision_id: `assemblyrev_${"b".repeat(32)}`, manifest_sha256: `sha256:${"c".repeat(64)}`};
let state = "RUNNING";
let failOnce = true;
const calls = [];
const keys = [];
const storage = new Map();
const api = async (path, options) => {
  calls.push([path, options?.method || "GET"]);
  if (path.includes("/latest?")) return null;
  if (options?.method === "POST") {
    keys.push(options.headers["Idempotency-Key"]);
    if (failOnce) { failOnce = false; throw new Error("response lost after submission"); }
  }
  return {...entry, build_id: `hwpxbuild_${"d".repeat(32)}`, state, download_available: state === "SUCCEEDED"};
};
let scheduled;
const control = createCuratedDeliveryControl({document, api, entry,
  storage: {getItem: (key) => storage.get(key), setItem: (key, value) => storage.set(key, value)},
  setTimer: (fn) => { scheduled = fn; return 1; }, clearTimer: () => { scheduled = null; },
});
const [button, status, download] = control.element.children;
await button.events.click();
assert.match(status.textContent, /response lost/);
await button.events.click();
assert.equal(keys.length, 2);
assert.equal(keys[0], keys[1], "unknown submission outcome must retain its original key");
assert.match(status.textContent, /제작 중/);
assert.equal(control.element.attributes["aria-busy"], "true");
state = "SUCCEEDED";
await button.events.click();
assert.equal(download.hidden, false);
assert.match(download.href, /\/studio\/api\/v1\/item-db\/assemblies\/assembly_[a-f0-9]+\/hwpx-builds\/hwpxbuild_[a-f0-9]+\/download$/);
const creates = calls.filter(([, method]) => method === "POST").length;
await button.events.click();
assert.equal(calls.filter(([, method]) => method === "POST").length, creates, "completed refresh cannot render again");
control.dispose();
assert.equal(scheduled, null);
console.log("item_db_delivery=PASS");
