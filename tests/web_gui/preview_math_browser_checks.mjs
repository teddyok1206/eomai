import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {createRequire} from "node:module";

const require = createRequire(import.meta.url);
const {chromium} = require(process.env.EOM_WEB_PLAYWRIGHT_MODULE);
const staticRoot = new URL("../../apps/web_gui/eom_web_gui/static/", import.meta.url);
const sources = new Map(await Promise.all([
  "preview-math.js", "vendor-katex-0.19.0.js", "item-preview.js",
].map(async name => [name, await readFile(new URL(name, staticRoot), "utf8")])));
const app = await readFile(new URL("app.js", staticRoot), "utf8");
const controller = app.slice(app.indexOf("function renderItemPreview("), app.indexOf("function installStructuredImport("))
  + app.slice(app.indexOf("function buildDocumentTable("), app.indexOf("async function loadHwpx("));
const browser = await chromium.launch({headless: true});
try {
  const page = await browser.newPage();
  const requests = [];
  const errors = [];
  page.on("request", request => requests.push(request.url()));
  page.on("pageerror", error => errors.push(error.message));
  await page.route("https://preview.invalid/assets/*", route => {
    const body = sources.get(new URL(route.request().url()).pathname.split("/").pop());
    return route.fulfill({status: body ? 200 : 404, body: body || "", contentType: "text/javascript",
      headers: {"Access-Control-Allow-Origin": "*"}});
  });
  await page.setContent("<!doctype html><div id='fixture'></div><div id='plain'></div>");
  await page.addStyleTag({content: await readFile(new URL("styles.css", staticRoot), "utf8")});
  await page.evaluate(async () => {
    window.renderPreviewText = (await import("https://preview.invalid/assets/preview-math.js")).renderPreviewText;
    const preview = await import("https://preview.invalid/assets/item-preview.js");
    window.orderedItemPreviewBlocks = preview.orderedItemPreviewBlocks;
    window.formatEquationSource = preview.formatEquationSource;
  });
  const render = async source => page.evaluate(source => {
    const root = document.querySelector("#fixture");
    renderPreviewText(root, source);
    return {text: root.textContent, maths: root.querySelectorAll("math").length,
      fractions: root.querySelectorAll("mfrac").length, scripts: root.querySelectorAll("msub,msup,msubsup").length,
      fallback: root.querySelectorAll(".preview-math-fallback").length,
      dangerous: root.querySelectorAll("a,img,script,iframe,[href],[src],[onerror]").length,
      display: root.querySelector("math")?.getAttribute("display")};
  }, source);
  let result = await render(String.raw`속력 $v=\frac{2d}{t}$, 가속도 $a_1=3\times10^{2}$이다.`);
  assert.equal(result.maths, 2);
  assert.equal(result.fractions, 1);
  assert(result.scripts >= 2);
  assert.equal(result.fallback, 0);
  assert.match(result.text, /^속력 /);
  assert.match(result.text, /이다\.$/);
  for (const source of [String.raw`$$\frac{a}{b+c}$$`, String.raw`\[\sqrt{x^2+1}\]`]) {
    result = await render(source);
    assert.equal(result.maths, 1);
    assert.equal(result.display, "block");
    assert.equal(result.fallback, 0);
  }
  assert.equal((await render(String.raw`값 \(x_1^2\)이다.`)).maths, 1);
  for (const source of ["일반 문장 2 < 3", "$a", "가격 $10, 가격 $20", String.raw`비용 \$10, \$20`, "a_b^2"]) {
    result = await render(source);
    assert.equal(result.text, source, "plain/currency/unmatched text is never rewritten");
    assert.equal(result.maths, 0);
  }
  for (const source of [String.raw`$\invalidcmd{x}$`, String.raw`$\frac{1}{2$`, "$" + "a".repeat(4001) + "$"]) {
    result = await render(source);
    assert.equal(result.text, source);
  }
  for (const source of [
    String.raw`$\href{https://unsafe.invalid}{x}$`, String.raw`$\includegraphics{https://unsafe.invalid/pixel}$`,
    String.raw`$\htmlClass{injected}{x}$`, '$\\text{<img src=x onerror="alert(1)">}$',
    '<script>window.injected=true</script><img src="https://unsafe.invalid/pixel">',
  ]) {
    result = await render(source);
    assert.equal(result.dangerous, 0);
  }
  result = await render(String.raw`$\gdef\leak{x}x$ $\leak$`);
  assert.equal(result.fallback, 1, "macros are isolated per expression");
  result = await render(String.raw`$\def\loop{\loop}\loop$`);
  assert.equal(result.fallback, 1, "recursive macro expansion is bounded");
  result = await render(Array.from({length: 200}, () => "$x$").join(" "));
  assert.equal(result.maths, 128);
  const long = "$x$ " + "본문".repeat(24000);
  result = await render(long);
  assert.equal(result.text, long);
  assert.equal(result.maths, 0);

  // Run the actual preview controller, including every authored text surface.
  await page.evaluate(source => {
    const root = document.querySelector("#plain");
    for (const id of ["revision-state", "item-inspector", "structured-base-revision", "structured-revision-etag",
      "item-hwpx-continue", "preview-page-state", "preview-empty", "preview-content", "preview-item-number",
      "preview-title", "preview-score", "preview-answer", "preview-explanation", "preview-authoring-intent",
      "preview-concept-source", "preview-blocks", "preview-choices", "preview-statement-explanations"]) {
      const node = document.createElement("div"); node.id = id; root.append(node);
    }
    window.$ = selector => document.querySelector(selector);
    window.state = {currentView: ""};
    window.setStateStatus = window.renderDefinitionList = window.selectHwpxDeliveryTarget = () => {};
    window.hwpxTargetFromItemPreview = () => null;
    window.statePresentation = (_, value) => ({label: value});
    window.eval(source);
    const math = String.raw`$v=\frac{d}{t}$`;
    const preview = {schema_version: "4.0", preview_state: "AVAILABLE", item_revision_id: "synthetic",
      title: math, answer: math, explanation: math, authoring_intent: math, concept_source: math,
      choices: [{label: "①", text: math}], statement_explanations: [{statement_id: "g", text: math}],
      blocks: [
        {block_id: "paragraph", type: "paragraph", purpose: "stem", text: math},
        {block_id: "material", type: "labeled_text", kind: "DATA", label: "", text: math},
        {block_id: "inquiry", type: "inquiry", kind: "탐구", goal: math, procedure: math, result: math},
        {block_id: "table", type: "table", caption: math, headers: [math], rows: [[math]]},
        {block_id: "claims", type: "statement_set", statements: [{statement_id: "g", label: "ㄱ", text: math}]},
        {block_id: "latex-equation", type: "equation", source: math},
        {block_id: "hancom-equation", type: "equation", source: "a^2+b_1=2"},
      ]};
    window.before = JSON.stringify(preview);
    renderItemPreview(preview);
    window.canonicalUnchanged = before === JSON.stringify(preview);
  }, controller);
  assert.equal(await page.locator("#plain math").count(), 17);
  assert.equal(await page.locator("#plain mfrac").count(), 17);
  assert.equal(await page.locator("#plain .equation-display").last().textContent(), "a²+b₁=2");
  assert.equal(await page.evaluate(() => canonicalUnchanged), true);
  assert.deepEqual(errors, []);
  assert(requests.every(url => url.startsWith("https://preview.invalid/assets/")), "no external resource loads");
  console.log("preview_math_browser=PASS inline/display/fields/security/bounds/immutable-content");
} finally {
  await browser.close();
}
