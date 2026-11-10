import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import {createCuratedOutputLibrary} from "../../apps/web_gui/eom_web_gui/static/curated-output-library.js";
globalThis.crypto = webcrypto;

class Element {
  constructor() {this.children = []; this.events = {}; this.dataset = {}; this.open = false; this.isConnected = true;}
  append(...values) {this.children.push(...values);}
  replaceChildren(...values) {this.children = values;}
  setAttribute() {}
  addEventListener(name, callback) {this.events[name] = callback;}
  querySelectorAll(selector) {
    return this.children.flatMap(child => [...(selector === "[data-library-action]" && child.dataset?.libraryAction ? [child] : []), ...(child.querySelectorAll?.(selector) || [])]);
  }
}
const id = (kind, char) => `${kind}_${char.repeat(32)}`, hash = `sha256:${"c".repeat(64)}`;
const entry = {assembly_id: id("assembly", "a"), assembly_revision_id: id("assemblyrev", "b"), manifest_sha256: hash,
  title: "저장된 개인 조립", placement_count: 1, created_at: "2026-11-10T00:00:00Z"};
const placement = {placement_kind: "EXTERNAL_SOURCE_DOCUMENT", source_id: id("extitem", "1"),
  source_revision_id: id("extitemrev", "2"), observation_sha256: hash, edition: 3, source_format: "HWPX", external_number: "10321"};
const nodes = new Map(["library", "list", "message", "refresh", "more"].map(key => [`#excel-output-${key}`, new Element()]));
const document = {createElement: () => new Element(), querySelector: key => nodes.get(key)};
const panel = nodes.get("#excel-output-library"), list = nodes.get("#excel-output-list"), status = nodes.get("#excel-output-message");
const calls = [], accepted = [], permissions = new Set(["item:read", "deliverable:read", "deliverable:update", "deliverable:create", "hwpx:build_create"]);
let entries = [entry], saved = {...entry, placements: [placement]}, rejectList = false, rejectRemove = false, confirmed = true, hold = null;
let removeReceipt = null, holdList = null, holdRemove = null;
const api = async (path, options) => {
  calls.push({path, options});
  if (path.includes("?limit=")) {
    if (rejectList) throw new Error("list unavailable");
    const values = [...entries];
    if (holdList) await new Promise(resolve => holdList.resolve = resolve);
    return {values, next_cursor: null};
  }
  if (path.includes("/remove")) {
    if (rejectRemove) {rejectRemove = false; throw new Error("reply lost");}
    const target = entries.find(value => path.includes(value.assembly_id)) || entry;
    entries = entries.filter(value => value.assembly_id !== target.assembly_id);
    if (holdRemove) await new Promise(resolve => holdRemove.resolve = resolve);
    return removeReceipt || {...target, removed_at: "2026-11-10T01:00:00Z"};
  }
  if (path.includes("/hwpx-builds")) return {...entry, build_id: id("hwpxbuild", "d"), state: "SUCCEEDED", validation_state: "PASS", download_available: true, output_sha256: hash};
  if (hold) await new Promise(resolve => hold.resolve = resolve);
  return saved;
};
const library = createCuratedOutputLibrary({document, api, can: value => permissions.has(value), confirm: () => confirmed,
  placeSelections: async (selections, current) => {if (!current()) return false; accepted.push(selections); return true;}});
const row = () => list.children[0];
const take = () => row().children[1];
const remove = () => row().children[2];
const settle = () => new Promise(resolve => setTimeout(resolve, 0));
library.install(); library.setOwner("owner-a"); library.open();
assert.equal(calls.length, 0, "closed history must not load or build");
panel.open = true; await panel.events.toggle(); await settle();
assert.equal(calls.length, 1);
assert.equal(row().children[0].children[0].textContent, entry.title);
await take().events.click();
assert.equal(accepted.length, 1);
assert.equal(accepted[0][0].pointer.external_number, undefined, "display number is not pointer authority");
assert.equal(accepted[0][0].pointer.source_revision_id, placement.source_revision_id);
assert.match(status.textContent, /배치 저장/);
assert.equal(calls.filter(call => call.options?.method === "POST").length, 0, "import must not auto-save or print");

for (const bad of [{assembly_revision_id: id("assemblyrev", "f")}, {manifest_sha256: `sha256:${"f".repeat(64)}`}, {placements: []}]) {
  saved = {...entry, placements: [placement], ...bad}; await take().events.click();
  assert.equal(accepted.length, 1); assert.match(status.textContent, /가져오기 실패/);
}
saved = {...entry, placements: [placement]};
rejectList = true; await nodes.get("#excel-output-refresh").events.click(); await settle();
assert.equal(row().children[0].children[0].textContent, entry.title, "failed refresh lost existing records");
rejectList = false;

const delivery = row().children[3];
await delivery.children[0].events.click();
assert.equal(delivery.children[2].hidden, false);
await delivery.children[0].events.click();
assert.equal(calls.filter(call => call.options?.method === "POST").length, 0, "completed output observation created a build");

confirmed = false; await remove().events.click();
assert.equal(calls.filter(call => call.path.includes("/remove")).length, 0);
confirmed = true; rejectRemove = true; await remove().events.click();
assert.match(status.textContent, /reply lost/);
await remove().events.click();
const removals = calls.filter(call => call.path.includes("/remove"));
assert.equal(removals.length, 2);
assert.deepEqual(removals[0].options, removals[1].options, "removal replay must preserve exact key/body");
assert.equal(list.children[0].textContent, "저장된 조립이나 간편 출력 기록이 없습니다.");
assert.deepEqual(saved.placements, [placement], "library removal changed canonical item content");

entries = [entry]; await nodes.get("#excel-output-refresh").events.click(); await settle();
hold = {}; const delayed = take().events.click(); await settle();
library.setOwner("owner-b"); hold.resolve(); await delayed; hold = null;
assert.equal(accepted.length, 1, "old owner late read reached Excel");
assert.equal(list.children.length, 0);
library.open(); await settle();
hold = {}; const closed = take().events.click(); await settle();
library.close(); hold.resolve(); await closed; hold = null;
assert.equal(accepted.length, 1, "closed view late read reached Excel");
library.open(); await settle();
// Serialize row mutations through the follow-up read: a late A snapshot cannot revive B.
const second = {...entry, assembly_id: id("assembly", "e"), assembly_revision_id: id("assemblyrev", "f"), title: "두 번째 기록"};
entries = [entry, second]; await nodes.get("#excel-output-refresh").events.click(); await settle();
const secondRemove = list.children[1].children[2], secondTake = list.children[1].children[1];
holdRemove = {}; const firstRemoval = remove().events.click(); await settle();
const duringRemoval = calls.length;
const conflictingRemoval = secondRemove.events.click(); await settle();
assert.equal(calls.length, duringRemoval, "a second row mutation/import raced the pending deletion");
await conflictingRemoval; await secondTake.events.click();
assert.equal(calls.length, duringRemoval);
assert.equal(secondRemove.disabled, true); assert.equal(secondTake.disabled, true);
holdList = {}; holdRemove.resolve(); await settle(); holdRemove = null;
const duringRefresh = calls.length;
await secondRemove.events.click(); await secondTake.events.click();
assert.equal(calls.length, duringRefresh, "row mutation started before the deletion refresh settled");
holdList.resolve(); await firstRemoval; holdList = null;
assert.deepEqual(list.children.map(value => value.children[0]?.children[0]?.textContent), [second.title]);
await remove().events.click();
assert.equal(entries.length, 0);
assert.equal(list.children[0].textContent, "저장된 조립이나 간편 출력 기록이 없습니다.");

// A confirmed deletion remains absent if the non-mutating follow-up list fails.
entries = [entry]; await nodes.get("#excel-output-refresh").events.click(); await settle();
rejectList = true; await remove().events.click(); rejectList = false;
assert.equal(list.children[0].textContent, "저장된 조립이나 간편 출력 기록이 없습니다.");

// An old owner's completion cannot unlock a newer owner's pending row mutation.
entries = [entry]; await nodes.get("#excel-output-refresh").events.click(); await settle();
holdRemove = {}; const oldWait = holdRemove, oldRemoval = remove().events.click(); await settle();
library.setOwner("owner-c"); entries = [second]; library.open(); await settle();
holdRemove = {}; const newWait = holdRemove, newRemoval = remove().events.click(); await settle();
oldWait.resolve(); await oldRemoval;
const pendingOtherOwner = calls.length;
await remove().events.click();
assert.equal(calls.length, pendingOtherOwner, "old owner completion unlocked the new removal");
newWait.resolve(); await newRemoval; holdRemove = null;
// Reopening the same view during its post-delete read must recover after the stale read is ignored.
entries = [entry, second]; await nodes.get("#excel-output-refresh").events.click(); await settle();
holdList = {}; const reopenedRemoval = remove().events.click(); await settle();
library.close(); library.open();
const invalidatedList = holdList; holdList = null; invalidatedList.resolve(); await reopenedRemoval;
assert.deepEqual(list.children.map(value => value.children[0]?.children[0]?.textContent), [second.title]);
entries = [entry]; await nodes.get("#excel-output-refresh").events.click(); await settle();
permissions.delete("deliverable:update"); await take().events.click();
assert.equal(accepted.length, 1, "import ignored current permission");
permissions.delete("item:read"); library.open();
assert.equal(panel.hidden, true);
console.log("curated_output_library=PASS lazy/pinned-import/no-auto-save/replay/download/owner-close-fence live_writes=0");
