import assert from "node:assert/strict";
import {
  contentPlanningLocation,
  readContentPlanningLocation,
  writeContentPlanningLocation,
} from "../../apps/web_gui/eom_web_gui/static/content-planning-location.js";

const id = prefix => `${prefix}_${"a".repeat(32)}`;
const selection = {deliverable_id: id("deliverable"), edition_id: id("edition"),
  deliverable_revision_id: id("delivrev"), section_id: id("section")};
assert.equal(contentPlanningLocation({view: "excel"}), null);
assert.deepEqual(contentPlanningLocation(selection), selection);
assert.equal(Object.isFrozen(contentPlanningLocation(selection)), true);
assert.deepEqual(contentPlanningLocation({...selection, token: "not-accepted", content: "not-accepted"}), selection);
for (const key of Object.keys(selection)) {
  for (const bad of [null, 42, "", "../private", "https://example.test/", selection[key].toUpperCase(), `${selection[key]}extra`]) {
    assert.throws(() => contentPlanningLocation({...selection, [key]: bad}), /주소/);
  }
}
for (const key of ["deliverable_id", "edition_id", "deliverable_revision_id"]) {
  const incomplete = {...selection}; delete incomplete[key];
  assert.throws(() => contentPlanningLocation(incomplete), /주소/);
}
const noSection = {...selection}; delete noSection.section_id;
assert.deepEqual(contentPlanningLocation(noSection), noSection, "an edition without sections remains addressable");
assert.throws(() => contentPlanningLocation({excel_location_invalid: true}), /주소/);
const parameters = new URLSearchParams({view: "excel"});
writeContentPlanningLocation(parameters, {...selection, auth: "ignored", draft: "ignored"});
assert.deepEqual(readContentPlanningLocation(parameters), selection);
assert.equal(parameters.has("auth"), false);
assert.equal(parameters.has("draft"), false);
for (const key of Object.keys(selection)) {
  const duplicate = new URLSearchParams(parameters); duplicate.append(key, selection[key]);
  assert.deepEqual(readContentPlanningLocation(duplicate), {excel_location_invalid: true});
}
assert.deepEqual(readContentPlanningLocation(new URLSearchParams("edition_id=invalid")), {excel_location_invalid: true});
assert.deepEqual(readContentPlanningLocation(new URLSearchParams("redirect=https://example.test/")), {});
assert.throws(() => writeContentPlanningLocation(new URLSearchParams(), {edition_id: id("edition")}), /주소/);
console.log("content_planning_location=PASS");
