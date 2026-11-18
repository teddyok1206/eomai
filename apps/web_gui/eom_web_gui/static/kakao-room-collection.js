// A tab remembers the exact request, never the Kakao session, URL or source contents.
const BASE = "/kakao-archive/collections";
const BINDING = /^kakaobinding_[0-9a-f]{32}$/, ROOM = /^kakaoroom_[0-9a-f]{32}$/;
const RUN = /^kakaorun_[0-9a-f]{32}$/, POLICY = /^kakaopolicyrev_[0-9a-f]{32}$/;
const KEY = /^kakao-room-collect-[0-9a-f-]{36}$/;
const RUNNING = new Set(["QUEUED", "INVENTORY", "COLLECTING", "RECONCILING", "PAUSING"]);
const REJECTED = new Set(["API_PRECONDITION_FAILED", "KAKAO_ARCHIVE_PRECONDITION_FAILED", "KAKAO_ARCHIVE_REQUEST_INVALID",
  "KAKAO_ARCHIVE_PERMISSION_DENIED", "KAKAO_ARCHIVE_RESOURCE_NOT_FOUND", "KAKAO_ARCHIVE_BINDING_RETIRED", "KAKAO_ARCHIVE_ROOM_RETIRED",
  "KAKAO_ARCHIVE_COLLECTION_ALREADY_PENDING", "KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT", "KAKAO_ARCHIVE_COLLECTION_CAPABILITY_MISMATCH",
  "KAKAO_ARCHIVE_CAPABILITY_EVIDENCE_INVALID", "HTTP_403", "HTTP_404", "HTTP_412", "HTTP_422"]);
const LABEL = Object.freeze({QUEUED: "대기 중", INVENTORY: "대화방 확인 중", COLLECTING: "수집 중", RECONCILING: "받은 자료 확인 중",
  PAUSING: "종료 확인 중", PAUSED: "일시 정지", AUTH_REQUIRED: "카카오 로그인 필요", COMPLETED: "원본 저장 완료",
  PARTIAL: "확인된 원본 저장 · 일부 범위 미확인", FAILED: "수집을 완료하지 못했습니다", CANCELLED: "취소됨"});
const version = value => Number.isInteger(value) && value >= 1 && value <= 2147483647;

function status(value, bindingId, runId = null) {
  const created = Date.parse(value?.created_at), updated = Date.parse(value?.updated_at);
  if (value?.schema_version !== "kakao-collection-status/1.0" || value.source_binding_id !== bindingId ||
      !RUN.test(value.run_id || "") || (runId !== null && value.run_id !== runId) || !Object.hasOwn(LABEL, value.state) ||
      !version(value.resource_version) || !Number.isFinite(created) || !Number.isFinite(updated) || updated < created) {
    throw new Error("수집 상태가 요청한 작업과 다릅니다.");
  }
  return value;
}

function restore(raw, scope) {
  const value = JSON.parse(raw), select = value?.body?.selection;
  if (!select || select.schema_version !== "kakao-capability-confirmation/1.0" || select.source_binding_id !== scope.bindingId ||
      select.room_id !== scope.roomId || !version(select.expected_binding_version) || !POLICY.test(value?.body?.expected_policy_revision_id || "") ||
      !KEY.test(value?.key || "") || !(value.runId === null || RUN.test(value.runId || ""))) return null;
  return {key:value.key, runId:value.runId, body:{selection:{schema_version:select.schema_version, source_binding_id:scope.bindingId,
    room_id:scope.roomId, expected_binding_version:select.expected_binding_version}, expected_policy_revision_id:value.body.expected_policy_revision_id}};
}

export function createKakaoRoomCollection({document, api, explainError, schedule, unschedule, pollMilliseconds, storage = null}) {
  let root = null, scope = null, timer = null, local = null;
  const submitting = new Set();
  const read = key => { try { return (storage ?? globalThis.sessionStorage)?.getItem(key) ?? null; } catch { return null; } };
  function remember(key, value) {
    local = {key, value};
    try { const store = storage ?? globalThis.sessionStorage; if (value) store?.setItem(key, JSON.stringify(value)); else store?.removeItem(key); } catch { /* A blocked storage never grants or changes authority. */ }
  }
  function unwatch() { if (timer !== null) unschedule(timer); timer = null; }
  function node(tag, text, cls) { const element = document.createElement(tag); element.textContent = text; if (cls) element.className = cls; return element; }
  function button(text, callback, disabled = false) {
    const element = node("button", text, "button quiet"); element.type = "button"; element.disabled = disabled;
    element.addEventListener("click", callback); return element;
  }
  function draw() {
    if (!root) return;
    root.hidden = !scope;
    if (!scope) { root.replaceChildren(); return; }
    const view = scope, pending = submitting.has(view.key);
    const liveMessage = node("p", view.message || (view.status ? LABEL[view.status.state] : ""), "form-message");
    liveMessage.setAttribute("role", "status"); liveMessage.setAttribute("aria-live", "polite");
    root.replaceChildren(node("h4", "선택한 대화방 수집"), liveMessage);
    if (view.roomName) root.insertBefore(node("p", view.roomName), liveMessage);
    if (view.canStart && !view.intent) {
      root.append(node("p", "카카오에서 이 방을 열어 대화와 사진을 가져옵니다. 메시지는 보내지 않지만 방이 읽음으로 표시될 수 있습니다.", "muted-label"),
        button("이 방 수집 시작", () => void submit(view), pending));
    } else if (view.canStart && !view.intent?.runId) {
      root.append(button("같은 수집 요청 확인", () => void submit(view), pending));
    }
    if (view.intent?.runId) {
      root.append(button("수집 상태 확인", () => void observe(view), view.checking));
      if (view.canStart && view.status && ["COMPLETED", "PARTIAL", "FAILED", "CANCELLED"].includes(view.status.state)) {
        root.append(button("이 방 다시 수집", () => {
          if (scope !== view || view.checking || submitting.has(view.key)) return;
          view.intent = null; view.status = null; void submit(view);
        }));
      }
    }
  }
  async function submit(view) {
    if (scope !== view || !view.canStart || view.intent?.runId || submitting.has(view.key)) return;
    if (!view.intent) {
      view.intent = {key:`kakao-room-collect-${globalThis.crypto.randomUUID()}`, runId:null, body:{selection:{
        schema_version:"kakao-capability-confirmation/1.0", source_binding_id:view.bindingId,
        room_id:view.roomId, expected_binding_version:view.bindingVersion}, expected_policy_revision_id:view.policy}};
      remember(view.key, view.intent);
    }
    const saved = view.intent;
    submitting.add(view.key); view.message = "수집 요청을 확인하고 있습니다."; draw();
    try {
      const result = status(await api(BASE, {method:"POST", mutation:true, body:saved.body,
        headers:{"Idempotency-Key":saved.key, "If-Match":`"v${saved.body.selection.expected_binding_version}"`}}), view.bindingId);
      // A late reply must not change another room's screen, but its accepted
      // ID is still needed when the same room is opened again in this tab.
      saved.runId = result.run_id; remember(view.key, saved);
      if (scope?.key === view.key && scope.intent?.key === saved.key) {
        scope.intent = saved; scope.status = result; scope.message = ""; watch(scope);
      }
    } catch (error) {
      const definite = REJECTED.has(error?.code);
      if (definite) remember(view.key, null);
      if (scope?.key === view.key && scope.intent?.key === saved.key) {
        if (definite) scope.intent = null;
        scope.message = definite ? `요청을 접수하지 못했습니다. ${explainError(error)}` :
          `접수 여부를 확인하지 못했습니다. 같은 요청으로 확인해 주세요. ${explainError(error)}`;
      }
    } finally { submitting.delete(view.key); draw(); }
  }
  async function observe(view) {
    if (scope !== view || view.checking || !view.intent?.runId) return;
    const runId = view.intent.runId; unwatch(); view.checking = true; draw();
    try {
      const result = status(await api(`${BASE}/${encodeURIComponent(runId)}?source_binding_id=${encodeURIComponent(view.bindingId)}`), view.bindingId, runId);
      if (scope !== view || view.intent?.runId !== runId) return;
      if (view.status && result.resource_version < view.status.resource_version) throw new Error("이전 실행 상태가 반환됐습니다.");
      view.status = result; view.message = ""; watch(view);
    } catch (error) { if (scope === view) view.message = `수집 상태를 확인하지 못했습니다. ${explainError(error)}`; }
    finally { view.checking = false; if (scope === view) draw(); }
  }
  function watch(view) {
    if (scope !== view) return;
    unwatch();
    if (RUNNING.has(view.status?.state)) timer = schedule(() => { timer = null; void observe(view); }, pollMilliseconds);
  }
  function setScope(owner, binding, room, canStart) {
    unwatch(); scope = null;
    if (owner && binding?.source_binding_id === room?.source_binding_id && BINDING.test(binding?.source_binding_id || "") && ROOM.test(room?.room_id || "") &&
        version(binding.resource_version) && POLICY.test(binding.policy_revision?.policy_revision_id || "")) {
      const key = `eom-kakao-room-collect:${owner}:${binding.source_binding_id}:${room.room_id}`;
      scope = {key, bindingId:binding.source_binding_id, roomId:room.room_id, bindingVersion:binding.resource_version,
        policy:binding.policy_revision.policy_revision_id, roomName:typeof room.display_name === "string" ? room.display_name : "",
        canStart:canStart && binding.state !== "RETIRED" && room.state === "ACTIVE" && room.identity_level === "MANUAL_CONFIRMED",
        intent:null, status:null, message:"", checking:false};
      try { scope.intent = local?.key === key ? local.value : restore(read(key), scope); } catch { /* Ignore tampered or expired tab input. */ }
      if (!scope.canStart && !scope.intent?.runId) scope = null;
      if (scope?.intent?.runId) void observe(scope);
    }
    draw();
  }
  return {install(container) { root = container; draw(); }, setScope};
}
