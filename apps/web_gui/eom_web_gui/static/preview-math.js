import katex from "./vendor-katex-0.19.0.js";

const MAX_TEXT_LENGTH = 48000;
const MAX_EQUATION_LENGTH = 4000;
const MAX_EQUATIONS = 128;
const DELIMITERS = new Map([
  ["$$", {close: "$$", display: true}],
  ["$", {close: "$", display: false}],
  ["\\(", {close: "\\)", display: false}],
  ["\\[", {close: "\\]", display: true}],
]);

function closingDelimiter(text, start, close) {
  let depth = 0;
  for (let index = start; index < text.length; index += 1) {
    if (text[index] === "\\") {
      if (depth === 0 && text.startsWith(close, index)) return index;
      index += 1;
      continue;
    }
    if (text[index] === "{") depth += 1;
    if (text[index] === "}") depth = Math.max(0, depth - 1);
    if (depth === 0 && text.startsWith(close, index)) {
      if (close === "$" && (/\s/.test(text[index - 1]) || text[index + 1] === "$")) continue;
      return index;
    }
  }
  return -1;
}

// This is a presentation boundary, not a rewrite of canonical Item content.
// Every scan is forward-only. Expressions and DOM growth are explicitly bounded.
export function renderPreviewText(target, value) {
  const text = typeof value === "string" ? value : "";
  target.replaceChildren();
  if (text.length > MAX_TEXT_LENGTH) {
    target.textContent = text;
    return;
  }
  let cursor = 0;
  let plainStart = 0;
  let count = 0;
  while (cursor < text.length && count < MAX_EQUATIONS) {
    const character = text[cursor];
    const two = text.slice(cursor, cursor + 2);
    if (character === "\\" && two !== "\\(" && two !== "\\[") {
      cursor += 2;
      continue;
    }
    const open = DELIMITERS.has(two) ? two : character === "$" ? "$" : null;
    if (open === null || (open === "$" && /\s/.test(text[cursor + 1] || " "))) {
      cursor += 1;
      continue;
    }
    const {close, display} = DELIMITERS.get(open);
    const start = cursor + open.length;
    const end = closingDelimiter(text, start, close);
    if (end < 0) break; // Preserve unmatched input rather than dropping a delimiter.
    target.append(document.createTextNode(text.slice(plainStart, cursor)));
    const source = text.slice(start, end);
    const original = text.slice(cursor, end + close.length);
    const equation = document.createElement("span");
    equation.className = display ? "preview-math-display" : "preview-math-inline";
    try {
      if (!source.trim() || source.length > MAX_EQUATION_LENGTH) throw Error("bounded_math");
      katex.render(source, equation, {
        output: "mathml", displayMode: display, throwOnError: true,
        trust: false, strict: "ignore", maxSize: 10, maxExpand: 100,
        macros: {}, globalGroup: false,
      });
    } catch (_) {
      // Do not inject parser error HTML or substitute a scientifically different formula.
      equation.textContent = original;
      equation.className = "preview-math-fallback";
      equation.title = "지원하지 않는 수식은 원문으로 표시합니다.";
    }
    target.append(equation);
    count += 1;
    cursor = end + close.length;
    plainStart = cursor;
  }
  target.append(document.createTextNode(text.slice(plainStart)));
}
