import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import {createItemDbSimilarityList} from "../../apps/web_gui/eom_web_gui/static/item-db-similarity-list.js";
import {itemDbSimilaritySelection} from "../../apps/web_gui/eom_web_gui/static/item-db-similarity.js";

globalThis.crypto ??= webcrypto;
const RealDate = Date;
const createdAt = RealDate.parse("2026-11-11T17:00:00Z");
let now = createdAt + 325000;
globalThis.Date = class extends RealDate {
  constructor(...args) {super(...(args.length ? args : [now]));}
  static now() {return now;}
};
const intervals = new Map();
const timeouts = new Map();
let nextTimer = 0;
globalThis.setInterval = (callback, delay) => {
  assert.equal(delay, 1000);
  intervals.set(++nextTimer, callback);
  return nextTimer;
};
globalThis.clearInterval = id => intervals.delete(id);
globalThis.setTimeout = (callback, delay) => {timeouts.set(++nextTimer, {callback, delay}); return nextTimer;};
globalThis.clearTimeout = id => timeouts.delete(id);

class Element {
  constructor() {this.children = []; this.events = new Map(); this.value = "5"; this.textContent = "";}
  append(...values) {this.children.push(...values);}
  replaceChildren(...values) {this.children = values;}
  addEventListener(name, callback) {
    const handlers = this.events.get(name) ?? [];
    handlers.push(callback);
    this.events.set(name, handlers);
  }
  setAttribute(name, value) {this[name] = value;}
  async dispatch(name) {
    await Promise.all((this.events.get(name) ?? []).map(callback => callback()));
  }
}
const elements = new Map();
const document = {createElement: () => new Element(), querySelector(selector) {
  if (!elements.has(selector)) elements.set(selector, new Element());
  return elements.get(selector);
}};
const $ = selector => document.querySelector(selector);
const graph = number => ({source_class: "PAST_EXAM", item_id: `item_${String(number).padStart(32, "0")}`,
  item_revision_id: `itemrev_${String(number).padStart(32, "0")}`, item_manifest_sha256: "sha256:" + "a".repeat(64),
  graph_snapshot_revision_id: "graphrev_" + "b".repeat(32), snapshot_sha256: "sha256:" + "c".repeat(64)});
const selections = [1, 2].map(number => itemDbSimilaritySelection("GRAPH_ITEM", graph(number)));
const calls = [];
const resultReads = [];
let record;
let finishCheck;
const searches = {
  async recent() {return {values: record ? [record] : [], next_cursor: null};},
  async submit(values, topK, key) {
    calls.push({operation: "SUBMIT", key});
    record = {search_id: "dbsearch_" + "1".repeat(32), created_at: new Date(createdAt).toISOString(),
      status: "PENDING", device: "CUDA", children: [], selections: values, top_k: topK};
    return record;
  },
  check(id) {
    calls.push({operation: "CHECK", id});
    return new Promise(resolve => {
      finishCheck = () => {
        record = {...record, status: "READY", children: record.selections.map((pointer, ordinal) => ({ordinal,
          source_item_revision_id: pointer.item_revision_id, state: "COMPLETED",
          selection: {workflow_id: "workflow_" + String(ordinal + 1).repeat(32)}}))};
        resolve(record);
      };
    });
  },
  async read(id) {calls.push({operation: "READ", id}); return record;},
  result(id, ordinal) {
    calls.push({operation: "RESULT_GET", id, ordinal});
    return new Promise(resolve => resultReads.push({
      finish: () => resolve({search_id: id, ordinal,
        source_item_revision_id: record.selections[ordinal].item_revision_id,
        status: "READY", candidates: [{kind: "GRAPH_ITEM", entry: graph(9), label: "합성 결과 문항",
          unit_label: "합성 단원", cosine_millionths: 912345}]}),
    }));
  },
};
const controller = createItemDbSimilarityList({document, searches, activate() {}, openSelection() {}});
controller.install();
controller.setOwner("operator_" + "1".repeat(32));
selections.forEach((selection, index) => controller.start(selection, `기준 문항 ${index + 1}`));

async function until(predicate, description) {
  for (let step = 0; step < 50 && !predicate(); step++) await Promise.resolve();
  assert(predicate(), description);
}

function assertOriginalClock(description) {
  assert.equal(intervals.size, 1, `${description}: one owner must update the shared elapsed DOM`);
  for (const callback of [...intervals.values()]) callback();
  const seconds = Math.floor((now - createdAt) / 1000);
  assert.equal($("#item-db-similarity-elapsed").textContent,
    `요청 후 ${Math.floor(seconds / 60)}분 ${seconds % 60}초`, description);
  assert.equal($("#item-db-similarity-progress").hidden, false);
}

function assertStopped(description) {
  assert.equal(intervals.size, 0, `${description}: no elapsed timers remain`);
  assert.equal(timeouts.size, 0, `${description}: no observation timers remain`);
  assert.equal($("#item-db-similarity-progress").hidden, true);
  assert.equal($("#item-db-similarity-tab-progress").hidden, true);
}

const first = $("#item-db-similarity-run").dispatch("click");
await until(() => finishCheck, "the original request is pending");
assertOriginalClock("PENDING at 325 seconds");
assert.equal($("#item-db-similarity-elapsed").textContent, "요청 후 5분 25초");
now += 1000;
assertOriginalClock("PENDING advances without a new search");
finishCheck();
await until(() => resultReads.length === 1, "READY awaits the original result GET");
assertOriginalClock("READY to delayed result must not start a second clock");
now += 42000;
assertOriginalClock("result GET keeps the server search creation time");
assert.match($("#item-db-similarity-progress-label").textContent, /결과.*불러/u);
resultReads[0].finish();
await first;
assertStopped("first result completed");
assert.equal(calls.filter(value => value.operation === "SUBMIT").length, 1);
assert.equal(calls.filter(value => value.operation === "CHECK").length, 1);
assert.equal(calls.filter(value => value.operation === "RESULT_GET").length, 1);

const completedCalls = calls.length;
await $("#item-db-similarity-refresh").dispatch("click");
assert.equal(calls.length, completedCalls, "completed confirmation neither calculates nor rereads");
assertStopped("completed confirmation");

await $("#item-db-similarity-history-refresh").dispatch("click");
now += 100000;
const history = $("#item-db-similarity-history").children[0].dispatch("click");
await until(() => resultReads.length === 2, "history reopens the existing result");
assertOriginalClock("history result GET has one clock and the original creation time");
now += 5000;
assertOriginalClock("history result GET advances monotonically");
resultReads[1].finish();
await history;
assertStopped("history reopened");

$("#item-db-similarity-source-select").value = "1";
const switched = $("#item-db-similarity-source-select").dispatch("change");
await until(() => resultReads.length === 3, "second anchor result is pending");
assertOriginalClock("anchor change retains the search clock");
now += 7000;
assertOriginalClock("anchor result GET advances from the same search time");
resultReads[2].finish();
await switched;
assertStopped("second anchor displayed");
assert.equal(calls.filter(value => value.operation === "SUBMIT").length, 1);
assert.equal(calls.filter(value => value.operation === "CHECK").length, 1);

await $("#item-db-similarity-history-refresh").dispatch("click");
const interrupted = $("#item-db-similarity-history").children[0].dispatch("click");
await until(() => resultReads.length === 4, "a late old-owner result is pending");
assertOriginalClock("before owner reset");
controller.setOwner(null);
assertStopped("owner reset cancels every timer");
const resetText = $("#item-db-similarity-message").textContent;
now += 9000;
resultReads[3].finish();
await interrupted;
assertStopped("late old-owner response cannot restart progress");
assert.equal($("#item-db-similarity-message").textContent, resetText);
assert.equal($("#item-db-similarity-results").children.length, 1);
assert.equal(calls.filter(value => value.operation === "SUBMIT").length, 1);
console.log("item_db_similarity_single_elapsed_owner=PASS live_requests=0 model_runs=0");
