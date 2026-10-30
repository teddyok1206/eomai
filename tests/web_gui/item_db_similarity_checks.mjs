import assert from "node:assert/strict";
import {createItemDbSimilarity, itemDbSimilaritySelection} from "../../apps/web_gui/eom_web_gui/static/item-db-similarity.js";

const graph = {source_class: "PAST_EXAM", item_id: "item_" + "1".repeat(32),
  item_revision_id: "itemrev_" + "2".repeat(32), item_manifest_sha256: "sha256:" + "3".repeat(64),
  graph_snapshot_revision_id: "graphrev_" + "4".repeat(32), snapshot_sha256: "sha256:" + "5".repeat(64)};
const external = {source_id: "extitem_" + "6".repeat(32), source_revision_id: "extitemrev_" + "7".repeat(32),
  observation_sha256: "sha256:" + "8".repeat(64), external_number: "10310"};

for (const [kind, entry, expected] of [["GRAPH_ITEM", graph, ["kind", "item_id", "item_revision_id", "item_manifest_sha256", "graph_snapshot_revision_id", "graph_snapshot_sha256"]],
  ["EXTERNAL_SOURCE", external, ["kind", "source_id", "source_revision_id", "observation_sha256"]]]) {
  const selection = itemDbSimilaritySelection(kind, entry);
  assert.deepEqual(Object.keys(selection.pointer), expected);
  assert.ok(Object.isFrozen(selection) && Object.isFrozen(selection.pointer) && Object.isFrozen(selection.entry));
  assert.notEqual(selection.entry, entry, "the small view value is separate from a mutable caller object");
  for (const key of expected.filter(key => key !== "kind")) {
    const presentationKey = key === "graph_snapshot_sha256" ? "snapshot_sha256" : key;
    assert.throws(() => itemDbSimilaritySelection(kind, {...entry, [presentationKey]: "untrusted/path/latest"}));
  }
}
const original = {...external};
const selection = itemDbSimilaritySelection("EXTERNAL_SOURCE", original);
original.source_revision_id = "extitemrev_" + "f".repeat(32);
assert.equal(selection.entry.source_revision_id, external.source_revision_id);
assert.equal(selection.pointer.source_revision_id, external.source_revision_id);
assert.throws(() => itemDbSimilaritySelection("UNTRUSTED", graph));
assert.throws(() => itemDbSimilaritySelection("GRAPH_ITEM", {...graph, source_class: "WORKER"}));
assert.throws(() => itemDbSimilaritySelection("EXTERNAL_SOURCE", graph));
assert.throws(() => itemDbSimilaritySelection("GRAPH_ITEM", external));
assert.equal(createItemDbSimilarity({document: {}, activate() {}, openSelection() {}}).available(), false,
  "a fixture-only implementation is not an active production search adapter");
console.log("item_db_similarity_selection=PASS live_writes=0");
