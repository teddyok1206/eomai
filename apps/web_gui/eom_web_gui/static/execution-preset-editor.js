const EFFORTS = new Set(["minimal", "low", "medium", "high", "xhigh"]);
const ROLES = new Set(["authoring", "image", "review", "item_management", "support"]);
const GENERAL_KNOWLEDGE_POLICIES = new Set(["DENY", "ALLOW_WITH_PROVENANCE"]);
const MODEL_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const REVISION_PATTERN = /^execpresetrev_[0-9a-f]{32}$/;
const SHA_PATTERN = /^sha256:[0-9a-f]{64}$/;
const EDITABLE_ROLES = new Set(["authoring", "review"]);

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

function cloneRolePolicy(value, isV2 = false) {
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
  if (isV2 ? !["NONE", "EVIDENCE_CONTEXT"].includes(value.evidence_access)
    : value.evidence_access !== null && value.evidence_access !== undefined) {
    throw new Error("PRESET_EVIDENCE_POLICY_INVALID");
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
    ...(isV2 ? {evidence_access: value.evidence_access} : {}),
  };
}

function cloneRetrievalPolicy(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)
    || !/^accessrev_[0-9a-f]{32}$/.test(value.access_policy_revision_id)
    || !SHA_PATTERN.test(value.access_policy_sha256)) {
    throw new Error("PRESET_RETRIEVAL_POLICY_INVALID");
  }
  const collections = {};
  const limits = {allowed_corpus_keys: 16, allowed_query_kinds: 3, allowed_source_classes: 5};
  const queryKinds = new Set(["CURRICULUM_COMPONENTS", "APPROVED_ITEM_STRUCTURE", "ITEM_PREPARATION"]);
  const sourceClasses = new Set(["CURRICULUM", "TEXTBOOK", "APPROVED_ITEM", "PAST_EXAM", "INTERNAL_GUIDE"]);
  for (const [key, maximum] of Object.entries(limits)) {
    const values = value[key];
    if (!Array.isArray(values) || !values.length || values.length > maximum
      || values.some((item) => typeof item !== "string")
      || new Set(values).size !== values.length
      || JSON.stringify([...values].sort()) !== JSON.stringify(values)
      || values.some((item) => key === "allowed_corpus_keys"
        ? !/^[a-z][a-z0-9_-]{1,63}$/.test(item)
        : !(key === "allowed_query_kinds" ? queryKinds : sourceClasses).has(item))) {
      throw new Error("PRESET_RETRIEVAL_POLICY_INVALID");
    }
    collections[key] = [...values];
  }
  const bounds = {
    max_documents: [1, 32], max_item_revisions: [0, 64], max_graph_nodes: [1, 256],
    max_claims: [1, 128], max_context_tokens: [1000, 32000],
  };
  const budget = {};
  for (const [key, [minimum, maximum]] of Object.entries(bounds)) {
    const number = value.maximum_budget?.[key];
    if (!Number.isInteger(number) || number < minimum || number > maximum) {
      throw new Error("PRESET_RETRIEVAL_BUDGET_INVALID");
    }
    budget[key] = number;
  }
  return {
    access_policy_revision_id: value.access_policy_revision_id,
    access_policy_sha256: value.access_policy_sha256,
    ...collections,
    maximum_budget: budget,
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
    if (!revision || preset.state !== "ACTIVE" || revision.state && revision.state !== "RELEASED"
      || !["execution-preset-revision/1.0", "execution-preset-revision/2.0"].includes(revision.schema_version)) continue;
    try {
      const isV2 = revision.schema_version === "execution-preset-revision/2.0";
      if (!isV2 && revision.retrieval_policy) throw new Error("PRESET_RETRIEVAL_POLICY_INVALID");
      if (!Number.isInteger(revision.revision_number) || revision.revision_number < 1) {
        throw new Error("PRESET_REVISION_NUMBER_INVALID");
      }
      if (!GENERAL_KNOWLEDGE_POLICIES.has(revision.general_knowledge_policy)) {
        throw new Error("PRESET_GENERAL_KNOWLEDGE_POLICY_INVALID");
      }
      if (!Array.isArray(revision.compatible_workflow_protocols) || !revision.compatible_workflow_protocols.length) {
        throw new Error("PRESET_WORKFLOW_PROTOCOLS_INVALID");
      }
      if (!Array.isArray(revision.role_policies) || !revision.role_policies.length
        || new Set(revision.role_policies.map((policy) => policy.role)).size !== revision.role_policies.length) {
        throw new Error("PRESET_ROLE_POLICY_INVALID");
      }
      bases.push({
        preset_id: requiredString(preset.preset_id, "PRESET_ID_INVALID"),
        preset_key: requiredString(preset.preset_key, "PRESET_KEY_INVALID"),
        preset_revision_id: requiredString(revision.preset_revision_id, "PRESET_REVISION_ID_INVALID"),
        revision_number: revision.revision_number,
        draft: {
          target_revision_schema_version: revision.schema_version,
          preset_key: preset.preset_key,
          display_name: requiredString(revision.display_name, "PRESET_DISPLAY_NAME_INVALID"),
          description: requiredString(revision.description, "PRESET_DESCRIPTION_INVALID"),
          role_policies: revision.role_policies.map((policy) => cloneRolePolicy(policy, isV2)),
          capacity_policy_revision_id: requiredString(
            revision.capacity_policy_revision_id,
            "PRESET_CAPACITY_POLICY_INVALID",
          ),
          general_knowledge_policy: revision.general_knowledge_policy,
          compatible_workflow_protocols: [...revision.compatible_workflow_protocols],
          ...(isV2 ? {retrieval_policy: cloneRetrievalPolicy(revision.retrieval_policy)} : {}),
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
  const isV2 = baseDraft.target_revision_schema_version === "execution-preset-revision/2.0";
  if (edits.general_knowledge_policy !== baseDraft.general_knowledge_policy) {
    throw new Error("PRESET_FIXED_POLICY_CHANGED");
  }
  const draft = {
    target_revision_schema_version: baseDraft.target_revision_schema_version || "execution-preset-revision/1.0",
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
      if (roleEdit.timeout_seconds !== policy.timeout_seconds
        || !EDITABLE_ROLES.has(policy.role)
        && JSON.stringify(roleEdit.model_candidates) !== JSON.stringify(policy.model_candidates)) {
        throw new Error("PRESET_FIXED_POLICY_CHANGED");
      }
      return cloneRolePolicy({
        ...policy,
        model_candidates: roleEdit.model_candidates,
      }, isV2);
    }),
    capacity_policy_revision_id: baseDraft.capacity_policy_revision_id,
    general_knowledge_policy: baseDraft.general_knowledge_policy,
    compatible_workflow_protocols: [...baseDraft.compatible_workflow_protocols],
    ...(isV2 ? {retrieval_policy: cloneRetrievalPolicy(baseDraft.retrieval_policy)} : {}),
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

export function approvedPresetModelOptions(base, response) {
  if (!base || !REVISION_PATTERN.test(response?.preset_revision_id)
    || response.preset_revision_id !== base.preset_revision_id
    || response.catalog_is_entitlement !== false || !Array.isArray(response.roles)) {
    throw new Error("PRESET_MODEL_OPTIONS_STALE");
  }
  const byRole = new Map();
  const policies = new Map(base.draft.role_policies.map((policy) => [policy.role, policy]));
  for (const item of response.roles) {
    const policy = policies.get(item.role);
    if (!policy || byRole.has(item.role) || policy.worker_pool_key !== item.worker_pool_key
      || !Array.isArray(item.candidates) || item.candidates.length > 320) {
      throw new Error("PRESET_MODEL_OPTIONS_INVALID");
    }
    const candidates = item.candidates.map(cloneCandidate);
    if (new Set(candidates.map((candidate) => candidateOptionValue(candidate.model, candidate.reasoning_effort))).size
      !== candidates.length) throw new Error("PRESET_MODEL_OPTIONS_INVALID");
    byRole.set(item.role, candidates);
  }
  for (const policy of base.draft.role_policies) {
    if (EDITABLE_ROLES.has(policy.role) && !byRole.has(policy.role)) {
      throw new Error("PRESET_MODEL_OPTIONS_INVALID");
    }
  }
  return byRole;
}

export function presetCandidateLabel(role, index) {
  if (role === "review") return index === 0 ? "기본 검토" : index === 1 ? "강화 검토" : `검토 후보 ${index + 1}`;
  return role === "authoring" ? index === 0 ? "출제" : `출제 후보 ${index + 1}` : role;
}

export function presetValidationSucceeded(value, target) {
  return Boolean(value && target && value.validation_id === target.validation_id
    && value.preset_revision_id === target.preset_revision_id
    && value.base_revision_id === target.base_revision_id
    && SHA_PATTERN.test(value.preset_policy_sha256)
    && value.scope === "NON_LIVE" && value.quality_evaluated === false
    && value.status === "SUCCEEDED" && value.error_code == null
    && typeof value.evaluation_id === "string" && value.evaluation_id.length
    && value.completed_at && Number.isInteger(value.cases_total) && value.cases_total > 0
    && value.cases_passed === value.cases_total);
}
