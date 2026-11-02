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
const owner = "operator_" + "1".repeat(32);
const other = "operator_" + "2".repeat(32);
const keyName = "eom:item-db-similarity:1";
const entry = {source_id: "extitem_" + "3".repeat(32), source_revision_id: "extitemrev_" + "4".repeat(32),
  observation_sha256: "sha256:" + "5".repeat(64), external_number: "10321", private_content: "must-not-be-stored"};
const selection = itemDbSimilaritySelection("EXTERNAL_SOURCE", entry);
const values = new Map();
const storage = {getItem: (key) => values.get(key) ?? null,
  setItem: (key, value) => values.set(key, value), removeItem: (key) => values.delete(key)};
class Element {
  constructor() {this.hidden = true; this.textContent = ""; this.children = []; this.events = new Map();}
  append(...children) {this.children.push(...children);}
  replaceChildren(...children) {this.children = children;}
  addEventListener(name, callback) {this.events.set(name, callback);}
  setAttribute(name, value) {this[name] = value;}
}
function fixture(search, continuationStorage = () => storage) {
  const elements = new Map();
  const document = {querySelector(selector) {
    if (!elements.has(selector)) elements.set(selector, new Element());
    return elements.get(selector);
  }, createElement: () => new Element()};
  const tabs = [];
  const app = createItemDbSimilarity({document, search, continuationStorage,
    activate: (tab) => tabs.push(tab), openSelection() {}});
  app.install();
  return {app, tabs, get: (selector) => document.querySelector(selector),
    refresh: () => document.querySelector("#item-db-similarity-refresh").events.get("click")()};
}
let original;
const firstCalls = [];
const first = fixture(async (pointer, key, pin) => {
  firstCalls.push({pointer, key, pin});
  original = {schema_version: "system-rag-reference-query-prepare-request/4.0", idempotency_key: key,
    request_sha256: "sha256:" + "6".repeat(64)};
  return {status: "PENDING", phase: "COMPUTING", pinned_query: original};
});
first.app.setOwner(owner);
await first.app.start(selection, "고유번호 10321");
const saved = values.get(keyName);
assert(saved && !saved.includes("must-not-be-stored"));
assert.deepEqual(Object.keys(JSON.parse(saved)).sort(), ["version", "owner", "selection", "sourceClass", "label", "key", "pin", "startedAt"].sort());
assert.equal(values.size, 1);
timers.clear(); // A navigation destroys the old page, not the server's operation.

const calls = [];
const restored = fixture(async (pointer, key, pin) => {
  calls.push({pointer, key, pin});
  return {status: "READY", phase: "READING_RESULTS", candidates: [], pinned_query: pin};
});
restored.app.setOwner(owner);
assert.equal(calls.length, 0, "login must not submit/compute automatically");
assert.equal(restored.get("#item-db-similarity-refresh").disabled, false);
assert.equal(restored.get("#item-db-similarity-anchor").textContent, "고유번호 10321");
assert.deepEqual(restored.tabs, ["similarity"]);
await restored.refresh();
assert.deepEqual(calls[0].pointer, selection.pointer);
assert.equal(calls[0].key, firstCalls[0].key);
assert.deepEqual(calls[0].pin, original, "use the original pin, never latest");
assert.equal(timers.size, 0);
assert.equal(JSON.parse(values.get(keyName)).key, firstCalls[0].key);
restored.app.setOwner(null);
assert.equal(values.size, 0, "explicit logout removes continuation");

for (const mutate of [
  (value) => {value.version = 2;},
  (value) => {value.owner = other;},
  (value) => {value.key = "new-unsafe-key";},
  (value) => {value.startedAt -= 25 * 60 * 60 * 1000;},
  (value) => {value.startedAt = Date.now() + 60_000;},
  (value) => {value.label = "x".repeat(513);},
  (value) => {value.selection.observation_sha256 = "/untrusted/latest";},
  (value) => {value.pin.idempotency_key = "different-key";},
  (value) => {value.pin.schema_version = "unreleased";},
  (value) => {value.pin.request_sha256 = "wrong-hash";},
  (value) => {value.pin.oversized = "x".repeat(65_536);},
]) {
  const value = JSON.parse(saved); mutate(value);
  values.set(keyName, JSON.stringify(value));
  const invalid = fixture(() => {throw new Error("must not call API");});
  invalid.app.setOwner(owner);
  assert.equal(invalid.get("#item-db-similarity-refresh").disabled, true);
  assert.equal(values.size, 0, "invalid local metadata must not select latest or another key");
}
values.set(keyName, "not-json");
const malformed = fixture(() => {}); malformed.app.setOwner(owner);
assert.equal(values.size, 0);

values.set(keyName, saved);
const revoked = fixture(() => {throw new Error("no source permission");});
revoked.app.setOwner(owner, false);
assert.equal(revoked.get("#item-db-similarity-refresh").disabled, true);
assert.equal(values.size, 0);

const graphValue = JSON.parse(saved);
graphValue.sourceClass = "PAST_EXAM";
graphValue.selection = {kind: "GRAPH_ITEM", item_id: "item_" + "7".repeat(32),
  item_revision_id: "itemrev_" + "8".repeat(32), item_manifest_sha256: "sha256:" + "9".repeat(64),
  graph_snapshot_revision_id: "graphrev_" + "a".repeat(32), graph_snapshot_sha256: "sha256:" + "b".repeat(64)};
values.set(keyName, JSON.stringify(graphValue));
const graphCalls = [];
const graphApp = fixture(async (pointer, key, pin) => {
  graphCalls.push({pointer, key, pin});
  return {status: "READY", phase: "READING_RESULTS", candidates: [], pinned_query: pin};
});
graphApp.app.setOwner(owner, false);
assert.equal(graphCalls.length, 0);
await graphApp.refresh();
assert.deepEqual(graphCalls[0].pointer, graphValue.selection);
assert.deepEqual(graphCalls[0].pin, original);
graphApp.app.setOwner(null);
assert.equal(values.size, 0);

values.set(keyName, saved);
const denied = fixture(async () => {throw new Error("SOURCE_ACCESS_DENIED");});
denied.app.setOwner(owner);
await denied.refresh();
assert.match(denied.get("#item-db-similarity-message").textContent, /SOURCE_ACCESS_DENIED/);
assert.equal(timers.size, 0, "a current authorization failure is not a retry grant");
assert.equal(JSON.parse(values.get(keyName)).key, firstCalls[0].key);
denied.app.reset();
assert.equal(values.size, 0, "permission change removes continuation");

const blockedStore = fixture(async () => ({status: "READY", phase: "READING_RESULTS", candidates: []}),
  () => {throw new Error("browser storage unavailable");});
blockedStore.app.setOwner(owner);
await blockedStore.app.start(selection, "고유번호 10321");
assert.equal(blockedStore.get("#item-db-similarity-count").textContent, "0개");

let release;
const changing = fixture(() => new Promise((resolve) => {release = resolve;}));
changing.app.setOwner(owner);
const pending = changing.app.start(selection, "고유번호 10321");
changing.app.setOwner(other);
release({status: "READY", phase: "READING_RESULTS", candidates: [], pinned_query: original});
await pending;
assert.equal(values.size, 0);
assert.equal(changing.get("#item-db-similarity-refresh").disabled, true);
assert.equal(changing.get("#item-db-similarity-count").textContent, "검색 전");
assert.equal(timers.size, 0);
console.log("similarity_same_owner_relogin_original_request_continuation=PASS live_writes=0");
