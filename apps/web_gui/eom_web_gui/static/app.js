const API = "/studio/api/v1";
const HWPX_BUILD_PATTERN = /^hwpxbuild_[a-f0-9]{32}$/;
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
  acceptedIntakes: [],
  structuredSource: null,
  codexAccounts: [],
  executionPresets: [],
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

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
    throw new Error("인증 세션이 만료되었습니다.");
  }
  if (!response.ok) {
    let code = `HTTP_${response.status}`;
    try {
      const problem = await response.json();
      if (typeof problem.error_code === "string") code = problem.error_code;
    } catch (_) {
      // The stable HTTP code remains the sanitized fallback.
    }
    throw new Error(code);
  }
  if (response.status === 204) return null;
  return response.json();
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
  $(".sidebar").classList.remove("open");
  if (name === "hwpx") loadHwpx();
  if (name === "control" && hasAdminRole()) loadControlPlane();
  if (name === "dashboard" && state.health) renderDashboard(state.health);
  window.scrollTo({top: 0, behavior: "smooth"});
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
    toast("고정 Revision과 연결된 Item ID도 입력하세요.");
  } else if (value.startsWith("item_")) {
    $("#item-id").value = value;
    showView("item");
    toast("고정 Item Revision ID도 입력하세요.");
  } else if (HWPX_BUILD_PATTERN.test(value)) {
    selectHwpxBuild(value);
    showView("hwpx");
    loadHwpxBuild();
  } else {
    toast("지원되는 Workflow, Item 또는 HWPX Build ID를 입력하세요.");
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
  $("#metric-api").textContent = value.application_api || "UNAVAILABLE";
  $("#metric-observe").textContent = value.observability || "UNAVAILABLE";
}

function installRequestDraft() {
  $("#draft-analyze").addEventListener("click", analyzeDraft);
  $("#draft-save").addEventListener("click", saveDraft);
  $("#draft-submit").addEventListener("click", submitDraft);
}

async function analyzeDraft() {
  const message = $("#draft-message");
  showMessage(message, "요청을 구조화하고 있습니다.");
  try {
    const draft = await api("/request-drafts", {
      method: "POST",
      mutation: true,
      body: {original_request_text: $("#request-text").value},
    });
    state.draft = draft;
    fillDraft(draft);
    setStatus($("#draft-state"), "success", "✓", "검토 가능");
    showMessage(message, "Draft를 검토하세요. Source Intake 없이 일반 지식 모드로 바로 제출할 수 있습니다.", "success");
    $("#draft-save").disabled = false;
    $("#draft-submit").disabled = false;
  } catch (failure) {
    showMessage(message, `요청 분석 실패: ${failure.message}`, "error");
  }
}

function fillDraft(draft) {
  const form = $("#draft-form");
  for (const key of ["subject", "topic", "item_format", "task_type", "difficulty", "choice_count"]) {
    form.elements[key].value = draft[key];
  }
  form.elements.equation_required.checked = draft.equation_required;
  form.elements.image_required.checked = draft.image_required;
  form.elements.quality_profile.value = draft.quality_profile;
  form.elements.source_intake_batch_id.value = draft.source_intake_batch_id || "";
  $("#draft-id").textContent = draft.request_draft_id;
  $("#draft-sha").textContent = draft.original_request_sha256;
}

function draftUpdateBody() {
  const form = $("#draft-form");
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
  };
}

async function saveDraft() {
  if (!state.draft) return false;
  try {
    state.draft = await api(`/request-drafts/${encodeURIComponent(state.draft.request_draft_id)}`, {
      method: "PUT", mutation: true, body: draftUpdateBody(),
    });
    fillDraft(state.draft);
    showMessage($("#draft-message"), "Request Draft가 저장되었습니다.", "success");
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
  const key = `studio:${state.draft.request_draft_id}:${state.draft.original_request_sha256.slice(0, 16)}`;
  try {
    const result = await api(`/request-drafts/${encodeURIComponent(state.draft.request_draft_id)}/submissions`, {
      method: "POST", mutation: true, body: {idempotency_key: key},
    });
    const workflowId = result.command && result.command.resource_id;
    showMessage($("#draft-message"), result.replayed ? "동일 요청 결과를 안전하게 재표시했습니다." : "Workflow 생성 command가 접수되었습니다.", "success");
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
  if (!workflowId.startsWith("workflow_")) return toast("올바른 Workflow ID를 입력하세요.");
  stopWorkflowUpdates();
  try {
    const value = await api(`/workflows/${encodeURIComponent(workflowId)}`);
    state.workflow = value;
    renderWorkflow(value);
    $("#approval-workflow-id").value = workflowId;
    startWorkflowUpdates(workflowId);
  } catch (failure) {
    setStatus($("#workflow-state"), "danger", "!", "조회 실패");
    toast(`Workflow 조회 실패: ${failure.message}`);
  }
}

function renderWorkflow(bundle) {
  const workflow = bundle.workflow || {};
  const style = statusStyle(workflow.state);
  setStatus($("#workflow-state"), style[0], style[1], workflow.state || "UNKNOWN");
  renderDefinitionList($("#workflow-inspector"), {
    Workflow: workflow.workflow_id,
    상태: workflow.state,
    "현재 단계": workflow.current_step_key,
    ETag: bundle.etag,
    "Definition": `${workflow.definition_key || "-"}@${workflow.definition_version || "-"}`,
    "Updated UTC": workflow.updated_at,
  });
  renderStages(workflow, bundle.steps || []);
  renderTimeline(bundle.timeline || []);
  renderOperationalLog(bundle);
  $("#approval-etag").value = bundle.etag || "";
  renderApprovalSummary(bundle);
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
    const hwpxState = state.hwpxCapability?.state || "CAPABILITY 확인 필요";
    detail.textContent = completed.has(key) ? "완료" : key === current ? "현재 단계" : key === "hwpx" ? hwpxState : "대기";
    element.querySelector("span").textContent = completed.has(key) ? "✓" : String(index + 1);
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
    mark.textContent = statusStyle(event.state)[1];
    const content = document.createElement("div");
    content.className = "event-content";
    const title = document.createElement("strong");
    title.textContent = event.label;
    const stateLabel = document.createElement("small");
    stateLabel.textContent = event.state;
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
  renderDefinitionList($("#approval-summary"), {Workflow: workflow.workflow_id, 상태: workflow.state, "현재 단계": workflow.current_step_key, ETag: bundle.etag});
  const waiting = ["AWAITING_HUMAN_APPROVAL", "AWAITING_APPROVAL"].includes(workflow.state) || String(workflow.stage || "").includes("APPROVAL");
  setStatus($("#approval-state"), waiting ? "warning" : "neutral", waiting ? "◆" : "■", waiting ? "승인 대기" : workflow.state || "확인 필요");
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
    showMessage(message, `승인 command ${result.command_id || ""}가 접수되었습니다.`, "success");
    $("#workflow-id").value = workflowId;
    await loadWorkflow();
    showView("approval");
  } catch (failure) {
    showMessage(message, `승인 실패: ${failure.message}`, "error");
  }
}

function installItemPreview() {
  $("#item-load").addEventListener("click", loadItemPreview);
}

async function loadItemPreview() {
  const itemId = $("#item-id").value.trim();
  const revisionId = $("#revision-id").value.trim();
  try {
    const preview = await api(`/items/${encodeURIComponent(itemId)}/revisions/${encodeURIComponent(revisionId)}/preview`);
    renderItemPreview(preview);
  } catch (failure) {
    toast(`Item Preview 조회 실패: ${failure.message}`);
  }
}

function renderItemPreview(preview) {
  const style = statusStyle(preview.revision_state);
  setStatus($("#revision-state"), style[0], style[1], preview.revision_state);
  renderDefinitionList($("#item-inspector"), {Item: preview.item_id, Revision: preview.item_revision_id, Workflow: preview.workflow_id, "Content Pack": preview.content_pack_release_id, "EOM Template": preview.template_delivery_available ? "AVAILABLE" : "STRUCTURED CONTENT REQUIRED"});
  $("#structured-base-revision").value = preview.item_revision_id;
  $("#structured-revision-etag").value = preview.revision_etag;
  if (preview.template_delivery_available) $("#hwpx-revision-id").value = preview.item_revision_id;
  $("#preview-page-state").textContent = preview.preview_state;
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
    $("#hwpx-state-title").textContent = value.state === "READY" ? "HWPX Renderer 준비 완료" : value.state === "PREPARED_NOT_DEPLOYED" ? "HWPX Renderer 운영 배포 필요" : "HWPX Renderer 상태 확인 필요";
    $("#hwpx-message").textContent = value.message;
    $("#renderer-key").textContent = value.renderer_key;
    $("#renderer-version").textContent = `${value.renderer_version} / ${value.document_profile}`;
    $("#hwpx-build-state").textContent = value.build_available ? "AVAILABLE" : "NOT AVAILABLE";
    $("#hwpx-validation").textContent = value.detail_code;
    $("#hwpx-equations").textContent = value.native_equations ? "SUPPORTED" : "NOT READY";
    $("#hwpx-tables").textContent = value.native_tables ? "SUPPORTED" : "NOT READY";
    $("#hwpx-download").textContent = value.build_available ? "AFTER VALIDATION" : "NOT AVAILABLE";
    const [tone, icon] = statusStyle(value.state);
    setStatus($("#hwpx-state-badge"), tone, icon, value.state);
    setStatus($("#hwpx-inspector-badge"), tone, icon, value.state);
    $("#hwpx-step-state").textContent = value.state;
    $("#metric-hwpx").textContent = value.state;
    $("#hwpx-build-submit").disabled = !value.build_available;
  } catch (failure) {
    setStatus($("#hwpx-state-badge"), "danger", "!", "CAPABILITY BLOCKED");
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
  $("#hwpx-revision-id").addEventListener("input", renderRecentHwpxBuilds);
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
  $("#hwpx-download").textContent = "NOT AVAILABLE";
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
  if (!revision.startsWith("itemrev_")) return toast("Approved Item Revision ID를 입력하세요.");
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
    showMessage($("#hwpx-build-message"), "HWPX manager queue에 요청했습니다.", "success");
    await loadHwpxBuild();
  } catch (failure) {
    showMessage($("#hwpx-build-message"), `Build 요청 실패: ${failure.message}`, "error");
  }
}

async function loadHwpxBuild() {
  if (!state.hwpxBuildId) return;
  try {
    const value = await api(`/hwpx/builds/${encodeURIComponent(state.hwpxBuildId)}`);
    const [tone, icon] = statusStyle(value.state);
    setStatus($("#hwpx-job-badge"), tone, icon, value.state);
    $("#hwpx-resource-state").textContent = `${value.state} / ${value.validation_state}`;
    $("#hwpx-validation").textContent = value.validation_state;
    $("#hwpx-equations").textContent = value.native_equation_count === null ? "대기" : String(value.native_equation_count);
    $("#hwpx-tables").textContent = value.native_table_count === null ? "대기" : String(value.native_table_count);
    $("#hwpx-artifact-revision").textContent = value.output_artifact_revision_id || "-";
    $("#hwpx-completed-at").textContent = value.completed_at || "-";
    $("#hwpx-revision-id").value = value.item_revision_id;
    const download = $("#hwpx-download-link");
    download.hidden = !value.download_available;
    download.href = value.download_available ? `${API}/hwpx/builds/${encodeURIComponent(value.build_id)}/download` : "#";
    $("#hwpx-download").textContent = value.download_available ? "AVAILABLE" : "NOT AVAILABLE";
    window.clearTimeout(state.hwpxPollTimer);
    if (["REQUESTED", "RUNNING", "VALIDATING"].includes(value.state)) {
      state.hwpxPollTimer = window.setTimeout(loadHwpxBuild, 2000);
    }
    if (value.download_available) {
      showMessage($("#hwpx-build-message"), "검증된 HWPX를 다운로드할 수 있습니다.", "success");
    } else if (value.failure_code) {
      showMessage($("#hwpx-build-message"), `Build 실패: ${value.failure_code}`, "error");
    } else {
      showMessage($("#hwpx-build-message"), `Build 상태: ${value.state}`);
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
    const [accounts, presets] = await Promise.all([
      api("/admin/codex-accounts"),
      api("/admin/execution-presets"),
    ]);
    state.codexAccounts = accounts;
    state.executionPresets = presets;
    renderCodexAccounts(accounts);
    renderExecutionPresets(presets);
    showMessage($("#codex-account-message"), `${accounts.length}개 fixed binding · credential 비노출`, "success");
    showMessage($("#execution-preset-message"), `${presets.length}개 logical preset · immutable revision`, "success");
  } catch (failure) {
    showMessage($("#codex-account-message"), `Control Plane 조회 실패: ${failure.message}`, "error");
  }
}

function controlCard(title, stateValue) {
  const card = document.createElement("article");
  card.className = "control-card";
  const header = document.createElement("header");
  const heading = document.createElement("h3");
  heading.textContent = title;
  const badge = document.createElement("span");
  const [tone, icon] = statusStyle(stateValue);
  setStatus(badge, tone, icon, stateValue);
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
    const {card, details} = controlCard(`${account.slot_key} · ${account.account_label}`, account.state);
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
    const {card, details} = controlCard(preset.preset_key, preset.state);
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
    select.append(new Option(`${row.state} · ${row.build_id} · ${when}`, row.build_id));
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
  installNavigation();
  installRequestDraft();
  installWorkflow();
  installApproval();
  installItemPreview();
  installStructuredImport();
  installHwpx();
  installControlPlane();
  installExplorer();
  $("#logout").addEventListener("click", logout);
  await initializeSession();
  const restoredHwpx = restoreHwpxBuild();
  if (restoredHwpx) showView("hwpx");
  await Promise.all([loadHealth(), loadHwpx(), loadRecentHwpxBuilds()]);
  if (restoredHwpx) await loadHwpxBuild();
}

boot().catch(() => window.location.replace("/studio/login"));
