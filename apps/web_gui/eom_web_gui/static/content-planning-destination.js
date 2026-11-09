// Destination input only. Existing Catalog queries own access and pointer validation;
// the caller owns unsaved-edit confirmation, exact slot reads and actual placement.
export function createPlanningDestinationPicker({document, query}) {
  let owner = null, opened = null;
  const node = (tag, text, className = "") => {
    const value = document.createElement(tag); value.className = className;
    if (text !== undefined) value.textContent = text;
    return value;
  };
  const option = (value, text) => {const result = node("option", text); result.value = value; return result;};
  function button(text, action) {
    const result = node("button", text, "button quiet"); result.type = "button";
    result.addEventListener("click", action); return result;
  }
  function finish(state, value) {
    if (opened !== state) return;
    opened = null;
    state.dialog.close(); state.dialog.remove(); state.resolve(value);
    if (state.focus?.isConnected) state.focus.focus();
  }
  function close() {if (opened) finish(opened, null);}

  function choose({selectionCount}) {
    close();
    if (!owner || !Number.isSafeInteger(selectionCount) || selectionCount < 1) return Promise.resolve(null);
    const dialog = node("dialog", undefined, "panel excel-main");
    dialog.id = "excel-destination-dialog";
    dialog.setAttribute("aria-labelledby", "excel-destination-title");
    dialog.style.width = "min(600px, calc(100vw - 32px))";
    dialog.style.maxHeight = "calc(100vh - 32px)";
    dialog.style.overflow = "auto";
    const title = node("h2", "문항을 배치할 곳 선택"); title.id = "excel-destination-title";
    const searchForm = node("form", undefined, "excel-inline");
    const search = node("input"); search.type = "search"; search.maxLength = 200;
    search.setAttribute("aria-label", "콘텐츠 이름 검색"); search.placeholder = "콘텐츠 이름";
    const find = node("button", "찾기", "button secondary"); find.type = "submit";
    searchForm.append(search, find);
    const fields = node("div", undefined, "form-grid excel-fields");
    function field(caption, id, control) {
      const label = node("label", caption, "wide"); control.id = id; label.htmlFor = id;
      label.append(control); fields.append(label); return label;
    }
    const contents = node("select"), editions = node("select"), sections = node("select");
    field("콘텐츠", "excel-destination-content", contents);
    const contentPages = node("div", undefined, "form-actions wide"); fields.append(contentPages);
    field("판 / 연도", "excel-destination-edition", editions);
    const editionPages = node("div", undefined, "form-actions wide"); fields.append(editionPages);
    field("회차 / 구간", "excel-destination-section", sections);
    const mode = node("select"); mode.append(option("INSERT", "사이에 넣기"), option("REPLACE", "문항 하나 교체"));
    field("배치 방식", "excel-destination-mode", mode);
    const position = node("input"); position.type = "number"; position.min = "1"; position.step = "1";
    const positionLabel = field("넣을 위치", "excel-destination-position", position);
    const status = node("p", "", "form-message"); status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite");
    const actions = node("div", undefined, "form-actions");
    const cancel = button("취소", close), submit = button("여기에 배치", submitSelection);
    submit.className = "button primary"; actions.append(cancel, submit);
    dialog.append(title, searchForm, fields, status, actions);
    const promise = new Promise(resolve => {
      opened = {owner, dialog, resolve, focus: document.activeElement,
        contentEpoch: 0, editionEpoch: 0, readEpoch: 0,
        product: null, searchText: "", editionRows: new Map(), composition: null, currentRevision: null,
        forms: new Map(), contentCursors: [null], editionCursors: [null],
        contentPage: 0, editionPage: 0, contentNext: null, editionNext: null};
    });
    const state = opened;
    const current = () => opened === state && owner === state.owner;
    const message = (text, error = false) => {status.textContent = text; status.className = `form-message${error ? " error" : ""}`;};
    function resetSelect(select, caption) {select.replaceChildren(option("", caption)); select.disabled = true;}
    function clearComposition() {
      state.readEpoch++; state.composition = null; state.currentRevision = null; state.forms.clear();
      resetSelect(sections, "회차를 선택해 주세요"); syncPosition(true);
    }
    function clearEditions() {
      state.editionEpoch++; state.editionRows.clear(); state.editionNext = null;
      state.editionCursors = [null]; state.editionPage = 0;
      resetSelect(editions, "판을 선택해 주세요"); clearComposition(); syncPaging();
    }
    function paging(root, prefix, load, cursors, pageKey, nextKey) {
      const previous = button(`이전 ${prefix}`, () => {
        if (!current() || !state[pageKey]) return;
        state[pageKey]--; load(state[cursors][state[pageKey]]);
      });
      const next = button(`다음 ${prefix}`, () => {
        if (!current() || !state[nextKey]) return;
        state[cursors][++state[pageKey]] = state[nextKey]; load(state[nextKey]);
      });
      root.append(previous, next); return {previous, next};
    }
    const contentPaging = paging(contentPages, "콘텐츠", loadContents, "contentCursors", "contentPage", "contentNext");
    const editionPaging = paging(editionPages, "판", loadEditions, "editionCursors", "editionPage", "editionNext");
    function syncPaging() {
      contentPaging.previous.disabled = state.contentPage === 0 || contents.disabled;
      contentPaging.next.disabled = !state.contentNext || contents.disabled;
      editionPaging.previous.disabled = state.editionPage === 0 || editions.disabled;
      editionPaging.next.disabled = !state.editionNext || editions.disabled;
    }
    function syncPosition(reset = false) {
      const selected = state.forms.get(sections.value);
      const count = selected?.form.placement_count ?? 0;
      const replacement = mode.querySelector('option[value="REPLACE"]');
      replacement.disabled = selectionCount !== 1 || count === 0;
      replacement.hidden = selectionCount !== 1;
      if (replacement.disabled) mode.value = "INSERT";
      const replacing = mode.value === "REPLACE", maximum = count + (replacing ? 0 : 1);
      mode.disabled = !selected; position.disabled = !selected;
      position.max = String(maximum);
      positionLabel.firstChild.textContent = replacing ? "교체할 문항 번호" : "넣을 위치";
      if (reset || !position.value || Number(position.value) > maximum) position.value = String(replacing ? 1 : maximum);
      submit.disabled = !selected;
    }
    async function loadContents(after = null) {
      if (!current()) return;
      const epoch = ++state.contentEpoch; state.product = null; state.contentNext = null;
      resetSelect(contents, "콘텐츠를 선택해 주세요"); clearEditions(); message("콘텐츠를 불러오는 중입니다.");
      try {
        const data = await query({query_kind: "LIST_CONTENTS", text: state.searchText, limit: 50, after_id: after});
        if (!current() || epoch !== state.contentEpoch) return;
        contents.append(...data.rows.map(row => option(row.deliverable_id, row.title)));
        contents.disabled = data.rows.length === 0; state.contentNext = data.next_id;
        message(data.rows.length ? "" : "검색된 콘텐츠가 없습니다.");
      } catch (error) {if (current() && epoch === state.contentEpoch) message(`콘텐츠 조회 실패: ${error.message}`, true);}
      finally {if (current() && epoch === state.contentEpoch) syncPaging();}
    }
    async function loadEditions(after = null) {
      if (!current() || !state.product) return;
      const epoch = ++state.editionEpoch, product = state.product;
      state.editionRows.clear(); state.editionNext = null;
      resetSelect(editions, "판을 선택해 주세요"); clearComposition(); syncPaging(); message("판을 불러오는 중입니다.");
      try {
        const data = await query({query_kind: "LIST_EDITIONS", deliverable_id: product, limit: 50, after_id: after});
        if (!current() || epoch !== state.editionEpoch) return;
        state.editionRows = new Map(data.rows.map(row => [row.edition_id, row]));
        editions.append(...data.rows.map(row => option(row.edition_id, row.edition_label)));
        editions.disabled = data.rows.length === 0; state.editionNext = data.next_id;
        message(data.rows.length ? "" : "선택할 판이 없습니다.");
      } catch (error) {if (current() && epoch === state.editionEpoch) message(`판 조회 실패: ${error.message}`, true);}
      finally {if (current() && epoch === state.editionEpoch) syncPaging();}
    }
    async function loadComposition() {
      const entry = state.editionRows.get(editions.value); clearComposition();
      if (!current() || !entry) return;
      const epoch = state.readEpoch; message("저장된 회차를 확인하고 있습니다.");
      try {
        const data = await query({query_kind: "READ_EDITION", edition_id: entry.edition_id, revision_id: entry.revision_id});
        if (!current() || epoch !== state.readEpoch) return;
        const value = data.composition;
        if (value.deliverable_id !== state.product || value.edition_id !== entry.edition_id
          || value.deliverable_revision_id !== entry.revision_id || value.composition_sha256 !== entry.composition_sha256
          || data.current_revision_id !== entry.revision_id) {
          throw new Error("편성이 바뀌었습니다. 콘텐츠를 다시 선택해 최신 판 목록을 확인해 주세요.");
        }
        state.composition = value; state.currentRevision = data.current_revision_id;
        const paths = new Map();
        for (const section of value.sections) {
          const parent = paths.get(section.parent_id);
          paths.set(section.section_id, parent ? `${parent} / ${section.label}` : section.label);
          if (section.kind === "FORM") state.forms.set(section.section_id, section);
        }
        sections.append(...[...state.forms.values()].map(section => option(section.section_id,
          `${paths.get(section.section_id)} · ${section.form.placement_count}문항`)));
        sections.disabled = state.forms.size === 0;
        message(state.forms.size ? "" : "이 판에는 문항을 넣을 회차가 없습니다. Excel에서 회차를 먼저 만들어 주세요.");
      } catch (error) {if (current() && epoch === state.readEpoch) message(`회차 조회 실패: ${error.message}`, true);}
    }
    function submitSelection() {
      const section = state.forms.get(sections.value);
      if (!current() || !state.composition || !section || !position.reportValidity()) return;
      const ordinal = Number(position.value), replacing = mode.value === "REPLACE";
      if (!Number.isSafeInteger(ordinal) || ordinal < 1
        || ordinal > section.form.placement_count + (replacing ? 0 : 1)
        || (replacing && selectionCount !== 1)) return;
      finish(state, {composition: state.composition, currentRevisionId: state.currentRevision,
        sectionId: section.section_id, index: ordinal - 1, replacePosition: replacing ? ordinal : null});
    }
    searchForm.addEventListener("submit", event => {
      event.preventDefault(); if (!current()) return;
      state.searchText = search.value.trim(); state.contentCursors = [null]; state.contentPage = 0; loadContents();
    });
    contents.addEventListener("change", () => {if (current()) {state.product = contents.value; clearEditions(); loadEditions();}});
    editions.addEventListener("change", loadComposition);
    sections.addEventListener("change", () => syncPosition(true));
    mode.addEventListener("change", () => syncPosition());
    dialog.addEventListener("cancel", event => {event.preventDefault(); finish(state, null);});
    dialog.addEventListener("close", () => finish(state, null));
    resetSelect(contents, "콘텐츠를 선택해 주세요");
    resetSelect(editions, "판을 선택해 주세요"); resetSelect(sections, "회차를 선택해 주세요"); syncPosition(true);
    document.body.append(dialog); dialog.showModal(); search.focus(); loadContents();
    return promise;
  }
  return Object.freeze({choose, close, setOwner(value) {if (owner !== value) {close(); owner = value;}}});
}
