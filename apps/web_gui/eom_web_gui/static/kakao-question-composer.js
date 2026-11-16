// Presentation of the existing atomic composition command, not a second editing engine.
const ID = /^kakaoquestion_[a-f0-9]{32}$/;
const REVISION = /^kakaoquestionrev_[a-f0-9]{32}$/;
const REJECTED = new Set(["KAKAO_ARCHIVE_REQUEST_INVALID", "KAKAO_ARCHIVE_PRECONDITION_FAILED",
  "KAKAO_ARCHIVE_COMPOSITION_SCOPE_INVALID", "KAKAO_ARCHIVE_QUESTION_EDIT_INVALID",
  "KAKAO_ARCHIVE_QUESTION_SELECTION_INVALID"]);

function inputOf(question) {
  if (!ID.test(question?.question_id || "") || !REVISION.test(question.question_revision_id || "") ||
      !Number.isInteger(question.resource_version) || question.resource_version < 1 || question.resource_version > 2147483646) {
    throw new Error("질문의 저장 버전을 확인해 주세요.");
  }
  return {question_id: question.question_id, question_revision_id: question.question_revision_id, resource_version: question.resource_version};
}

function checkResult(body, result) {
  const inputs = body.operation === "SPLIT" ? [body.input] : body.inputs;
  const expected = body.operation === "SPLIT" ? body.partitions.length : 1;
  if (result?.schema_version !== "kakao-question-composition-result/1.0" || result.operation !== body.operation ||
      result.source_binding_id !== body.source_binding_id || result.room_id !== body.room_id ||
      !Array.isArray(result.inputs) || result.inputs.length !== inputs.length ||
      result.inputs.some((item, i) => Object.keys(inputs[i]).some(key => item[key] !== inputs[i][key])) ||
      !Array.isArray(result.outputs) || result.outputs.length !== expected) throw new Error("저장 결과의 연결 정보를 확인하지 못했습니다.");
  const seen = new Set(inputs.map(item => item.question_id));
  for (const output of result.outputs) {
    inputOf(output);
    if (seen.has(output.question_id) || output.source_binding_id !== body.source_binding_id || output.room_id !== body.room_id || output.resource_version !== 1) {
      throw new Error("다른 질문의 저장 결과입니다.");
    }
    seen.add(output.question_id);
  }
}

export function createKakaoQuestionComposer({document, api, explainError, onSaved, captureView = () => null}) {
  let root = null, owner = null, binding = null, editable = false, active = false, epoch = 0;
  let draft = null, intent = null, notice = "";
  const el = (tag, text, className = "") => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; };
  function button(text, action) { const node = el("button", text, "button quiet"); node.type = "button"; node.addEventListener("click", () => { if (available() && root.contains(node) && !node.disabled) action(); }); return node; }
  const available = () => active && owner && editable && binding && binding.state !== "RETIRED";
  function render() {
    if (!root) return;
    root.replaceChildren(); root.hidden = !available();
    if (!available()) return;
    if (intent) {
      const same = intent.body.source_binding_id === binding.source_binding_id;
      root.append(el("h3", "질문 구성 저장"), el("p", same ?
        "앞선 요청의 결과를 확인합니다. 원문·사진과 이미 만든 자료는 그대로 보존됩니다." :
        "다른 채널에 확인할 저장 요청이 있습니다. 해당 채널을 다시 선택해 주세요.", "muted-label"));
      if (same) {
        const retry = button(intent.result ? "저장한 질문 열기" : "같은 저장 요청 확인", () => void submit());
        retry.disabled = intent.busy; root.append(retry);
        root.append(el("p", intent.note || "저장 결과를 확인하고 있습니다.", "form-message"));
      }
      return;
    }
    if (!draft) { root.append(el("p", notice || "질문 목록에서 합칠 질문을 고르거나, 질문을 열어 나눌 위치를 선택할 수 있습니다.", "muted-label")); return; }
    root.append(el("h3", draft.operation === "SPLIT" ? "질문 나누기" : "질문 합치기"));
    root.append(el("p", "원문·사진은 바뀌지 않습니다. 새 질문으로 저장하며 기존 자료는 그대로 남습니다.", "muted-label"));
    if (draft.operation === "SPLIT") {
      root.append(el("p", "새 질문이 시작할 위치를 골라 주세요. 문장 내부가 아니라 메시지·사진 사이에서 나눕니다.", "muted-label"));
      draft.blocks.forEach((block, i) => {
        const row = el("div", undefined, "kakao-composition-block");
        row.append(el("p", `${i + 1}. ${block.kind === "IMAGE" ? "사진" : block.text}`, "kakao-message-text"));
        if (i < draft.blocks.length - 1) {
          const label = el("label", undefined, "kakao-review-check"), check = el("input"); check.type = "checkbox";
          check.checked = draft.cuts.has(i + 1);
          const selectedDraft = draft;
          check.addEventListener("change", () => { if (!available() || intent || draft !== selectedDraft || !root.contains(check)) return; if (check.checked) draft.cuts.add(i + 1); else draft.cuts.delete(i + 1); });
          label.append(check, el("span", `${i + 2}번째 내용부터 새 질문`)); row.append(label);
        }
        root.append(row);
      });
    } else {
      root.append(el("p", "아래 순서대로 하나의 질문이 됩니다. 필요하면 순서를 바꿔 주세요.", "muted-label"));
      const items = [...draft.items.values()];
      items.forEach((item, index) => {
        const row = el("div", undefined, "kakao-composition-row"); row.append(el("span", `${index + 1}. ${item.label}`));
        for (const [label, delta] of [["위로", -1], ["아래로", 1]]) {
          const move = button(label, () => { const target = index + delta; [items[index], items[target]] = [items[target], items[index]]; draft.items = new Map(items.map(entry => [entry.input.question_id, entry])); render(); });
          move.disabled = index + delta < 0 || index + delta >= items.length; row.append(move);
        }
        row.append(button("빼기", () => { draft.items.delete(item.input.question_id); render(); })); root.append(row);
      });
    }
    const save = button("새 질문으로 저장", () => void submit());
    save.disabled = draft.operation === "SPLIT" ? draft.blocks.length < 2 : draft.items.size < 2;
    root.append(save, button("선택 비우기", () => { draft = null; render(); }));
    const note = el("p", draft.note || "", "form-message"); note.setAttribute("role", "status"); root.append(note);
  }
  function body() {
    const scope = {schema_version: "kakao-question-compose/1.0", operation: draft.operation, source_binding_id: binding.source_binding_id, room_id: draft.room};
    if (draft.operation === "MERGE") return {...scope, inputs: [...draft.items.values()].map(item => item.input)};
    const partitions = [], cuts = draft.cuts;
    let part = [];
    draft.blocks.forEach((block, index) => {
      if (cuts.has(index)) { partitions.push(part); part = []; }
      part.push({kind: "BLOCK", block_id: block.block_id});
    });
    partitions.push(part);
    if (partitions.length < 2 || partitions.length > 100) throw new Error("나눌 위치를 1~99개 선택해 주세요.");
    return {...scope, input: draft.input, partitions};
  }
  async function submit() {
    if (!available() || intent?.busy || (intent && intent.body.source_binding_id !== binding.source_binding_id)) return;
    if (!intent) {
      try { intent = {body: body(), key: `kakao-compose-${globalThis.crypto.randomUUID()}`, busy: false, result: null, note: ""}; }
      catch (error) { draft.note = error.message; render(); return; }
    }
    const selected = intent, token = epoch, view = captureView();
    selected.busy = true; selected.note = selected.result ? "저장한 질문을 열고 있습니다." : "질문 구성을 저장하고 있습니다."; render();
    try {
      if (!selected.result) {
        const result = await api("/kakao-archive/questions/compose", {method: "POST", mutation: true, headers: {"Idempotency-Key": selected.key}, body: selected.body});
        if (token !== epoch || intent !== selected) return;
        checkResult(selected.body, result); selected.result = result;
        selected.note = "질문 저장이 완료됐습니다. 저장한 질문을 열어 확인해 주세요.";
      }
      if (available() && selected.body.source_binding_id === binding.source_binding_id) {
        const opened = await onSaved(selected.result, view);
        if (token !== epoch || intent !== selected) return;
        if (opened !== false) { draft = null; intent = null; notice = "새 질문을 저장했습니다. 기존 자료와 원문은 그대로 보존됩니다."; }
        else selected.note = "질문 저장이 완료됐습니다. 저장한 질문을 열어 확인해 주세요.";
      }
    } catch (error) {
      if (token !== epoch || intent !== selected) return;
      if (["KAKAO_ARCHIVE_PERMISSION_DENIED", "KAKAO_ARCHIVE_RESOURCE_NOT_FOUND"].includes(error.code)) editable = false;
      if (!selected.result && REJECTED.has(error.code)) { intent = null; if (draft) draft.note = explainError(error); else notice = explainError(error); }
      else selected.note = selected.result ? `저장은 완료됐습니다. 목록을 다시 열어 주세요. ${explainError(error)}` : `결과를 확인하지 못했습니다. 같은 요청으로 다시 확인할 수 있습니다. ${explainError(error)}`;
    } finally { selected.busy = false; if (token === epoch) render(); }
  }
  function split(view) {
    if (!available() || intent) return false;
    const question = view.question, blocks = view.ordered_blocks;
    if (question.source_binding_id !== binding.source_binding_id || !Array.isArray(blocks) || blocks.length < 1 || blocks.length > 230 ||
        new Set(blocks.map(block => block.block_id)).size !== blocks.length || blocks.some(block => !["TEXT", "IMAGE"].includes(block.kind) || typeof block.block_id !== "string")) throw new Error("질문 구성을 확인해 주세요.");
    draft = {operation: "SPLIT", room: question.room_id, input: inputOf(question), blocks, cuts: new Set(), note: ""}; render(); return true;
  }
  function add(question) {
    if (!available() || intent || question.source_binding_id !== binding.source_binding_id) return false;
    const input = inputOf(question);
    if (draft?.operation !== "MERGE") draft = {operation: "MERGE", room: question.room_id, items: new Map(), note: ""};
    if (draft.room !== question.room_id) { draft.note = "같은 대화방의 질문을 골라 주세요. 다른 방의 질문은 섞지 않습니다."; render(); return false; }
    const entry = {input, label: `${question.student?.display_name || "학생 미연결"} · ${question.first_student_at_utc ? new Date(question.first_student_at_utc).toLocaleString("ko-KR", {timeZone: "Asia/Seoul"}) : "시각 확인 필요"}`};
    if (draft.items.has(input.question_id) || draft.items.size < 100) draft.items.set(input.question_id, entry);
    else draft.note = "한 번에 최대 100개 질문을 고를 수 있습니다.";
    render(); return true;
  }
  function reset() { epoch++; draft = null; intent = null; notice = ""; }
  return {
    install(node) { root = node; root.setAttribute("aria-label", "질문 구성 편집"); render(); }, split, add,
    setOwner(value) { if (value !== owner) { reset(); owner = value; binding = null; editable = false; } render(); },
    setPermissions(values) { editable = values.includes("kakao_archive:edit") && values.includes("kakao_archive:read"); render(); },
    setBinding(value) { if (value?.source_binding_id !== binding?.source_binding_id) draft = null; binding = value; render(); },
    open() { active = true; render(); }, close() { active = false; draft = null; render(); },
  };
}
