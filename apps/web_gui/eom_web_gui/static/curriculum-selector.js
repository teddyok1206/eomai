const LEVELS = Object.freeze(["LARGE", "MIDDLE", "SMALL"]);

export function indexCurriculumUnits(units) {
  const byKey = new Map();
  for (const unit of units) {
    if (!unit || typeof unit.key !== "string" || !LEVELS.includes(unit.level)) {
      throw new Error("CURRICULUM_OUTLINE_INVALID");
    }
    if (byKey.has(unit.key)) throw new Error("CURRICULUM_OUTLINE_DUPLICATE_KEY");
    byKey.set(unit.key, unit);
  }
  return byKey;
}

export function curriculumAncestors(units, selectedKey) {
  const selected = {large: "", middle: "", small: ""};
  if (!selectedKey) return selected;
  const byKey = indexCurriculumUnits(units);
  let current = byKey.get(selectedKey);
  if (!current) throw new Error("CURRICULUM_OUTLINE_UNIT_MISSING");
  const visited = new Set();
  while (current) {
    if (visited.has(current.key)) throw new Error("CURRICULUM_OUTLINE_CYCLE");
    visited.add(current.key);
    selected[current.level.toLowerCase()] = current.key;
    if (current.level === "LARGE") break;
    if (!current.parent_key) break;
    current = byKey.get(current.parent_key);
    if (!current) throw new Error("CURRICULUM_OUTLINE_PARENT_MISSING");
  }
  return selected;
}

export function isCurriculumDescendant(units, childKey, ancestorKey) {
  if (!childKey || !ancestorKey) return false;
  const ancestors = curriculumAncestors(units, childKey);
  return Object.values(ancestors).includes(ancestorKey);
}

export function curriculumOptionsForSelection(units, selection) {
  const byKey = indexCurriculumUnits(units);
  const selectedLarge = selection.large || "";
  const selectedMiddle = selection.middle || "";
  if (selectedLarge && byKey.get(selectedLarge)?.level !== "LARGE") {
    throw new Error("CURRICULUM_LARGE_SELECTION_INVALID");
  }
  if (selectedMiddle && byKey.get(selectedMiddle)?.level !== "MIDDLE") {
    throw new Error("CURRICULUM_MIDDLE_SELECTION_INVALID");
  }

  function belongsTo(unit, ancestorKey) {
    let current = unit;
    const visited = new Set();
    while (current?.parent_key) {
      if (visited.has(current.key)) throw new Error("CURRICULUM_OUTLINE_CYCLE");
      visited.add(current.key);
      if (current.parent_key === ancestorKey) return true;
      if (current.level === "LARGE") return false;
      current = byKey.get(current.parent_key);
      if (!current) throw new Error("CURRICULUM_OUTLINE_PARENT_MISSING");
    }
    return false;
  }

  const large = units.filter((unit) => unit.level === "LARGE");
  const middle = units.filter(
    (unit) => unit.level === "MIDDLE" && (!selectedLarge || unit.parent_key === selectedLarge),
  );
  const small = units.filter(
    (unit) =>
      unit.level === "SMALL" &&
      (!selectedMiddle
        ? !selectedLarge || belongsTo(unit, selectedLarge)
        : unit.parent_key === selectedMiddle),
  );
  return {large, middle, small};
}

export function reconcileCurriculumSelection(units, selection, changedLevel) {
  const next = {
    large: selection.large || "",
    middle: selection.middle || "",
    small: selection.small || "",
  };
  if (changedLevel === "SMALL" && next.small) {
    return curriculumAncestors(units, next.small);
  }
  if (changedLevel === "MIDDLE") {
    if (!next.middle) {
      next.small = "";
      return next;
    }
    const ancestors = curriculumAncestors(units, next.middle);
    next.large = ancestors.large;
    if (next.small && !isCurriculumDescendant(units, next.small, next.middle)) next.small = "";
    return next;
  }
  if (changedLevel === "LARGE") {
    if (next.middle && !isCurriculumDescendant(units, next.middle, next.large)) {
      next.middle = "";
      next.small = "";
    } else if (next.small && !isCurriculumDescendant(units, next.small, next.large)) {
      next.small = "";
    }
  }
  return next;
}

export function deepestCurriculumUnitKey(selection) {
  return selection.small || selection.middle || selection.large || "";
}
