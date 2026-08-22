const API = "/studio/api/v1";
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
  acceptedIntakes: [],
  structuredSource: null,
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
  } else {
    toast("지원되는 Workflow 또는 Item ID를 입력하세요.");
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
  $("#draft-form").elements.source_intake_batch_id.addEventListener("change", () => {
    const selected = $("#draft-form").elements.source_intake_batch_id.value;
    $("#draft-submit").disabled = !state.draft || !selected;
  });
}

async function loadAcceptedIntakes(selectedId = null) {
  const select = $("#draft-form").elements.source_intake_batch_id;
  const values = await api("/content-intakes/accepted");
  if (!Array.isArray(values)) throw new Error("APPLICATION_API_RESPONSE_INVALID");
  state.acceptedIntakes = values;
  select.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = values.length ? "ACCEPTED intake를 선택하세요" : "사용 가능한 ACCEPTED intake가 없습니다";
  select.append(placeholder);
  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value.intake_batch_id;
    option.textContent = `${value.batch_name} · ${value.intake_batch_id}`;
    select.append(option);
  });
  select.value = selectedId || "";
  return values.length;
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
    const intakeCount = await loadAcceptedIntakes(draft.source_intake_batch_id);
    fillDraft(draft);
    setStatus($("#draft-state"), "success", "✓", "검토 가능");
    showMessage(message, intakeCount ? "Draft를 검토하고 ACCEPTED intake를 선택한 뒤 저장하세요." : "ACCEPTED source intake가 없어 Workflow를 제출할 수 없습니다.", intakeCount ? "success" : "error");
    $("#draft-save").disabled = false;
    $("#draft-submit").disabled = true;
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
    $("#draft-submit").disabled = !state.draft.source_intake_batch_id;
    return true;
  } catch (failure) {
    showMessage($("#draft-message"), `Draft 저장 실패: ${failure.message}`, "error");
    return false;
  }
}

async function submitDraft() {
  if (!state.draft) return;
  if (!(await saveDraft())) return;
  if (!state.draft.source_intake_batch_id) {
    showMessage($("#draft-message"), "ACCEPTED source intake를 선택하세요.", "error");
    return;
  }
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
    state.hwpxBuildId = command.resource_id;
    $("#hwpx-build-id").textContent = state.hwpxBuildId;
    $("#hwpx-build-refresh").disabled = false;
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
    const download = $("#hwpx-download-link");
    download.hidden = !value.download_available;
    download.href = value.download_available ? `${API}/hwpx/builds/${encodeURIComponent(value.build_id)}/download` : "#";
    $("#hwpx-download").textContent = value.download_available ? "AVAILABLE" : "NOT AVAILABLE";
    window.clearTimeout(state.hwpxPollTimer);
    if (["REQUESTED", "RUNNING", "VALIDATING"].includes(value.state)) {
      state.hwpxPollTimer = window.setTimeout(loadHwpxBuild, 2000);
    }
    if (value.failure_code) showMessage($("#hwpx-build-message"), `Build 실패: ${value.failure_code}`, "error");
  } catch (failure) {
    showMessage($("#hwpx-build-message"), `상태 조회 실패: ${failure.message}`, "error");
  }
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
  installExplorer();
  $("#logout").addEventListener("click", logout);
  await initializeSession();
  await Promise.all([loadHealth(), loadHwpx()]);
}

boot().catch(() => window.location.replace("/studio/login"));
