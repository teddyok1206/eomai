// Owner-private directory. Display names never identify students or map a room automatically.
const BASE = "/kakao-archive/students";
const STUDENT = /^kakaostudent_[a-f0-9]{32}$/;
const REVISION = /^kakaostudentrev_[a-f0-9]{32}$/;
const REJECTED = new Set(["KAKAO_ARCHIVE_PRECONDITION_FAILED", "API_PRECONDITION_FAILED", "HTTP_412",
  "KAKAO_ARCHIVE_STUDENT_RETIRED", "KAKAO_ARCHIVE_RESOURCE_NOT_FOUND", "KAKAO_ARCHIVE_PERMISSION_DENIED",
  "PERMISSION_DENIED", "HTTP_403", "HTTP_404"]);

function studentValue(value) {
  if (value?.schema_version !== "kakao-student/1.0" || !STUDENT.test(value.student_id || "") ||
      !REVISION.test(value.display_revision_id || "") ||
      !(value.previous_revision_id === null || REVISION.test(value.previous_revision_id || "")) ||
      !["ACTIVE", "RETIRED"].includes(value.state) || !Number.isInteger(value.resource_version) ||
      value.resource_version < 1 || value.resource_version > 2147483647 ||
      (value.resource_version === 1) !== (value.previous_revision_id === null) ||
      typeof value.display_name !== "string" || !value.display_name.trim() || [...value.display_name].length > 128 ||
      /[\u0000-\u001f\u007f]/.test(value.display_name) || !/^sha256:[a-f0-9]{64}$/.test(value.sha256 || "")) {
    throw new Error("학생 정보를 확인하지 못했습니다.");
  }
  return value;
}

export function createKakaoStudents({document, api, explainError}) {
  let root = null, owner = null, active = false, permissions = new Set();
  let generation = 0, listRequest = 0, detailRequest = 0, loading = false;
  let rows = new Map(), selected = null, nextCursor = null, intent = null, pending = false;
  const nodes = {};
  const allowed = key => owner !== null && permissions.has(`kakao_archive:${key}`);
  const live = token => active && allowed("read") && token === generation;
  function node(tag, text, className = "") {
    const result = document.createElement(tag);
    if (text !== undefined) result.textContent = text;
    if (className) result.className = className;
    return result;
  }
  function button(text, callback) {
    const result = node("button", text, "button quiet"); result.type = "button";
    result.addEventListener("click", callback); return result;
  }
  function message(text, error = false) {
    nodes.message.textContent = text; nodes.message.className = `form-message${error ? " error" : ""}`;
  }
  function clearDetail() {
    detailRequest++; selected = null; nodes.list.value = "";
    nodes.detail.replaceChildren(node("p", "학생을 선택하면 이름과 사용 상태를 확인할 수 있습니다.", "empty-state"));
  }
  function clear() {
    listRequest++; loading = false; rows.clear(); nextCursor = null; nodes.list.replaceChildren(); clearDetail();
    nodes.name.value = intent?.kind === "CREATE" && !intent.receipt ? intent.body.display_name : "";
    sync(); message(owner ? "학생 목록을 새로고침해 주세요." : "로그인 후 학생 목록을 열 수 있습니다.");
  }
  function sync() {
    if (!root) return;
    root.hidden = !allowed("read"); nodes.createForm.hidden = !allowed("edit");
    const unresolved = intent && !intent.receipt;
    nodes.name.disabled = pending || Boolean(unresolved);
    nodes.create.disabled = !allowed("edit") || pending || Boolean(unresolved);
    nodes.next.hidden = !nextCursor; nodes.next.disabled = loading;
    for (const control of nodes.detail.querySelectorAll("input,button")) {
      control.disabled = pending || Boolean(unresolved) || !allowed("edit");
    }
    nodes.recovery.replaceChildren();
    if (active && allowed("edit") && unresolved) {
      const captured = intent;
      const replay = button("같은 학생 요청 확인", () => { if (!pending && intent === captured) void mutate(captured); });
      replay.disabled = pending;
      nodes.recovery.append(node("p", "앞선 학생 변경의 처리 여부를 같은 요청으로 확인합니다.", "form-message"), replay);
    }
  }
  function renderList() {
    const selectedId = selected?.student_id;
    nodes.list.replaceChildren(node("option", "학생 선택")); nodes.list.firstChild.value = "";
    for (const value of rows.values()) {
      const option = node("option", `${value.display_name}${value.state === "RETIRED" ? " · 사용 중지" : ""}`);
      option.value = value.student_id; nodes.list.append(option);
    }
    if (selectedId && rows.has(selectedId)) nodes.list.value = selectedId;
    sync();
  }
  function renderDetail(value) {
    selected = value; rows.set(value.student_id, value); renderList();
    const title = node("h3", value.display_name), state = node("span", value.state === "ACTIVE" ? "사용 중" : "사용 중지", "status-badge");
    nodes.detail.replaceChildren(title, state);
    if (value.state === "RETIRED") {
      nodes.detail.append(node("p", "앞으로 사용할 학생 목록에서는 제외됩니다. 기존 자료와 이름 변경 이력은 유지됩니다."));
    } else if (allowed("edit")) {
      const form = node("form", undefined, "kakao-student-edit"); form.setAttribute("aria-label", "학생 이름 변경");
      const label = node("label", "표시 이름"), input = node("input"); input.type = "text"; input.maxLength = 256; input.required = true;
      input.value = value.display_name; input.autocomplete = "off"; label.append(input);
      const save = node("button", "이름 저장", "button secondary"); save.type = "submit";
      form.append(label, save); form.addEventListener("submit", event => {
        event.preventDefault(); if (selected !== value) return;
        const name = validName(input.value); if (name === null) return;
        void begin("RENAME", value, {display_name: name});
      });
      const confirm = node("label", undefined, "kakao-retire-confirm"), check = node("input"); check.type = "checkbox";
      check.dataset.kakao = "student-retire-confirm";
      confirm.append(check, node("span", "이 학생을 사용 중지합니다. 기존 자료는 삭제하지 않습니다."));
      const retire = button("학생 사용 중지", () => {
        if (selected !== value) return;
        if (!check.checked) { message("사용 중지 확인란을 먼저 선택해 주세요.", true); return; }
        void begin("RETIRE", value);
      });
      nodes.detail.append(form, confirm, retire);
    }
    sync();
  }
  function validName(raw) {
    if (!raw.trim() || [...raw].length > 128 || /[\u0000-\u001f\u007f]/.test(raw)) {
      message("학생 이름을 확인해 주세요.", true); return null;
    }
    return raw;
  }
  async function refresh(append = false) {
    if (!root || !active || !allowed("read")) return;
    if (append && (!nextCursor || loading)) return;
    const token = generation, request = ++listRequest, cursor = append ? nextCursor : null;
    if (!append) clearDetail();
    loading = true; sync(); message("학생 목록을 불러오고 있습니다.");
    try {
      const page = await api(`${BASE}?limit=50${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`);
      if (!live(token) || request !== listRequest) return;
      if (!Array.isArray(page?.items) || page.items.length > 50 || !(page.next_cursor === null || STUDENT.test(page.next_cursor || ""))) {
        throw new Error("학생 목록의 형식을 확인하지 못했습니다.");
      }
      const next = append ? new Map(rows) : new Map(); let previous = cursor;
      for (const item of page.items) {
        const value = studentValue(item);
        if (previous !== null && value.student_id <= previous) throw new Error("학생 목록의 순서를 확인하지 못했습니다.");
        // A selected/newly added student can already be present outside the loaded page.
        const cached = next.get(value.student_id);
        next.set(value.student_id, cached && cached.resource_version > value.resource_version ? cached : value);
        previous = value.student_id;
      }
      if (page.next_cursor !== null && (page.items.length !== 50 || page.next_cursor !== previous)) throw new Error("학생 목록의 다음 위치를 확인하지 못했습니다.");
      if (selected && next.has(selected.student_id) && selected.resource_version > next.get(selected.student_id).resource_version) next.set(selected.student_id, selected);
      rows = next; nextCursor = page.next_cursor; renderList();
      message(rows.size ? `${rows.size}명의 학생을 표시했습니다. 같은 이름이어도 서로 다른 학생으로 관리합니다.` : "아직 등록한 학생이 없습니다.");
    } catch (error) {
      if (live(token) && request === listRequest) { clear(); message(`학생 목록을 불러오지 못했습니다. ${explainError(error)}`, true); }
    } finally { if (live(token) && request === listRequest) { loading = false; sync(); } }
  }
  async function selectStudent(id) {
    if (!active || !allowed("read")) return;
    clearDetail(); if (!STUDENT.test(id || "")) return;
    const token = generation, request = detailRequest;
    nodes.list.value = id; message("학생 정보를 불러오고 있습니다.");
    try {
      const value = studentValue(await api(`${BASE}/${encodeURIComponent(id)}`));
      if (!live(token) || request !== detailRequest) return;
      if (value.student_id !== id) throw new Error("다른 학생 정보가 반환됐습니다.");
      renderDetail(value); message("학생 정보를 확인했습니다. 확인된 대화방을 선택해 학생을 연결할 수 있습니다.");
    } catch (error) {
      if (live(token) && request === detailRequest) {
        if (REJECTED.has(error?.code)) clear(); else clearDetail();
        message(`학생 정보를 열지 못했습니다. ${explainError(error)}`, true);
      }
    }
  }
  async function begin(kind, value = null, extra = {}) {
    if (!active || !allowed("read") || !allowed("edit") || pending || (intent && !intent.receipt)) return;
    if (value && (selected !== value || value.state !== "ACTIVE")) return;
    const body = {schema_version: "kakao-student-command/1.0", action: kind, ...extra};
    if (value) Object.assign(body, {parent_revision_id: value.display_revision_id, expected_resource_version: value.resource_version});
    intent = {kind, body, targetId: value?.student_id || null, etag: value ? `"v${value.resource_version}"` : null,
      key: `kakao-student-${globalThis.crypto.randomUUID()}`, path: value ? `${BASE}/${encodeURIComponent(value.student_id)}/commands` : BASE, receipt: null};
    await mutate(intent);
  }
  async function mutate(current) {
    if (!active || !allowed("read") || !allowed("edit") || pending || intent !== current) return;
    const capturedOwner = owner, token = generation, selection = detailRequest;
    listRequest++; loading = false;
    pending = true; sync(); message("학생 정보를 저장하고 있습니다.");
    try {
      const headers = {"Idempotency-Key": current.key}; if (current.etag) headers["If-Match"] = current.etag;
      const result = await api(current.path, {method: "POST", mutation: true, headers, body: current.body});
      if (owner !== capturedOwner || intent !== current) return;
      const value = studentValue(result?.student);
      if (typeof result.replayed !== "boolean" || (current.kind === "CREATE" && (value.resource_version !== 1 || value.state !== "ACTIVE" || value.display_name !== current.body.display_name)) ||
          (current.kind !== "CREATE" && (value.student_id !== current.targetId || value.resource_version !== current.body.expected_resource_version + 1 || value.previous_revision_id !== current.body.parent_revision_id)) ||
          (current.kind === "RENAME" && (value.state !== "ACTIVE" || value.display_name !== current.body.display_name)) || (current.kind === "RETIRE" && value.state !== "RETIRED")) {
        throw new Error("학생 변경 결과를 확인하지 못했습니다.");
      }
      current.receipt = result;
      if (live(token)) {
        nodes.name.value = "";
        // Replay returns its original immutable revision; read current before displaying an editable version.
        if (selection === detailRequest) await selectStudent(value.student_id);
      }
    } catch (error) {
      if (live(token) && intent === current) {
        if (REJECTED.has(error?.code)) {
          intent = null; clear(); message(`학생 상태나 권한이 변경됐습니다. 새로고침한 뒤 확인해 주세요. ${explainError(error)}`, true);
        } else message(`처리 여부를 확인하지 못했습니다. 같은 학생 요청으로 다시 확인해 주세요. ${explainError(error)}`, true);
      }
    } finally {
      if (owner === capturedOwner && (intent === current || intent === null)) { pending = false; sync(); }
    }
  }
  function install(container) {
    if (root) return;
    root = container; root.classList.add("kakao-students"); root.setAttribute("aria-label", "학생 관리");
    nodes.message = node("p", undefined, "form-message"); nodes.message.setAttribute("role", "status"); nodes.message.setAttribute("aria-live", "polite");
    nodes.createForm = node("form", undefined, "kakao-student-edit"); nodes.createForm.setAttribute("aria-label", "학생 추가");
    // Native maxlength is UTF-16; validName enforces the contract's 128 code points.
    const label = node("label", "새 학생 이름"); nodes.name = node("input"); nodes.name.type = "text"; nodes.name.required = true; nodes.name.maxLength = 256; nodes.name.autocomplete = "off"; label.append(nodes.name);
    nodes.create = node("button", "학생 추가", "button secondary"); nodes.create.type = "submit"; nodes.createForm.append(label, nodes.create);
    nodes.createForm.addEventListener("submit", event => { event.preventDefault(); const name = validName(nodes.name.value); if (name !== null) void begin("CREATE", null, {display_name: name}); });
    nodes.recovery = node("div");
    const selectLabel = node("label", "학생", "kakao-student-picker"); nodes.list = node("select"); nodes.list.setAttribute("aria-label", "학생"); selectLabel.append(nodes.list);
    nodes.list.addEventListener("change", () => void selectStudent(nodes.list.value));
    nodes.next = button("학생 더 보기", () => void refresh(true)); nodes.detail = node("div", undefined, "kakao-student-detail"); nodes.detail.dataset.kakao = "student-detail";
    root.replaceChildren(node("h2", "학생 관리"), node("p", "학생 이름을 따로 보관합니다. 이름이 같아도 자동으로 합치거나 대화방과 연결하지 않습니다.", "muted-label"), nodes.message,
      nodes.createForm, nodes.recovery, selectLabel, nodes.next, nodes.detail);
    clear();
  }
  function setOwner(value) {
    if (owner === value) return;
    owner = value || null; permissions = new Set(); generation++; intent = null; pending = false;
    if (root) clear();
  }
  function setPermissions(values) {
    permissions = new Set(values); generation++;
    if (!allowed("read") || !allowed("edit")) { intent = null; pending = false; }
    if (root) clear(); if (active && allowed("read")) void refresh();
  }
  async function open() { active = true; generation++; await refresh(); }
  function close() { active = false; generation++; if (root) clear(); }
  return {install, setOwner, setPermissions, open, close, refresh};
}
