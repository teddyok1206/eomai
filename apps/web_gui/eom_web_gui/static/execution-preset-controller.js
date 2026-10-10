import {
  approvedPresetModelOptions,
  candidateOptionValue,
  guidedPresetBases,
  presetCandidateLabel,
  presetValidationSucceeded,
  reviewedPresetDraft,
} from "./execution-preset-editor.js";

const EFFORT_LABELS = {minimal: "최소", low: "낮음", medium: "보통", high: "높음", xhigh: "매우 높음"};
const DRAFT_ID = /^execpresetrev_[0-9a-f]{32}$/;
const JOB_ID = /^job_[0-9a-f]{32}$/;
const POLL_LIMIT = 30;

// This controller owns only the administrator's model-policy editing session.
// The server owns capability admission, evaluation evidence and release decisions.
export function createExecutionPresetEditor({document, api, isAdmin, refresh, showMessage, addDetail}) {
  const $ = (selector) => document.querySelector(selector);
  let presets = [];
  let bases = [];
  let base = null;
  let options = null;
  let allowedPairs = new Map();
  let reviewed = null;
  let editorVersion = 0;
  let readVersion = 0;
  let action = null;
  let draftIntent = null;
  let validationIntent = null;
  let releaseIntent = null;
  let target = null;
  let validation = null;
  let pollVersion = 0;
  let pollTimer = null;
  let pollCount = 0;

  function message(text, tone = "neutral") {
    showMessage($("#preset-draft-message"), text, tone);
  }

  function stopPolling() {
    pollVersion += 1;
    clearTimeout(pollTimer);
    pollTimer = null;
  }

  function modelOptionsNeedRefresh() {
    return Boolean(base && options && base.draft.role_policies
      .some((policy) => !options.get(policy.role)?.length));
  }

  function fixedModelOptionsUnavailable() {
    return Boolean(base && options && base.draft.role_policies.some((policy) =>
      !["authoring", "review"].includes(policy.role) && policy.model_candidates.some((candidate) =>
        !allowedPairs.get(policy.role)?.has(candidateOptionValue(candidate.model, candidate.reasoning_effort)))));
  }

  function sync() {
    const busy = action !== null;
    $("#preset-base-select").disabled = busy || !bases.length;
    for (const field of document.querySelectorAll("#preset-guided-form input:not([readonly]), #preset-guided-form textarea")) {
      field.disabled = busy || !base || !options;
    }
    $("#preset-general-knowledge").disabled = true;
    const candidateFields = Array.from(document.querySelectorAll("[data-preset-model], [data-preset-effort]"));
    for (const field of candidateFields) {
      field.disabled = busy || !options || !field.options.length || field.options.length === 1 && !field.value;
    }
    $("#preset-review-open").disabled = busy || !base || !options || modelOptionsNeedRefresh() || fixedModelOptionsUnavailable()
      || candidateFields.some((field) => !field.value);
    $("#preset-draft-submit").disabled = busy || !reviewed || !$("#preset-review-confirm").checked;
    $("#preset-validation-submit").disabled = busy || !target || Boolean(target.validation_id);
    $("#preset-validation-refresh").disabled = busy || !target?.validation_id;
    $("#preset-release-confirm").disabled = busy || !presetValidationSucceeded(validation, target);
    $("#preset-release-submit").disabled = busy || !presetValidationSucceeded(validation, target)
      || !$("#preset-release-confirm").checked;
  }

  function clearDraftReview() {
    reviewed = null;
    $("#preset-review-confirm").checked = false;
    $("#preset-review-panel").hidden = true;
    $("#preset-review-summary").replaceChildren();
    sync();
  }

  function clearValidation() {
    stopPolling();
    target = null;
    validation = null;
    validationIntent = null;
    releaseIntent = null;
    $("#preset-release-panel").hidden = true;
    $("#preset-release-confirm").checked = false;
    $("#preset-release-summary").replaceChildren();
    $("#preset-validation-status").textContent = "확인 전";
    sync();
  }

  function invalidate() {
    editorVersion += 1;
    readVersion += 1;
    draftIntent = null;
    clearDraftReview();
    clearValidation();
  }

  function reset() {
    invalidate();
    base = null;
    options = null;
    allowedPairs = new Map();
    $("#preset-base-revision").value = "-";
    $("#preset-display-name").value = "";
    $("#preset-description").value = "";
    $("#preset-capacity-revision").value = "-";
    $("#preset-protocols").value = "-";
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "실행 설정을 선택하세요.";
    $("#preset-role-editors").replaceChildren(empty);
    sync();
  }

  function appendOption(select, value, label, selected = false) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    option.selected = selected;
    select.append(option);
  }

  function renderEfforts(modelSelect, effortSelect, candidates, selectedEffort) {
    effortSelect.replaceChildren();
    const efforts = candidates.filter((candidate) => candidate.model === modelSelect.value)
      .map((candidate) => candidate.reasoning_effort);
    if (!efforts.length) appendOption(effortSelect, "", candidates.length
      ? "모델을 먼저 선택하세요" : "목록 확인 필요");
    for (const effort of efforts) appendOption(effortSelect, effort, EFFORT_LABELS[effort], effort === selectedEffort);
    if (!efforts.includes(selectedEffort) && efforts.length) effortSelect.value = efforts[0];
  }

  function renderRoles() {
    const root = $("#preset-role-editors");
    root.replaceChildren();
    for (const [roleIndex, policy] of base.draft.role_policies.entries()) {
      if (!["authoring", "review"].includes(policy.role)) continue;
      const candidates = options.get(policy.role) || [];
      const models = [...new Set(candidates.map((candidate) => candidate.model))].sort();
      for (const [candidateIndex, candidate] of policy.model_candidates.entries()) {
        const card = document.createElement("section");
        card.className = "policy-role-card";
        const heading = document.createElement("h3");
        heading.textContent = presetCandidateLabel(policy.role, candidateIndex);
        const fields = document.createElement("div");
        fields.className = "policy-role-fields";
        const modelLabel = document.createElement("label");
        modelLabel.textContent = "모델";
        const modelSelect = document.createElement("select");
        modelSelect.dataset.presetModel = "true";
        modelSelect.dataset.roleIndex = String(roleIndex);
        modelSelect.dataset.candidateIndex = String(candidateIndex);
        const exactCurrent = candidates.some((item) => item.model === candidate.model
          && item.reasoning_effort === candidate.reasoning_effort);
        if (!exactCurrent) appendOption(modelSelect, "", candidates.length
          ? "현재 설정 사용 불가 · 모델을 선택하세요" : "모델 목록 확인 필요", true);
        for (const model of models) appendOption(modelSelect, model, model, exactCurrent && model === candidate.model);
        const effortLabel = document.createElement("label");
        effortLabel.textContent = "생각하는 깊이";
        const effortSelect = document.createElement("select");
        effortSelect.dataset.presetEffort = "true";
        effortSelect.dataset.roleIndex = String(roleIndex);
        effortSelect.dataset.candidateIndex = String(candidateIndex);
        renderEfforts(modelSelect, effortSelect, candidates, candidate.reasoning_effort);
        modelSelect.addEventListener("change", () => {
          renderEfforts(modelSelect, effortSelect, candidates, effortSelect.value);
          sync();
        });
        modelLabel.append(modelSelect);
        effortLabel.append(effortSelect);
        fields.append(modelLabel, effortLabel);
        card.append(heading, fields);
        root.append(card);
      }
    }
  }

  async function chooseBase() {
    if (action || !isAdmin()) return;
    const selected = $("#preset-base-select").value;
    reset();
    base = bases.find((item) => item.preset_revision_id === selected) || null;
    if (!base) return;
    const capturedBase = base;
    const sequence = ++readVersion;
    $("#preset-base-revision").value = base.preset_revision_id;
    $("#preset-display-name").value = base.draft.display_name;
    $("#preset-description").value = base.draft.description;
    $("#preset-general-knowledge").value = base.draft.general_knowledge_policy;
    $("#preset-capacity-revision").value = base.draft.capacity_policy_revision_id;
    $("#preset-protocols").value = base.draft.compatible_workflow_protocols.join(", ");
    message("사용할 수 있는 모델을 확인하고 있습니다.");
    sync();
    try {
      const response = await api(`/admin/execution-presets/${encodeURIComponent(base.preset_id)}/model-options`);
      if (sequence !== readVersion || base !== capturedBase) return;
      options = approvedPresetModelOptions(base, response);
      allowedPairs = new Map([...options].map(([role, candidates]) => [role,
        new Set(candidates.map((candidate) => candidateOptionValue(candidate.model, candidate.reasoning_effort)))]));
      renderRoles();
      message(modelOptionsNeedRefresh()
        ? "코덱스 계정에서 ‘상태 확인’을 한 뒤 실행 설정을 다시 선택하세요. 로그인 상태가 바뀌면 모델 목록도 다시 확인해 주세요."
        : fixedModelOptionsUnavailable()
          ? "변경하지 않는 역할의 기존 모델·추론 설정이 승인 목록에 없습니다. 코덱스 계정 상태와 관리 정책을 확인하세요."
        : "출제와 검토 모델을 각각 선택하세요. 진행 중인 작업은 바뀌지 않습니다.");
    } catch (failure) {
      if (sequence !== readVersion || base !== capturedBase) return;
      options = null;
      message(`모델 목록을 불러오지 못했습니다: ${failure.message}`, "error");
    }
    sync();
  }

  function collectEdits() {
    return {
      display_name: $("#preset-display-name").value,
      description: $("#preset-description").value,
      general_knowledge_policy: base.draft.general_knowledge_policy,
      role_policies: base.draft.role_policies.map((policy, roleIndex) => ({
        role: policy.role,
        timeout_seconds: policy.timeout_seconds,
        model_candidates: policy.model_candidates.map((candidate, candidateIndex) => {
          if (!["authoring", "review"].includes(policy.role)) return {...candidate};
          const suffix = `[data-role-index="${roleIndex}"][data-candidate-index="${candidateIndex}"]`;
          const selected = {
            model: $(`[data-preset-model]${suffix}`).value,
            reasoning_effort: $(`[data-preset-effort]${suffix}`).value,
          };
          const key = candidateOptionValue(selected.model, selected.reasoning_effort);
          if (!allowedPairs.get(policy.role)?.has(key)) {
            throw new Error("PRESET_MODEL_OPTION_NOT_ALLOWED");
          }
          return selected;
        }),
      })),
    };
  }

  function reviewEdits() {
    if (action || !base || !options || modelOptionsNeedRefresh() || fixedModelOptionsUnavailable() || !isAdmin()) return;
    try {
      clearValidation();
      reviewed = reviewedPresetDraft(base.draft, collectEdits());
      const summary = $("#preset-review-summary");
      summary.replaceChildren();
      addDetail(summary, "실행 설정", reviewed.display_name);
      for (const policy of reviewed.role_policies) {
        if (!["authoring", "review"].includes(policy.role)) continue;
        for (const [index, candidate] of policy.model_candidates.entries()) {
          addDetail(summary, presetCandidateLabel(policy.role, index), `${candidate.model} · ${EFFORT_LABELS[candidate.reasoning_effort]}`);
        }
      }
      $("#preset-review-confirm").checked = false;
      $("#preset-review-panel").hidden = false;
      message("변경 내용을 확인하세요.");
      sync();
    } catch (failure) {
      clearDraftReview();
      message(`설정을 확인하지 못했습니다: ${failure.message}`, "error");
    }
  }

  function inspectDraft(preset, revision) {
    if (action || !isAdmin() || revision.state !== "DRAFT") return;
    const releasedBase = guidedPresetBases([preset])[0];
    if (!releasedBase) return message("사용 중인 기준 버전을 찾을 수 없습니다.", "error");
    invalidate();
    target = {
      preset_id: preset.preset_id,
      preset_revision_id: revision.preset_revision_id,
      base_revision_id: releasedBase.preset_revision_id,
      revision_number: revision.revision_number,
      validation_id: null,
    };
    const summary = $("#preset-release-summary");
    addDetail(summary, "실행 설정", revision.display_name || preset.preset_key);
    for (const policy of revision.role_policies) {
      if (!["authoring", "review"].includes(policy.role)) continue;
      for (const [index, candidate] of policy.model_candidates.entries()) {
        addDetail(summary, presetCandidateLabel(policy.role, index), `${candidate.model} · ${EFFORT_LABELS[candidate.reasoning_effort]}`);
      }
    }
    $("#preset-release-panel").hidden = false;
    $("#advanced-preset-policy").open = true;
    message("설정을 확인한 뒤 새 작업에 적용할 수 있습니다. 문항 품질 검토와는 별개입니다.");
    sync();
  }

  async function createDraft() {
    if (action || !reviewed || !$("#preset-review-confirm").checked || !isAdmin()) return;
    const version = editorVersion;
    const capturedBase = base;
    if (!draftIntent) draftIntent = {
      body: {...reviewed, idempotency_key: `studio:preset:draft:${crypto.randomUUID()}`}, version,
    };
    const intent = draftIntent;
    action = "DRAFT";
    sync();
    try {
      const response = await api("/admin/execution-presets", {method: "POST", mutation: true, body: intent.body});
      if (version !== editorVersion || base !== capturedBase) return;
      if (!DRAFT_ID.test(response.resource_id)) throw new Error("APPLICATION_API_RESPONSE_INVALID");
      draftIntent = null;
      clearDraftReview();
      message("설정 초안을 저장했습니다.", "success");
      await refresh();
      if (version !== editorVersion || base !== capturedBase) return;
      const logical = presets.find((item) => item.preset_id === capturedBase.preset_id);
      const revision = logical?.revisions.find((item) => item.preset_revision_id === response.resource_id);
      if (revision) {
        action = null;
        inspectDraft(logical, revision);
      }
    } catch (failure) {
      if (version === editorVersion) message(`설정 초안 저장 실패: ${failure.message}`, "error");
    } finally {
      action = null;
      sync();
    }
  }

  async function pollValidation(sequence) {
    const captured = target;
    if (!captured?.validation_id || sequence !== pollVersion || !isAdmin()) return;
    try {
      const response = await api(`/admin/execution-preset-validations/${encodeURIComponent(captured.validation_id)}`);
      if (sequence !== pollVersion || target !== captured) return;
      if (response.validation_id !== captured.validation_id
        || response.preset_revision_id !== captured.preset_revision_id
        || response.base_revision_id !== captured.base_revision_id) {
        throw new Error("APPLICATION_API_RESPONSE_INVALID");
      }
      validation = response;
      if (presetValidationSucceeded(response, captured)) {
        $("#preset-validation-status").textContent = `확인 완료 · ${response.cases_passed}개 검사 통과`;
        message("설정 확인이 끝났습니다. 확인 후 새 작업에 적용하세요.", "success");
      } else if (response.status === "FAILED") {
        $("#preset-validation-status").textContent = "확인 실패";
        message(`설정을 확인하지 못했습니다. 기술 코드: ${response.error_code}`, "error");
      } else if (!["QUEUED", "RUNNING"].includes(response.status)) {
        throw new Error("APPLICATION_API_RESPONSE_INVALID");
      } else {
        $("#preset-validation-status").textContent = response.status === "QUEUED" ? "확인 대기" : "설정 확인 중";
        if (++pollCount < POLL_LIMIT) pollTimer = setTimeout(() => pollValidation(sequence), 2000);
        else message("설정 확인이 계속되고 있습니다. 잠시 후 ‘상태 확인’을 누르세요.");
      }
    } catch (failure) {
      if (sequence === pollVersion && target === captured) {
        validation = null;
        message(`확인 상태 조회 실패: ${failure.message}`, "error");
      }
    }
    sync();
  }

  async function evaluate() {
    if (action || !target || target.validation_id || !isAdmin()) return;
    const captured = target;
    const version = editorVersion;
    const observationVersion = pollVersion;
    if (!validationIntent) validationIntent = {
      body: {base_revision_id: target.base_revision_id, resource_version: target.revision_number,
        idempotency_key: `studio:preset:evaluate:${crypto.randomUUID()}`},
    };
    action = "EVALUATE";
    sync();
    try {
      const result = await api(`/admin/execution-preset-revisions/${encodeURIComponent(captured.preset_revision_id)}/evaluations`, {
        method: "POST", mutation: true, body: validationIntent.body,
      });
      if (target !== captured || version !== editorVersion) return;
      if (!JOB_ID.test(result.resource_id) || result.status !== "ACCEPTED") throw new Error("APPLICATION_API_RESPONSE_INVALID");
      captured.validation_id = result.resource_id;
      validationIntent = null;
      // Preserve an accepted command identity without restarting a suspended view's polling.
      if (observationVersion !== pollVersion || !isAdmin()) return;
      stopPolling();
      pollCount = 0;
      await pollValidation(pollVersion);
    } catch (failure) {
      if (target === captured) message(`설정 확인 시작 실패: ${failure.message}`, "error");
    } finally {
      action = null;
      sync();
    }
  }

  async function release() {
    if (action || !presetValidationSucceeded(validation, target)
      || !$("#preset-release-confirm").checked || !isAdmin()) return;
    const captured = target;
    const version = editorVersion;
    if (!releaseIntent) releaseIntent = {
      body: {resource_version: target.revision_number, idempotency_key: `studio:preset:release:${crypto.randomUUID()}`},
    };
    action = "RELEASE";
    stopPolling();
    sync();
    try {
      const result = await api(`/admin/execution-preset-revisions/${encodeURIComponent(captured.preset_revision_id)}/releases`, {
        method: "POST", mutation: true, body: releaseIntent.body,
      });
      if (target !== captured || version !== editorVersion) return;
      if (!DRAFT_ID.test(result.resource_id) || result.status !== "COMPLETED") throw new Error("APPLICATION_API_RESPONSE_INVALID");
      releaseIntent = null;
      clearValidation();
      await refresh();
      message("새 작업에 적용했습니다. 이미 진행 중인 작업은 기존 설정을 유지합니다.", "success");
    } catch (failure) {
      if (target === captured) message(`설정 적용 실패: ${failure.message}`, "error");
    } finally {
      action = null;
      sync();
    }
  }

  function setPresets(values) {
    presets = values;
    bases = guidedPresetBases(values);
    const selector = $("#preset-base-select");
    const selected = base?.preset_revision_id || "";
    selector.replaceChildren();
    appendOption(selector, "", bases.length ? "사용 중인 실행 설정 선택" : "편집 가능한 실행 설정 없음");
    for (const item of bases) appendOption(selector, item.preset_revision_id, item.draft.display_name, item.preset_revision_id === selected);
    if (base && !bases.some((item) => item.preset_revision_id === base.preset_revision_id)
      || target && !bases.some((item) => item.preset_id === target.preset_id && item.preset_revision_id === target.base_revision_id)) {
      reset();
      message("기준 설정이 변경되었습니다. 실행 설정을 다시 선택하세요.");
    }
    sync();
  }

  function install() {
    $("#preset-base-select").addEventListener("change", chooseBase);
    for (const event of ["input", "change"]) $("#preset-guided-form").addEventListener(event, (input) => {
      if (input.target.id === "preset-base-select") return;
      invalidate();
    });
    $("#preset-review-open").addEventListener("click", reviewEdits);
    $("#preset-review-confirm").addEventListener("change", sync);
    $("#preset-review-cancel").addEventListener("click", invalidate);
    $("#preset-draft-submit").addEventListener("click", createDraft);
    $("#preset-release-confirm").addEventListener("change", sync);
    $("#preset-release-cancel").addEventListener("click", invalidate);
    $("#preset-validation-submit").addEventListener("click", evaluate);
    $("#preset-validation-refresh").addEventListener("click", () => {
      if (action || !target?.validation_id) return;
      stopPolling();
      pollCount = 0;
      pollValidation(pollVersion);
    });
    $("#preset-release-submit").addEventListener("click", release);
    reset();
  }

  return {install, setPresets, inspectDraft, stopPolling, reset};
}
