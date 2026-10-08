const REQUIRED_PERMISSION_BY_ELEMENT_ID = Object.freeze({
  "structured-import-submit": "item:import_structured_content",
  "mock-exam-submit": "deliverable:create",
  "mock-exam-hwpx-submit": "hwpx:build_create",
  "approval-submit": "workflow:approve",
  "hwpx-build-submit": "hwpx:build_create",
  "hwpx-approval-submit": "workflow:approve",
  "quality-plan-create": "workflow:approve",
  "quality-session-start": "workflow:approve",
  "quality-session-finalize": "workflow:approve",
  "pdf-review-submit": "workflow:start",
  "support-submit": "customer_support:create",
  "chat-send": "general_chat:write",
  "chat-knowledge-panel": "item:read",
});

export function effectivePermissions(operator) {
  return new Set(
    operator && Array.isArray(operator.effective_permissions)
      ? operator.effective_permissions.map((value) => String(value).toLowerCase())
      : [],
  );
}

export function hasPermission(operator, permission) {
  return effectivePermissions(operator).has(String(permission).toLowerCase());
}

export function applyPermissionVisibility(root, operator) {
  const permissions = effectivePermissions(operator);
  root.querySelectorAll("[data-required-permission]").forEach((element) => {
    const allowed = permissions.has(String(element.dataset.requiredPermission).toLowerCase());
    element.hidden = !allowed;
    // Permission is not workflow readiness: granting access must not enable
    // controls that are waiting for a draft, selected revision or response.
    if (!allowed && "disabled" in element) element.disabled = true;
    element.setAttribute("aria-disabled", String(!allowed));
  });
}

export function installPermissionRequirements(root) {
  for (const [id, permission] of Object.entries(REQUIRED_PERMISSION_BY_ELEMENT_ID)) {
    const element = root.getElementById(id);
    if (element) element.dataset.requiredPermission = permission;
  }
}
