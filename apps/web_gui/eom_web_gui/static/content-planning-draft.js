// Browser edit state only. Catalog validates identities, permissions and transitions.
export function newPlanningId(prefix) {
  return `${prefix}_${globalThis.crypto.randomUUID().replaceAll("-", "")}`;
}

export function slotSelection(target) {
  if (target.placement_kind === "EMPTY") return {placement_kind: "EMPTY"};
  const keys = target.placement_kind === "EXTERNAL_SOURCE_DOCUMENT"
    ? ["placement_kind", "source_id", "source_revision_id", "observation_sha256", "edition", "source_format"]
    : ["placement_kind", "item_id", "item_revision_id", "item_manifest_sha256", "graph_snapshot_revision_id", "graph_snapshot_sha256"];
  return Object.fromEntries(keys.map(key => [key, target[key]]));
}

export function targetIdentity(target) {
  return target.placement_kind === "EMPTY" ? null
    : target.placement_kind === "EXTERNAL_SOURCE_DOCUMENT" ? `source:${target.source_id}` : `item:${target.item_id}`;
}

export function createPlanningDraft() {
  let composition = null;
  const sections = new Map(), changed = new Set();
  function rows(id) {
    const value = sections.get(id);
    if (!value) throw new Error("회차를 먼저 불러와 주세요.");
    return value;
  }
  function renumber(id) {
    sections.set(id, rows(id).map((row, index) => ({...row, position: index + 1})));
    changed.add(id);
  }
  return {
    reset(value = null) {composition = value; sections.clear(); changed.clear();},
    composition: () => composition,
    dirty: () => changed.size > 0,
    loaded: id => sections.has(id),
    rows: id => rows(id).map(row => ({...row})),
    load(id, values) {
      if (changed.has(id)) throw new Error("저장하지 않은 배치를 다시 불러올 수 없습니다.");
      sections.set(id, values.map(row => ({...row, target: slotSelection(row.target)})));
    },
    add(id, target = {placement_kind: "EMPTY"}) {
      const list = rows(id);
      if (list.length >= 100000) throw new Error("한 회차의 문항 수가 너무 많습니다.");
      const row = {placement_id: newPlanningId("placement"), position: list.length + 1,
        target: slotSelection(target), points_milli: null, display_number: null, note: "", copied_from: null};
      list.push(row); changed.add(id); return row.placement_id;
    },
    update(id, placementId, values) {
      const list = rows(id), index = list.findIndex(row => row.placement_id === placementId);
      if (index < 0) throw new Error("편집할 자리가 없어졌습니다.");
      const allowed = Object.fromEntries(Object.entries(values).filter(([key]) => ["points_milli", "display_number", "note", "target"].includes(key)));
      if (allowed.target) allowed.target = slotSelection(allowed.target);
      list[index] = {...list[index], ...allowed}; changed.add(id);
    },
    remove(id, placementId) {
      const list = rows(id), index = list.findIndex(row => row.placement_id === placementId);
      if (index < 0) return false;
      list.splice(index, 1); renumber(id); return true;
    },
    move(from, placementId, to, index) {
      const source = rows(from), target = rows(to), current = source.findIndex(row => row.placement_id === placementId);
      if (current < 0 || !Number.isInteger(index) || index < 0 || index > target.length) return false;
      const [row] = source.splice(current, 1); target.splice(index, 0, row);
      renumber(from); if (from !== to) renumber(to); return true;
    },
    duplicateCounts(id) {
      const counts = new Map();
      for (const row of rows(id)) { const key = targetIdentity(row.target); if (key) counts.set(key, (counts.get(key) || 0) + 1); }
      return counts;
    },
    command() {
      if (!composition || !changed.size) return null;
      const byId = new Map(composition.sections.map(section => [section.section_id, section]));
      return {command_kind: "EDIT_EDITION", edition_id: composition.edition_id, edit: {
        change_kind: "SAVE_SECTIONS", expected_revision_id: composition.deliverable_revision_id,
        expected_sha256: composition.composition_sha256,
        changes: [...changed].map(id => ({section_id: id,
          before_assembly_revision_id: byId.get(id).form.assembly_revision_id,
          before_manifest_sha256: byId.get(id).form.manifest_sha256, placements: rows(id)})),
      }};
    },
  };
}

export function initialSections(count) {
  if (!Number.isInteger(count) || count < 0 || count > 1000) throw new Error("회차 수는 0~1,000 사이로 입력해 주세요.");
  return Array.from({length: count}, (_, i) => ({section_id: newPlanningId("section"), parent_id: null,
    kind: "FORM", ordinal: i + 1, label: `${i + 1}회차`, numbering: "RESET_PER_SECTION"}));
}
