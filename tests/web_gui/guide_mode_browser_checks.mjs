import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {createRequire} from "node:module";

const require = createRequire(import.meta.url);
const {chromium} = require(process.env.EOM_WEB_PLAYWRIGHT_MODULE);
const root = new URL("../../apps/web_gui/eom_web_gui/static/", import.meta.url);
const names = ["index.html", "styles.css", "guide-mode.js", "guide-content.js", "eom-mark.svg"];
const assets = new Map(await Promise.all(names.map(async name => [name, await readFile(new URL(name, root), "utf8")])));
const browser = await chromium.launch({headless: true});
try {
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const requests = [];
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("https://guide.invalid/**", route => {
    const url = new URL(route.request().url());
    if (url.pathname === "/studio") return route.fulfill({contentType: "text/html", body: assets.get("index.html")});
    const name = url.pathname.split("/").at(-1);
    if (name === "app.js") return route.fulfill({contentType: "text/javascript", body: 'import {installGuideMode} from "./guide-mode.js"; installGuideMode(); window.guideReady=true;'});
    const body = assets.get(name);
    if (!body) {requests.push(url.pathname); return route.abort();}
    return route.fulfill({body, contentType: name.endsWith("js") ? "text/javascript" : name.endsWith("css") ? "text/css" : "image/svg+xml"});
  });
  await page.goto("https://guide.invalid/studio");
  await page.waitForFunction(() => window.guideReady);
  page.setDefaultTimeout(5000);
  await page.evaluate(() => {
    document.querySelector('[data-view="request"]').classList.add("active");
    window.clicks = 0; window.submits = 0;
    const save = document.querySelector("#draft-save");
    // This fixture installs only help, not authenticated application handlers.
    save.disabled = false;
    save.addEventListener("click", () => {window.clicks++;});
    document.querySelector("#draft-form").addEventListener("submit", event => {event.preventDefault();window.submits++;});
    document.querySelector("#draft-form").noValidate = true;
    const submit = document.createElement("button");submit.type="submit";
    submit.id="native-guide-test-submit";submit.textContent="Submit fixture";
    document.querySelector("#draft-form").append(submit);
  });
  const popup = page.locator("#guide-tooltip");
  const toggle = page.locator("#guide-mode-toggle");
  const box = () => page.locator("#request-text").evaluate(node => {
    const rect = node.getBoundingClientRect();
    // Focusing a lower form action may legitimately scroll without changing layout.
    return {x: rect.x + scrollX, y: rect.y + scrollY, width: rect.width, height: rect.height};
  });
  const before = await box();
  const controlMarkup = await page.locator("#draft-save").evaluate(node => node.outerHTML);
  assert.equal(await toggle.getAttribute("aria-checked"), "false");
  for (const id of ["global-load", "logout"]){
    assert.equal(await page.locator('#'+id).evaluate(node=>getComputedStyle(node).whiteSpace),"nowrap");
  }
  await page.locator("#draft-save").hover();
  await page.locator("#request-text").focus();
  assert.equal(await popup.isVisible(), false);
  assert.equal(await page.locator("#request-text").getAttribute("aria-describedby"), null);
  await toggle.click();
  assert.equal(await toggle.getAttribute("aria-checked"), "true");
  await page.locator("#draft-save").scrollIntoViewIfNeeded();
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await page.locator("#draft-save").hover();
  await popup.waitFor({state: "visible"});
  assert.equal(await page.locator("#guide-tooltip-title").textContent(), "초안 저장");
  assert.match(await popup.textContent(), /저장만으로 문항 제작이 시작되지는/);
  assert.equal(await page.locator("#draft-save").getAttribute("aria-describedby"), "guide-tooltip");
  assert.deepEqual(await box(), before, "help must not shift the form");
  await popup.hover();
  await page.waitForTimeout(150);
  assert.equal(await popup.isVisible(), true, "tooltip must be hoverable");
  await page.keyboard.press("Escape");
  assert.equal(await popup.isVisible(), false);
  await page.locator("#draft-save").click();
  assert.equal(await page.evaluate(() => window.clicks), 1, "mode must not intercept the action");

  // Existing ARIA and disabled-control semantics are preserved.
  await page.evaluate(() => document.querySelector("#draft-submit").disabled = true);
  await page.locator("#draft-submit").scrollIntoViewIfNeeded();
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await page.locator("#draft-submit").hover();
  await popup.waitFor({state: "visible"});
  assert.match(await popup.textContent(), /여러 번 보내지/);
  assert.equal(await page.locator("#draft-submit").isDisabled(), true);
  const target = page.locator("#workflow-hwpx-continue");
  await page.evaluate(() => {
    document.querySelector('[data-view="request"]').classList.remove("active");
    document.querySelector('[data-view="workflow"]').classList.add("active");
  });
  await target.hover();
  await popup.waitFor({state: "visible"});
  assert.equal(await target.getAttribute("aria-describedby"), "workflow-hwpx-message guide-tooltip");
  await page.keyboard.press("Escape");
  assert.equal(await target.getAttribute("aria-describedby"), "workflow-hwpx-message");

  // Delegation covers controls that appear after installation and never reads their text as HTML.
  await page.evaluate(() => {
    document.querySelector('[data-view="workflow"]').classList.remove("active");
    document.querySelector('[data-view="dashboard"]').classList.add("active");
    const button = document.createElement("button");button.type="button";
    button.textContent='<img src="invalid" onerror="window.injected=true">';
    button.id="dynamic-inbox-button";document.querySelector("#work-inbox").append(button);
  });
  await page.locator("#dynamic-inbox-button").hover();
  await popup.waitFor({state: "visible"});
  assert.equal(await page.locator("#guide-tooltip-title").textContent(), "이어 할 작업");
  assert.equal(await popup.locator("img").count(), 0);
  assert.equal(await page.evaluate(() => Boolean(window.injected)), false);
  await page.locator('.nav-item[data-view-target="request"]').hover();
  await popup.waitFor({state: "visible"});
  assert.equal(await page.locator("#guide-tooltip-title").textContent(), "새 문항 요청");
  await page.locator('.nav-item[data-view-target="request"]').click();
  assert.equal(await popup.isVisible(), false, "navigation must dismiss old help");

  // Hidden controls never gain visibility; newly rendered account actions use static copy.
  await page.evaluate(() => {
    const hidden = document.createElement("div");hidden.hidden=true;
    const action = document.createElement("button");action.dataset.guideKey="operator:delete";
    action.id="hidden-account-action";hidden.append(action);document.body.append(hidden);
  });
  await page.locator("#hidden-account-action").dispatchEvent("pointerover", {pointerType:"mouse"});
  assert.equal(await popup.isVisible(), false);
  assert.equal(await page.locator("#hidden-account-action").isVisible(), false);
  await page.evaluate(() => {
    const button = document.createElement("button");button.type="button";
    button.id="dynamic-account-action";button.dataset.guideKey="operator:delete";
    button.disabled=true;button.textContent="Account fixture";document.querySelector("#work-inbox").append(button);
  });
  await page.locator("#dynamic-account-action").hover();
  await popup.waitFor({state: "visible"});
  assert.match(await popup.textContent(), /로그인 정보는 되살릴 수 없습니다/);
  assert.equal(await page.locator("#dynamic-account-action").isDisabled(), true);
  await page.keyboard.press("Escape");

  // Focus works without mouse movement. OFF cleans up and changes no form behavior.
  await page.evaluate(() => {
    document.querySelector('[data-view="dashboard"]').classList.remove("active");
    document.querySelector('[data-view="request"]').classList.add("active");
  });
  await page.locator('#draft-form [name="material_form"]').focus();
  await popup.waitFor({state: "visible"});
  assert.match(await popup.textContent(), /표만 있는 문항도 괜찮/);
  await page.locator("#native-guide-test-submit").click();
  assert.equal(await page.evaluate(() => window.submits), 1);
  await toggle.click();
  assert.equal(await popup.isVisible(), false);
  assert.equal(await page.locator("#guide-tooltip-description").textContent(), "");
  assert.equal(await page.locator('[aria-describedby~="guide-tooltip"]').count(), 0);
  assert.equal(await page.locator("#draft-save").evaluate(node => node.outerHTML), controlMarkup);
  await page.evaluate(() => window.scrollTo(0, 0));
  assert.deepEqual(await box(), before);
  await page.locator("#draft-save").click();
  assert.equal(await page.evaluate(() => window.clicks), 2);
  await page.locator("#native-guide-test-submit").click();
  assert.equal(await page.evaluate(() => window.submits), 2);

  // Window-edge placement on small screens, scroll/resize dismissal, reload defaults.
  await page.setViewportSize({width: 390, height: 650});
  await toggle.click();
  await page.locator("#request-text").focus();
  await popup.waitFor({state: "visible"});
  const bounds = await popup.boundingBox();
  assert.ok(bounds.x >= 0 && bounds.y >= 0 && bounds.x + bounds.width <= 390 && bounds.y + bounds.height <= 650);
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= 390), "header must fit mobile viewport");
  await page.setViewportSize({width: 320, height: 650});
  await popup.waitFor({state: "hidden"});
  assert.equal(await popup.isVisible(), false);
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= 320));
  await page.locator("#request-text").dispatchEvent("pointerover", {pointerType:"touch"});
  assert.equal(await popup.isVisible(), false, "touch must not simulate a sticky hover");
  await page.locator("#draft-save").scrollIntoViewIfNeeded();
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await page.locator("#draft-save").focus();
  await popup.waitFor({state: "visible"});
  await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
  assert.equal(await popup.isVisible(), false);
  await page.reload();await page.waitForFunction(() => window.guideReady);
  assert.equal(await toggle.getAttribute("aria-checked"), "false");
  assert.equal(await popup.isVisible(), false);
  assert.deepEqual(requests, []);assert.deepEqual(errors, []);
  assert.equal(await page.evaluate(() => localStorage.length + sessionStorage.length), 0);
  console.log("guide_mode_browser=PASS");
} finally {
  await browser.close();
}
