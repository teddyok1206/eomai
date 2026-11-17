// Saved student study edits only. Source resolution, revisions and PDF claims belong to Catalog.
import {createKakaoConceptPicker} from "./kakao-concept-picker.js";
const BASE = "/kakao-archive";
const ID = /^[a-z][a-z0-9_]{1,48}_[a-f0-9]{32}$/;
function id(value) { if (typeof value !== "string" || !ID.test(value)) throw new Error("자료 연결을 확인해 주세요."); return encodeURIComponent(value); }

export function createKakaoStudyEditor({document, api, explainError, schedule = setTimeout, unschedule = clearTimeout}) {
  let root = null, context = null, generation = 0, timer = null, draft = null, saved = null;
  let saveIntent = null, exportIntent = null, busy = false, observed = null, dirty = false;
  const nodes = {};
  const pickers = new Map();
  function clearPickers() { for (const picker of pickers.values()) picker.clear(); pickers.clear(); }
  function el(tag, text, className = "") { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; }
  function button(text, action) { const node = el("button", text, "button quiet"); node.type = "button"; node.addEventListener("click", action); return node; }
  function live(token) { return root && context && token === generation; }
  function say(text, error = false) { nodes.note.textContent = text; nodes.note.className = `form-message${error ? " error" : ""}`; }
  function stop() { if (timer !== null) unschedule(timer); timer = null; }
  function clear() { generation++; stop(); clearPickers(); context = null; draft = null; saved = null; saveIntent = null; exportIntent = null; observed = null; busy = false; dirty = false; if (root) root.replaceChildren(); }
  function input(parent, labelText, value, multiline, change, maxLength) {
    const label = el("label", labelText), field = el(multiline ? "textarea" : "input"); field.value = value ?? ""; field.maxLength = maxLength; if (multiline) field.rows = 4;
    field.addEventListener("input", () => { change(field.value); dirty = true; controls(); }); label.append(field); parent.append(label); return field;
  }
  function controls() {
    const locked = busy || saveIntent !== null || exportIntent !== null;
    nodes.form?.querySelectorAll("input, textarea, button").forEach(node => { node.disabled = locked || !context?.canEdit; });
    if (nodes.save) { nodes.save.disabled = busy || !draft || !context?.canEdit || exportIntent !== null; nodes.save.textContent = saveIntent ? "같은 저장 요청 확인" : "설명 자료 저장"; }
    if (nodes.pdf) { nodes.pdf.disabled = busy || !saved || !context?.canExport || saveIntent !== null || (dirty && !exportIntent); nodes.pdf.textContent = exportIntent ? "같은 PDF 요청 확인" : "저장한 설명으로 PDF 만들기"; }
    if (nodes.fresh) nodes.fresh.disabled = locked || !context?.canEdit;
    nodes.history?.querySelectorAll("button").forEach(node => { node.disabled = locked; });
  }
  function renderForm() {
    nodes.form.replaceChildren(); if (!draft) { controls(); return; }
    input(nodes.form, "설명 자료 이름", draft.title, false, value => { draft.title = value; }, 128);
    draft.questions.forEach((question, index) => {
      const section = el("section", undefined, "kakao-study-question"); section.append(el("h5", `${index + 1}번째 질문의 보충 설명`));
      const questionId = context.questionRefs?.get(question.question_revision_id);
      if (questionId) {
        const revision = question.question_revision_id;
        if (!pickers.has(revision)) pickers.set(revision, createKakaoConceptPicker({document, api, explainError, schedule, unschedule,
          canEdit: () => !!context?.canEdit && !busy && !saveIntent && !exportIntent,
          onSelect: (task, blocks) => { const current = draft?.questions.find(value => value.question_revision_id === revision); if (!current) return; current.concept_task_id = task; current.blocks = blocks; dirty = true; renderForm(); }
        }));
        const host = el("section"); section.append(host); pickers.get(revision).mount(host, {binding:context.binding, questionId, revision, student:context.student, selected:question});
      }
      question.blocks.forEach((block, blockIndex) => {
        const box = el("fieldset"), legend = el("legend", `선택한 교재 개념 ${blockIndex + 1}`); box.append(legend);
        box.append(el("p", "빈칸으로 두면 원래 추천 설명을 사용합니다. 교재 인용과 원본 그림은 변경하지 않습니다.", "field-help"));
        for (const [key, label, length] of [["title", "개념 제목", 128], ["relevance", "이 질문과의 연결", 1000], ["explanation", "개념 설명", 8000]]) input(box, label, block[key], key !== "title", value => { block[key] = value || null; }, length);
        section.append(box);
      });
      question.notes.forEach((note, noteIndex) => {
        const box = el("fieldset"); box.append(el("legend", `직접 쓴 설명 ${noteIndex + 1}`));
        input(box, "설명 제목", note.title, false, value => { note.title = value; }, 128);
        input(box, "설명 내용", note.text, true, value => { note.text = value; }, 8000);
        box.append(button("이 설명 빼기", () => { if (!busy && !saveIntent && !exportIntent) { question.notes.splice(noteIndex, 1); dirty = true; renderForm(); } })); section.append(box);
      });
      if (question.notes.length < 8) section.append(button("직접 쓴 설명 추가", () => { if (!busy && !saveIntent && !exportIntent) { question.notes.push({title: "보충 설명", text: ""}); dirty = true; renderForm(); } }));
      nodes.form.append(section);
    }); controls();
  }
  function matches(row) { return context && row?.source_binding_id === context.binding && row.packet_id === context.packet && row.packet_revision_id === context.revision && row.student_id === context.student; }
  async function open(container, value) {
    clear(); root = container; context = {...value, questionRefs:new Map((value.questionRefs || []).map(ref => [ref.question_revision_id, ref.question_id]))}; const token = generation;
    root.replaceChildren(el("h4", `${value.studentName} · 개념·설명 자료`), el("p", "질문·조교 답변은 보존하고, 뒤쪽에 보충 설명을 붙입니다. 저장한 버전별로 PDF를 다시 받을 수 있습니다.", "field-help"));
    nodes.note = el("p", "저장한 설명 자료를 확인하고 있습니다.", "form-message"); nodes.note.setAttribute("role", "status");
    nodes.fresh = button("새 설명 자료 시작", () => void fresh(generation));
    nodes.history = el("div", undefined, "kakao-study-history"); nodes.form = el("div", undefined, "kakao-study-form");
    nodes.save = button("설명 자료 저장", () => void save()); nodes.pdf = button("저장한 설명으로 PDF 만들기", () => void makePdf());
    nodes.output = el("div"); nodes.output.setAttribute("role", "status");
    root.append(nodes.fresh, nodes.history, nodes.form, nodes.save, nodes.pdf, nodes.note, nodes.output); controls();
    try { await history(token); if (live(token)) say("저장본을 열거나 새 설명 자료를 시작해 주세요."); }
    catch (error) { if (live(token)) say(explainError(error), true); }
  }
  async function history(token, cursor = null) {
    const query = new URLSearchParams({source_binding_id: context.binding, limit: "100"}); if (cursor) query.set("cursor", cursor);
    const result = await api(`${BASE}/studies?${query}`); if (!live(token)) return;
    if (!Array.isArray(result?.items) || result.items.length > 100) throw new Error("설명 자료 목록을 확인하지 못했습니다.");
    if (!cursor) nodes.history.replaceChildren(); nodes.history.querySelector('[data-action="more-studies"]')?.remove();
    for (const row of result.items) if (matches(row)) { id(row.study_id); id(row.study_revision_id); nodes.history.append(button(`${row.title} · 수정 ${row.resource_version - 1}회 · 열기`, () => void read(token, row))); }
    if (result.next_cursor) { const more = button("이전 설명 자료 더 보기", () => void history(token, result.next_cursor).catch(error => { if (live(token)) say(explainError(error), true); })); more.dataset.action = "more-studies"; nodes.history.append(more); }
    controls();
  }
  async function fresh(token) {
    if (!live(token) || busy || saveIntent || exportIntent || !context.canEdit) return;
    busy = true; controls();
    try {
      const query = new URLSearchParams({source_binding_id: context.binding});
      const result = await api(`${BASE}/question-packets/${id(context.packet)}/revisions/${id(context.revision)}/students/${id(context.student)}/study-selection?${query}`);
      if (!live(token)) return;
      if (!matches(result) || result.schema_version !== "kakao-study-create/1.0" || !Array.isArray(result.questions)) throw new Error("학생별 질문 구성이 다릅니다.");
      clearPickers(); saved = null; draft = structuredClone(result); dirty = true; observed = null; stop(); nodes.output.replaceChildren(); renderForm(); say("필요한 설명을 입력한 뒤 저장해 주세요.");
    } catch (error) { if (live(token)) say(explainError(error), true); }
    finally { if (live(token)) { busy = false; controls(); } }
  }
  async function read(token, row) {
    if (!live(token) || busy || saveIntent || exportIntent) return;
    busy = true; controls();
    try {
      const query = new URLSearchParams({source_binding_id: context.binding});
      const result = await api(`${BASE}/studies/${id(row.study_id)}/revisions/${id(row.study_revision_id)}?${query}`);
      if (!live(token)) return;
      if (!matches(result.study) || result.study.study_revision_id !== row.study_revision_id || !Array.isArray(result.questions)) throw new Error("저장한 설명 자료의 버전이 다릅니다.");
      clearPickers(); saved = result.study; draft = {schema_version: "kakao-study-create/1.0", source_binding_id: context.binding, packet_id: context.packet, packet_revision_id: context.revision, student_id: context.student, title: saved.title, questions: structuredClone(result.questions)};
      dirty = false; observed = null; stop(); nodes.output.replaceChildren(); renderForm(); say("저장한 설명을 열었습니다. 수정하면 새 버전으로 저장됩니다.");
    } catch (error) { if (live(token)) say(explainError(error), true); }
    finally { if (live(token)) { busy = false; controls(); } }
  }
  async function save() {
    if (!context?.canEdit || busy || !draft || exportIntent) return;
    if (!saveIntent) {
      if (!draft.title.trim() || draft.questions.some(q => q.notes.some(n => !n.title.trim() || !n.text.trim()))) { say("자료 이름과 추가한 설명의 제목·내용을 채워 주세요.", true); return; }
      const body = structuredClone(draft); let path = `${BASE}/studies`, method = "POST"; const headers = {"Idempotency-Key": `kakao-study-${crypto.randomUUID()}`};
      if (saved) { body.schema_version = "kakao-study-revise/1.0"; body.study_id = saved.study_id; body.parent_revision_id = saved.study_revision_id; body.expected_resource_version = saved.resource_version; path += `/${id(saved.study_id)}`; method = "PATCH"; headers["If-Match"] = `"v${saved.resource_version}"`; }
      saveIntent = {path, method, headers, body};
    }
    const token = generation, intent = saveIntent; busy = true; controls(); say("설명 자료를 저장하고 있습니다.");
    try {
      const result = await api(intent.path, {method: intent.method, mutation: true, headers: intent.headers, body: intent.body});
      if (!live(token) || saveIntent !== intent) return;
      if (!matches(result.study) || typeof result.replayed !== "boolean") throw new Error("저장 결과의 학생·자료가 다릅니다.");
      saved = result.study; saveIntent = null; dirty = false; say("설명 자료를 저장했습니다. 저장한 내용으로 PDF를 만들 수 있습니다."); await history(token);
    } catch (error) { if (live(token)) {
      if (error?.code === "KAKAO_ARCHIVE_PRECONDITION_FAILED") { saveIntent = null; say("다른 수정본이 먼저 저장됐습니다. 저장본을 다시 열어 확인해 주세요.", true); }
      else say(`저장 결과를 확인하지 못했습니다. 같은 요청으로 확인할 수 있습니다. ${explainError(error)}`, true);
    } }
    finally { if (live(token)) { busy = false; controls(); } }
  }
  function showExport(result) {
    if (!saved || result.study.study_id !== saved.study_id || result.study.study_revision_id !== saved.study_revision_id || result.study.manifest_sha256 !== saved.manifest.sha256 || !matches(result.export)) throw new Error("설명 자료와 PDF의 버전이 다릅니다.");
    const value = result.export; observed = value; nodes.output.replaceChildren();
    const names = {PENDING: "PDF 제작 대기", RUNNING: "PDF 제작 중", COMPLETED: "PDF 제작 완료", FAILED: "PDF 제작 실패 · 이전 기록 보존", NEEDS_LAYOUT_REVIEW: "쪽 배치 확인이 필요합니다"};
    nodes.output.append(el("p", names[value.state] || "상태 확인이 필요합니다."));
    if (value.state === "COMPLETED" && context.canExport) {
      const query = new URLSearchParams({source_binding_id: context.binding, revision_id: value.export_revision_id}); id(value.export_revision_id);
      const link = el("a", "설명 자료 PDF 내려받기", "button quiet"); link.href = `/studio/api/v1${BASE}/exports/${id(value.export_id)}/file?${query}`; nodes.output.append(link);
    }
    nodes.output.append(button("PDF 상태 확인", () => void observe(generation, value.export_id)));
    if (["PENDING", "RUNNING"].includes(value.state)) timer = schedule(() => void observe(generation, value.export_id), 8000);
  }
  async function makePdf() {
    if (!saved || !context?.canExport || busy || saveIntent || (dirty && !exportIntent)) return;
    if (!exportIntent) exportIntent = {key: `kakao-study-pdf-${crypto.randomUUID()}`, body: {schema_version: "kakao-study-export-create/1.0", source_binding_id: context.binding, study: {study_id: saved.study_id, study_revision_id: saved.study_revision_id, manifest_sha256: saved.manifest.sha256}}};
    const token = generation, intent = exportIntent; busy = true; controls(); stop();
    try {
      const result = await api(`${BASE}/study-exports`, {method: "POST", mutation: true, headers: {"Idempotency-Key": intent.key}, body: intent.body});
      if (!live(token) || exportIntent !== intent) return; showExport(result.result); exportIntent = null;
    } catch (error) { if (live(token)) say(`PDF 요청을 확인하지 못했습니다. 같은 요청으로 확인할 수 있습니다. ${explainError(error)}`, true); }
    finally { if (live(token)) { busy = false; controls(); } }
  }
  async function observe(token, exportId) {
    if (!live(token) || busy || observed?.export_id !== exportId) return; busy = true; stop(); controls();
    try {
      const query = new URLSearchParams({source_binding_id: context.binding}); const result = await api(`${BASE}/study-exports/${id(exportId)}?${query}`);
      if (live(token) && observed?.export_id === exportId) { if (result.export?.export_id !== exportId) throw new Error("PDF 연결이 다릅니다."); showExport(result); }
    } catch (error) { if (live(token)) say(`PDF 상태를 확인하지 못했습니다. ${explainError(error)}`, true); }
    finally { if (live(token)) { busy = false; controls(); } }
  }
  return {open, clear};
}
