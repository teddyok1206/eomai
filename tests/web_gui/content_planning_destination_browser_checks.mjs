import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {createRequire} from "node:module";

const require = createRequire(import.meta.url);
const {chromium} = require(process.env.EOM_WEB_PLAYWRIGHT_MODULE);
const root = new URL("../../apps/web_gui/eom_web_gui/static/", import.meta.url);
const names = ["content-planning-destination.js", "styles.css", "content-planning.css"];
const assets = new Map(await Promise.all(names.map(async name => [name, await readFile(new URL(name, root), "utf8")])));
const id = (prefix, n = 1) => `${prefix}_${n.toString(16).padStart(32, "0")}`;
const app = `
import {createPlanningDestinationPicker} from './content-planning-destination.js';
const id = (prefix, n = 1) => prefix + '_' + n.toString(16).padStart(32, '0');
const number = value => parseInt(value.split('_').at(-1), 16);
const sha = 'sha256:' + 'a'.repeat(64);
const f = window.fixture = {calls: [], actor: 'owner-a', hold: null, releases: [], stale: false, wrong: false, result: 'waiting'};
const edition = (product, n) => ({edition_id: id('edition', product * 1000 + n), deliverable_id: id('deliverable', product),
  revision_id: id('delivrev', product * 1000 + n), composition_sha256: sha,
  edition_label: n + '판', academic_year: 2027, section_count: 3});
async function query(body) {
  f.calls.push({body: structuredClone(body), actor: f.actor});
  let data;
  if (body.query_kind === 'LIST_CONTENTS') {
    const start = body.after_id ? number(body.after_id) : 0;
    const rows = body.text === '없음' ? [] : Array.from({length: Math.min(50, 51-start)}, (_, i) => ({
      deliverable_id: id('deliverable', start+i+1), title: '콘텐츠 ' + (start+i+1), content_type: 'OTHER', edition_count: 51}));
    data = {result_kind: 'CONTENTS', rows, next_id: rows.length === 50 ? rows.at(-1).deliverable_id : null};
  } else if (body.query_kind === 'LIST_EDITIONS') {
    const product = number(body.deliverable_id), start = body.after_id ? number(body.after_id) % 1000 : 0;
    const rows = Array.from({length: Math.min(50, 51-start)}, (_, i) => edition(product, start+i+1));
    data = {result_kind: 'EDITIONS', rows, next_id: rows.length === 50 ? rows.at(-1).edition_id : null};
  } else if (body.query_kind === 'READ_EDITION') {
    const n = number(body.edition_id), product = Math.floor(n/1000);
    data = {result_kind: 'COMPOSITION', current_revision_id: id('delivrev', f.stale ? 999999 : n), composition: {
      schema_version: 'content-edition-composition/1.0', edition_id: body.edition_id,
      deliverable_id: id('deliverable', f.wrong ? 999 : product), deliverable_revision_id: body.revision_id,
      composition_sha256: sha, content_title: '콘텐츠 ' + product, edition_label: (n%1000) + '판',
      sections: [{section_id: id('section'), parent_id: null, kind: 'GROUP', label: '1부', form: null},
        {section_id: id('section', 2), parent_id: id('section'), kind: 'FORM', label: '첫 회차', form: {placement_count: 2}},
        {section_id: id('section', 3), parent_id: id('section'), kind: 'FORM', label: '빈 회차', form: {placement_count: 0}}]}};
  } else throw new Error('Unexpected write or slot read: ' + body.query_kind);
  if (f.hold === body.query_kind) {f.hold = null; await new Promise(resolve => f.releases.push(resolve));}
  return data;
}
const picker = f.picker = createPlanningDestinationPicker({document, query});
picker.setOwner(f.actor);
f.choose = count => {f.result = 'waiting'; f.pending = picker.choose({selectionCount: count}).then(value => {f.result = value;});};
f.ready = true;
`;
const html = '<!doctype html><html lang="ko"><head><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="styles.css"><link rel="stylesheet" href="content-planning.css"></head><body><button id="opener">배치할 문항</button><script type="module" src="fixture.js"></script></body></html>';
const browser = await chromium.launch({headless: true});
try {
  const page = await browser.newPage(), errors = [], unexpected = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/*", route => {
    const name = new URL(route.request().url()).pathname.split("/").at(-1);
    const body = name === "index.html" ? html : name === "fixture.js" ? app : assets.get(name);
    if (body === undefined) {unexpected.push(name); return route.abort();}
    return route.fulfill({body, contentType: name.endsWith(".js") ? "text/javascript" : name.endsWith(".css") ? "text/css" : "text/html"});
  });
  await page.goto("https://destination.invalid/index.html");
  page.setDefaultTimeout(5000);
  await page.waitForFunction(() => fixture?.ready);
  const content = page.locator('#excel-destination-content'), editions = page.locator('#excel-destination-edition');
  const sections = page.locator('#excel-destination-section'), mode = page.locator('#excel-destination-mode');
  const position = page.locator('#excel-destination-position'), submit = page.getByRole('button', {name: '여기에 배치', exact: true});
  async function choose(count = 1) {
    await page.locator('#opener').focus();
    await page.evaluate(count => fixture.choose(count), count);
    await page.waitForFunction(() => document.querySelector('#excel-destination-content')?.options.length === 51);
  }
  async function destination(product = 1, revision = 1) {
    await content.selectOption(id('deliverable', product));
    await page.waitForFunction(() => document.querySelector('#excel-destination-edition').options.length === 51);
    await editions.selectOption(id('edition', product * 1000 + revision));
    await page.waitForFunction(() => document.querySelector('#excel-destination-section').options.length === 3);
    await sections.selectOption(id('section', 2));
  }

  await choose(2);
  assert.equal(await submit.isDisabled(), true);
  assert.equal(await content.locator('option').count(), 51);
  await page.getByRole('searchbox', {name: '콘텐츠 이름 검색'}).fill('아직 제출하지 않은 검색어');
  await page.getByRole('button', {name: '다음 콘텐츠', exact: true}).click();
  await page.waitForFunction(() => document.querySelector('#excel-destination-content').options.length === 2);
  assert.equal(await page.evaluate(() => fixture.calls.at(-1).body.text), '', 'pagination changed an unsubmitted search');
  assert.equal(await page.getByRole('button', {name: '다음 콘텐츠', exact: true}).isDisabled(), true);
  await page.getByRole('button', {name: '이전 콘텐츠', exact: true}).click();
  await page.waitForFunction(() => document.querySelector('#excel-destination-content').options.length === 51);
  await content.selectOption(id('deliverable'));
  await page.waitForFunction(() => document.querySelector('#excel-destination-edition').options.length === 51);
  await page.getByRole('button', {name: '다음 판', exact: true}).click();
  await page.waitForFunction(() => document.querySelector('#excel-destination-edition').options.length === 2);
  await editions.selectOption(id('edition', 1051));
  await page.waitForFunction(() => document.querySelector('#excel-destination-section').options.length === 3);
  assert.match(await sections.innerText(), /1부 \/ 첫 회차 · 2문항/);
  await sections.selectOption(id('section', 2));
  assert.equal(await position.inputValue(), '3');
  assert.equal(await mode.locator('option[value="REPLACE"]').evaluate(option => option.disabled), true);
  await position.fill('0'); await submit.click();
  assert.equal(await page.evaluate(() => fixture.result), 'waiting');
  await position.fill('2'); await submit.click();
  const result = await page.evaluate(async () => {await fixture.pending; return fixture.result;});
  assert.equal(result.currentRevisionId, id('delivrev', 1051));
  assert.equal(result.composition.deliverable_revision_id, id('delivrev', 1051));
  assert.equal(result.sectionId, id('section', 2));
  assert.equal(result.index, 1); assert.equal(result.replacePosition, null);
  assert.equal(await page.evaluate(() => document.activeElement.id), 'opener');
  const reads = await page.evaluate(() => fixture.calls.filter(call => call.body.query_kind === 'READ_EDITION'));
  assert.equal(reads[0].body.revision_id, id('delivrev', 1051), 'read silently used latest');

  await choose(); await destination();
  await mode.selectOption('REPLACE'); await position.fill('2'); await submit.click();
  assert.equal(await page.evaluate(() => fixture.result.replacePosition), 2);
  assert.equal(await page.evaluate(() => fixture.result.index), 1);
  await choose(); await destination();
  await sections.selectOption(id('section', 3));
  assert.equal(await position.inputValue(), '1');
  assert.equal(await mode.locator('option[value="REPLACE"]').evaluate(option => option.disabled), true);
  await page.keyboard.press('Escape');
  assert.equal(await page.evaluate(async () => {await fixture.pending; return fixture.result;}), null);

  // An edition-list pin cannot silently become a new writable head.
  await choose(); await page.evaluate(() => {fixture.stale = true;});
  await content.selectOption(id('deliverable'));
  await page.waitForFunction(() => document.querySelector('#excel-destination-edition').options.length === 51);
  await editions.selectOption(id('edition', 1001));
  await page.waitForFunction(() => document.querySelector('[role="status"]').textContent.includes('편성이 바뀌었습니다'));
  assert.equal(await submit.isDisabled(), true);
  await page.getByRole('button', {name: '취소', exact: true}).click();
  await page.evaluate(() => {fixture.stale = false; fixture.wrong = true;});
  await choose(); await content.selectOption(id('deliverable'));
  await page.waitForFunction(() => document.querySelector('#excel-destination-edition').options.length === 51);
  await editions.selectOption(id('edition', 1001));
  await page.waitForFunction(() => document.querySelector('[role="status"]').textContent.includes('편성이 바뀌었습니다'));
  assert.equal(await submit.isDisabled(), true);
  await page.getByRole('button', {name: '취소', exact: true}).click();
  await page.evaluate(() => {fixture.wrong = false;});

  // Late A does not overwrite selected B within the same open dialog.
  await choose(); await content.selectOption(id('deliverable'));
  await page.waitForFunction(() => document.querySelector('#excel-destination-edition').options.length === 51);
  await page.evaluate(() => {fixture.hold = 'READ_EDITION';});
  await editions.selectOption(id('edition', 1001));
  await page.waitForFunction(() => fixture.releases.length === 1);
  await editions.selectOption(id('edition', 1002));
  await page.waitForFunction(() => document.querySelector('#excel-destination-section').options.length === 3);
  await page.evaluate(() => fixture.releases.shift()());
  await sections.selectOption(id('section', 2)); await submit.click();
  assert.equal(await page.evaluate(() => fixture.result.currentRevisionId), id('delivrev', 1002));

  // New open/owner generations cancel promises and discard late prior responses.
  await page.evaluate(() => {fixture.hold = 'LIST_CONTENTS'; fixture.choose(1); fixture.previous = fixture.pending;});
  await page.waitForFunction(() => fixture.releases.length === 1);
  await choose();
  assert.equal(await page.locator('dialog').count(), 1);
  await page.evaluate(async () => {await fixture.previous; fixture.releases.shift()();});
  await destination();
  await page.evaluate(() => {fixture.actor = 'owner-b'; fixture.picker.setOwner(fixture.actor);});
  assert.equal(await page.evaluate(async () => {await fixture.pending; return fixture.result;}), null);
  assert.equal(await page.locator('dialog').count(), 0);
  await choose(); await destination();
  await submit.click();
  assert.equal(await page.evaluate(() => fixture.calls.at(-1).actor), 'owner-b');
  await page.evaluate(() => {fixture.hold = 'LIST_CONTENTS'; fixture.choose(1);});
  await page.waitForFunction(() => fixture.releases.length === 1);
  await page.evaluate(() => {fixture.picker.setOwner(null); fixture.releases.shift()();});
  assert.equal(await page.evaluate(async () => {await fixture.pending; return fixture.result;}), null);
  assert.equal(await page.locator('dialog').count(), 0);

  await page.evaluate(() => {fixture.picker.setOwner('owner-b'); fixture.choose(1);});
  await page.waitForFunction(() => document.querySelector('#excel-destination-content').options.length === 51);
  await page.getByRole('searchbox', {name: '콘텐츠 이름 검색'}).fill('없음');
  await page.getByRole('button', {name: '찾기', exact: true}).click();
  await page.waitForFunction(() => document.querySelector('[role="status"]').textContent === '검색된 콘텐츠가 없습니다.');
  assert.equal(await submit.isDisabled(), true);
  await page.setViewportSize({width: 390, height: 844});
  const box = await page.locator('dialog').boundingBox();
  assert.ok(box.x >= 0 && box.x + box.width <= 390, 'mobile modal overflow');
  await page.getByRole('button', {name: '취소', exact: true}).click();
  const calls = await page.evaluate(() => fixture.calls);
  assert.ok(calls.filter(call => call.body.query_kind !== 'READ_EDITION').every(call => call.body.limit === 50));
  assert.ok(calls.every(call => ['LIST_CONTENTS', 'LIST_EDITIONS', 'READ_EDITION'].includes(call.body.query_kind)));
  assert.deepEqual(errors, []); assert.deepEqual(unexpected, []);
  console.log('CONTENT_PLANNING_DESTINATION_BROWSER=PASS writes=0');
} finally {await browser.close();}
