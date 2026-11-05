import {createItemDbDraft} from "./item-db-draft.js";
import {createCuratedDeliveryControl} from "./item-db-delivery.js";

function node(document, tag, className, value) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (value !== undefined) element.textContent = value;
  return element;
}

// Own only draft/list/delivery presentation. The Catalog retains all save/delete rules.
export function createItemDbAssembly({document, api, activate, message}) {
  const $ = (selector) => document.querySelector(selector);
  let owner = null;
  let savedCursor = null;
  let savedSequence = 0;
  let pendingSave = null;
  let replacementTarget = null;
  let loaded = false;
  let ownerGeneration = 0;
  let draftSequence = 0;
  let saving = false;
  const deliveries = new Set();
  const pendingRemovals = new Map();
  const draft = createItemDbDraft();

  function renderDraft() {
    draftSequence += 1;
    const root = $("#item-db-draft-list");
    root.replaceChildren();
    const entries = draft.entries();
    $("#item-db-draft-count").textContent = `${entries.length}개`;
    $("#item-db-tab-count").textContent = String(entries.length);
    $("#item-db-draft-save").disabled = saving || entries.length === 0;
    $("#item-db-draft-empty").hidden = entries.length > 0;
    entries.forEach((selection, index) => {
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
        if (selection.pointer === replacementTarget) cancelReplacement();
        draft.remove(index);
        renderDraft();
      });
      const replace = node(document, "button", "button quiet", "교체");
      replace.type = "button";
      replace.addEventListener("click", () => {
        replacementTarget = selection.pointer;
        $("#item-db-replacement-label").textContent = `${index + 1}번 문항 교체: 조회에서 바꿀 문항을 골라 ‘조립 목록에 담기’를 누르세요.`;
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
    const replacing = replacementTarget !== null;
    const result = replacing ? draft.replaceOne(replacementTarget, pointer, label) : draft.add(pointer, label);
    if (result === "DUPLICATE") {
      message("이미 조립 목록에 담긴 문항입니다.");
      return;
    }
    if (result === "FULL") {
      message("조립 초안에는 문항을 최대 200개까지 담을 수 있습니다.", true);
      return;
    }
    if (result === "MISSING") {
      cancelReplacement();
      message("교체할 문항이 초안에서 빠졌습니다. 배치에서 다시 선택해 주세요.", true);
      return;
    }
    if (replacing) cancelReplacement();
    renderDraft();
    if (replacing) activate("assembly");
    message(replacing ? "선택한 위치의 문항을 교체했습니다. 순서를 저장해 주세요." : "조립 순서 초안에 담았습니다. 아직 HWPX를 만들지는 않았습니다.");
  }

  async function saveDraft() {
    if (saving || !owner) return;
    const button = $("#item-db-draft-save");
    const name = $("#item-db-assembly-name");
    if (!name.reportValidity()) return;
    name.value = name.value.trim();
    const proposal = {...draft.proposal(), schema_version: "curated-document-assembly-draft/2.0", title: name.value};
    if (!proposal.placements.length) return;
    const signature = JSON.stringify(proposal);
    if (!pendingSave || pendingSave.signature !== signature) {
      pendingSave = {signature, key: `studio:curated-assembly:${crypto.randomUUID()}`};
    }
    const operation = pendingSave;
    const generation = ownerGeneration;
    saving = true;
    button.disabled = true;
    message("조립 순서를 저장하고 있습니다.");
    try {
      const receipt = await api("/item-db/assemblies", {
        method: "POST", mutation: true, body: proposal,
        headers: {"Idempotency-Key": operation.key},
      });
      if (generation !== ownerGeneration) return;
      if (!/^assembly_[0-9a-f]{32}$/.test(receipt.assembly_id)
        || receipt.placement_count !== proposal.placements.length) {
        throw new Error("저장 결과를 확인하지 못했습니다.");
      }
      operation.assemblyId = receipt.assembly_id;
      message("조립 순서를 저장했습니다. 아래 목록에서 다시 열 수 있습니다.");
      await loadSaved(true);
    } catch (error) {
      if (generation === ownerGeneration) message(`조립 순서 저장 실패: ${error.message || "다시 시도해 주세요."}`, true);
    } finally {
      if (generation === ownerGeneration) {
        saving = false;
        button.disabled = draft.entries().length === 0;
      }
    }
  }

  function savedLabel(placement) {
    if (placement.placement_kind === "EXTERNAL_SOURCE_DOCUMENT") {
      return `창작 원본 ${placement.external_number} · ${placement.edition}교 · ${placement.source_format}`;
    }
    return placement.placement_kind === "PAST_EXAM_ITEM_REVISION"
      ? "기출 문항" : "등록 문항";
  }

  async function openSaved(entry) {
    const assemblyId = entry.assembly_id;
    const request = ++draftSequence;
    message("저장한 조립 순서를 불러오는 중입니다.");
    try {
      const saved = await api(`/item-db/assemblies/${encodeURIComponent(assemblyId)}`);
      if (request !== draftSequence) return;
      if (saved.assembly_id !== assemblyId || saved.assembly_revision_id !== entry.assembly_revision_id
        || saved.manifest_sha256 !== entry.manifest_sha256 || !Array.isArray(saved.placements)) {
        throw new Error("저장본이 올바르지 않습니다.");
      }
      const selections = saved.placements.map((placement) => {
        const {external_number, ...pointer} = placement;
        return {pointer, label: savedLabel(placement)};
      });
      if (!draft.replace(selections)) throw new Error("저장된 순서를 불러올 수 없습니다.");
      cancelReplacement();
      $("#item-db-assembly-name").value = entry.title || "";
      pendingSave = null;
      renderDraft();
      message("저장한 조립 순서를 다시 열었습니다. 바꾼 뒤 저장하면 별도 저장본이 됩니다.");
      $("#item-db-draft-title").scrollIntoView({block: "start"});
    } catch (error) {
      if (request === draftSequence) message(`저장본 열기 실패: ${error.message || "다시 시도해 주세요."}`, true);
    }
  }

  async function removeSaved(entry) {
    const selection = {assembly_revision_id: entry.assembly_revision_id, manifest_sha256: entry.manifest_sha256};
    const signature = JSON.stringify(selection);
    let operation = pendingRemovals.get(entry.assembly_id);
    if (operation?.busy) return;
    if (operation && operation.signature !== signature) {
      message("저장본의 버전이 바뀌었습니다. 목록을 새로고침해 주세요.", true);
      return;
    }
    if (!globalThis.confirm(`‘${entry.title || "제목 없는 조립"}’을 목록에서 삭제할까요?\n원본 문항과 이미 만든 HWPX 파일은 그대로 보존됩니다.`)) return;
    if (!operation) {
      operation = {signature, key: `studio:curated-remove:${crypto.randomUUID()}`, busy: false};
      pendingRemovals.set(entry.assembly_id, operation);
    }
    const generation = ownerGeneration;
    operation.busy = true;
    message("저장한 조립 순서를 목록에서 삭제하고 있습니다.");
    try {
      const receipt = await api(`/item-db/assemblies/${encodeURIComponent(entry.assembly_id)}/remove`, {
        method: "POST", mutation: true, body: selection,
        headers: {"Idempotency-Key": operation.key},
      });
      if (generation !== ownerGeneration) return;
      if (receipt.assembly_id !== entry.assembly_id || receipt.assembly_revision_id !== entry.assembly_revision_id
        || receipt.manifest_sha256 !== entry.manifest_sha256 || !Number.isFinite(Date.parse(receipt.removed_at))) {
        throw new Error("삭제 결과를 확인하지 못했습니다. 같은 요청으로 다시 확인해 주세요.");
      }
      if (pendingSave?.assemblyId === entry.assembly_id) pendingSave = null;
      await loadSaved(true);
      if (generation === ownerGeneration) message("목록에서 삭제했습니다. 원본 문항과 기존 파일은 유지됩니다.");
    } catch (error) {
      if (generation === ownerGeneration) message(`목록 삭제 실패: ${error.message || "같은 요청으로 다시 시도해 주세요."}`, true);
    } finally {
      operation.busy = false;
    }
  }

  async function loadSaved(reset = false) {
    const request = ++savedSequence;
    if (reset) {
      savedCursor = null;
      for (const delivery of deliveries) delivery.dispose();
      deliveries.clear();
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
        const label = node(document, "div", "item-db-saved-summary");
        label.append(node(document, "strong", "item-db-saved-title", entry.title || "제목 없는 조립"),
          node(document, "span", "", `${time} · ${entry.placement_count}문항`));
        const open = node(document, "button", "button secondary", "다시 열기");
        open.type = "button";
        open.addEventListener("click", () => openSaved(entry));
        const remove = node(document, "button", "button quiet", "삭제");
        remove.type = "button";
        remove.setAttribute("aria-label", `${entry.title || "제목 없는 조립"} 목록에서 삭제`);
        remove.addEventListener("click", () => removeSaved(entry));
        const delivery = createCuratedDeliveryControl({document, api, entry});
        deliveries.add(delivery);
        line.append(label, open, remove, delivery.element);
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

  return Object.freeze({
    add: addToDraft,
    install() {
      renderDraft();
      $("#item-db-draft-save").addEventListener("click", saveDraft);
      $("#item-db-assembly-name").addEventListener("input", () => {draftSequence += 1;});
      $("#item-db-replacement-cancel").addEventListener("click", cancelReplacement);
      $("#item-db-saved-refresh").addEventListener("click", () => loadSaved(true));
      $("#item-db-saved-more").addEventListener("click", () => loadSaved(false));
    },
    setOwner(value) {
      if (owner === value) return false;
      owner = value;
      ownerGeneration += 1;
      savedSequence += 1;
      loaded = false;
      savedCursor = null;
      pendingSave = null;
      saving = false;
      pendingRemovals.clear();
      $("#item-db-assembly-name").value = "";
      cancelReplacement();
      for (const delivery of deliveries) delivery.dispose();
      deliveries.clear();
      draft.replace([]);
      renderDraft();
      $("#item-db-saved-list").replaceChildren();
      return true;
    },
    open() {
      if (!loaded && owner) {
        loaded = true;
        loadSaved(true);
      }
    },
    refresh: () => loadSaved(true),
  });
}
