import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import {createItemDbSimilarityList} from "../../apps/web_gui/eom_web_gui/static/item-db-similarity-list.js";
import {itemDbSimilaritySelection} from "../../apps/web_gui/eom_web_gui/static/item-db-similarity.js";

globalThis.crypto ??= webcrypto;
const timers = new Map();
let timerId = 0;
globalThis.setTimeout = (callback, delay) => {timers.set(++timerId, {callback, delay}); return timerId;};
globalThis.clearTimeout = id => timers.delete(id);
globalThis.setInterval = () => 2;
globalThis.clearInterval = () => {};
class Element {
  constructor() {this.children = []; this.events = new Map(); this.value = "5"; this.textContent = "";}
  append(...values) {this.children.push(...values);}
  replaceChildren(...values) {this.children = values;}
  addEventListener(name, callback) {this.events.set(name, callback);}
  setAttribute(name, value) {this[name] = value;}
}
const elements = new Map();
const document = {createElement: () => new Element(), querySelector(selector) {
  if (!elements.has(selector)) elements.set(selector, new Element()); return elements.get(selector);
}};
const graph = number => ({source_class: "PAST_EXAM", item_id: `item_${String(number).padStart(32, "0")}`,
  item_revision_id: `itemrev_${String(number).padStart(32, "0")}`, item_manifest_sha256: "sha256:" + "a".repeat(64),
  graph_snapshot_revision_id: "graphrev_" + "b".repeat(32), snapshot_sha256: "sha256:" + "c".repeat(64)});
const selections = [1, 2].map(number => itemDbSimilaritySelection("GRAPH_ITEM", graph(number)));
const calls = [];
let record;
let observationError = null;
const searches = {
  async recent() {calls.push("history"); return {values: record ? [record] : [], next_cursor: null};},
  async submit(values, topK, key) {
    calls.push({operation: "SUBMIT", values, topK, key});
    record = {search_id: "dbsearch_" + "1".repeat(32), created_at: new Date().toISOString(),
      status: "PENDING", device: "CUDA", children: [], selections: values, top_k: topK};
    return record;
  },
  async check(id) {
    calls.push({operation: "CHECK", id});
    if (observationError) throw Object.assign(new Error("synthetic observation failure"), {code: observationError});
    record = {...record, status: "READY", children: record.selections.map((pointer, ordinal) => ({ordinal,
      source_item_revision_id: pointer.item_revision_id, state: "COMPLETED", selection: {workflow_id: "workflow_" + String(ordinal + 1).repeat(32)}}))};
    return record;
  },
  async read(id) {calls.push({operation: "READ", id}); return record;},
  async result(id, ordinal) {
    calls.push({operation: "RESULT_GET", id, ordinal});
    return {search_id: id, ordinal, source_item_revision_id: record.selections[ordinal].item_revision_id,
      status: "READY", candidates: [{kind: "GRAPH_ITEM", entry: graph(9), label: "합성 결과 문항",
        unit_label: "합성 단원", cosine_millionths: 912345}]};
  },
};
const previews = [];
const opened = [];
const controller = createItemDbSimilarityList({document, searches, activate() {},
  async previewSelection(pointer, root, isCurrent) {previews.push(pointer); if (isCurrent()) root.replaceChildren(new Element());},
  openSelection(value) {opened.push(value);},
});
controller.install();
controller.setOwner("operator_" + "1".repeat(32));
controller.start(selections[0], "기준 문항 하나");
controller.start(selections[1], "기준 문항 둘");
controller.start(selections[0], "기준 문항 하나");
assert.equal(document.querySelector("#item-db-similarity-draft-count").textContent, "2문항");
document.querySelector("#item-db-similarity-top-k").value = "10";
await document.querySelector("#item-db-similarity-run").events.get("click")();
assert.equal(calls.filter(value => value.operation === "SUBMIT").length, 1);
assert.equal(calls.find(value => value.operation === "SUBMIT").values.length, 2);
assert.equal(calls.find(value => value.operation === "SUBMIT").topK, 10);
assert.equal(calls.filter(value => value.operation === "RESULT_GET").length, 1);
assert.equal(document.querySelector("#item-db-similarity-count").textContent, "1개");
await document.querySelector("#item-db-similarity-refresh").events.get("click")();
assert.equal(calls.filter(value => value.operation === "CHECK").length, 1, "completed confirmation must not call preparation");
assert.equal(calls.filter(value => value.operation === "RESULT_GET").length, 1, "visible result confirmation keeps its existing view");
document.querySelector("#item-db-similarity-source-select").value = "1";
await document.querySelector("#item-db-similarity-source-select").events.get("change")();
assert.equal(calls.filter(value => value.operation === "RESULT_GET").length, 2);
document.querySelector("#item-db-similarity-source-select").value = "0";
await document.querySelector("#item-db-similarity-source-select").events.get("change")();
assert.equal(calls.filter(value => value.operation === "RESULT_GET").length, 2, "same-page anchor switching reuses the validated projection");
const row = document.querySelector("#item-db-similarity-results").children[0];
row.events.get("click")();
assert.equal(opened[0].pointer.item_revision_id, graph(9).item_revision_id);
await document.querySelector("#item-db-similarity-history-refresh").events.get("click")();
await document.querySelector("#item-db-similarity-history").children[0].events.get("click")();
assert.equal(calls.filter(value => value.operation === "SUBMIT").length, 1);
assert.equal(calls.filter(value => value.operation === "CHECK").length, 1);
assert.equal(calls.filter(value => value.operation === "RESULT_GET").length, 3, "history reopen must reauthorize the existing result with GET only");
assert(previews.length >= 2);
await document.querySelector("#item-db-similarity-run").events.get("click")();
const submissions = calls.filter(value => value.operation === "SUBMIT");
assert.equal(submissions.length, 2, "only explicit new-search action may create a fresh intent");
assert.notEqual(submissions[0].key, submissions[1].key);
record = {...record, status: "UNAVAILABLE", device: null, children: [], error_code: "ITEM_DB_SIMILARITY_UNAVAILABLE"};
await document.querySelector("#item-db-similarity-history-refresh").events.get("click")();
assert.match(document.querySelector("#item-db-similarity-history").children[0].textContent, /연결 확인 필요/u);
await document.querySelector("#item-db-similarity-history").children[0].events.get("click")();
assert.match(document.querySelector("#item-db-similarity-message").textContent, /문항 연결/u);
assert.doesNotMatch(document.querySelector("#item-db-similarity-message").textContent, /풀이보고서/u);
record = {...record, error_code: "ITEM_DB_SIMILARITY_NOT_INDEXED"};
await document.querySelector("#item-db-similarity-history-refresh").events.get("click")();
await document.querySelector("#item-db-similarity-history").children[0].events.get("click")();
assert.match(document.querySelector("#item-db-similarity-message").textContent, /풀이보고서/u);
assert.equal(calls.filter(value => value.operation === "SUBMIT").length, 2, "history/status explanations never submit a new search");
controller.setOwner(null);
assert.equal(document.querySelector("#item-db-similarity-results").children.length, 1);
assert.equal(document.querySelector("#item-db-similarity-source-preview").children.length, 0);
assert.equal(document.querySelector("#item-db-similarity-history").children.length, 0);

// A temporary owner observation failure must not strand a successful background calculation.
controller.setOwner("operator_" + "1".repeat(32));
controller.start(selections[0], "기준 문항 하나");
observationError = "REFERENCE_QUERY_PREPARE_UNAVAILABLE";
const submitsBeforeRetry = calls.filter(value => value.operation === "SUBMIT").length;
await document.querySelector("#item-db-similarity-run").events.get("click")();
assert.match(document.querySelector("#item-db-similarity-message").textContent, /같은 요청/u);
async function tick(delay) {
  assert.equal(timers.size, 1, "only one observation timer may be pending");
  const [id, timer] = [...timers][0];
  assert.equal(timer.delay, delay);
  timers.delete(id);
  await timer.callback();
}
await tick(5000);
await tick(10000);
observationError = null;
await tick(20000);
assert.equal(record.status, "READY");
assert.equal(timers.size, 0);
assert.equal(calls.filter(value => value.operation === "SUBMIT").length, submitsBeforeRetry + 1);
assert(calls.filter(value => value.operation === "CHECK").every(value => value.id === record.search_id));
const readsAfterRetry = calls.filter(value => value.operation === "RESULT_GET").length;
await document.querySelector("#item-db-similarity-refresh").events.get("click")();
assert.equal(calls.filter(value => value.operation === "RESULT_GET").length, readsAfterRetry);

// Bound retries; explicit confirmation cancels a queued timer instead of creating a second loop.
observationError = "REFERENCE_QUERY_PREPARE_UNAVAILABLE";
await document.querySelector("#item-db-similarity-run").events.get("click")();
const pendingTimer = [...timers.keys()][0];
await document.querySelector("#item-db-similarity-refresh").events.get("click")();
assert(!timers.has(pendingTimer));
await tick(5000);
await tick(10000);
await tick(20000);
assert.equal(timers.size, 0);
assert.match(document.querySelector("#item-db-similarity-message").textContent, /확인하지 못했습니다/u);

// A queued or late callback from the previous owner must never observe another owner's search.
await document.querySelector("#item-db-similarity-refresh").events.get("click")();
const oldCallback = [...timers.values()][0].callback;
controller.setOwner(null);
assert.equal(timers.size, 0);
const checksBeforeLogout = calls.filter(value => value.operation === "CHECK").length;
await oldCallback();
assert.equal(calls.filter(value => value.operation === "CHECK").length, checksBeforeLogout);

controller.setOwner("operator_" + "2".repeat(32));
controller.start(selections[0], "기준 문항 하나");
for (const code of ["AUTH_REAUTHENTICATION_REQUIRED", "PERMISSION_DENIED", "ITEM_DB_SIMILARITY_RESULT_STALE", "UNEXPECTED_ERROR"]) {
  observationError = code;
  await document.querySelector("#item-db-similarity-run").events.get("click")();
  assert.equal(timers.size, 0, `${code} must not be automatically retried`);
}
controller.setOwner(null);
console.log("item_db_list_history_result_reads=PASS model_runs=0");
