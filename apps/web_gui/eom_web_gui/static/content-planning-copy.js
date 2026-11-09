// Copy preparation uses released READ_SECTION / SAVE_SECTIONS contracts.
// Catalog, not this editing helper, owns source authorization and provenance checks.
import {newPlanningId, slotSelection} from "./content-planning-draft.js";

const LIMIT = 100000;
const FORM_KEYS = ["form_id", "form_revision_id", "form_sha256", "assembly_id", "assembly_revision_id", "manifest_sha256", "placement_count"];

function invalid(message) {throw new Error(message);}

export async function loadPlanningCopy({query, composition, sectionIds, placementIds = null}) {
  const selected = new Set(sectionIds), known = new Set(composition.sections.map(row => row.section_id));
  if (!selected.size || selected.size !== sectionIds.length || [...selected].some(id => !known.has(id))) invalid("복사할 구간을 다시 골라 주세요.");
  const wanted = placementIds === null ? null : new Set(placementIds);
  if (wanted && (!wanted.size || wanted.size !== placementIds.length)) invalid("복사할 자리를 다시 골라 주세요.");
  const included = new Map(), entries = [], labels = new Map(), seen = new Set();
  // The saved tree is canonical pre-order. Parent membership expands groups in O(n).
  for (const section of composition.sections) {
    const enabled = selected.has(section.section_id) || included.get(section.parent_id) === true;
    included.set(section.section_id, enabled);
    if (!enabled || section.kind !== "FORM") continue;
    let after = 0, count = 0;
    do {
      const result = await query({query_kind: "READ_SECTION", edition_id: composition.edition_id,
        revision_id: composition.deliverable_revision_id, composition_sha256: composition.composition_sha256,
        section_id: section.section_id, after_position: after, limit: 200});
      if (result.edition_id !== composition.edition_id || result.revision_id !== composition.deliverable_revision_id
          || result.composition_sha256 !== composition.composition_sha256 || result.section_id !== section.section_id
          || FORM_KEYS.some(key => result.form?.[key] !== section.form[key])
          || result.total !== section.form.placement_count || !Array.isArray(result.rows)) invalid("복사 원본 저장본이 일치하지 않습니다. 원본을 다시 열어 주세요.");
      const titles = new Map((result.labels || []).map(row => [row.placement_id, row.title]));
      for (const row of result.rows) {
        if (row.position !== ++count || seen.has(row.placement_id)) invalid("복사 원본 문항 순서가 올바르지 않습니다.");
        seen.add(row.placement_id);
        if (wanted && !wanted.has(row.placement_id)) continue;
        if (entries.length >= LIMIT) invalid("한 번에 복사할 문항 수가 너무 많습니다.");
        entries.push({placement_id: row.placement_id, position: entries.length + 1,
          target: slotSelection(row.target), points_milli: row.points_milli, display_number: row.display_number,
          note: row.note, copied_from: {assembly_id: section.form.assembly_id,
            assembly_revision_id: section.form.assembly_revision_id, manifest_sha256: section.form.manifest_sha256,
            placement_id: row.placement_id}});
        if (titles.has(row.placement_id)) labels.set(row.placement_id, titles.get(row.placement_id));
      }
      const expectedNext = count < result.total ? count : null;
      if (result.next_position !== expectedNext || (expectedNext !== null && expectedNext <= after)) invalid("복사 원본의 다음 위치가 올바르지 않습니다.");
      after = result.next_position;
    } while (after !== null);
    if (count !== section.form.placement_count) invalid("복사 원본 문항이 일부 누락되었습니다.");
  }
  if (wanted && [...wanted].some(id => !seen.has(id))) invalid("선택한 자리가 원본 저장본에 없습니다.");
  if (!entries.length) invalid("복사할 문항이나 빈 자리가 없습니다.");
  return {sourceRevisionId: composition.deliverable_revision_id, sourceTitle: `${composition.content_title} · ${composition.edition_label}`, entries, labels};
}

export function pastePlanningCopy(currentRows, clipboard, {mode = "INSERT", index = currentRows.length, replacePlacementIds = []} = {}) {
  if (!Array.isArray(clipboard?.entries) || !clipboard.entries.length) invalid("복사할 원본을 먼저 골라 주세요.");
  const ids = new Set(currentRows.map(row => row.placement_id));
  if (ids.size !== currentRows.length) invalid("현재 편성에 중복된 자리가 있습니다.");
  let remaining = currentRows;
  if (mode === "REPLACE") {
    const replaced = new Set(replacePlacementIds);
    if (!replaced.size || replaced.size !== replacePlacementIds.length || [...replaced].some(id => !ids.has(id))) invalid("교체할 자리를 다시 골라 주세요.");
    index = currentRows.findIndex(row => replaced.has(row.placement_id));
    remaining = currentRows.filter(row => !replaced.has(row.placement_id));
  } else if (mode !== "INSERT" || replacePlacementIds.length) invalid("붙여넣기 방식을 확인해 주세요.");
  if (!Number.isInteger(index) || index < 0 || index > remaining.length) invalid("삽입할 위치를 확인해 주세요.");
  if (remaining.length + clipboard.entries.length > LIMIT) invalid("한 회차의 문항 수가 너무 많습니다.");
  const additions = clipboard.entries.map(row => ({...row, placement_id: newPlanningId("placement"), target: slotSelection(row.target), copied_from: {...row.copied_from}}));
  const rows = [...remaining.slice(0, index), ...additions, ...remaining.slice(index)].map((row, i) => ({...row, position: i + 1}));
  const labels = new Map(additions.map((row, i) => [row.placement_id, clipboard.labels?.get(clipboard.entries[i].placement_id)]).filter(([, value]) => value));
  return {rows, labels};
}
