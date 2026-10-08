import assert from "node:assert/strict";
const {renderChatMarkdown} = await import(process.argv[2]);

class Node {
  constructor(tag) { this.tagName = tag; this.children = []; this.style = {}; this.attributes = {}; this.handlers = {}; this.content = ""; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; this.content = ""; }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(key, handler) { this.handlers[key] = handler; }
  set textContent(value) { this.content = value; this.children = []; }
  get textContent() { return this.content + this.children.map((node) => node.textContent).join(""); }
}
const document = {
  createElement: (tag) => new Node(tag),
  createTextNode: (text) => { const node = new Node("#text"); node.textContent = text; return node; },
};
const flatten = (node) => [node, ...node.children.flatMap(flatten)];
const render = (text) => {
  const container = new Node("article");
  renderChatMarkdown(document, container, text);
  return container;
};

const formatted = render("# 제목\n\n**굵게** *기울임* ~~삭제~~ `인라인` &amp; &#xD55C;\n\n> 인용\n\n- 목록\n  - 중첩\n- [x] 완료\n\n3. 셋\n4. 넷\n\n| 가 | 나 |\n|:---|---:|\n| 1 | 2 |\n\n---\n\n```python\nprint('<script>')\n```\n\n[안전한 링크](https://example.com/page)");
const nodes = flatten(formatted);
for (const tag of ["h1", "strong", "em", "del", "code", "blockquote", "ul", "ol", "li", "table", "thead", "tbody", "th", "td", "hr", "pre", "a"]) assert(nodes.some((node) => node.tagName === tag), tag);
assert.equal(nodes.find((node) => node.tagName === "ol").start, 3);
assert(nodes.some((node) => node.tagName === "td" && node.style.textAlign === "right"));
assert(formatted.textContent.includes("& 한"));
assert(formatted.textContent.includes("☑ 완료"));
const link = nodes.find((node) => node.tagName === "a");
assert.equal(link.href, "https://example.com/page");
assert.equal(link.rel, "noopener noreferrer");
assert.equal(link.referrerPolicy, "no-referrer");
let copied;
Object.defineProperty(globalThis, "navigator", {value: {clipboard: {writeText: async (text) => { copied = text; }}}, configurable: true});
await nodes.find((node) => node.tagName === "button").handlers.click();
assert.equal(copied, "print('<script>')");

const attacks = render('<script>alert(1)</script>\n\n<img src="https://tracker.invalid" onerror="alert(1)">\n\n[실행](javascript:alert%281%29) [파일](file:///etc/passwd) [데이터](data:text/html,payload) [인증](https://user:pass@example.com/)\n\n![외부 그림](https://tracker.invalid/pixel)\n\n&lt;iframe src=x&gt;');
const unsafe = flatten(attacks);
assert(!unsafe.some((node) => ["script", "iframe", "img", "input", "style", "a"].includes(node.tagName)));
assert(attacks.textContent.includes('<script>alert(1)</script>'));
assert(attacks.textContent.includes("외부 그림"));
assert(unsafe.every((node) => !Object.keys(node.attributes).some((name) => /^on/i.test(name))));

const long = "**x** ".repeat(3500);
const bounded = render(long);
assert.equal(bounded.children[0].className, "chat-text");
assert.equal(bounded.textContent, long);
for (const text of ["> ".repeat(1500) + "깊은 중첩", "[".repeat(12000), "````js\nconst x = 1;\n````", "한글\n줄바꿈"]) assert(render(text).textContent);
assert.throws(() => render("a".repeat(32001)), /CHAT_MARKDOWN_INVALID/);
assert.equal(render("😀".repeat(17000)).textContent, "😀".repeat(17000));
console.log("CHAT_MARKDOWN=PASS formatting/security/copy/bounded-fallback");
