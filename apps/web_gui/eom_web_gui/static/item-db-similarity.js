// Presentation only. The injected adapter must use the official authenticated QUERY/read use case.
const ID = Object.freeze({
  item: /^item_[0-9a-f]{32}$/,
  revision: /^itemrev_[0-9a-f]{32}$/,
  graph: /^graphrev_[0-9a-f]{32}$/,
  source: /^extitem_[0-9a-f]{32}$/,
  sourceRevision: /^extitemrev_[0-9a-f]{32}$/,
  hash: /^sha256:[0-9a-f]{64}$/,
});
const PHASE_LABELS = Object.freeze({
  PREPARING: "검색 준비 중",
  WAITING_FOR_RESOURCE: "작업 순서를 기다리고 있습니다",
  COMPUTING: "유사도 계산 중",
  READING_RESULTS: "결과 불러오는 중",
});

export function itemDbSimilaritySelection(kind, entry) {
  let pointer;
  if (kind === "GRAPH_ITEM" && ["PAST_EXAM", "APPROVED_ITEM"].includes(entry?.source_class)
    && ID.item.test(entry.item_id) && ID.revision.test(entry.item_revision_id)
    && ID.hash.test(entry.item_manifest_sha256) && ID.graph.test(entry.graph_snapshot_revision_id)
    && ID.hash.test(entry.snapshot_sha256)) {
    pointer = {kind, item_id: entry.item_id, item_revision_id: entry.item_revision_id,
      item_manifest_sha256: entry.item_manifest_sha256,
      graph_snapshot_revision_id: entry.graph_snapshot_revision_id,
      graph_snapshot_sha256: entry.snapshot_sha256};
  } else if (kind === "EXTERNAL_SOURCE" && ID.source.test(entry?.source_id)
    && ID.sourceRevision.test(entry.source_revision_id) && ID.hash.test(entry.observation_sha256)) {
    pointer = {kind, source_id: entry.source_id, source_revision_id: entry.source_revision_id,
      observation_sha256: entry.observation_sha256};
  } else {
    throw new Error("선택한 문항의 버전을 확인하지 못했습니다. 다시 조회해 주세요.");
  }
  return Object.freeze({kind, entry: Object.freeze({...entry}), pointer: Object.freeze(pointer)});
}

function selectionKey(selection) {
  return JSON.stringify(selection.pointer);
}

function sourceIdentity(selection) {
  return selection.kind === "GRAPH_ITEM"
    ? `${selection.kind}:${selection.pointer.item_revision_id}`
    : `${selection.kind}:${selection.pointer.source_id}:${selection.pointer.source_revision_id}`;
}

export function createItemDbSimilarity({document, search, openSelection, activate}) {
  const $ = (selector) => document.querySelector(selector);
  let operation = null;
  let sequence = 0;
  let busy = false;
  let elapsedTimer = null;
  let observationTimer = null;

  function clearObservation() {
    if (observationTimer !== null) clearTimeout(observationTimer);
    observationTimer = null;
  }

  function updateElapsed() {
    if (!operation) return;
    const seconds = Math.max(0, Math.floor((performance.now() - operation.startedAt) / 1000));
    const elapsed = seconds >= 60 ? `${Math.floor(seconds / 60)}분 ${seconds % 60}초` : `${seconds}초`;
    $("#item-db-similarity-elapsed").textContent = `요청 후 ${elapsed}`;
  }

  function progress() {
    const processing = busy || operation?.result?.status === "PENDING";
    $("#item-db-similarity-progress").hidden = !processing;
    $("#item-db-similarity-tab-progress").hidden = !processing;
    if (processing) {
      $("#item-db-similarity-progress-label").textContent = PHASE_LABELS[operation.result?.phase] || "유사도 검색 중";
      updateElapsed();
      if (elapsedTimer === null) elapsedTimer = setInterval(updateElapsed, 1000);
    } else if (elapsedTimer !== null) {
      clearInterval(elapsedTimer);
      elapsedTimer = null;
    }
  }

  function message(text, error = false) {
    const target = $("#item-db-similarity-message");
    target.className = `form-message${error ? " error" : ""}`;
    target.textContent = text;
  }

  function element(tag, text) {
    const value = document.createElement(tag);
    if (text !== undefined) value.textContent = text;
    return value;
  }

  function empty(text) {
    const row = element("tr");
    const cell = element("td", text);
    cell.colSpan = 5;
    cell.className = "empty-state";
    row.append(cell);
    $("#item-db-similarity-results").replaceChildren(row);
  }

  function controls() {
    $("#item-db-similarity-refresh").disabled = !operation || busy || typeof search !== "function";
    $("#item-db-similarity-results").setAttribute("aria-busy", String(busy));
    progress();
  }

  function readCandidates(result) {
    if (!result || !["READY", "PARTIAL", "PENDING", "UNAVAILABLE", "FAILED"].includes(result.status)) {
      throw new Error("검색 결과를 확인하지 못했습니다. 같은 요청으로 다시 확인해 주세요.");
    }
    if (result.phase !== undefined && !Object.hasOwn(PHASE_LABELS, result.phase)) {
      throw new Error("검색 진행 상태를 확인하지 못했습니다.");
    }
    if (!["READY", "PARTIAL"].includes(result.status)) return [];
    if (!Array.isArray(result.candidates) || result.candidates.length > 64) {
      throw new Error("검색 결과 목록을 확인하지 못했습니다.");
    }
    const seen = new Set();
    return result.candidates.map((candidate) => {
      const selection = itemDbSimilaritySelection(candidate.kind, candidate.entry);
      const key = sourceIdentity(selection);
      if (seen.has(key) || key === sourceIdentity(operation.selection)
        || typeof candidate.label !== "string" || !candidate.label.trim() || candidate.label.length > 512
        || (candidate.unit_label !== undefined && (typeof candidate.unit_label !== "string" || candidate.unit_label.length > 512))
        || !Number.isInteger(candidate.cosine_millionths)
        || Math.abs(candidate.cosine_millionths) > 1000000) {
        throw new Error("검색 결과의 문항 또는 점수를 확인하지 못했습니다.");
      }
      seen.add(key);
      return {...candidate, selection};
    });
  }

  function render(result, candidates) {
    const root = $("#item-db-similarity-results");
    root.replaceChildren();
    candidates.forEach((candidate, index) => {
      const row = element("tr");
      const title = element("button", candidate.label);
      title.type = "button";
      title.className = "item-db-row-open";
      title.setAttribute("aria-label", `${candidate.label} 조회에서 열기`);
      const cell = element("td");
      cell.append(title);
      row.append(element("td", String(index + 1)), cell,
        element("td", candidate.kind === "EXTERNAL_SOURCE" ? "창작 원본"
          : candidate.entry.source_class === "PAST_EXAM" ? "기출" : "창작·승인 문항"),
        element("td", candidate.unit_label || "—"),
        element("td", (candidate.cosine_millionths / 1000000).toFixed(3)));
      row.addEventListener("click", () => openSelection(candidate.selection));
      root.append(row);
    });
    $("#item-db-similarity-count").textContent = `${candidates.length}개`;
    if (!candidates.length) empty("이 범위에서 유사한 문항을 찾지 못했습니다.");
    message(result.status === "PARTIAL"
      ? "풀이보고서와 임베딩이 준비된 문항에서 찾았습니다. 결과를 선택하면 조회에서 열립니다."
      : "결과를 선택하면 조회에서 문항을 열 수 있습니다.");
  }

  async function observe() {
    if (!operation || busy) return;
    clearObservation();
    const request = ++sequence;
    if (typeof search !== "function") {
      message("유사도 검색 연결을 준비하고 있습니다. 기존 조회와 배치는 그대로 이용할 수 있습니다.");
      return;
    }
    busy = true;
    if (operation.result?.status !== "PENDING") operation.result = null;
    empty("유사한 문항을 찾고 있습니다.");
    controls();
    message("선택한 문항과 유사한 문항을 찾고 있습니다.");
    try {
      const result = await search(operation.selection.pointer, operation.idempotencyKey);
      if (request !== sequence) return;
      const candidates = readCandidates(result);
      operation.result = result;
      if (["READY", "PARTIAL"].includes(result.status)) render(result, candidates);
      else {
        empty(result.status === "PENDING" ? "검색 중입니다. 잠시 뒤 결과를 확인해 주세요."
          : result.status === "UNAVAILABLE" ? "이 문항은 풀이보고서 또는 검색 자료가 아직 준비되지 않았습니다."
            : "검색을 완료하지 못했습니다.");
        $("#item-db-similarity-count").textContent = {
          PENDING: "검색 중", UNAVAILABLE: "준비 필요", FAILED: "작업 실패",
        }[result.status];
        message(result.message || (result.status === "PENDING"
          ? "결과 확인은 같은 검색 요청을 이어서 확인합니다." : "문항 조회와 배치는 계속 사용할 수 있습니다."), result.status === "FAILED");
      }
    } catch (error) {
      if (request === sequence) {
        operation.result = null;
        empty("검색이 끝났는지 확인하지 못했습니다. ‘결과 확인’을 눌러 주세요.");
        $("#item-db-similarity-count").textContent = "확인 필요";
        message(`검색 상태를 확인하지 못했습니다: ${error.message || "다시 확인해 주세요."}`, true);
      }
    } finally {
      if (request === sequence) {
        busy = false;
        controls();
        if (operation.result?.status === "PENDING") observationTimer = setTimeout(observe, 2500);
      }
    }
  }

  return Object.freeze({
    available: () => typeof search === "function",
    install() {
      $("#item-db-similarity-refresh").addEventListener("click", observe);
      controls();
      if (typeof search !== "function") {
        message("유사도 검색 연결을 준비하고 있습니다. 기존 조회와 배치는 그대로 이용할 수 있습니다.");
      }
    },
    reset() {
      sequence++;
      clearObservation();
      operation = null;
      busy = false;
      controls();
      $("#item-db-similarity-anchor").textContent = "조회에서 문항을 선택해 주세요.";
      $("#item-db-similarity-count").textContent = "검색 전";
      empty("아직 검색한 문항이 없습니다.");
      message("사용 권한이 바뀌었습니다. 조회에서 문항을 다시 선택해 주세요.");
    },
    start(selection, label) {
      activate("similarity");
      if (operation && selectionKey(operation.selection) === selectionKey(selection)) return observe();
      clearObservation();
      sequence++;
      busy = false;
      operation = {selection, idempotencyKey: `studio:db-similarity:${crypto.randomUUID()}`, result: null,
        startedAt: performance.now()};
      $("#item-db-similarity-anchor").textContent = label;
      $("#item-db-similarity-count").textContent = "검색 전";
      empty("선택한 문항으로 검색을 시작합니다.");
      return observe();
    },
  });
}
