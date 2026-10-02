const VIEW_NAMES = new Set([
  "dashboard", "workflow", "request", "item", "item-bank", "hwpx",
  "pdf-review", "quality-review", "control", "admin-settings", "learning",
  "knowledge", "explorer", "support", "account",
]);

const POINTERS = Object.freeze({
  workflow_id: /^workflow_[0-9a-f]{32}$/,
  item_id: /^item_[0-9a-f]{32}$/,
  item_revision_id: /^itemrev_[0-9a-f]{32}$/,
  hwpx_build_id: /^hwpxbuild_[0-9a-f]{32}$/,
  quality_plan_id: /^qualityplan_[0-9a-f]{32}$/,
});

export function studioRouteFromLocation(location) {
  const parameters = new URLSearchParams(location.search);
  const requestedView = parameters.get("view")
    || (POINTERS.hwpx_build_id.test(parameters.get("hwpx_build_id") || "") ? "hwpx" : "dashboard");
  const route = {view: VIEW_NAMES.has(requestedView) ? requestedView : "dashboard"};
  for (const [name, pattern] of Object.entries(POINTERS)) {
    const value = parameters.get(name);
    if (value && pattern.test(value)) route[name] = value;
  }
  return Object.freeze(route);
}

export function studioRouteUrl(route) {
  const parameters = new URLSearchParams();
  const view = VIEW_NAMES.has(route?.view) ? route.view : "dashboard";
  if (view !== "dashboard") parameters.set("view", view);
  for (const [name, pattern] of Object.entries(POINTERS)) {
    const value = route?.[name];
    if (typeof value === "string" && pattern.test(value)) parameters.set(name, value);
  }
  const query = parameters.toString();
  return `/studio/${query ? `?${query}` : ""}`;
}

export function updateStudioHistory(windowObject, route, {replace = false} = {}) {
  const url = studioRouteUrl(route);
  const method = replace ? "replaceState" : "pushState";
  windowObject.history[method](route, "", url);
}

export function supportContextRoute(route) {
  const view = VIEW_NAMES.has(route?.view) ? route.view : "dashboard";
  const segments = ["studio", view];
  for (const [name, pattern] of Object.entries(POINTERS)) {
    const value = route?.[name];
    if (typeof value === "string" && pattern.test(value)) segments.push(name, value);
  }
  return `/${segments.join("/")}`.slice(0, 512);
}

export function supportContextFromHistory(historyState) {
  const value = historyState?.support_origin_route;
  return typeof value === "string"
    && value.length <= 512
    && /^\/studio(?:\/[a-z0-9_-]+)*$/.test(value)
    ? value
    : "/studio/";
}
