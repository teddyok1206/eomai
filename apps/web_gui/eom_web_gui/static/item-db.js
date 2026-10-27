import {createItemDbDraft, selectedFinalSourcePlacement} from "./item-db-draft.js";

const MATCH_LABELS = Object.freeze({
  MATCHED: "파일 연결됨",
  MATCHED_DETECTED_HWPX: "파일 연결됨 · HWPX",
  MATCHED_IDENTICAL_COPIES: "파일 연결됨 · 동일 복사본",
  REJECTED: "반려",
  REJECTION_AMBIGUOUS: "반려 여부 확인 필요",
  DRAFT_ONLY: "최종본 없음",
  LINK_UNSUPPORTED: "파일 형식 확인 필요",
  DOCUMENT_MISSING: "파일 없음",
  NAME_MISMATCH: "파일 대응 확인 필요",
  CONTENT_CONFLICT: "파일 내용 확인 필요",
  FORMAT_MISMATCH: "파일 형식 불일치",
});

const CELL_LABELS = Object.freeze({
  A: "번호", B: "검토 난이도 1", C: "검토 난이도 2", D: "검토 난이도 3",
  E: "검토 난이도 4", F: "반려 사유", G: "교사 확인", H: "배점",
  I: "출제 의도", J: "평균 난이도", K: "원본 그림 파일", L: "1교",
  M: "2교", N: "3교", O: "학년", P: "시행 월", Q: "대단원",
  R: "소단원", S: "시행 연도", T: "고난도 여부", V: "교재 분류",
  U: "고유번호", W: "기출 변형 여부", X: "반려 여부", Y: "문항 분류", Z: "분야",
  AA: "자동 번호", AB: "작업자", AC: "출제일", AD: "출제자",
  AE: "지정 탐구", AF: "특이사항",
});
const FIELD_ORDER = ["U", "Q", "R", "Z", "Y", "V", "O", "AD", "AC", "J", "H", "X", "L", "M", "N"];
const FILTER_FIELDS = [...FIELD_ORDER, ...Object.keys(CELL_LABELS).filter((value) => !FIELD_ORDER.includes(value))];
const FILTER_OPERATORS = Object.freeze({
  EQ: "같음", NE: "다름", CONTAINS: "포함", IS_EMPTY: "값 없음", IS_NOT_EMPTY: "값 있음",
});
const SEARCH_FIELDS = ["MATCH_STATUS", ...FILTER_FIELDS];

function node(document, tag, className, value) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (value !== undefined) element.textContent = value;
  return element;
}

export function createItemDb({document, api, openRegisteredItem, canReadSource}) {
  const $ = (selector) => document.querySelector(selector);
  let cursor = null;
  let query = "";
  let loaded = false;
  let lastSourceAccess = null;
  let sequence = 0;
  let detailSequence = 0;
  let resultCount = 0;
  let selectedRow = null;
  let savedCursor = null;
  let savedSequence = 0;
  let pendingSave = null;
  const draft = createItemDbDraft();

  function renderDraft() {
    const root = $("#item-db-draft-list");
    root.replaceChildren();
    const entries = draft.entries();
    $("#item-db-draft-count").textContent = `${entries.length}개`;
    $("#item-db-draft-save").disabled = entries.length === 0;
    $("#item-db-draft-empty").hidden = entries.length > 0;
    entries.forEach((selection, index) => {
      const line = node(document, "li", "item-db-draft-row");
      const label = node(document, "span", "", selection.label);
      const actions = node(document, "span", "item-db-draft-actions");
      for (const [caption, next] of [
        ["위로", index - 1], ["아래로", index + 1],
      ]) {
        const button = node(document, "button", "button quiet", caption);
        button.type = "button";
        button.disabled = next < 0 || next >= entries.length;
        button.addEventListener("click", () => {
          draft.move(index, next);
          renderDraft();
        });
        actions.append(button);
      }
      const remove = node(document, "button", "button quiet", "빼기");
      remove.type = "button";
      remove.addEventListener("click", () => {
        draft.remove(index);
        renderDraft();
      });
      actions.append(remove);
      line.append(label, actions);
      root.append(line);
    });
  }

  function addToDraft(pointer, label) {
    const result = draft.add(pointer, label);
    if (result === "DUPLICATE") {
      message("이미 조립 목록에 담긴 문항입니다.");
      return;
    }
    if (result === "FULL") {
      message("조립 초안에는 문항을 최대 200개까지 담을 수 있습니다.", true);
      return;
    }
    renderDraft();
    message("조립 순서 초안에 담았습니다. 아직 HWPX를 만들지는 않았습니다.");
  }

  async function saveDraft() {
    const button = $("#item-db-draft-save");
    const proposal = draft.proposal();
    if (!proposal.placements.length) return;
    const signature = JSON.stringify(proposal);
    if (!pendingSave || pendingSave.signature !== signature) {
      pendingSave = {signature, key: `studio:curated-assembly:${crypto.randomUUID()}`};
    }
    button.disabled = true;
    message("조립 순서를 저장하고 있습니다.");
    try {
      const receipt = await api("/item-db/assemblies", {
        method: "POST", mutation: true, body: proposal,
        headers: {"Idempotency-Key": pendingSave.key},
      });
      if (!/^assembly_[0-9a-f]{32}$/.test(receipt.assembly_id)
        || receipt.placement_count !== proposal.placements.length) {
        throw new Error("저장 결과를 확인하지 못했습니다.");
      }
      message("조립 순서를 저장했습니다. 아래 목록에서 다시 열 수 있습니다.");
      await loadSaved(true);
    } catch (error) {
      message(`조립 순서 저장 실패: ${error.message || "다시 시도해 주세요."}`, true);
    } finally {
      button.disabled = draft.entries().length === 0;
    }
  }

  function savedLabel(placement) {
    if (placement.placement_kind === "EXTERNAL_SOURCE_DOCUMENT") {
      return `창작 원본 ${placement.external_number} · ${placement.edition}교 · ${placement.source_format}`;
    }
    return placement.placement_kind === "PAST_EXAM_ITEM_REVISION"
      ? "기출 승인 문항" : "창작 승인 문항";
  }

  async function openSaved(assemblyId) {
    message("저장한 조립 순서를 불러오는 중입니다.");
    try {
      const saved = await api(`/item-db/assemblies/${encodeURIComponent(assemblyId)}`);
      if (saved.assembly_id !== assemblyId || !Array.isArray(saved.placements)) {
        throw new Error("저장본이 올바르지 않습니다.");
      }
      const selections = saved.placements.map((placement) => {
        const {external_number, ...pointer} = placement;
        return {pointer, label: savedLabel(placement)};
      });
      if (!draft.replace(selections)) throw new Error("저장된 순서를 불러올 수 없습니다.");
      pendingSave = null;
      renderDraft();
      message("저장한 조립 순서를 다시 열었습니다. 바꾼 뒤 저장하면 별도 저장본이 됩니다.");
      $("#item-db-draft-title").scrollIntoView({block: "start"});
    } catch (error) {
      message(`저장본 열기 실패: ${error.message || "다시 시도해 주세요."}`, true);
    }
  }

  async function loadSaved(reset = false) {
    const request = ++savedSequence;
    if (reset) {
      savedCursor = null;
      $("#item-db-saved-list").replaceChildren();
    }
    const more = $("#item-db-saved-more");
    more.disabled = true;
    try {
      const params = new URLSearchParams({limit: "20"});
      if (savedCursor) params.set("cursor", savedCursor);
      const page = await api(`/item-db/assemblies?${params.toString()}`);
      if (request !== savedSequence) return;
      if (!Array.isArray(page.values)) throw new Error("저장본 목록이 올바르지 않습니다.");
      const root = $("#item-db-saved-list");
      for (const entry of page.values) {
        const line = node(document, "div", "item-db-draft-row");
        const time = new Intl.DateTimeFormat("ko-KR", {
          timeZone: "Asia/Seoul", dateStyle: "medium", timeStyle: "short",
        }).format(new Date(entry.created_at));
        const label = node(document, "span", "", `${time} · ${entry.placement_count}문항`);
        const open = node(document, "button", "button secondary", "다시 열기");
        open.type = "button";
        open.addEventListener("click", () => openSaved(entry.assembly_id));
        line.append(label, open);
        root.append(line);
      }
      if (!root.children.length) root.append(node(document, "p", "empty-state", "저장한 조립 순서가 없습니다."));
      savedCursor = page.next_cursor;
      more.hidden = !savedCursor;
    } catch (error) {
      if (request === savedSequence) message(`저장본 목록 조회 실패: ${error.message || "다시 시도해 주세요."}`, true);
    } finally {
      if (request === savedSequence) more.disabled = false;
    }
  }

  function message(value, error = false) {
    const element = $("#item-db-message");
    element.className = `form-message${error ? " error" : ""}`;
    element.textContent = value;
  }

  function option(value, label) {
    const item = node(document, "option", "", label);
    item.value = value;
    return item;
  }

  function syncFilterControls() {
    const count = $("#item-db-filter-rows").children.length;
    $("#item-db-filter-empty").hidden = count > 0;
    $("#item-db-filter-clear").hidden = count === 0;
    $("#item-db-filter-add").disabled = count >= 8;
  }

  function addFilter(selectedField = "U") {
    const rows = $("#item-db-filter-rows");
    if (rows.children.length >= 8) {
      message("검색 조건은 최대 8개까지 추가할 수 있습니다.", true);
      return;
    }
    const row = node(document, "div", "item-db-filter-row");
    const field = node(document, "select", "item-db-filter-field");
    field.setAttribute("aria-label", "검색할 항목");
    for (const column of SEARCH_FIELDS) field.append(option(column, column === "MATCH_STATUS" ? "파일 상태" : CELL_LABELS[column]));
    field.value = SEARCH_FIELDS.includes(selectedField) ? selectedField : "U";
    const operator = node(document, "select", "item-db-filter-operator");
    operator.setAttribute("aria-label", "검색 방법");
    for (const [value, label] of Object.entries(FILTER_OPERATORS)) operator.append(option(value, label));
    operator.value = ["U", "MATCH_STATUS"].includes(field.value) ? "EQ" : "CONTAINS";
    const value = node(document, "input", "item-db-filter-value");
    value.setAttribute("aria-label", "검색할 값");
    value.maxLength = 255;
    const status = node(document, "select", "item-db-status-value");
    status.setAttribute("aria-label", "파일 상태");
    for (const [key, label] of Object.entries(MATCH_LABELS)) status.append(option(key, label));
    const remove = node(document, "button", "item-db-filter-remove", "×");
    remove.type = "button";
    remove.setAttribute("aria-label", "이 조건 지우기");
    remove.addEventListener("click", () => {
      row.remove();
      syncFilterControls();
      $("#item-db-filter-add").focus();
    });
    function updateControls() {
      const statusField = field.value === "MATCH_STATUS";
      for (const item of operator.options) {
        item.disabled = statusField && !["EQ", "NE"].includes(item.value)
          || field.value === "U" && item.value.startsWith("IS_");
      }
      if (operator.selectedOptions[0].disabled) operator.value = "EQ";
      status.hidden = !statusField;
      status.disabled = !statusField;
      value.hidden = statusField || operator.value.startsWith("IS_");
      value.disabled = value.hidden;
      if (value.hidden) value.value = "";
      value.maxLength = field.value === "U" ? 5 : 255;
      value.inputMode = field.value === "U" ? "numeric" : "text";
      value.placeholder = field.value === "U" ? "예: 10310" : `${CELL_LABELS[field.value] || "내용"} 입력`;
    }
    field.addEventListener("change", updateControls);
    operator.addEventListener("change", updateControls);
    row.append(field, operator, value, status, remove);
    updateControls();
    rows.append(row);
    syncFilterControls();
    (field.value === "MATCH_STATUS" ? status : value).focus();
  }

  function filters() {
    const conditions = [...$("#item-db-filter-rows").children].map((row) => {
      const field = row.querySelector(".item-db-filter-field").value;
      const operator = row.querySelector(".item-db-filter-operator").value;
      const value = field === "MATCH_STATUS" ? row.querySelector(".item-db-status-value").value
        : row.querySelector(".item-db-filter-value").value.trim();
      if (operator !== "IS_EMPTY" && operator !== "IS_NOT_EMPTY" && !value) {
        throw new Error("검색 조건의 값을 입력해 주세요.");
      }
      if (field === "U" && ["EQ", "NE"].includes(operator) && !/^[0-9]{5}$/.test(value)) {
        throw new Error("고유번호는 숫자 5자리로 입력해 주세요.");
      }
      return {field, operator, value: operator.startsWith("IS_") ? null : value};
    });
    return {schema_version: "external-item-db-filter/1.0", match_mode: $("#item-db-match-mode").value,
      conditions, limit: 50, cursor: null};
  }

  function metadataList(values, className) {
    const list = node(document, "dl", className);
    for (const [label, value] of values) {
      const cell = node(document, "div", "");
      cell.append(node(document, "dt", "", label), node(document, "dd", "", value || "미입력"));
      list.append(cell);
    }
    return list;
  }

  function tableHeading(source) {
    const row = node(document, "tr", "");
    const labels = source === "EXTERNAL_SOURCE"
      ? ["고유번호", "분야", "대단원", "소단원", "학년", "출제자", "파일 상태"]
      : ["문항", "단원", "승인 상태", "HWPX 조립"];
    for (const label of labels) {
      const heading = node(document, "th", "", label);
      heading.scope = "col";
      row.append(heading);
    }
    $("#item-db-table-heading").replaceChildren(row);
  }

  function emptyResults(value, source) {
    const row = node(document, "tr", "");
    const cell = node(document, "td", "empty-state", value);
    cell.colSpan = source === "EXTERNAL_SOURCE" ? 7 : 4;
    row.append(cell);
    $("#item-db-results").replaceChildren(row);
  }

  function selectRow(row) {
    if (selectedRow) {
      selectedRow.classList.remove("is-selected");
      selectedRow.querySelector("button").setAttribute("aria-pressed", "false");
    }
    selectedRow = row;
    if (row) {
      row.classList.add("is-selected");
      row.querySelector("button").setAttribute("aria-pressed", "true");
    }
  }

  function resetDetail() {
    detailSequence++;
    selectRow(null);
    $("#item-db-detail-close").hidden = true;
    $("#item-db-detail").replaceChildren(node(document, "p", "empty-state", "왼쪽 표에서 문항을 선택하세요."));
  }

  function focusDetail(row) {
    selectRow(row);
    const panel = $("#item-db-detail-panel");
    $("#item-db-detail-close").hidden = false;
    if (window.matchMedia("(max-width: 1100px)").matches) panel.scrollIntoView({block: "start"});
    panel.focus({preventScroll: true});
  }

  function resultRow(key, caption, values, select) {
    const row = node(document, "tr", "");
    row.dataset.selectionKey = key;
    const first = node(document, "td", "");
    const open = node(document, "button", "item-db-row-open", caption);
    open.type = "button";
    open.setAttribute("aria-label", `${caption} 문항 정보 보기`);
    open.setAttribute("aria-pressed", "false");
    first.append(open);
    row.append(first);
    for (const value of values) row.append(node(document, "td", "", value || "—"));
    row.addEventListener("click", () => select(row));
    return row;
  }

  function renderEntry(entry) {
    return resultRow(entry.source_id, entry.external_number,
      [entry.field_label, entry.major_unit, entry.minor_unit, entry.grade_label, entry.author_label,
        MATCH_LABELS[entry.match_status] || "확인 필요"],
      (row) => openDetail(entry.source_id, row));
  }

  function graphLabel(entry) {
    const source = entry.source_class === "PAST_EXAM" ? "기출" : "창작·승인 문항";
    const display = /^itemrev_[0-9a-f]{32}$/.test(entry.source_display_label)
      ? "승인 문항" : entry.source_display_label;
    return `${source} · ${display}`;
  }

  function renderGraphEntry(entry) {
    return resultRow(entry.item_revision_id, graphLabel(entry),
      [entry.curriculum_units.map((unit) => unit.label).join(" · "),
        entry.item_revision_state === "APPROVED" ? "승인 완료" : "이전 승인 버전",
        entry.hwpx_exam_eligible ? "가능" : "대상 아님"],
      (row) => openGraphDetail(entry, row));
  }

  function openGraphDetail(entry, row) {
    detailSequence++;
    focusDetail(row);
    const root = $("#item-db-detail");
    root.replaceChildren(node(document, "h3", "", graphLabel(entry)), metadataList([
      ["문항 종류", entry.source_class === "PAST_EXAM" ? "기출" : "창작"],
      ["승인 상태", entry.item_revision_state === "APPROVED" ? "승인 완료" : "이전 승인 버전"],
      ["단원", entry.curriculum_units.map((unit) => unit.label).join(" · ")],
      ["HWPX 조립", entry.hwpx_exam_eligible ? "가능" : "대상 아님"],
    ], "item-db-detail-summary"));
    const button = node(document, "button", "button secondary", "문항 미리보기");
    button.type = "button";
    button.addEventListener("click", () => openRegisteredItem(entry));
    const select = node(document, "button", "button quiet", "조립 목록에 담기");
    select.type = "button";
    select.disabled = !entry.hwpx_exam_eligible;
    if (select.disabled) select.title = "이 문항 버전은 현재 HWPX 조립 대상이 아닙니다.";
    select.addEventListener("click", () => addToDraft({
      placement_kind: entry.source_class === "PAST_EXAM"
        ? "PAST_EXAM_ITEM_REVISION" : "REGISTERED_ITEM_REVISION",
      item_id: entry.item_id,
      item_revision_id: entry.item_revision_id,
      item_manifest_sha256: entry.item_manifest_sha256,
      graph_snapshot_revision_id: entry.graph_snapshot_revision_id,
      graph_snapshot_sha256: entry.snapshot_sha256,
    }, graphLabel(entry)));
    const actions = node(document, "div", "item-db-result-actions");
    actions.append(button, select);
    root.append(actions);
  }

  function selectedSource() { return $("#item-db-source").value; }

  function syncSourceControls() {
    const graph = selectedSource() !== "EXTERNAL_SOURCE";
    $("#item-db-source-filters").hidden = graph;
    $("#item-db-graph-filters").hidden = !graph;
    $("#item-db-filter-add").hidden = graph;
    $("#item-db-export").hidden = graph;
  }

  function syncSourceAccess() {
    const allowed = canReadSource();
    const option = $("#item-db-source").querySelector('option[value="EXTERNAL_SOURCE"]');
    option.hidden = !allowed;
    option.disabled = !allowed;
    if (!allowed && selectedSource() === "EXTERNAL_SOURCE") $("#item-db-source").value = "PAST_EXAM";
    syncSourceControls();
    const changed = lastSourceAccess !== allowed;
    lastSourceAccess = allowed;
    return changed;
  }

  async function load(reset = false) {
    const source = selectedSource();
    let parameters;
    try {
      parameters = source === "EXTERNAL_SOURCE" ? filters()
        : {source_class: source, curriculum_unit_key: $("#item-db-graph-unit").value};
    } catch (error) {
      message(error.message, true);
      return;
    }
    const request = ++sequence;
    const key = JSON.stringify(parameters);
    if (reset || key !== query) {
      query = key;
      cursor = null;
      resetDetail();
      $("#item-db-results").replaceChildren();
      tableHeading(source);
      resultCount = 0;
      loaded = false;
    }
    parameters.cursor = cursor;
    const more = $("#item-db-more");
    more.disabled = true;
    $("#item-db-results").setAttribute("aria-busy", "true");
    $("#item-db-result-count").textContent = "조회 중";
    message("문항을 찾고 있습니다.");
    try {
      const page = source === "EXTERNAL_SOURCE"
        ? await api("/item-db/external-sources/search", {
          method: "POST", mutation: true, body: parameters,
        })
        : await api(`/item-db/graph-items?${new URLSearchParams({
          source_class: source,
          ...(parameters.curriculum_unit_key ? {curriculum_unit_key: parameters.curriculum_unit_key} : {}),
          ...(cursor ? {cursor} : {}),
        }).toString()}`);
      if (request !== sequence) return;
      const root = $("#item-db-results");
      for (const entry of page.values) root.append(source === "EXTERNAL_SOURCE"
        ? renderEntry(entry) : renderGraphEntry(entry));
      resultCount += page.values.length;
      if (!resultCount) emptyResults("조건에 맞는 문항이 없습니다.", source);
      cursor = page.next_cursor;
      more.hidden = !page.has_more;
      $("#item-db-result-count").textContent = `${resultCount}개 표시${page.has_more ? " · 더 있음" : ""}`;
      message(source === "EXTERNAL_SOURCE" ? "원본 보관 문항입니다. 등록·승인된 문항과 구분됩니다." : "등록·승인된 문항에서 조회했습니다.");
      loaded = true;
    } catch (error) {
      if (request === sequence) {
        $("#item-db-result-count").textContent = resultCount ? `${resultCount}개 표시` : "조회 실패";
        if (!resultCount) emptyResults("문항을 불러오지 못했습니다. 다시 조회해 주세요.", source);
        message(`문항 조회 실패: ${error.message || "잠시 후 다시 시도해 주세요."}`, true);
      }
    } finally {
      if (request === sequence) {
        more.disabled = false;
        $("#item-db-results").setAttribute("aria-busy", "false");
      }
    }
  }

  async function openDetail(sourceId, row) {
    const request = ++detailSequence;
    const root = $("#item-db-detail");
    focusDetail(row);
    root.replaceChildren(node(document, "p", "empty-state", "문항 정보를 불러오는 중입니다."));
    try {
      const detail = await api(`/item-db/external-sources/${encodeURIComponent(sourceId)}`);
      if (request !== detailSequence || detail.entry.source_id !== sourceId) return;
      root.replaceChildren();
      const byColumn = new Map(detail.cells.map((cell) => [cell.column, cell]));
      const cellValue = (column) => byColumn.get(column)?.raw_text || "";
      const placement = selectedFinalSourcePlacement(detail);
      const heading = node(document, "div", "item-db-detail-heading");
      const title = node(document, "div", "item-db-result-heading");
      title.append(node(document, "h3", "", `고유번호 ${detail.entry.external_number}`),
        node(document, "span", "status-badge tone-neutral", "창작 원본 · 원본 보관"));
      heading.append(title);
      if (placement) {
        const chosen = detail.editions.find((edition) => edition.edition === placement.edition);
        if (chosen) {
          const select = node(document, "button", "button primary", "조립 목록에 담기");
          select.type = "button";
          select.addEventListener("click", () => addToDraft(placement,
            `창작 원본 ${detail.entry.external_number} · ${chosen.edition}교 · ${chosen.filename}`));
          heading.append(select);
        }
      }
      root.append(heading, metadataList([
        ["대단원", cellValue("Q")], ["소단원", cellValue("R")], ["분야", cellValue("Z")],
        ["문항 분류", cellValue("Y")], ["난이도", cellValue("J")], ["배점", cellValue("H")],
        ["학년", cellValue("O")], ["교재 분류", cellValue("V")],
        ["출제자", cellValue("AD")], ["출제일", cellValue("AC")],
      ], "item-db-detail-summary"));
      const editionsSection = node(document, "section", "item-db-detail-section");
      editionsSection.append(node(document, "h3", "", "교정본 파일"));
      const editions = node(document, "div", "item-db-editions");
      const previousEditions = node(document, "details", "item-db-previous-editions");
      previousEditions.append(node(document, "summary", "", "이전 교정본 보기"));
      for (const edition of detail.editions) {
        const isFinal = placement?.edition === edition.edition;
        const line = node(document, "div", `item-db-edition${isFinal ? " is-final" : ""}`);
        const editionHeading = node(document, "div", "item-db-edition-heading");
        editionHeading.append(node(document, "strong", "", `${edition.edition}교`),
          node(document, "span", `status-badge ${isFinal ? "tone-success" : "tone-neutral"}`,
            isFinal ? "최종본" : edition.edition === 1 ? "초안" : "교정본"));
        line.append(editionHeading);
        if (edition.available && edition.filename) {
          const link = node(document, "a", "item-db-edition-file", edition.filename);
          link.href = `/studio/api/v1/item-db/external-sources/${encodeURIComponent(sourceId)}`
            + `/editions/${edition.edition}/download?source_revision_id=${encodeURIComponent(detail.entry.source_revision_id)}`;
          line.append(link);
          const preview = node(document, "a", "item-db-preview-link", "PDF 열기");
          preview.href = `/studio/api/v1/item-db/external-sources/${encodeURIComponent(sourceId)}`
            + `/editions/${edition.edition}/preview.pdf?source_revision_id=${encodeURIComponent(detail.entry.source_revision_id)}`;
          preview.target = "_blank";
          preview.rel = "noopener noreferrer";
          preview.hidden = true;
          const prepare = node(document, "button", "button quiet", "PDF 미리보기 준비");
          prepare.type = "button";
          prepare.addEventListener("click", async () => {
            prepare.disabled = true;
            prepare.textContent = "PDF 준비 중…";
            try {
              const result = await api(`/item-db/external-sources/${encodeURIComponent(sourceId)}`
                + `/editions/${edition.edition}/preview?source_revision_id=${encodeURIComponent(detail.entry.source_revision_id)}`,
              {method: "POST", mutation: true});
              if (request !== detailSequence) return;
              if (typeof result.sha256 !== "string" || !/^sha256:[0-9a-f]{64}$/.test(result.sha256)) {
                throw new Error("PDF 준비 결과가 올바르지 않습니다.");
              }
              preview.hidden = false;
              prepare.remove();
              message("PDF 미리보기가 준비됐습니다. 'PDF 열기'를 누르세요.");
            } catch (error) {
              if (request !== detailSequence) return;
              prepare.disabled = false;
              prepare.textContent = "PDF 미리보기 준비";
              message(`PDF를 준비하지 못했습니다: ${error.message || "다시 시도해 주세요."}`, true);
            }
          });
          const actions = node(document, "div", "item-db-edition-actions");
          actions.append(prepare, preview);
          line.append(actions);
        } else {
          line.append(node(document, "span", "item-db-edition-file", edition.filename || "파일 확인 필요"));
        }
        line.append(node(document, "span", "item-db-unit-path", MATCH_LABELS[edition.match_status] || "확인 필요"));
        if (placement && !isFinal) previousEditions.append(line);
        else editions.append(line);
      }
      if (previousEditions.children.length > 1) editions.append(previousEditions);
      editionsSection.append(editions);
      root.append(editionsSection);
      for (const [column, label] of [["I", "출제 의도"], ["AF", "특이사항"]]) {
        if (!cellValue(column)) continue;
        const section = node(document, "section", "item-db-detail-section");
        section.append(node(document, "h3", "", label), node(document, "p", "", cellValue(column)));
        root.append(section);
      }
      const remaining = node(document, "details", "item-db-detail-section");
      remaining.append(node(document, "summary", "", "검토·관리 정보 더 보기"));
      const metadata = node(document, "dl", "item-db-metadata");
      const primaryColumns = new Set(["Q", "R", "Z", "Y", "J", "H", "O", "V", "AD", "AC", "I", "AF"]);
      for (const cell of detail.cells) {
        // The original U value is shown once in the heading; L/M/N are filenames above.
        if (["U", "L", "M", "N"].includes(cell.column)) continue;
        if (primaryColumns.has(cell.column)) continue;
        if (!cell.present && !cell.raw_text) continue;
        metadata.append(
          node(document, "dt", "", CELL_LABELS[cell.column] || cell.column),
          node(document, "dd", "", cell.raw_text || "비어 있음"),
        );
      }
      remaining.append(metadata);
      if (metadata.children.length) root.append(remaining);
    } catch (error) {
      if (request === detailSequence) root.replaceChildren(node(document, "p", "empty-state", `정보를 불러오지 못했습니다: ${error.message || "다시 시도해 주세요."}`));
    }
  }

  async function exportRows() {
    const button = $("#item-db-export");
    let parameters;
    try {
      parameters = filters();
    } catch (error) {
      message(error.message, true);
      return;
    }
    button.disabled = true;
    message("검색 결과를 엑셀로 준비하고 있습니다.");
    try {
      const blob = await api("/item-db/external-sources/export", {
        method: "POST", mutation: true, body: parameters, binary: true,
      });
      if (blob.type !== "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet") {
        throw new Error("엑셀 파일 형식이 올바르지 않습니다.");
      }
      const url = URL.createObjectURL(blob);
      const link = node(document, "a", "");
      link.href = url;
      link.download = "EOM-item-database.xlsx";
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
      message("검색 결과 엑셀 파일을 다운로드했습니다.");
    } catch (error) {
      message(`엑셀 저장 실패: ${error.message || "잠시 후 다시 시도해 주세요."}`, true);
    } finally {
      button.disabled = false;
    }
  }

  return Object.freeze({
    install() {
      renderDraft();
      syncFilterControls();
      tableHeading(selectedSource());
      $("#item-db-source").addEventListener("change", () => {
        syncSourceControls();
        load(true);
      });
      $("#item-db-filter-add").addEventListener("click", () => addFilter());
      $("#item-db-filter-quick").addEventListener("click", (event) => {
        const button = event.target.closest("[data-filter-field]");
        if (button) addFilter(button.dataset.filterField);
      });
      $("#item-db-filter-clear").addEventListener("click", () => {
        $("#item-db-filter-rows").replaceChildren();
        $("#item-db-match-mode").value = "ALL";
        syncFilterControls();
      });
      $("#item-db-form").addEventListener("submit", (event) => {
        event.preventDefault();
        load(true);
      });
      $("#item-db-more").addEventListener("click", () => load(false));
      $("#item-db-export").addEventListener("click", exportRows);
      $("#item-db-draft-save").addEventListener("click", saveDraft);
      $("#item-db-saved-refresh").addEventListener("click", () => loadSaved(true));
      $("#item-db-saved-more").addEventListener("click", () => loadSaved(false));
      $("#item-db-detail-close").addEventListener("click", () => {
        const button = selectedRow?.querySelector("button");
        resetDetail();
        button?.focus();
      });
    },
    open() {
      const changed = syncSourceAccess();
      if (changed || !loaded) load(true);
      loadSaved(true);
    },
    setCurriculumUnits(units) {
      const select = $("#item-db-graph-unit");
      const selected = select.value;
      select.replaceChildren(option("", "전체 단원"));
      const byKey = new Map(units.map((unit) => [unit.key, unit]));
      for (const unit of units) {
        const parent = unit.parent_key ? byKey.get(unit.parent_key) : null;
        select.append(option(unit.key, `${unit.code} ${unit.label}${parent ? ` · ${parent.label}` : ""}`));
      }
      if ([...select.options].some((item) => item.value === selected)) select.value = selected;
    },
  });
}
