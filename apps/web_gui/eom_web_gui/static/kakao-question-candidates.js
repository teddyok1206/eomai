// Read accepted candidates; all grouping, identity and persistence stay in Catalog.
const BASE = "/kakao-archive/questions";
const ID = prefix => new RegExp(`^${prefix}_[a-f0-9]{32}$`);
const SOURCE = ID("kakaosourcerev"), QUESTION = ID("kakaoquestion"), REVISION = ID("kakaoquestionrev");
const SHA = /^sha256:[a-f0-9]{64}$/;

function pageValue(value, binding, room, source, hash, after) {
  if (value?.schema_version !== "kakao-question-candidate-page/1.0" || value.source_binding_id !== binding || value.room_id !== room ||
      !ID("kakaomappingrev").test(value.mapping_revision_id || "") || !Number.isInteger(value.total_candidates) || value.total_candidates < 0 || value.total_candidates > 100000 ||
      !Number.isInteger(value.unknown_sender_rows) || value.unknown_sender_rows < 0 || value.unknown_sender_rows > 100000 ||
      !Array.isArray(value.items) || value.items.length > 50 || (source && (value.source_revision_id !== source || value.source_resolution_sha256 !== hash))) throw new Error("질문 후보의 원본 연결을 확인하지 못했습니다.");
  if (value.source_revision_id === null) {
    if (value.source_resolution_sha256 !== null || value.total_candidates || value.items.length || value.next_after_ordinal !== null) throw new Error("수락한 원본 정보를 확인하지 못했습니다.");
  } else if (!SOURCE.test(value.source_revision_id || "") || !SHA.test(value.source_resolution_sha256 || "")) throw new Error("원본 버전을 확인하지 못했습니다.");
  for (const [i, row] of value.items.entries()) {
    if (row.candidate_ordinal !== after + i + 1 || typeof row.preview !== "string" || [...row.preview].length > 240 || typeof row.recomposed !== "boolean" || typeof row.boundary_uncertain !== "boolean" ||
        !Array.isArray(row.review_reasons) || row.review_reasons.length > 8 || row.review_reasons.some(value => typeof value !== "string") ||
        !Number.isInteger(row.student_message_count) || row.student_message_count < 1 || !Number.isInteger(row.reply_message_count) || row.reply_message_count < 0 || !Number.isInteger(row.photo_count) || row.photo_count < 0 ||
        row.saved_question !== null && (!QUESTION.test(row.saved_question?.question_id || "") || !REVISION.test(row.saved_question?.question_revision_id || "")) || row.recomposed && row.saved_question === null) throw new Error("질문 후보를 확인하지 못했습니다.");
  }
  const last = value.items.at(-1)?.candidate_ordinal;
  if (value.next_after_ordinal !== (last && last < value.total_candidates ? last : null)) throw new Error("다음 후보 위치를 확인하지 못했습니다.");
  return value;
}

async function requestKey(body) {
  // The existing create command is flat. The same command survives reloads with
  // one key, rather than relying on a process-local UUID after a lost response.
  const raw = new TextEncoder().encode(JSON.stringify(body, Object.keys(body).sort()));
  const hash = await crypto.subtle.digest("SHA-256", raw);
  return "kakao-candidate-" + [...new Uint8Array(hash)].map(value => value.toString(16).padStart(2, "0")).join("");
}

export function createKakaoQuestionCandidates({document, api, explainError, onSaved, onOpen}) {
  let root, owner = null, binding = null, room = null, active = false, permissions = new Set();
  let generation = 0, read = 0, loading = false, pending = null, page = null, selection = null, intent = null, notice = "";
  const allowed = () => active && owner && binding && room && permissions.has("kakao_archive:read") && permissions.has("kakao_archive:edit");
  const live = token => allowed() && token === generation;
  function el(tag, text, className = "") { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; node.className = className; return node; }
  function button(text, action) { const node = el("button", text, "button quiet"); node.type = "button"; node.addEventListener("click", action); return node; }
  function clear() { generation++; read++; loading = false; page = selection = null; notice = ""; render(); }
  function render() {
    if (!root) return;
    root.replaceChildren(); root.hidden = !allowed();
    if (!allowed()) return;
    root.append(el("h3", "원본에서 질문 가져오기"), el("p", "이미 수락한 대화에서 질문을 찾습니다. 카카오를 새로 수집하지 않습니다.", "muted-label"));
    const refresh = button(page ? "후보 다시 확인" : "원본에서 질문 찾기", () => void load()); refresh.disabled = loading || pending; root.append(refresh);
    if (selection) {
      const fresh = button("새로 받은 원본 확인", () => { if (pending || intent && !intent.receipt) return; page = selection = null; void load(); });
      fresh.disabled = loading || pending || Boolean(intent && !intent.receipt); root.append(fresh);
      if (page) root.append(el("p", `이 원본에서 찾은 질문 ${page.total_candidates}개 · 작성자 확인이 필요한 메시지 ${page.unknown_sender_rows}개`, "muted-label"));
    } else if (page) root.append(el("p", "이 방에는 아직 수락한 대화 원본이 없습니다.", "empty-state"));
    if (room.mapping?.state !== "MAPPED") root.append(el("p", "먼저 대화방을 학생과 연결해 주세요. 연결한 뒤 질문을 저장할 수 있습니다.", "form-message"));
    for (const row of page?.items || []) {
      const item = el("div", undefined, "kakao-composition-block");
      item.append(el("strong", `질문 후보 ${row.candidate_ordinal}`), el("p", row.preview || "사진이 포함된 질문", "kakao-message-text"),
        el("small", `학생 메시지 ${row.student_message_count}개 · 답변 ${row.reply_message_count}개 · 학생 사진 ${row.photo_count}개`));
      if (row.recomposed) item.append(el("p", "이미 나누거나 합쳐 저장했습니다. 질문 목록에서 편집 결과를 확인해 주세요.", "muted-label"));
      else if (row.saved_question) item.append(button("저장한 질문 열기", () => { if (allowed() && !pending) void onOpen(row.saved_question); }));
      else {
        const save = button("질문으로 저장", () => void saveCandidate(row));
        save.disabled = loading || pending || Boolean(intent && !intent.receipt) || room.mapping?.state !== "MAPPED" || room.mapping.mapping_revision_id !== page.mapping_revision_id;
        item.append(save);
      }
      if (row.boundary_uncertain || row.review_reasons.length) item.append(el("p", "저장한 뒤 원문·사진과 질문 범위를 확인해 주세요.", "muted-label"));
      root.append(item);
    }
    if (page?.next_after_ordinal) { const next = button("다음 후보 보기", () => void load(page.next_after_ordinal)); next.disabled = loading || pending; root.append(next); }
    if (intent && intent.owner === owner && intent.body.source_binding_id === binding.source_binding_id && intent.body.room_id === room.room_id) {
      const retry = button(intent.receipt ? "저장 결과 다시 열기" : "같은 저장 요청 확인", () => void submit(intent)); retry.disabled = pending; root.append(retry);
    } else if (intent && !intent.receipt) root.append(el("p", "앞서 저장한 방을 다시 선택해 같은 요청의 처리 여부를 확인해 주세요.", "form-message"));
    const message = el("p", notice, "form-message"); message.setAttribute("role", "status"); root.append(message);
  }
  async function load(after = 0) {
    if (!allowed() || pending) return;
    const token = generation, request = ++read, selected = selection;
    loading = true; notice = "수락한 대화의 질문 후보를 확인하고 있습니다."; render();
    const query = new URLSearchParams({source_binding_id:binding.source_binding_id,room_id:room.room_id,limit:"50",after_ordinal:String(after)});
    if (selected) query.set("source_revision_id", selected.revision);
    try {
      const result = await api(`${BASE}/candidates?${query}`);
      if (!live(token) || request !== read) return;
      page = pageValue(result, binding.source_binding_id, room.room_id, selected?.revision, selected?.hash, after);
      selection = page.source_revision_id ? {revision:page.source_revision_id,hash:page.source_resolution_sha256} : null;
      notice = "저장된 질문과 수동 편집 결과는 다시 가져와도 덮어쓰지 않습니다.";
    } catch (error) { if (live(token) && request === read) { page = null; notice = `후보를 확인하지 못했습니다. ${error.code ? explainError(error) : error.message}`; } }
    finally { if (live(token) && request === read) { loading = false; render(); } }
  }
  async function saveCandidate(row) {
    if (!allowed() || loading || pending || intent && !intent.receipt || !page?.source_revision_id || row.saved_question || room.mapping?.state !== "MAPPED" || room.mapping.mapping_revision_id !== page.mapping_revision_id) return;
    const token = generation;
    const body = {schema_version:"kakao-question-create/1.0",source_binding_id:binding.source_binding_id,room_id:room.room_id,source_revision_id:page.source_revision_id,candidate_ordinal:row.candidate_ordinal,expected_mapping_revision_id:page.mapping_revision_id};
    const preparation = {}; pending = preparation; render();
    try {
      const key = await requestKey(body);
      if (!live(token)) return;
      intent = {owner,body,key,receipt:null};
    } catch { if (live(token)) notice = "저장 요청을 준비하지 못했습니다. 다시 확인해 주세요."; }
    finally { if (pending === preparation) { pending = null; render(); } }
    if (live(token) && intent?.body === body) await submit(intent);
  }
  async function submit(current) {
    if (!allowed() || pending || intent !== current || current.owner !== owner || current.body.source_binding_id !== binding.source_binding_id || current.body.room_id !== room.room_id) return;
    const token = generation, attempt = {}; pending = attempt; notice = "질문 저장 결과를 확인하고 있습니다."; render();
    try {
      if (!current.receipt) {
        const result = await api(BASE, {method:"POST",mutation:true,body:current.body,headers:{"Idempotency-Key":current.key}});
        if (owner !== current.owner || intent !== current) return;
        const saved = result?.question;
        if (saved?.source_binding_id !== current.body.source_binding_id || saved.room_id !== current.body.room_id || !QUESTION.test(saved.question_id || "") || !REVISION.test(saved.question_revision_id || "")) throw new Error("저장 결과의 연결을 확인하지 못했습니다.");
        current.receipt = saved;
        if (live(token) && page?.source_revision_id === current.body.source_revision_id) page = {...page,items:page.items.map(row => row.candidate_ordinal === current.body.candidate_ordinal ? {...row,saved_question:{question_id:saved.question_id,question_revision_id:saved.question_revision_id}} : row)};
      }
      if (live(token)) { const opened = await onSaved(current.receipt); if (live(token)) notice = opened === false ? "저장했습니다. ‘저장 결과 다시 열기’를 눌러 확인해 주세요." : "질문을 저장했습니다. 원문과 사진을 확인해 주세요."; }
    } catch (error) { if (live(token)) notice = current.receipt ? "질문은 저장됐지만 화면을 열지 못했습니다. 저장 결과만 다시 열 수 있습니다." : `처리 여부를 확인하지 못했습니다. 같은 요청으로 다시 확인할 수 있습니다. ${error.code ? explainError(error) : error.message}`; }
    finally { if (pending === attempt) { pending = null; render(); } }
  }
  return {
    install(container) { root = container; render(); },
    setOwner(value) { if (owner === value) return; owner = value || null; binding = room = intent = pending = null; permissions = new Set(); clear(); },
    setPermissions(values) { permissions = new Set(values); clear(); },
    setBinding(value) { binding = value; room = null; clear(); },
    setRoom(value) { room = value; clear(); },
    open() { active = true; clear(); },
    close() { active = false; clear(); },
  };
}
