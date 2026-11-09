import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {createServer} from "node:http";
import {createRequire} from "node:module";
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.EOM_WEB_PLAYWRIGHT_MODULE);
const root = new URL("../../apps/web_gui/eom_web_gui/static/", import.meta.url);
const names = ["index.html", "styles.css", "content-planning.css", "content-planning.js", "content-planning-draft.js", "item-db-delivery.js", "knowledge-map.css", "eom-mark.svg"];
const assets = new Map(await Promise.all(names.map(async name => [name, await readFile(new URL(name, root), "utf8")])));
const app = `
import {createContentPlanning} from './content-planning.js';
const f = window.fixture = {calls: [], composition: null, rows: new Map(), fail: false, held: null, release: null, printed: [], dbOpens: 0};
const id = (p, n = 1) => p + '_' + n.toString(16).padStart(32, '0'), sha = 'sha256:' + 'a'.repeat(64);
let revision = 0;
function publish(value) {
  revision++; f.composition = {...value, deliverable_revision_id: id('delivrev', revision), revision_number: revision, composition_sha256: sha};
  return {schema_version: 'content-planning-write-result/1.0', disposition: 'SAVED', replayed: false, composition: structuredClone(f.composition), current_revision_id: f.composition.deliverable_revision_id};
}
async function api(path, options = {}) {
  f.calls.push({path, body: structuredClone(options.body), key: options.headers?.['Idempotency-Key']});
  const b = options.body || {};
  if (path.includes('/hwpx-builds')) {
    if (path.includes('/latest?')) return f.build || null;
    if (options.method === 'POST') {
      f.buildSubmissions = (f.buildSubmissions || 0) + 1;
      f.build = {schema_version: 'curated-hwpx-build-view/2.0', build_id: id('hwpxbuild'), assembly_id: f.prepared.assembly_id,
        assembly_revision_id: f.prepared.assembly_revision_id, state: 'SUCCEEDED', validation_state: 'PASS', placement_count: 1200,
        section_count: 1200, output_sha256: sha, output_size_bytes: 1000, failure_code: null, resource_version: 3,
        created_at: '2026-11-09T12:00:00Z', completed_at: '2026-11-09T12:01:00Z', download_available: true};
    }
    return f.build;
  }
  if (path.endsWith('/deliveries')) {
    f.prepared = {schema_version: 'content-delivery-prepared/1.0', edition_id: b.edition_id,
      revision_id: b.revision_id, composition_sha256: b.composition_sha256, scope_sha256: sha,
      assembly_id: id('assembly', 99), assembly_revision_id: id('assemblyrev', 99), manifest_sha256: sha,
      placement_count: 1200, created_at: '2026-11-09T12:00:00Z', replayed: false};
    return f.prepared;
  }
  if (b.query_kind === 'DELIVERIES') return {result_kind: 'DELIVERIES', edition_id: b.edition_id,
    rows: f.prepared ? [{prepared: f.prepared, section_labels: ['1회차'], section_count: 1, matches_current_revision: true}] : [], next_id: null};
  if (f.held === b.query_kind) {f.held = null; await new Promise(r => f.release = r);}
  if (path.endsWith('/commands')) {
    if (f.fail) {f.fail = false; throw new Error('합성 응답 지연');}
    if (b.command_kind === 'CREATE_CONTENT') return publish({schema_version: 'content-edition-composition/1.0', deliverable_id: id('deliverable'), edition_id: id('edition'), previous_revision_id: null, content_title: b.content_title, content_type: b.content_type, edition_label: b.edition_label, academic_year: b.academic_year, created_by: id('operator'), created_at: '2026-11-09T00:00:00Z', sections: b.sections.map((s, i) => ({...s, form: {form_id: id('form', i+1), form_revision_id: id('formrev', i+1), form_sha256: sha, assembly_id: id('assembly', i+1), assembly_revision_id: id('assemblyrev', i+1), manifest_sha256: sha, placement_count: 0}}))});
    if (b.edit?.change_kind === 'SAVE_SECTIONS') {
      for (const change of b.edit.changes) {f.rows.set(change.section_id, change.placements); f.composition.sections.find(s => s.section_id === change.section_id).form.placement_count = change.placements.length;}
      return publish(f.composition);
    }
    if (b.edit?.change_kind === 'SAVE_STRUCTURE') return publish({...f.composition, sections: b.edit.sections.map(s => ({...s, form: f.composition.sections.find(v => v.section_id === s.section_id)?.form || null}))});
    if (b.command_kind === 'COPY_EDITION') return publish({...f.composition, edition_id: id('edition', 2), edition_label: b.edition_label, academic_year: b.academic_year});
  }
  if (path.endsWith('/prints')) {
    f.printed.push(b); return {result_kind: 'PRINT_MUTATION', disposition: 'RECORDED', replayed: false};
  }
  if (b.query_kind === 'LIST_CONTENTS') return {result_kind: 'CONTENTS', rows: f.composition ? [{deliverable_id: f.composition.deliverable_id, title: f.composition.content_title, content_type: 'OTHER', edition_count: 1}] : [], next_id: null};
  if (b.query_kind === 'LIST_EDITIONS') return {result_kind: 'EDITIONS', rows: [{edition_id: f.composition.edition_id, edition_label: f.composition.edition_label}], next_id: null};
  if (b.query_kind === 'READ_EDITION') return {result_kind: 'COMPOSITION', composition: structuredClone(f.composition), current_revision_id: f.composition.deliverable_revision_id};
  if (b.query_kind === 'READ_SECTION') {
    const all = f.rows.get(b.section_id) || [], rows = all.slice(b.after_position, b.after_position + b.limit);
    return {result_kind: 'SECTION', rows, total: all.length, next_position: b.after_position + rows.length < all.length ? b.after_position + rows.length : null};
  }
  if (b.query_kind === 'PRINTS') return {result_kind: 'PRINTS', rows: [], next_id: null};
  if (b.query_kind === 'USAGE') return {result_kind: 'USAGE', total_locations: 0, rows: [], next_after: null};
  if (b.query_kind === 'USAGE_SUMMARY') return {result_kind: 'USAGE_SUMMARY', query_sha256: sha, coverage: 'ACCESSIBLE_CONTENTS', rows: b.targets.map((_, i) => ({target_index: i, total_locations: 0, edition_locations: 0, other_locations: 0}))};
  if (b.query_kind === 'HISTORY') return {result_kind: 'HISTORY', rows: [], next_sequence: null};
  throw new Error('Unexpected ' + b.query_kind);
}
const prompts = [];
const c = f.controller = createContentPlanning({document, api, can: () => true, openItemDb: () => f.dbOpens++, openTarget: p => f.opened = p, confirm: () => true, prompt: () => prompts.shift() ?? null});
f.prompts = prompts;
c.install(); c.setOwner('owner'); c.open();
document.querySelectorAll('.view').forEach(v => v.classList.toggle('active', v.dataset.view === 'excel'));
`;
const server = createServer((request, response) => {
  const name = (request.url || "").split("/").pop().split("?")[0] || "index.html";
  const content = name === "app.js" ? app : assets.get(name);
  if (content === undefined) {response.writeHead(404); response.end(); return;}
  response.setHeader("Content-Type", name.endsWith(".js") ? "text/javascript" : name.endsWith(".css") ? "text/css" : name.endsWith(".svg") ? "image/svg+xml" : "text/html"); response.end(content);
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const browser = await chromium.launch({headless: true});
try {
  const page = await browser.newPage({viewport: {width: 1600, height: 1050}}), errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto(`http://127.0.0.1:${server.address().port}/studio/`);
  await page.locator("#excel-create-panel summary").click();
  await page.locator("#excel-name").fill("맞춤 시험지 <img src=x>");
  await page.locator("#excel-edition-name").fill("2027 초판");
  await page.locator("#excel-year").fill("2027");
  await page.locator("#excel-rounds").fill("20");
  await page.locator("#excel-create button").click();
  await page.waitForFunction(() => !document.querySelector("#excel-empty-slot").disabled);
  assert.equal(await page.locator("#excel-sections button").count(), 20);
  assert.match(await page.locator("#excel-content-title").textContent(), /<img src=x>/);
  assert.equal(await page.locator("#excel-content-title img").count(), 0);
  await page.locator("#excel-empty-slot").click();
  await page.locator("#excel-choose").click();
  await page.evaluate(() => {
    const target = {placement_kind: 'EXTERNAL_SOURCE_DOCUMENT', source_id: 'extitem_' + '1'.repeat(32), source_revision_id: 'extitemrev_' + '2'.repeat(32), observation_sha256: 'sha256:' + 'a'.repeat(64), edition: 3, source_format: 'HWPX'};
    fixture.target = target; fixture.controller.acceptSelection(target, '고유번호 10321');
  });
  await page.locator("#excel-choose").click();
  await page.evaluate(() => fixture.controller.acceptSelection(fixture.target, '고유번호 10321'));
  assert.equal(await page.locator("#excel-rows tr").count(), 3);
  assert.equal(await page.locator("#excel-rows .excel-duplicate").count(), 2);
  await page.evaluate(() => fixture.fail = true);
  await page.locator("#excel-save").click();
  await page.locator("#excel-retry-button").waitFor();
  assert.equal(await page.locator("#excel-empty-slot").isDisabled(), true);
  await page.locator("#excel-retry-button").click();
  await page.waitForFunction(() => document.querySelector("#excel-retry").hidden);
  const writes = await page.evaluate(() => fixture.calls.filter(c => c.body.edit?.change_kind === 'SAVE_SECTIONS'));
  assert.equal(writes.length, 2); assert.deepEqual(writes[0], writes[1], "retry changed key or input");
  assert.equal(await page.evaluate(() => fixture.printed.length), 0, "save falsely recorded print");
  await page.locator("#excel-sections button").nth(1).click();
  await page.waitForFunction(() => document.querySelector("#excel-section-title").textContent === '2회차' && !document.querySelector("#excel-empty-slot").disabled);
  await page.locator("#excel-sections button").first().click();
  await page.waitForFunction(() => document.querySelectorAll("#excel-rows tr").length === 3);
  await page.locator("#excel-rows tr").nth(1).getByRole("button", {name: "사용 이력", exact: true}).click();
  await page.waitForFunction(() => document.querySelector("#excel-inspect-title").textContent.includes('사용 이력'));
  await page.evaluate(() => {
    const first = fixture.composition.sections[0];
    fixture.rows.set(first.section_id, Array.from({length: 1200}, (_, i) => ({placement_id: 'placement_' + (i+1).toString(16).padStart(32,'0'), position: i+1, target: fixture.target, points_milli: null, display_number: null, note: '', copied_from: null})));
    first.form.placement_count = 1200;
  });
  await page.locator("#excel-refresh").click();
  await page.waitForFunction(() => document.querySelector("#excel-page").textContent.includes('/ 1200문항'));
  assert.equal(await page.locator("#excel-rows tr").count(), 50);
  await page.locator("#excel-next-page").click(); assert.match(await page.locator("#excel-page").textContent(), /51–100/);
  await page.locator('#excel-delivery-panel summary').click();
  await page.locator('#excel-delivery-prepare').click();
  await page.getByRole('button', {name: 'HWPX 제작', exact: true}).click();
  await page.getByRole('link', {name: 'HWPX 다운로드', exact: true}).waitFor();
  assert.match(await page.getByRole('link', {name: 'HWPX 다운로드', exact: true}).getAttribute('href'), /hwpx-builds\/hwpxbuild_[a-f0-9]+\/download$/);
  assert.equal(await page.evaluate(() => fixture.printed.length), 0, 'HWPX export recorded printing');
  await page.locator('#excel-delivery-refresh').click();
  await page.getByRole('button', {name: 'HWPX 제작', exact: true}).click();
  await page.getByRole('link', {name: 'HWPX 다운로드', exact: true}).waitFor();
  assert.equal(await page.evaluate(() => fixture.buildSubmissions), 1, 'history lookup resubmitted build');
  await page.screenshot({path: '/tmp/eom-excel-browser-desktop.png', fullPage: true});
  await page.setViewportSize({width: 390, height: 844});
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, "mobile page overflow");
  await page.screenshot({path: '/tmp/eom-excel-browser-mobile.png', fullPage: true});
  await page.evaluate(() => {fixture.held = 'READ_EDITION'; document.querySelector('#excel-refresh').click();});
  await page.waitForFunction(() => fixture.release !== null);
  await page.evaluate(() => {fixture.controller.setOwner('another-user'); fixture.release();});
  await page.waitForTimeout(50);
  assert.equal(await page.locator("#excel-editor").isVisible(), false, "previous owner's late response rendered");
  assert.deepEqual(errors, []);
  console.log("CONTENT_PLANNING_BROWSER=PASS desktop/mobile/create/1200/replay/owner-race live_writes=0");
} finally {await browser.close(); server.close();}
