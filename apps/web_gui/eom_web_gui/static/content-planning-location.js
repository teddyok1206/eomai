// URL selections are pointers, never authority or a persisted editing draft.
const POINTERS = Object.freeze({
  deliverable_id: /^deliverable_[0-9a-f]{32}$/,
  edition_id: /^edition_[0-9a-f]{32}$/,
  deliverable_revision_id: /^delivrev_[0-9a-f]{32}$/,
  section_id: /^section_[0-9a-f]{32}$/,
});
const REQUIRED = ["deliverable_id", "edition_id", "deliverable_revision_id"];

export function contentPlanningLocation(route) {
  const invalid = () => {throw new Error("콘텐츠 주소가 올바르지 않습니다. 콘텐츠와 판을 다시 선택해 주세요.");};
  if (route?.excel_location_invalid) invalid();
  if (!Object.keys(POINTERS).some(name => route?.[name] !== undefined)) return null;
  const result = {};
  for (const [name, pattern] of Object.entries(POINTERS)) {
    const value = route?.[name];
    if (value === undefined && !REQUIRED.includes(name)) continue;
    if (typeof value !== "string" || !pattern.test(value)) invalid();
    result[name] = value;
  }
  return Object.freeze(result);
}

export function readContentPlanningLocation(parameters) {
  const values = {};
  for (const name of Object.keys(POINTERS)) {
    const matches = parameters.getAll(name);
    if (matches.length > 1) return {excel_location_invalid: true};
    if (matches.length) values[name] = matches[0];
  }
  try {return contentPlanningLocation(values) || {};}
  catch {return {excel_location_invalid: true};}
}

export function writeContentPlanningLocation(parameters, route) {
  const selection = contentPlanningLocation(route);
  for (const [name, value] of Object.entries(selection || {})) parameters.set(name, value);
}
