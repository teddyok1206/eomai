import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";

globalThis.crypto = webcrypto;
const {createGeneralChat} = await import(process.argv[2]);

class Element {
  constructor() {
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
    createElement() { return new Element(); },
  };
};

// An uncertain HTTP result replays the same intent, never another model call key.
{
  const document = createDocument();
  const submissions = [];
  const api = async (path, options) => {
    if (path.endsWith("/slot")) return {state: "READY"};
    if (path.endsWith("/turns")) {
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
  input.value = "같은 질문";
  await document.getElementById("chat-form").fire("submit");
  assert.equal(input.value, "같은 질문");
  await document.getElementById("chat-form").fire("submit");
  assert.deepEqual(submissions[0], submissions[1]);
  assert.equal(input.value, "");
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

console.log("CHAT_BROWSER_STATE=PASS uncertain-replay/stale-selection/owner-reset/unavailable");
