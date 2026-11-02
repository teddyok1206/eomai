// Owns the list and durable search identity. The existing one-anchor view only reads results.
import {createItemDbSimilarity, itemDbSimilaritySelection} from "./item-db-similarity.js";

const SEARCH_ID = /^dbsearch_[0-9a-f]{32}$/;
const OWNER_ID = /^operator_[0-9a-f]{32}$/;
const pointerKey = (pointer) => JSON.stringify(Object.fromEntries(Object.entries(pointer).sort(([a], [b]) => a.localeCompare(b))));
const sourceKey = (pointer) => pointer.kind === "GRAPH_ITEM" ? pointer.item_revision_id : pointer.source_revision_id;
const intentKey = (selections, topK) => JSON.stringify([selections.map(pointerKey), topK]);

function fromPointer(pointer) {
  return itemDbSimilaritySelection(pointer.kind, pointer.kind === "GRAPH_ITEM"
    ? {...pointer, snapshot_sha256: pointer.graph_snapshot_sha256} : pointer);
}

export function createItemDbSimilarityList({document, searches, previewSelection, openSelection, activate}) {
  const $ = (selector) => document.querySelector(selector);
  const draft = new Map();
  const labels = new Map();
  const results = new Map();
  let owner = null;
  let epoch = 0;
  let generation = 0;
  let current = null;
  let ordinal = 0;
  let pendingIntent = null;
  let busy = false;
  let polling = null;
  let elapsedTimer = null;
  let previewGeneration = 0;
  let displayKey = null;
  const view = createItemDbSimilarity({document, activate, openSelection,
    async search() {
      const record = current, position = ordinal, capturedOwner = owner, capturedEpoch = epoch;
      if (!record?.children[position]?.selection) throw new Error("선택한 기준 문항의 계산이 아직 끝나지 않았습니다.");
      const key = `${record.search_id}:${position}`;
      let value = results.get(key);
      if (!value) {
        value = await searches.result(record.search_id, position);
        if (value.search_id !== record.search_id || value.ordinal !== position
          || value.source_item_revision_id !== record.children[position].source_item_revision_id
          || !Array.isArray(value.candidates) || value.candidates.length > record.top_k) {
          throw new Error("원래 검색과 다른 결과가 반환됐습니다.");
        }
        if (capturedOwner === owner && capturedEpoch === epoch) {
          results.set(key, value);
          if (results.size > 64) results.delete(results.keys().next().value);
        }
      }
      return {...value, phase: "READING_RESULTS"};
    },
  });

  function element(tag, text) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function message(text, error = false) {
    const node = $("#item-db-similarity-message");
    node.textContent = text;
    node.className = `form-message${error ? " error" : ""}`;
  }

  function stopPolling() {
    if (polling !== null) clearTimeout(polling);
    polling = null;
    if (elapsedTimer !== null) clearInterval(elapsedTimer);
    elapsedTimer = null;
  }

  function progress() {
    const running = busy || current?.status === "PENDING" || current?.status === "PREPARING";
    $("#item-db-similarity-progress").hidden = !running;
    $("#item-db-similarity-tab-progress").hidden = !running;
    if (!running) return;
    $("#item-db-similarity-progress-label").textContent = busy ? "검색 상태 확인 중"
      : current?.status === "PREPARING" ? "검색 준비 중"
        : current?.device ? "유사도 계산 중" : "작업 순서를 기다리고 있습니다";
    // This is elapsed wall time, not an invented GPU percentage or completion estimate.
    const seconds = Math.max(0, Math.floor((Date.now() - Date.parse(current?.created_at || new Date().toISOString())) / 1000));
    $("#item-db-similarity-elapsed").textContent = `요청 후 ${Math.floor(seconds / 60)}분 ${seconds % 60}초`;
  }

  function controls() {
    $("#item-db-similarity-run").disabled = !owner || !draft.size || busy || !searches;
    $("#item-db-similarity-refresh").disabled = !current || busy;
    $("#item-db-similarity-top-k").disabled = busy;
    $("#item-db-similarity-draft-count").textContent = `${draft.size}문항`;
    if (current?.status === "PENDING" || current?.status === "PREPARING") {
      const complete = current.children.filter(child => child.state === "COMPLETED").length;
      $("#item-db-similarity-count").textContent = `${complete}/${current.selections.length}문항 계산 완료`;
    }
    progress();
  }

  function renderDraft() {
    const list = $("#item-db-similarity-draft");
    list.replaceChildren();
    for (const [key, entry] of draft) {
      const row = element("li");
      const remove = element("button", "빼기");
      remove.type = "button"; remove.className = "button quiet";
      remove.addEventListener("click", () => {draft.delete(key); pendingIntent = null; renderDraft();});
      row.append(element("span", entry.label), remove);
      list.append(row);
    }
    controls();
  }

  function validRecord(value, expectedId) {
    if (!value || !SEARCH_ID.test(value.search_id) || (expectedId && value.search_id !== expectedId)
      || !Array.isArray(value.selections) || !value.selections.length || value.selections.length > 32
      || !Number.isInteger(value.top_k) || value.top_k < 1 || value.top_k > 64
      || !["PREPARING", "PENDING", "READY", "FAILED", "UNAVAILABLE"].includes(value.status)
      || !Array.isArray(value.children) || (value.children.length && value.children.length !== value.selections.length)) {
      throw new Error("검색 기록의 문항 목록을 확인하지 못했습니다.");
    }
    value.selections.forEach(fromPointer);
    return value;
  }

  function renderAnchors() {
    const select = $("#item-db-similarity-source-select");
    select.replaceChildren();
    if (!current) return;
    current.selections.forEach((pointer, index) => {
      const option = element("option", labels.get(pointerKey(pointer)) || `기준 문항 ${index + 1}`);
      option.value = String(index); select.append(option);
    });
    select.value = String(ordinal);
    select.disabled = current.selections.length === 1;
  }

  async function selectAnchor() {
    if (!current) return;
    const record = current, capturedEpoch = epoch;
    const pointer = record.selections[ordinal];
    const label = labels.get(pointerKey(pointer)) || `기준 문항 ${ordinal + 1}`;
    const key = `${record.search_id}:${ordinal}`;
    if (displayKey === key) {
      if (record.children[ordinal]?.selection) return view.start(fromPointer(pointer), label);
      controls();
      return;
    }
    displayKey = key;
    const previewRequest = ++previewGeneration;
    $("#item-db-similarity-anchor").textContent = `${label} · 상위 ${record.top_k}개`;
    const root = $("#item-db-similarity-source-preview");
    root.replaceChildren(element("p", "기준 문항을 불러오는 중입니다."));
    Promise.resolve(previewSelection?.(pointer, root, () => previewRequest === previewGeneration && capturedEpoch === epoch))
      .catch(() => {if (previewRequest === previewGeneration && capturedEpoch === epoch) root.replaceChildren(element("p", "이 문항의 미리보기를 불러오지 못했습니다."));});
    view.reset();
    if (record.children[ordinal]?.selection) {
      await view.start(fromPointer(pointer), label);
    } else {
      message(record.status === "FAILED" ? "일부 검색이 실패했습니다. 완료된 문항의 결과는 계속 열 수 있습니다."
        : record.status === "UNAVAILABLE" ? "목록의 문항 중 풀이보고서 또는 검색 자료가 아직 준비되지 않은 문항이 있습니다."
          : "선택한 기준 문항의 계산을 기다리고 있습니다.", record.status === "FAILED");
      controls();
    }
  }

  async function recent() {
    if (!owner || !searches) return;
    const capturedEpoch = epoch;
    try {
      const page = await searches.recent();
      if (capturedEpoch !== epoch) return;
      const root = $("#item-db-similarity-history");
      root.replaceChildren();
      for (const raw of page.values) {
        const record = validRecord(raw);
        const time = new Intl.DateTimeFormat("ko-KR", {timeZone: "Asia/Seoul", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit"}).format(new Date(record.created_at));
        const state = {READY: "완료", PENDING: "계산 중", PREPARING: "준비 중", FAILED: "실패", UNAVAILABLE: "준비 필요"}[record.status];
        const button = element("button", `${time} · ${record.selections.length}문항 · 상위 ${record.top_k}개 · ${state}`);
        button.type = "button"; button.className = "item-db-history-entry";
        button.addEventListener("click", () => openRecord(record.search_id));
        root.append(button);
      }
      if (!page.values.length) root.append(element("p", "아직 저장된 검색이 없습니다."));
    } catch (error) {
      if (capturedEpoch === epoch) $("#item-db-similarity-history").textContent = `검색 기록 조회 실패: ${error.message}`;
    }
  }

  async function openRecord(searchId) {
    if (!owner || busy) return;
    const request = ++generation, capturedEpoch = epoch;
    stopPolling(); busy = true; controls();
    try {
      const record = validRecord(await searches.read(searchId), searchId);
      if (request !== generation || capturedEpoch !== epoch) return;
      current = record; ordinal = 0; displayKey = null;
      // Reopening history reauthorizes the canonical read; same-page confirmation stays local.
      for (const key of results.keys()) if (key.startsWith(`${searchId}:`)) results.delete(key);
      view.reset();
      renderAnchors(); activate("similarity");
      await selectAnchor();
    } catch (error) {
      if (request === generation && capturedEpoch === epoch) message(`검색 기록을 열지 못했습니다: ${error.message}`, true);
    } finally {
      if (request === generation && capturedEpoch === epoch) {busy = false; controls();}
    }
  }

  async function check() {
    if (!current || busy) return;
    if (["READY", "FAILED"].includes(current.status)) {
      if (current.children[ordinal]?.selection) return selectAnchor();
      controls(); return;
    }
    const request = generation, capturedEpoch = epoch, searchId = current.search_id;
    busy = true; controls();
    if (elapsedTimer === null) elapsedTimer = setInterval(progress, 1000);
    try {
      const value = validRecord(await searches.check(searchId), searchId);
      if (request !== generation || capturedEpoch !== epoch) return;
      if (intentKey(value.selections, value.top_k) !== intentKey(current.selections, current.top_k)) throw new Error("원래 검색의 문항 또는 결과 개수가 바뀌었습니다.");
      current = value;
      if (current.children[ordinal]?.selection) await selectAnchor();
      else message(value.status === "FAILED" ? "검색을 완료하지 못했습니다. 기존 실패 기록은 보존됩니다." : "검색을 진행하고 있습니다.", value.status === "FAILED");
    } catch (error) {
      if (request === generation && capturedEpoch === epoch) message(`검색 상태를 확인하지 못했습니다: ${error.message}`, true);
      return;
    } finally {
      if (request === generation && capturedEpoch === epoch) {busy = false; controls();}
    }
    if (current?.status === "PENDING" && request === generation && capturedEpoch === epoch) polling = setTimeout(check, 2500);
    else {stopPolling(); recent();}
  }

  async function run() {
    if (!owner || busy || !draft.size) return;
    const topK = Number($("#item-db-similarity-top-k").value);
    if (!Number.isInteger(topK) || topK < 1 || topK > 64) {message("결과 개수는 1~64개로 정해 주세요.", true); return;}
    const selections = [...draft.values()].map(entry => entry.selection.pointer);
    const fingerprint = intentKey(selections, topK);
    if (current && fingerprint === intentKey(current.selections, current.top_k)) {activate("similarity"); return check();}
    if (!pendingIntent || pendingIntent.fingerprint !== fingerprint) pendingIntent = {fingerprint, key: `studio:db-similarity:${crypto.randomUUID()}`};
    const request = ++generation, capturedEpoch = epoch;
    stopPolling(); busy = true; controls();
    try {
      const record = validRecord(await searches.submit(selections, topK, pendingIntent.key));
      if (request !== generation || capturedEpoch !== epoch) return;
      if (intentKey(record.selections, record.top_k) !== fingerprint) throw new Error("다른 문항 목록의 검색이 반환됐습니다.");
      current = record; ordinal = 0; renderAnchors(); activate("similarity");
      await selectAnchor();
    } catch (error) {
      if (request === generation && capturedEpoch === epoch) message(`검색 시작 실패: ${error.message}`, true);
      return;
    } finally {
      if (request === generation && capturedEpoch === epoch) {busy = false; controls();}
    }
    recent();
    if (["UNAVAILABLE", "FAILED"].includes(current?.status)) return;
    return check();
  }

  return Object.freeze({
    available: () => Boolean(searches),
    install() {
      $("#item-db-similarity-run").addEventListener("click", run);
      $("#item-db-similarity-refresh").addEventListener("click", check);
      $("#item-db-similarity-history-refresh").addEventListener("click", recent);
      $("#item-db-similarity-source-select").addEventListener("change", async () => {
        const next = Number($("#item-db-similarity-source-select").value);
        if (!current || !Number.isInteger(next) || next < 0 || next >= current.selections.length) return;
        ordinal = next; await selectAnchor();
      });
      controls();
    },
    start(selection, label) {
      const key = sourceKey(selection.pointer);
      if (!draft.has(key) && draft.size >= 32) {message("한 번에 최대 32문항까지 검색할 수 있습니다.", true); return;}
      draft.set(key, {selection, label}); labels.set(pointerKey(selection.pointer), label);
      pendingIntent = null; renderDraft(); activate("similarity");
      message("목록의 문항과 결과 개수를 정한 뒤 ‘검색 시작’을 누르세요.");
    },
    reset() {
      epoch++; generation++; previewGeneration++; stopPolling(); busy = false;
      current = null; displayKey = null; pendingIntent = null; results.clear(); draft.clear(); labels.clear(); view.reset();
      renderDraft(); $("#item-db-similarity-source-preview").replaceChildren();
      $("#item-db-similarity-history").replaceChildren();
    },
    setOwner(value) {
      const next = typeof value === "string" && OWNER_ID.test(value) ? value : null;
      if (next === owner) return;
      this.reset(); owner = next; view.setOwner(owner); controls();
      if (owner) recent();
    },
  });
}
