import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import {createItemDbSimilarity, itemDbSimilaritySelection} from "../../apps/web_gui/eom_web_gui/static/item-db-similarity.js";

globalThis.crypto ??= webcrypto;
const timers = new Map();
let nextTimer = 0;
globalThis.setTimeout = (callback) => {const id = ++nextTimer; timers.set(id, callback); return id;};
globalThis.clearTimeout = (id) => timers.delete(id);
globalThis.setInterval = () => ++nextTimer;
globalThis.clearInterval = () => {};

class Element {
  constructor() {this.hidden = true; this.textContent = ""; this.children = []; this.events = new Map();}
  append(...children) {this.children.push(...children);}
  replaceChildren(...children) {this.children = children;}
  addEventListener(name, callback) {this.events.set(name, callback);}
  setAttribute(name, value) {this[name] = value;}
}
const elements = new Map();
const document = {
  querySelector(selector) {if (!elements.has(selector)) elements.set(selector, new Element()); return elements.get(selector);},
  createElement() {return new Element();},
};
const entry = {source_id: "extitem_" + "1".repeat(32), source_revision_id: "extitemrev_" + "2".repeat(32), observation_sha256: "sha256:" + "3".repeat(64)};
const selection = itemDbSimilaritySelection("EXTERNAL_SOURCE", entry);
const original = {schema_version: "system-rag-reference-query-prepare-request/4.0", request_sha256: "sha256:" + "4".repeat(64)};
const calls = [];
let activated;
const app = createItemDbSimilarity({document, activate(value) {activated = value;}, openSelection() {},
  async search(pointer, key, pin) {
    calls.push({pointer, key, pin});
    if (calls.length === 1) return {status: "PENDING", phase: "PREPARING", pinned_query: original, message: "원 범위 준비 완료"};
    if (calls.length === 2) throw new Error("synthetic preparation response timeout");
    return {status: "READY", phase: "READING_RESULTS", pinned_query: original, candidates: []};
  },
});
app.install();
await app.start(selection, "합성 문항");
assert.equal(activated, "similarity");
assert.equal(document.querySelector("#item-db-similarity-progress").hidden, false);
assert.equal(document.querySelector("#item-db-similarity-tab-progress").hidden, false);
assert.equal(document.querySelector("#item-db-similarity-progress-label").textContent, "검색 준비 중");
assert.equal(calls[0].pin, null);
assert.equal(timers.size, 1);
const callback = [...timers.values()][0];
await callback();
assert.equal(calls[1].pin, original);
assert.match(document.querySelector("#item-db-similarity-message").textContent, /timeout/);
assert.equal(document.querySelector("#item-db-similarity-refresh").disabled, false);
assert.equal(timers.size, 0, "failed observation must not auto-spam or create another search");
await document.querySelector("#item-db-similarity-refresh").events.get("click")();
assert.equal(calls.length, 3);
assert(calls.every(call => call.pointer === selection.pointer && call.key === calls[0].key));
assert.equal(calls[2].pin, original, "response failure must not lose the original query pin");
assert.equal(document.querySelector("#item-db-similarity-progress").hidden, true);
assert.equal(document.querySelector("#item-db-similarity-tab-progress").hidden, true);
await document.querySelector("#item-db-similarity-refresh").events.get("click")();
assert.equal(calls.length, 3, "completed result confirmation must never submit another query");
assert.equal(document.querySelector("#item-db-similarity-progress").hidden, true);
app.reset();
assert.equal(timers.size, 0);
console.log("similarity_preparing_original_pin_and_timeout_replay=PASS live_writes=0");
