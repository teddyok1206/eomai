import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";

globalThis.crypto = webcrypto;
const {createGeneralChat} = await import(process.argv[2]);

class Element {
  constructor(tagName = "div") {
    this.tagName = tagName;
    this.style = {};
    this.children = [];
    this.handlers = new Map();
    this.value = "";
    this.textContent = "";
    this.scrollHeight = 0;
    this.scrollTop = 0;
    this.clientHeight = 0;
  }
  append(...values) { this.children.push(...values); }
  replaceChildren(...values) { this.children = values; }
  setAttribute(name, value) { this[name] = value; }
  addEventListener(name, handler) { this.handlers.set(name, handler); }
  focus() {}
  fire(name) { return this.handlers.get(name)?.({preventDefault() {}}); }
}

const tick = () => new Promise((resolve) => setImmediate(resolve));
const first = "chat_" + "1".repeat(32);
const second = "chat_" + "2".repeat(32);
const conversation = (id, title) => ({
  conversation_id: id, title, resource_version: 1, messages: [],
  updated_at: "2026-10-07T00:00:00Z", has_more: false, next_cursor: null,
});
const summaries = [conversation(first, "첫 번째"), conversation(second, "두 번째")];
const createDocument = () => {
  const elements = new Map();
  return {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, new Element());
      return elements.get(id);
    },
    createElement(tag) { return new Element(tag); },
    createTextNode(text) { const node = new Element("#text"); node.textContent = text; return node; },
  };
};

// New conversation invalidates selection responses, not runtime readiness.
// Refetch under the new epoch so an initial late slot reply cannot strand Send.
{
  const document = createDocument();
  const slotReplies = [];
  const calls = [];
  const api = async path => {
    calls.push(path);
    if (path.endsWith("/slot")) return await new Promise(resolve => slotReplies.push(resolve));
    return {values: summaries, next_cursor: null};
  };
  const controller = createGeneralChat({document, api, errorMessage: error => error.message});
  controller.install(); controller.setOwner("owner-one");
  const opening = controller.open();
  document.getElementById("chat-input").value = "새 대화 초안";
  const creating = document.getElementById("chat-new").fire("click");
  assert.equal(slotReplies.length, 2);
  slotReplies[1]({state: "READY"}); await creating; await tick();
  assert.equal(document.getElementById("chat-send").disabled, false);
  assert.equal(document.getElementById("chat-input").value, "새 대화 초안");
  assert.equal(document.getElementById("chat-conversations").children.length, 2);
  slotReplies[0]({state: "UNAVAILABLE", unavailable_reason: "obsolete"});
  await opening; await tick();
  assert.equal(document.getElementById("chat-send").disabled, false);
  assert.equal(calls.some(path => /\/grounded-turns$|\/turns$/.test(path)), false);
  controller.close();
}

// An uncertain HTTP result replays the same intent, never another model call key.
{
  const document = createDocument();
  const submissions = [];
  const api = async (path, options) => {
    if (path.endsWith("/slot")) return {state: "READY"};
    if (path.endsWith("/grounded-turns")) {
      submissions.push({...options.body});
      if (submissions.length === 1) throw new Error("HTTP_TIMEOUT");
      return conversation(first, "첫 번째");
    }
    if (options?.method === "POST") return conversation(first, "첫 번째");
    return {values: summaries, next_cursor: null};
  };
  const controller = createGeneralChat({document, api, errorMessage: (error) => error.message});
  controller.install(); controller.setOwner("owner-one"); await controller.open();
  const input = document.getElementById("chat-input");
  document.getElementById("chat-knowledge-panel").open = true;
  input.value = "같은 질문";
  await document.getElementById("chat-form").fire("submit");
  assert.equal(input.value, "같은 질문");
  assert.equal(document.getElementById("chat-knowledge-panel").open, true);
  await document.getElementById("chat-form").fire("submit");
  assert.deepEqual(submissions[0], submissions[1]);
  assert.equal(input.value, "");
  assert.equal(document.getElementById("chat-knowledge-panel").open, false);
  controller.close();
}

// Selecting B while A is slow cannot render A, nor permit sending into a blank target.
{
  const document = createDocument();
  let resolveFirst;
  const api = async (path) => {
    if (path.endsWith("/slot")) return {state: "READY"};
    if (path.endsWith(first)) return await new Promise((resolve) => { resolveFirst = resolve; });
    if (path.endsWith(second)) return conversation(second, "두 번째");
    return {values: summaries, next_cursor: null};
  };
  const controller = createGeneralChat({document, api, errorMessage: (error) => error.message});
  controller.install(); controller.setOwner("owner-one"); await controller.open();
  const buttons = document.getElementById("chat-conversations").children;
  const slow = buttons.find((value) => value.textContent === "첫 번째").fire("click");
  assert.equal(document.getElementById("chat-send").disabled, true);
  await buttons.find((value) => value.textContent === "두 번째").fire("click");
  await tick();
  resolveFirst(conversation(first, "첫 번째")); await slow; await tick();
  assert.equal(document.getElementById("chat-conversation-title").textContent, "두 번째");
  controller.setOwner("owner-two");
  assert.equal(document.getElementById("chat-conversations").children.length, 0);
  assert.equal(document.getElementById("chat-input").value, "");
  controller.close();
}

// An uncertain deletion keeps one intent and prevents a new turn until replay confirms it.
{
  const document = createDocument();
  const deletions = [];
  let removed = false;
  const api = async (path, options) => {
    if (path.endsWith("/slot")) return {state: "READY"};
    if (path.endsWith("/deletion")) {
      deletions.push({...options.body});
      if (deletions.length === 1) throw new Error("HTTP_TIMEOUT");
      removed = true;
      return {conversation_id: first, resource_version: 2, deleted_at: "2026-10-07T00:01:00Z"};
    }
    if (path.endsWith(first)) return conversation(first, "첫 번째");
    return {values: removed ? [summaries[1]] : summaries, next_cursor: null};
  };
  const controller = createGeneralChat({document, api, errorMessage: error => error.message});
  controller.install(); controller.setOwner("owner-one"); await controller.open();
  await document.getElementById("chat-conversations").children[0].fire("click");
  await document.getElementById("chat-delete").fire("click");
  assert.equal(document.getElementById("chat-delete-confirm").hidden, false);
  await document.getElementById("chat-delete-accept").fire("click");
  assert.equal(document.getElementById("chat-send").disabled, true);
  assert.equal(document.getElementById("chat-error").textContent, "HTTP_TIMEOUT");
  await document.getElementById("chat-delete-accept").fire("click");
  assert.deepEqual(deletions[0], deletions[1]);
  assert.equal(document.getElementById("chat-conversation-title").textContent, "새 대화");
  assert.equal(document.getElementById("chat-conversations").children.length, 1);
  controller.close();
}

// A disabled runtime cannot fabricate a ready badge or submit a question.
{
  const document = createDocument();
  const calls = [];
  const api = async (path) => {
    calls.push(path);
    return {state: "UNAVAILABLE", unavailable_reason: "not activated"};
  };
  const controller = createGeneralChat({document, api, errorMessage: (error) => error.message});
  controller.install(); controller.setOwner("owner-one"); await controller.open();
  document.getElementById("chat-input").value = "질문";
  await document.getElementById("chat-form").fire("submit");
  assert.equal(document.getElementById("chat-send").disabled, true);
  assert.deepEqual(calls, ["/general-chat/slot"]);
  controller.close();
}

// Display-only Markdown and cached bodies cannot change user text or cross owners.
{
  const document = createDocument();
  const view = {...conversation(first, "첫 번째"), messages: [
    {turn_id: "turn-one", sequence: 1, role: "user", state: "COMPLETED", text: "**내 질문**"},
    {turn_id: "turn-one", sequence: 2, role: "assistant", state: "COMPLETED", text: "**답변**"},
  ]};
  const api = async (path) => path.endsWith("/slot") ? {state: "READY"} : path.endsWith(first) ? view : {values: summaries, next_cursor: null};
  const controller = createGeneralChat({document, api, errorMessage: (error) => error.message});
  controller.install(); controller.setOwner("owner-one"); await controller.open();
  await document.getElementById("chat-conversations").children[0].fire("click");
  const messages = document.getElementById("chat-messages").children;
  assert.equal(messages[0].children[1].textContent, "**내 질문**");
  const body = messages[1].children[1];
  assert.equal(body.className, "chat-markdown");
  assert.equal(body.children[0].children[0].tagName, "strong");
  await document.getElementById("chat-conversations").children[0].fire("click");
  assert.equal(document.getElementById("chat-messages").children[1].children[1], body);
  controller.setOwner("owner-two"); await controller.open();
  await document.getElementById("chat-conversations").children[0].fire("click");
  assert.notEqual(document.getElementById("chat-messages").children[1].children[1], body);
  controller.close();
}

// R sources are honest document cards, not invented Item Preview links.
{
  const document = createDocument();
  const item = {item_id: "item_one", item_revision_id: "itemrev_one", manifest_sha256: "pinned"};
  const view = {...conversation(first, "첫 번째"), messages: [
    {turn_id: "turn-one", sequence: 1, role: "user", state: "COMPLETED", text: "교과서와 기출 근거"},
    {turn_id: "turn-one", sequence: 2, role: "assistant", state: "COMPLETED", text: "답변"},
  ]};
  const sources = [
    {key: "R1", kind: "RAG_ANALYSIS", display_name: "<svg onload=bad>", location: "PDF 10-11쪽", approval: "APPROVED", reference: {source: {source_class: "TEXTBOOK"}}},
    {key: "S1", kind: "ITEM_CONTENT", display_name: "기출 문항", approval: "APPROVED", item},
  ];
  const opened = [];
  const api = async path => path.endsWith("/slot") ? {state: "READY"}
    : path.endsWith("/grounding") ? {conversation_id: first, values: [{turn_id: "turn-one", sources}]}
    : path.endsWith(first) ? view : {values: summaries, next_cursor: null};
  const controller = createGeneralChat({document, api, errorMessage: error => error.message, openItem: ref => opened.push(ref)});
  controller.install(); controller.setOwner("owner-one"); await controller.open();
  await document.getElementById("chat-conversations").children[0].fire("click");
  await tick();
  const links = document.getElementById("chat-messages").children[1].children.filter(e => e.className === "chat-source-link" || e.className === "button quiet chat-source-link");
  assert.equal(links.length, 2);
  assert.equal(links[0].tagName, "span");
  assert.equal(links[0].textContent, "[R1] <svg onload=bad> · 교과서 · PDF 10-11쪽 · 승인 분석");
  assert.equal(links[0].handlers.has("click"), false);
  assert.equal(links[1].tagName, "button");
  await links[1].fire("click");
  assert.deepEqual(opened, [item]);
  controller.close();
}

console.log("CHAT_BROWSER_STATE=PASS uncertain-replay/deletion-replay/stale-selection/owner-reset/unavailable/markdown-cache/rag-source-card");
