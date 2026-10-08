import assert from "node:assert/strict";
const {createChatKnowledge} = await import(process.argv[2]);
class Element {
  constructor(tag = "div") { this.tagName = tag; this.children = []; this.handlers = new Map(); this.value = ""; this.textContent = ""; }
  append(...values) { this.children.push(...values); }
  replaceChildren(...values) { this.children = values; }
  addEventListener(name, handler) { this.handlers.set(name, handler); }
  fire(name) { return this.handlers.get(name)?.({preventDefault() {}}); }
}
const elements = new Map();
const document = {getElementById(id) { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); }, createElement(tag) { return new Element(tag); }};
const $ = (id) => document.getElementById(id);
const card = {item_id: "item_one", item_revision_id: "revision_one", manifest_sha256: "hash_one",
  display_name: '<img src=x onerror="evil()">', created_at: "2026-10-08T00:00:00Z",
  approval: {status: "PENDING"}, graph_membership: "NOT_INDEXED", source_kind: "GENERATED"};
const replies = [];
const calls = [];
const api = (path, options) => {
  calls.push({path, ...options});
  return new Promise((resolve, reject) => replies.push({resolve, reject}));
};
const opened = [];
const controller = createChatKnowledge({document, api, errorMessage: (error) => error.message, openItem: (value) => opened.push(value)});
controller.install(); controller.setOwner("owner-one"); controller.open();
const tick = () => new Promise((resolve) => setImmediate(resolve));
$("chat-knowledge-recent").fire("click");
$("chat-knowledge-generated").fire("click");
replies[1].resolve({values: [card], truncated: false}); await tick();
const list = $("chat-knowledge-results");
assert.equal(list.children.length, 1);
assert.equal(list.children[0].children[0].textContent, card.display_name);
assert.match(list.children[0].children[1].textContent, /승인 대기.*Graph 미반영/);
list.children[0].children[0].fire("click");
assert.deepEqual(opened, [card]);
replies[0].resolve({values: [{...card, display_name: "STALE"}], truncated: true}); await tick();
assert.equal(list.children[0].children[0].textContent, card.display_name);

// Logout or an owner change cannot expose delayed source metadata.
$("chat-knowledge-recent").fire("click");
controller.setOwner("owner-two");
assert.equal(list.children.length, 0);
replies[2].resolve({values: [card], truncated: false}); await tick();
assert.equal(list.children.length, 0);

// Search failure clears older navigation, never quietly asks the model instead.
controller.open(); $("chat-knowledge-query").value = "전자기 유도";
$("chat-knowledge-form").fire("submit");
assert.deepEqual(calls.at(-1).body.query.terms, ["전자기", "유도"]);
replies[3].reject(new Error("UNAVAILABLE")); await tick();
assert.equal(list.children.length, 0);
assert.equal($("chat-knowledge-status").textContent, "UNAVAILABLE");
assert.equal($("chat-knowledge-submit").disabled, false);
assert.ok(calls.every((value) => value.path === "/general-chat/knowledge/search"));
controller.close();
