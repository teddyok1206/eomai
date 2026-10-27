import assert from "node:assert/strict";
import {createItemDbDraft, selectedFinalSourcePlacement} from "../../apps/web_gui/eom_web_gui/static/item-db-draft.js";

const source = {
  placement_kind: "EXTERNAL_SOURCE_DOCUMENT",
  source_id: `extitem_${"1".repeat(32)}`,
  source_revision_id: `extitemrev_${"2".repeat(32)}`,
  observation_sha256: `sha256:${"3".repeat(64)}`,
  edition: 3,
  source_format: "HWPX",
};
const item = {
  placement_kind: "PAST_EXAM_ITEM_REVISION",
  item_id: `item_${"4".repeat(32)}`,
  item_revision_id: `itemrev_${"5".repeat(32)}`,
  item_manifest_sha256: `sha256:${"6".repeat(64)}`,
  graph_snapshot_revision_id: `graphrev_${"7".repeat(32)}`,
  graph_snapshot_sha256: `sha256:${"8".repeat(64)}`,
};
const draft = createItemDbDraft(2);
const detail = {
  entry: {
    source_id: source.source_id,
    source_revision_id: source.source_revision_id,
    observation_sha256: source.observation_sha256,
    match_status: "MATCHED_DETECTED_HWPX",
    selected_filename: "final.hwp",
  },
  editions: [
    {edition: 1, available: true, filename: "draft.hwp", media_type: "application/vnd.hancom.hwp"},
    {edition: 2, available: true, filename: "earlier.hwp", media_type: "application/vnd.hancom.hwp"},
    {edition: 3, available: true, filename: "final.hwp", media_type: "application/vnd.hancom.hwpx"},
  ],
};
assert.deepEqual(selectedFinalSourcePlacement(detail), source);
assert.equal(selectedFinalSourcePlacement({...detail, entry: {...detail.entry, match_status: "NAME_MISMATCH"}}), null);
assert.equal(selectedFinalSourcePlacement({...detail, entry: {...detail.entry, selected_filename: "absent.hwp"}}), null);
assert.equal(selectedFinalSourcePlacement({...detail, editions: detail.editions.slice(0, 1)}), null);
assert.equal(draft.add(source, "원본"), "ADDED");
assert.equal(draft.add({...source, edition: 2}, "같은 원본"), "DUPLICATE");
assert.equal(draft.add(item, "기출"), "ADDED");
assert.equal(draft.add({...item, item_revision_id: `itemrev_${"9".repeat(32)}`}, "세 번째"), "FULL");
assert.equal(draft.move(0, 1), true);
assert.deepEqual(draft.proposal(), {
  schema_version: "curated-document-assembly-draft/1.0",
  placements: [{...item, position: 1}, {...source, position: 2}],
});
assert.equal(draft.remove(0), true);
assert.equal(draft.add(item, "다시 기출"), "ADDED");
assert.deepEqual(draft.proposal().placements.map((row) => row.position), [1, 2]);
assert.equal(draft.move(-1, 0), false);
assert.equal(draft.remove(5), false);
console.log("item_db_draft=PASS");
