const EFFORTS = new Set(["minimal", "low", "medium", "high", "xhigh"]);
const ROLES = new Set(["authoring", "image", "review", "item_management", "support"]);
const GENERAL_KNOWLEDGE_POLICIES = new Set(["DENY", "ALLOW_WITH_PROVENANCE"]);
const MODEL_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;

function requiredString(value, errorCode) {
  if (typeof value !== "string" || !value.length) throw new Error(errorCode);
  return value;
}

function cloneArtifactPointer(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("PRESET_ARTIFACT_POINTER_INVALID");
  }
  return {
    artifact_id: requiredString(value.artifact_id, "PRESET_ARTIFACT_ID_INVALID"),
    artifact_revision_id: requiredString(value.artifact_revision_id, "PRESET_ARTIFACT_REVISION_INVALID"),
    sha256: requiredString(value.sha256, "PRESET_ARTIFACT_SHA_INVALID"),
    schema_ref: requiredString(value.schema_ref, "PRESET_ARTIFACT_SCHEMA_INVALID"),
    media_type: requiredString(value.media_type, "PRESET_ARTIFACT_MEDIA_INVALID"),
    logical_name: requiredString(value.logical_name, "PRESET_ARTIFACT_MEMBER_INVALID"),
  };
}

function cloneBundlePointer(value, expectedPrefix) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("PRESET_BUNDLE_POINTER_INVALID");
  }
  const bundleId = requiredString(value.bundle_id, "PRESET_BUNDLE_ID_INVALID");
  const revisionId = requiredString(value.bundle_revision_id, "PRESET_BUNDLE_REVISION_INVALID");
  if (!bundleId.startsWith(`${expectedPrefix}bundle_`) || !revisionId.startsWith(`${expectedPrefix}rev_`)) {
    throw new Error("PRESET_BUNDLE_TYPE_INVALID");
  }
  return {
    bundle_id: bundleId,
    bundle_revision_id: revisionId,
    manifest_artifact: cloneArtifactPointer(value.manifest_artifact),
    manifest_sha256: requiredString(value.manifest_sha256, "PRESET_BUNDLE_SHA_INVALID"),
  };
}

function cloneCandidate(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("PRESET_MODEL_CANDIDATE_INVALID");
  }
  const model = requiredString(value.model, "PRESET_MODEL_INVALID");
  if (!MODEL_PATTERN.test(model) || !EFFORTS.has(value.reasoning_effort)) {
    throw new Error("PRESET_MODEL_CANDIDATE_INVALID");
  }
  return {model, reasoning_effort: value.reasoning_effort};
}

function cloneRolePolicy(value) {
  if (!value || typeof value !== "object" || Array.isArray(value) || !ROLES.has(value.role)) {
    throw new Error("PRESET_ROLE_POLICY_INVALID");
  }
  if (!Array.isArray(value.model_candidates) || value.model_candidates.length < 1 || value.model_candidates.length > 4) {
    throw new Error("PRESET_MODEL_CANDIDATES_INVALID");
  }
  if (!Number.isInteger(value.timeout_seconds) || value.timeout_seconds < 30 || value.timeout_seconds > 7200) {
    throw new Error("PRESET_TIMEOUT_INVALID");
  }
  if (value.sandbox !== "read-only" || value.network !== "disabled") {
    throw new Error("PRESET_SANDBOX_POLICY_INVALID");
  }
  if (value.evidence_access !== null && value.evidence_access !== undefined) {
    throw new Error("PRESET_V2_REQUIRES_REVIEWED_PIPELINE");
  }
  const candidates = value.model_candidates.map(cloneCandidate);
  if (new Set(candidates.map((item) => `${item.model}/${item.reasoning_effort}`)).size !== candidates.length) {
    throw new Error("PRESET_MODEL_CANDIDATES_DUPLICATED");
  }
  return {
    role: value.role,
    model_candidates: candidates,
    instruction_bundle: cloneBundlePointer(value.instruction_bundle, "instr"),
    reference_bundle: value.reference_bundle === null || value.reference_bundle === undefined
      ? null
      : cloneBundlePointer(value.reference_bundle, "ref"),
    worker_pool_key: requiredString(value.worker_pool_key, "PRESET_WORKER_POOL_INVALID"),
    timeout_seconds: value.timeout_seconds,
    sandbox: "read-only",
    network: "disabled",
  };
}

function currentRevision(preset) {
  if (!preset || typeof preset !== "object" || !Array.isArray(preset.revisions)) return null;
  return preset.revisions.find(
    (revision) => revision.preset_revision_id === preset.current_revision_id,
  ) || null;
}

export function guidedPresetBases(presets) {
  if (!Array.isArray(presets)) return [];
  const bases = [];
  for (const preset of presets) {
    const revision = currentRevision(preset);
    if (!revision || revision.schema_version !== "execution-preset-revision/1.0" || revision.retrieval_policy) continue;
    try {
      if (!Number.isInteger(revision.revision_number) || revision.revision_number < 1) {
        throw new Error("PRESET_REVISION_NUMBER_INVALID");
      }
      if (!GENERAL_KNOWLEDGE_POLICIES.has(revision.general_knowledge_policy)) {
        throw new Error("PRESET_GENERAL_KNOWLEDGE_POLICY_INVALID");
      }
      if (!Array.isArray(revision.compatible_workflow_protocols) || !revision.compatible_workflow_protocols.length) {
        throw new Error("PRESET_WORKFLOW_PROTOCOLS_INVALID");
      }
      bases.push({
        preset_id: requiredString(preset.preset_id, "PRESET_ID_INVALID"),
        preset_key: requiredString(preset.preset_key, "PRESET_KEY_INVALID"),
        preset_revision_id: requiredString(revision.preset_revision_id, "PRESET_REVISION_ID_INVALID"),
        revision_number: revision.revision_number,
        draft: {
          preset_key: preset.preset_key,
          display_name: requiredString(revision.display_name, "PRESET_DISPLAY_NAME_INVALID"),
          description: requiredString(revision.description, "PRESET_DESCRIPTION_INVALID"),
          role_policies: revision.role_policies.map(cloneRolePolicy),
          capacity_policy_revision_id: requiredString(
            revision.capacity_policy_revision_id,
            "PRESET_CAPACITY_POLICY_INVALID",
          ),
          general_knowledge_policy: revision.general_knowledge_policy,
          compatible_workflow_protocols: [...revision.compatible_workflow_protocols],
        },
      });
    } catch (_) {
      // An unsupported or malformed preset is not offered as a mutation base.
    }
  }
  return bases;
}

export function candidateOptionValue(model, reasoningEffort) {
  if (!MODEL_PATTERN.test(model) || !EFFORTS.has(reasoningEffort)) {
    throw new Error("PRESET_MODEL_CANDIDATE_INVALID");
  }
  return `${encodeURIComponent(model)}::${reasoningEffort}`;
}

export function candidateFromOptionValue(value) {
  if (typeof value !== "string") throw new Error("PRESET_MODEL_CANDIDATE_INVALID");
  const separator = value.lastIndexOf("::");
  if (separator < 1) throw new Error("PRESET_MODEL_CANDIDATE_INVALID");
  let model;
  try {
    model = decodeURIComponent(value.slice(0, separator));
  } catch (_) {
    throw new Error("PRESET_MODEL_CANDIDATE_INVALID");
  }
  return cloneCandidate({model, reasoning_effort: value.slice(separator + 2)});
}

export function reviewedPresetDraft(baseDraft, edits) {
  const draft = {
    preset_key: requiredString(baseDraft.preset_key, "PRESET_KEY_INVALID"),
    display_name: requiredString(edits.display_name?.trim(), "PRESET_DISPLAY_NAME_INVALID"),
    description: requiredString(edits.description?.trim(), "PRESET_DESCRIPTION_INVALID"),
    role_policies: baseDraft.role_policies.map((policy, roleIndex) => {
      const roleEdit = edits.role_policies?.[roleIndex];
      if (
        !roleEdit
        || roleEdit.role !== policy.role
        || !Array.isArray(roleEdit.model_candidates)
        || roleEdit.model_candidates.length !== policy.model_candidates.length
      ) {
        throw new Error("PRESET_ROLE_EDIT_INVALID");
      }
      return cloneRolePolicy({
        ...policy,
        model_candidates: roleEdit.model_candidates,
        timeout_seconds: roleEdit.timeout_seconds,
      });
    }),
    capacity_policy_revision_id: baseDraft.capacity_policy_revision_id,
    general_knowledge_policy: edits.general_knowledge_policy,
    compatible_workflow_protocols: [...baseDraft.compatible_workflow_protocols],
  };
  if (!GENERAL_KNOWLEDGE_POLICIES.has(draft.general_knowledge_policy)) {
    throw new Error("PRESET_GENERAL_KNOWLEDGE_POLICY_INVALID");
  }
  if (draft.display_name.length > 128 || draft.description.length > 1000) {
    throw new Error("PRESET_TEXT_LIMIT_EXCEEDED");
  }
  if (JSON.stringify(draft) === JSON.stringify(baseDraft)) {
    throw new Error("PRESET_DRAFT_HAS_NO_CHANGES");
  }
  return draft;
}
