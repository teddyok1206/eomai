// Reversible display state only. The existing commit owner retains mutation/replay keys.
export function createContentPlanningLifecycle({document, api, can, commit, openEdition, onStateChange = () => {}, confirm = text => globalThis.confirm(text)}) {
  const $ = selector => document.querySelector(selector), entries = new Map();
  let owner = null, ownerEpoch = 0, active = false, disabled = false, productId = null, editionId = null;
  let current = null, currentEpoch = 0, listEpoch = 0, reading = false, listing = false;
  let rows = [], cursor = null, listProduct = null, listProductTitle = "";
  const key = target => `${target.target_kind}:${target.target_id}`;
  const node = (tag, text, className = "") => {const n = document.createElement(tag); if (text !== undefined) n.textContent = text; n.className = className; return n;};
  const query = body => api("/content-planning/lifecycle/query", {method: "POST", mutation: true, body});
  function message(text, error = false) {const n = $("#excel-lifecycle-message"); n.textContent = text; n.className = `form-message${error ? " error" : ""}`;}
  function target() {
    const kind = $("#excel-lifecycle-target").value, id = kind === "CONTENT" ? productId : editionId;
    return id ? {target_kind: kind, target_id: id} : null;
  }
  function stateText(entry) {return `${entry.title} · ${entry.lifecycle_state === "ARCHIVED" ? "보관 중" : "사용 중"}${entry.parent_archived ? " · 상위 콘텐츠 보관 중" : ""}`;}
  function actionButton(text, action, blocked = false) {const b = node("button", text, "button quiet"); b.type = "button"; b.disabled = blocked; b.addEventListener("click", action); return b;}
  function render() {
    const blocked = disabled || reading || listing;
    $("#excel-lifecycle-read").disabled = !owner || !target() || blocked;
    $("#excel-lifecycle-target").disabled = blocked;
    $("#excel-lifecycle-status").textContent = reading ? "상태를 확인하고 있습니다…" : current ? stateText(current) : "현재 콘텐츠나 판의 상태를 확인해 주세요.";
    $("#excel-lifecycle-change").textContent = current?.lifecycle_state === "ARCHIVED" ? "다시 사용하기" : "보관하기";
    $("#excel-lifecycle-change").disabled = blocked || !current || !can("deliverable:update") || (current.parent_archived && current.lifecycle_state === "ARCHIVED");
    $("#excel-lifecycle-reason").disabled = blocked || !can("deliverable:update");
    $("#excel-lifecycle-list").disabled = !owner || blocked;
    $("#excel-lifecycle-list-kind").disabled = blocked;
    $("#excel-lifecycle-more").hidden = cursor === null;
    $("#excel-lifecycle-more").disabled = blocked;
    $("#excel-lifecycle-list-title").textContent = listing ? "보관 목록을 확인하고 있습니다…" : listProductTitle;
    const list = $("#excel-lifecycle-rows"); list.replaceChildren();
    for (const entry of rows) {
      const row = node("div", undefined, "excel-record"), actions = node("div", undefined, "excel-toolbar");
      row.append(node("p", stateText(entry)));
      if (entry.target.target_kind === "CONTENT") actions.append(actionButton("판 보기", () => listEditions(entry), blocked));
      else if (entry.current_revision_id) actions.append(actionButton("편성 열기", () => openEdition(entry), blocked));
      if (entry.lifecycle_state === "ARCHIVED" && can("deliverable:update")) actions.append(actionButton("복원하기", () => change(entry), blocked || entry.parent_archived));
      row.append(actions); list.append(row);
    }
  }
  async function readTarget(selected) {
    if (!owner || !active || !selected || disabled || reading) return;
    const epoch = ++currentEpoch, actor = ownerEpoch; reading = true; render();
    try {
      const result = await query({action_kind: "READ_LIFECYCLE", target: selected});
      if (epoch !== currentEpoch || actor !== ownerEpoch || !active) return;
      entries.set(key(result.entry.target), result.entry);
      rows = rows.map(row => key(row.target) === key(result.entry.target) ? result.entry : row);
      if (target() && key(selected) === key(target())) {
        current = result.entry;
        const history = $("#excel-lifecycle-events"); history.replaceChildren();
        for (const event of result.events) history.append(node("p", `${new Date(event.created_at).toLocaleString("ko-KR", {timeZone: "Asia/Seoul"})} · ${event.reason}`));
      }
      message(""); onStateChange();
    } catch (error) {if (epoch === currentEpoch && actor === ownerEpoch && active) message(`보관 상태 조회 실패: ${error.message}`, true);}
    finally {if (epoch === currentEpoch && actor === ownerEpoch) {reading = false; render();}}
  }
  const readCurrent = () => readTarget(target());
  async function listArchived(append = false) {
    if (!owner || !active || disabled || listing) return;
    const kind = $("#excel-lifecycle-list-kind").value;
    const parent = kind === "EDITION" ? listProduct || productId : null;
    if (kind === "EDITION" && !parent) {message("판을 조회할 콘텐츠를 먼저 선택해 주세요.", true); return;}
    const epoch = ++listEpoch, actor = ownerEpoch; listing = true; render();
    try {
      const result = await query({action_kind: "LIST_LIFECYCLE", target_kind: kind,
        deliverable_id: parent, lifecycle_state: listProduct && kind === "EDITION" ? "ALL" : "ARCHIVED",
        after_id: append ? cursor : null, limit: 50});
      if (epoch !== listEpoch || actor !== ownerEpoch || !active) return;
      rows = append ? [...rows, ...result.rows] : result.rows; cursor = result.next_id;
      for (const entry of result.rows) entries.set(key(entry.target), entry);
      message(rows.length ? "" : "해당 보관 목록이 없습니다."); onStateChange();
    } catch (error) {if (epoch === listEpoch && actor === ownerEpoch && active) message(`보관 목록 조회 실패: ${error.message}`, true);}
    finally {if (epoch === listEpoch && actor === ownerEpoch) {listing = false; render();}}
  }
  function listEditions(entry) {
    listProduct = entry.deliverable_id; listProductTitle = `${entry.title}의 판`;
    $("#excel-lifecycle-list-kind").value = "EDITION"; cursor = null; listArchived();
  }
  async function change(entry) {
    if (!owner || !active || disabled || reading || listing || !can("deliverable:update")) return;
    const reason = $("#excel-lifecycle-reason").value.trim();
    if (!reason) {message("보관하거나 복원하는 이유를 적어 주세요.", true); $("#excel-lifecycle-reason").focus(); return;}
    if (entry.parent_archived && entry.lifecycle_state === "ARCHIVED") {message("상위 콘텐츠를 먼저 복원해 주세요.", true); return;}
    const desired = entry.lifecycle_state === "ARCHIVED" ? "ACTIVE" : "ARCHIVED";
    if (!confirm(`${entry.title}을(를) ${desired === "ACTIVE" ? "다시 사용" : "보관"}할까요? 문항과 사용·인쇄 이력은 지워지지 않습니다.`)) return;
    await commit({action_kind: "CHANGE_LIFECYCLE", target: entry.target, expected_state: entry.lifecycle_state,
      expected_version: entry.version, desired_state: desired, reason}, "lifecycle");
  }
  return {
    updateContext(value) {
      const ownerChanged = value.owner !== owner;
      if (ownerChanged) {
        owner = value.owner; ownerEpoch++; currentEpoch++; listEpoch++; entries.clear(); current = null;
        rows = []; cursor = null; listProduct = null; listProductTitle = ""; reading = false; listing = false;
        $("#excel-lifecycle-reason").value = ""; $("#excel-lifecycle-events").replaceChildren(); message("");
      }
      if (ownerChanged || productId !== value.deliverableId || editionId !== value.editionId) {
        currentEpoch++; current = null; reading = false; $("#excel-lifecycle-events").replaceChildren();
      }
      productId = value.deliverableId; editionId = value.editionId; disabled = value.disabled;
      render();
    },
    open() {active = true; if ($("#excel-lifecycle-panel").open && target() && !current) readCurrent();},
    close() {active = false; currentEpoch++; listEpoch++; reading = false; listing = false;},
    refreshCurrent: readCurrent,
    refreshTarget: readTarget,
    selectionArchived() {
      const content = productId ? entries.get(`CONTENT:${productId}`) : null;
      const edition = editionId ? entries.get(`EDITION:${editionId}`) : null;
      return content?.lifecycle_state === "ARCHIVED" || edition?.lifecycle_state === "ARCHIVED" || edition?.parent_archived === true;
    },
    acceptResult(result) {
      const entry = result.entry; entries.set(key(entry.target), entry);
      if (entry.target.target_kind === "CONTENT") {
        for (const [id, existing] of entries) if (existing.target.target_kind === "EDITION" && existing.deliverable_id === entry.deliverable_id) entries.set(id, {...existing, parent_archived: entry.lifecycle_state === "ARCHIVED"});
      }
      if (current && key(current.target) === key(entry.target)) current = entry;
      rows = rows.map(row => entries.get(key(row.target)) || row);
      if (entry.lifecycle_state === "ACTIVE" && !listProduct) rows = rows.filter(row => key(row.target) !== key(entry.target));
      message(entry.lifecycle_state === "ARCHIVED" ? "보관했습니다. 사용·인쇄 이력은 유지됩니다." : "다시 사용할 수 있습니다.");
      render(); onStateChange();
    },
    install() {
      $("#excel-lifecycle-panel").addEventListener("toggle", () => {if ($("#excel-lifecycle-panel").open) readCurrent();});
      $("#excel-lifecycle-target").addEventListener("change", () => {currentEpoch++; current = null; reading = false; readCurrent(); render();});
      $("#excel-lifecycle-read").addEventListener("click", readCurrent);
      $("#excel-lifecycle-change").addEventListener("click", () => {if (current) change(current);});
      $("#excel-lifecycle-list").addEventListener("click", () => listArchived());
      $("#excel-lifecycle-more").addEventListener("click", () => listArchived(true));
      $("#excel-lifecycle-list-kind").addEventListener("change", () => {listEpoch++; listing = false; listProduct = null; listProductTitle = ""; cursor = null; rows = []; listArchived();});
    },
  };
}
