import {Lexer} from "./vendor-marked-18.1.0.js";

// Parse Markdown once, then construct only permitted DOM elements. Model HTML
// never enters an HTML sink, and images never load external tracking resources.
export function renderChatMarkdown(document, container, text) {
  if (typeof text !== "string" || text.length > 64000 || (text.length > 32000 && Array.from(text).length > 32000)) throw new TypeError("CHAT_MARKDOWN_INVALID");
  const root = document.createElement("div");
  root.className = "chat-markdown";
  let nodes = 0;
  const element = (tag) => {
    if (++nodes > 4096) throw new RangeError("CHAT_MARKDOWN_LIMIT");
    return document.createElement(tag);
  };
  const literal = (parent, value) => {
    if (++nodes > 4096) throw new RangeError("CHAT_MARKDOWN_LIMIT");
    parent.append(document.createTextNode(value));
  };
  const entities = (value) => value.replace(/&(?:#(x[0-9a-f]+|\d+)|(amp|lt|gt|quot|apos|nbsp));/gi, (raw, number, name) => {
    if (!number) return {amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: "\u00a0"}[name.toLowerCase()];
    const code = number[0].toLowerCase() === "x" ? parseInt(number.slice(1), 16) : Number(number);
    return code > 0 && code <= 0x10ffff && !(code >= 0xd800 && code <= 0xdfff) ? String.fromCodePoint(code) : raw;
  });
  const linkTarget = (href) => {
    try {
      const url = new URL(entities(href));
      if (!["https:", "http:"].includes(url.protocol) || url.username || url.password) return null;
      return url.href;
    } catch (_) { return null; }
  };
  function codeBlock(parent, token) {
    const block = element("div");
    block.className = "chat-code";
    const toolbar = element("div");
    toolbar.className = "chat-code-toolbar";
    const language = element("span");
    language.textContent = (token.lang || "").split(/\s/, 1)[0].slice(0, 40);
    const copy = element("button");
    copy.type = "button";
    copy.className = "button quiet";
    copy.textContent = "코드 복사";
    copy.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(token.text); copy.textContent = "복사됨"; }
      catch (_) { copy.textContent = "복사하지 못했습니다"; }
    });
    toolbar.append(language, copy);
    const pre = element("pre");
    const code = element("code");
    code.textContent = token.text;
    pre.append(code);
    block.append(toolbar, pre);
    parent.append(block);
  }
  function table(parent, token, depth) {
    const frame = element("div");
    frame.className = "chat-table";
    const grid = element("table");
    const head = element("thead"), body = element("tbody");
    const row = (cells, target, heading) => {
      const line = element("tr");
      for (const cell of cells) {
        const node = element(heading ? "th" : "td");
        if (heading) node.setAttribute("scope", "col");
        if (["left", "center", "right"].includes(cell.align)) node.style.textAlign = cell.align;
        walk(node, cell.tokens, depth + 1);
        line.append(node);
      }
      target.append(line);
    };
    row(token.header, head, true);
    for (const cells of token.rows) row(cells, body, false);
    grid.append(head, body);
    frame.append(grid);
    parent.append(frame);
  }
  function walk(parent, tokens, depth = 0) {
    if (depth > 48) throw new RangeError("CHAT_MARKDOWN_LIMIT");
    for (const token of tokens || []) {
      if (token.type === "space" || token.type === "def") continue;
      if (token.type === "code") { codeBlock(parent, token); continue; }
      if (token.type === "table") { table(parent, token, depth); continue; }
      if (token.type === "list") {
        const list = element(token.ordered ? "ol" : "ul");
        if (token.ordered && Number.isSafeInteger(token.start) && token.start > 0) list.start = token.start;
        for (const item of token.items) {
          const node = element("li");
          walk(node, item.tokens, depth + 1);
          list.append(node);
        }
        parent.append(list);
        continue;
      }
      if (token.type === "checkbox") { literal(parent, token.checked ? "☑ " : "☐ "); continue; }
      const tags = {paragraph: "p", strong: "strong", em: "em", del: "del", blockquote: "blockquote", br: "br", hr: "hr", codespan: "code"};
      let tag = tags[token.type];
      if (token.type === "heading") tag = `h${Math.min(6, Math.max(1, token.depth))}`;
      if (token.type === "link") {
        const href = linkTarget(token.href);
        const node = element(href ? "a" : "span");
        if (href) {
          node.href = href;
          node.target = "_blank";
          node.rel = "noopener noreferrer";
          node.referrerPolicy = "no-referrer";
        }
        walk(node, token.tokens, depth + 1);
        parent.append(node);
      } else if (token.type === "image") {
        literal(parent, `[이미지: ${entities(token.text || "")}]`);
      } else if (tag) {
        const node = element(tag);
        if (token.type === "codespan") node.textContent = token.text;
        else walk(node, token.tokens, depth + 1);
        parent.append(node);
      } else if (token.type === "text" && token.tokens) {
        walk(parent, token.tokens, depth + 1);
      } else {
        literal(parent, token.type === "html" ? token.raw : entities(token.text ?? token.raw ?? ""));
      }
    }
  }
  try { walk(root, Lexer.lex(text, {gfm: true, breaks: true})); }
  catch (_) {
    // Bounded pathological nesting/unsupported parser input must not break chat.
    root.replaceChildren();
    root.className = "chat-text";
    root.textContent = text;
  }
  container.append(root);
  return root;
}
