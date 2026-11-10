import {createItemDbDraft} from "./item-db-draft.js";
import {createCuratedDeliveryControl} from "./item-db-delivery.js";
import {createPlanningDraft} from "./content-planning-draft.js";

function node(document, tag, className, value) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (value !== undefined) element.textContent = value;
  return element;
}

// Transient selection and quick delivery. Excel owns the saved-output library;
// Catalog retains all persistence, permission, and idempotency rules.
export function createItemDbAssembly({document, api, activate, message, canPrint = () => false, canPlan = () => false, planningSelectionHint = () => null, onPlanningSelections = () => false}) {
  const $ = (selector) => document.querySelector(selector);
  let owner = null;
  let pendingSave = null;
  let replacementTarget = null;
  let ownerGeneration = 0;
  let draftSequence = 0;
  let saving = false;
  let planning = false;
  let output = null;
  const draft = createItemDbDraft();
  // A DB selection is not a saved private assembly. Reuse Excel's occurrence
  // model without changing the historical private draft's 200/unique contract.
  const collector = createPlanningDraft(), labels = new Map();
  const collectorSection = "db-selection";
  const pageSize = 100;
  let excelMode = false, pageIndex = 0, selectionTools = null;
  collector.load(collectorSection, []);

  function entries() {
    return excelMode ? collector.rows(collectorSection).map(row => ({
      placementId: row.placement_id, pointer: row.target, label: labels.get(row.placement_id),
    })) : draft.entries();
  }

  function refreshMode() {
    const next = Boolean(owner && planningSelectionHint());
    if (next === excelMode) {renderDraft(); return;}
    excelMode = next;
    pageIndex = 0;
    cancelReplacement();
    renderDraft();
  }

  function appendSelections(selections) {
    const ids = collector.addMany(collectorSection, selections.map(selection => selection.pointer));
    ids.forEach((id, index) => labels.set(id, selections[index].label));
  }

  function resetCollector() {
    collector.reset(); collector.load(collectorSection, []); labels.clear(); pageIndex = 0;
  }

  function syncPlanningControl(count) {
    $("#item-db-draft-to-excel").hidden = !canPlan();
    $("#item-db-draft-to-excel").disabled = saving || planning || count === 0 || !canPlan();
  }

  function renderDraft() {
    draftSequence += 1;
    const root = $("#item-db-draft-list");
    root.replaceChildren();
    const values = entries(), mode = excelMode, generation = ownerGeneration;
    const current = () => generation === ownerGeneration && mode === excelMode
      && mode === Boolean(owner && planningSelectionHint()) && !saving && !planning;
    $("#item-db-draft-title").textContent = excelMode ? "Excel에 담을 문항" : "간편 출력 목록";
    $("#item-db-draft-count").textContent = `${values.length}개`;
    $("#item-db-tab-count").textContent = String(values.length);
    const create = $("#item-db-quick-create");
    create.hidden = excelMode;
    create.disabled = excelMode || saving || planning || !owner || values.length === 0 || !canPrint();
    create.textContent = saving ? "출력 준비 중…" : "한글 파일 만들기";
    $("#item-db-quick-result").hidden = excelMode || !output;
    syncPlanningControl(values.length);
    $("#item-db-draft-empty").hidden = values.length > 0;
    const pageCount = Math.max(1, Math.ceil(values.length / pageSize));
    pageIndex = Math.min(pageIndex, pageCount - 1);
    if (selectionTools) {
      selectionTools.root.hidden = !excelMode;
      selectionTools.previous.disabled = pageIndex === 0;
      selectionTools.next.disabled = pageIndex + 1 >= pageCount;
      selectionTools.page.textContent = `${pageIndex + 1} / ${pageCount}쪽`;
      selectionTools.importDraft.disabled = !draft.entries().length || saving || planning;
    }
    const offset = excelMode ? pageIndex * pageSize : 0;
    const visible = excelMode ? values.slice(offset, offset + pageSize) : values;
    visible.forEach((selection, localIndex) => {
      const index = offset + localIndex;
      const line = node(document, "tr", "");
      const number = node(document, "th", "", `${index + 1}번`);
      number.scope = "row";
      const item = node(document, "td", "");
      item.append(node(document, "div", "item-db-draft-card", selection.label));
      const actionCell = node(document, "td", "");
      const actions = node(document, "div", "item-db-draft-actions");
      actions.setAttribute("role", "group");
      actions.setAttribute("aria-label", `${index + 1}번 문항 편집`);
      for (const [caption, next] of [
        ["위로", index - 1], ["아래로", index + 1],
      ]) {
        const button = node(document, "button", "button quiet", caption);
        button.type = "button";
        button.disabled = saving || planning || next < 0 || next >= values.length;
        button.addEventListener("click", () => {
          if (!current()) return;
          if (excelMode) collector.move(collectorSection, selection.placementId, collectorSection, next);
          else draft.move(index, next);
          renderDraft();
        });
        actions.append(button);
      }
      const remove = node(document, "button", "button quiet", "빼기");
      remove.type = "button"; remove.disabled = saving || planning;
      remove.addEventListener("click", () => {
        if (!current()) return;
        if ((excelMode ? selection.placementId : selection.pointer) === replacementTarget) cancelReplacement();
        if (excelMode) {collector.remove(collectorSection, selection.placementId); labels.delete(selection.placementId);}
        else draft.remove(index);
        renderDraft();
      });
      const replace = node(document, "button", "button quiet", "교체");
      replace.type = "button"; replace.disabled = saving || planning;
      replace.addEventListener("click", () => {
        if (!current()) return;
        replacementTarget = excelMode ? selection.placementId : selection.pointer;
        $("#item-db-replacement-label").textContent = `${index + 1}번 문항 교체: 조회에서 바꿀 문항을 골라 ‘목록에 담기’를 누르세요.`;
        $("#item-db-replacement").hidden = false;
        activate("search");
        $("#item-db-search-tab").focus();
      });
      actions.append(remove, replace);
      actionCell.append(actions);
      line.append(number, item, actionCell);
      root.append(line);
    });
  }

  function cancelReplacement() {
    replacementTarget = null;
    $("#item-db-replacement").hidden = true;
    $("#item-db-replacement-label").textContent = "";
  }

  function addToDraft(pointer, label) {
    if (!owner || saving || planning) return;
    refreshMode();
    const replacing = replacementTarget !== null;
    if (excelMode) {
      try {
        if (replacing) {
          collector.update(collectorSection, replacementTarget, {target: pointer});
          labels.set(replacementTarget, label);
        } else appendSelections([{pointer, label}]);
      } catch (error) {message(error.message, true); return;}
      if (replacing) cancelReplacement();
      renderDraft();
      if (replacing) activate("assembly");
      message(replacing ? "선택한 자리의 문항을 교체했습니다." : "Excel에 담을 목록에 추가했습니다. 같은 문항도 여러 자리에 배치할 수 있습니다.");
      return;
    }
    const result = replacing ? draft.replaceOne(replacementTarget, pointer, label) : draft.add(pointer, label);
    if (result === "DUPLICATE") {
      message("이미 목록에 담긴 문항입니다.");
      return;
    }
    if (result === "FULL") {
      message("간편 출력은 최대 200문항입니다. 더 많은 문항은 Excel에서 선택해 주세요.", true);
      return;
    }
    if (result === "MISSING") {
      cancelReplacement();
      message("교체할 문항이 목록에서 빠졌습니다. 다시 선택해 주세요.", true);
      return;
    }
    if (replacing) cancelReplacement();
    renderDraft();
    if (replacing) activate("assembly");
    message(replacing ? "선택한 문항을 교체했습니다." : "목록에 담았습니다. 간편 출력하거나 Excel에 배치할 수 있습니다.");
  }

  async function quickOutput() {
    if (saving || planning || !owner || !canPrint()) return;
    refreshMode();
    if (excelMode) return;
    const proposal = draft.proposal();
    if (!proposal.placements.length) return;
    const body = {...proposal, schema_version: "curated-document-assembly-draft/2.0",
      title: `간편 출력 · ${proposal.placements.length}문항`};
    const signature = JSON.stringify(body);
    if (!pendingSave || pendingSave.signature !== signature) {
      pendingSave = {signature, body, key: `studio:curated-assembly:${crypto.randomUUID()}`, receipt: null};
    }
    const operation = pendingSave, generation = ownerGeneration;
    saving = true; renderDraft(); message("선택한 문항으로 한글 파일을 준비하고 있습니다.");
    try {
      if (!operation.receipt) {
        const receipt = await api("/item-db/assemblies", {method: "POST", mutation: true,
          body: operation.body, headers: {"Idempotency-Key": operation.key}});
        if (generation !== ownerGeneration) return;
        if (!/^assembly_[0-9a-f]{32}$/.test(receipt.assembly_id)
          || !/^assemblyrev_[0-9a-f]{32}$/.test(receipt.assembly_revision_id)
          || !/^sha256:[0-9a-f]{64}$/.test(receipt.manifest_sha256)
          || receipt.state !== "INPUT_PINNED"
          || receipt.placement_count !== body.placements.length) {
          throw new Error("출력할 문항 목록을 확인하지 못했습니다. 같은 버튼으로 다시 확인해 주세요.");
        }
        operation.receipt = receipt;
      }
      if (generation !== ownerGeneration || Boolean(planningSelectionHint())) return;
      if (output?.operation !== operation) {
        output?.control.dispose();
        const control = createCuratedDeliveryControl({document, api, entry: operation.receipt, canCreate: canPrint()});
        output = {operation, control};
        $("#item-db-quick-result").replaceChildren(
          node(document, "strong", "", operation.body.title), control.element);
      }
      $("#item-db-quick-result").hidden = false;
      // One user action, two existing idempotent boundaries. Repeated clicks reuse
      // the saved receipt and latest/build reads instead of generating new jobs.
      await output.control.start();
      if (generation === ownerGeneration && !Boolean(planningSelectionHint())) {
        message("아래에서 제작 상태와 다운로드를 확인하세요. 이전 출력은 Excel에서 다시 열 수 있습니다.");
      }
    } catch (error) {
      if (generation === ownerGeneration) message(`간편 출력 준비 실패: ${error.message || "같은 버튼으로 다시 확인해 주세요."}`, true);
    } finally {
      if (generation === ownerGeneration) {saving = false; refreshMode();}
    }
  }

  return Object.freeze({
    add: addToDraft,
    install() {
      const root = node(document, "div", "form-actions");
      root.id = "item-db-excel-selection-tools";
      const previous = node(document, "button", "button quiet", "이전 100개");
      const next = node(document, "button", "button quiet", "다음 100개");
      const page = node(document, "span", "", "");
      const importDraft = node(document, "button", "button secondary", "간편 출력 목록 가져오기");
      for (const button of [previous, next, importDraft]) button.type = "button";
      previous.addEventListener("click", () => {if (excelMode && pageIndex > 0) {pageIndex -= 1; renderDraft();}});
      next.addEventListener("click", () => {if (excelMode) {pageIndex += 1; renderDraft();}});
      importDraft.addEventListener("click", () => {
        refreshMode();
        if (!excelMode || saving || planning || !draft.entries().length) return;
        try {appendSelections(draft.entries()); renderDraft();}
        catch (error) {message(error.message, true);}
      });
      root.append(previous, page, next, importDraft);
      $("#item-db-draft-to-excel").before(root);
      selectionTools = {root, previous, next, page, importDraft};
      renderDraft();
      $("#item-db-quick-create").addEventListener("click", quickOutput);
      $("#item-db-draft-to-excel").addEventListener("click", async () => {
        if (saving || planning || !owner || !canPlan()) return;
        refreshMode();
        const values = entries();
        if (!values.length) return;
        const generation = ownerGeneration, mode = excelMode;
        planning = true; renderDraft(); const request = draftSequence;
        const current = () => generation === ownerGeneration && mode === excelMode && request === draftSequence && canPlan();
        try {
          const accepted = await onPlanningSelections(values, current);
          if (!current() || !accepted) return;
          if (mode) resetCollector();
          refreshMode();
        } catch (error) {if (current()) message(`Excel 배치 준비 실패: ${error.message || "다시 시도해 주세요."}`, true);}
        finally {if (generation === ownerGeneration) {planning = false; renderDraft();}}
      });
      $("#item-db-replacement-cancel").addEventListener("click", cancelReplacement);
    },
    setOwner(value) {
      if (owner === value) return false;
      owner = value;
      ownerGeneration += 1;
      pendingSave = null;
      saving = false;
      planning = false;
      cancelReplacement();
      output?.control.dispose(); output = null;
      $("#item-db-quick-result").replaceChildren();
      draft.replace([]);
      resetCollector();
      excelMode = Boolean(owner && planningSelectionHint());
      renderDraft();
      return true;
    },
    open: refreshMode,
    refreshMode,
    refresh: refreshMode,
  });
}
