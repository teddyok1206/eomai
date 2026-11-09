import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {createServer} from "node:http";
import {createRequire} from "node:module";
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.EOM_WEB_PLAYWRIGHT_MODULE);
const root = new URL("../../apps/web_gui/eom_web_gui/static/", import.meta.url);
const names = ["index.html", "styles.css", "content-planning.css", "content-planning.js", "content-planning-draft.js", "content-planning-location.js", "content-planning-pending.js", "content-planning-copy.js", "content-planning-lifecycle.js", "item-db-delivery.js", "knowledge-map.css", "eom-mark.svg"];
const assets = new Map(await Promise.all(names.map(async name => [name, await readFile(new URL(name, root), "utf8")])));
const app = `
import {createContentPlanning} from './content-planning.js';
const f = window.fixture = {calls: [], composition: null, rows: new Map(), fail: false, held: null, release: null, printed: [], dbOpens: 0, lifecycle: new Map(), failLifecycle: false};
const id = (p, n = 1) => p + '_' + n.toString(16).padStart(32, '0'), sha = 'sha256:' + 'a'.repeat(64);
let revision = 0;
function publish(value) {
  revision++; f.composition = {...value, deliverable_revision_id: id('delivrev', revision), revision_number: revision, composition_sha256: sha};
  return {schema_version: 'content-planning-write-result/1.0', disposition: 'SAVED', replayed: false, composition: structuredClone(f.composition), current_revision_id: f.composition.deliverable_revision_id};
}
async function api(path, options = {}) {
  f.calls.push({path, body: structuredClone(options.body), key: options.headers?.['Idempotency-Key']});
  const b = options.body || {};
  const lifecycleEntry = target => f.lifecycle.get(target.target_id) || {target,
    deliverable_id: f.composition.deliverable_id,
    title: target.target_kind === 'CONTENT' ? f.composition.content_title : f.composition.edition_label,
    lifecycle_state: 'ACTIVE', version: 0, current_revision_id: f.composition.deliverable_revision_id, parent_archived: false};
  if (path.endsWith('/lifecycle/query')) {
    if (b.action_kind === 'READ_LIFECYCLE') return {result_kind: 'LIFECYCLE_VIEW', entry: lifecycleEntry(b.target), events: []};
    return {result_kind: 'LIFECYCLE_LIST', rows: [...f.lifecycle.values()].filter(e => e.target.target_kind === b.target_kind && (b.lifecycle_state === 'ALL' || e.lifecycle_state === b.lifecycle_state)), next_id: null};
  }
  if (path.endsWith('/lifecycle')) {
    if (f.failLifecycle) {
      f.failLifecycle = false;
      const error = new Error('합성 보관 응답 지연'); error.code = f.lifecycleFailureCode;
      if (error.code === 'CONTENT_LIFECYCLE_STALE') {
        const before = lifecycleEntry(b.target); f.lifecycle.set(b.target.target_id, {...before, version: before.version + 1});
      }
      throw error;
    }
    const before = lifecycleEntry(b.target);
    if (b.expected_version !== before.version || b.expected_state !== before.lifecycle_state) throw new Error('Unexpected lifecycle version');
    const entry = {...before, lifecycle_state: b.desired_state, version: before.version + 1};
    f.lifecycle.set(b.target.target_id, entry);
    return {result_kind: 'LIFECYCLE_MUTATION', entry, replayed: false, disposition: 'CHANGED'};
  }
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
    if (f.fail) {f.fail = false; const error = new Error('합성 응답 지연'); error.code = f.failureCode; f.failureCode = null; throw error;}
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
    return {result_kind: 'SECTION', edition_id: b.edition_id, revision_id: b.revision_id,
      composition_sha256: b.composition_sha256, section_id: b.section_id,
      form: structuredClone(f.composition.sections.find(s => s.section_id === b.section_id).form),
      rows, total: all.length, next_position: b.after_position + rows.length < all.length ? b.after_position + rows.length : null};
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
  const submitted = await page.evaluate(() => fixture.calls.filter(c => c.body.edit?.change_kind === 'SAVE_SECTIONS').at(-1));
  await page.evaluate(() => {fixture.controller.setOwner(null); fixture.controller.setOwner('other'); fixture.controller.open();});
  assert.equal(await page.locator('#excel-retry').isVisible(), false, 'other owner received pending request');
  await page.evaluate(() => {fixture.controller.setOwner(null); fixture.controller.setOwner('owner'); fixture.controller.open();});
  await page.locator('#excel-retry-button').waitFor();
  await page.locator("#excel-retry-button").click();
  await page.waitForFunction(() => document.querySelector("#excel-retry").hidden);
  const writes = await page.evaluate(() => fixture.calls.filter(c => c.body.edit?.change_kind === 'SAVE_SECTIONS'));
  assert.equal(writes.length, 2); assert.deepEqual(writes[0], writes[1], "retry changed key or input");
  assert.deepEqual(writes[1], submitted, 'reauthentication replaced submitted command');
  assert.equal(await page.evaluate(() => sessionStorage.getItem('eom:excel:pending:1:owner')), null);
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
  await page.locator('#excel-print-panel summary').click();
  await page.waitForFunction(() => document.querySelector('#excel-print-output').options.length === 2);
  const printedOutput = await page.evaluate(() => ({build: fixture.build.build_id, hash: fixture.build.output_sha256}));
  await page.locator('#excel-print-output').selectOption(printedOutput.build);
  await page.locator('#excel-print-form button[type="submit"]').click();
  await page.waitForFunction(() => fixture.printed.length === 1);
  const printCommand = await page.evaluate(() => fixture.printed[0]);
  assert.equal(printCommand.command_kind, 'RECORD_PRINT_WITH_OUTPUT');
  assert.equal(printCommand.output_build_id, printedOutput.build);
  assert.equal(printCommand.output_sha256, printedOutput.hash);
  await page.screenshot({path: '/tmp/eom-excel-browser-desktop.png', fullPage: true});
  await page.setViewportSize({width: 390, height: 844});
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, "mobile page overflow");
  await page.screenshot({path: '/tmp/eom-excel-browser-mobile.png', fullPage: true});
  await page.setViewportSize({width: 1600, height: 1050});
  await page.locator('#excel-copy-panel summary').click();
  await page.getByRole('checkbox', {name: '52번 복사·교체 선택', exact: true}).check();
  await page.getByRole('checkbox', {name: '51번 복사·교체 선택', exact: true}).check();
  await page.locator('#excel-copy-selected').click();
  await page.waitForFunction(() => document.querySelector('#excel-copy-source').textContent.includes('2개 복사됨'));
  const source = await page.evaluate(() => ({revision: fixture.composition.deliverable_revision_id, form: {...fixture.composition.sections[0].form}}));
  await page.evaluate(() => fixture.prompts.push('2028 새 판', '2028'));
  await page.locator('#excel-copy').click();
  await page.waitForFunction(() => document.querySelector('#excel-content-title').textContent.includes('2028 새 판') && !document.querySelector('#excel-empty-slot').disabled);
  await page.locator('#excel-sections button').nth(1).click();
  await page.waitForFunction(() => document.querySelector('#excel-section-title').textContent === '2회차' && !document.querySelector('#excel-empty-slot').disabled);
  await page.locator('#excel-paste-position').fill('1');
  await page.locator('#excel-paste').click();
  assert.equal(await page.locator('#excel-rows tr').count(), 2);
  assert.equal(await page.locator('#excel-copy-selected').isDisabled(), true, 'unsaved target was allowed as a saved copy source');
  await page.locator('#excel-save').click();
  await page.waitForFunction(() => document.querySelector('#excel-draft-state').textContent === '저장됨');
  const copied = await page.evaluate(() => fixture.calls.filter(c => c.body?.edit?.change_kind === 'SAVE_SECTIONS').at(-1).body.edit.changes[0].placements);
  assert.equal(copied.length, 2);
  assert.deepEqual(copied.map(row => row.copied_from.placement_id), [51, 52].map(n => 'placement_' + n.toString(16).padStart(32, '0')), 'checkbox click order replaced source order');
  for (const row of copied) {
    assert.equal(row.copied_from.assembly_revision_id, source.form.assembly_revision_id);
    assert.equal(row.copied_from.manifest_sha256, source.form.manifest_sha256);
    assert.notEqual(row.placement_id, row.copied_from.placement_id);
  }
  await page.getByRole('checkbox', {name: '1번 복사·교체 선택', exact: true}).check();
  await page.locator('#excel-paste-mode').selectOption('REPLACE');
  await page.locator('#excel-paste').click();
  assert.equal(await page.locator('#excel-rows tr').count(), 3);
  await page.locator('#excel-save').click();
  await page.waitForFunction(() => document.querySelector('#excel-draft-state').textContent === '저장됨');
  const replaced = await page.evaluate(() => fixture.calls.filter(c => c.body?.edit?.change_kind === 'SAVE_SECTIONS').at(-1).body.edit.changes[0].placements);
  assert.deepEqual(replaced.map(row => row.position), [1, 2, 3]);
  assert.equal(replaced[2].placement_id, copied[1].placement_id, 'replace changed the unselected target');
  assert.equal(replaced.some(row => row.placement_id === copied[0].placement_id), false);
  await page.locator('#excel-copy-section').click();
  await page.waitForFunction(() => document.querySelector('#excel-copy-source').textContent.includes('3개 복사됨'));
  await page.setViewportSize({width: 390, height: 844});
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, 'open copy panel overflow');
  const beforeConflict = await page.locator('#excel-rows tr').count();
  await page.locator('#excel-empty-slot').click();
  await page.evaluate(() => {fixture.fail = true; fixture.failureCode = 'CONTENT_EDITION_REVISION_STALE';});
  await page.locator('#excel-save').click();
  await page.waitForFunction(() => document.querySelector('#excel-message').textContent.includes('다른 사람이'));
  assert.equal(await page.locator('#excel-rows tr').count(), beforeConflict + 1, 'conflict discarded editing values');
  const beforeReload = await page.evaluate(() => fixture.calls.filter(c => c.body?.edit?.change_kind === 'SAVE_SECTIONS').length);
  await page.locator('#excel-refresh').click();
  await page.waitForFunction(() => document.querySelector('#excel-retry').hidden && !document.querySelector('#excel-empty-slot').disabled);
  assert.equal(await page.evaluate(() => fixture.calls.filter(c => c.body?.edit?.change_kind === 'SAVE_SECTIONS').length), beforeReload, 'explicit conflict reload resubmitted command');
  await page.setViewportSize({width: 1600, height: 1050});
  const beforeArchive = await page.evaluate(() => JSON.stringify(fixture.composition));
  await page.locator('#excel-lifecycle-panel > summary').click();
  await page.waitForFunction(() => document.querySelector('#excel-lifecycle-status').textContent.includes('사용 중'));
  await page.locator('#excel-lifecycle-reason').fill('다음 콘텐츠로 전환');
  await page.evaluate(() => fixture.failLifecycle = true);
  await page.locator('#excel-lifecycle-change').click();
  await page.locator('#excel-retry-button').waitFor();
  await page.locator('#excel-retry-button').click();
  await page.waitForFunction(() => document.querySelector('#excel-lifecycle-status').textContent.includes('보관 중'));
  assert.equal(await page.locator('#excel-empty-slot').isDisabled(), true, 'archived edition remained editable');
  assert.equal(await page.evaluate(() => JSON.stringify(fixture.composition)), beforeArchive, 'archive changed immutable composition');
  const archiveCalls = await page.evaluate(() => fixture.calls.filter(c => c.path.endsWith('/lifecycle')));
  assert.equal(archiveCalls.length, 2); assert.deepEqual(archiveCalls[0], archiveCalls[1], 'lifecycle retry changed key/body');
  await page.locator('#excel-lifecycle-list-kind').selectOption('EDITION');
  await page.locator('#excel-lifecycle-rows').getByRole('button', {name: '편성 열기', exact: true}).waitFor();
  await page.locator('#excel-lifecycle-rows').getByRole('button', {name: '편성 열기', exact: true}).click();
  await page.waitForFunction(() => document.querySelector('#excel-draft-state').textContent === '저장됨');
  const archivedRead = await page.evaluate(() => fixture.calls.filter(c => c.body?.query_kind === 'READ_EDITION').at(-1).body);
  assert.equal(archivedRead.revision_id, JSON.parse(beforeArchive).deliverable_revision_id);
  assert.equal(await page.locator('#excel-empty-slot').isDisabled(), true);
  await page.locator('#excel-lifecycle-rows').getByRole('button', {name: '복원하기', exact: true}).click();
  await page.waitForFunction(() => !document.querySelector('#excel-empty-slot').disabled);
  assert.equal(await page.evaluate(() => JSON.stringify(fixture.composition)), beforeArchive);
  assert.equal(await page.evaluate(() => fixture.printed.length), 1, 'archive/restore created printing');
  // A stale archive-list action must refresh its own target, not the open edition.
  const otherEdition = 'edition_' + '9'.repeat(32);
  await page.evaluate(other => {
    fixture.lifecycle.set(other, {target: {target_kind: 'EDITION', target_id: other},
      deliverable_id: fixture.composition.deliverable_id, title: '다른 판', lifecycle_state: 'ARCHIVED',
      version: 0, current_revision_id: fixture.composition.deliverable_revision_id, parent_archived: false});
  }, otherEdition);
  await page.locator('#excel-lifecycle-list').click();
  await page.locator('#excel-lifecycle-rows').getByRole('button', {name: '복원하기', exact: true}).waitFor();
  await page.evaluate(() => {fixture.failLifecycle = true; fixture.lifecycleFailureCode = 'CONTENT_LIFECYCLE_STALE';});
  await page.locator('#excel-lifecycle-rows').getByRole('button', {name: '복원하기', exact: true}).click();
  await page.waitForFunction(() => document.querySelector('#excel-message').textContent.includes('보관 상태를 먼저 변경'));
  await page.locator('#excel-refresh').click();
  await page.waitForFunction(() => document.querySelector('#excel-retry').hidden && !document.querySelector('#excel-lifecycle-list').disabled);
  const refreshedTarget = await page.evaluate(() => fixture.calls.filter(c => c.body?.action_kind === 'READ_LIFECYCLE').at(-1).body.target.target_id);
  assert.equal(refreshedTarget, otherEdition, 'stale recovery refreshed the open edition instead of rejected target');
  assert.match(await page.locator('#excel-lifecycle-status').textContent(), /2028 새 판/, 'other target read replaced current selection');
  await page.locator('#excel-lifecycle-rows').getByRole('button', {name: '복원하기', exact: true}).click();
  await page.waitForFunction(other => fixture.lifecycle.get(other).lifecycle_state === 'ACTIVE', otherEdition);
  const refreshedCommand = await page.evaluate(() => fixture.calls.filter(c => c.path.endsWith('/lifecycle')).at(-1).body);
  assert.equal(refreshedCommand.expected_version, 1);

  // A's definite rejection must not turn B's unknown saved submission into a discard.
  await page.locator('#excel-empty-slot').click();
  await page.evaluate(() => {fixture.fail = true; fixture.failureCode = 'CONTENT_EDITION_REVISION_STALE';});
  await page.locator('#excel-save').click();
  await page.waitForFunction(() => document.querySelector('#excel-message').textContent.includes('다른 사람이 먼저'));
  const otherPending = {path: 'commands', key: 'studio:excel:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', body: {
    command_kind: 'CREATE_CONTENT', content_title: '다른 사용자 복구', content_type: 'OTHER',
    edition_label: '첫 판', academic_year: null, sections: []}};
  await page.evaluate(operation => {
    sessionStorage.setItem('eom:excel:pending:1:owner-b', JSON.stringify(operation));
    fixture.controller.setOwner('owner-b'); fixture.controller.open();
  }, otherPending);
  await page.locator('#excel-refresh').click();
  await page.waitForFunction(() => document.querySelector('#excel-content-title').textContent.includes('다른 사용자 복구'));
  const otherCalls = await page.evaluate(key => fixture.calls.filter(c => c.key === key), otherPending.key);
  assert.equal(otherCalls.length, 1, 'B unknown operation was discarded rather than replayed');
  assert.deepEqual(otherCalls[0].body, otherPending.body);
  assert.equal(await page.evaluate(() => sessionStorage.getItem('eom:excel:pending:1:owner-b')), null);
  await page.evaluate(() => {fixture.held = 'READ_EDITION'; document.querySelector('#excel-refresh').click();});
  await page.waitForFunction(() => fixture.release !== null);
  await page.evaluate(() => {fixture.controller.setOwner('another-user'); fixture.release();});
  await page.waitForTimeout(50);
  assert.equal(await page.locator("#excel-editor").isVisible(), false, "previous owner's late response rendered");
  assert.equal(await page.locator('#excel-copy-source').textContent(), '복사할 구간이나 문항을 골라 주세요.', 'old owner clipboard remained visible');
  await page.evaluate(() => {
    sessionStorage.setItem('eom:excel:pending:1:owner-corrupt', '{}');
    fixture.controller.setOwner('owner-corrupt'); fixture.controller.open();
  });
  assert.equal(await page.locator('#excel-create button').isDisabled(), true);
  await page.evaluate(() => fixture.controller.setOwner('owner-clean'));
  assert.equal(await page.locator('#excel-create button').isDisabled(), false, 'prior owner recovery error blocked a clean owner');
  await page.evaluate(() => fixture.controller.open());
  assert.equal(await page.locator('#excel-create button').isDisabled(), false);
  assert.deepEqual(errors, []);
  console.log("CONTENT_PLANNING_BROWSER=PASS desktop/mobile/create/1200/replay/copy-insert-replace/archive-restore/owner-race live_writes=0");
} finally {await browser.close(); server.close();}
