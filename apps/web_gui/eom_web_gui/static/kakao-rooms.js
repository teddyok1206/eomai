// Existing admitted rooms only. Names are display values, never mapping identity.
const BASE = "/kakao-archive/rooms";
const ROOM = /^kakaoroom_[a-f0-9]{32}$/, BINDING = /^kakaobinding_[a-f0-9]{32}$/;
const REV = /^kakaomappingrev_[a-f0-9]{32}$/, STUDENT = /^kakaostudent_[a-f0-9]{32}$/, DISPLAY = /^kakaostudentrev_[a-f0-9]{32}$/;
const REJECTED = new Set(["KAKAO_ARCHIVE_PRECONDITION_FAILED", "API_PRECONDITION_FAILED", "HTTP_412", "HTTP_403", "HTTP_404",
  "KAKAO_ARCHIVE_PERMISSION_DENIED", "PERMISSION_DENIED", "KAKAO_ARCHIVE_RESOURCE_NOT_FOUND", "KAKAO_ARCHIVE_BINDING_RETIRED",
  "KAKAO_ARCHIVE_ROOM_RETIRED", "KAKAO_ARCHIVE_STUDENT_RETIRED", "KAKAO_ARCHIVE_STUDENT_STALE"]);
const validText = (value, max) => typeof value === "string" && value.trim() && [...value].length <= max && !/[\u0000-\u001f\u007f]/.test(value);
function roomValue(value, bindingId) {
  const mapping = value?.mapping;
  if (value?.schema_version !== "kakao-room/1.0" || value.source_binding_id !== bindingId || !ROOM.test(value.room_id || "") ||
      !validText(value.display_name, 128) || !["ACTIVE", "RETIRED"].includes(value.state) ||
      !["SOURCE_VERIFIED", "MANUAL_CONFIRMED"].includes(value.identity_level) || !Number.isInteger(value.resource_version) ||
      value.resource_version < 1 || value.resource_version > 2147483647 || mapping?.schema_version !== "kakao-room-mapping/1.0" ||
      mapping.resource_version !== value.resource_version || !REV.test(mapping.mapping_revision_id || "") ||
      !(mapping.previous_revision_id === null || REV.test(mapping.previous_revision_id || "")) ||
      (value.resource_version === 1) !== (mapping.previous_revision_id === null) || !validText(mapping.reason, 1000) ||
      !/^sha256:[a-f0-9]{64}$/.test(mapping.sha256 || "") ||
      (mapping.state !== "MAPPED" && mapping.state !== "UNMAPPED") ||
      (mapping.state === "MAPPED" ? (!STUDENT.test(mapping.student_id || "") || !DISPLAY.test(mapping.student_display_revision_id || "") || !validText(mapping.student_display_name, 128)) :
        [mapping.student_id, mapping.student_display_revision_id, mapping.student_display_name].some(x => x !== null))) {
    throw new Error("대화방 연결 정보를 확인하지 못했습니다.");
  }
  return value;
}

export function createKakaoRooms({document, api, explainError, onSelect = () => {}}) {
  let root = null, owner = null, active = false, permissions = new Set(), binding = null;
  let generation = 0, listRequest = 0, detailRequest = 0, studentRequest = 0;
  let rows = new Map(), students = new Map(), selected = null, cursor = null, studentCursor = null;
  let loading = false, studentLoading = false, intent = null, pending = false;
  const nodes = {};
  const allowed = key => owner !== null && permissions.has(`kakao_archive:${key}`);
  const live = token => active && allowed("read") && binding !== null && generation === token;
  const canEdit = () => allowed("edit") && binding?.state !== "RETIRED" && selected?.state === "ACTIVE";
  function node(tag, text, cls = "") {
    const value = document.createElement(tag); if (text !== undefined) value.textContent = text; if (cls) value.className = cls; return value;
  }
  function button(text, callback) { const value = node("button", text, "button quiet"); value.type = "button"; value.addEventListener("click", callback); return value; }
  function message(text, error = false) { nodes.message.textContent = text; nodes.message.className = `form-message${error ? " error" : ""}`; }
  function clearDetail() {
    selected = null; detailRequest++; studentRequest++; students.clear(); studentCursor = null; studentLoading = false;
    nodes.detail.replaceChildren(node("p", "대화방을 선택해 학생 연결을 확인해 주세요.", "empty-state"));
  }
  function clear() {
    listRequest++; rows.clear(); cursor = null; loading = false; nodes.list.replaceChildren(); clearDetail();
    message(binding ? "대화방 목록을 새로고침해 주세요." : "채널을 먼저 선택해 주세요."); sync();
  }
  function sync() {
    if (!root) return;
    root.hidden = !allowed("read"); nodes.next.hidden = !cursor; nodes.next.disabled = loading;
    for (const control of nodes.detail.querySelectorAll("input,select,button")) control.disabled = pending || Boolean(intent && !intent.receipt) || !canEdit();
    if (nodes.moreStudents?.isConnected) { nodes.moreStudents.hidden = !studentCursor; nodes.moreStudents.disabled ||= studentLoading; }
    nodes.recovery.replaceChildren();
    if (active && allowed("edit") && intent && !intent.receipt) {
      const captured = intent, sameBinding = binding?.source_binding_id === captured.bindingId;
      nodes.recovery.append(node("p", sameBinding ? "앞선 연결 변경의 처리 여부를 같은 요청으로 확인합니다." : "처리 여부를 확인하지 못한 연결이 있습니다. 요청했던 채널로 돌아가 확인해 주세요.", "form-message"));
      if (sameBinding) { const replay = button("같은 연결 요청 확인", () => void mutate(captured)); replay.disabled = pending; nodes.recovery.append(replay); }
    }
  }
  function renderList() {
    nodes.list.replaceChildren();
    for (const row of rows.values()) {
      const entry = node("div", undefined, "kakao-list-row");
      entry.append(button(row.display_name, () => void select(row.room_id)), node("small", row.mapping.student_display_name || "학생 연결 필요")); nodes.list.append(entry);
    }
    if (!rows.size) nodes.list.append(node("p", "확인된 대화방이 없습니다. 카카오 로그인과 채널 확인 후 가져올 수 있습니다.", "empty-state"));
    sync();
  }
  async function refresh(append = false) {
    if (!root || !active || !allowed("read") || !binding) return;
    if (append && (!cursor || loading)) return;
    const token = generation, request = ++listRequest, start = append ? cursor : null, bindingId = binding.source_binding_id;
    if (!append) clearDetail(); loading = true; sync(); message("대화방을 불러오고 있습니다.");
    try {
      const query = new URLSearchParams({source_binding_id: bindingId, limit: "50"}); if (start) query.set("cursor", start);
      const page = await api(`${BASE}?${query}`);
      if (!live(token) || request !== listRequest) return;
      if (!Array.isArray(page?.items) || page.items.length > 50 || !(page.next_cursor === null || ROOM.test(page.next_cursor || ""))) throw new Error("대화방 목록을 확인하지 못했습니다.");
      const next = append ? new Map(rows) : new Map(); let previous = start;
      for (const item of page.items) { const value = roomValue(item, bindingId); if (previous !== null && value.room_id <= previous) throw new Error("대화방 목록 순서가 다릅니다."); next.set(value.room_id, value); previous = value.room_id; }
      if (page.next_cursor !== null && (page.items.length !== 50 || page.next_cursor !== previous)) throw new Error("다음 대화방 목록을 확인하지 못했습니다.");
      if (selected && next.has(selected.room_id) && selected.resource_version > next.get(selected.room_id).resource_version) next.set(selected.room_id, selected);
      rows = next; cursor = page.next_cursor; renderList(); message("대화방 연결은 자동 수집을 시작하지 않습니다.");
    } catch (error) { if (live(token) && request === listRequest) { clear(); message(`대화방을 불러오지 못했습니다. ${explainError(error)}`, true); } }
    finally { if (live(token) && request === listRequest) { loading = false; sync(); } }
  }
  async function select(id) {
    if (!active || !allowed("read") || !binding || !ROOM.test(id || "")) return;
    clearDetail(); const token = generation, request = detailRequest, bindingId = binding.source_binding_id;
    message("대화방 정보를 불러오고 있습니다.");
    try {
      const value = roomValue(await api(`${BASE}/${encodeURIComponent(id)}?source_binding_id=${encodeURIComponent(bindingId)}`), bindingId);
      if (!live(token) || request !== detailRequest) return;
      if (value.room_id !== id) throw new Error("다른 대화방 정보가 반환됐습니다.");
      selected = value; rows.set(id, value); renderList(); renderDetail(value); onSelect(value);
      message("학생을 확인해 직접 연결해 주세요. 이름이 같아도 자동 연결하지 않습니다.");
      if (canEdit()) await loadStudents(value);
    } catch (error) { if (live(token) && request === detailRequest) { if (REJECTED.has(error?.code)) clear(); else clearDetail(); message(`대화방을 열지 못했습니다. ${explainError(error)}`, true); } }
  }
  function renderDetail(value) {
    nodes.detail.replaceChildren(node("h4", value.display_name), node("p", value.mapping.state === "MAPPED" ? `연결된 학생: ${value.mapping.student_display_name} (연결 당시 이름)` : "연결된 학생이 없습니다."));
    if (!canEdit()) { sync(); return; }
    const form = node("form", undefined, "kakao-room-edit"); form.setAttribute("aria-label", "대화방 학생 연결");
    const label = node("label", "연결할 학생"); nodes.studentSelect = node("select"); nodes.studentSelect.setAttribute("aria-label", "연결할 학생"); label.append(nodes.studentSelect);
    nodes.moreStudents = button("연결할 학생 더 보기", () => void loadStudents(value, true));
    // Native maxlength counts UTF-16 units; submit validation uses schema code points.
    const reasonLabel = node("label", "연결 변경 이유"); nodes.reason = node("input"); nodes.reason.type = "text"; nodes.reason.maxLength = 2000; nodes.reason.required = true; reasonLabel.append(nodes.reason);
    const map = node("button", "학생 연결 저장", "button secondary"); map.type = "submit";
    form.append(label, nodes.moreStudents, reasonLabel, map);
    form.addEventListener("submit", event => { event.preventDefault(); const student = students.get(nodes.studentSelect.value); if (selected !== value || !student) { message("연결할 학생을 선택해 주세요.", true); return; } void begin(value, "MAP_STUDENT", student); });
    nodes.detail.append(form);
    if (value.mapping.state === "MAPPED") {
      const label = node("label", undefined, "kakao-retire-confirm"), confirm = node("input"); confirm.type = "checkbox"; confirm.dataset.kakao = "room-unmap-confirm";
      label.append(confirm, node("span", "이 방의 학생 연결을 해제합니다. 기존 자료의 연결 이력은 유지됩니다."));
      nodes.detail.append(label, button("학생 연결 해제", () => { if (!confirm.checked) { message("연결 해제 확인란을 먼저 선택해 주세요.", true); return; } void begin(value, "UNMAP_STUDENT"); }));
    }
    renderStudents(); sync();
  }
  function renderStudents() {
    if (!nodes.studentSelect?.isConnected) return;
    const chosen = nodes.studentSelect.value;
    const placeholder = node("option", "학생 선택"); placeholder.value = ""; nodes.studentSelect.replaceChildren(placeholder);
    let ordinal = 0;
    for (const student of students.values()) { const option = node("option", `${++ordinal}. ${student.display_name}`); option.value = student.student_id; nodes.studentSelect.append(option); }
    if (students.has(chosen)) nodes.studentSelect.value = chosen; sync();
  }
  async function loadStudents(room, append = false) {
    if (selected !== room || !canEdit() || !active || (append && (!studentCursor || studentLoading))) return;
    const token = generation, request = ++studentRequest, start = append ? studentCursor : null;
    studentLoading = true; sync();
    try {
      const page = await api(`/kakao-archive/students?limit=50${start ? `&cursor=${encodeURIComponent(start)}` : ""}`);
      if (!live(token) || request !== studentRequest || selected !== room) return;
      if (!Array.isArray(page?.items) || page.items.length > 50 || !(page.next_cursor === null || STUDENT.test(page.next_cursor || ""))) throw new Error("학생 목록을 확인하지 못했습니다.");
      const next = append ? new Map(students) : new Map(); let previous = start;
      for (const student of page.items) {
        if (student?.schema_version !== "kakao-student/1.0" || !STUDENT.test(student.student_id || "") || !DISPLAY.test(student.display_revision_id || "") || !validText(student.display_name, 128) || !["ACTIVE", "RETIRED"].includes(student.state) || (previous !== null && student.student_id <= previous)) throw new Error("학생 목록을 확인하지 못했습니다.");
        if (student.state === "ACTIVE") next.set(student.student_id, student); previous = student.student_id;
      }
      if (page.next_cursor !== null && (page.items.length !== 50 || page.next_cursor !== previous)) throw new Error("학생 목록 순서가 다릅니다.");
      students = next; studentCursor = page.next_cursor; renderStudents();
    } catch (error) { if (live(token) && request === studentRequest && selected === room) { students.clear(); studentCursor = null; renderStudents(); if (REJECTED.has(error?.code)) clear(); message(`학생 목록을 불러오지 못했습니다. ${explainError(error)}`, true); } }
    finally { if (live(token) && request === studentRequest) { studentLoading = false; sync(); } }
  }
  async function begin(room, action, student = null) {
    if (!active || !canEdit() || selected !== room || pending || (intent && !intent.receipt)) return;
    if (!validText(nodes.reason.value, 1000)) { message("연결 변경 이유를 적어 주세요.", true); return; }
    const body = {schema_version: "kakao-room-mapping-command/1.0", action, parent_revision_id: room.mapping.mapping_revision_id,
      expected_resource_version: room.resource_version, reason: nodes.reason.value};
    if (action === "MAP_STUDENT") Object.assign(body, {student_id: student.student_id, student_display_revision_id: student.display_revision_id});
    intent = {body, bindingId: room.source_binding_id, roomId: room.room_id, etag: `"v${room.resource_version}"`, key: `kakao-room-${globalThis.crypto.randomUUID()}`, receipt: null};
    await mutate(intent);
  }
  async function mutate(current) {
    if (!active || !allowed("read") || !allowed("edit") || pending || intent !== current || binding?.source_binding_id !== current.bindingId) return;
    const token = generation, capturedOwner = owner, selection = detailRequest; listRequest++; loading = false; pending = true; sync();
    try {
      const result = await api(`${BASE}/${encodeURIComponent(current.roomId)}/mapping?source_binding_id=${encodeURIComponent(current.bindingId)}`, {method: "POST", mutation: true,
        headers: {"Idempotency-Key": current.key, "If-Match": current.etag}, body: current.body});
      if (owner !== capturedOwner || intent !== current) return;
      const room = roomValue(result?.room, current.bindingId), mapping = room.mapping, body = current.body;
      if (typeof result.replayed !== "boolean" || room.room_id !== current.roomId || room.state !== "ACTIVE" || room.resource_version !== body.expected_resource_version + 1 || mapping.previous_revision_id !== body.parent_revision_id || mapping.reason !== body.reason ||
          (body.action === "MAP_STUDENT" ? (mapping.state !== "MAPPED" || mapping.student_id !== body.student_id || mapping.student_display_revision_id !== body.student_display_revision_id) : mapping.state !== "UNMAPPED")) throw new Error("학생 연결 결과를 확인하지 못했습니다.");
      current.receipt = result;
      // Replayed receipts may be historical. Resolve current before offering another edit.
      if (live(token) && selection === detailRequest) await select(current.roomId);
    } catch (error) { if (live(token) && intent === current) { if (REJECTED.has(error?.code)) { intent = null; clear(); message(`연결 상태나 권한이 변경됐습니다. 새로고침해 주세요. ${explainError(error)}`, true); } else message(`처리 여부를 확인하지 못했습니다. 같은 연결 요청으로 확인해 주세요. ${explainError(error)}`, true); } }
    finally { if (owner === capturedOwner && (intent === current || intent === null)) { pending = false; sync(); } }
  }
  function install(container) {
    root = container; root.classList.add("kakao-room-directory");
    nodes.message = node("p", undefined, "form-message"); nodes.message.setAttribute("role", "status"); nodes.message.setAttribute("aria-live", "polite");
    nodes.list = node("div"); nodes.recovery = node("div"); nodes.detail = node("div", undefined, "kakao-room-detail"); nodes.detail.dataset.kakao = "room-detail";
    nodes.next = button("대화방 더 보기", () => void refresh(true));
    root.replaceChildren(nodes.message, nodes.list, nodes.next, nodes.recovery, nodes.detail); clear();
  }
  function setOwner(value) { if (owner === value) return; owner = value || null; permissions = new Set(); binding = null; generation++; intent = null; pending = false; if (root) clear(); }
  function setPermissions(values) { permissions = new Set(values); generation++; if (!allowed("read") || !allowed("edit")) { intent = null; pending = false; } if (root) clear(); }
  async function setBinding(value) { generation++; binding = value && BINDING.test(value.source_binding_id || "") ? value : null; if (root) clear(); if (binding) await refresh(); }
  function open() { active = true; generation++; }
  function close() { active = false; generation++; binding = null; if (root) clear(); }
  return {install, setOwner, setPermissions, setBinding, open, close, refresh, select};
}
