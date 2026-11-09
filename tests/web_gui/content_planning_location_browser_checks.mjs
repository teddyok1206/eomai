import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {createServer} from "node:http";
import {createRequire} from "node:module";

const require = createRequire(import.meta.url);
const {chromium} = require(process.env.EOM_WEB_PLAYWRIGHT_MODULE);
const root = new URL("../../apps/web_gui/eom_web_gui/static/", import.meta.url);
const names = ["index.html", "styles.css", "content-planning.css", "content-planning.js",
  "content-planning-draft.js", "content-planning-location.js", "content-planning-pending.js", "content-planning-copy.js", "content-planning-lifecycle.js", "content-planning-destination.js", "studio-route.js",
  "item-db-delivery.js", "knowledge-map.css", "eom-mark.svg"];
const assets = new Map(await Promise.all(names.map(async name => [name, await readFile(new URL(name, root), "utf8")])));
const id = (prefix, n = 1) => `${prefix}_${n.toString(16).padStart(32, "0")}`;
const selection = {view: "excel", deliverable_id: id("deliverable"), edition_id: id("edition"),
  deliverable_revision_id: id("delivrev"), section_id: id("section", 2)};
const app = `
import {createContentPlanning} from './content-planning.js';
import {studioRouteFromLocation, updateStudioHistory} from './studio-route.js';
const id = (prefix, n = 1) => prefix + '_' + n.toString(16).padStart(32, '0');
const sha = 'sha256:' + 'a'.repeat(64);
const f = window.fixture = {calls: [], routeWrites: [], actor: 'owner-a', delay: false, release: null, wrong: false, ready: false};
const sections = [1, 2].map(n => ({section_id: id('section', n), parent_id: null, kind: 'FORM',
  ordinal: n, label: n + '회차', numbering: 'RESET_PER_SECTION', form: {form_id: id('form', n),
  form_revision_id: id('formrev', n), form_sha256: sha, assembly_id: id('assembly', n),
  assembly_revision_id: id('assemblyrev', n), manifest_sha256: sha, placement_count: 1}}));
const composition = n => ({schema_version: 'content-edition-composition/1.0', deliverable_id: id('deliverable'),
  edition_id: id('edition'), deliverable_revision_id: id('delivrev', n), previous_revision_id: null,
  content_title: '복원 확인용', content_type: 'OTHER', edition_label: '2027 초판', academic_year: 2027,
  revision_number: n, composition_sha256: sha, created_by: id('operator'), created_at: '2026-11-09T00:00:00Z',
  sections: structuredClone(sections)});
async function api(path, options) {
  const b = options.body; f.calls.push({path, body: structuredClone(b), actor: f.actor});
  if (b.query_kind === 'LIST_CONTENTS') return {rows: [{deliverable_id: id('deliverable'), title: '복원 확인용', content_type: 'OTHER'}], next_id: null};
  if (b.query_kind === 'LIST_EDITIONS') return {rows: [{edition_id: id('edition'), edition_label: '2027 초판'}], next_id: null};
  if (b.query_kind === 'READ_EDITION') {
    if (f.delay) {f.delay = false; await new Promise(resolve => f.release = resolve);}
    if (b.edition_id !== id('edition') || ![null, id('delivrev'), id('delivrev', 2)].includes(b.revision_id)) throw new Error('지정된 저장본을 조회할 수 없습니다.');
    const n = f.wrong || b.revision_id === null || b.revision_id === id('delivrev', 2) ? 2 : 1;
    return {composition: composition(n), current_revision_id: id('delivrev', 2)};
  }
  if (b.query_kind === 'READ_SECTION') return {rows: [{placement_id: id('placement'), position: 1,
    target: {placement_kind: 'EMPTY'}, points_milli: null, display_number: null, note: '', copied_from: null}], next_position: null};
  if (b.query_kind === 'USAGE_SUMMARY') return {rows: []};
  throw new Error('Unexpected query or mutation: ' + path + ' ' + b.query_kind);
}
const c = f.controller = createContentPlanning({document, api, can: () => true, openItemDb: () => {},
  openTarget: () => {}, confirm: () => true, onSelectionChange: route => {f.routeWrites.push(route); updateStudioHistory(window, route, {replace: true});}});
c.install(); c.setOwner(f.actor); c.open();
document.querySelectorAll('.view').forEach(v => v.classList.toggle('active', v.dataset.view === 'excel'));
await c.restoreLocation(studioRouteFromLocation(window.location)); f.ready = true;
`;
const server = createServer((request, response) => {
  const name = (request.url || "").split("?")[0].split("/").pop() || "index.html";
  const content = name === "app.js" ? app : assets.get(name);
  if (content === undefined) {response.writeHead(404); response.end(); return;}
  response.setHeader("Content-Type", name.endsWith(".js") ? "text/javascript" : name.endsWith(".css") ? "text/css" : name.endsWith(".svg") ? "image/svg+xml" : "text/html");
  response.end(content);
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const browser = await chromium.launch({headless: true});
try {
  const page = await browser.newPage(), errors = [];
  page.on("pageerror", error => errors.push(error.message));
  const url = route => `http://127.0.0.1:${server.address().port}/studio/?${new URLSearchParams(route)}`;
  async function visit(route) {await page.goto(url(route)); await page.waitForFunction(() => window.fixture?.ready);}
  await visit(selection);
  assert.equal(await page.locator("#excel-section-title").textContent(), "2회차");
  assert.match(await page.locator("#excel-version").textContent(), /과거 저장본.*1차/);
  assert.equal(await page.locator("#excel-rows tr").count(), 1);
  let reads = await page.evaluate(() => fixture.calls.filter(c => c.body.query_kind === 'READ_EDITION'));
  assert.equal(reads.length, 1);
  assert.equal(reads[0].body.revision_id, selection.deliverable_revision_id);
  assert.equal(reads[0].actor, "owner-a");
  await page.locator("#excel-sections button").first().click();
  await page.waitForFunction(() => new URLSearchParams(location.search).get('section_id').endsWith('1'));
  await page.reload(); await page.waitForFunction(() => window.fixture?.ready);
  assert.equal(await page.locator("#excel-section-title").textContent(), "1회차");
  assert.match(await page.locator("#excel-version").textContent(), /과거 저장본.*1차/);
  assert.equal(await page.locator("#excel-empty-slot").isDisabled(), true, "historical URL became current editable revision");

  // Missing exact section/revision and malformed pointers never fall back to the first/latest.
  await visit({...selection, section_id: id("section", 99)});
  assert.match(await page.locator("#excel-message").textContent(), /회차가 이 저장본에 없습니다/);
  assert.equal(await page.locator("#excel-editor").isVisible(), false);
  assert.equal(await page.evaluate(() => fixture.calls.filter(c => c.body.query_kind === 'READ_SECTION').length), 0);
  await visit({...selection, deliverable_id: id("deliverable", 99)});
  assert.match(await page.locator("#excel-message").textContent(), /저장본과 조회 결과가 다릅니다/);
  await visit({...selection, deliverable_revision_id: id("delivrev", 99)});
  assert.match(await page.locator("#excel-message").textContent(), /지정된 저장본을 조회할 수 없습니다/);
  reads = await page.evaluate(() => fixture.calls.filter(c => c.body.query_kind === 'READ_EDITION'));
  assert.equal(reads.length, 1); assert.equal(reads[0].body.revision_id, id("delivrev", 99));
  await visit({...selection, edition_id: "https://example.test/private"});
  assert.match(await page.locator("#excel-message").textContent(), /콘텐츠 주소가 올바르지 않습니다/);
  assert.equal(await page.evaluate(() => fixture.calls.filter(c => c.body.query_kind === 'READ_EDITION').length), 0);

  await visit(selection);
  await page.evaluate(async route => {fixture.wrong = true; await fixture.controller.restoreLocation(route);}, selection);
  assert.match(await page.locator("#excel-message").textContent(), /저장본과 조회 결과가 다릅니다/);
  assert.match(await page.locator("#excel-version").textContent(), /과거 저장본.*1차/, "failed read destroyed prior saved view");

  // Changing owner invalidates late reads and clears the previous owner's rendered content.
  await visit(selection);
  const writes = await page.evaluate(() => fixture.routeWrites.length);
  await page.evaluate(route => {fixture.delay = true; fixture.waiting = fixture.controller.restoreLocation(route);}, selection);
  await page.waitForFunction(() => fixture.release !== null);
  await page.evaluate(async () => {fixture.actor = 'owner-b'; fixture.controller.setOwner(fixture.actor); fixture.release(); await fixture.waiting;});
  assert.equal(await page.locator("#excel-editor").isVisible(), false);
  assert.equal(await page.locator("#excel-rows tr").count(), 0);
  assert.equal(await page.evaluate(() => fixture.routeWrites.length), writes);
  await page.evaluate(route => fixture.controller.restoreLocation(route), selection);
  reads = await page.evaluate(() => fixture.calls.filter(c => c.body.query_kind === 'READ_EDITION'));
  assert.equal(reads.at(-1).actor, "owner-b", "new owner reused the old owner's data");
  assert.equal(await page.locator("#excel-section-title").textContent(), "2회차");

  // Leaving Excel while a read finishes must not steal the current route.
  await page.evaluate(route => {fixture.release = null; fixture.delay = true; fixture.waiting = fixture.controller.restoreLocation(route);}, selection);
  await page.waitForFunction(() => fixture.release !== null);
  const writesBeforeLeaving = await page.evaluate(() => fixture.routeWrites.length);
  await page.evaluate(async () => {fixture.controller.close(); history.replaceState({view: 'dashboard'}, '', '/studio/'); fixture.release(); await fixture.waiting;});
  assert.equal(new URL(page.url()).search, "");
  assert.equal(await page.evaluate(() => fixture.routeWrites.length), writesBeforeLeaving);
  assert.equal(await page.evaluate(() => localStorage.length + sessionStorage.length), 0);
  assert.equal(await page.evaluate(() => fixture.calls.some(c => c.path !== '/content-planning/query')), false);
  assert.deepEqual(errors, []);
  console.log("CONTENT_PLANNING_LOCATION_BROWSER=PASS reload/history/missing/owner/background live_writes=0");
} finally {await browser.close(); server.close();}
