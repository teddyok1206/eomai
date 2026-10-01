const ITEM_ID_PATTERN = /^item_[a-f0-9]{32}$/;
const ITEM_REVISION_PATTERN = /^itemrev_[a-f0-9]{32}$/;
const WORKFLOW_ID_PATTERN = /^workflow_[a-f0-9]{32}$/;

function requireIdentifier(value, pattern) {
  if (typeof value !== "string" || !pattern.test(value)) {
    throw new Error("HWPX_DELIVERY_TARGET_INVALID");
  }
  return value;
}

function target(source, itemRevisionId, itemId = null, workflowId = null) {
  return Object.freeze({
    source,
    itemRevisionId: requireIdentifier(itemRevisionId, ITEM_REVISION_PATTERN),
    itemId: itemId === null ? null : requireIdentifier(itemId, ITEM_ID_PATTERN),
    workflowId: workflowId === null ? null : requireIdentifier(workflowId, WORKFLOW_ID_PATTERN),
  });
}

export function hwpxTargetFromWorkflow(bundle) {
  const workflow = bundle?.workflow;
  const registration = workflow?.item_registration;
  if (!workflow || workflow.state !== "COMPLETED" || !registration) return null;
  return target(
    "WORKFLOW",
    registration.item_revision_id,
    registration.item_id,
    workflow.workflow_id,
  );
}

export function hwpxTargetFromItemPreview(preview) {
  if (!preview?.template_delivery_available) return null;
  return target(
    "ITEM_PREVIEW",
    preview.item_revision_id,
    preview.item_id,
    typeof preview.workflow_id === "string" ? preview.workflow_id : null,
  );
}

export function hwpxTargetFromBuild(build) {
  return target("HWPX_BUILD", build?.item_revision_id);
}

export function hwpxTargetFromAdminRevision(itemRevisionId) {
  return target("ADMIN_ID", itemRevisionId);
}
