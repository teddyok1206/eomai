import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import {loadPlanningCopy, pastePlanningCopy} from "../../apps/web_gui/eom_web_gui/static/content-planning-copy.js";
globalThis.crypto ||= webcrypto;
const sha = "sha256:" + "a".repeat(64), id = (prefix, n) => prefix + "_" + n.toString(16).padStart(32, "0");
const form = n => ({form_id: id("form", n), form_revision_id: id("formrev", n), form_sha256: sha, assembly_id: id("assembly", n), assembly_revision_id: id("assemblyrev", n), manifest_sha256: sha, placement_count: 3});
const composition = {edition_id: id("edition", 1), deliverable_revision_id: id("delivrev", 1), composition_sha256: sha, content_title: "원판", edition_label: "2026", sections: [
  {section_id: id("section", 1), kind: "GROUP", parent_id: null, form: null},
  {section_id: id("section", 2), kind: "FORM", parent_id: id("section", 1), form: form(2)},
  {section_id: id("section", 3), kind: "FORM", parent_id: id("section", 1), form: form(3)},
]};
const rows = n => Array.from({length: 3}, (_, i) => ({placement_id: id("placement", n * 10 + i), position: i + 1,
  target: {placement_kind: "EMPTY"}, note: "메모 " + n + i, display_number: null, points_milli: 2000, copied_from: null}));
const calls = [];
async function query(request) {
  calls.push(request);
  assert.equal(request.revision_id, composition.deliverable_revision_id);
  const section = composition.sections.find(s => s.section_id === request.section_id), n = Number.parseInt(section.section_id.slice(-2), 16);
  const all = rows(n), page = all.slice(request.after_position, request.after_position + 2), next = request.after_position + page.length;
  return {edition_id: request.edition_id, revision_id: request.revision_id, composition_sha256: request.composition_sha256,
    section_id: section.section_id, form: section.form, rows: page,
    labels: page.map(row => ({placement_id: row.placement_id, title: row.note})), total: 3, next_position: next < 3 ? next : null};
}
const clipboard = await loadPlanningCopy({query, composition, sectionIds: [id("section", 3), id("section", 1)]});
assert.equal(calls.length, 4);
assert.deepEqual(clipboard.entries.map(row => row.copied_from.placement_id), [...rows(2), ...rows(3)].map(row => row.placement_id));
const subset = await loadPlanningCopy({query, composition, sectionIds: [id("section", 1)], placementIds: [id("placement", 32), id("placement", 21)]});
assert.deepEqual(subset.entries.map(row => row.placement_id), [id("placement", 21), id("placement", 32)]);
const before = rows(8), saved = structuredClone(before);
const inserted = pastePlanningCopy(before, subset, {index: 1});
assert.deepEqual(before, saved);
assert.equal(inserted.rows.length, 5);
assert.equal(inserted.rows[1].copied_from.placement_id, id("placement", 21));
assert.equal(inserted.labels.get(inserted.rows[1].placement_id), "메모 21");
assert.deepEqual(inserted.rows.map(row => row.position), [1, 2, 3, 4, 5]);
const twice = pastePlanningCopy(inserted.rows, subset);
assert.equal(new Set(twice.rows.map(row => row.placement_id)).size, 7);
const replaced = pastePlanningCopy(before, subset, {mode: "REPLACE", replacePlacementIds: [before[2].placement_id, before[0].placement_id]});
assert.equal(replaced.rows.length, 3);
assert.equal(replaced.rows[2].placement_id, before[1].placement_id);
assert.throws(() => pastePlanningCopy(before, subset, {mode: "REPLACE", replacePlacementIds: ["missing"]}), /교체할/);
assert.throws(() => pastePlanningCopy(before, subset, {index: 99}), /삽입할/);
assert.throws(() => pastePlanningCopy(Array(100000).fill(null).map((_, i) => ({placement_id: String(i)})), subset), /너무 많/);
assert.deepEqual(before, saved);
await assert.rejects(loadPlanningCopy({query, composition, sectionIds: [id("section", 1)], placementIds: ["missing"]}), /없습니다/);
await assert.rejects(loadPlanningCopy({query, composition, sectionIds: ["missing"]}), /구간/);
await assert.rejects(loadPlanningCopy({query: async r => ({...await query(r), revision_id: "stale"}), composition, sectionIds: [id("section", 2)]}), /일치/);
await assert.rejects(loadPlanningCopy({query: async r => ({...await query(r), next_position: 0}), composition, sectionIds: [id("section", 2)]}), /다음 위치/);
await assert.rejects(loadPlanningCopy({query: async () => {throw new Error("source read failed");}, composition, sectionIds: [id("section", 2)]}), /source read failed/);
assert.deepEqual(before, saved);
console.log("content_planning_copy=PASS");
