import assert from "node:assert/strict";
import {readFile, mkdir} from "node:fs/promises";
import {createRequire} from "node:module";

const require = createRequire(import.meta.url);
const {chromium} = require(process.env.EOM_WEB_PLAYWRIGHT_MODULE);
const root = new URL("../../apps/web_gui/eom_web_gui/static/", import.meta.url);
const names = ["index.html", "styles.css", "knowledge-map.css", "content-planning.css", "studio-permissions.js", "eom-mark.svg"];
const assets = new Map(await Promise.all(names.map(async name => [name, await readFile(new URL(name, root), "utf8")])));
const source = await readFile(new URL("app.js", root), "utf8");
function section(start, end) {
  const first = source.indexOf(start), last = source.indexOf(end, first);
  assert.ok(first >= 0 && last > first, `missing source boundary: ${start}`);
  return source.slice(first, last);
}
const renderer = section("function operatorRoleChoices(", "function operatorMutationBody(");
const primitives = section("function renderDefinitionList(", "function renderStages(")
  + section("function controlCard(", "function codexSlotCard(")
  + section("function addControlDetail(", "function presetRoleLabel(");
const fixture = `
import {hasPermission} from './studio-permissions.js';
const $ = selector => document.querySelector(selector);
const roleLabel = role => ({VIEWER:'조회', AUTHOR:'출제', REVIEWER:'검토', EDITOR:'편집', ADMIN:'관리자'}[role] || role);
const permissions = ['operator:assign_role','operator:revoke_role','operator:disable',
  'operator:enable','operator:revoke_sessions','operator:delete'];
const state = {operator: {operator_id:'operator_self', effective_permissions:permissions}};
function setStatus(node, tone, icon, text) {node.textContent = text;}
function setStateStatus(node, domain, state) {node.className='status-badge';node.textContent=state;}
function showMessage(node, text) {node.textContent = text;}
const calls = [], confirmations = [];
const record = (operation, ...args) => {calls.push({operation, args:structuredClone(args)});};
const assignOperatorRole = (...args) => record('assign', ...args);
const revokeOperatorRole = (...args) => record('revoke', ...args);
const disableOperatorAccount = (...args) => record('disable', ...args);
const enableOperatorAccount = (...args) => record('enable', ...args);
const revokeOperatorSessions = (...args) => record('sessions', ...args);
const deleteOperatorAccount = (...args) => record('delete', ...args);
const accounts = [
 {operator_id:'operator_self', username:'self.fixture', display_name:'현재 관리자', status:'ACTIVE', roles:['ADMIN'], resource_version:11},
 {operator_id:'operator_active', username:'active.fixture', display_name:'여러 역할을 가진 사용자', status:'ACTIVE', roles:['VIEWER','AUTHOR','REVIEWER','EDITOR','ADMIN'], resource_version:23},
 {operator_id:'operator_disabled', username:'disabled.fixture', display_name:'정지된 사용자', status:'DISABLED', roles:['VIEWER'], resource_version:37},
];
${primitives}
${renderer}
const fixture = window.accountFixture = {state, accounts, calls, confirmations, confirmed:false,
  render:() => renderOperatorAccounts(accounts)};
window.confirm = message => {confirmations.push(message);return fixture.confirmed;};
document.querySelectorAll('.view').forEach(node => node.classList.toggle('active', node.dataset.view === 'admin-settings'));
renderOperatorAccounts(accounts);
window.ready = true;
`;

const browser = await chromium.launch({headless: true});
try {
  const page = await browser.newPage({viewport:{width:1440,height:1100}, reducedMotion:"reduce"});
  const errors = [], unexpected = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/*", route => {
    const url = new URL(route.request().url());
    if (url.origin !== "https://accounts.invalid") {unexpected.push(url.pathname);return route.abort();}
    const name = url.pathname === "/studio/" ? "index.html" : url.pathname.split("/").at(-1);
    if (name === "app.js") return route.fulfill({body:fixture,contentType:"text/javascript"});
    if (!assets.has(name)) {unexpected.push(url.pathname);return route.abort();}
    return route.fulfill({body:assets.get(name),contentType:name.endsWith(".html") ? "text/html" : name.endsWith(".js") ? "text/javascript" : name.endsWith(".css") ? "text/css" : "image/svg+xml"});
  });
  await page.goto("https://accounts.invalid/studio/");
  await page.waitForFunction(() => window.ready);
  const cards = page.locator("#operator-list > .control-card");
  assert.equal(await cards.count(), 3);
  assert.equal(await cards.nth(0).locator("button, .operator-caution").count(), 0, "no self-administration actions");
  const active = cards.nth(1), disabled = cards.nth(2);
  assert.equal(await active.locator(".operator-role-actions button").isDisabled(), true, "all roles already assigned");
  assert.equal(await disabled.locator(".operator-role-actions select option").count(), 4);
  assert.equal(await page.locator(".operator-caution[open]").count(), 0, "caution sections default closed");
  assert.equal(await page.locator(".operator-caution > summary").first().textContent(), "주의가 필요한 작업");
  for (const button of await page.locator("#operator-list .button.danger").all()) {
    assert.equal(await button.isVisible(), false, "red actions are not mixed into ordinary account controls");
    assert.equal(await button.evaluate(node => Boolean(node.closest(".operator-caution"))), true);
  }
  assert.equal(await disabled.locator('[data-guide-key="operator:enable"]').isVisible(), true);
  if (process.env.EOM_GUI_SCREENSHOT_DIR) {
    await mkdir(process.env.EOM_GUI_SCREENSHOT_DIR,{recursive:true});
    await page.locator(".account-admin-panel").screenshot({path:`${process.env.EOM_GUI_SCREENSHOT_DIR}/account-default-1440.png`});
  }
  for (const width of [1440, 1024, 390]) {
    await page.setViewportSize({width, height:1100});
    await page.locator(".operator-caution").evaluateAll(nodes => nodes.forEach(node => {node.open = true;}));
    assert.equal(await active.locator(".operator-role-revocations button").count(), 5);
    assert.equal(await active.locator(".operator-security-actions button").count(), 2);
    assert.equal(await active.locator(".operator-delete-action button").count(), 1);
    assert.equal(await disabled.locator(".operator-security-actions button").count(), 1);
    const bounds = await page.evaluate(() => ({width:innerWidth,scroll:document.documentElement.scrollWidth}));
    assert.ok(bounds.scroll <= bounds.width + 1, `no page overflow at ${width}: ${JSON.stringify(bounds)}`);
    for (const card of [active, disabled]) {
      const roleBox = await card.locator(".operator-role-actions").boundingBox();
      const reasonBox = await card.locator(".operator-reason").boundingBox();
      const revokeBox = await card.locator(".operator-role-revocations").boundingBox();
      const securityBox = await card.locator(".operator-security-actions").boundingBox();
      const deleteBox = await card.locator(".operator-delete-action").boundingBox();
      assert.ok(roleBox.y + roleBox.height <= reasonBox.y, "normal roles precede caution reason");
      assert.ok(reasonBox.y + reasonBox.height <= revokeBox.y, "reason precedes destructive actions");
      assert.ok(revokeBox.y + revokeBox.height <= securityBox.y + 1, "role removal is a separate group");
      assert.ok(securityBox.y + securityBox.height <= deleteBox.y + 1, "permanent deletion is last");
      const controls = await card.locator("button, input, select").evaluateAll(nodes => nodes.map(node => {
        const box = node.getBoundingClientRect();
        return {x:box.x,right:box.right,y:box.y,bottom:box.bottom,height:box.height,label:node.textContent || node.getAttribute('aria-label') || node.tagName};
      }));
      for (const box of controls) {
        assert.ok(box.x >= 0 && box.right <= width + 1, `control stays on screen at ${width}: ${box.label}`);
        assert.ok(box.height >= 40, `control touch target at ${width}: ${box.label}`);
      }
      for (let first = 0; first < controls.length; first++) for (let next = first + 1; next < controls.length; next++) {
        const a = controls[first], b = controls[next];
        assert.ok(a.right <= b.x + 1 || b.right <= a.x + 1 || a.bottom <= b.y + 1 || b.bottom <= a.y + 1,
          `controls overlap at ${width}: ${a.label}/${b.label}`);
      }
      const reason = card.locator(".operator-reason");
      assert.ok(await reason.evaluate(node => Boolean(node.labels?.length)), "reason has an explicit label");
    }
    if (process.env.EOM_GUI_SCREENSHOT_DIR) {
      await mkdir(process.env.EOM_GUI_SCREENSHOT_DIR,{recursive:true});
      await page.screenshot({path:`${process.env.EOM_GUI_SCREENSHOT_DIR}/account-actions-${width}.png`,fullPage:true});
    }
  }

  // Existing callbacks still receive the selected account, reason and role; no real API exists.
  await active.locator('[data-guide-key="operator:revoke_role"]').first().click();
  assert.equal(await page.evaluate(() => accountFixture.calls.length), 0);
  assert.match(await page.locator("#operator-message").textContent(), /역할 해제 사유/);
  await active.locator('[data-guide-key="operator:disable"]').click();
  assert.equal(await page.evaluate(() => accountFixture.calls.length), 0);
  assert.match(await page.locator("#operator-message").textContent(), /계정 정지 사유/);
  await active.locator('[data-guide-key="operator:delete"]').click();
  assert.equal(await page.evaluate(() => accountFixture.confirmations.length), 0);
  assert.match(await page.locator("#operator-message").textContent(), /계정 삭제 사유/);
  await active.locator(".operator-reason").fill("  TEST_ONLY layout regression  ");
  await active.locator('[data-guide-key="operator:revoke_role"]').first().click();
  await active.locator('[data-guide-key="operator:disable"]').click();
  await active.locator('[data-guide-key="operator:revoke_sessions"]').click();
  await active.locator('[data-guide-key="operator:delete"]').click();
  assert.equal(await page.evaluate(() => accountFixture.calls.some(value => value.operation === 'delete')), false, "cancel prevents deletion");
  await page.evaluate(() => {accountFixture.confirmed = true;});
  await active.locator('[data-guide-key="operator:delete"]').click();
  await disabled.locator('[data-guide-key="operator:enable"]').click();
  await disabled.locator(".operator-role-actions select").selectOption("AUTHOR");
  await disabled.locator('[data-guide-key="operator:assign_role"]').click();
  const calls = await page.evaluate(() => accountFixture.calls);
  assert.deepEqual(calls.map(value => value.operation), ["revoke","disable","sessions","delete","enable","assign"]);
  for (const call of calls.slice(0,4)) assert.equal(call.args[0].operator_id,"operator_active");
  assert.equal(calls[0].args[1],"VIEWER");
  assert.equal(calls[0].args[2],"TEST_ONLY layout regression");
  assert.equal(calls[1].args[1],"TEST_ONLY layout regression");
  assert.equal(calls[3].args[1],"TEST_ONLY layout regression");
  assert.equal(calls[4].args[0].operator_id,"operator_disabled");
  assert.equal(calls[5].args[1],"AUTHOR");
  assert.match((await page.evaluate(() => accountFixture.confirmations))[0], /여러 역할을 가진 사용자.*영구 삭제/);

  await page.evaluate(() => {accountFixture.state.operator.effective_permissions = [];accountFixture.render();});
  for (const button of await cards.locator("button").all()) assert.equal(await button.isDisabled(), true);
  assert.equal(await page.locator(".operator-caution[open]").count(),0);
  assert.deepEqual(errors,[]);
  assert.deepEqual(unexpected,[]);
  console.log("operator_accounts_browser=PASS grouping reasons confirmation permissions responsive live_writes=0");
} finally {
  await browser.close();
}
