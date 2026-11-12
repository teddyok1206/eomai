// Presentation only. The server validates current-account model admission and CAS.
const LABELS = {minimal: "최소", low: "낮음", medium: "보통", high: "높음", xhigh: "매우 높음"};

export function createChatModelSettingsEditor({document, api, isAdmin, showMessage}) {
  const $ = selector => document.querySelector(selector);
  let settings = null;
  let version = 0;
  let busy = false;
  let intent = null;
  const message = (text, tone = "neutral") => showMessage($("#chat-model-message"), text, tone);
  const selected = () => ({model: $("#chat-model-select").value, reasoning_effort: $("#chat-model-effort").value});
  function sync() {
    const pair = selected();
    const admitted = settings?.candidates.some(v => v.model === pair.model && v.reasoning_effort === pair.reasoning_effort);
    $("#chat-model-select").disabled = busy || !settings?.candidates.length;
    $("#chat-model-effort").disabled = busy || !pair.model;
    $("#chat-model-save").disabled = busy || !isAdmin() || !admitted;
    $("#chat-model-refresh").disabled = busy || !isAdmin();
  }
  function option(select, value, text, selected = false) {
    const node = document.createElement("option");
    node.value = value; node.textContent = text; node.selected = selected; select.append(node);
  }
  function efforts(preferred) {
    const node = $("#chat-model-effort"); node.replaceChildren();
    const values = settings?.candidates.filter(v => v.model === $("#chat-model-select").value) || [];
    if (!values.length) option(node, "", "모델을 먼저 선택하세요");
    for (const pair of values) option(node, pair.reasoning_effort, LABELS[pair.reasoning_effort], pair.reasoning_effort === preferred);
  }
  function reset() {
    version += 1; settings = null; intent = null; busy = false;
    $("#chat-model-select").replaceChildren(); $("#chat-model-effort").replaceChildren();
    $("#chat-model-current").textContent = "설정 확인 전"; message(""); sync();
  }
  async function refresh() {
    if (!isAdmin() || busy) return;
    const read = ++version; busy = true; sync();
    try {
      const value = await api("/admin/general-chat/model-settings");
      if (read !== version || !isAdmin()) return;
      if (!Array.isArray(value.candidates) || !Number.isInteger(value.resource_version) || value.resource_version < 1
          || value.applies_to !== "NEXT_TURN" || value.dedicated_slot !== "06") throw new Error("설정 응답을 확인하지 못했습니다.");
      settings = value; intent = null;
      const node = $("#chat-model-select"); node.replaceChildren();
      const models = [...new Set(value.candidates.map(v => v.model))].sort();
      const current = value.current;
      if (!current || !models.includes(current.model)) option(node, "", models.length ? "모델을 선택하세요" : "슬롯 상태·모델 목록 확인 필요", true);
      for (const model of models) option(node, model, model, model === current?.model);
      efforts(current?.reasoning_effort);
      $("#chat-model-current").textContent = current ? `${current.model} · ${LABELS[current.reasoning_effort]}` : "설치 기본값 사용 중";
      message("");
    } catch (error) {
      if (read === version && isAdmin()) {settings = null; message(`채팅 모델 설정 조회 실패: ${error.message}`, "error");}
    } finally {if (read === version) {busy = false; sync();}}
  }
  async function save(event) {
    event.preventDefault();
    if (busy || !settings || !isAdmin() || $("#chat-model-save").disabled) return;
    const pair = selected();
    if (!intent) intent = {...pair, resource_version: settings.resource_version, idempotency_key: `chat-model:${crypto.randomUUID()}`};
    const request = intent; const edit = version; busy = true; sync();
    try {
      const result = await api("/admin/general-chat/model-settings", {method: "POST", mutation: true, body: request});
      if (edit !== version || !isAdmin()) return;
      if (result.status !== "COMPLETED" || !/^chatmodelrev_[0-9a-f]{32}$/.test(result.resource_id)
          || result.resource_version !== request.resource_version + 1) throw new Error("설정 저장 결과를 확인하지 못했습니다.");
      settings = {...settings, current: pair, resource_version: result.resource_version, revision_id: result.resource_id};
      intent = null;
      $("#chat-model-current").textContent = `${pair.model} · ${LABELS[pair.reasoning_effort]}`;
      message("저장했습니다. 다음 답변부터 적용되며 작성 중인 답변은 바뀌지 않습니다.", "success");
    } catch (error) {if (edit === version) message(`채팅 모델 설정 저장 실패: ${error.message}`, "error");}
    finally {if (edit === version) {busy = false; sync();}}
  }
  function install() {
    $("#chat-model-form").addEventListener("submit", save);
    $("#chat-model-refresh").addEventListener("click", refresh);
    $("#chat-model-select").addEventListener("change", () => {intent = null; efforts(); sync();});
    $("#chat-model-effort").addEventListener("change", () => {intent = null; sync();});
    reset();
  }
  return {install, refresh, reset};
}
