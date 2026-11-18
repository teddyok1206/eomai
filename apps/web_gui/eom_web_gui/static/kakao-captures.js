// Received-input selection only. Never controls Kakao or infers a room from a filename.
const BASE = "/kakao-archive/manual-captures";
const BINDING = /^kakaobinding_[a-f0-9]{32}$/, LEASE = /^kakaoremotelease_[a-f0-9]{32}$/, CAPTURE = /^kakaodownload_[a-f0-9]{32}$/, SHA = /^sha256:[a-f0-9]{64}$/;
const STATES = {ROOM_IDENTITY_OBSERVED:"대화방 확인 정보 있음", NOT_RECEIVED:"파일 받는 중", TRANSFER_FAILED:"파일 받기 실패", NO_OBSERVATION:"방 확인 정보 없음", ROOM_IDENTITY_UNAVAILABLE:"방 확인 필요", INPUT_UNAVAILABLE:"수신 기록 확인 필요"};
const REFUSED = new Set(["HTTP_403", "HTTP_404", "HTTP_409", "HTTP_412", "API_PRECONDITION_FAILED", "KAKAO_ARCHIVE_PERMISSION_DENIED", "KAKAO_ARCHIVE_RESOURCE_NOT_FOUND", "KAKAO_ARCHIVE_PRECONDITION_FAILED", "KAKAO_ARCHIVE_BINDING_RETIRED", "KAKAO_ARCHIVE_CHANNEL_IDENTITY_MISMATCH", "KAKAO_ARCHIVE_ROOM_IDENTITY_MISMATCH"]);

function pageValue(value, binding) {
  if (value?.schema_version !== "kakao-manual-capture-page/1.0" || value.source_binding_id !== binding ||
      value.scope !== "RECENT_EIGHT_MANUAL_SESSIONS" || !Number.isInteger(value.binding_resource_version) || value.binding_resource_version < 1 || value.binding_resource_version > 2147483647 ||
      !Array.isArray(value.items) || value.items.length > 50 || typeof value.truncated !== "boolean") throw new Error("수신 목록 형식을 확인하지 못했습니다.");
  const ids = new Set();
  for (const item of value.items) {
    const key = `${item.manual_lease_id}/${item.capture_id}`;
    if (!LEASE.test(item.manual_lease_id || "") || !CAPTURE.test(item.capture_id || "") || ids.has(key) || !Object.hasOwn(STATES, item.state) ||
        (item.state === "ROOM_IDENTITY_OBSERVED" ? !SHA.test(item.preview_sha256 || "") : item.preview_sha256 !== null) ||
        !(item.started_at === null || Number.isFinite(Date.parse(item.started_at))) || !(item.completed_at === null || Number.isFinite(Date.parse(item.completed_at))) ||
        !(item.size_bytes === null || Number.isInteger(item.size_bytes) && item.size_bytes > 0 && item.size_bytes <= 33554432) ||
        (item.completed_at !== null && (item.started_at === null || Date.parse(item.completed_at) < Date.parse(item.started_at))) ||
        (item.state === "ROOM_IDENTITY_OBSERVED" && (item.completed_at === null || item.size_bytes === null))) throw new Error("수신 자료 정보를 확인하지 못했습니다.");
    ids.add(key);
  }
  return value;
}

export function createKakaoCaptures({document, api, explainError, onConfirmed = async () => {}}) {
  let root, owner = null, binding = null, active = false, roles = new Set(), permissions = new Set();
  let generation = 0, request = 0, loading = false, pending = false, page = null, selected = null, intent = null;
  let photoRequest = 0, checkingPhoto = false;
  const nodes = {};
  const allowed = () => active && owner && roles.has("ADMIN") && permissions.has("kakao_archive:collect") && binding && binding.state !== "RETIRED";
  const live = token => allowed() && token === generation;
  function node(tag, text, cls = "") { const result = document.createElement(tag); if (text !== undefined) result.textContent = text; if (cls) result.className = cls; return result; }
  function button(text, callback) { const result = node("button", text, "button quiet"); result.type = "button"; result.addEventListener("click", callback); return result; }
  function message(text, error = false) { nodes.message.textContent = text; nodes.message.className = `form-message${error ? " error" : ""}`; }
  function label(item, index) {
    const time = item.started_at ? new Date(item.started_at).toLocaleString("ko-KR", {timeZone:"Asia/Seoul", dateStyle:"short", timeStyle:"short"}) : "시각 확인 필요";
    return `${index + 1}. ${time} · ${STATES[item.state]}`;
  }
  function photoSelection() {
    const items = page?.items || [];
    const csv = items[nodes.csv.value], photo = items[nodes.photo.value];
    if (!csv || !photo || photo.state !== "ROOM_IDENTITY_OBSERVED" ||
        csv.state !== "ROOM_IDENTITY_UNAVAILABLE" || csv.manual_lease_id !== photo.manual_lease_id) return null;
    return {source_binding_id:page.source_binding_id, manual_lease_id:photo.manual_lease_id,
      csv_capture_id:csv.capture_id, photo_capture_id:photo.capture_id};
  }
  function resetPhotoStatus() {
    photoRequest++; checkingPhoto = false; nodes.photoStatus.textContent = "";
  }
  function photoOptions() {
    resetPhotoStatus();
    for (const [select, title] of [[nodes.csv, "받은 대화 CSV 선택"], [nodes.photo, "받은 사진 선택"]]) {
      const empty = node("option", title); empty.value = ""; select.replaceChildren(empty);
    }
    for (const [index, item] of (page?.items || []).entries()) {
      const select = item.state === "ROOM_IDENTITY_OBSERVED" ? nodes.photo :
        item.state === "ROOM_IDENTITY_UNAVAILABLE" ? nodes.csv : null;
      if (!select) continue;
      const option = node("option", label(item, index)); option.value = String(index); select.append(option);
    }
    sync();
  }
  async function checkPhoto() {
    const selection = photoSelection();
    if (!allowed() || loading || pending || checkingPhoto || !selection) return;
    const token = generation, serial = ++photoRequest;
    checkingPhoto = true; sync(); nodes.photoStatus.textContent = "두 파일에서 사진이 들어갈 대화 행을 확인하고 있습니다.";
    try {
      const result = await api(`${BASE}/photo-occurrence?${new URLSearchParams(selection)}`);
      if (!live(token) || serial !== photoRequest) return;
      if (Object.entries(selection).some(([key, value]) => result?.selection?.[key] !== value) ||
          (result.row_ordinal !== null && (!Number.isInteger(result.row_ordinal) ||
           result.row_ordinal < 1 || result.row_ordinal > 100000))) throw new Error("선택한 수신 자료와 응답이 일치하지 않습니다.");
      nodes.photoStatus.textContent = result.row_ordinal === null
        ? "사진이 속한 대화 행을 확정하지 못했습니다. 어떤 자료도 등록하지 않았습니다."
        : `앞뒤 대화가 일치하는 CSV ${result.row_ordinal}번째 대화 행을 찾았습니다. 아직 등록하지 않았습니다.`;
    } catch (error) {
      if (live(token) && serial === photoRequest) nodes.photoStatus.textContent = `사진 위치를 확인하지 못했습니다. ${explainError(error)}`;
    } finally {
      if (live(token) && serial === photoRequest) { checkingPhoto = false; sync(); }
    }
  }
  function sync() {
    if (!root) return;
    root.hidden = !allowed(); nodes.refresh.disabled = !allowed() || loading || pending;
    for (const control of nodes.form.querySelectorAll("input,button")) control.disabled = !allowed() || pending || Boolean(intent && !intent.receipt);
    nodes.form.hidden = !selected || selected.state !== "ROOM_IDENTITY_OBSERVED";
    nodes.photoForm.hidden = nodes.csv.options.length < 2 || nodes.photo.options.length < 2;
    nodes.checkPhoto.disabled = !allowed() || loading || pending || checkingPhoto || !photoSelection();
    nodes.recovery.replaceChildren();
    if (intent && !intent.receipt && allowed()) {
      nodes.recovery.append(node("p", "처리 여부가 확인되지 않은 요청은 같은 요청으로 확인합니다.", "muted-label"));
      if (intent.body.source_binding_id === binding.source_binding_id) { const retry = button("같은 방 확인 요청 확인", () => void submit(intent)); retry.disabled = pending; nodes.recovery.append(retry); }
    }
  }
  function clear() {
    page = null; selected = null; request++; loading = false;
    if (root) { nodes.list.replaceChildren(); nodes.name.value = ""; nodes.confirm.checked = false; message("사진을 내려받은 뒤 ‘받은 자료 새로고침’을 눌러 주세요."); photoOptions(); }
  }
  function renderList() {
    nodes.list.replaceChildren();
    for (const [index, item] of (page?.items || []).entries()) {
      const line = node("div", undefined, "kakao-list-row");
      const select = button(label(item, index), () => {
        if (!allowed() || pending || intent && !intent.receipt) return;
        selected = item; nodes.confirm.checked = false; sync();
      });
      select.disabled = item.state !== "ROOM_IDENTITY_OBSERVED" || pending || Boolean(intent && !intent.receipt);
      line.append(select); if (item.size_bytes !== null) line.append(node("small", `${Math.ceil(item.size_bytes / 1024)} KB`)); nodes.list.append(line);
    }
    if (!page?.items.length) nodes.list.append(node("p", "이 연결에서 최근 받은 자료가 없습니다.", "empty-state"));
    sync();
  }
  async function refresh() {
    if (!allowed() || loading || pending) return;
    const token = generation, current = ++request, bindingId = binding.source_binding_id; loading = true; resetPhotoStatus(); sync(); message("수신 기록만 확인하고 있습니다. 사진·대화를 새로 가져오지 않습니다.");
    try {
      const result = await api(`${BASE}?source_binding_id=${encodeURIComponent(bindingId)}`);
      if (!live(token) || current !== request) return;
      page = pageValue(result, bindingId); selected = null; renderList(); photoOptions();
      message(page.truncated ? "최근 수신 자료 일부만 표시됩니다. 확인 정보가 없는 자료는 연결하지 않습니다." : "방 확인 정보는 사진 다운로드에서 관측한 정보입니다. 아직 질문이나 사진이 등록된 것은 아닙니다.");
    } catch (error) { if (live(token) && current === request) { page = null; selected = null; nodes.list.replaceChildren(); photoOptions(); message(`수신 기록을 확인하지 못했습니다. ${explainError(error)}`, true); } }
    finally { if (live(token) && current === request) { loading = false; sync(); } }
  }
  async function begin() {
    if (!allowed() || pending || intent && !intent.receipt || !page || selected?.state !== "ROOM_IDENTITY_OBSERVED") return;
    const name = nodes.name.value.trim();
    if (!name || [...name].length > 128 || /[\u0000-\u001f\u007f]/.test(name) || !nodes.confirm.checked) { message("방 이름과 채널·대화방 확인란을 확인해 주세요.", true); return; }
    intent = {key:`kakao-capture-${crypto.randomUUID()}`, owner, body:{schema_version:"kakao-manual-capture-confirm/1.0", source_binding_id:binding.source_binding_id,
      manual_lease_id:selected.manual_lease_id, capture_id:selected.capture_id, expected_preview_sha256:selected.preview_sha256,
      expected_binding_version:page.binding_resource_version, display_name:name, channel_and_room_confirmed:true}};
    await submit(intent);
  }
  async function submit(current) {
    if (!allowed() || pending || intent !== current || current.owner !== owner || current.body.source_binding_id !== binding.source_binding_id || current.receipt) return;
    const token = generation; pending = true; sync(); message("원본과 방 확인 정보를 검사해 저장하고 있습니다.");
    try {
      const result = await api(`${BASE}/confirm-room`, {method:"POST", mutation:true, body:current.body,
        headers:{"Idempotency-Key":current.key, "If-Match":`"v${current.body.expected_binding_version}"`}});
      if (owner !== current.owner || intent !== current) return;
      if (typeof result?.replayed !== "boolean" || result.room?.source_binding_id !== current.body.source_binding_id || !/^kakaoroom_[a-f0-9]{32}$/.test(result.room?.room_id || "")) throw new Error("방 저장 결과를 확인하지 못했습니다.");
      current.receipt = result;
      selected = null; nodes.confirm.checked = false;
      if (live(token)) { message("대화방을 저장했습니다. 대화방 영역에서 학생을 연결해 주세요. 자동 수집은 시작하지 않았습니다."); await onConfirmed(result.room); }
    } catch (error) {
      if (!live(token) || intent !== current) return;
      if (current.receipt) message("방 저장은 완료됐습니다. 대화방 목록을 새로고침해 주세요.", true);
      else if (REFUSED.has(error?.code)) { intent = null; selected = null; message(`방이나 권한 정보가 변경됐습니다. 수신 목록을 다시 확인해 주세요. ${explainError(error)}`, true); }
      else message(`처리 여부를 확인하지 못했습니다. 같은 요청으로 확인해 주세요. ${explainError(error)}`, true);
    } finally { if (owner === current.owner && (intent === current || intent === null)) { pending = false; sync(); renderList(); } }
  }
  function install(container) {
    root = container; root.classList.add("kakao-capture-intake"); root.setAttribute("aria-label", "받은 자료 확인");
    nodes.message = node("p", undefined, "form-message"); nodes.message.setAttribute("role", "status"); nodes.message.setAttribute("aria-live", "polite");
    nodes.refresh = button("받은 자료 새로고침", () => void refresh()); nodes.list = node("div"); nodes.recovery = node("div");
    nodes.form = node("form", undefined, "kakao-bootstrap"); nodes.form.setAttribute("aria-label", "수신 대화방 확인");
    const name = node("label", "저장할 대화방 이름"); nodes.name = node("input"); nodes.name.type = "text"; nodes.name.required = true; nodes.name.maxLength = 256; nodes.name.autocomplete = "off"; name.append(nodes.name);
    const confirmation = node("label", undefined, "kakao-retire-confirm"); nodes.confirm = node("input"); nodes.confirm.type = "checkbox";
    confirmation.append(nodes.confirm, node("span", "선택한 연결의 채널·대화방에서 내려받은 사진임을 확인했습니다."));
    const save = node("button", "대화방 확인 저장", "button secondary"); save.type = "submit";
    nodes.form.append(name, confirmation, save); nodes.form.addEventListener("submit", event => { event.preventDefault(); void begin(); });
    nodes.photoForm = node("div", undefined, "kakao-bootstrap");
    nodes.photoForm.setAttribute("role", "group"); nodes.photoForm.setAttribute("aria-label", "사진이 속한 대화 확인");
    for (const [key, text] of [["csv", "대화 CSV"], ["photo", "사진"]]) {
      const field = node("label", text); nodes[key] = node("select");
      nodes[key].addEventListener("change", () => { resetPhotoStatus(); sync(); });
      field.append(nodes[key]); nodes.photoForm.append(field);
    }
    nodes.checkPhoto = button("사진 위치 확인", () => void checkPhoto());
    nodes.photoStatus = node("p", undefined, "form-message"); nodes.photoStatus.setAttribute("role", "status");
    nodes.photoForm.append(nodes.checkPhoto, node("p", "같은 카카오 로그인 회차에서 받은 대화 CSV와 사진을 골라 주세요.", "muted-label"), nodes.photoStatus);
    root.replaceChildren(node("h3", "받은 자료 확인"), nodes.message, nodes.refresh, nodes.list, nodes.photoForm, nodes.form, nodes.recovery); clear();
  }
  function setOwner(value) { if (owner === value) return; owner = value || null; roles.clear(); permissions.clear(); binding = null; intent = null; pending = false; generation++; clear(); }
  function setRoles(values) { roles = new Set(values); generation++; clear(); }
  function setPermissions(values) { permissions = new Set(values); generation++; clear(); }
  function setBinding(value) { generation++; binding = value && BINDING.test(value.source_binding_id || "") ? value : null; clear(); }
  function open() { active = true; generation++; sync(); }
  function close() { active = false; generation++; binding = null; clear(); }
  return {install, setOwner, setRoles, setPermissions, setBinding, open, close, refresh};
}
