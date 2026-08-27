import {
  curriculumAncestors,
  curriculumOptionsForSelection,
  deepestCurriculumUnitKey,
  reconcileCurriculumSelection,
} from "./curriculum-selector.js";

const API = "/studio/api/v1";
const HWPX_BUILD_PATTERN = /^hwpxbuild_[a-f0-9]{32}$/;
const ANALYSIS_BATCH_PATTERN = /^analysisbatch_[a-f0-9]{32}$/;
const state = {
  csrf: "",
  operator: null,
  draft: null,
  workflow: null,
  health: null,
  stream: null,
  pollTimer: null,
  explorerCursor: null,
  explorerRow: null,
  hwpxCapability: null,
  hwpxBuildId: null,
  hwpxPollTimer: null,
  hwpxRecentBuilds: [],
  recentItems: [],
  acceptedIntakes: [],
  structuredSource: null,
  codexAccounts: [],
  executionPresets: [],
  knowledgeAnalysisBatches: [],
  knowledgeQualityReport: null,
  analysisBatchPollTimer: null,
  presentationVocabulary: null,
  curriculumOutline: null,
  curriculumSelection: {large: "", middle: "", small: ""},
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));
const UI_MODE_BY_VIEW = Object.freeze({
  workflow: "engine",
  request: "human",
  item: "human",
  approval: "human",
  hwpx: "human",
  control: "engine",
  knowledge: "engine",
  explorer: "engine",
  dashboard: "human",
});

function syncUiMode(name) {
  const mode = UI_MODE_BY_VIEW[name] || "human";
  const label = mode === "engine" ? "운영·근거 화면" : "사용자 작업면";
  document.documentElement.dataset.uiMode = mode;
  $("#surface-mode-label").lastChild.textContent = ` ${label}`;
  $("#sidebar-mode-label").textContent = label;
}

async function api(path, options = {}) {
  const headers = {Accept: "application/json", ...(options.headers || {})};
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (options.mutation) headers["X-CSRF-Token"] = state.csrf;
  const response = await fetch(`${API}${path}`, {
    method: options.method || "GET",
    credentials: "same-origin",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  if (response.status === 401) {
    window.location.replace("/studio/login");
    throw new StudioApiError("AUTH_REAUTHENTICATION_REQUIRED");
  }
  if (!response.ok) {
    let code = `HTTP_${response.status}`;
    try {
      const problem = await response.json();
      if (typeof problem.error_code === "string") code = problem.error_code;
    } catch (_) {
      // The stable HTTP code remains the sanitized fallback.
    }
    throw new StudioApiError(code);
  }
  if (response.status === 204) return null;
  return response.json();
}

class StudioApiError extends Error {
  constructor(code) {
    const presentation = errorPresentation(code);
    const action = presentation.action ? ` ${presentation.action}` : "";
    super(`${presentation.label}${action} (기술 코드: ${code})`);
    this.name = "StudioApiError";
    this.code = code;
  }
}

async function loadPresentationVocabulary() {
  try {
    const response = await fetch("/studio/assets/presentation-vocabulary.ko-KR.json", {
      credentials: "same-origin",
      headers: {Accept: "application/json"},
    });
    if (!response.ok) throw new Error("PRESENTATION_VOCABULARY_UNAVAILABLE");
    const vocabulary = await response.json();
    if (
      vocabulary?.schema_version !== "studio-presentation-vocabulary/1.0"
      || vocabulary?.locale !== "ko-KR"
      || typeof vocabulary?.domains?.generic?.states !== "object"
      || typeof vocabulary?.errors !== "object"
    ) {
      throw new Error("PRESENTATION_VOCABULARY_INVALID");
    }
    state.presentationVocabulary = vocabulary;
    document.documentElement.dataset.presentationVocabulary = "ready";
  } catch (_) {
    state.presentationVocabulary = null;
    document.documentElement.dataset.presentationVocabulary = "unavailable";
  }
}

function setStatus(element, tone, icon, label) {
  element.className = `status-badge tone-${tone}`;
  element.replaceChildren();
  const mark = document.createElement("span");
  mark.className = "status-icon";
  mark.setAttribute("aria-hidden", "true");
  mark.textContent = icon;
  element.append(mark, document.createTextNode(` ${label}`));
}

function statusStyle(value) {
  const normalized = String(value || "UNKNOWN").toUpperCase();
  if (["COMPLETED", "SUCCEEDED", "APPROVED", "READY", "ACTIVE", "AVAILABLE"].includes(normalized)) return ["success", "✓"];
  if (["FAILED", "BLOCKED", "UNAVAILABLE", "DEGRADED"].includes(normalized)) return ["danger", "!"];
  if (["PENDING", "AWAITING_HUMAN_APPROVAL", "AWAITING_APPROVAL", "PREPARED_NOT_DEPLOYED"].includes(normalized)) return ["warning", "◆"];
  if (["RUNNING", "CLAIMED", "QUEUED", "ACCEPTED"].includes(normalized)) return ["primary", "●"];
  return ["neutral", "■"];
}

function statePresentation(domain, value) {
  const raw = String(value || "UNKNOWN").toUpperCase();
  const domains = state.presentationVocabulary?.domains;
  const presentation = domains?.[domain]?.states?.[raw] || domains?.generic?.states?.[raw];
  const [fallbackTone, fallbackIcon] = statusStyle(raw);
  if (!presentation || typeof presentation.label !== "string") {
    return {
      raw,
      label: "알 수 없는 상태",
      tone: fallbackTone,
      icon: fallbackIcon,
      known: false,
    };
  }
  return {
    raw,
    label: presentation.label,
    tone: presentation.tone || fallbackTone,
    icon: presentation.icon || fallbackIcon,
    known: true,
  };
}

function setStateStatus(element, domain, value) {
  const presentation = statePresentation(domain, value);
  setStatus(element, presentation.tone, presentation.icon, presentation.label);
  element.dataset.rawState = presentation.raw;
  element.dataset.presentationKnown = String(presentation.known);
  element.title = `기술 상태: ${presentation.raw}`;
}

function stageLabel(value) {
  const key = String(value || "").replace("item_management", "registration");
  return state.presentationVocabulary?.stages?.[key]?.label || key || "-";
}

function errorPresentation(value) {
  const code = String(value || "APPLICATION_API_REQUEST_FAILED").toUpperCase();
  const presentation = state.presentationVocabulary?.errors?.[code];
  if (presentation && typeof presentation.label === "string") return presentation;
  return {
    label: "요청을 처리하지 못했습니다.",
    action: "기술 오류 코드를 확인한 뒤 관리자에게 알려주세요.",
    audience: "USER",
  };
}

function errorMessage(value) {
  const code = String(value || "APPLICATION_API_REQUEST_FAILED").toUpperCase();
  const presentation = errorPresentation(code);
  return `${presentation.label}${presentation.action ? ` ${presentation.action}` : ""} (기술 코드: ${code})`;
}

function showMessage(element, value, tone = "") {
  element.className = `form-message${tone ? ` ${tone}` : ""}`;
  element.textContent = value;
}

function toast(value) {
  const element = $("#toast");
  element.textContent = value;
  element.hidden = false;
  window.setTimeout(() => { element.hidden = true; }, 3200);
}

function showView(name) {
  $$(".view").forEach((element) => element.classList.toggle("active", element.dataset.view === name));
  $$(".nav-item").forEach((element) => element.classList.toggle("active", element.dataset.viewTarget === name));
  syncUiMode(name);
  $(".sidebar").classList.remove("open");
  if (name === "hwpx") loadHwpx();
  if (name !== "control") window.clearTimeout(state.analysisBatchPollTimer);
  if (name === "control" && hasAdminRole()) loadControlPlane();
  if (name === "dashboard" && state.health) renderDashboard(state.health);
  const behavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
  window.scrollTo({top: 0, behavior});
}

function installNavigation() {
  $$('[data-view-target]').forEach((button) => button.addEventListener("click", () => showView(button.dataset.viewTarget)));
  $("#mobile-menu").addEventListener("click", () => $(".sidebar").classList.toggle("open"));
  $("#global-load").addEventListener("click", loadGlobalId);
  $("#global-id").addEventListener("keydown", (event) => { if (event.key === "Enter") loadGlobalId(); });
}

function loadGlobalId() {
  const value = $("#global-id").value.trim();
  if (value.startsWith("workflow_")) {
    $("#workflow-id").value = value;
    showView("workflow");
    loadWorkflow();
  } else if (value.startsWith("itemrev_")) {
    $("#revision-id").value = value;
    showView("item");
    toast("문항 버전과 연결된 문항 ID도 입력하세요.");
  } else if (value.startsWith("item_")) {
    $("#item-id").value = value;
    showView("item");
    toast("문항의 고정된 버전 ID도 입력하세요.");
  } else if (HWPX_BUILD_PATTERN.test(value)) {
    selectHwpxBuild(value);
    showView("hwpx");
    loadHwpxBuild();
  } else if (ANALYSIS_BATCH_PATTERN.test(value)) {
    $("#knowledge-batch-id").value = value;
    showView("knowledge");
    loadKnowledgeQuality();
  } else {
    toast("지원되는 문항 제작 진행, 문항, HWPX 제작 또는 분석 배치 ID를 입력하세요.");
  }
}

async function initializeSession() {
  const session = await api("/session");
  state.csrf = session.csrf_token;
  state.operator = session.operator;
  $("#current-user").textContent = session.operator.display_name || session.operator.username || "Operator";
  const roles = Array.isArray(session.operator.roles) ? session.operator.roles : [];
  $("#current-role").textContent = roles.join(" · ") || "Operator";
  $$(".admin-only").forEach((element) => { element.hidden = !roles.includes("ADMIN"); });
}

async function loadHealth() {
  try {
    const value = await api("/health/ready");
    state.health = value;
    const apiState = value.application_api === "ACTIVE" ? ["success", "✓", "API Active"] : ["danger", "!", "API Unavailable"];
    const observeState = value.observability === "ACTIVE" ? ["success", "✓", "Observe Active"] : ["warning", "◆", "Observe 제한"];
    setStatus($("#api-health"), ...apiState);
    setStatus($("#observe-health"), ...observeState);
    renderDashboard(value);
  } catch (_) {
    setStatus($("#api-health"), "danger", "!", "API Unavailable");
    setStatus($("#observe-health"), "warning", "◆", "Observe 미확인");
  }
}

function renderDashboard(value) {
  $("#metric-api").textContent = statePresentation("generic", value.application_api).label;
  $("#metric-observe").textContent = statePresentation("generic", value.observability).label;
}

function replaceCurriculumOptions(select, placeholder, units, labelFor) {
  select.replaceChildren();
  const empty = document.createElement("option");
  empty.value = "";
  empty.textContent = placeholder;
  select.append(empty);
  for (const unit of units) {
    const option = document.createElement("option");
    option.value = unit.key;
    option.textContent = labelFor(unit);
    select.append(option);
  }
}

function renderCurriculumOutline() {
  const form = $("#draft-form");
  const units = state.curriculumOutline?.units;
  if (!Array.isArray(units)) return;
  const byKey = new Map(units.map((unit) => [unit.key, unit]));
  const options = curriculumOptionsForSelection(units, state.curriculumSelection);
  replaceCurriculumOptions(
    form.elements.curriculum_large_unit_key,
    "대단원 선택",
    options.large,
    (unit) => `${unit.code} ${unit.label}`,
  );
  replaceCurriculumOptions(
    form.elements.curriculum_middle_unit_key,
    "중단원 선택",
    options.middle,
    (unit) => {
      const parent = byKey.get(unit.parent_key);
      return `${unit.code} ${unit.label}${parent ? ` · ${parent.label}` : ""}`;
    },
  );
  replaceCurriculumOptions(
    form.elements.curriculum_small_unit_key,
    options.small.length ? "소단원 선택" : "소단원 목록 준비 중",
    options.small,
    (unit) => {
      const parent = byKey.get(unit.parent_key);
      return `${unit.code} ${unit.label}${parent ? ` · ${parent.label}` : ""}`;
    },
  );
  form.elements.curriculum_large_unit_key.value = state.curriculumSelection.large;
  form.elements.curriculum_middle_unit_key.value = state.curriculumSelection.middle;
  form.elements.curriculum_small_unit_key.value = state.curriculumSelection.small;
}

function setCurriculumSelection(selection) {
  state.curriculumSelection = {
    large: selection.large || "",
    middle: selection.middle || "",
    small: selection.small || "",
  };
  renderCurriculumOutline();
}

function changeCurriculumSelection(level, value) {
  if (!state.curriculumOutline) return;
  const selection = {...state.curriculumSelection, [level.toLowerCase()]: value};
  setCurriculumSelection(
    reconcileCurriculumSelection(state.curriculumOutline.units, selection, level),
  );
}

function syncGraphGroundingCapability() {
  const input = $("#draft-form").elements.knowledge_grounding;
  const available = state.curriculumOutline?.graph_grounding_available === true;
  input.disabled = !available;
  if (!available) input.checked = false;
  $("#graph-grounding-status").textContent = available
    ? "공개된 Graph 매핑을 선택한 교육과정 범위에 적용합니다."
    : "Graph 매핑 준비 중 · 교육과정 분류는 지금 사용할 수 있습니다.";
}

function syncCurriculumSelectorAvailability() {
  const form = $("#draft-form");
  const available = Array.isArray(state.curriculumOutline?.units);
  const smallAvailable = state.curriculumOutline?.units.some((unit) => unit.level === "SMALL") === true;
  form.elements.curriculum_large_unit_key.disabled = !available;
  form.elements.curriculum_middle_unit_key.disabled = !available;
  form.elements.curriculum_small_unit_key.disabled = !smallAvailable;
}

async function loadCurriculumOutline() {
  try {
    state.curriculumOutline = await api("/curriculum/editorial-outline");
    renderCurriculumOutline();
    syncGraphGroundingCapability();
    syncCurriculumSelectorAvailability();
  } catch (failure) {
    state.curriculumOutline = null;
    syncCurriculumSelectorAvailability();
    syncGraphGroundingCapability();
    showMessage($("#draft-message"), `교육과정 목록 조회 실패: ${failure.message}`, "error");
  }
}

function installRequestDraft() {
  $("#draft-analyze").addEventListener("click", analyzeDraft);
  $("#draft-save").addEventListener("click", saveDraft);
  $("#draft-submit").addEventListener("click", submitDraft);
  const form = $("#draft-form");
  form.elements.curriculum_large_unit_key.addEventListener("change", (event) => {
    changeCurriculumSelection("LARGE", event.target.value);
  });
  form.elements.curriculum_middle_unit_key.addEventListener("change", (event) => {
    changeCurriculumSelection("MIDDLE", event.target.value);
  });
  form.elements.curriculum_small_unit_key.addEventListener("change", (event) => {
    changeCurriculumSelection("SMALL", event.target.value);
  });
}

async function analyzeDraft() {
  const message = $("#draft-message");
  const pendingCurriculumSelection = {...state.curriculumSelection};
  showMessage(message, "요청을 구조화하고 있습니다.");
  try {
    const draft = await api("/request-drafts", {
      method: "POST",
      mutation: true,
      body: {original_request_text: $("#request-text").value},
    });
    state.draft = draft;
    fillDraft(draft, pendingCurriculumSelection);
    setStatus($("#draft-state"), "success", "✓", "검토 가능");
    showMessage(message, "문항 요청 초안을 검토하세요. 참고 자료 묶음 없이 일반 지식 모드로 바로 제출할 수 있습니다.", "success");
    $("#draft-save").disabled = false;
    $("#draft-submit").disabled = false;
  } catch (failure) {
    showMessage(message, `요청 분석 실패: ${failure.message}`, "error");
  }
}

function fillDraft(draft, fallbackCurriculumSelection = {large: "", middle: "", small: ""}) {
  const form = $("#draft-form");
  for (const key of ["subject", "topic", "item_format", "task_type", "difficulty", "choice_count"]) {
    form.elements[key].value = draft[key];
  }
  form.elements.equation_required.checked = draft.equation_required;
  form.elements.image_required.checked = draft.image_required;
  form.elements.quality_profile.value = draft.quality_profile;
  form.elements.source_intake_batch_id.value = draft.source_intake_batch_id || "";
  form.elements.authoring_guidance.value = draft.authoring_guidance;
  const graphGroundingAvailable = state.curriculumOutline?.graph_grounding_available === true;
  form.elements.knowledge_grounding.checked = draft.knowledge_grounding && graphGroundingAvailable;
  form.elements.knowledge_grounding.disabled = !graphGroundingAvailable;
  syncCurriculumSelectorAvailability();
  const selectedKey = draft.curriculum_selected_unit_key || "";
  setCurriculumSelection(
    state.curriculumOutline && selectedKey
      ? curriculumAncestors(state.curriculumOutline.units, selectedKey)
      : fallbackCurriculumSelection,
  );
  $("#draft-id").textContent = draft.request_draft_id;
  $("#draft-sha").textContent = draft.draft_spec_sha256;
}

function normalizeAuthoringGuidance(value) {
  return value.normalize("NFC").replace(/\s+/gu, " ").trim();
}

function draftUpdateBody() {
  const form = $("#draft-form");
  const selectedUnitKey = deepestCurriculumUnitKey(state.curriculumSelection) || null;
  if (form.elements.knowledge_grounding.checked && selectedUnitKey === null) {
    throw new Error("Graph 근거를 사용하려면 대단원 또는 중단원을 선택하세요.");
  }
  return {
    subject: form.elements.subject.value.trim(),
    topic: form.elements.topic.value.trim(),
    item_format: form.elements.item_format.value,
    task_type: form.elements.task_type.value,
    difficulty: form.elements.difficulty.value,
    choice_count: Number(form.elements.choice_count.value),
    equation_required: form.elements.equation_required.checked,
    image_required: form.elements.image_required.checked,
    quality_profile: form.elements.quality_profile.value,
    source_intake_batch_id: form.elements.source_intake_batch_id.value || null,
    authoring_guidance: normalizeAuthoringGuidance(form.elements.authoring_guidance.value),
    knowledge_grounding: form.elements.knowledge_grounding.checked,
    curriculum_selected_unit_key: selectedUnitKey,
  };
}

async function saveDraft() {
  if (!state.draft) return false;
  try {
    state.draft = await api(`/request-drafts/${encodeURIComponent(state.draft.request_draft_id)}`, {
      method: "PUT", mutation: true, body: draftUpdateBody(),
    });
    fillDraft(state.draft);
    showMessage($("#draft-message"), "문항 요청 초안이 저장되었습니다.", "success");
    $("#draft-submit").disabled = false;
    return true;
  } catch (failure) {
    showMessage($("#draft-message"), `Draft 저장 실패: ${failure.message}`, "error");
    return false;
  }
}

async function submitDraft() {
  if (!state.draft) return;
  if (!(await saveDraft())) return;
  const key = `studio:${state.draft.request_draft_id}:${state.draft.draft_spec_sha256}`;
  try {
    const result = await api(`/request-drafts/${encodeURIComponent(state.draft.request_draft_id)}/submissions`, {
      method: "POST", mutation: true, body: {idempotency_key: key},
    });
    const workflowId = result.command && result.command.resource_id;
    showMessage($("#draft-message"), result.replayed ? "동일 요청 결과를 안전하게 재표시했습니다." : "문항 제작 요청이 접수되었습니다.", "success");
    if (typeof workflowId === "string") {
      $("#workflow-id").value = workflowId;
      $("#approval-workflow-id").value = workflowId;
      showView("workflow");
      await loadWorkflow();
    }
  } catch (failure) {
    showMessage($("#draft-message"), `Workflow 제출 실패: ${failure.message}`, "error");
  }
}

function installWorkflow() {
  $("#workflow-load").addEventListener("click", loadWorkflow);
  $("#timeline-refresh").addEventListener("click", loadWorkflow);
  $("#workflow-id").addEventListener("keydown", (event) => { if (event.key === "Enter") loadWorkflow(); });
}

async function loadWorkflow() {
  const workflowId = $("#workflow-id").value.trim();
  if (!workflowId.startsWith("workflow_")) return toast("올바른 문항 제작 진행 ID를 입력하세요.");
  stopWorkflowUpdates();
  try {
    const value = await api(`/workflows/${encodeURIComponent(workflowId)}`);
    state.workflow = value;
    renderWorkflow(value);
    $("#approval-workflow-id").value = workflowId;
    startWorkflowUpdates(workflowId);
  } catch (failure) {
    setStatus($("#workflow-state"), "danger", "!", "조회 실패");
    toast(`문항 제작 진행 조회 실패: ${failure.message}`);
  }
}

function renderWorkflow(bundle) {
  const workflow = bundle.workflow || {};
  const provenance = workflow.knowledge_provenance || null;
  setStateStatus($("#workflow-state"), "workflow", workflow.state);
  const summary = {
    "문항 제작 진행 ID": workflow.workflow_id,
    "진행 상태": statePresentation("workflow", workflow.state).label,
    "현재 단계": stageLabel(workflow.current_step_key),
    ETag: bundle.etag,
    "제작 절차 버전": `${workflow.definition_key || "-"}@${workflow.definition_version || "-"}`,
    "최근 갱신 (UTC)": workflow.updated_at,
  };
  if (provenance) {
    Object.assign(summary, {
      "근거 자료 묶음": provenance.evidence_bundle_revision_id,
      "지식 그래프 버전": provenance.graph_snapshot_revision_id,
      "교육과정 키": provenance.curriculum_root_key,
      "근거 자료 유형": (provenance.source_classes || []).join(", "),
      "실행 계획 SHA": provenance.plan_sha256,
    });
  }
  renderDefinitionList($("#workflow-inspector"), summary);
  renderWorkflowEvidence(provenance);
  renderStages(workflow, bundle.steps || []);
  renderTimeline(bundle.timeline || []);
  renderOperationalLog(bundle);
  $("#approval-etag").value = bundle.etag || "";
  renderApprovalSummary(bundle);
}

function appendEvidenceChip(root, label, value, technicalValue = "") {
  const chip = document.createElement("span");
  chip.className = "evidence-chip";
  if (technicalValue) chip.title = technicalValue;
  const heading = document.createElement("strong");
  heading.textContent = label;
  chip.append(heading, document.createTextNode(value ? ` ${value}` : ""));
  root.append(chip);
}

function renderWorkflowEvidence(provenance) {
  const root = $("#workflow-evidence");
  root.replaceChildren();
  const label = document.createElement("span");
  label.className = "evidence-label";
  label.textContent = "제작 근거";
  root.append(label);
  if (!provenance) {
    appendEvidenceChip(root, "요구", "구조화됨");
    appendEvidenceChip(root, "과학 지식", "작업자 기본 지식");
    return;
  }
  if (provenance.curriculum_root_key) appendEvidenceChip(root, "교육과정", String(provenance.curriculum_root_key));
  const sourceClasses = Array.isArray(provenance.source_classes) ? provenance.source_classes.filter(Boolean) : [];
  if (sourceClasses.length) appendEvidenceChip(root, "근거 유형", sourceClasses.join(" · "));
  if (provenance.evidence_bundle_revision_id) {
    appendEvidenceChip(root, "근거 묶음", "고정됨", `기술 ID: ${provenance.evidence_bundle_revision_id}`);
  }
  if (provenance.graph_snapshot_revision_id) {
    appendEvidenceChip(root, "지식 그래프", "고정됨", `기술 ID: ${provenance.graph_snapshot_revision_id}`);
  }
  if (root.children.length === 1) appendEvidenceChip(root, "근거", "검증된 버전으로 고정됨");
}

function renderDefinitionList(element, values) {
  element.replaceChildren();
  for (const [key, value] of Object.entries(values)) {
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = key;
    dd.textContent = value === null || value === undefined || value === "" ? "-" : String(value);
    element.append(dt, dd);
  }
}

function renderStages(workflow, steps) {
  const keys = ["request", "authoring", "review", "approval", "registration", "hwpx"];
  const current = String(workflow.current_step_key || "request").replace("item_management", "registration");
  const completed = new Set(steps.filter((step) => step.state === "SUCCEEDED").map((step) => String(step.step_key).replace("item_management", "registration")));
  if (workflow.state === "COMPLETED") keys.slice(0, 5).forEach((key) => completed.add(key));
  $$("#stage-list li").forEach((element, index) => {
    const key = keys[index];
    element.classList.toggle("complete", completed.has(key));
    element.classList.toggle("current", key === current && !completed.has(key));
    const detail = element.querySelector("small");
    const hwpxState = state.hwpxCapability
      ? statePresentation("hwpx_capability", state.hwpxCapability.state).label
      : "제작 가능 여부 확인 필요";
    detail.textContent = completed.has(key) ? "완료" : key === current ? "현재 단계" : key === "hwpx" ? hwpxState : "대기";
    element.querySelector("span").textContent = completed.has(key) ? "✓" : String(index + 1);
  });
  $$("#production-map li").forEach((element) => {
    const key = element.dataset.flowStage;
    element.classList.toggle("complete", completed.has(key));
    element.classList.toggle("current", key === current && !completed.has(key));
    element.setAttribute("aria-current", key === current && !completed.has(key) ? "step" : "false");
  });
}

function renderTimeline(events) {
  const root = $("#timeline");
  root.replaceChildren();
  if (!events.length) {
    const empty = document.createElement("li");
    empty.className = "empty-state";
    empty.textContent = "표시 가능한 sanitized event가 없습니다.";
    root.append(empty);
    return;
  }
  for (const event of events) {
    const row = document.createElement("li");
    row.className = "timeline-event";
    const time = document.createElement("time");
    time.className = "event-time";
    time.dateTime = event.timestamp;
    time.textContent = formatSeoul(event.timestamp);
    const mark = document.createElement("span");
    mark.className = "event-mark";
    const presentation = statePresentation("workflow", event.state);
    mark.textContent = presentation.icon;
    const content = document.createElement("div");
    content.className = "event-content";
    const title = document.createElement("strong");
    title.textContent = event.label;
    const stateLabel = document.createElement("small");
    stateLabel.textContent = presentation.label;
    stateLabel.dataset.rawState = presentation.raw;
    stateLabel.title = `기술 상태: ${presentation.raw}`;
    const meta = document.createElement("div");
    meta.className = "event-meta";
    for (const value of [event.step, event.worker_slot, event.job_id, event.attempt ? `attempt ${event.attempt}` : null, event.artifact_id, event.validation_result, event.elapsed_ms !== null ? `${event.elapsed_ms}ms` : null, event.error_code]) {
      if (!value) continue;
      const code = document.createElement("code");
      code.textContent = String(value);
      meta.append(code);
    }
    content.append(title, stateLabel, meta);
    row.append(time, mark, content);
    root.append(row);
  }
}

function renderOperationalLog(bundle) {
  const root = $("#operational-log");
  root.replaceChildren();
  const entries = [];
  for (const step of bundle.steps || []) entries.push(`${step.step_key || "step"} · ${step.state || "UNKNOWN"} · attempt ${step.attempt || "-"} · ${step.error_code || "validated"}`);
  for (const event of bundle.events || []) entries.push(`${event.created_at || "-"} · ${event.event_type || "EVENT"} · ${event.new_state || "RECORDED"}`);
  if (!entries.length) entries.push("표시할 sanitized 운영 기록이 없습니다.");
  for (const entry of entries.slice(-100)) {
    const line = document.createElement("p");
    line.textContent = entry;
    root.append(line);
  }
}

function startWorkflowUpdates(workflowId) {
  if (typeof window.EventSource !== "function") return startPolling(workflowId);
  const stream = new EventSource(`${API}/workflows/${encodeURIComponent(workflowId)}/stream`, {withCredentials: true});
  state.stream = stream;
  stream.addEventListener("open", () => setStatus($("#stream-status"), "success", "●", "SSE 연결"));
  stream.addEventListener("workflow", (event) => {
    try { state.workflow = JSON.parse(event.data); renderWorkflow(state.workflow); } catch (_) { /* invalid events are ignored and polling remains available */ }
  });
  stream.addEventListener("error", () => {
    stream.close();
    if (state.stream === stream) state.stream = null;
    setStatus($("#stream-status"), "warning", "◆", "Polling fallback");
    startPolling(workflowId);
  });
}

function startPolling(workflowId) {
  if (state.pollTimer) return;
  state.pollTimer = window.setInterval(async () => {
    try { const value = await api(`/workflows/${encodeURIComponent(workflowId)}`); state.workflow = value; renderWorkflow(value); } catch (_) { setStatus($("#stream-status"), "danger", "!", "업데이트 중단"); }
  }, 5000);
}

function stopWorkflowUpdates() {
  if (state.stream) state.stream.close();
  if (state.pollTimer) window.clearInterval(state.pollTimer);
  state.stream = null;
  state.pollTimer = null;
}

function formatSeoul(value) {
  try { return new Intl.DateTimeFormat("ko-KR", {timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false}).format(new Date(value)); }
  catch (_) { return "-"; }
}

function installApproval() {
  $("#approval-load").addEventListener("click", async () => {
    $("#workflow-id").value = $("#approval-workflow-id").value.trim();
    await loadWorkflow();
    showView("approval");
  });
  $("#approval-submit").addEventListener("click", approveWorkflow);
}

function renderApprovalSummary(bundle) {
  const workflow = bundle.workflow || {};
  renderDefinitionList($("#approval-summary"), {"문항 제작 진행 ID": workflow.workflow_id, "진행 상태": statePresentation("workflow", workflow.state).label, "현재 단계": stageLabel(workflow.current_step_key), ETag: bundle.etag});
  const waiting = ["AWAITING_HUMAN_APPROVAL", "AWAITING_APPROVAL"].includes(workflow.state) || String(workflow.stage || "").includes("APPROVAL");
  if (waiting) setStatus($("#approval-state"), "warning", "◆", "검토 승인 대기");
  else setStateStatus($("#approval-state"), "workflow", workflow.state);
  $("#approval-submit").disabled = !waiting || !bundle.etag;
}

async function approveWorkflow() {
  const workflowId = $("#approval-workflow-id").value.trim();
  const etag = $("#approval-etag").value;
  const message = $("#approval-message");
  try {
    const result = await api(`/workflows/${encodeURIComponent(workflowId)}/approvals`, {
      method: "POST", mutation: true,
      body: {etag, idempotency_key: `studio-approval:${workflowId}:${etag.replaceAll('"', "")}`, reason: $("#approval-reason").value.trim() || null},
    });
    showMessage(message, `검토 승인 요청이 접수되었습니다. ${result.command_id || ""}`, "success");
    $("#workflow-id").value = workflowId;
    await loadWorkflow();
    showView("approval");
  } catch (failure) {
    showMessage(message, `승인 실패: ${failure.message}`, "error");
  }
}

function installItemPreview() {
  $("#item-load").addEventListener("click", loadItemPreview);
  $("#recent-items-refresh").addEventListener("click", loadRecentItems);
  $("#recent-items").addEventListener("change", loadSelectedRecentItem);
}

async function loadRecentItems() {
  const select = $("#recent-items");
  try {
    state.recentItems = await api("/items/recent");
    select.replaceChildren(new Option(
      state.recentItems.length ? "최근 완성 문항 선택" : "현재 선택 가능한 완성 문항 없음",
      "",
    ));
    for (const item of state.recentItems) {
      const reference = item.human_reference_code ? `${item.human_reference_code} · ` : "";
      const when = item.created_at || "시각 미상";
      select.append(new Option(`${reference}${item.item_id} · ${when}`, item.item_id));
    }
  } catch (failure) {
    select.replaceChildren(new Option(`목록 조회 실패: ${failure.message}`, ""));
  }
}

async function loadSelectedRecentItem() {
  const selected = state.recentItems.find((item) => item.item_id === $("#recent-items").value);
  if (!selected) return;
  $("#item-id").value = selected.item_id;
  $("#revision-id").value = selected.item_revision_id;
  await loadItemPreview();
}

async function loadItemPreview() {
  const itemId = $("#item-id").value.trim();
  const revisionId = $("#revision-id").value.trim();
  try {
    const preview = await api(`/items/${encodeURIComponent(itemId)}/revisions/${encodeURIComponent(revisionId)}/preview`);
    renderItemPreview(preview);
  } catch (failure) {
    toast(`완성 문항 조회 실패: ${failure.message}`);
  }
}

function renderItemPreview(preview) {
  setStateStatus($("#revision-state"), "item_revision", preview.revision_state);
  renderDefinitionList($("#item-inspector"), {"문항 ID": preview.item_id, "문항 버전 ID": preview.item_revision_id, "문항 제작 진행 ID": preview.workflow_id, "콘텐츠 팩 버전": preview.content_pack_release_id, "EOM 문항 템플릿": preview.template_delivery_available ? "사용 가능" : "구조화 문항 필요"});
  $("#structured-base-revision").value = preview.item_revision_id;
  $("#structured-revision-etag").value = preview.revision_etag;
  if (preview.template_delivery_available) $("#hwpx-revision-id").value = preview.item_revision_id;
  updateHwpxDeliveryGuide();
  $("#preview-page-state").textContent = statePresentation("generic", preview.preview_state).label;
  if (preview.preview_state !== "AVAILABLE") {
    $("#preview-content").hidden = true;
    $("#preview-empty").hidden = false;
    $("#preview-empty strong").textContent = "Metadata-only Preview";
    $("#preview-empty p").textContent = "Application API의 검토된 문항 read-model endpoint가 준비되면 본문·수식·표가 표시됩니다.";
    return;
  }
  $("#preview-empty").hidden = true;
  $("#preview-content").hidden = false;
  $("#preview-body").textContent = preview.body || "";
  $("#preview-answer").textContent = preview.answer || "";
  $("#preview-explanation").textContent = preview.explanation || "";
  const choices = $("#preview-choices");
  choices.replaceChildren();
  for (const choice of preview.choices || []) {
    const item = document.createElement("li");
    item.textContent = `${choice.label} ${choice.text}`;
    choices.append(item);
  }
  const equations = $("#preview-equations");
  equations.replaceChildren();
  for (const value of preview.equations || []) {
    const code = document.createElement("code");
    code.textContent = value;
    equations.append(code);
  }
  const tables = $("#preview-tables");
  tables.replaceChildren();
  for (const value of preview.tables || []) tables.append(buildDocumentTable(value));
}

function installStructuredImport() {
  $("#structured-load-sources").addEventListener("click", loadStructuredSources);
  $("#structured-import-submit").addEventListener("click", importStructuredItem);
  loadStructuredImportIntakes().catch((failure) => showMessage($("#structured-import-message"), failure.message, "error"));
}

async function loadStructuredImportIntakes() {
  const values = state.acceptedIntakes.length ? state.acceptedIntakes : await api("/content-intakes/accepted");
  state.acceptedIntakes = values;
  const select = $("#structured-intake");
  select.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = values.length ? "ACCEPTED intake 선택" : "사용 가능한 ACCEPTED intake 없음";
  select.append(placeholder);
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value.intake_batch_id;
    option.textContent = `${value.batch_name} · ${value.intake_batch_id}`;
    select.append(option);
  }
}

async function loadStructuredSources() {
  const intakeId = $("#structured-intake").value;
  if (!intakeId) return showMessage($("#structured-import-message"), "ACCEPTED intake를 선택하세요.", "error");
  try {
    const sources = await api(`/content-intakes/${encodeURIComponent(intakeId)}/sources`);
    const pointer = sources.find((value) => ["image/png", "image/jpeg"].includes(value.media_type));
    if (!pointer) throw new Error("INTAKE_IMAGE_SOURCE_REQUIRED");
    state.structuredSource = pointer;
    $("#structured-source-pointer").textContent = JSON.stringify(pointer, null, 2);
    if (!$("#structured-content-json").value.trim()) {
      $("#structured-content-json").value = JSON.stringify(structuredItemSkeleton(pointer), null, 2);
    }
    showMessage($("#structured-import-message"), "정확한 artifact member와 SHA를 불러왔습니다. 문항 의미를 편집하고 검토하세요.", "success");
  } catch (failure) {
    showMessage($("#structured-import-message"), `Source 조회 실패: ${failure.message}`, "error");
  }
}

function structuredItemSkeleton(pointer) {
  return {
    schema_version: "1.0", locale: "ko-KR", title: "검토된 구조화 문항",
    body: [
      {block_id: "block_stem", type: "paragraph", purpose: "stem", text: "문항 본문을 입력하세요."},
      {block_id: "block_data", type: "table", purpose: "data", caption: null, headers: ["구분", "값"], rows: [["자료", "내용"]]},
      {block_id: "block_image", type: "image", purpose: "stimulus", artifact: {artifact_id: pointer.artifact_id, artifact_revision_id: pointer.artifact_revision_id, artifact_member: pointer.artifact_member, sha256: pointer.sha256, media_type: pointer.media_type}, alt_text: pointer.filename, width_px: 800, height_px: 500},
      {block_id: "block_equation", type: "equation", purpose: "stimulus", notation: "hancom-equation-script", source: "a^2+b^2=c^2"},
      {block_id: "block_prompt", type: "paragraph", purpose: "prompt", text: "옳은 것을 고르시오."},
      {block_id: "block_claims", type: "statement_set", purpose: "claims", statements: [{statement_id: "statement_g", label: "ㄱ", text: "명제 ㄱ"}, {statement_id: "statement_n", label: "ㄴ", text: "명제 ㄴ"}, {statement_id: "statement_d", label: "ㄷ", text: "명제 ㄷ"}]},
    ],
    interaction: {type: "single_choice", choices: [1, 2, 3, 4, 5].map((value) => ({choice_id: `choice_${value}`, label: String(value), text: `선택지 ${value}`}))},
    solution: {correct_choice_ids: ["choice_1"], accepted_answers: [], explanation: "정답 해설을 입력하세요.", authoring_intent: "평가 의도를 입력하세요.", statement_explanations: [{statement_id: "statement_g", text: "ㄱ 해설"}, {statement_id: "statement_n", text: "ㄴ 해설"}, {statement_id: "statement_d", text: "ㄷ 해설"}]},
    score: {points: 3},
  };
}

async function importStructuredItem() {
  const message = $("#structured-import-message");
  if (!$("#structured-reviewed").checked) return showMessage(message, "명시적 검토 확인이 필요합니다.", "error");
  let content;
  try { content = JSON.parse($("#structured-content-json").value); } catch (_) { return showMessage(message, "구조화 콘텐츠 JSON이 올바르지 않습니다.", "error"); }
  const baseRevision = $("#structured-base-revision").value.trim();
  try {
    const result = await api("/items/structured-content-imports", {
      method: "POST", mutation: true,
      body: {base_revision_id: baseRevision, revision_etag: $("#structured-revision-etag").value.trim(), idempotency_key: `studio:structured-import:${baseRevision}:${crypto.randomUUID()}`, reviewed: true, review_reason: $("#structured-review-reason").value.trim(), content},
    });
    $("#revision-id").value = result.resource_id;
    $("#hwpx-revision-id").value = result.resource_id;
    showMessage(message, `새 immutable Revision ${result.resource_id}가 등록되었습니다.`, "success");
    await loadItemPreview();
  } catch (failure) {
    showMessage(message, `등록 실패: ${failure.message}`, "error");
  }
}

function buildDocumentTable(value) {
  const table = document.createElement("table");
  table.className = "document-table";
  if (value.caption) { const caption = document.createElement("caption"); caption.textContent = value.caption; table.append(caption); }
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const text of value.headers || []) { const th = document.createElement("th"); th.textContent = text; headRow.append(th); }
  head.append(headRow);
  const body = document.createElement("tbody");
  for (const row of value.rows || []) { const tr = document.createElement("tr"); for (const text of row) { const td = document.createElement("td"); td.textContent = text; tr.append(td); } body.append(tr); }
  table.append(head, body);
  return table;
}

async function loadHwpx() {
  try {
    const value = await api("/hwpx/capability");
    state.hwpxCapability = value;
    $("#hwpx-state-title").textContent = statePresentation("hwpx_capability", value.state).label;
    $("#hwpx-message").textContent = value.message;
    $("#renderer-key").textContent = value.renderer_key;
    $("#renderer-version").textContent = `${value.renderer_version} / ${value.document_profile}`;
    $("#hwpx-build-state").textContent = value.build_available ? "제작 가능" : "현재 제작 불가";
    $("#hwpx-validation").textContent = value.detail_code;
    $("#hwpx-equations").textContent = value.native_equations ? "지원" : "준비 필요";
    $("#hwpx-tables").textContent = value.native_tables ? "지원" : "준비 필요";
    $("#hwpx-download").textContent = value.build_available ? "검증 후 가능" : "현재 이용 불가";
    setStateStatus($("#hwpx-state-badge"), "hwpx_capability", value.state);
    setStateStatus($("#hwpx-inspector-badge"), "hwpx_capability", value.state);
    $("#hwpx-step-state").textContent = statePresentation("hwpx_capability", value.state).label;
    $("#metric-hwpx").textContent = statePresentation("hwpx_capability", value.state).label;
    $("#hwpx-build-submit").disabled = !value.build_available;
  } catch (failure) {
    setStatus($("#hwpx-state-badge"), "danger", "!", "HWPX 상태 확인 실패");
    $("#hwpx-message").textContent = failure.message;
    $("#hwpx-build-submit").disabled = true;
  }
}

function installHwpx() {
  $("#hwpx-build-submit").addEventListener("click", createHwpxBuild);
  $("#hwpx-build-refresh").addEventListener("click", loadHwpxBuild);
  $("#hwpx-build-load").addEventListener("click", loadSelectedHwpxBuild);
  $("#hwpx-existing-build-id").addEventListener("keydown", (event) => {
    if (event.key === "Enter") loadSelectedHwpxBuild();
  });
  $("#hwpx-recent-builds").addEventListener("change", loadRecentHwpxBuild);
  $("#hwpx-recent-refresh").addEventListener("click", loadRecentHwpxBuilds);
  $("#hwpx-revision-id").addEventListener("input", () => {
    renderRecentHwpxBuilds();
    updateHwpxDeliveryGuide();
  });
  updateHwpxDeliveryGuide();
}

function selectHwpxBuild(buildId) {
  state.hwpxBuildId = buildId;
  $("#hwpx-existing-build-id").value = buildId;
  $("#hwpx-build-id").textContent = buildId;
  $("#hwpx-build-refresh").disabled = false;
  const url = new URL(window.location.href);
  url.searchParams.set("hwpx_build_id", buildId);
  window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
}

function resetHwpxBuildResult() {
  window.clearTimeout(state.hwpxPollTimer);
  setStatus($("#hwpx-job-badge"), "neutral", "■", "조회 중");
  $("#hwpx-resource-state").textContent = "-";
  $("#hwpx-artifact-revision").textContent = "-";
  $("#hwpx-completed-at").textContent = "-";
  const download = $("#hwpx-download-link");
  download.hidden = true;
  download.href = "#";
  $("#hwpx-download").textContent = "아직 이용 불가";
  updateHwpxDeliveryGuide();
}

function loadSelectedHwpxBuild() {
  const buildId = $("#hwpx-existing-build-id").value.trim();
  if (!HWPX_BUILD_PATTERN.test(buildId)) {
    return showMessage($("#hwpx-build-message"), "정확한 hwpxbuild_ ID를 입력하세요.", "error");
  }
  selectHwpxBuild(buildId);
  resetHwpxBuildResult();
  return loadHwpxBuild();
}

function restoreHwpxBuild() {
  const buildId = new URL(window.location.href).searchParams.get("hwpx_build_id");
  if (!buildId || !HWPX_BUILD_PATTERN.test(buildId)) return false;
  selectHwpxBuild(buildId);
  return true;
}

async function createHwpxBuild() {
  const revision = $("#hwpx-revision-id").value.trim();
  if (!revision.startsWith("itemrev_")) return toast("승인된 문항 버전 ID를 입력하세요.");
  const itemNumber = Number.parseInt($("#hwpx-item-number").value, 10);
  if (!Number.isInteger(itemNumber) || itemNumber < 1 || itemNumber > 999) return toast("문항 번호는 1~999 범위여야 합니다.");
  const idempotency = `studio:hwpx:${revision}:${crypto.randomUUID()}`;
  try {
    const command = await api("/hwpx/builds", {
      method: "POST",
      mutation: true,
      body: {
        item_revision_id: revision,
        idempotency_key: idempotency,
        require_native_equations: true,
        require_native_tables: true,
        item_number: itemNumber,
      },
    });
    selectHwpxBuild(command.resource_id);
    showMessage($("#hwpx-build-message"), "HWPX 제작 요청을 접수했습니다.", "success");
    await loadHwpxBuild();
  } catch (failure) {
    showMessage($("#hwpx-build-message"), `HWPX 제작 요청 실패: ${failure.message}`, "error");
  }
}

async function loadHwpxBuild() {
  if (!state.hwpxBuildId) return;
  try {
    const value = await api(`/hwpx/builds/${encodeURIComponent(state.hwpxBuildId)}`);
    setStateStatus($("#hwpx-job-badge"), "hwpx_build", value.state);
    $("#hwpx-resource-state").textContent = `${statePresentation("hwpx_build", value.state).label} / ${statePresentation("generic", value.validation_state).label}`;
    $("#hwpx-resource-state").dataset.rawState = `${value.state}/${value.validation_state}`;
    $("#hwpx-resource-state").title = `기술 상태: ${value.state} / 검증: ${value.validation_state}`;
    $("#hwpx-validation").textContent = statePresentation("generic", value.validation_state).label;
    $("#hwpx-equations").textContent = value.native_equation_count === null ? "대기" : String(value.native_equation_count);
    $("#hwpx-tables").textContent = value.native_table_count === null ? "대기" : String(value.native_table_count);
    $("#hwpx-artifact-revision").textContent = value.output_artifact_revision_id || "-";
    $("#hwpx-completed-at").textContent = value.completed_at || "-";
    $("#hwpx-revision-id").value = value.item_revision_id;
    const download = $("#hwpx-download-link");
    download.hidden = !value.download_available;
    download.href = value.download_available ? `${API}/hwpx/builds/${encodeURIComponent(value.build_id)}/download` : "#";
    $("#hwpx-download").textContent = value.download_available ? "다운로드 가능" : "아직 이용 불가";
    updateHwpxDeliveryGuide(value);
    window.clearTimeout(state.hwpxPollTimer);
    if (["REQUESTED", "RUNNING", "VALIDATING"].includes(value.state)) {
      state.hwpxPollTimer = window.setTimeout(loadHwpxBuild, 2000);
    }
    if (value.download_available) {
      showMessage($("#hwpx-build-message"), "검증된 HWPX를 다운로드할 수 있습니다.", "success");
    } else if (value.failure_code) {
      showMessage($("#hwpx-build-message"), `HWPX 제작 실패: ${errorMessage(value.failure_code)}`, "error");
    } else {
      showMessage($("#hwpx-build-message"), `HWPX 제작 상태: ${statePresentation("hwpx_build", value.state).label}`);
    }
    rememberRecentHwpxBuild(value);
  } catch (failure) {
    resetHwpxBuildResult();
    setStatus($("#hwpx-job-badge"), "danger", "!", "조회 실패");
    showMessage($("#hwpx-build-message"), `상태 조회 실패: ${failure.message}`, "error");
  }
}

function hasAdminRole() {
  const roles = state.operator && Array.isArray(state.operator.roles) ? state.operator.roles : [];
  return roles.includes("ADMIN");
}

function installControlPlane() {
  $("#control-refresh").addEventListener("click", loadControlPlane);
  $("#preset-draft-submit").addEventListener("click", createPresetDraft);
}

async function loadControlPlane() {
  if (!hasAdminRole()) return;
  try {
    const [accounts, presets, batches] = await Promise.all([
      api("/admin/codex-accounts"),
      api("/admin/execution-presets"),
      api("/admin/knowledge-analysis-batches"),
    ]);
    state.codexAccounts = accounts;
    state.executionPresets = presets;
    state.knowledgeAnalysisBatches = batches;
    renderCodexAccounts(accounts);
    renderExecutionPresets(presets);
    renderAnalysisBatches(batches);
    showMessage($("#codex-account-message"), `${accounts.length}개 fixed binding · credential 비노출`, "success");
    showMessage($("#execution-preset-message"), `${presets.length}개 logical preset · immutable revision`, "success");
    scheduleAnalysisBatchRefresh(batches);
  } catch (failure) {
    showMessage($("#codex-account-message"), `Control Plane 조회 실패: ${failure.message}`, "error");
  }
}

function scheduleAnalysisBatchRefresh(batches) {
  window.clearTimeout(state.analysisBatchPollTimer);
  if (batches.some((value) => ["QUEUED", "RUNNING"].includes(value.state))) {
    state.analysisBatchPollTimer = window.setTimeout(loadAnalysisBatches, 10000);
  }
}

async function loadAnalysisBatches() {
  if (!hasAdminRole() || !$('[data-view="control"].active')) return;
  try {
    const batches = await api("/admin/knowledge-analysis-batches");
    state.knowledgeAnalysisBatches = batches;
    renderAnalysisBatches(batches);
    scheduleAnalysisBatchRefresh(batches);
  } catch (failure) {
    showMessage($("#analysis-batch-message"), `배치 상태 조회 실패: ${failure.message}`, "error");
  }
}

function renderAnalysisBatches(batches) {
  const root = $("#analysis-batch-list");
  root.replaceChildren();
  if (!batches.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "등록된 분석 배치가 없습니다.";
    root.append(empty);
    showMessage($("#analysis-batch-message"), "배치 0개 · 제품 기능과 독립된 읽기 전용 상태");
    return;
  }
  for (const batch of batches) {
    const {card, details} = controlCard(batch.batch_id, batch.state, "knowledge_analysis");
    const completed = batch.accepted_range_count + batch.failed_range_count;
    const percent = Math.floor((completed * 100) / batch.total_range_count);
    addControlDetail(details, "Accepted", `${batch.accepted_range_count} / ${batch.total_range_count}`);
    addControlDetail(details, "Failed", batch.failed_range_count);
    addControlDetail(details, "Progress", `${percent}%`);
    addControlDetail(details, "ETA", analysisBatchEta(batch, completed));
    addControlDetail(details, "Failure", batch.failure_code);
    addControlDetail(details, "Updated", batch.updated_at);
    const progress = document.createElement("progress");
    progress.className = "analysis-progress";
    progress.max = batch.total_range_count;
    progress.value = completed;
    progress.setAttribute("aria-label", `${batch.batch_id} 진행률`);
    card.append(progress);
    const actions = document.createElement("div");
    actions.className = "form-actions";
    actions.append(actionButton("범위·품질 보기", () => {
      $("#knowledge-batch-id").value = batch.batch_id;
      showView("knowledge");
      loadKnowledgeQuality();
    }, true));
    card.append(actions);
    root.append(card);
  }
  const active = batches.filter((value) => ["QUEUED", "RUNNING"].includes(value.state)).length;
  showMessage($("#analysis-batch-message"), `${batches.length}개 최근 배치 · 실행 중 ${active}개 · 10초 자동 갱신`, "success");
}

function analysisBatchEta(batch, completed) {
  if (batch.state === "SUCCEEDED") return "완료";
  if (batch.state !== "RUNNING" || completed === 0 || !batch.started_at || !batch.updated_at) return "산출 대기";
  const started = Date.parse(batch.started_at);
  const observed = Date.parse(batch.updated_at);
  if (!Number.isFinite(started) || !Number.isFinite(observed) || observed <= started) return "계산 불가";
  const remaining = batch.total_range_count - completed;
  if (remaining <= 0) return "마무리 중";
  const seconds = Math.ceil(((observed - started) / 1000 / completed) * remaining);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.max(1, Math.ceil((seconds % 3600) / 60));
  return `단순 추정 약 ${hours ? `${hours}시간 ` : ""}${minutes}분`;
}

function installKnowledgeQuality() {
  $("#knowledge-quality-load").addEventListener("click", loadKnowledgeQuality);
  $("#knowledge-batch-id").addEventListener("keydown", (event) => {
    if (event.key === "Enter") loadKnowledgeQuality();
  });
}

async function loadKnowledgeQuality() {
  const batchId = $("#knowledge-batch-id").value.trim();
  const message = $("#knowledge-quality-message");
  if (!ANALYSIS_BATCH_PATTERN.test(batchId)) {
    return showMessage(message, "정확한 analysisbatch_ ID를 입력하세요.", "error");
  }
  showMessage(message, "기존 read-only 범위를 확인하고 있습니다.");
  try {
    const report = await api(`/admin/knowledge-analysis-batches/${encodeURIComponent(batchId)}/quality`);
    state.knowledgeQualityReport = report;
    renderKnowledgeQuality(report);
    showMessage(message, `resource v${report.resource_version} · ${report.observed_range_count}개 범위 관찰`, "success");
  } catch (failure) {
    state.knowledgeQualityReport = null;
    setStatus($("#knowledge-quality-badge"), "danger", "!", "조회 실패");
    showMessage(message, `분석 품질 조회 실패: ${failure.message}`, "error");
  }
}

function renderKnowledgeQuality(report) {
  const tones = {PASS: ["success", "✓", "구조 점검 통과"], WARN: ["warning", "◆", "검토 항목 있음"], FAIL: ["danger", "!", "구조 불일치"]};
  setStatus($("#knowledge-quality-badge"), ...(tones[report.quality_state] || ["neutral", "■", "알 수 없음"]));
  $("#quality-ranges").textContent = `${report.observed_range_count} / ${report.total_range_count}`;
  $("#quality-pages").textContent = `${report.unique_page_count} (${report.selected_page_count})`;
  $("#quality-visual-pages").textContent = `${report.visual_input_page_count}`;
  $("#quality-accepted-pages").textContent = `${report.accepted_page_count}`;
  $("#quality-gaps").textContent = `${report.gap_page_count}`;
  $("#quality-overlaps").textContent = `${report.overlap_page_count}`;
  $("#knowledge-observed-at").textContent = `Observed ${report.observed_at}`;
  renderKnowledgeMap(report.documents || []);
  renderKnowledgeFindings(report.findings || []);
  renderKnowledgeDocuments(report.documents || []);
}

function renderKnowledgeMap(documents) {
  const root = $("#knowledge-map");
  root.replaceChildren();
  let edgeCount = 0;
  for (const documentCoverage of documents) {
    const unitKeys = documentCoverage.curriculum_unit_keys || [];
    edgeCount += unitKeys.length;
    const row = document.createElement("div");
    row.className = "knowledge-map-row";
    const unit = document.createElement("code");
    unit.textContent = unitKeys.join(" · ") || "미분류";
    const arrow = document.createElement("span");
    arrow.setAttribute("aria-hidden", "true");
    arrow.textContent = "→";
    const target = document.createElement("div");
    const revision = document.createElement("strong");
    revision.textContent = documentCoverage.document_revision_id;
    const pages = document.createElement("small");
    pages.textContent = `physical pages ${documentCoverage.first_physical_page}–${documentCoverage.last_physical_page}`;
    target.append(revision, pages);
    row.append(unit, arrow, target);
    root.append(row);
  }
  if (!documents.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "관찰된 교육과정 연결이 없습니다.";
    root.append(empty);
  }
  $("#knowledge-edge-count").textContent = `${edgeCount} observed edges`;
}

function renderKnowledgeFindings(findings) {
  const root = $("#knowledge-findings");
  root.replaceChildren();
  if (!findings.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "범위·pointer 구조에서 이상을 찾지 못했습니다.";
    root.append(empty);
    return;
  }
  for (const finding of findings) {
    const item = document.createElement("article");
    item.className = `quality-finding${finding.severity === "ERROR" ? " error" : ""}`;
    const code = document.createElement("strong");
    code.textContent = finding.code;
    const context = document.createElement("small");
    const pageScope = finding.first_physical_page === null ? "" : ` · pages ${finding.first_physical_page}–${finding.last_physical_page}`;
    context.textContent = `${finding.severity}${finding.document_revision_id ? ` · ${finding.document_revision_id}` : ""}${pageScope}`;
    item.append(code, context);
    root.append(item);
  }
}

function renderKnowledgeDocuments(documents) {
  const root = $("#knowledge-document-list");
  root.replaceChildren();
  for (const documentCoverage of documents) {
    const card = document.createElement("article");
    card.className = "document-coverage-card";
    const identity = document.createElement("div");
    const revision = document.createElement("code");
    revision.textContent = documentCoverage.document_revision_id;
    const scope = document.createElement("small");
    scope.textContent = `pages ${documentCoverage.first_physical_page}–${documentCoverage.last_physical_page} · ${documentCoverage.curriculum_unit_keys.join(", ") || "미분류"}`;
    identity.append(revision, scope);
    card.append(identity);
    for (const [label, value] of [["Ranges", documentCoverage.range_count], ["Unique", documentCoverage.unique_page_count], ["Accepted", documentCoverage.accepted_page_count], ["Cancelled", documentCoverage.cancelled_page_count], ["Gaps", documentCoverage.gap_page_count], ["Overlaps", documentCoverage.overlap_page_count]]) {
      const stat = document.createElement("div");
      stat.className = "coverage-stat";
      const title = document.createElement("span");
      title.textContent = label;
      const count = document.createElement("strong");
      count.textContent = String(value);
      stat.append(title, count);
      card.append(stat);
    }
    root.append(card);
  }
  if (!documents.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "관찰된 문서 버전이 없습니다.";
    root.append(empty);
  }
}

function updateHwpxDeliveryGuide(build = null) {
  const stages = Object.fromEntries($$("#hwpx-delivery-guide li").map((element) => [element.dataset.deliveryStage, element]));
  Object.values(stages).forEach((element) => element.classList.remove("complete", "current"));
  const hasRevision = $("#hwpx-revision-id").value.trim().startsWith("itemrev_");
  if (!hasRevision) {
    stages.revision.classList.add("current");
    return;
  }
  stages.revision.classList.add("complete");
  if (!build || !["SUCCEEDED"].includes(build.state)) {
    stages.build.classList.add("current");
    return;
  }
  stages.build.classList.add("complete");
  stages.download.classList.add(build.download_available ? "complete" : "current");
}

function controlCard(title, stateValue, domain = "generic") {
  const card = document.createElement("article");
  card.className = "control-card";
  const header = document.createElement("header");
  const heading = document.createElement("h3");
  heading.textContent = title;
  const badge = document.createElement("span");
  setStateStatus(badge, domain, stateValue);
  header.append(heading, badge);
  const details = document.createElement("dl");
  card.append(header, details);
  return {card, details};
}

function addControlDetail(list, label, value) {
  const term = document.createElement("dt");
  const description = document.createElement("dd");
  term.textContent = label;
  description.textContent = value === null || value === undefined ? "-" : String(value);
  list.append(term, description);
}

function actionButton(label, action, quiet = false) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `button ${quiet ? "quiet" : "secondary"}`;
  button.textContent = label;
  button.addEventListener("click", action);
  return button;
}

function renderCodexAccounts(accounts) {
  const root = $("#codex-account-list");
  root.replaceChildren();
  if (!accounts.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "등록된 sanitized binding이 없습니다.";
    root.append(empty);
    return;
  }
  for (const account of accounts) {
    const {card, details} = controlCard(`${account.slot_key} · ${account.account_label}`, account.state, "codex_account");
    const capabilities = (account.capabilities || []).map((value) => `${value.model}/${value.reasoning_effort}`).join(", ") || "관측 없음";
    addControlDetail(details, "Binding", account.binding_id);
    addControlDetail(details, "CLI", account.codex_cli_version);
    addControlDetail(details, "Capabilities", capabilities);
    addControlDetail(details, "Active leases", account.active_lease_count);
    addControlDetail(details, "Last success", account.last_successful_job_id);
    addControlDetail(details, "Observed", account.observed_at);
    const actions = document.createElement("div");
    actions.className = "form-actions";
    actions.append(
      actionButton("상태 관측", () => sendAccountCommand(account, "OBSERVE")),
      actionButton("Enable", () => sendAccountCommand(account, "ENABLE")),
      actionButton("Drain", () => sendAccountCommand(account, "DRAIN"), true),
      actionButton("Disable", () => sendAccountCommand(account, "DISABLE"), true),
    );
    card.append(actions);
    root.append(card);
  }
}

async function sendAccountCommand(account, commandType) {
  const reason = commandType === "DRAIN" ? "OPERATOR_REQUESTED_DRAIN" : commandType === "DISABLE" ? "OPERATOR_REQUESTED_DISABLE" : null;
  try {
    const result = await api(`/admin/codex-accounts/${encodeURIComponent(account.binding_id)}/commands`, {
      method: "POST",
      mutation: true,
      body: {
        command_type: commandType,
        resource_version: account.resource_version,
        idempotency_key: `studio:codex-account:${account.binding_id}:${commandType}:${crypto.randomUUID()}`,
        reason_code: reason,
      },
    });
    showMessage($("#codex-account-message"), `${result.command_id} 접수 · credential 전송 없음`, "success");
    await pollControlCommand(result.command_id);
  } catch (failure) {
    showMessage($("#codex-account-message"), `계정 command 실패: ${failure.message}`, "error");
  }
}

async function pollControlCommand(commandId) {
  for (let attempt = 0; attempt < 15; attempt += 1) {
    const value = await api(`/admin/codex-control-commands/${encodeURIComponent(commandId)}`);
    if (["SUCCEEDED", "FAILED"].includes(value.state)) {
      showMessage($("#codex-account-message"), `${value.command_type}: ${value.state}${value.error_code ? ` · ${value.error_code}` : ""}`, value.state === "SUCCEEDED" ? "success" : "error");
      await loadControlPlane();
      return;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 1000));
  }
  showMessage($("#codex-account-message"), "command가 계속 처리 중입니다. 새로고침으로 확인하세요.");
}

function renderExecutionPresets(presets) {
  const root = $("#execution-preset-list");
  root.replaceChildren();
  if (!presets.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "등록된 Execution Preset이 없습니다.";
    root.append(empty);
    return;
  }
  for (const preset of presets) {
    const revisions = Array.isArray(preset.revisions) ? [...preset.revisions].sort((left, right) => right.revision_number - left.revision_number) : [];
    const latest = revisions[0];
    const current = revisions.find((revision) => revision.preset_revision_id === preset.current_revision_id);
    const {card, details} = controlCard(preset.preset_key, preset.state, "execution_preset");
    addControlDetail(details, "Preset", preset.preset_id);
    addControlDetail(details, "Current", preset.current_revision_id);
    addControlDetail(details, "Revision count", revisions.length);
    addControlDetail(details, "Policy SHA", current ? current.content_sha256 : null);
    addControlDetail(details, "Models", current ? current.role_policies.map((policy) => `${policy.role}:${policy.model_candidates.map((candidate) => `${candidate.model}/${candidate.reasoning_effort}`).join("|")}`).join(", ") : null);
    addControlDetail(details, "Evaluation", current && current.evaluations.length ? current.evaluations.map((value) => `${value.scope}:${value.outcome}`).join(", ") : "없음");
    const actions = document.createElement("div");
    actions.className = "form-actions";
    if (latest && latest.state === "DRAFT") actions.append(actionButton("DRAFT Release", () => mutatePreset("release", latest.preset_revision_id, latest.revision_number)));
    if (current && preset.state === "ACTIVE") actions.append(actionButton("Deprecate", () => mutatePreset("deprecate", preset.preset_id, current.revision_number), true));
    card.append(actions);
    root.append(card);
  }
}

async function mutatePreset(operation, identifier, resourceVersion) {
  const path = operation === "release"
    ? `/admin/execution-preset-revisions/${encodeURIComponent(identifier)}/releases`
    : `/admin/execution-presets/${encodeURIComponent(identifier)}/deprecations`;
  try {
    const result = await api(path, {
      method: "POST",
      mutation: true,
      body: {resource_version: resourceVersion, idempotency_key: `studio:preset:${operation}:${identifier}:${crypto.randomUUID()}`},
    });
    showMessage($("#execution-preset-message"), `${operation}: ${result.resource_id}`, "success");
    await loadControlPlane();
  } catch (failure) {
    showMessage($("#execution-preset-message"), `${operation} 실패: ${failure.message}`, "error");
  }
}

async function createPresetDraft() {
  let value;
  try {
    value = JSON.parse($("#preset-draft-json").value);
  } catch (_) {
    return showMessage($("#preset-draft-message"), "Preset Draft JSON이 올바르지 않습니다.", "error");
  }
  try {
    const result = await api("/admin/execution-presets", {
      method: "POST",
      mutation: true,
      body: {...value, idempotency_key: `studio:preset:draft:${crypto.randomUUID()}`},
    });
    showMessage($("#preset-draft-message"), `DRAFT ${result.resource_id} 생성`, "success");
    await loadControlPlane();
  } catch (failure) {
    showMessage($("#preset-draft-message"), `DRAFT 생성 실패: ${failure.message}`, "error");
  }
}

async function loadRecentHwpxBuilds() {
  if (!hasAdminRole()) return;
  try {
    const result = await api("/explorer/query", {
      method: "POST",
      mutation: true,
      body: {schema_version: "1.0", entity: "hwpx_builds", sort: "created_desc", limit: 20},
    });
    state.hwpxRecentBuilds = result.rows;
    renderRecentHwpxBuilds();
  } catch (failure) {
    const select = $("#hwpx-recent-builds");
    select.replaceChildren(new Option(`목록 조회 실패: ${failure.message}`, ""));
  }
}

function renderRecentHwpxBuilds() {
  if (!hasAdminRole()) return;
  const selectedRevision = $("#hwpx-revision-id").value.trim();
  const rows = state.hwpxRecentBuilds.filter(
    (row) => !selectedRevision || row.item_revision_id === selectedRevision,
  );
  const select = $("#hwpx-recent-builds");
  select.replaceChildren(new Option(rows.length ? "최근 Build 선택" : "조건에 맞는 최근 Build 없음", ""));
  for (const row of rows) {
    const when = row.completed_at || row.created_at || "시각 미상";
    select.append(new Option(`${statePresentation("hwpx_build", row.state).label} · ${row.build_id} · ${when}`, row.build_id));
  }
}

function rememberRecentHwpxBuild(value) {
  if (!hasAdminRole()) return;
  state.hwpxRecentBuilds = [
    value,
    ...state.hwpxRecentBuilds.filter((row) => row.build_id !== value.build_id),
  ].slice(0, 20);
  renderRecentHwpxBuilds();
}

function loadRecentHwpxBuild() {
  const buildId = $("#hwpx-recent-builds").value;
  if (!HWPX_BUILD_PATTERN.test(buildId)) return;
  $("#hwpx-existing-build-id").value = buildId;
  loadSelectedHwpxBuild();
}

function installExplorer() {
  $("#explorer-form").addEventListener("submit", (event) => { event.preventDefault(); state.explorerCursor = null; runExplorer(); });
  $("#explorer-next").addEventListener("click", runExplorer);
  $("#density-toggle").addEventListener("click", () => {
    const wrap = $(".data-table-wrap");
    wrap.classList.toggle("dense");
    $("#density-toggle").textContent = wrap.classList.contains("dense") ? "편안하게" : "조밀하게";
  });
  $("#json-close").addEventListener("click", () => { $("#json-drawer").hidden = true; });
  $("#json-copy").addEventListener("click", copyExplorerId);
}

function explorerBody() {
  const form = $("#explorer-form");
  const toUtc = (value) => value ? new Date(value).toISOString() : null;
  return {
    schema_version: "1.0",
    entity: form.elements.entity.value,
    exact_id: form.elements.exact_id.value.trim() || null,
    status: form.elements.status.value.trim() || null,
    date_from: toUtc(form.elements.date_from.value),
    date_to: toUtc(form.elements.date_to.value),
    sort: form.elements.sort.value,
    cursor: state.explorerCursor,
    limit: Number(form.elements.limit.value),
  };
}

async function runExplorer() {
  const message = $("#explorer-message");
  try {
    const result = await api("/explorer/query", {method: "POST", mutation: true, body: explorerBody()});
    renderExplorer(result);
    state.explorerCursor = result.next_cursor;
    $("#explorer-next").disabled = !result.has_more || !result.next_cursor;
    $("#explorer-capability").textContent = `${result.entity} · ${result.capability}`;
    showMessage(message, `${result.rows.length}개 row · Application API/Observability read-only projection`, "success");
  } catch (failure) {
    showMessage(message, `조회 실패: ${failure.message}`, "error");
  }
}

function renderExplorer(result) {
  const table = $("#explorer-table");
  table.querySelector("thead").replaceChildren();
  table.querySelector("tbody").replaceChildren();
  const headerRow = document.createElement("tr");
  for (const column of result.columns) { const th = document.createElement("th"); th.textContent = column.replaceAll("_", " "); headerRow.append(th); }
  table.querySelector("thead").append(headerRow);
  if (!result.rows.length) {
    const tr = document.createElement("tr"); const td = document.createElement("td"); td.className = "empty-state"; td.colSpan = Math.max(1, result.columns.length); td.textContent = result.capability === "EXACT_ID_REQUIRED" ? "이 entity는 정확한 ID 조회가 필요합니다." : result.capability === "PREPARED_NOT_DEPLOYED" ? "HWPX Renderer 운영 배포 필요" : "조건에 맞는 row가 없습니다."; tr.append(td); table.querySelector("tbody").append(tr); return;
  }
  for (const row of result.rows) {
    const tr = document.createElement("tr"); tr.tabIndex = 0;
    tr.addEventListener("click", () => openExplorerRow(row));
    tr.addEventListener("keydown", (event) => { if (event.key === "Enter") openExplorerRow(row); });
    for (const column of result.columns) { const td = document.createElement("td"); td.textContent = row[column] === null || row[column] === undefined ? "-" : String(row[column]); td.title = td.textContent; tr.append(td); }
    table.querySelector("tbody").append(tr);
  }
}

function openExplorerRow(row) {
  state.explorerRow = row;
  $("#json-detail").textContent = JSON.stringify(row, null, 2);
  $("#json-drawer").hidden = false;
}

async function copyExplorerId() {
  if (!state.explorerRow || !navigator.clipboard) return toast("복사 가능한 ID가 없습니다.");
  const value = Object.values(state.explorerRow).find((item) => typeof item === "string" && /^(workflow|item|itemrev|job|artifact|revision|usage|contentpack)_/.test(item));
  if (!value) return toast("이 row에는 복사 가능한 ID가 없습니다.");
  await navigator.clipboard.writeText(value);
  toast("ID를 복사했습니다.");
}

async function logout() {
  try { await api("/logout", {method: "POST", mutation: true, body: {}}); } finally { window.location.replace("/studio/login"); }
}

async function boot() {
  await loadPresentationVocabulary();
  syncUiMode("workflow");
  installNavigation();
  installRequestDraft();
  installWorkflow();
  installApproval();
  installItemPreview();
  installStructuredImport();
  installHwpx();
  installControlPlane();
  installKnowledgeQuality();
  installExplorer();
  $("#logout").addEventListener("click", logout);
  await initializeSession();
  await loadCurriculumOutline();
  const restoredHwpx = restoreHwpxBuild();
  if (restoredHwpx) showView("hwpx");
  await Promise.all([loadHealth(), loadHwpx(), loadRecentHwpxBuilds(), loadRecentItems()]);
  if (restoredHwpx) await loadHwpxBuild();
}

boot().catch(() => window.location.replace("/studio/login"));
