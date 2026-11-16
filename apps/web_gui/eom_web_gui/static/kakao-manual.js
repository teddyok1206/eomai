// Private manual-login presentation; no credentials, profile paths or runtime authority.
const BASE = "/kakao-archive/manual-sessions";
const LEASE = /^kakaoremotelease_[a-f0-9]{32}$/;
const BINDING = /^kakaobinding_[a-f0-9]{32}$/;
const PHASE = new Set(["PREPARING", "ACTIVE", "STOPPING", "ENDED", "ERROR"]);
const DENIED = new Set(["KAKAO_ARCHIVE_PERMISSION_DENIED", "KAKAO_ARCHIVE_RESOURCE_NOT_FOUND", "AUTH_REAUTHENTICATION_REQUIRED", "HTTP_401", "HTTP_403"]);

function checked(value, bindingId, leaseId = null) {
  const created = Date.parse(value?.created_at), absolute = Date.parse(value?.absolute_expires_at);
  const expires = value?.expires_at === null ? null : Date.parse(value?.expires_at);
  if (value?.schema_version !== "kakao-manual-session/1.0" || !LEASE.test(value.lease_id || "") ||
      value.source_binding_id !== bindingId || (leaseId && value.lease_id !== leaseId) || !PHASE.has(value.phase) ||
      !Number.isInteger(value.resource_version) || value.resource_version < 1 || value.resource_version > 2147483647 ||
      !Number.isInteger(value.grant_revision) || value.grant_revision < 0 || value.grant_revision > 2147483647 ||
      !Number.isFinite(created) || !Number.isFinite(absolute) || absolute <= created || absolute - created > 1200000 ||
      (value.grant_revision === 0) !== (expires === null) ||
      (expires !== null && (!Number.isFinite(expires) || expires <= created || expires > absolute)) ||
      typeof value.ready !== "boolean" || (value.ready && (value.phase !== "ACTIVE" || !value.grant_revision)) ||
      (value.phase === "ENDED") !== (value.closed_at !== null)) {
    throw new Error("원격 로그인 상태를 확인하지 못했습니다.");
  }
  return value;
}

export function createKakaoManual({document, api, explainError = () => "잠시 후 다시 확인해 주세요.",
  schedule = setTimeout, unschedule = clearTimeout, now = Date.now, remoteViewEnabled = null}) {
  let root, owner = null, active = false, binding = null, lease = null;
  let roles = new Set(), permissions = new Set(), generation = 0, timer = null, expiryTimer = null;
  let intent = null, busy = false, message = "", failed = false, frame = null;
  let viewEnabled = remoteViewEnabled === true;
  const nodes = {};
  function node(tag, text, className = "") {
    const value = document.createElement(tag); if (text !== undefined) value.textContent = text;
    if (className) value.className = className; return value;
  }
  function permitted() { return active && owner && roles.has("ADMIN") && permissions.has("kakao_archive:remote"); }
  function available() { return permitted() && binding && binding.state !== "RETIRED"; }
  function live(token) { return available() && token === generation; }
  function stopHeartbeat() { if (timer !== null) unschedule(timer); timer = null; }
  function stopTimer() { stopHeartbeat(); if (expiryTimer !== null) unschedule(expiryTimer); expiryTimer = null; }
  function removeFrame() { frame?.remove(); frame = null; }
  function selectedLease() { return lease?.source_binding_id === binding?.source_binding_id ? lease : null; }
  function selectedIntent() { return intent?.bindingId === binding?.source_binding_id ? intent : null; }
  function scheduleNext() {
    stopHeartbeat(); if (!available() || busy || selectedIntent() || failed) return;
    const current = selectedLease(); if (!current || ["ENDED", "ERROR"].includes(current.phase)) return;
    if (current.phase === "ACTIVE" && current.expires_at && Date.parse(current.expires_at) <= now()) return;
    const token = generation;
    timer = schedule(() => { timer = null; if (live(token)) void (current.phase === "ACTIVE" ? renew() : refresh()); }, current.phase === "ACTIVE" ? 10000 : 3000);
  }
  function render() {
    if (!root) return;
    if (expiryTimer !== null) unschedule(expiryTimer); expiryTimer = null;
    root.hidden = !permitted() || !binding;
    const current = selectedLease(), pending = selectedIntent();
    const expired = current?.expires_at && Date.parse(current.expires_at) <= now();
    nodes.start.disabled = !available() || busy || Boolean(intent) || Boolean(current && !["ENDED", "ERROR"].includes(current.phase));
    // ERROR retains the physical profile fence until the server confirms actual closure.
    if (current?.phase === "ERROR") nodes.start.disabled = true;
    nodes.refresh.disabled = !available() || busy || !current;
    nodes.end.disabled = !available() || busy || Boolean(intent) || !current || ["STOPPING", "ENDED"].includes(current.phase);
    nodes.retry.hidden = !pending; nodes.retry.disabled = busy || !available();
    nodes.status.textContent = message || (current ? ({PREPARING:"로그인 화면을 준비하고 있습니다.", ACTIVE:expired ? "연결 시간이 끝났습니다. 상태를 확인해 주세요." : "로그인 연결이 준비됐습니다.", STOPPING:"로그인 연결을 안전하게 닫고 있습니다.", ENDED:"로그인 연결을 닫았습니다.", ERROR:"로그인 연결을 완료하지 못했습니다. 기존 기록은 보존됩니다."}[current.phase]) : "카카오 로그인은 관리자가 이 연결에서 직접 진행합니다. 대화 수집이나 채널 확인을 자동으로 시작하지 않습니다.");
    nodes.status.className = `form-message${failed ? " error" : ""}`;
    nodes.detail.textContent = current ? `최대 종료 시각: ${new Date(current.absolute_expires_at).toLocaleTimeString("ko-KR", {timeZone:"Asia/Seoul", hour:"2-digit", minute:"2-digit"})}` : "비밀번호나 인증 코드를 이 화면의 일반 입력란에 적지 마세요.";
    const view = Boolean(available() && current?.ready && current.phase === "ACTIVE" && !expired && !failed && (!pending || pending.kind === "RENEW") && viewEnabled);
    if (!view) removeFrame();
    if (view && !frame) {
      frame = node("iframe"); frame.title = "카카오 로그인 원격 화면";
      frame.src = "/studio/admin/remote/vnc.html"; frame.referrerPolicy = "no-referrer";
      frame.setAttribute("sandbox", "allow-scripts allow-same-origin"); nodes.viewport.append(frame);
    }
    nodes.unavailable.hidden = viewEnabled || !current?.ready;
    if (available() && current?.ready && !expired) {
      const token = generation;
      expiryTimer = schedule(() => { expiryTimer = null; if (live(token)) { render(); scheduleNext(); } }, Math.max(1, Date.parse(current.expires_at) - now()));
    }
  }
  function install(container) {
    if (root) return; root = container; root.classList.add("kakao-manual"); root.setAttribute("aria-label", "카카오 로그인");
    nodes.status = node("p", undefined, "form-message"); nodes.status.setAttribute("role", "status"); nodes.status.setAttribute("aria-live", "polite");
    const actions = node("div", undefined, "kakao-toolbar");
    for (const [name, title, callback] of [["start", "카카오 로그인 준비", start], ["refresh", "로그인 상태 확인", refresh], ["end", "로그인 연결 종료", end], ["retry", "같은 로그인 요청 확인", retry]]) {
      nodes[name] = node("button", title, "button quiet"); nodes[name].type = "button";
      nodes[name].dataset.kakaoManual = name; nodes[name].addEventListener("click", () => void callback()); actions.append(nodes[name]);
    }
    nodes.detail = node("p", undefined, "muted-label"); nodes.viewport = node("div", undefined, "kakao-manual-viewport");
    nodes.unavailable = node("p", "서버의 원격 화면 연결이 아직 활성화되지 않았습니다. 카카오 로그인 완료로 처리하지 않습니다.", "form-message");
    root.replaceChildren(node("h3", "카카오 로그인"), nodes.status, actions, nodes.detail, nodes.unavailable, nodes.viewport); render();
  }
  function accept(value, expectedLease = null) {
    const next = checked(value, binding.source_binding_id, expectedLease);
    if (lease?.lease_id === next.lease_id && lease.resource_version > next.resource_version) return;
    lease = next;
  }
  async function mutate(kind, body) {
    if (!available() || busy) return;
    const current = selectedLease();
    if (!intent) intent = {kind, bindingId: binding.source_binding_id, leaseId: kind === "START" ? null : current?.lease_id,
      body, key: `kakao-manual-${crypto.randomUUID()}`, etag: kind === "END" ? `"v${body.expected_resource_version}"` : null};
    const captured = selectedIntent(); if (!captured) { message = "이전 연결의 요청 처리 여부를 먼저 확인해 주세요."; failed = true; render(); return; }
    const token = generation; busy = true; failed = false; message = "요청 처리 상태를 확인하고 있습니다."; stopTimer();
    if (captured.kind !== "RENEW") removeFrame(); render();
    try {
      const path = captured.kind === "START" ? BASE : `${BASE}/${captured.leaseId}/commands`;
      const reply = await api(path, {method:"POST", mutation:true, body:captured.body,
        headers:{"Idempotency-Key":captured.key, ...(captured.etag ? {"If-Match":captured.etag} : {})}});
      if (!live(token) || intent !== captured) return;
      if (typeof reply?.replayed !== "boolean") throw new Error("요청 결과를 확인하지 못했습니다.");
      accept(reply.session, captured.leaseId); intent = null; message = ""; failed = false;
    } catch (error) {
      if (!live(token) || intent !== captured) return;
      failed = true; message = ["KAKAO_ARCHIVE_UNAVAILABLE", "KAKAO_ARCHIVE_REMOTE_RUNTIME_UNAVAILABLE", "KAKAO_ARCHIVE_REMOTE_PROFILE_UNASSIGNED"].includes(error?.code)
        ? "서버의 로그인 연결이 아직 준비되지 않았습니다. 관리자 설정을 확인한 뒤 같은 요청으로 확인할 수 있습니다."
        : `로그인 요청을 확인하지 못했습니다. ${explainError(error)} 같은 요청 확인은 새 로그인 창을 만들지 않습니다.`;
      if (DENIED.has(error?.code)) { lease = null; intent = null; }
    } finally { if (live(token)) { busy = false; render(); scheduleNext(); } }
  }
  async function start() {
    if (!available() || busy || intent || (selectedLease() && selectedLease().phase !== "ENDED")) return;
    await mutate("START", {schema_version:"kakao-manual-start/1.0", source_binding_id:binding.source_binding_id});
  }
  async function renew() {
    const current = selectedLease(); if (!available() || busy || intent || current?.phase !== "ACTIVE" || !current.ready) return;
    if (Date.parse(current.expires_at) <= now()) { render(); return; }
    await mutate("RENEW", {schema_version:"kakao-manual-command/1.0", action:"RENEW", expected_grant_revision:current.grant_revision});
  }
  async function end() {
    const current = selectedLease(); if (!available() || busy || intent || !current || ["STOPPING", "ENDED"].includes(current.phase)) return;
    await mutate("END", {schema_version:"kakao-manual-command/1.0", action:"END", expected_resource_version:current.resource_version});
  }
  async function retry() { const pending = selectedIntent(); if (pending) await mutate(pending.kind, pending.body); }
  async function refresh() {
    const current = selectedLease(); if (!available() || busy || !current) return;
    const token = generation; busy = true; stopTimer(); message = "로그인 상태를 확인하고 있습니다."; render();
    try {
      const result = await api(`${BASE}/${current.lease_id}`);
      if (!live(token)) return;
      accept(result, current.lease_id); message = ""; failed = false;
    } catch (error) {
      if (!live(token)) return;
      failed = true; message = `로그인 상태를 확인하지 못했습니다. ${explainError(error)}`;
      if (DENIED.has(error?.code)) { lease = null; intent = null; }
    } finally { if (live(token)) { busy = false; render(); scheduleNext(); } }
  }
  async function loadConfiguration() {
    if (remoteViewEnabled !== null || !permitted()) return;
    const token = generation;
    try {
      const result = await api("/kakao-archive/remote/configuration");
      if (token !== generation || !permitted()) return;
      viewEnabled = result?.schema_version === "kakao-remote-presentation/1.0" && result.remote_view_enabled === true;
    } catch {
      if (token !== generation || !permitted()) return;
      viewEnabled = false;
    }
    render();
  }
  function invalidate() { generation++; busy = false; stopTimer(); removeFrame(); message = ""; failed = false; if (remoteViewEnabled === null) viewEnabled = false; }
  function setOwner(value) { if (owner === value) return; invalidate(); owner = value || null; binding = null; lease = null; intent = null; roles.clear(); permissions.clear(); render(); }
  function setRoles(values) { invalidate(); roles = new Set(values); render(); }
  function setPermissions(values) { invalidate(); permissions = new Set(values); render(); }
  async function setBinding(value) {
    invalidate(); binding = value && BINDING.test(value.source_binding_id || "") ? value : null; render();
    void loadConfiguration();
    if (available() && selectedLease()) await refresh();
  }
  function open() { active = true; invalidate(); render(); void loadConfiguration(); if (available() && selectedLease()) void refresh(); }
  function close() { active = false; invalidate(); render(); }
  return {install, setOwner, setRoles, setPermissions, setBinding, open, close, refresh};
}
