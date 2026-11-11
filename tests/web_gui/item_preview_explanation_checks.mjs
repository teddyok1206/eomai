import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {runInNewContext} from "node:vm";

// Run the production renderer; no search, authoring, source mutation or network.
const source = await readFile(new URL("../../apps/web_gui/eom_web_gui/static/app.js", import.meta.url), "utf8");
const renderer = source.slice(source.indexOf("function renderItemPreview("), source.indexOf("function renderPreviewBlock("));
class Element {
  constructor(tag) {this.tag = tag; this.children = []; this.ownText = "";}
  append(...children) {this.children.push(...children);}
  replaceChildren(...children) {this.children = children; this.ownText = "";}
  set textContent(value) {this.ownText = value ?? ""; this.children = [];}
  get textContent() {return this.ownText + this.children.map(child => child.textContent).join("");}
}
const nodes = new Map();
const $ = selector => {
  if (!nodes.has(selector)) nodes.set(selector, new Element("div"));
  return nodes.get(selector);
};
const context = {
  $, document: {createElement: tag => new Element(tag)}, state: {currentView: ""},
  setStateStatus() {}, renderDefinitionList() {}, selectHwpxDeliveryTarget() {},
  hwpxTargetFromItemPreview: () => null,
  statePresentation: (_, value) => ({label: value}),
  renderPreviewText: (node, value) => {node.textContent = value;},
  orderedItemPreviewBlocks: preview => preview.blocks,
  renderPreviewBlock: () => new Element("div"),
};
runInNewContext(renderer, context);
const explanations = [
  {statement_id: "statement_s1", text: "A의 질량과 부피로 밀도를 계산한다."},
  {statement_id: "statement_s2", text: "B의 온도는 일정하게 유지된다."},
  {statement_id: "statement_s3", text: "C의 속력이 감소하므로 이 진술은 옳지 않다."},
];
const statements = explanations.map((row, index) => ({statement_id: row.statement_id, label: "ㄱㄴㄷ"[index], text: "판단할 진술"}));
const base = {
  preview_state: "AVAILABLE", item_revision_id: "synthetic", content_profile: "BLOCKS_V1",
  answer: "③", authoring_intent: "평가할 개념", concept_source: "개념 출처",
  choices: [{label: "①", text: "선택지"}],
  blocks: [{type: "statement_set", statements}],
  explanation: "세 진술의 공통 계산을 먼저 수행한다.",
  statement_explanations: explanations,
};
function render(preview) {
  const before = JSON.stringify(preview);
  context.renderItemPreview(preview);
  assert.equal(JSON.stringify(preview), before, "rendering must preserve all canonical and structured values");
  assert.equal($("#preview-explanation").textContent, preview.explanation);
  return $("#preview-explanation").textContent + $("#preview-statement-explanations").textContent;
}
function assertStandalone() {
  const text = render(base);
  assert.equal($("#preview-statement-explanations").children.length, 3);
  for (const row of explanations) assert.equal(text.split(row.text).length - 1, 1);
  assert(text.includes(base.explanation), "BLOCKS_V1 keeps its independent overview");
}
assertStandalone();
for (const profile of ["CONTENT_TEAM_V2", "CONTENT_TEAM_V3"]) {
  for (const allCorrect of [false, true]) {
    const correct = allCorrect ? explanations : explanations.slice(0, 2);
    const explanation = [base.explanation, ...correct.map((row, index) => `${"ㄱㄴㄷ"[index]}. ${row.text}`),
      ...(allCorrect ? [] : ["오답 해설", `ㄷ. ${explanations[2].text}`])].join("\n\n");
    const text = render({...base, content_profile: profile, explanation});
    assert.equal($("#preview-statement-explanations").children.length, 0,
      "content-team keeps full sections and clears prior standalone rows");
    for (const row of explanations) assert.equal(text.split(row.text).length - 1, 1);
    assert.equal(text.includes("오답 해설"), !allCorrect);
    assertStandalone(); // Switching back must not suppress independent V1 explanations.
  }
  const direct = {...base, content_profile: profile, blocks: [], statement_explanations: [],
    explanation: "정답 선택지의 근거이다.\n\n오답 해설\n나머지 선택지는 조건과 다르다."};
  assert.equal(render(direct), direct.explanation, "non-combination sections remain intact");
  assert.equal($("#preview-statement-explanations").children.length, 0);
}
console.log("item_preview_explanations=PASS content-team-once/legacy-preserved/profile-switch/immutable-dto");
