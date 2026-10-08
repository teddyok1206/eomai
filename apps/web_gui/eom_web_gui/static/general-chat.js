const ACTIVE = new Set(["QUEUED", "RUNNING"]);

export function mergeChatMessages(previous, incoming) {
  const indexed = new Map(previous.map((value) => [value.sequence, value]));
  for (const value of incoming) {
    const existing = indexed.get(value.sequence);
    if (existing && (existing.turn_id !== value.turn_id || existing.role !== value.role)) {
      throw new Error("GENERAL_CHAT_MESSAGE_IDENTITY_CHANGED");
    }
    indexed.set(value.sequence, value);
  }
  return [...indexed.values()].sort((a, b) => a.sequence - b.sequence);
}

export function chatIsActive(conversation) {
  return conversation?.messages?.some((value) => ACTIVE.has(value.state)) || false;
}

export function createGeneralChat({document, api, errorMessage}) {
  const $ = (id) => document.getElementById(id);
  let owner = null;
  let visible = false;
  let epoch = 0;
  let timer = null;
  let selected = null;
  let slot = null;
  let conversationCursor = null;
  let sending = false;
  let sendSerial = 0;
  let loading = false;
  let createIntent = null;
  const intents = new Map();
  const drafts = new Map();
  const summaries = new Map();
  // Owner-scoped bounded DOM memo: polling must not parse unchanged immutable
  // replies again. A changed source invalidates the entry; logout clears it.
  const replyBodies = new Map();
  const stopTimer = () => { clearTimeout(timer); timer = null; };
  const key = () => `studio:chat:${crypto.randomUUID()}`;
  const current = (token) => visible && owner !== null && token === epoch;

  function fail(error) {
    $("chat-error").textContent = error?.code === "GENERAL_CHAT_NOT_READY"
      ? "전용 대화 서비스를 준비 중입니다. 입력한 메시지는 그대로 유지됩니다."
      : errorMessage(error);
    $("chat-error").hidden = false;
  }

  function controls() {
    const active = chatIsActive(selected);
    $("chat-send").disabled = $("chat-send").hidden || !slot || slot.state === "UNAVAILABLE" || sending || loading || active;
    $("chat-input").readOnly = sending || loading;
    $("chat-send").textContent = sending ? "전송 중…" : active ? "답변 중…" : "↑ 보내기";
  }

  function render() {
    $("chat-conversation-title").textContent = selected?.title || "새 대화";
    $("chat-more-messages").hidden = !selected?.has_more;
    const log = $("chat-messages");
    const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 80;
    log.replaceChildren();
    if (!selected?.messages?.length) {
      const welcome = document.createElement("div");
      welcome.className = "chat-welcome";
      welcome.textContent = "무엇을 도와드릴까요?";
      log.append(welcome);
    }
    for (const message of selected?.messages || []) {
      const bubble = document.createElement("article");
      bubble.className = `chat-message chat-message-${message.role}`;
      const name = document.createElement("strong");
      name.className = "chat-speaker";
      name.textContent = message.role === "user" ? "나" : "ChatGPT";
      bubble.append(name);
      if (message.text && message.role === "assistant") {
        const key = `${selected.conversation_id}:${message.turn_id}`;
        const cached = replyBodies.get(key);
        if (cached?.text === message.text) bubble.append(cached.node);
        else {
          const node = renderChatMarkdown(document, bubble, message.text);
          replyBodies.set(key, {text: message.text, node});
          if (replyBodies.size > 100) replyBodies.delete(replyBodies.keys().next().value);
        }
      }
      else if (message.text) {
        const text = document.createElement("div");
        text.className = "chat-text";
        text.textContent = message.text;
        bubble.append(text);
      }
      else {
        const status = document.createElement("span");
        status.className = "chat-pending";
        status.textContent = {QUEUED: "차례를 기다리고 있습니다…", RUNNING: "답변을 작성하고 있습니다…",
          FAILED: "답변 생성에 실패했습니다.", CANCELLED: "답변 생성이 취소되었습니다."}[message.state] || "";
        bubble.append(status);
      }
      log.append(bubble);
    }
    controls();
    if (atBottom) log.scrollTop = log.scrollHeight;
  }

  function renderHistory() {
    const list = $("chat-conversations");
    list.replaceChildren();
    const ordered = [...summaries.values()].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
    for (const value of ordered) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "chat-history-item";
      button.textContent = value.title;
      button.setAttribute("aria-pressed", String(value.conversation_id === selected?.conversation_id));
      button.addEventListener("click", () => select(value.conversation_id));
      list.append(button);
    }
    $("chat-more-conversations").hidden = !conversationCursor;
  }

  async function loadHistory(token, cursor = null) {
    const page = cursor
      ? await api(`/general-chat/conversations?cursor=${encodeURIComponent(cursor)}`)
      : await api("/general-chat/conversations");
    if (!current(token)) return;
    for (const value of page.values) summaries.set(value.conversation_id, value);
    conversationCursor = page.next_cursor;
    renderHistory();
  }

  function accept(value, {older = false} = {}) {
    const previous = selected;
    if (previous?.conversation_id === value.conversation_id && value.resource_version < previous.resource_version) return;
    const messages = older || previous?.conversation_id === value.conversation_id
      ? mergeChatMessages(previous?.messages || [], value.messages) : value.messages;
    selected = {...value, messages};
    // Polling the latest page must not lose the older-history cursor.
    if (!older && previous?.conversation_id === value.conversation_id) {
      selected.has_more = previous.has_more;
      selected.next_cursor = previous.next_cursor;
    }
    summaries.set(value.conversation_id, {
      conversation_id: value.conversation_id, title: value.title, updated_at: value.updated_at,
    });
    renderHistory();
    render();
  }

  function schedule(token) {
    stopTimer();
    if (!current(token) || !chatIsActive(selected)) return;
    timer = setTimeout(async () => {
      try {
        const value = await api(`/general-chat/conversations/${selected.conversation_id}`);
        if (!current(token)) return;
        accept(value);
        schedule(token);
      } catch (error) { if (current(token)) fail(error); }
    }, 3000);
  }

  async function refreshSlot(token) {
    const value = await api("/general-chat/slot");
    if (!current(token)) return;
    slot = value;
    $("chat-slot").textContent = {READY: "● 대화 전용 · 준비됨", BUSY: "● 대화 전용 · 응답 중",
      UNAVAILABLE: "○ 대화 전용 · 준비 중"}[value.state];
    $("chat-slot").className = `status-badge tone-${value.state === "UNAVAILABLE" ? "neutral" : "success"}`;
    $("chat-slot").title = value.unavailable_reason || "기존 작업 슬롯과 분리된 대화 전용 슬롯";
    controls();
  }

  async function select(id) {
    if (sending) return;
    drafts.set(selected?.conversation_id || "new", $("chat-input").value);
    stopTimer();
    const token = ++epoch;
    selected = null;
    loading = true;
    $("chat-input").value = drafts.get(id) || "";
    $("chat-error").hidden = true;
    controls();
    try {
      const value = await api(`/general-chat/conversations/${id}`);
      if (!current(token)) return;
      accept(value);
      schedule(token);
    } catch (error) { if (current(token)) { render(); fail(error); } }
    finally { if (current(token)) { loading = false; controls(); } }
  }

  async function send(event) {
    event.preventDefault();
    if (sending || loading || chatIsActive(selected) || !slot || slot.state === "UNAVAILABLE") return;
    const text = $("chat-input").value.trim();
    if (!text) return;
    const token = epoch;
    const operation = ++sendSerial;
    sending = true;
    controls();
    $("chat-error").hidden = true;
    try {
      if (!selected) {
        if (!createIntent) createIntent = {title: text.slice(0, 120), idempotency_key: key()};
        const value = await api("/general-chat/conversations", {
          method: "POST", mutation: true, body: createIntent,
        });
        if (!current(token)) return;
        accept(value);
        createIntent = null;
      }
      const id = selected.conversation_id;
      let intent = intents.get(id);
      if (intent && intent.text !== text) {
        $("chat-error").textContent = "이전 전송의 처리 여부를 확인하려면 새로고침하세요. 메시지를 바꿔 중복 전송하지 않습니다.";
        $("chat-error").hidden = false;
        return;
      }
      if (!intent) {
        intent = {text, expected_version: selected.resource_version, idempotency_key: key()};
        intents.set(id, intent);
      }
      const value = await api(`/general-chat/conversations/${id}/turns`, {
        method: "POST", mutation: true, body: intent,
      });
      if (!current(token)) return;
      intents.delete(id);
      drafts.delete(id);
      drafts.delete("new");
      $("chat-input").value = "";
      accept(value);
      schedule(token);
    } catch (error) { if (current(token)) fail(error); }
    finally {
      if (operation === sendSerial) { sending = false; if (visible) controls(); }
    }
  }

  async function open() {
    visible = true;
    loading = false;
    const token = ++epoch;
    render();
    try {
      await refreshSlot(token);
      if (!current(token) || slot.state === "UNAVAILABLE") return;
      await loadHistory(token);
      if (selected && current(token)) {
        const value = await api(`/general-chat/conversations/${selected.conversation_id}`);
        if (current(token)) { accept(value); schedule(token); }
      }
    } catch (error) { if (current(token)) fail(error); }
  }

  function close() { visible = false; epoch += 1; stopTimer(); }

  function setOwner(value) {
    if (owner === value) return;
    close();
    owner = value;
    sendSerial += 1;
    sending = false;
    selected = null;
    slot = null;
    loading = false;
    createIntent = null;
    intents.clear(); drafts.clear(); summaries.clear(); replyBodies.clear();
    conversationCursor = null;
    $("chat-input").value = "";
    $("chat-error").hidden = true;
    renderHistory(); render();
  }

  function install() {
    $("chat-form").addEventListener("submit", send);
    $("chat-input").addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault(); $("chat-form").requestSubmit();
      }
    });
    $("chat-new").addEventListener("click", () => {
      if (sending) return;
      drafts.set(selected?.conversation_id || "new", $("chat-input").value);
      stopTimer(); epoch += 1; selected = null;
      loading = false;
      $("chat-input").value = drafts.get("new") || "";
      $("chat-error").hidden = true;
      renderHistory(); render(); $("chat-input").focus();
    });
    $("chat-refresh").addEventListener("click", open);
    $("chat-more-conversations").addEventListener("click", async () => {
      const token = epoch;
      try { await loadHistory(token, conversationCursor); }
      catch (error) { if (current(token)) fail(error); }
    });
    $("chat-more-messages").addEventListener("click", async () => {
      const token = epoch;
      if (!selected?.next_cursor) return;
      try {
        const value = await api(`/general-chat/conversations/${selected.conversation_id}?cursor=${encodeURIComponent(selected.next_cursor)}`);
        if (current(token)) accept(value, {older: true});
      } catch (error) { if (current(token)) fail(error); }
    });
  }

  return Object.freeze({install, open, close, setOwner});
}
import {renderChatMarkdown} from "./chat-markdown.js";
