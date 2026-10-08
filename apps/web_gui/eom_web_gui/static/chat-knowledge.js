// Discovery selects exact pins; citations only come from committed answer evidence.
export function createChatKnowledge({document, api, errorMessage, openItem}) {
  const $ = (id) => document.getElementById(id);
  let owner = null;
  let visible = false;
  let serial = 0;
  const attached = new Map();
  let pinnedSnapshot = null;

  function selection() {
    return attached.size ? {references: [...attached.values()].map(({item_id, item_revision_id, manifest_sha256}) => ({item_id, item_revision_id, manifest_sha256})), snapshot: pinnedSnapshot} : null;
  }

  function resetSelection() {
    attached.clear(); pinnedSnapshot = null;
    let list = $("chat-knowledge-selected");
    if (list) list.replaceChildren();
  }

  function renderAttached() {
    let list = $("chat-knowledge-selected");
    if (!list) {
      list = document.createElement("div"); list.id = "chat-knowledge-selected";
      $("chat-knowledge-results").parentNode.insertBefore(list, $("chat-knowledge-results"));
    }
    list.replaceChildren();
    for (const card of attached.values()) {
      const button = document.createElement("button"); button.type = "button"; button.className = "button quiet";
      button.textContent = `${card.display_name} ×`;
      button.addEventListener("click", () => { attached.delete(card.item_revision_id); if (!attached.size) pinnedSnapshot = null; renderAttached(); });
      list.append(button);
    }
  }

  function clear() {
    serial += 1;
    $("chat-knowledge-results").replaceChildren();
    $("chat-knowledge-status").textContent = "";
    $("chat-knowledge-submit").disabled = false;
  }

  function render(selection) {
    const renderedOwner = owner;
    const renderedSerial = serial;
    const list = $("chat-knowledge-results");
    list.replaceChildren();
    for (const card of selection.values) {
      const article = document.createElement("article");
      article.className = "chat-source-card";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "button quiet";
      button.textContent = card.display_name;
      button.addEventListener("click", () => {
        if (visible && owner === renderedOwner && serial === renderedSerial && openItem) openItem(card);
      });
      const detail = document.createElement("span");
      const attach = document.createElement("button");
      attach.type = "button"; attach.className = "button quiet"; attach.textContent = "대화에 첨부";
      attach.addEventListener("click", () => {
        if (!visible || owner !== renderedOwner || serial !== renderedSerial) return;
        if (attached.has(card.item_revision_id)) return;
        if (attached.size >= 3) { $("chat-knowledge-status").textContent = "한 번에 최대 3개 문항을 첨부할 수 있습니다."; return; }
        const snapshot = selection.snapshot ? {graph_snapshot_revision_id: selection.snapshot.graph_snapshot_revision_id, sha256: selection.snapshot.snapshot_sha256} : null;
        if (attached.size && JSON.stringify(snapshot) !== JSON.stringify(pinnedSnapshot)) { $("chat-knowledge-status").textContent = "Graph 버전이 달라 기존 첨부를 먼저 해제해 주세요."; return; }
        pinnedSnapshot = snapshot; attached.set(card.item_revision_id, card); renderAttached();
        $("chat-knowledge-status").textContent = "첨부한 문항과 연결된 승인 풀이보고서를 다음 답변에 참고합니다.";
      });
      const source = {PAST_EXAM: "기출", GENERATED: "제작 문항", UNCLASSIFIED: "문항"}[card.source_kind];
      const approval = card.approval.status === "APPROVED" ? "승인 완료" : "승인 대기";
      const graph = {INDEXED: "Graph 반영", NOT_INDEXED: "Graph 미반영", UNAVAILABLE: "Graph 확인 불가"}[card.graph_membership];
      detail.textContent = `${source} · ${approval} · ${graph} · ${new Date(card.created_at).toLocaleString("ko-KR", {timeZone: "Asia/Seoul"})}`;
      article.append(button, attach, detail);
      list.append(article);
    }
    $("chat-knowledge-status").textContent = selection.values.length
      ? `${selection.values.length}개 표시${selection.truncated ? " · 일부 결과만 표시됩니다" : ""}`
      : "이 검색 범위에서 일치하는 문항을 찾지 못했습니다.";
  }

  async function search(query) {
    if (!visible || owner === null) return;
    const token = ++serial;
    const requestedOwner = owner;
    $("chat-knowledge-results").replaceChildren();
    $("chat-knowledge-status").textContent = "문항을 찾고 있습니다…";
    $("chat-knowledge-submit").disabled = true;
    try {
      const selection = await api("/general-chat/knowledge/search", {
        method: "POST", mutation: true,
        body: {schema_version: "chat-knowledge-query/1.0", query, limit: 20},
      });
      if (!visible || owner !== requestedOwner || token !== serial) return;
      render(selection);
    } catch (error) {
      if (visible && owner === requestedOwner && token === serial) {
        $("chat-knowledge-results").replaceChildren();
        $("chat-knowledge-status").textContent = errorMessage(error);
      }
    } finally {
      if (token === serial) $("chat-knowledge-submit").disabled = false;
    }
  }

  function install() {
    $("chat-knowledge-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const terms = [...new Set($("chat-knowledge-query").value.toLowerCase().match(/[a-z0-9가-힣_]+/g) || [])];
      if (!terms.length || terms.length > 8 || terms.some((term) => term.length < 2 || term.length > 128)) {
        clear();
        $("chat-knowledge-status").textContent = "개념을 1~8개 입력해 주세요.";
        return;
      }
      search({kind: "TOPIC", terms, source: "ALL"});
    });
    $("chat-knowledge-recent").addEventListener("click", () => search({kind: "RECENT", source: "ALL"}));
    $("chat-knowledge-generated").addEventListener("click", () => search({kind: "RECENT", source: "GENERATED"}));
    $("chat-knowledge-exam-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const number = $("chat-knowledge-exam-number").value;
      search({kind: "EXAM", administration_year: Number($("chat-knowledge-exam-year").value),
        administration_month: Number($("chat-knowledge-exam-month").value),
        target_school_level: "HIGH_SCHOOL", target_grade: Number($("chat-knowledge-exam-grade").value),
        subject_key: "integrated-science", item_number: number ? Number(number) : null});
    });
  }

  return Object.freeze({
    install,
    selection,
    resetSelection,
    open() { visible = true; },
    close() { visible = false; clear(); },
    setOwner(value) {
      if (owner === value) return;
      owner = value;
      resetSelection();
      clear();
      $("chat-knowledge-query").value = "";
      $("chat-knowledge-panel").open = false;
    },
  });
}
