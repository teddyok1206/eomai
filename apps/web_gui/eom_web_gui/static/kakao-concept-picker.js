// Optional shared-slot recommendation UI. All source/model authority stays on the server.
const BASE = "/kakao-archive";
const ID = /^[a-z][a-z0-9_]{1,48}_[a-f0-9]{32}$/;
const PAGE = /^E[1-3]P[1-9][0-9]{0,4}$/;
function id(value) { if (typeof value !== "string" || !ID.test(value)) throw new Error("질문 연결을 확인해 주세요."); return encodeURIComponent(value); }
const STATES = {PREPARING:"질문 준비 중",PLAN_PENDING:"개념 찾기 대기",PLAN_RUNNING:"관련 개념 정리 중",SEARCHING:"교과서 자료 검색 중",COMPOSE_PENDING:"설명 작성 대기",COMPOSE_RUNNING:"설명 작성 중",COMPLETED:"교과서 추천 완료",NEEDS_INPUT:"추가 정보가 필요합니다",FAILED:"추천 실패 · 이전 기록 보존",CANCELLED:"추천 취소됨"};

export function createKakaoConceptPicker({document, api, explainError, canEdit, onSelect, schedule = setTimeout, unschedule = clearTimeout}) {
  let root = null, context = null, generation = 0, timer = null, busy = false, intent = null, result = null, pendingTask = null;
  let instructions = "", summaries = [], cursor = null, message = "";
  function el(tag, text) { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; return node; }
  function button(text, action) { const node = el("button", text); node.type = "button"; node.className = "button quiet"; node.disabled = busy || !canEdit(); node.addEventListener("click", action); return node; }
  function stop() { if (timer !== null) unschedule(timer); timer = null; }
  function clear() { generation++; stop(); root = null; context = null; intent = null; result = null; pendingTask = null; instructions = ""; summaries = []; cursor = null; busy = false; message = ""; }
  function live(token) { return root && context && token === generation; }
  function matches(task) { return task?.source_binding_id === context.binding && task.question_id === context.questionId && task.question_revision_id === context.revision; }
  function fail(error) { message = explainError(error); }
  function mount(container, value) {
    if (context && (context.binding !== value.binding || context.questionId !== value.questionId || context.revision !== value.revision)) clear();
    context = {...value}; root = container; render();
  }
  function render() {
    if (!root) return; root.replaceChildren(); root.className = "kakao-concept-picker";
    root.append(el("h6", "교과서로 보충하기"), el("p", "사용 가능한 작업 슬롯에서 관련 교과서 개념을 찾아 설명 초안을 씁니다. 선택한 내용만 PDF에 넣습니다. 교과서가 뒷받침하는 범위를 넘는 설명은 근거로 표시하지 않습니다."));
    const label = el("label", "찾아볼 개념이나 추가 요청 (선택)"), field = el("textarea"); field.rows = 2; field.maxLength = 6000; field.value = instructions; field.disabled = busy || !!intent || !canEdit(); field.addEventListener("input", () => { instructions = field.value; }); label.append(field); root.append(label);
    root.append(button(intent ? "같은 추천 요청 확인" : "교과서 개념 추천", () => void start()), button("이 질문의 추천 작업 보기", () => void history()));
    const note = el("p", message || (result ? STATES[result.state] : "추천을 요청하거나 이전 추천을 열어 주세요.")); note.setAttribute("role", "status"); root.append(note);
    for (const row of summaries) { const date = new Date(row.created_at).toLocaleString("ko-KR", {timeZone:"Asia/Seoul"}); root.append(button(`${date} · 추천 열기`, () => void read(row.task_id))); }
    if (cursor) root.append(button("추천 작업 더 보기", () => void history(cursor)));
    if (pendingTask || result) root.append(button("추천 상태 확인", () => void read(pendingTask || result.task.task_id)));
    if (!result) return;
    root.append(el("p", result.focus_summary));
    for (const limitation of result.limitations) root.append(el("p", `자료 범위 안내: ${limitation}`));
    for (const check of result.staff_checks) root.append(el("p", `조교 답변 확인 메모: ${check}`));
    if (result.state !== "COMPLETED" || !result.result_sha256) return;
    if (!result.blocks.length) root.append(el("p", "이 질문에 적절한 교과서 자료를 찾지 못했습니다. 직접 설명을 추가할 수 있습니다."));
    const choices = new Map();
    for (const [index, block] of result.blocks.entries()) {
      const box = el("fieldset"), legend = el("legend", block.title); box.append(legend);
      const choose = el("input"); choose.type = "checkbox"; choose.disabled = busy || !canEdit();
      const previous = context.selected?.concept_task_id === result.task.task_id ? context.selected.blocks.find(value => value.block_index === index) : null;
      choose.checked = !!previous; const use = el("label", "이 개념 넣기"); use.prepend(choose); box.append(use);
      box.append(el("p", block.relevance), el("p", block.explanation));
      for (const citation of block.citations) box.append(el("p", `${citation.title} · ${citation.location} · ${citation.kind === "ORIGINAL_PASSAGE" ? "교재 원문 인용: " + citation.quote : "승인된 교재 분석을 참고한 설명 (원문 인용 아님)"}`));
      const captures = [];
      for (const [captureIndex, capture] of block.captures.entries()) {
        if (!PAGE.test(capture.page_key)) throw new Error("교과서 그림 연결을 확인해 주세요.");
        const figure = el("figure"), frame = el("div"), image = el("img"), mark = el("span"); frame.className = "kakao-concept-page";
        const query = new URLSearchParams({source_binding_id:context.binding}); image.src = `/studio/api/v1${BASE}/concepts/${id(result.task.task_id)}/pages/${capture.page_key}?${query}`; image.loading = "lazy"; image.alt = `${capture.source_title} · 원본 ${capture.physical_page}쪽`;
        const rect = capture.rectangle; mark.className = "kakao-concept-region"; mark.style.left = `${rect.x*100}%`; mark.style.top = `${rect.y*100}%`; mark.style.width = `${rect.width*100}%`; mark.style.height = `${rect.height*100}%`; frame.append(image, mark);
        const check = el("input"); check.type = "checkbox"; check.checked = !!previous && (previous.capture_indices === null || previous.capture_indices.includes(captureIndex)); check.disabled = busy || !canEdit();
        const caption = el("label", `표시한 교과서 그림 넣기 · ${capture.reason}`); caption.prepend(check); figure.append(frame, caption); box.append(figure); captures.push(check);
      }
      choices.set(index, {choose, captures}); root.append(box);
    }
    if (result.blocks.length) root.append(button("선택한 개념·그림 반영", () => {
      if (busy || !canEdit()) return;
      const blocks = [...choices].filter(([,value]) => value.choose.checked).map(([block_index,value]) => {
        const previous = context.selected?.concept_task_id === result.task.task_id ? context.selected.blocks.find(value => value.block_index === block_index) : null;
        return {block_index,title:previous?.title ?? null,relevance:previous?.relevance ?? null,explanation:previous?.explanation ?? null,capture_indices:value.captures.flatMap((check,index) => check.checked ? [index] : [])};
      });
      onSelect(blocks.length ? result.task.task_id : null, blocks); message = "선택한 내용이 편집본에 반영됐습니다. 설명 자료 저장을 눌러 주세요."; render();
    }));
  }
  async function start() {
    if (!context || busy || !canEdit()) return; const token = generation; busy = true; stop(); render();
    try {
      if (!intent) {
        const query = new URLSearchParams({source_binding_id:context.binding});
        const value = await api(`${BASE}/questions/${id(context.questionId)}/revisions/${id(context.revision)}?${query}`);
        if (!live(token)) return;
        const question = value.question;
        if (!question || question.source_binding_id !== context.binding || question.question_id !== context.questionId || question.question_revision_id !== context.revision || question.student?.student_id !== context.student) throw new Error("학생·질문 버전을 다시 확인해 주세요.");
        intent = {key:`kakao-concept-${crypto.randomUUID()}`,body:{schema_version:"kakao-concept-create/1.0",source_binding_id:context.binding,room_id:question.room_id,question_id:context.questionId,question_revision_id:context.revision,expected_question_version:question.resource_version,base_study_revision_id:null,additional_instructions:instructions}};
      }
      const sent = intent, value = await api(`${BASE}/concepts`, {method:"POST",mutation:true,headers:{"Idempotency-Key":sent.key},body:sent.body});
      if (!live(token) || intent !== sent) return;
      if (!matches(value.task) || typeof value.replayed !== "boolean") throw new Error("추천 작업의 질문 연결이 다릅니다.");
      id(value.task.task_id); pendingTask = value.task.task_id; intent = null; result = null; message = "개념 추천을 요청했습니다. 화면을 닫아도 수락된 작업은 이어집니다.";
      timer = schedule(() => void read(pendingTask), 1000);
    } catch (error) { if (live(token)) fail(error); }
    finally { if (live(token)) { busy = false; render(); } }
  }
  async function read(task) {
    if (!context || busy || !task) return; const token = generation; busy = true; stop(); render();
    try {
      const query = new URLSearchParams({source_binding_id:context.binding}), value = await api(`${BASE}/concepts/${id(task)}?${query}`);
      if (!live(token)) return;
      if (!matches(value.task) || value.task.task_id !== task || !STATES[value.state]) throw new Error("추천 결과의 질문 연결이 다릅니다.");
      result = value; pendingTask = null; message = STATES[value.state];
      if (!["COMPLETED","NEEDS_INPUT","FAILED","CANCELLED"].includes(value.state)) timer = schedule(() => void read(task), 8000);
    } catch (error) { if (live(token)) fail(error); }
    finally { if (live(token)) { busy = false; render(); } }
  }
  async function history(after = null) {
    if (!context || busy) return; const token = generation; busy = true; render();
    try {
      const query = new URLSearchParams({source_binding_id:context.binding,limit:"100"}); if (after) query.set("cursor", after);
      const value = await api(`${BASE}/concepts?${query}`); if (!live(token)) return;
      if (!Array.isArray(value.items) || value.items.length > 100) throw new Error("추천 작업 목록을 확인하지 못했습니다.");
      summaries = (after ? summaries : []).concat(value.items.filter(matches)); cursor = value.next_cursor; message = summaries.length ? "이 질문의 추천 작업을 열어 주세요. 목록은 작업 식별 순서입니다." : "이 질문의 추천 작업이 없습니다.";
    } catch (error) { if (live(token)) fail(error); }
    finally { if (live(token)) { busy = false; render(); } }
  }
  return {mount, clear};
}
