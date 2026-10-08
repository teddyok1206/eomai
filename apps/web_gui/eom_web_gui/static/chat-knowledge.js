// Model-free Item discovery. These cards are not citations or grounded turns.
export function createChatKnowledge({document, api, errorMessage, openItem}) {
  const $ = (id) => document.getElementById(id);
  let owner = null;
  let visible = false;
  let serial = 0;

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
      const source = {PAST_EXAM: "기출", GENERATED: "제작 문항", UNCLASSIFIED: "문항"}[card.source_kind];
      const approval = card.approval.status === "APPROVED" ? "승인 완료" : "승인 대기";
      const graph = {INDEXED: "Graph 반영", NOT_INDEXED: "Graph 미반영", UNAVAILABLE: "Graph 확인 불가"}[card.graph_membership];
      detail.textContent = `${source} · ${approval} · ${graph} · ${new Date(card.created_at).toLocaleString("ko-KR", {timeZone: "Asia/Seoul"})}`;
      article.append(button, detail);
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
    open() { visible = true; },
    close() { visible = false; clear(); },
    setOwner(value) {
      if (owner === value) return;
      owner = value;
      clear();
      $("chat-knowledge-query").value = "";
      $("chat-knowledge-panel").open = false;
    },
  });
}
