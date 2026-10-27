const MATCH_LABELS = Object.freeze({
  MATCHED: "최종 파일 연결됨",
  MATCHED_DETECTED_HWPX: "최종 파일 연결됨 · HWPX",
  MATCHED_IDENTICAL_COPIES: "최종 파일 연결됨 · 동일 복사본",
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
  EQ: "일치", NE: "불일치", CONTAINS: "포함", IS_EMPTY: "비어 있음", IS_NOT_EMPTY: "비어 있지 않음",
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

  function addFilter() {
    const rows = $("#item-db-filter-rows");
    if (rows.children.length >= 8) {
      message("검색 조건은 최대 8개까지 추가할 수 있습니다.", true);
      return;
    }
    const row = node(document, "div", "item-db-filter-row");
    const field = node(document, "select", "item-db-filter-field");
    field.setAttribute("aria-label", "검색할 항목");
    for (const column of SEARCH_FIELDS) field.append(option(column, column === "MATCH_STATUS" ? "파일 상태" : CELL_LABELS[column]));
    const operator = node(document, "select", "item-db-filter-operator");
    operator.setAttribute("aria-label", "검색 방법");
    for (const [value, label] of Object.entries(FILTER_OPERATORS)) operator.append(option(value, label));
    const value = node(document, "input", "item-db-filter-value");
    value.setAttribute("aria-label", "검색할 값");
    value.maxLength = 255;
    const status = node(document, "select", "item-db-status-value");
    status.setAttribute("aria-label", "파일 상태");
    for (const [key, label] of Object.entries(MATCH_LABELS)) status.append(option(key, label));
    const remove = node(document, "button", "button quiet", "삭제");
    remove.type = "button";
    remove.addEventListener("click", () => row.remove());
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
    }
    field.addEventListener("change", updateControls);
    operator.addEventListener("change", updateControls);
    row.append(field, operator, value, status, remove);
    updateControls();
    rows.append(row);
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

  function renderEntry(entry) {
    const card = node(document, "article", "item-bank-card");
    const heading = node(document, "h3", "", `${entry.external_number} · ${entry.selected_filename || "원본 파일 확인 필요"}`);
    const summary = node(document, "p", "", [entry.major_unit, entry.minor_unit, entry.field_label]
      .filter(Boolean).join(" · ") || "단원 정보 없음");
    const graphState = entry.graph_state === "NOT_PUBLISHED" ? "Graph 미게시" : "Graph 상태 확인 필요";
    const state = node(document, "p", "", `${MATCH_LABELS[entry.match_status] || "확인 필요"} · ${graphState}`);
    const similarity = node(document, "p", "", "유사도 준비 전 · 원본 문항은 아직 임베딩되지 않았습니다.");
    const button = node(document, "button", "button secondary", "문항 정보 보기");
    button.type = "button";
    button.addEventListener("click", () => openDetail(entry.source_id));
    card.append(heading, summary, state, similarity, button);
    return card;
  }

  function renderGraphEntry(entry) {
    const card = node(document, "article", "item-bank-card");
    const source = entry.source_class === "PAST_EXAM" ? "기출" : "창작·승인 문항";
    const display = /^itemrev_[0-9a-f]{32}$/.test(entry.source_display_label)
      ? "승인 문항" : entry.source_display_label;
    const heading = node(document, "h3", "", `${source} · ${display}`);
    const units = node(document, "p", "", entry.curriculum_units
      .map((unit) => `${unit.unit_code} ${unit.label}`).join(" · "));
    const state = node(document, "p", "", entry.item_revision_state === "APPROVED"
      ? "승인 완료 · Graph에 등록됨" : "고정된 이전 승인 버전 · Graph에 등록됨");
    const button = node(document, "button", "button secondary", "문항 보기");
    button.type = "button";
    button.addEventListener("click", () => openRegisteredItem(entry));
    card.append(heading, units, state, button);
    return card;
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
    const request = ++sequence;
    const source = selectedSource();
    let parameters;
    try {
      parameters = source === "EXTERNAL_SOURCE" ? filters()
        : {source_class: source, curriculum_unit_key: $("#item-db-graph-unit").value};
    } catch (error) {
      message(error.message, true);
      return;
    }
    const key = JSON.stringify(parameters);
    if (reset || key !== query) {
      query = key;
      cursor = null;
      $("#item-db-results").replaceChildren();
      $("#item-db-detail-panel").hidden = true;
    }
    parameters.cursor = cursor;
    const more = $("#item-db-more");
    more.disabled = true;
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
      if (!root.children.length) root.append(node(document, "p", "empty-state", "조건에 맞는 문항이 없습니다."));
      cursor = page.next_cursor;
      more.hidden = !page.has_more;
      message(`${page.values.length}개 문항을 불러왔습니다.${source === "EXTERNAL_SOURCE" ? " 이 원본들은 Graph 게시 전입니다." : " Graph의 승인 근거로 검색했습니다."}`);
      loaded = true;
    } catch (error) {
      if (request === sequence) message(`문항 조회 실패: ${error.message || "잠시 후 다시 시도해 주세요."}`, true);
    } finally {
      if (request === sequence) more.disabled = false;
    }
  }

  async function openDetail(sourceId) {
    const request = ++sequence;
    const panel = $("#item-db-detail-panel");
    const root = $("#item-db-detail");
    panel.hidden = false;
    root.replaceChildren(node(document, "p", "empty-state", "문항 정보를 불러오는 중입니다."));
    try {
      const detail = await api(`/item-db/external-sources/${encodeURIComponent(sourceId)}`);
      if (request !== sequence || detail.entry.source_id !== sourceId) return;
      root.replaceChildren();
      root.append(node(document, "h3", "", `고유번호 ${detail.entry.external_number}`));
      root.append(node(document, "p", "", MATCH_LABELS[detail.entry.match_status] || "확인 필요"));
      const editions = node(document, "div", "item-db-editions");
      editions.append(node(document, "h3", "", "교정본 파일"));
      for (const edition of detail.editions) {
        const line = node(document, "p", "");
        line.append(document.createTextNode(`${edition.edition}교 · `));
        if (edition.available && edition.filename) {
          const link = node(document, "a", "", edition.filename);
          link.href = `/studio/api/v1/item-db/external-sources/${encodeURIComponent(sourceId)}`
            + `/editions/${edition.edition}/download?source_revision_id=${encodeURIComponent(detail.entry.source_revision_id)}`;
          line.append(link);
        } else {
          line.append(document.createTextNode(edition.filename || "파일 확인 필요"));
        }
        line.append(document.createTextNode(` · ${MATCH_LABELS[edition.match_status] || "확인 필요"}`));
        editions.append(line);
      }
      root.append(editions);
      const metadata = node(document, "dl", "inspector-list item-db-metadata");
      for (const cell of detail.cells) {
        // The original U value is shown once in the heading; L/M/N are filenames above.
        if (["U", "L", "M", "N"].includes(cell.column)) continue;
        if (!cell.present && !cell.raw_text) continue;
        metadata.append(
          node(document, "dt", "", CELL_LABELS[cell.column] || cell.column),
          node(document, "dd", "", cell.raw_text || "비어 있음"),
        );
      }
      root.append(metadata);
    } catch (error) {
      if (request === sequence) root.replaceChildren(node(document, "p", "empty-state", `정보를 불러오지 못했습니다: ${error.message || "다시 시도해 주세요."}`));
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
      $("#item-db-source").addEventListener("change", () => {
        syncSourceControls();
        load(true);
      });
      $("#item-db-filter-add").addEventListener("click", addFilter);
      $("#item-db-form").addEventListener("submit", (event) => {
        event.preventDefault();
        load(true);
      });
      $("#item-db-more").addEventListener("click", () => load(false));
      $("#item-db-export").addEventListener("click", exportRows);
      $("#item-db-detail-close").addEventListener("click", () => {
        $("#item-db-detail-panel").hidden = true;
      });
    },
    open() {
      const changed = syncSourceAccess();
      if (changed || !loaded) load(true);
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
