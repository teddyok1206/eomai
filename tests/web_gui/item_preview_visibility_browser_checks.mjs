import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {createRequire} from "node:module";

const require = createRequire(import.meta.url);
const {chromium} = require(process.env.EOM_WEB_PLAYWRIGHT_MODULE);
const staticRoot = new URL("../../apps/web_gui/eom_web_gui/static/", import.meta.url);
const css = await readFile(new URL("styles.css", staticRoot), "utf8");
const app = await readFile(new URL("app.js", staticRoot), "utf8");
const handlers = app.slice(
  app.indexOf("async function loadItemPreview()"),
  app.indexOf("function renderPreviewBlock("),
);
const browser = await chromium.launch({headless: true});
try {
  const page = await browser.newPage();
  await page.setContent(`
    <input id="item-id"><input id="revision-id">
    <input id="structured-base-revision"><input id="structured-revision-etag">
    <button id="item-hwpx-continue"></button><div id="revision-state"></div>
    <dl id="item-inspector"></dl><div id="preview-page-state"></div>
    <div id="preview-empty" class="document-empty"><div><strong></strong><p></p></div></div>
    <div id="preview-content" hidden>
      <span id="preview-item-number"></span><h2 id="preview-title"></h2>
      <span id="preview-score"></span><span id="preview-answer"></span>
      <div id="preview-explanation"></div><div id="preview-authoring-intent"></div>
      <div id="preview-concept-source"></div><div id="preview-blocks"></div>
      <ol id="preview-choices"></ol><div id="preview-statement-explanations"></div>
    </div>`);
  await page.addStyleTag({content: css});
  await page.evaluate(source => {
    window.$ = selector => document.querySelector(selector);
    window.state = {itemPreviewRequestSequence: 0, currentView: ""};
    window.pending = [];
    window.api = () => new Promise((resolve, reject) => pending.push({resolve, reject}));
    window.selectHwpxDeliveryTarget = target => {window.deliveryTarget = target;};
    window.setStatus = window.setStateStatus = window.renderDefinitionList = () => {};
    window.hwpxTargetFromItemPreview = preview => ({itemRevisionId: preview.item_revision_id});
    window.statePresentation = (_, value) => ({label: value});
    window.orderedItemPreviewBlocks = preview => preview.blocks;
    window.toast = message => {window.lastToast = message;};
    window.eval(source);
    window.available = revision => ({preview_state: "AVAILABLE", item_revision_id: revision,
      revision_etag: `"${revision}"`, title: revision, blocks: [], choices: [],
      statement_explanations: []});
  }, handlers);
  const start = async (id, promiseName) => page.evaluate(({id, promiseName}) => {
    $("#item-id").value = id;
    $("#revision-id").value = id;
    window[promiseName] = loadItemPreview();
  }, {id, promiseName});
  const visibility = () => page.evaluate(() => ({
    empty: $("#preview-empty").getBoundingClientRect().height > 0,
    content: getComputedStyle($("#preview-content")).display !== "none",
    title: $("#preview-title").textContent,
    revision: $("#structured-base-revision").value,
    target: window.deliveryTarget,
  }));
  await start("A", "first");
  assert.equal((await visibility()).empty, true);
  assert.equal((await visibility()).content, false);
  await page.evaluate(async () => {pending[0].resolve(available("A")); await first;});
  let view = await visibility();
  assert.equal(view.empty, false, "completed preview must remove the 700px loading area");
  assert.equal(view.content, true);
  assert.equal(view.revision, "A");

  await start("B", "second");
  await start("C", "third");
  await page.evaluate(async () => {pending[2].resolve(available("C")); await third;});
  await page.evaluate(async () => {pending[1].resolve(available("B")); await second;});
  view = await visibility();
  assert.equal(view.empty, false);
  assert.equal(view.title, "C", "late response must not replace the selected preview");
  assert.equal(view.revision, "C");
  assert.equal(view.target.itemRevisionId, "C");

  await start("D", "fourth");
  await page.evaluate(async () => {pending[3].reject(new Error("UNAVAILABLE")); await fourth;});
  view = await visibility();
  assert.equal(view.empty, true, "failed preview must still show its actionable error");
  assert.equal(view.content, false);
  assert.equal(view.revision, "");
  assert.equal(view.target, null);
  assert.match(await page.locator("#preview-empty strong").textContent(), /조회 실패/);

  await start("E", "fifth");
  await page.evaluate(async () => {pending[4].resolve(available("E")); await fifth;});
  assert.equal((await visibility()).empty, false, "recovery must clear the error area");
  await start("F", "sixth");
  await page.evaluate(async () => {
    pending[5].resolve({...available("F"), preview_state: "UNSUPPORTED"}); await sixth;
  });
  assert.equal((await visibility()).empty, true);
  assert.match(await page.locator("#preview-empty strong").textContent(), /지원하지 않는/);

  for (const className of ["document-empty", "chat-welcome", "nav-item", "work-inbox"]) {
    const layout = await page.evaluate(className => {
      const node = document.createElement("div");
      node.className = className;
      document.body.append(node);
      node.hidden = true;
      const hidden = getComputedStyle(node).display;
      node.hidden = false;
      const shown = getComputedStyle(node).display;
      node.remove();
      return {hidden, shown};
    }, className);
    assert.equal(layout.hidden, "none", `${className} must respect hidden state`);
    assert.notEqual(layout.shown, "none", `${className} must retain its intended layout`);
  }
  console.log("item_preview_visibility_browser=PASS");
} finally {
  await browser.close();
}
