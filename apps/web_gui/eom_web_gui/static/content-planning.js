import {createPlanningDraft, initialSections, newPlanningId, slotSelection, targetIdentity} from "./content-planning-draft.js";
import {createCuratedDeliveryControl} from "./item-db-delivery.js";

const PAGE_SIZE = 50;
const CONTENT_TYPES = Object.freeze({MOCK_EXAM: "모의고사", TEXTBOOK: "교재", WEEKLY: "주간지", OTHER: "기타"});
const CHANGE_LABELS = Object.freeze({CREATE_CONTENT: "콘텐츠 생성", CREATE_EDITION: "새 판 생성", COPY_EDITION: "판 복사", EDIT_EDITION: "편성 변경", SAVE_SECTIONS: "배치 변경", SAVE_STRUCTURE: "구성 변경"});

export function createContentPlanning({document, api, can, openItemDb, openTarget, confirm = text => globalThis.confirm(text), prompt = text => globalThis.prompt(text)}) {
  const $ = selector => document.querySelector(selector), draft = createPlanningDraft();
  let owner = null, ownerEpoch = 0, active = false, selectionEpoch = 0, contentEpoch = 0;
  let productId = null, selected = null, currentRevision = null, loaded = false, page = 0;
  let contents = [], editions = [], contentCursor = null, editionCursor = null, printCursor = null;
  let busy = false, loadingSection = false, pending = null, selectionTarget = null, moreInspect = null;
  const labels = new Map();
  let deliveryCursor = null, deliveryControls = [], deliveryEpoch = 0;
  let usageKey = null, usageEpoch = 0;
  const usageCounts = new Map();
  const node = (tag, text, className = "") => { const n = document.createElement(tag); n.className = className; if (text !== undefined) n.textContent = text; return n; };
  const option = (value, text) => {const n = node("option", text); n.value = value; return n;};
  function button(text, action, disabled = false) {const n = node("button", text, "button quiet"); n.type = "button"; n.disabled = disabled; n.addEventListener("click", action); return n;}
  function message(text, error = false) {const n = $("#excel-message"); n.textContent = text; n.className = `form-message${error ? " error" : ""}`;}
  const query = body => api("/content-planning/query", {method: "POST", mutation: true, body});
  const comp = () => draft.composition();
  const labelKey = target => JSON.stringify(slotSelection(target));
  const section = () => comp()?.sections.find(value => value.section_id === selected);
  const locked = () => busy || pending !== null || loadingSection;
  const editable = () => can("deliverable:update") && comp()?.deliverable_revision_id === currentRevision && !locked();
  const dateText = value => new Date(value).toLocaleString("ko-KR", {timeZone: "Asia/Seoul", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit"});

  function label(target) {
    const key = labelKey(target);
    return labels.get(key) || (target.placement_kind === "EMPTY" ? "빈 자리" : target.external_number ? `고유번호 ${target.external_number}` : target.placement_kind === "PAST_EXAM_ITEM_REVISION" ? "기출 문항" : "등록 문항");
  }
  function remember(rows) {for (const row of rows) if (row.target.external_number && !labels.has(labelKey(row.target))) labels.set(labelKey(row.target), `고유번호 ${row.target.external_number}`);}
  function sync() {
    const formReady = section()?.kind === "FORM" && draft.loaded(selected);
    $("#excel-save").disabled = !editable() || !draft.dirty();
    $("#excel-choose").disabled = !editable() || !formReady;
    $("#excel-empty-slot").disabled = !editable() || !formReady;
    $("#excel-copy").disabled = !comp() || locked() || draft.dirty() || !can("deliverable:create");
    $("#excel-new-edition").disabled = !productId || locked() || !can("deliverable:create");
    $("#excel-create-panel").hidden = !can("deliverable:create");
    $("#excel-structure-panel").hidden = !can("deliverable:update");
    for (const el of $("#excel-section-form").querySelectorAll("input,select,button")) el.disabled = !editable() || draft.dirty();
    for (const el of $("#excel-create").querySelectorAll("input,select,button")) el.disabled = locked();
    for (const el of $("#excel-print-form").querySelectorAll("input,button")) el.disabled = locked() || draft.dirty() || !can("usage:fulfill_plan");
    $("#excel-delivery-prepare").disabled = !comp() || locked() || draft.dirty() || !can("hwpx:build_create");
    $("#excel-delivery-refresh").disabled = !comp() || busy;
    $("#excel-retry").hidden = pending === null;
    $("#excel-retry-button").disabled = busy;
    $("#excel-draft-state").textContent = loadingSection ? "문항 불러오는 중…" : draft.dirty() ? "저장하지 않은 배치" : "저장됨";
  }
  function renderContents() {
    const root = $("#excel-contents"); root.replaceChildren();
    for (const value of contents) {
      const b = button(`${value.title} · ${CONTENT_TYPES[value.content_type]}`, () => selectProduct(value.deliverable_id));
      b.setAttribute("aria-current", String(value.deliverable_id === productId)); root.append(b);
    }
    if (!contents.length) root.append(node("p", "아직 콘텐츠가 없습니다.", "empty-state"));
    $("#excel-more-contents").hidden = contentCursor === null;
  }
  async function refreshContents(append = false) {
    if (!owner) return;
    const epoch = ++contentEpoch, actor = ownerEpoch;
    try {
      const data = await query({query_kind: "LIST_CONTENTS", text: $("#excel-search").value.trim(), limit: 50, after_id: append ? contentCursor : null});
      if (epoch !== contentEpoch || actor !== ownerEpoch) return;
      contents = append ? [...contents, ...data.rows] : data.rows;
      contentCursor = data.next_id; loaded = true; renderContents();
    } catch (error) {if (epoch === contentEpoch && actor === ownerEpoch) message(`콘텐츠 조회 실패: ${error.message}`, true);}
  }
  function mayLeave() {return !locked() && (!draft.dirty() || confirm("저장하지 않은 배치를 버리고 이동할까요?"));}
  async function selectProduct(id, append = false) {
    if (busy || pending || (!append && !mayLeave())) return;
    const actor = ownerEpoch, epoch = ++selectionEpoch;
    if (!append) {
      clearDeliveries(); productId = id; draft.reset(); selected = null; currentRevision = null; editions = [];
      $("#excel-editor").hidden = true; $("#excel-empty").hidden = false;
      $("#excel-sections").replaceChildren(); renderContents();
    }
    try {
      const result = await query({query_kind: "LIST_EDITIONS", deliverable_id: id, limit: 100, after_id: append ? editionCursor : null});
      if (actor !== ownerEpoch || epoch !== selectionEpoch) return;
      editions = append ? [...editions, ...result.rows] : result.rows; editionCursor = result.next_id;
      const select = $("#excel-editions"); select.replaceChildren(...editions.map(row => option(row.edition_id, row.edition_label)));
      select.disabled = !editions.length; $("#excel-more-editions").hidden = editionCursor === null;
      if (comp()) select.value = comp().edition_id;
      else if (editions.length) await loadEdition(editions[0].edition_id);
    } catch (error) {if (actor === ownerEpoch && epoch === selectionEpoch) message(`판 조회 실패: ${error.message}`, true);}
  }
  function renderComposition() {
    const value = comp(); if (!value) return;
    $("#excel-empty").hidden = true; $("#excel-editor").hidden = false;
    $("#excel-content-title").textContent = `${value.content_title} · ${value.edition_label}`;
    $("#excel-version").textContent = value.deliverable_revision_id === currentRevision ? `현재 저장본 · ${value.revision_number}차` : `과거 저장본 · ${value.revision_number}차`;
    const root = $("#excel-sections"), parents = $("#excel-section-parent"), print = $("#excel-print-sections");
    root.replaceChildren(); parents.replaceChildren(option("", "최상위")); print.replaceChildren();
    const output = $("#excel-delivery-sections"); output.replaceChildren();
    const depth = new Map();
    for (const s of value.sections) {
      const level = s.parent_id === null ? 0 : (depth.get(s.parent_id) || 0) + 1; depth.set(s.section_id, level);
      const b = button(`${"　".repeat(Math.min(level, 4))}${s.kind === "GROUP" ? "▸ " : ""}${s.label}${s.form ? ` · ${s.form.placement_count}문항` : ""}`, () => chooseSection(s.section_id));
      b.setAttribute("aria-current", String(selected === s.section_id)); root.append(b);
      if (s.kind === "GROUP") parents.append(option(s.section_id, s.label));
      else {
        const wrap = node("label"), input = node("input"); input.type = "checkbox"; input.value = s.section_id; input.checked = s.section_id === selected;
        wrap.append(input, document.createTextNode(s.label)); print.append(wrap);
        const outputWrap = node("label"), outputInput = node("input");
        outputInput.type = "checkbox"; outputInput.value = s.section_id; outputInput.checked = s.section_id === selected;
        outputWrap.append(outputInput, document.createTextNode(s.label)); output.append(outputWrap);
      }
    }
    const chosen = section();
    if (chosen) {$("#excel-section-label").value = chosen.label; $("#excel-section-kind").value = chosen.kind; parents.value = chosen.parent_id || ""; $("#excel-numbering").value = chosen.numbering;}
    sync();
  }
  async function loadEdition(id, revision = null) {
    if (!mayLeave()) {$("#excel-editions").value = comp()?.edition_id || ""; return;}
    const actor = ownerEpoch, epoch = ++selectionEpoch;
    message("편성을 불러오는 중입니다.");
    try {
      const data = await query({query_kind: "READ_EDITION", edition_id: id, revision_id: revision});
      if (actor !== ownerEpoch || epoch !== selectionEpoch) return;
      applyComposition(data.composition, data.current_revision_id); message("");
      if (selected) await chooseSection(selected);
    } catch (error) {if (actor === ownerEpoch && epoch === selectionEpoch) message(`편성 조회 실패: ${error.message}`, true);}
  }
  function applyComposition(value, head) {
    usageKey = null; usageEpoch++; usageCounts.clear();
    if (productId !== value.deliverable_id) editions = [];
    productId = value.deliverable_id; currentRevision = head; draft.reset(value); selectionTarget = null; page = 0;
    const entry = {edition_id: value.edition_id, deliverable_id: value.deliverable_id, edition_label: value.edition_label};
    editions = [...editions.filter(row => row.edition_id !== value.edition_id), entry];
    $("#excel-editions").replaceChildren(...editions.map(row => option(row.edition_id, row.edition_label)));
    $("#excel-editions").value = value.edition_id; $("#excel-editions").disabled = false;
    if (!value.sections.some(s => s.section_id === selected)) selected = value.sections.find(s => s.kind === "FORM")?.section_id || value.sections[0]?.section_id || null;
    $("#excel-inspect").hidden = true; moreInspect = null;
    $("#excel-prints").replaceChildren(); printCursor = null;
    clearDeliveries();
    renderComposition(); renderRows();
  }
  async function ensureSection(id, epoch) {
    if (draft.loaded(id)) return;
    const value = comp(), rows = []; let after = 0;
    do {
      const result = await query({query_kind: "READ_SECTION", edition_id: value.edition_id,
        revision_id: value.deliverable_revision_id, composition_sha256: value.composition_sha256,
        section_id: id, after_position: after, limit: 200});
      if (epoch !== selectionEpoch || comp() !== value) return;
      rows.push(...result.rows);
      const titles = new Map((result.labels || []).map(value => [value.placement_id, value.title]));
      for (const row of result.rows) if (titles.has(row.placement_id)) labels.set(labelKey(row.target), titles.get(row.placement_id));
      if (result.next_position !== null && result.next_position <= after) throw new Error("문항 목록의 다음 위치가 올바르지 않습니다.");
      after = result.next_position;
    } while (after !== null);
    remember(rows); draft.load(id, rows);
  }
  async function chooseSection(id) {
    if (busy || pending) return;
    const epoch = ++selectionEpoch, actor = ownerEpoch;
    selected = id; page = 0; selectionTarget = null; renderComposition();
    loadingSection = section()?.kind === "FORM"; renderRows(); sync();
    try {if (loadingSection) await ensureSection(id, epoch);}
    catch (error) {if (epoch === selectionEpoch && actor === ownerEpoch) message(`문항 조회 실패: ${error.message}`, true);}
    finally {if (epoch === selectionEpoch && actor === ownerEpoch) {loadingSection = false; renderRows(); sync();}}
  }
  function renderRows() {
    const root = $("#excel-rows"); root.replaceChildren();
    const s = section(); $("#excel-section-title").textContent = s?.label || "회차를 추가해 주세요.";
    const rows = s?.kind === "FORM" && draft.loaded(selected) ? draft.rows(selected) : [];
    page = Math.min(page, Math.max(0, Math.ceil(rows.length / PAGE_SIZE) - 1));
    const duplicates = rows.length ? draft.duplicateCounts(selected) : new Map();
    for (const row of rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)) {
      const tr = node("tr"), numberCell = node("td"), item = node("td"), pointsCell = node("td"), noteCell = node("td"), actionsCell = node("td"), actions = node("div", undefined, "excel-row-actions");
      const number = node("input"); number.value = row.display_number || ""; number.placeholder = `${row.position}번`; number.maxLength = 32; number.setAttribute("aria-label", `${row.position}번 표시 번호`);
      number.addEventListener("change", () => {draft.update(selected, row.placement_id, {display_number: number.value.trim() || null}); sync();}); numberCell.append(number);
      item.append(node("div", label(row.target)));
      item.dataset.usageTarget = labelKey(row.target);
      const count = duplicates.get(targetIdentity(row.target)) || 0;
      item.dataset.localCount = String(count);
      if (count > 1) item.append(node("span", `이 회차에서 ${count}회 사용`, "excel-duplicate"));
      const usage = usageCounts.get(labelKey(row.target));
      if (usage?.edition_locations > count || usage?.other_locations > 0) {
        const caption = `${comp().academic_year === null ? "연도 없음" : comp().academic_year + "년"} 저장·인쇄 기록: 같은 판 ${usage.edition_locations}곳${usage.other_locations ? ` · 다른 판 ${usage.other_locations}곳` : ""}`;
        item.append(node("span", caption, "excel-duplicate excel-usage-summary"));
      }
      const points = node("input"); points.type = "number"; points.min = "0"; points.max = "1000"; points.step = "0.001"; points.value = row.points_milli === null ? "" : String(row.points_milli / 1000); points.setAttribute("aria-label", `${row.position}번 배점`);
      points.addEventListener("change", () => {if (points.reportValidity()) {draft.update(selected, row.placement_id, {points_milli: points.value === "" ? null : Math.round(Number(points.value) * 1000)}); sync();}}); pointsCell.append(points);
      const note = node("input"); note.value = row.note; note.maxLength = 2000; note.setAttribute("aria-label", `${row.position}번 메모`); note.addEventListener("change", () => {draft.update(selected, row.placement_id, {note: note.value}); sync();}); noteCell.append(note);
      for (const input of [number, points, note]) input.disabled = !editable();
      const change = fn => () => {if (!editable()) return; fn(); renderRows(); sync();};
      actions.append(button("↑", change(() => draft.move(selected, row.placement_id, selected, row.position - 2)), !editable() || row.position === 1),
        button("↓", change(() => draft.move(selected, row.placement_id, selected, row.position)), !editable() || row.position === rows.length),
        button("교체", () => beginSelection(row.placement_id), !editable()),
        button("빼기", change(() => draft.remove(selected, row.placement_id)), !editable()),
        button("다른 회차로", () => moveToSection(row), !editable()));
      if (row.target.placement_kind !== "EMPTY") actions.append(button("문항 열기", () => openTarget(row.target)), button("사용 이력", () => showUsage(row.target)));
      actionsCell.append(actions); tr.append(numberCell, item, pointsCell, noteCell, actionsCell); root.append(tr);
    }
      if (!rows.length) {const tr = node("tr"), td = node("td", loadingSection ? "문항을 불러오는 중입니다." : s?.kind === "GROUP" ? "왼쪽에서 이 그룹의 회차를 골라 주세요." : "DB에서 문항을 선택하거나 빈 자리를 추가해 주세요.", "empty-state"); td.colSpan = 5; tr.append(td); root.append(tr);}
    $("#excel-page").textContent = rows.length ? `${page * PAGE_SIZE + 1}–${Math.min(rows.length, (page + 1) * PAGE_SIZE)} / ${rows.length}문항` : "";
    $("#excel-prev-page").disabled = page === 0; $("#excel-next-page").disabled = (page + 1) * PAGE_SIZE >= rows.length;
    refreshUsageCounts(rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE));
  }
  async function refreshUsageCounts(rows) {
    const value = comp(); if (!owner || !value || busy || loadingSection) return;
    const unique = new Map(rows.filter(row => row.target.placement_kind !== "EMPTY").map(row => [labelKey(row.target), slotSelection(row.target)]));
    const targets = [...unique.values()]; if (!targets.length) return;
    const body = {query_kind: "USAGE_SUMMARY", targets, academic_year: value.academic_year, edition_id: value.edition_id};
    const key = JSON.stringify([value.deliverable_revision_id, body]); if (key === usageKey) return;
    usageKey = key; const epoch = ++usageEpoch, actor = ownerEpoch;
    $("#excel-usage-status").textContent = "사용 이력 확인 중…";
    try {
      const result = await query(body);
      if (epoch !== usageEpoch || actor !== ownerEpoch || value !== comp()) return;
      for (const count of result.rows) usageCounts.set(labelKey(targets[count.target_index]), count);
      // Update only badges: a late read must not replace an input being edited.
      for (const cell of $("#excel-rows").querySelectorAll("[data-usage-target]")) {
        cell.querySelector(".excel-usage-summary")?.remove();
        const count = usageCounts.get(cell.dataset.usageTarget);
        if (count?.edition_locations > Number(cell.dataset.localCount) || count?.other_locations > 0) {
          cell.append(node("span", `${value.academic_year === null ? "연도 없음" : value.academic_year + "년"} 저장·인쇄 기록: 같은 판 ${count.edition_locations}곳${count.other_locations ? ` · 다른 판 ${count.other_locations}곳` : ""}`, "excel-duplicate excel-usage-summary"));
        }
      }
      $("#excel-usage-status").textContent = "";
    } catch (error) {if (epoch === usageEpoch && actor === ownerEpoch) $("#excel-usage-status").textContent = "사용 이력 확인 실패 · 문항의 사용 이력에서 다시 확인해 주세요.";}
  }
  function beginSelection(placementId = null) {
    if (!editable() || !draft.loaded(selected)) return;
    selectionTarget = {editionId: comp().edition_id, sectionId: selected, placementId, ownerEpoch}; openItemDb();
  }
  function acceptSelection(target, title) {
    if (!selectionTarget || selectionTarget.ownerEpoch !== ownerEpoch || selectionTarget.editionId !== comp()?.edition_id || !editable()) return false;
    const context = selectionTarget; selected = context.sectionId;
    if (context.placementId) draft.update(selected, context.placementId, {target}); else draft.add(selected, target);
    labels.set(labelKey(target), title); selectionTarget = null; renderComposition(); renderRows(); sync();
    message("문항을 배치했습니다. 배치 저장을 눌러 확정해 주세요."); return true;
  }
  async function moveToSection(row) {
    const forms = comp().sections.filter(s => s.kind === "FORM" && s.section_id !== selected);
    if (!forms.length) {message("이동할 다른 회차가 없습니다."); return;}
    const index = Number(prompt(`이동할 회차 번호를 입력해 주세요.\n${forms.map((s, i) => `${i + 1}. ${s.label}`).join("\n")}`)) - 1;
    const target = forms[index]; if (!target || !editable()) return;
    const epoch = selectionEpoch, from = selected; loadingSection = true; sync();
    try {await ensureSection(target.section_id, epoch); if (epoch !== selectionEpoch) return;
      draft.move(from, row.placement_id, target.section_id, draft.rows(target.section_id).length); renderRows();
    } catch (error) {message(`이동 준비 실패: ${error.message}`, true);}
    finally {if (epoch === selectionEpoch) {loadingSection = false; renderRows(); sync();}}
  }
  async function commit(body, path = "commands") {
    if (!["commands", "prints", "deliveries"].includes(path)) throw new Error("지원하지 않는 저장 요청입니다.");
    if (busy || !owner || (pending && pending.body !== body)) return;
    if (!pending) pending = {body, path, key: `studio:excel:${globalThis.crypto.randomUUID()}`};
    const operation = pending, actor = ownerEpoch; busy = true; sync(); renderRows(); message("저장하고 있습니다.");
    try {
      const options = {method: "POST", mutation: true, body: operation.body, headers: {"Idempotency-Key": operation.key}};
      const result = operation.path === "prints"
        ? await api("/content-planning/prints", {...options, method: "POST"})
        : operation.path === "deliveries" ? await api("/content-planning/deliveries", {...options, method: "POST"})
        : await api("/content-planning/commands", {...options, method: "POST"});
      if (actor !== ownerEpoch) return;
      pending = null; busy = false;
      if (result.composition) {$("#excel-create-panel").open = false; applyComposition(result.composition, result.current_revision_id); if (selected) await chooseSection(selected); await refreshContents();}
      else if (operation.path === "deliveries") await loadDeliveries();
      else await loadPrints();
      message(result.current_revision_id && result.current_revision_id !== result.composition?.deliverable_revision_id ? "이 요청은 저장됐지만 이후 편집이 있습니다. 새로고침해 현재 편성을 확인해 주세요." : "저장했습니다.");
    } catch (error) {if (actor === ownerEpoch) message(`저장 결과 확인 실패: ${error.message} 같은 요청 다시 확인을 눌러 주세요.`, true);}
    finally {if (actor === ownerEpoch) {busy = false; sync(); renderRows();}}
  }
  async function copyEdition(empty = false) {
    if (!comp() || locked() || draft.dirty()) return;
    const name = prompt(empty ? "새 판 이름을 입력해 주세요." : "복사할 새 판 이름을 입력해 주세요."); if (!name?.trim()) return;
    const yearText = prompt("연도를 입력해 주세요. 연도 없이 관리하면 비워 두세요."); if (yearText === null) return;
    const year = yearText.trim() ? Number(yearText) : null;
    if (year !== null && (!Number.isInteger(year) || year < 1900 || year > 3000)) {message("연도를 확인해 주세요.", true); return;}
    await commit(empty ? {command_kind: "CREATE_EDITION", deliverable_id: comp().deliverable_id, edition_label: name.trim(), academic_year: year, sections: initialSections(1)}
      : {command_kind: "COPY_EDITION", source_edition_id: comp().edition_id, source_revision_id: comp().deliverable_revision_id, source_sha256: comp().composition_sha256, edition_label: name.trim(), academic_year: year});
  }
  function structureCommand(sections, removed = []) {
    return {command_kind: "EDIT_EDITION", edition_id: comp().edition_id, edit: {change_kind: "SAVE_STRUCTURE", expected_revision_id: comp().deliverable_revision_id,
      expected_sha256: comp().composition_sha256, edition_label: comp().edition_label, academic_year: comp().academic_year, sections, confirmed_removed_sections: removed}};
  }
  function structureRows() {return comp().sections.map(({form, ...s}) => s);}
  function orderStructure(values) {
    const children = new Map(); for (const s of values) {if (!children.has(s.parent_id)) children.set(s.parent_id, []); children.get(s.parent_id).push(s);}
    const stack = [...(children.get(null) || [])].reverse(), result = [], ordinals = new Map();
    while (stack.length) {const s = stack.pop(), n = (ordinals.get(s.parent_id) || 0) + 1; ordinals.set(s.parent_id, n); result.push({...s, ordinal: n}); stack.push(...[...(children.get(s.section_id) || [])].reverse());}
    if (result.length !== values.length) throw new Error("상위 그룹을 확인해 주세요."); return result;
  }
  async function editStructure(action) {
    if (!editable() || draft.dirty()) return;
    let values = structureRows(), removed = [];
    try {
      if (action === "ADD" || action === "UPDATE") {
        if (!$("#excel-section-form").reportValidity()) return;
        const old = section(), id = action === "UPDATE" ? old?.section_id : newPlanningId("section"); if (!id) return;
        const kind = $("#excel-section-kind").value;
        if (action === "UPDATE" && old.kind !== kind) {message("회차와 그룹의 종류를 바꾸려면 새 구성을 만든 뒤 이동해 주세요.", true); return;}
        const s = {section_id: id, parent_id: $("#excel-section-parent").value || null, kind, label: $("#excel-section-label").value.trim(), numbering: $("#excel-numbering").value, ordinal: 1};
        values = action === "ADD" ? [...values, s] : values.map(value => value.section_id === id ? s : value);
      } else if (action === "REMOVE") {
        if (!selected || !confirm("선택한 구성과 그 아래 배치를 현재 판에서 뺄까요? 이전 저장본과 인쇄 이력은 남습니다.")) return;
        const remove = new Set([selected]); for (const s of values) if (remove.has(s.parent_id)) remove.add(s.section_id);
        removed = [...remove]; values = values.filter(s => !remove.has(s.section_id));
      } else {
        const current = section(); if (!current) return;
        const siblings = values.filter(s => s.parent_id === current.parent_id), index = siblings.findIndex(s => s.section_id === selected), next = index + (action === "UP" ? -1 : 1);
        if (next < 0 || next >= siblings.length) return;
        const a = values.findIndex(s => s.section_id === selected), b = values.findIndex(s => s.section_id === siblings[next].section_id);
        [values[a], values[b]] = [values[b], values[a]];
      }
      await commit(structureCommand(orderStructure(values), removed));
    } catch (error) {message(error.message, true);}
  }
  function inspect(title, append) {$("#excel-inspect").hidden = false; $("#excel-inspect-title").textContent = title; const root = $("#excel-inspect-body"); if (!append) root.replaceChildren(); return root;}
  async function showHistory(before = null) {
    if (!comp()) return; const epoch = selectionEpoch, actor = ownerEpoch, id = comp().edition_id;
    try {
      const result = await query({query_kind: "HISTORY", edition_id: id, before_sequence: before, limit: 50});
      if (epoch !== selectionEpoch || actor !== ownerEpoch) return;
      const root = inspect("변경 이력", before !== null);
      for (const row of result.rows) root.append(button(`${dateText(row.created_at)} · ${CHANGE_LABELS[row.command_kind] || "편성 변경"}`, () => loadEdition(id, row.after_revision_id)));
      moreInspect = result.next_sequence === null ? null : () => showHistory(result.next_sequence); $("#excel-inspect-more").hidden = !moreInspect;
    } catch (error) {if (epoch === selectionEpoch && actor === ownerEpoch) message(`이력 조회 실패: ${error.message}`, true);}
  }
  async function showUsage(target, after = null) {
    const epoch = selectionEpoch, actor = ownerEpoch;
    try {
      const result = await query({query_kind: "USAGE", targets: [slotSelection(target)], academic_year: "ALL", after, limit: 100});
      if (epoch !== selectionEpoch || actor !== ownerEpoch) return;
      const root = inspect(`사용 이력 · ${result.total_locations}곳`, after !== null);
      if (after === null && can("usage:read")) root.append(button("이전 사용 기록", () => showPriorUsage(target)));
      if (!result.rows.length && after === null) root.append(node("p", "저장된 편성·인쇄 이력이 없습니다. 현재 초안은 저장 후 집계됩니다."));
      for (const row of result.rows) {
        const card = node("div", undefined, "excel-record"); card.append(node("p", `${row.content_title} · ${row.edition_label} · ${row.section_label} · ${row.position}번`),
          node("p", `${row.currently_placed ? "배치 중" : "현재 배치에서 제외"}${row.print_count ? ` · 인쇄 ${row.print_count}회` : " · 인쇄 전"}`), button("편성 열기", () => loadEdition(row.edition_id, row.revision_id))); root.append(card);
      }
      moreInspect = result.next_after ? () => showUsage(target, result.next_after) : null; $("#excel-inspect-more").hidden = !moreInspect;
    } catch (error) {if (epoch === selectionEpoch && actor === ownerEpoch) message(`사용 이력 조회 실패: ${error.message}`, true);}
  }
  async function showPriorUsage(target, after = null) {
    const epoch = selectionEpoch, actor = ownerEpoch;
    try {
      const result = await query({query_kind: "PRIOR_USAGE", targets: [slotSelection(target)], academic_year: "ALL", after, limit: 100});
      if (epoch !== selectionEpoch || actor !== ownerEpoch) return;
      const root = inspect("이전 사용 기록 · 연도 미지정", after !== null);
      if (after === null) root.append(button("편성·인쇄 이력으로 돌아가기", () => showUsage(target)));
      if (!result.rows.length && after === null) root.append(node("p", "이전에 기록된 사용 내역이 없습니다."));
      for (const row of result.rows) {
        const card = node("div", undefined, "excel-record");
        card.append(node("p", `${row.title} · ${row.section} · ${row.position}번`), node("p", `기록일 ${dateText(row.recorded_at)} · 학년도 정보 없음`)); root.append(card);
      }
      moreInspect = result.next_after ? () => showPriorUsage(target, result.next_after) : null; $("#excel-inspect-more").hidden = !moreInspect;
    } catch (error) {if (epoch === selectionEpoch && actor === ownerEpoch) message(`이전 사용 기록 조회 실패: ${error.message}`, true);}
  }
  async function loadPrints(append = false) {
    if (!comp()) return; const epoch = selectionEpoch, actor = ownerEpoch;
    try {
      const result = await query({query_kind: "PRINTS", edition_id: comp().edition_id, before_id: append ? printCursor : null, limit: 30});
      if (epoch !== selectionEpoch || actor !== ownerEpoch) return;
      const root = $("#excel-prints"); if (!append) root.replaceChildren();
      if (!result.rows.length && !append) root.append(node("p", "인쇄 기록이 없습니다."));
      for (const entry of result.rows) {
        const row = entry.record, card = node("div", undefined, "excel-record");
        card.append(node("p", `${row.printed_on || dateText(row.recorded_at)} · ${row.scope.forms.map(s => s.path.map(p => p.label).join(" / ")).join(", ")}`),
          node("p", entry.state === "VOIDED" ? "기록 취소" : entry.state === "CORRECTED" ? "정정된 이전 기록" : entry.matches_current_scope ? "현재 편성과 같은 인쇄본" : "인쇄 이후 편성 변경"));
        if (row.note || entry.reason) card.append(node("p", entry.reason || row.note));
        if (entry.state === "ACTIVE" && can("usage:fulfill_plan")) {
          card.append(button("오입력 취소", () => {const reason = prompt("인쇄 기록을 취소하는 이유를 입력해 주세요."); if (reason?.trim()) commit({command_kind: "VOID_PRINT", edition_id: row.scope.edition_id, print_record_id: row.print_record_id, record_sha256: row.record_sha256, reason: reason.trim()}, "prints");}));
          for (const [intent, caption] of [["REPRINT", "재인쇄 기록"], ["CORRECTION", "현재 편성으로 정정"]]) card.append(button(caption, () => recordPrint(intent, row.print_record_id), locked() || draft.dirty()));
        }
        root.append(card);
      }
      printCursor = result.next_id; $("#excel-more-prints").hidden = printCursor === null;
    } catch (error) {if (epoch === selectionEpoch && actor === ownerEpoch) message(`인쇄 기록 조회 실패: ${error.message}`, true);}
  }
  function clearDeliveries() {
    deliveryEpoch++; deliveryCursor = null;
    for (const control of deliveryControls) control.dispose();
    deliveryControls = []; $("#excel-deliveries").replaceChildren();
    $("#excel-more-deliveries").hidden = true;
  }
  async function loadDeliveries(append = false) {
    if (!comp()) return;
    if (!append) clearDeliveries();
    const epoch = ++deliveryEpoch, actor = ownerEpoch, revision = comp().deliverable_revision_id;
    try {
      const result = await query({query_kind: "DELIVERIES", edition_id: comp().edition_id,
        before_id: append ? deliveryCursor : null, limit: 30});
      if (epoch !== deliveryEpoch || actor !== ownerEpoch || revision !== comp()?.deliverable_revision_id) return;
      const root = $("#excel-deliveries");
      if (!result.rows.length && !append) root.append(node("p", "준비한 출력이 없습니다."));
      for (const entry of result.rows) {
        const row = entry.prepared, card = node("div", undefined, "excel-record");
        card.append(node("p", `${entry.section_labels.join(", ")}${entry.section_count > 3 ? ` 외 ${entry.section_count - 3}개 회차` : ""} · ${row.placement_count}문항 · ${dateText(row.created_at)}`),
          node("p", entry.matches_current_revision ? "현재 저장본" : "이전 저장본 · 준비 당시 편성 유지"));
        if (can("hwpx:read")) {
          const control = createCuratedDeliveryControl({document, api, entry: row, canCreate: can("hwpx:build_create")});
          deliveryControls.push(control); card.append(control.element);
        }
        root.append(card);
      }
      deliveryCursor = result.next_id; $("#excel-more-deliveries").hidden = deliveryCursor === null;
    } catch (error) {if (epoch === deliveryEpoch && actor === ownerEpoch) message(`출력 조회 실패: ${error.message}`, true);}
  }
  async function prepareDelivery() {
    if (!comp() || locked() || draft.dirty() || !can("hwpx:build_create")) return;
    const ids = [...$("#excel-delivery-sections").querySelectorAll("input:checked")].map(input => input.value);
    if (!ids.length) {message("내보낼 회차를 골라 주세요.", true); return;}
    await commit({command_kind: "PREPARE_DELIVERY", edition_id: comp().edition_id,
      revision_id: comp().deliverable_revision_id, composition_sha256: comp().composition_sha256,
      section_ids: ids}, "deliveries");
  }
  async function recordPrint(intent = "INITIAL", previous = null) {
    if (!comp() || locked() || draft.dirty()) return;
    const ids = [...$("#excel-print-sections").querySelectorAll("input:checked")].map(input => input.value);
    if (!ids.length) {message("실제로 인쇄한 회차를 골라 주세요.", true); return;}
    const note = $("#excel-print-note").value.trim();
    if (intent === "CORRECTION" && !note) {message("메모에 정정 이유를 입력해 주세요.", true); return;}
    if (!confirm("선택한 회차의 현재 저장본을 실제 인쇄한 것으로 기록할까요? HWPX 다운로드 여부와는 별개입니다.")) return;
    await commit({command_kind: "RECORD_PRINT", edition_id: comp().edition_id, revision_id: comp().deliverable_revision_id, composition_sha256: comp().composition_sha256,
      section_ids: ids, intent, predecessor_print_record_id: previous, printed_on: $("#excel-print-date").value || null, note}, "prints");
  }
  return {
    setOwner(value) {if (owner === value) return; clearDeliveries(); usageEpoch++; usageKey = null; usageCounts.clear(); owner = value; ownerEpoch++; selectionEpoch++; contentEpoch++; draft.reset(); labels.clear(); loaded = false; selected = null; productId = null; currentRevision = null; pending = null; selectionTarget = null; busy = false; loadingSection = false; contents = []; editions = []; contentCursor = null; editionCursor = null; printCursor = null; moreInspect = null; $("#excel-editor").hidden = true; $("#excel-empty").hidden = false; $("#excel-sections").replaceChildren(); $("#excel-editions").replaceChildren(); $("#excel-rows").replaceChildren(); $("#excel-prints").replaceChildren(); $("#excel-inspect-body").replaceChildren(); $("#excel-create").reset(); $("#excel-find").reset(); $("#excel-print-form").reset(); message(""); renderContents(); sync();},
    open() {active = true; if (owner && !loaded) refreshContents(); if (comp() && $("#excel-delivery-panel").open) loadDeliveries(); sync();},
    close() {active = false; clearDeliveries();},
    selectionHint: () => selectionTarget && !locked() ? `${comp().content_title} · ${comp().sections.find(s => s.section_id === selectionTarget.sectionId).label}` : null,
    acceptSelection,
    install() {
      $("#excel-find").addEventListener("submit", event => {event.preventDefault(); refreshContents();});
      $("#excel-more-contents").addEventListener("click", () => refreshContents(true));
      $("#excel-more-editions").addEventListener("click", () => selectProduct(productId, true));
      $("#excel-editions").addEventListener("change", event => loadEdition(event.target.value));
      $("#excel-refresh").addEventListener("click", async () => {
        if (busy || loadingSection) return;
        if (pending && !confirm("처리 결과를 현재 저장본에서 다시 확인할까요? 기존 요청을 새로 제출하지 않습니다.")) return;
        pending = null; sync(); if (comp()) await loadEdition(comp().edition_id); await refreshContents();
      });
      $("#excel-create").addEventListener("submit", event => {event.preventDefault(); if (locked() || !mayLeave()) return;
        commit({command_kind: "CREATE_CONTENT", content_title: $("#excel-name").value.trim(), content_type: $("#excel-type").value, edition_label: $("#excel-edition-name").value.trim(), academic_year: $("#excel-year").value ? Number($("#excel-year").value) : null, sections: initialSections(Number($("#excel-rounds").value))});});
      $("#excel-save").addEventListener("click", () => {const command = draft.command(); if (command && editable()) commit(command);});
      $("#excel-retry-button").addEventListener("click", () => {if (pending) commit(pending.body, pending.path);});
      $("#excel-empty-slot").addEventListener("click", () => {if (editable()) {draft.add(selected); renderRows(); sync();}});
      $("#excel-choose").addEventListener("click", () => beginSelection());
      $("#excel-copy").addEventListener("click", () => copyEdition());
      $("#excel-new-edition").addEventListener("click", () => copyEdition(true));
      $("#excel-history").addEventListener("click", () => showHistory());
      $("#excel-inspect-more").addEventListener("click", () => moreInspect?.());
      $("#excel-prev-page").addEventListener("click", () => {page--; renderRows();});
      $("#excel-next-page").addEventListener("click", () => {page++; renderRows();});
      $("#excel-section-form").addEventListener("submit", event => {event.preventDefault(); editStructure("ADD");});
      for (const [id, action] of [["update", "UPDATE"], ["remove", "REMOVE"], ["up", "UP"], ["down", "DOWN"]]) $("#excel-section-" + id).addEventListener("click", () => editStructure(action));
      $("#excel-print-form").addEventListener("submit", event => {event.preventDefault(); recordPrint();});
      $("#excel-print-refresh").addEventListener("click", () => loadPrints());
      $("#excel-more-prints").addEventListener("click", () => loadPrints(true));
      $("#excel-delivery-prepare").addEventListener("click", prepareDelivery);
      $("#excel-delivery-refresh").addEventListener("click", () => loadDeliveries());
      $("#excel-more-deliveries").addEventListener("click", () => loadDeliveries(true));
      document.defaultView?.addEventListener("beforeunload", event => {if (draft.dirty() || pending) {event.preventDefault(); event.returnValue = "";}});
      sync();
    },
  };
}
