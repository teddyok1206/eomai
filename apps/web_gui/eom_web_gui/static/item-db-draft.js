// A transient ordered selection. The server must reauthorize every pinned pointer before publication.
const CONNECTED_STATES = new Set(["MATCHED", "MATCHED_DETECTED_HWPX", "MATCHED_IDENTICAL_COPIES"]);
const OFFICE_FORMATS = new Map([
  ["application/vnd.hancom.hwp", "HWP"],
  ["application/vnd.hancom.hwpx", "HWPX"],
]);

export function selectedFinalSourcePlacement(detail) {
  if (!CONNECTED_STATES.has(detail.entry.match_status)) return null;
  const edition = [...detail.editions].reverse().find((row) =>
    row.available && row.edition >= 2 && row.filename === detail.entry.selected_filename
    && OFFICE_FORMATS.has(row.media_type));
  if (!edition) return null;
  return {
    placement_kind: "EXTERNAL_SOURCE_DOCUMENT",
    source_id: detail.entry.source_id,
    source_revision_id: detail.entry.source_revision_id,
    observation_sha256: detail.entry.observation_sha256,
    edition: edition.edition,
    source_format: OFFICE_FORMATS.get(edition.media_type),
  };
}

export function createItemDbDraft(limit = 200) {
  const ordered = [];
  const keys = new Set();

  function key(pointer) {
    return pointer.placement_kind === "EXTERNAL_SOURCE_DOCUMENT"
      ? `source:${pointer.source_id}` : `item:${pointer.item_revision_id}`;
  }

  return Object.freeze({
    entries: () => [...ordered],
    add(pointer, label) {
      const identity = key(pointer);
      if (keys.has(identity)) return "DUPLICATE";
      if (ordered.length >= limit) return "FULL";
      ordered.push({pointer: Object.freeze({...pointer}), label});
      keys.add(identity);
      return "ADDED";
    },
    move(index, next) {
      if (index < 0 || index >= ordered.length || next < 0 || next >= ordered.length) return false;
      [ordered[index], ordered[next]] = [ordered[next], ordered[index]];
      return true;
    },
    remove(index) {
      if (index < 0 || index >= ordered.length) return false;
      keys.delete(key(ordered[index].pointer));
      ordered.splice(index, 1);
      return true;
    },
    replace(selections) {
      if (!Array.isArray(selections) || selections.length > limit) return false;
      const identities = new Set(selections.map(({pointer}) => key(pointer)));
      if (identities.size !== selections.length) return false;
      ordered.splice(0, ordered.length, ...selections.map(({pointer, label}) => ({
        pointer: Object.freeze({...pointer}), label,
      })));
      keys.clear();
      for (const identity of identities) keys.add(identity);
      return true;
    },
    proposal() {
      return {
        schema_version: "curated-document-assembly-draft/1.0",
        placements: ordered.map(({pointer}, index) => ({...pointer, position: index + 1})),
      };
    },
  });
}
