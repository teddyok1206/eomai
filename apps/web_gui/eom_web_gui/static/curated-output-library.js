import {createCuratedDeliveryControl} from "./item-db-delivery.js";

// Private output history remains private; importing only prepares an Excel draft.
export function createCuratedOutputLibrary({document, api, can, placeSelections,
  confirm = text => globalThis.confirm(text)}) {
  const $ = selector => document.querySelector(selector);
  const panel = $("#excel-output-library"), list = $("#excel-output-list");
  const more = $("#excel-output-more"), refresh = $("#excel-output-refresh");
  const controls = new Set(), removals = new Map(), entries = new Map();
  let owner = null, ownerEpoch = 0, active = false, cursor = null, sequence = 0;
  let loading = false, importing = false, importSequence = 0;
  let removalPending = null;
  const readable = () => Boolean(owner && can("item:read"));
  const current = epoch => epoch === ownerEpoch && active && panel.open && readable();
  const node = (tag, text, className = "") => {
    const value = document.createElement(tag); value.className = className;
    if (text !== undefined) value.textContent = text;
    return value;
  };
  function message(text, error = false) {
    const value = $("#excel-output-message"); value.textContent = text;
    value.className = `form-message${error ? " error" : ""}`;
  }
  function dispose() {for (const control of controls) control.dispose(); controls.clear();}
  function sync() {
    panel.hidden = !readable();
    refresh.disabled = loading || importing || removalPending !== null || !readable();
    more.disabled = refresh.disabled;
    more.hidden = cursor === null;
    for (const button of list.querySelectorAll("[data-library-action]")) {
      button.disabled = loading || importing || removalPending !== null || !current(ownerEpoch) || (button.dataset.libraryAction === "import"
        ? !can("deliverable:read") || !can("deliverable:update")
        : !can("deliverable:create") || Boolean(removals.get(button.dataset.assemblyId)?.busy));
    }
  }
  function validEntry(entry) {
    return /^assembly_[0-9a-f]{32}$/.test(entry.assembly_id)
      && /^assemblyrev_[0-9a-f]{32}$/.test(entry.assembly_revision_id)
      && /^sha256:[0-9a-f]{64}$/.test(entry.manifest_sha256)
      && Number.isInteger(entry.placement_count) && entry.placement_count > 0
      && Number.isFinite(Date.parse(entry.created_at));
  }
  function placementLabel(placement) {
    if (placement.placement_kind === "EXTERNAL_SOURCE_DOCUMENT") {
      return `창작 원본 ${placement.external_number} · ${placement.edition}교 · ${placement.source_format}`;
    }
    return placement.placement_kind === "PAST_EXAM_ITEM_REVISION" ? "기출 문항" : "등록 문항";
  }
  async function importEntry(entry, epoch) {
    if (!current(epoch) || loading || importing || removalPending !== null || !can("deliverable:read") || !can("deliverable:update")) return;
    const request = ++importSequence;
    const isCurrent = () => current(epoch) && request === importSequence
      && can("deliverable:read") && can("deliverable:update");
    importing = true; sync(); message("저장된 문항과 순서를 확인하고 있습니다.");
    try {
      const saved = await api(`/item-db/assemblies/${encodeURIComponent(entry.assembly_id)}`);
      if (!isCurrent()) return;
      if (saved.assembly_id !== entry.assembly_id || saved.assembly_revision_id !== entry.assembly_revision_id
        || saved.manifest_sha256 !== entry.manifest_sha256 || !Array.isArray(saved.placements)
        || saved.placements.length !== entry.placement_count) throw new Error("선택한 저장본이 아닙니다. 목록을 다시 확인해 주세요.");
      const selections = saved.placements.map(placement => {
        const {external_number, ...pointer} = placement;
        return {pointer, label: placementLabel(placement)};
      });
      const accepted = await placeSelections(selections, isCurrent);
      if (isCurrent()) message(accepted ? "문항을 가져왔습니다. 배치 저장을 눌러 확정해 주세요." : "가져오기를 취소했습니다. 기존 배치는 유지됩니다.");
    } catch (error) {if (isCurrent()) message(`가져오기 실패: ${error.message}`, true);}
    finally {if (epoch === ownerEpoch && request === importSequence) {importing = false; sync();}}
  }
  async function removeEntry(entry, epoch) {
    if (!current(epoch) || loading || importing || removalPending !== null || !can("deliverable:create")) return;
    const body = {assembly_revision_id: entry.assembly_revision_id, manifest_sha256: entry.manifest_sha256};
    const signature = JSON.stringify(body);
    let operation = removals.get(entry.assembly_id);
    if (operation?.busy) return;
    if (operation && operation.signature !== signature) {message("저장본의 버전이 바뀌었습니다. 목록을 다시 확인해 주세요.", true); return;}
    if (!confirm(`‘${entry.title || "제목 없는 조립"}’을 목록에서 삭제할까요?\n원본 문항과 이미 만든 HWPX 파일은 그대로 보존됩니다.`) || !current(epoch)) return;
    if (!operation) {
      operation = {signature, key: `studio:curated-remove:${crypto.randomUUID()}`, busy: false};
      removals.set(entry.assembly_id, operation);
    }
    removalPending = operation; operation.busy = true; sync(); message("목록에서 삭제하고 있습니다.");
    try {
      const receipt = await api(`/item-db/assemblies/${encodeURIComponent(entry.assembly_id)}/remove`, {
        method: "POST", mutation: true, body, headers: {"Idempotency-Key": operation.key},
      });
      if (!current(epoch)) return;
      if (receipt.assembly_id !== entry.assembly_id || receipt.assembly_revision_id !== entry.assembly_revision_id
        || receipt.manifest_sha256 !== entry.manifest_sha256 || !Number.isFinite(Date.parse(receipt.removed_at))) {
        throw new Error("삭제 결과를 확인하지 못했습니다. 같은 요청으로 다시 확인해 주세요.");
      }
      // The confirmed receipt is authoritative even when the following read fails.
      entries.delete(entry.assembly_id); render();
      await load(true);
      if (current(epoch)) message("목록에서 삭제했습니다. 원본 문항과 기존 파일은 유지됩니다.");
    } catch (error) {if (current(epoch)) message(`목록 삭제 실패: ${error.message}`, true);}
    finally {
      operation.busy = false;
      if (removalPending === operation) removalPending = null;
      if (epoch === ownerEpoch) {
        sync();
        // Reopening during deletion can invalidate its list read; refresh the empty view once.
        if (current(epoch) && list.children.length === 0) await load(true);
      }
    }
  }
  function render() {
    dispose(); list.replaceChildren();
    const epoch = ownerEpoch;
    for (const entry of entries.values()) {
      const row = node("div", undefined, "item-db-draft-row");
      const summary = node("div", undefined, "item-db-saved-summary");
      const date = new Date(entry.created_at).toLocaleString("ko-KR", {timeZone: "Asia/Seoul", dateStyle: "medium", timeStyle: "short"});
      summary.append(node("strong", entry.title || "제목 없는 조립", "item-db-saved-title"), node("span", `${date} · ${entry.placement_count}문항`));
      const take = node("button", "Excel에 가져오기", "button secondary");
      take.type = "button"; take.dataset.libraryAction = "import"; take.dataset.assemblyId = entry.assembly_id;
      take.addEventListener("click", () => importEntry(entry, epoch));
      const remove = node("button", "목록에서 삭제", "button quiet");
      remove.type = "button"; remove.dataset.libraryAction = "remove"; remove.dataset.assemblyId = entry.assembly_id;
      remove.addEventListener("click", () => removeEntry(entry, epoch));
      const delivery = createCuratedDeliveryControl({document, api, entry, canCreate: can("hwpx:build_create")});
      controls.add(delivery); row.append(summary, take, remove, delivery.element); list.append(row);
    }
    if (!entries.size) list.append(node("p", "저장된 조립이나 간편 출력 기록이 없습니다.", "empty-state"));
    sync();
  }
  async function load(reset = false) {
    if (!current(ownerEpoch) || importing || loading) return;
    const epoch = ownerEpoch, request = ++sequence;
    loading = true; sync(); message("기록을 불러오는 중입니다.");
    try {
      const params = new URLSearchParams({limit: "20"});
      if (!reset && cursor) params.set("cursor", cursor);
      const page = await api(`/item-db/assemblies?${params}`);
      if (!current(epoch) || request !== sequence) return;
      if (!Array.isArray(page.values) || !page.values.every(validEntry)
        || !(page.next_cursor === null || typeof page.next_cursor === "string")) throw new Error("저장본 목록이 올바르지 않습니다.");
      if (reset) entries.clear();
      for (const entry of page.values) entries.set(entry.assembly_id, entry);
      cursor = page.next_cursor; render(); message("");
    } catch (error) {if (current(epoch) && request === sequence) message(`기록 조회 실패: ${error.message}`, true);}
    finally {if (epoch === ownerEpoch && request === sequence) {loading = false; sync();}}
  }
  function suspend() {
    sequence++; importSequence++; loading = false; importing = false;
    dispose(); entries.clear(); list.replaceChildren(); cursor = null; sync();
  }
  return Object.freeze({
    install() {
      panel.addEventListener("toggle", () => {if (panel.open) {if (removalPending === null) load(true);} else suspend();});
      refresh.addEventListener("click", () => {if (removalPending === null) return load(true);});
      more.addEventListener("click", () => {if (removalPending === null) return load(false);});
      sync();
    },
    setOwner(value) {
      if (value === owner) return;
      owner = value; ownerEpoch++; removalPending = null; removals.clear(); suspend(); message("");
    },
    open() {active = true; sync(); if (panel.open && removalPending === null) load(true);},
    close() {active = false; suspend();},
  });
}
