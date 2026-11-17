// Presentation of exact saved selections. Catalog owns grouping, approval and rendering.
import {createKakaoStudyEditor} from "./kakao-study-editor.js";
const BASE = "/kakao-archive", ID = /^[a-z][a-z0-9_]{1,48}_[a-f0-9]{32}$/;
const SELECTION_REFUSALS = new Set(["KAKAO_ARCHIVE_FINAL_BLOCKED", "KAKAO_ARCHIVE_QUESTION_OUTSIDE_PERIOD", "KAKAO_ARCHIVE_STUDENT_DISPLAY_CONFLICT", "KAKAO_ARCHIVE_PERIOD_INVALID", "KAKAO_ARCHIVE_STUDENT_UNMAPPED", "KAKAO_ARCHIVE_QUESTION_EXCLUDED", "KAKAO_ARCHIVE_EMPTY_SELECTION"]);
function identifier(value) { if (typeof value !== "string" || !ID.test(value)) throw new Error("자료 연결을 확인해 주세요."); return encodeURIComponent(value); }
function page(value) { if (!value || !Array.isArray(value.items) || value.items.length > 100 || !(value.next_cursor === null || typeof value.next_cursor === "string")) throw new Error("목록 형식을 확인하지 못했습니다."); return value; }

export function createKakaoPublications({document, api, explainError, setStateStatus, schedule = setTimeout, unschedule = clearTimeout}) {
  const studyEditor = createKakaoStudyEditor({document, api, explainError, schedule, unschedule});
  let root = null, owner = null, active = false, binding = null, generation = 0, detailGeneration = 0, timer = null;
  let permissions = new Set(), selected = new Map(), packets = new Map(), packetIntent = null, saving = false;
  let currentPacket = null, currentStudents = new Map(), exportIntent = null, exporting = false, observed = null, observing = false;
  const nodes = {};
  function el(tag, text, className = "") { const result = document.createElement(tag); if (text !== undefined) result.textContent = text; if (className) result.className = className; return result; }
  function button(text, callback) { const result = el("button", text, "button quiet"); result.type = "button"; result.addEventListener("click", callback); return result; }
  function live(token) { return active && owner && binding && generation === token && permissions.has("kakao_archive:read"); }
  function writable() { return active && owner && binding && ["DRAFT", "ACTIVE"].includes(binding.state) && permissions.has("kakao_archive:export"); }
  function stop() { if (timer !== null) unschedule(timer); timer = null; }
  function say(text, error = false) { nodes.note.textContent = text; nodes.note.className = `form-message${error ? " error" : ""}`; }
  function badge(value) { const result = el("span", "상태 확인 필요", "status-badge"); setStateStatus?.(result, "kakao_archive", value); return result; }
  function controls() {
    const locked = saving || packetIntent !== null;
    for (const field of [nodes.title, nodes.start, nodes.end, nodes.mode, nodes.replies]) field.disabled = !writable() || locked;
    nodes.save.disabled = !writable() || saving || (!packetIntent && selected.size === 0);
    nodes.save.textContent = packetIntent ? "같은 자료 저장 요청 확인" : "선택한 질문으로 자료 저장";
    nodes.selection.querySelectorAll("button").forEach(value => { value.disabled = locked; });
  }
  function install(container) {
    if (root) return; root = container;
    const form = el("form", undefined, "kakao-packet-form"); form.setAttribute("aria-label", "질문 자료 만들기");
    const fields = [["title", "자료 이름", "text"], ["start", "시작 날짜", "date"], ["end", "마지막 날짜", "date"]];
    for (const [key, name, type] of fields) { const label = el("label", name), input = el("input"); input.type = type; label.append(input); nodes[key] = input; form.append(label); }
    const date = new Intl.DateTimeFormat("sv-SE", {timeZone: "Asia/Seoul"}).format(new Date());
    nodes.start.value = date; nodes.end.value = date; nodes.title.value = "학생 질문 자료";
    const modeLabel = el("label", "자료 상태"); nodes.mode = el("select");
    for (const [value, label] of [["DRAFT", "확인용 초안"], ["FINAL", "확인 완료 자료"]]) { const option = el("option", label); option.value = value; nodes.mode.append(option); } modeLabel.append(nodes.mode); form.append(modeLabel);
    const replies = el("label", undefined, "kakao-review-check"); nodes.replies = el("input"); nodes.replies.type = "checkbox"; nodes.replies.checked = true; replies.append(nodes.replies, el("span", "조교 답변도 함께 넣기")); form.append(replies);
    nodes.selection = el("div", undefined, "kakao-selected-questions"); nodes.selection.setAttribute("aria-label", "자료에 넣을 질문");
    nodes.save = el("button", "선택한 질문으로 자료 저장", "button secondary"); nodes.save.type = "submit";
    nodes.note = el("p", "질문 목록에서 ‘자료에 넣기’를 누른 뒤 기간을 골라 주세요.", "form-message"); nodes.note.setAttribute("role", "status");
    form.append(nodes.selection, nodes.save, nodes.note); form.addEventListener("submit", event => { event.preventDefault(); void savePacket(); });
    nodes.list = el("div"); nodes.detail = el("div", undefined, "kakao-packet-detail");
    root.append(form, nodes.list, nodes.detail); renderSelection(); controls();
  }
  function renderSelection() {
    if (!root) return; nodes.selection.replaceChildren();
    for (const row of selected.values()) { const chip = el("div", undefined, "kakao-selected-question");
      chip.append(el("span", `${row.student?.display_name || "학생"}의 질문`), button("빼기", () => { if (!packetIntent && !saving) { selected.delete(row.question_id); renderSelection(); } })); nodes.selection.append(chip); }
    if (!selected.size) nodes.selection.append(el("p", "선택한 질문이 없습니다.", "empty-state")); controls();
  }
  function addQuestion(row) {
    if (!writable() || saving || packetIntent) { if (root) say("진행 중인 자료 저장 요청부터 확인해 주세요.", true); return; }
    identifier(row.question_id); identifier(row.question_revision_id);
    if (row.source_binding_id !== binding.source_binding_id || !row.student || row.review_state === "EXCLUDED") { say("학생 연결과 출력 제외 여부를 먼저 확인해 주세요.", true); return; }
    if (selected.size >= 200 && !selected.has(row.question_id)) { say("한 자료에는 질문을 200개까지 넣을 수 있습니다.", true); return; }
    selected.set(row.question_id, row); renderSelection(); say(`${selected.size}개의 질문을 선택했습니다. 선택한 버전으로 저장합니다.`);
  }
  async function refresh() {
    const token = generation; if (!live(token)) return;
    packets.clear(); nodes.list.replaceChildren(); await loadPackets(token);
  }
  async function loadPackets(token, cursor = null) {
    const query = new URLSearchParams({source_binding_id: binding.source_binding_id, limit: "50"}); if (cursor) query.set("cursor", cursor);
    try {
      const result = page(await api(`${BASE}/question-packets?${query}`)); if (!live(token)) return;
      for (const row of result.items) { identifier(row.packet_id); identifier(row.packet_revision_id); if (row.source_binding_id !== binding.source_binding_id) throw new Error("다른 채널의 자료입니다."); packets.set(row.packet_id, row); }
      nodes.list.replaceChildren();
      for (const row of packets.values()) { const item = el("div", undefined, "kakao-packet"); item.append(el("strong", row.title), el("span", `${row.question_count}개 질문 · ${row.student_count}명`), button("학생별 PDF 보기", () => void openPacket(row))); nodes.list.append(item); }
      if (!packets.size) nodes.list.append(el("p", "아직 저장한 질문 자료가 없습니다.", "empty-state"));
      if (result.next_cursor) nodes.list.append(button("자료 더 보기", () => { if (live(token)) void loadPackets(token, result.next_cursor); }));
    } catch (error) { if (live(token)) say(`저장한 자료를 읽지 못했습니다. ${explainError(error)}`, true); }
  }
  async function savePacket() {
    if (!writable() || saving) return;
    if (!packetIntent) {
      const title = nodes.title.value.trim();
      if (!title || [...title].length > 128 || !nodes.start.value || !nodes.end.value || nodes.start.value > nodes.end.value || !selected.size) { say("자료 이름과 날짜, 선택한 질문을 확인해 주세요.", true); return; }
      packetIntent = {owner, binding: binding.source_binding_id, rows: [...selected.values()], key: `kakao-packet-${crypto.randomUUID()}`, body: {
        schema_version: "kakao-packet-create/1.0", source_binding_id: binding.source_binding_id, title,
        questions: [...selected.values()].map(row => ({question_id: row.question_id, question_revision_id: row.question_revision_id})),
        display_start_date: nodes.start.value, display_end_date_inclusive: nodes.end.value, mode: nodes.mode.value, include_replies: nodes.replies.checked}};
    }
    const token = generation, intent = packetIntent;
    if (intent.owner !== owner || intent.binding !== binding.source_binding_id) { say("앞선 채널의 자료 저장 요청부터 확인해 주세요.", true); return; }
    saving = true; controls(); say("선택한 질문을 자료로 저장하고 있습니다.");
    try {
      const result = await api(`${BASE}/question-packets`, {method: "POST", mutation: true, headers: {"Idempotency-Key": intent.key}, body: intent.body});
      if (!live(token) || packetIntent !== intent) return;
      const row = result.packet; if (row?.source_binding_id !== intent.binding || typeof result.replayed !== "boolean") throw new Error("자료 저장 결과를 확인하지 못했습니다.");
      identifier(row.packet_id); identifier(row.packet_revision_id); packetIntent = null;
      say("질문 자료를 저장했습니다. 학생을 골라 PDF를 만들 수 있습니다."); await refresh(); if (live(token)) await openPacket(row);
    } catch (error) { if (live(token)) {
      if (SELECTION_REFUSALS.has(error?.code)) {
        packetIntent = null;
        say(`선택한 질문의 확인 상태와 날짜를 확인해 주세요. 확인 전 질문은 ‘확인용 초안’으로 저장할 수 있습니다. ${explainError(error)}`, true);
      } else say(`저장 결과를 확인하지 못했습니다. 같은 요청으로 다시 확인할 수 있습니다. ${explainError(error)}`, true);
    } }
    finally { if (generation === token && owner === intent.owner) { saving = false; if (root) controls(); } }
  }
  async function openPacket(row) {
    const token = generation, request = ++detailGeneration; if (!live(token)) return;
    studyEditor.clear();
    stop(); currentPacket = null; currentStudents.clear(); observed = null; exportIntent = null; exporting = false; observing = false; nodes.detail.replaceChildren(el("p", "저장한 자료를 여는 중입니다."));
    const query = new URLSearchParams({source_binding_id: binding.source_binding_id});
    try {
      const result = await api(`${BASE}/question-packets/${identifier(row.packet_id)}/revisions/${identifier(row.packet_revision_id)}?${query}`);
      if (!live(token) || request !== detailGeneration) return;
      if (result.packet?.packet_id !== row.packet_id || result.packet.packet_revision_id !== row.packet_revision_id || result.packet.source_binding_id !== binding.source_binding_id || !Array.isArray(result.students)) throw new Error("자료 버전이 다릅니다.");
      currentPacket = result; currentStudents = new Map(result.students.map(student => [student.student_id, student])); nodes.detail.replaceChildren(el("h4", row.title), el("p", `${row.display_start_date} ~ ${row.display_end_date_inclusive} · ${row.mode === "FINAL" ? "확인 완료 자료" : "확인용 초안"}`));
      const label = el("label", "PDF로 만들 학생"); nodes.student = el("select");
      for (const student of result.students) { identifier(student.student_id); const option = el("option", `${student.display_name} · ${student.question_count}개 질문`); option.value = student.student_id; nodes.student.append(option); } label.append(nodes.student);
      nodes.export = button("학생 PDF 만들기", () => void createExport(token, request)); nodes.export.disabled = !writable();
      nodes.exportStatus = el("div"); nodes.exportStatus.setAttribute("role", "status");
      nodes.history = el("div"); nodes.detail.append(label, nodes.export, nodes.exportStatus, el("h4", "이 자료의 PDF 기록"), nodes.history);
      const studyHost = el("section", undefined, "kakao-study-editor");
      const openStudy = button("개념·설명 편집", () => {
        if (!detailLive(token, request)) return;
        const student = currentStudents.get(nodes.student.value); if (!student) return;
        void studyEditor.open(studyHost, {binding: binding.source_binding_id, packet: row.packet_id,
          revision: row.packet_revision_id, student: student.student_id, studentName: student.display_name,
          questionRefs: currentPacket.questions,
          canEdit: permissions.has("kakao_archive:edit") && ["DRAFT", "ACTIVE"].includes(binding.state), canExport: writable()});
      });
      nodes.student.addEventListener("change", () => studyEditor.clear());
      nodes.detail.append(openStudy, studyHost);
      await loadExports(token, request);
    } catch (error) { if (live(token) && request === detailGeneration) { nodes.detail.replaceChildren(el("p", "자료를 열지 못했습니다.")); say(explainError(error), true); } }
  }
  function detailLive(token, request) { return live(token) && request === detailGeneration && currentPacket; }
  function downloadLink(value) {
    const link = el("a", "PDF 내려받기", "button quiet");
    const query = new URLSearchParams({source_binding_id: value.source_binding_id, revision_id: value.export_revision_id});
    link.href = `/studio/api/v1${BASE}/exports/${identifier(value.export_id)}/file?${query}`; return link;
  }
  function exportRow(value) {
    const student = currentStudents.get(value.student_id);
    if (value.source_binding_id !== binding.source_binding_id || value.packet_id !== currentPacket.packet.packet_id || value.packet_revision_id !== currentPacket.packet.packet_revision_id || !student) throw new Error("다른 자료의 PDF입니다.");
    const item = el("div", undefined, "kakao-export"); item.append(el("strong", student.display_name), badge(value.state));
    item.append(el("p", value.profile?.layout_policy === "student-study-a4/1.0" ? (currentPacket.packet.include_replies ? "질문·답변과 기록 정보" : "질문과 기록 정보") : "기존 질문 자료"));
    if (value.state === "COMPLETED") { identifier(value.export_revision_id); item.append(el("p", `${value.page_count}쪽`)); if (writable()) item.append(downloadLink(value)); }
    else if (value.state === "NEEDS_LAYOUT_REVIEW") item.append(el("p", "한 페이지에 담기 어려운 질문이 있습니다. 질문을 나누거나 사진 구성을 확인해 주세요."));
    else if (value.state === "FAILED") item.append(el("p", "PDF를 만들지 못했습니다. 실패 기록은 보존됩니다."));
    else item.append(el("p", "PDF 제작 중입니다. 상태 확인은 새 제작을 시작하지 않습니다."));
    const token = generation, request = detailGeneration;
    item.append(button("상태 확인", () => { if (detailLive(token, request) && nodes.detail.contains(item)) { observed = value; void observe(token, request, value.export_id); } }));
    return item;
  }
  async function loadExports(token, request, cursor = null) {
    const query = new URLSearchParams({source_binding_id: binding.source_binding_id, limit: "100"}); if (cursor) query.set("cursor", cursor);
    const result = page(await api(`${BASE}/exports?${query}`)); if (!detailLive(token, request)) return;
    const values = result.items.filter(item => item.packet_revision_id === currentPacket.packet.packet_revision_id);
    if (!cursor) nodes.history.replaceChildren(); nodes.history.querySelector('[data-kakao="export-more"]')?.remove();
    for (const value of values) nodes.history.append(exportRow(value));
    if (!values.length && !cursor) nodes.history.append(el("p", result.next_cursor ? "이 페이지에는 해당 자료의 PDF가 없습니다. 이전 기록을 더 볼 수 있습니다." : "아직 만든 PDF가 없습니다.", "empty-state"));
    if (result.next_cursor) { const more = button("이전 PDF 기록 더 보기", () => { if (detailLive(token, request)) void loadExports(token, request, result.next_cursor).catch(error => { if (detailLive(token, request)) say(explainError(error), true); }); }); more.dataset.kakao = "export-more"; nodes.history.append(more); }
  }
  async function createExport(token, request) {
    if (!detailLive(token, request) || !writable() || exporting) return;
    const packet = currentPacket.packet;
    if (!exportIntent) exportIntent = {key: `kakao-pdf-${crypto.randomUUID()}`, body: {schema_version: "kakao-export-create/1.0", source_binding_id: binding.source_binding_id, packet_id: packet.packet_id, packet_revision_id: packet.packet_revision_id, student_id: nodes.student.value}};
    const intent = exportIntent; exporting = true; nodes.student.disabled = true; nodes.export.disabled = true;
    nodes.exportStatus.replaceChildren(el("p", "PDF 제작을 요청하고 있습니다."));
    try {
      const result = await api(`${BASE}/exports`, {method: "POST", mutation: true, headers: {"Idempotency-Key": intent.key}, body: intent.body});
      if (!detailLive(token, request) || exportIntent !== intent) return;
      const value = result.export; if (value?.student_id !== intent.body.student_id || value.packet_id !== packet.packet_id) throw new Error("학생 PDF 요청이 다릅니다.");
      observed = value; nodes.exportStatus.replaceChildren(exportRow(value)); exportIntent = null;
      if (["PENDING", "RUNNING"].includes(value.state)) timer = schedule(() => void observe(token, request, value.export_id), 8000);
      else await loadExports(token, request);
    } catch (error) { if (detailLive(token, request)) { nodes.export.textContent = "같은 PDF 요청 확인"; nodes.exportStatus.replaceChildren(el("p", `요청 결과를 확인하지 못했습니다. ${explainError(error)}`)); } }
    finally { if (detailLive(token, request)) { exporting = false; nodes.export.disabled = !writable(); nodes.student.disabled = exportIntent !== null; if (!exportIntent) nodes.export.textContent = "학생 PDF 만들기"; } }
  }
  async function observe(token, request, exportId) {
    if (!detailLive(token, request) || observing || observed?.export_id !== exportId) return;
    stop(); observing = true;
    try { const query = new URLSearchParams({source_binding_id: binding.source_binding_id}); const value = await api(`${BASE}/exports/${identifier(exportId)}?${query}`);
      if (!detailLive(token, request) || observed?.export_id !== exportId) return;
      if (value.export_id !== exportId) throw new Error("PDF 연결이 다릅니다."); observed = value; nodes.exportStatus.replaceChildren(exportRow(value));
      if (["PENDING", "RUNNING"].includes(value.state)) timer = schedule(() => void observe(token, request, exportId), 8000); else await loadExports(token, request);
    } catch (error) { if (detailLive(token, request)) say(`PDF 상태를 확인하지 못했습니다. ${explainError(error)}`, true); }
    finally { if (detailLive(token, request)) observing = false; }
  }
  async function setBinding(value) {
    studyEditor.clear();
    generation++; detailGeneration++; stop(); currentPacket = null; currentStudents.clear(); observed = null; binding = value; exporting = false; observing = false; saving = false;
    selected.clear(); packets.clear(); if (root) {
      if (packetIntent && value && packetIntent.binding === value.source_binding_id) {
        selected = new Map(packetIntent.rows.map(row => [row.question_id, row]));
        const body = packetIntent.body; nodes.title.value = body.title; nodes.start.value = body.display_start_date; nodes.end.value = body.display_end_date_inclusive; nodes.mode.value = body.mode; nodes.replies.checked = body.include_replies;
      }
      nodes.list.replaceChildren(); nodes.detail.replaceChildren(); renderSelection();
    }
    if (value && value.state !== "RETIRED") await refresh();
  }
  function clearPrivateFields() { if (!root) return; nodes.title.value = "학생 질문 자료"; const date = new Intl.DateTimeFormat("sv-SE", {timeZone: "Asia/Seoul"}).format(new Date()); nodes.start.value = date; nodes.end.value = date; nodes.mode.value = "DRAFT"; nodes.replies.checked = true; say("질문 목록에서 ‘자료에 넣기’를 누른 뒤 기간을 골라 주세요."); }
  function setOwner(value) { if (value === owner) return; studyEditor.clear(); owner = value; permissions = new Set(); generation++; detailGeneration++; stop(); binding = null; selected.clear(); packets.clear(); currentStudents.clear(); packetIntent = null; exportIntent = null; observed = null; currentPacket = null; saving = false; exporting = false; observing = false; if (root) { nodes.list.replaceChildren(); nodes.detail.replaceChildren(); clearPrivateFields(); renderSelection(); } }
  function setPermissions(values) { studyEditor.clear(); permissions = new Set(values); generation++; detailGeneration++; stop(); if (!permissions.has("kakao_archive:read")) { void setBinding(null); clearPrivateFields(); } if (root) controls(); }
  function open() { active = true; }
  function close() { studyEditor.clear(); active = false; generation++; detailGeneration++; stop(); if (root) { nodes.list.replaceChildren(); nodes.detail.replaceChildren(); } }
  return {install, addQuestion, setOwner, setPermissions, setBinding, open, close, refresh};
}
