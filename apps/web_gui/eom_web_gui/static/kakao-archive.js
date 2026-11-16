// Presentation only: original messages, revisions and source authority belong to Catalog.
import {createKakaoStudents} from "./kakao-students.js";
import {createKakaoRooms} from "./kakao-rooms.js";
import {createKakaoManual} from "./kakao-manual.js";
const BASE = "/kakao-archive";
const ID = /^[a-z][a-z0-9_]{1,48}_[a-f0-9]{32}$/;
const TERMINAL_RUNS = new Set(["COMPLETED", "PARTIAL", "FAILED", "CANCELLED", "PAUSED", "AUTH_REQUIRED"]);
const ACTIVE_RUNS = new Set(["QUEUED", "INVENTORY", "COLLECTING", "RECONCILING"]);
const MAX_PAGE = 100;
const BINDING_ID = /^kakaobinding_[a-f0-9]{32}$/;
const POLICY_ID = /^kakaopolicyrev_[a-f0-9]{32}$/;
const DENIED_RESOURCE_CODES = new Set(["PERMISSION_DENIED", "KAKAO_ARCHIVE_PERMISSION_DENIED", "HTTP_403", "HTTP_404", "HTTP_410",
  "KAKAO_ARCHIVE_RESOURCE_NOT_FOUND", "KAKAO_ARCHIVE_RESOURCE_STALE", "API_PRECONDITION_FAILED"]);

function bootstrapBinding(value) {
  const revision = value?.policy_revision, policy = revision?.policy;
  if (value?.schema_version !== "kakao-source-binding/1.0" || !BINDING_ID.test(value.source_binding_id || "") ||
      !["DRAFT", "RETIRED"].includes(value.state) || value.capability_state !== "NOT_VERIFIED" || value.schedule_enabled !== false ||
      typeof value.display_name !== "string" || !value.display_name.trim() || [...value.display_name].length > 128 ||
      !Number.isInteger(value.resource_version) || value.resource_version < 1 || value.resource_version > 2147483647 ||
      revision?.source_binding_id !== value.source_binding_id || !POLICY_ID.test(revision?.policy_revision_id || "") ||
      !Number.isInteger(policy?.interval_minutes) || policy.interval_minutes < 60 || policy.interval_minutes > 10080 ||
      policy.include_images !== true || !["unknown", "Asia/Seoul"].includes(policy.source_timezone) || policy.question_rule_version !== "turn_v1") {
    throw new Error("채널 연결 준비 정보를 확인하지 못했습니다.");
  }
  return value;
}

function identifier(value) {
  if (typeof value !== "string" || !ID.test(value)) throw new Error("자료의 연결 정보를 확인하지 못했습니다.");
  return encodeURIComponent(value);
}

function pageValues(value) {
  if (!value || !Array.isArray(value.items) || value.items.length > MAX_PAGE ||
      !(value.next_cursor === null || (typeof value.next_cursor === "string" && value.next_cursor.length <= 2048))) {
    throw new Error("목록의 형식을 확인하지 못했습니다.");
  }
  return value;
}

function date(value) {
  const parsed = value ? new Date(value) : null;
  return parsed && Number.isFinite(parsed.getTime())
    ? parsed.toLocaleString("ko-KR", {timeZone: "Asia/Seoul", dateStyle: "medium", timeStyle: "short"})
    : "시각 확인 필요";
}

export function createKakaoArchive({document, api, setStateStatus, explainError = () => "잠시 후 다시 확인해 주세요.",
  container = null, pollMilliseconds = 8000, schedule = setTimeout, unschedule = clearTimeout}) {
  let root = container, owner = null, active = false, installed = false;
  let generation = 0, listGeneration = 0, questionListGeneration = 0, detailGeneration = 0, runGeneration = 0, timer = null;
  let permissions = new Set(), roles = new Set(), binding = null, run = null, currentRoom = null;
  let collectionIntent = null, collectionPending = false, bindingRows = new Map();
  let bindingIntent = null, bindingPending = false;
  let questionRows = new Map(), packetRows = new Map();
  const nodes = {};
  const students = createKakaoStudents({document, api, explainError});
  const manual = createKakaoManual({document, api, explainError, schedule, unschedule});
  const rooms = createKakaoRooms({document, api, explainError, onSelect: row => {
    if (!active || !readReady() || row.source_binding_id !== binding?.source_binding_id) return;
    const token = generation; currentRoom = row.room_id; clearDetails(); questionRows.clear();
    empty(nodes.questions, "이 대화방의 질문을 불러오고 있습니다.");
    void loadQuestions(token).catch(error => { if (live(token)) message(explainError(error), true); });
  }});

  function node(tag, text, className = "") {
    const result = document.createElement(tag);
    if (text !== undefined) result.textContent = text;
    if (className) result.className = className;
    return result;
  }
  function button(text, callback, className = "button quiet") {
    const result = node("button", text, className); result.type = "button";
    result.addEventListener("click", callback); return result;
  }
  function message(text, error = false) {
    nodes.message.textContent = text;
    nodes.message.className = `form-message${error ? " error" : ""}`;
  }
  function status(value) {
    const badge = node("span", "상태 확인 필요", "status-badge");
    if (setStateStatus) setStateStatus(badge, "kakao_archive", value);
    else badge.dataset.rawState = value;
    return badge;
  }
  function allowed(key) { return permissions.has(`kakao_archive:${key}`); }
  function mayManage() { return owner !== null && roles.has("ADMIN") && allowed("collect"); }
  // Capture/export controls still require verified capabilities; accepted question
  // history uses its separate current-authorized read path below.
  function archiveReady() { return binding?.capability_state === "VERIFIED" && binding?.state === "ACTIVE" && binding?.allowed_actions?.includes("READ_ARCHIVE"); }
  // Existing accepted content has its own current authorization. A channel which
  // cannot currently collect may still have readable history; backend ACLs decide.
  function readReady() { return allowed("read") && binding && ["DRAFT", "ACTIVE"].includes(binding.state); }
  function live(token) { return active && owner !== null && token === generation; }
  function stopTimer() { if (timer !== null) unschedule(timer); timer = null; }
  function clearDetails() {
    detailGeneration++;
    nodes.detail.replaceChildren(node("p", "질문을 선택하면 원문과 사진을 확인할 수 있습니다.", "empty-state"));
  }
  function clearSelection() {
    binding = null; run = null; currentRoom = null; runGeneration++; questionListGeneration++;
    void rooms.setBinding(null); questionRows.clear(); packetRows.clear();
    void manual.setBinding(null);
    nodes.connection.replaceChildren(); nodes.run.replaceChildren();
    nodes.questions.replaceChildren(); nodes.packets.replaceChildren();
    clearDetails(); stopTimer();
  }
  function clearPrivateView() {
    clearSelection(); bindingRows.clear(); nodes.bindings.replaceChildren();
    nodes.bindingName.value = bindingIntent?.kind === "CREATE" && !bindingIntent.receipt ? bindingIntent.body.display_name : "";
    syncBootstrapControls();
    message(owner ? "연결을 선택해 주세요." : "로그인 후 학생 질문을 열어 주세요.");
  }
  function technicalDetails(entries) {
    const details = node("details", undefined, "kakao-technical");
    details.append(node("summary", "기술 정보"));
    const list = node("dl");
    for (const [label, value] of entries) {
      if (value) list.append(node("dt", label), node("dd", String(value)));
    }
    details.append(list); return details;
  }
  function empty(target, text) { target.replaceChildren(node("p", text, "empty-state")); }

  function install() {
    if (installed) return;
    root ||= document.querySelector("#kakao-archive-root");
    if (!root) throw new Error("학생 질문 화면이 준비되지 않았습니다.");
    installed = true; root.classList.add("kakao-archive");
    const toolbar = node("div", undefined, "kakao-toolbar");
    nodes.refresh = button("새로고침", () => void Promise.all([refresh(), students.refresh()]));
    const heading = node("h1", "KakaoTalk"); heading.id = "kakao-archive-title";
    toolbar.append(heading, nodes.refresh);
    nodes.message = node("p", "로그인 후 학생 질문을 열어 주세요.", "form-message");
    nodes.message.setAttribute("role", "status"); nodes.message.setAttribute("aria-live", "polite");
    nodes.bootstrap = node("form", undefined, "kakao-bootstrap");
    nodes.bootstrap.setAttribute("aria-label", "채널 연결 준비");
    const nameLabel = node("label", "채널 이름");
    nodes.bindingName = node("input"); nodes.bindingName.type = "text"; nodes.bindingName.maxLength = 256;
    nodes.bindingName.required = true; nodes.bindingName.autocomplete = "off"; nameLabel.append(nodes.bindingName);
    nodes.createBinding = node("button", "연결 준비 저장", "button secondary"); nodes.createBinding.type = "submit";
    nodes.bootstrap.append(nameLabel, nodes.createBinding,
      node("p", "채널 이름만 저장합니다. 아직 카카오에 로그인하거나 대화를 가져오지 않습니다.", "muted-label"));
    nodes.bootstrap.addEventListener("submit", event => { event.preventDefault(); void createBinding(); });
    nodes.bindingRecovery = node("div", undefined, "kakao-binding-recovery");
    const bindingLabel = node("label", "카카오 채널", "kakao-binding");
    nodes.bindings = node("select"); nodes.bindings.setAttribute("aria-label", "카카오 채널");
    nodes.bindings.addEventListener("change", () => void selectBinding(nodes.bindings.value));
    bindingLabel.append(nodes.bindings);
    nodes.connection = node("div", undefined, "kakao-connection");
    nodes.run = node("section", undefined, "kakao-run"); nodes.run.setAttribute("aria-label", "수집 진행");
    const work = node("div", undefined, "kakao-workspace");
    for (const [name, title] of [["rooms", "대화방"], ["questions", "질문 목록"], ["detail", "질문 검토"]]) {
      const section = node("section", undefined, `kakao-${name}`);
      section.setAttribute("aria-label", title); section.append(node("h3", title));
      nodes[name] = node("div"); nodes[name].dataset.kakao = name; section.append(nodes[name]); work.append(section);
    }
    const publications = node("section", undefined, "kakao-publications");
    publications.setAttribute("aria-label", "만든 자료"); publications.append(node("h3", "만든 자료"));
    nodes.packets = node("div"); publications.append(nodes.packets);
    nodes.students = node("section"); students.install(nodes.students);
    nodes.manual = node("section"); manual.install(nodes.manual);
    rooms.install(nodes.rooms);
    root.replaceChildren(toolbar, nodes.message, nodes.bootstrap, nodes.bindingRecovery, bindingLabel, nodes.connection, nodes.manual, nodes.students, nodes.run, work, publications);
    clearDetails(); syncBootstrapControls();
  }

  function syncBootstrapControls() {
    if (!installed) return;
    nodes.bootstrap.hidden = !mayManage();
    nodes.bindingName.disabled = bindingPending || (bindingIntent?.kind === "CREATE" && !bindingIntent.receipt);
    nodes.createBinding.disabled = !mayManage() || bindingPending || (bindingIntent?.kind === "RETIRE" && !bindingIntent.receipt);
    nodes.createBinding.textContent = bindingIntent?.kind === "CREATE" && !bindingIntent.receipt ? "같은 준비 요청 확인" : "연결 준비 저장";
    const retire = nodes.connection.querySelector('[data-kakao="retire"]');
    if (retire) retire.disabled = !mayManage() || bindingPending || binding?.state !== "DRAFT";
    nodes.bindingRecovery.replaceChildren();
    const intent = bindingIntent;
    if (active && mayManage() && intent?.kind === "RETIRE" && !intent.receipt) {
      const retry = button("같은 해제 요청 확인", () => {
        if (active && mayManage() && !bindingPending && bindingIntent === intent) void mutateBinding(intent.kind, intent.path, intent.body, intent.etag);
      });
      retry.disabled = bindingPending;
      nodes.bindingRecovery.append(node("p", "앞선 해제 요청의 처리 여부를 같은 요청으로 확인합니다.", "form-message"), retry);
    }
  }

  async function createBinding() {
    if (!active || !mayManage() || bindingPending) return;
    const name = nodes.bindingName.value.trim();
    if (!name || [...name].length > 128 || /[\u0000-\u001f\u007f]/.test(name)) { message("채널 이름을 확인해 주세요.", true); return; }
    const body = {schema_version: "kakao-binding-create/1.0", action: "CREATE", display_name: name,
      policy: {interval_minutes: 1440, include_images: true, source_timezone: "unknown", question_rule_version: "turn_v1"}};
    await mutateBinding("CREATE", `${BASE}/source-bindings`, body);
  }

  async function retireBinding(selected, token) {
    if (!live(token) || !mayManage() || binding !== selected || selected.state !== "DRAFT" || bindingPending) return;
    const check = nodes.connection.querySelector('[data-kakao="retire-confirm"]');
    if (!check?.checked) { message("연결 준비를 해제하려면 확인란을 먼저 선택해 주세요.", true); return; }
    const value = bootstrapBinding(selected);
    await mutateBinding("RETIRE", `${BASE}/source-bindings/${identifier(value.source_binding_id)}/commands`, {
      schema_version: "kakao-binding-command/1.0", action: "RETIRE",
      parent_policy_revision_id: value.policy_revision.policy_revision_id, expected_resource_version: value.resource_version,
    }, `"v${value.resource_version}"`);
  }

  async function mutateBinding(kind, path, body, etag = null) {
    const signature = JSON.stringify({path, body, etag}), capturedOwner = owner, token = generation;
    if (bindingIntent && !bindingIntent.receipt && bindingIntent.signature !== signature) {
      message("앞선 연결 요청의 처리 여부를 먼저 확인해 주세요. 같은 요청을 다시 확인할 수 있습니다.", true); return;
    }
    if (!bindingIntent || bindingIntent.signature !== signature) bindingIntent = {
      kind, signature, body, path, etag, targetId: kind === "RETIRE" ? binding?.source_binding_id : null,
      key: `kakao-binding-${globalThis.crypto.randomUUID()}`, receipt: null,
    };
    const intent = bindingIntent;
    if (intent.receipt) { await showMutatedBinding(intent.receipt.binding, token); return; }
    bindingPending = true; syncBootstrapControls(); message("연결 요청의 처리 여부를 확인하고 있습니다.");
    try {
      const headers = {"Idempotency-Key": intent.key}; if (etag) headers["If-Match"] = etag;
      const result = await api(path, {method: "POST", mutation: true, headers, body: intent.body});
      if (owner !== capturedOwner || bindingIntent !== intent) return;
      const value = bootstrapBinding(result?.binding);
      if (typeof result.replayed !== "boolean" || (kind === "CREATE" && value.state !== "DRAFT") ||
          (kind === "RETIRE" && (value.state !== "RETIRED" || value.source_binding_id !== intent.targetId))) {
        throw new Error("연결 요청의 결과를 확인하지 못했습니다.");
      }
      intent.receipt = result;
      if (live(token)) await showMutatedBinding(value, token);
    } catch (error) {
      if (live(token)) {
        if (["API_PRECONDITION_FAILED", "KAKAO_ARCHIVE_PRECONDITION_FAILED", "KAKAO_ARCHIVE_BINDING_RETIRED",
          "PERMISSION_DENIED", "KAKAO_ARCHIVE_PERMISSION_DENIED", "HTTP_403", "HTTP_412"].includes(error?.code)) {
          if (bindingIntent === intent) bindingIntent = null;
          clearSelection(); message(`연결 상태나 권한이 변경됐습니다. 새로고침한 뒤 다시 확인해 주세요. ${explainError(error)}`, true);
        } else message(`처리 여부를 확인하지 못했습니다. 같은 요청으로 다시 확인해 주세요. ${explainError(error)}`, true);
      }
    } finally {
      if (bindingIntent === intent || (owner === capturedOwner && bindingIntent === null)) bindingPending = false;
      if (owner === capturedOwner) syncBootstrapControls();
    }
  }

  async function showMutatedBinding(value, token) {
    if (!live(token)) return;
    bindingRows.set(value.source_binding_id, value);
    if (![...nodes.bindings.options].some(option => option.value === value.source_binding_id)) {
      const option = node("option", value.display_name); option.value = value.source_binding_id; nodes.bindings.append(option);
    }
    nodes.bindingName.value = "";
    await selectBinding(value.source_binding_id);
  }

  async function refresh() {
    if (!installed || !active || !owner) return;
    if (!allowed("read")) { clearPrivateView(); message("학생 질문을 볼 수 있는 권한이 없습니다.", true); return; }
    const token = generation, request = ++listGeneration;
    nodes.refresh.disabled = true;
    message("연결을 확인하고 있습니다.");
    try {
      const page = pageValues(await api(`${BASE}/source-bindings`));
      if (!live(token) || request !== listGeneration) return;
      const rows = new Map();
      for (const value of page.items) {
        if (!BINDING_ID.test(value.source_binding_id || "")) throw new Error("채널 연결 정보를 확인하지 못했습니다.");
        rows.set(value.source_binding_id, value);
      }
      bindingRows = rows;
      nodes.bindings.replaceChildren(node("option", "채널 선택")); nodes.bindings.firstChild.value = "";
      for (const value of rows.values()) {
        const option = node("option", value.display_name); option.value = value.source_binding_id;
        nodes.bindings.append(option);
      }
      if (page.next_cursor) message("연결 목록 일부만 표시했습니다. 현재 운영 범위의 채널을 확인해 주세요.");
      if (binding && rows.has(binding.source_binding_id)) {
        const selected = binding.source_binding_id; nodes.bindings.value = selected;
        await selectBinding(selected);
      } else {
        clearSelection();
        message(rows.size ? "채널을 선택하면 대화와 질문을 확인할 수 있습니다." : "아직 연결된 채널이 없습니다. 관리자에게 채널 연결을 요청해 주세요.");
      }
    } catch (error) {
      if (live(token) && request === listGeneration) {
        // Failed reads are not an empty archive or proof that a previous source is still authorized.
        clearPrivateView(); message(`연결을 확인하지 못했습니다. ${explainError(error)}`, true);
      }
    } finally { if (live(token) && request === listGeneration) nodes.refresh.disabled = false; }
  }

  async function selectBinding(value) {
    if (!active || !owner || !allowed("read")) return;
    generation++; listGeneration++; clearSelection();
    const row = bindingRows.get(value);
    if (!row) return;
    const token = generation;
    message("채널 정보를 불러오고 있습니다.");
    try {
      const detail = await api(`${BASE}/source-bindings/${identifier(value)}`);
      if (!live(token)) return;
      if (detail.source_binding_id !== value) throw new Error("다른 채널 정보가 반환됐습니다.");
      if (detail.capability_state === "NOT_VERIFIED") bootstrapBinding(detail);
      else if (detail.capability_state !== "VERIFIED" || detail.state !== "ACTIVE" || !detail.allowed_actions?.includes("READ_ARCHIVE")) {
        throw new Error("지원하지 않는 채널 연결 상태입니다.");
      }
      binding = detail; nodes.bindings.value = value;
      await rooms.setBinding(detail);
      await manual.setBinding(detail);
      if (!live(token)) return;
      nodes.connection.replaceChildren(node("strong", detail.display_name), status(detail.state));
      if (!archiveReady()) {
        const retired = detail.state === "RETIRED";
        nodes.connection.append(node("p", retired ? "해제된 연결 준비입니다. 보관된 이력은 유지됩니다." : "연결 이름을 저장했습니다. 카카오 로그인과 대상 채널 확인은 아직 준비되지 않았습니다. 자동 수집하지 않습니다."));
        empty(nodes.questions, "대화를 수집한 뒤 질문을 확인할 수 있습니다.");
        empty(nodes.packets, "질문을 확인한 뒤 PDF 자료를 만들 수 있습니다.");
        if (!retired && mayManage()) {
          const label = node("label", undefined, "kakao-retire-confirm"), check = node("input");
          check.type = "checkbox"; check.dataset.kakao = "retire-confirm";
          label.append(check, node("span", "이 연결 준비를 해제합니다. 보관 이력은 삭제하지 않습니다."));
          const retire = button("연결 준비 해제", () => void retireBinding(detail, token)); retire.dataset.kakao = "retire";
          nodes.connection.append(label, retire);
        }
        nodes.connection.append(technicalDetails([["연결", value], ["설정 버전", detail.resource_version], ["수집 정책", detail.policy_revision.policy_revision_id]]));
        syncBootstrapControls(); message(retired ? "연결 준비를 해제했습니다." : "연결 준비만 저장된 상태입니다. 대화 수집은 아직 시작하지 않았습니다.");
        if (!retired) {
          try { await loadQuestions(token); }
          catch (error) { if (live(token)) { empty(nodes.questions, "질문 목록을 불러오지 못했습니다."); message(explainError(error), true); } }
        }
        return;
      }
      const collect = button("전체 다시 수집", () => void collectAll());
      collect.dataset.kakao = "collect";
      collect.disabled = collectionPending || !allowed("collect") || !detail.allowed_actions?.includes("COLLECT");
      nodes.connection.append(collect);
      if (collectionIntent?.bindingId === value && !collectionIntent.receipt) {
        collect.textContent = "같은 수집 요청 확인";
      }
      nodes.connection.append(technicalDetails([["연결", value], ["수집 정책", detail.collection_policy_revision_id]]));
      await Promise.all([loadQuestions(token), loadPackets(token)]);
      if (live(token)) {
        message("원문을 확인한 뒤 학생과 질문 범위를 검토해 주세요.");
        if (detail.latest_run_id) await observeRun(detail.latest_run_id, token);
      }
    } catch (error) { if (live(token)) { clearSelection(); message(`채널을 열지 못했습니다. ${explainError(error)}`, true); } }
    finally { if (live(token)) nodes.refresh.disabled = false; }
  }

  async function collectAll() {
    if (!active || !owner || !archiveReady() || !allowed("collect") || collectionPending || !binding.allowed_actions?.includes("COLLECT")) return;
    const token = generation, captured = binding, capturedOwner = owner;
    const body = {schema_version: "kakao-archive-collection-create/1.0", source_binding_id: captured.source_binding_id,
      mode: "REPEAT", collection_policy_revision_id: captured.collection_policy_revision_id};
    try { identifier(body.collection_policy_revision_id); }
    catch (error) { message(error.message, true); return; }
    const signature = JSON.stringify(body);
    if (collectionIntent && !collectionIntent.receipt && collectionIntent.signature !== signature) {
      message("앞선 수집 요청의 접수 여부를 먼저 확인해 주세요. 다른 요청을 겹쳐 만들지 않습니다.", true); return;
    }
    if (!collectionIntent || collectionIntent.signature !== signature) {
      collectionIntent = {bindingId: captured.source_binding_id, signature, key: `kakao-collect-${globalThis.crypto.randomUUID()}`, receipt: null};
    }
    const intent = collectionIntent;
    if (intent.receipt) { await observeRun(intent.receipt.resource_id, token); return; }
    collectionPending = true;
    const collect = nodes.connection.querySelector('[data-kakao="collect"]'); if (collect) collect.disabled = true;
    message("수집 요청의 접수 여부를 확인하고 있습니다.");
    try {
      const reply = await api(`${BASE}/collection-runs`, {method: "POST", mutation: true, body,
        headers: {"Idempotency-Key": intent.key}});
      if (owner !== capturedOwner || collectionIntent !== intent) return;
      if (reply.resource_type !== "kakao_collection_run" || !["ACCEPTED", "COMPLETED"].includes(reply.status)) throw new Error("수집 접수 정보를 확인하지 못했습니다.");
      identifier(reply.resource_id); intent.receipt = reply;
      if (!live(token)) return;
      message("수집 요청을 접수했습니다. 완료 여부는 아래 진행 상태에서 확인할 수 있습니다.");
      await observeRun(reply.resource_id, token);
    } catch (error) {
      if (live(token)) message(`접수 여부를 확인하지 못했습니다. 같은 요청으로 다시 확인할 수 있습니다. ${explainError(error)}`, true);
    } finally {
      if (collectionIntent === intent) collectionPending = false;
      if (active && owner === capturedOwner && collectionIntent === intent && binding?.source_binding_id === intent.bindingId) {
        const currentButton = nodes.connection.querySelector('[data-kakao="collect"]');
        if (currentButton) {
          currentButton.disabled = !allowed("collect") || !binding.allowed_actions?.includes("COLLECT");
          currentButton.textContent = intent.receipt ? "수집 상태 확인" : "같은 수집 요청 확인";
        }
      }
    }
  }

  async function observeRun(runId, token = generation) {
    if (!live(token) || !allowed("read") || !archiveReady()) return;
    stopTimer();
    const request = ++runGeneration;
    try {
      const value = await api(`${BASE}/collection-runs/${identifier(runId)}`);
      if (!live(token) || request !== runGeneration) return;
      if (value.run_id !== runId || value.source_binding_id !== binding?.source_binding_id) throw new Error("수집 연결 정보가 다릅니다.");
      run = value; nodes.run.replaceChildren(node("h3", "수집 진행"), status(value.state));
      const counts = value.counters || {};
      nodes.run.append(node("p", `대화방 ${counts.rooms_exported ?? "?"} / ${counts.rooms_discovered ?? "?"}개 · 사진 ${counts.attachment_files_downloaded ?? "?"} / ${counts.attachment_files_discovered ?? "?"}개`));
      if (value.coverage?.inventory_complete !== true) nodes.run.append(node("p", "전체 방 목록이 확인되지 않았습니다. 보관된 자료만 열람할 수 있습니다.", "form-message"));
      if (value.state === "AUTH_REQUIRED") nodes.run.append(node("p", "카카오 로그인이 필요합니다. 이미 받은 자료는 보관되어 있습니다."));
      if (value.error_code) nodes.run.append(technicalDetails([["확인 코드", value.error_code]]));
      nodes.run.append(button("상태 확인", () => void observeRun(runId, token)));
      if (["COMPLETED", "PARTIAL", "FAILED", "CANCELLED"].includes(value.state) && allowed("collect") && binding.allowed_actions?.includes("COLLECT")) {
        nodes.run.append(button("새로 수집하기", () => {
          if (!live(token) || run?.run_id !== runId || collectionPending) return;
          collectionIntent = null; void collectAll();
        }));
      }
      if (ACTIVE_RUNS.has(value.state)) timer = schedule(() => void observeRun(runId, token), pollMilliseconds);
      else if (!TERMINAL_RUNS.has(value.state)) message("수집 상태를 확인해야 합니다. 자동 새로고침을 멈췄습니다.", true);
    } catch (error) { if (live(token) && request === runGeneration) message(`수집 상태를 확인하지 못했습니다. ${explainError(error)}`, true); }
  }


  async function loadQuestions(token, cursor = null) {
    const roomId = currentRoom, request = ++questionListGeneration;
    const query = new URLSearchParams({source_binding_id: binding.source_binding_id, limit: "50"});
    if (roomId) query.set("room_id", roomId);
    if (cursor) query.set("cursor", cursor);
    const page = pageValues(await api(`${BASE}/questions?${query}`));
    if (!live(token) || currentRoom !== roomId || request !== questionListGeneration) return;
    if (!cursor) questionRows.clear();
    for (const row of page.items) {
      identifier(row.question_id); identifier(row.question_revision_id); identifier(row.room_id);
      if (row.source_binding_id !== binding.source_binding_id || (roomId && row.room_id !== roomId)) throw new Error("질문 목록의 소속이 다릅니다.");
      questionRows.set(row.question_id, row);
    }
    nodes.questions.replaceChildren();
    for (const row of questionRows.values()) {
      const entry = node("div", undefined, "kakao-list-row");
      entry.append(button(`${row.student?.display_name || "학생 미연결"}의 질문`, () => {
        if (live(token) && currentRoom === roomId && request === questionListGeneration) void openQuestion(row.question_id, row.question_revision_id);
      }),
        node("small", date(row.first_student_at_utc)), status(row.review_state)); nodes.questions.append(entry);
    }
    if (!questionRows.size) empty(nodes.questions, "확인할 질문이 없습니다. 대화 수집과 학생 연결 상태를 확인해 주세요.");
    more(nodes.questions, page.next_cursor, next => loadQuestions(token, next), token);
  }

  function more(target, cursor, fetchPage, token) {
    if (!cursor) return;
    const next = button("더 보기", async () => {
      if (next.disabled || !live(token)) return;
      next.disabled = true;
      try { await fetchPage(cursor); }
      catch (error) { if (live(token)) { message(explainError(error), true); next.disabled = false; } }
    }); target.append(next);
  }

  async function openQuestion(questionId, revisionId) {
    if (!active || !owner || !readReady()) return;
    const token = generation, request = ++detailGeneration;
    empty(nodes.detail, "질문을 불러오고 있습니다.");
    try {
      const query = new URLSearchParams({source_binding_id: binding.source_binding_id});
      const roomId = questionRows.get(questionId)?.room_id;
      if (roomId) query.set("room_id", roomId);
      const value = await api(`${BASE}/questions/${identifier(questionId)}/revisions/${identifier(revisionId)}?${query}`);
      if (!live(token) || request !== detailGeneration) return;
      const question = value.question;
      if (value.schema_version !== "kakao-question-view/1.0" || question?.question_id !== questionId || question.question_revision_id !== revisionId || question.source_binding_id !== binding.source_binding_id || (roomId && question.room_id !== roomId) || !Array.isArray(value.ordered_blocks)) throw new Error("질문 연결 정보가 다릅니다.");
      nodes.detail.replaceChildren(node("h4", question.student?.display_name || "학생 연결 필요"),
        node("p", date(question.first_student_at_utc), "muted-label"), status(question.review_state));
      for (const block of value.ordered_blocks) {
        if (block.kind === "TEXT" && typeof block.text === "string") nodes.detail.append(node("p", block.text, "kakao-message-text"));
        else if (block.kind === "IMAGE") {
          if (block.availability !== "available") {
            nodes.detail.append(node("p", "미확보 사진 · 원본을 확인하기 전에는 완성 자료에 넣을 수 없습니다.", "form-message error")); continue;
          }
          const image = node("img"); image.alt = "질문에 첨부된 사진"; image.loading = "lazy";
          const scope = new URLSearchParams({source_binding_id: question.source_binding_id, room_id: question.room_id});
          image.src = `/studio/api/v1${BASE}/questions/${identifier(questionId)}/revisions/${identifier(revisionId)}/images/${identifier(block.attachment_id)}?${scope}`;
          image.addEventListener("error", () => {
            if (live(token) && request === detailGeneration) image.replaceWith(node("p", "사진을 불러오지 못했습니다. 원본 연결 상태를 확인해 주세요.", "form-message error"));
          }); nodes.detail.append(image);
        } else throw new Error("지원하지 않는 질문 구성입니다.");
      }
      if (value.review_reasons?.length) nodes.detail.append(node("p", "학생·질문 경계 또는 사진 연결에 확인할 사항이 있습니다.", "form-message"));
      if (allowed("edit")) installQuestionReview(question, token, request);
      nodes.detail.append(technicalDetails([["질문", questionId], ["보관된 버전", revisionId]]));
    } catch (error) {
      if (live(token) && request === detailGeneration) { empty(nodes.detail, "질문을 열지 못했습니다."); message(explainError(error), true); }
    }
  }

  function installQuestionReview(question, token, request) {
    const form = node("form", undefined, "kakao-question-review"); form.setAttribute("aria-label", "질문 확인 저장");
    const label = node("label", "확인 메모"), reason = node("textarea"); reason.rows = 2;
    reason.placeholder = "확인한 내용이나 제외하는 이유를 적어 주세요."; label.append(reason);
    const boundaryLabel = node("label", undefined, "kakao-review-check"), boundary = node("input"); boundary.type = "checkbox";
    boundaryLabel.append(boundary, node("span", "이 내용이 하나의 질문인 것을 확인했습니다."));
    const note = node("p", "확인 상태만 저장합니다. 원문과 사진은 바뀌지 않습니다.", "muted-label"); note.setAttribute("role", "status");
    const confirm = button("질문 확인 완료", () => void save("CONFIRM"), "button secondary");
    const exclude = button("출력에서 제외", () => void save("EXCLUDE"));
    form.append(label, boundaryLabel, confirm, exclude, note); nodes.detail.append(form);
    let intent = null, pending = false;
    const current = () => live(token) && request === detailGeneration && nodes.detail.contains(form) && allowed("edit");
    function controls() {
      reason.disabled = pending || intent !== null; boundary.disabled = pending || intent !== null;
      confirm.disabled = pending || (intent ? intent.action !== "CONFIRM" : !boundary.checked);
      exclude.disabled = pending || (intent !== null && intent.action !== "EXCLUDE");
      confirm.textContent = intent?.action === "CONFIRM" ? "같은 확인 저장 요청 확인" : "질문 확인 완료";
      exclude.textContent = intent?.action === "EXCLUDE" ? "같은 제외 요청 확인" : "출력에서 제외";
    }
    boundary.addEventListener("change", controls); form.addEventListener("submit", event => event.preventDefault()); controls();
    async function save(action) {
      if (!current() || pending || (intent && intent.action !== action)) return;
      if (!intent) {
        const memo = reason.value.trim();
        if (!memo || [...memo].length > 1000 || (action === "CONFIRM" && !boundary.checked)) { note.textContent = "확인 메모를 1,000자 이내로 적고, 질문 범위를 확인해 주세요."; return; }
        intent = {action, key: `kakao-review-${globalThis.crypto.randomUUID()}`,
          body: {schema_version: "kakao-question-edit/1.0", action, parent_revision_id: question.question_revision_id, reason: memo,
            ...(action === "CONFIRM" ? {boundary_confirmed: true} : {})}};
      }
      pending = true; controls(); note.textContent = "확인 내용을 저장하고 있습니다.";
      try {
        const query = new URLSearchParams({source_binding_id: question.source_binding_id, room_id: question.room_id});
        const result = await api(`${BASE}/questions/${identifier(question.question_id)}/review?${query}`, {method: "POST", mutation: true,
          headers: {"Idempotency-Key": intent.key, "If-Match": `"v${question.resource_version}"`}, body: intent.body});
        if (!current()) return;
        const saved = result.question;
        if (!saved || saved.question_id !== question.question_id || saved.source_binding_id !== question.source_binding_id || saved.room_id !== question.room_id || saved.previous_revision_id !== question.question_revision_id || saved.resource_version !== question.resource_version + 1) throw new Error("저장한 질문 버전을 확인하지 못했습니다.");
        await loadQuestions(token);
        if (current()) await openQuestion(saved.question_id, saved.question_revision_id);
      } catch (error) {
        if (current()) note.textContent = `저장 결과를 확인하지 못했습니다. 같은 요청으로 다시 확인할 수 있습니다. ${explainError(error)}`;
      } finally { pending = false; if (current()) controls(); }
    }
  }

  async function loadPackets(token, cursor = null) {
    const query = new URLSearchParams({source_binding_id: binding.source_binding_id, limit: "50"});
    if (cursor) query.set("cursor", cursor);
    const page = pageValues(await api(`${BASE}/question-packets?${query}`));
    if (!live(token)) return;
    if (!cursor) packetRows.clear();
    for (const row of page.items) { identifier(row.packet_id); identifier(row.current_revision_id); packetRows.set(row.packet_id, row); }
    nodes.packets.replaceChildren();
    for (const row of packetRows.values()) {
      const entry = node("div", undefined, "kakao-packet");
      entry.append(node("strong", row.title), node("span", `${row.question_count}개 질문`));
      entry.append(button("학생별 PDF 보기", () => void openExports(row.current_revision_id, entry, token))); nodes.packets.append(entry);
    }
    if (!packetRows.size) empty(nodes.packets, "아직 만든 자료가 없습니다.");
    more(nodes.packets, page.next_cursor, next => loadPackets(token, next), token);
  }

  async function openExports(packetRevisionId, target, token) {
    if (!live(token) || !allowed("read") || !archiveReady()) return;
    const query = new URLSearchParams({source_binding_id: binding.source_binding_id, packet_revision_id: packetRevisionId, limit: "50"});
    const stamp = String(Number(target.dataset.request || 0) + 1); target.dataset.request = stamp;
    try {
      const page = pageValues(await api(`${BASE}/exports?${query}`));
      if (!live(token) || target.dataset.request !== stamp || !root.contains(target)) return;
      target.querySelector(".kakao-exports")?.remove();
      const list = node("div", undefined, "kakao-exports");
      for (const item of page.items) {
        if (item.packet_revision_id !== packetRevisionId || item.source_binding_id !== binding.source_binding_id) throw new Error("자료 연결 정보가 다릅니다.");
        if (!["DRAFT", "FINAL"].includes(item.mode)) throw new Error("자료의 발행 구분을 확인하지 못했습니다.");
        const row = node("div", undefined, "kakao-export");
        row.append(node("strong", item.student_display_name), status(item.state), node("span", item.mode === "DRAFT" ? "검토용" : "완성 자료"));
        if (item.state === "SUCCEEDED") {
          const exportId = identifier(item.export_id), revisionId = identifier(item.export_revision_id);
          if (!Number.isInteger(item.page_count) || item.page_count < 1) throw new Error("PDF 페이지 정보를 확인하지 못했습니다.");
          const preview = node("img"); preview.loading = "lazy"; preview.alt = `${item.student_display_name} 질문 자료 첫 페이지`;
          preview.src = `/studio/api/v1${BASE}/exports/${exportId}/pages/1/preview?revision_id=${revisionId}`;
          preview.addEventListener("error", () => {
            if (live(token) && target.dataset.request === stamp && root.contains(target)) preview.replaceWith(node("p", "미리보기를 불러오지 못했습니다. 자료의 접근 상태를 다시 확인해 주세요.", "form-message error"));
          });
          row.append(preview, node("p", `${item.page_count}쪽 · 첫 페이지 미리보기`));
          if (allowed("export")) {
            const download = node("a", "PDF 내려받기", "button quiet");
            download.href = `/studio/api/v1${BASE}/exports/${exportId}/download?revision_id=${revisionId}`;
            row.append(download);
          }
        } else if (item.state === "NEEDS_LAYOUT_REVIEW") row.append(node("p", "한 페이지에 담기 어렵습니다. 글과 사진을 확인해 질문을 나눠 주세요.", "form-message"));
        list.append(row);
      }
      if (!page.items.length) list.append(node("p", "아직 만든 PDF가 없습니다.", "empty-state"));
      if (page.next_cursor) list.append(node("p", "앞부분 50건을 표시했습니다.", "muted-label"));
      target.append(list);
    } catch (error) {
      if (live(token) && target.dataset.request === stamp) {
        if (DENIED_RESOURCE_CODES.has(error?.code)) target.querySelector(".kakao-exports")?.remove();
        message(`PDF 정보를 불러오지 못했습니다. ${explainError(error)}`, true);
      }
    }
  }

  function setOwner(next) {
    if (next === owner) return;
    students.setOwner(next);
    rooms.setOwner(next);
    manual.setOwner(next);
    owner = next || null; permissions = new Set(); roles = new Set();
    generation++; listGeneration++; collectionIntent = null; collectionPending = false; bindingIntent = null; bindingPending = false;
    if (installed) { clearPrivateView(); nodes.refresh.disabled = false; }
  }
  function setPermissions(values) {
    students.setPermissions(values);
    rooms.setPermissions(values);
    manual.setPermissions(values);
    permissions = new Set(values);
    generation++; listGeneration++; stopTimer();
    if (installed) clearPrivateView();
    if (active && owner) void refresh();
  }
  function setRoles(values) {
    manual.setRoles(values);
    roles = new Set(values); generation++; listGeneration++; stopTimer();
    if (installed) clearPrivateView();
    if (active && owner && allowed("read")) void refresh();
  }
  async function open() { install(); active = true; generation++; rooms.open(); manual.open(); await Promise.all([refresh(), students.open()]); }
  function close() {
    students.close();
    rooms.close();
    manual.close();
    active = false; generation++; listGeneration++; stopTimer();
    if (installed) clearPrivateView();
    // A pending request keeps its key while the same owner navigates away and back.
    // Closing a view never cancels its durable collection run.
  }
  async function restoreLocation(route) {
    if (!active || !owner || !allowed("read")) return;
    const capturedOwner = owner, token = generation;
    if (route.source_binding_id && !bindingRows.has(route.source_binding_id)) {
      await refresh();
      if (!live(token) || owner !== capturedOwner) return;
    }
    if (route.source_binding_id) await selectBinding(route.source_binding_id);
    if (!active || owner !== capturedOwner || generation !== token + (route.source_binding_id ? 1 : 0) ||
        (route.source_binding_id && binding?.source_binding_id !== route.source_binding_id)) return;
    if (route.question_id && route.question_revision_id) await openQuestion(route.question_id, route.question_revision_id);
  }
  return {install, setOwner, setPermissions, setRoles, open, close, restoreLocation, refresh};
}
