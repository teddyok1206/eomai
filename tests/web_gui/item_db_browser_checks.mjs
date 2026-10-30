import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {createRequire} from "node:module";

const require = createRequire(import.meta.url);
const {chromium} = require(process.env.EOM_WEB_PLAYWRIGHT_MODULE);
const staticRoot = new URL("../../apps/web_gui/eom_web_gui/static/", import.meta.url);
const names = ["index.html", "styles.css", "item-db.js", "item-db-draft.js", "item-db-similarity.js", "eom-mark.svg"];
const assets = new Map(await Promise.all(names.map(async name => [name, await readFile(new URL(name, staticRoot), "utf8")])));

// Exact repository HTML, CSS and controller; only the existing API and navigation
// adapters are fixtures. No production credentials, DB or model calls are used.
const fixtureApp = `
import {createItemDb} from './item-db.js';
const fixture = window.dbFixture = {calls: [], similarCalls: [], opened: [], variations: [], allowSource: true, hold: null, release: null, releaseSimilar: {}};
const columns = Array.from({length: 26}, (_, index) => String.fromCharCode(65 + index)).concat(['AA','AB','AC','AD','AE','AF']);
function entry(number) {
  return {source_id: 'extitem_' + number.padStart(32, '0'), source_revision_id: 'extitemrev_' + number.padStart(32, '0'),
    external_number: number, observation_sha256: 'sha256:' + 'a'.repeat(64), major_unit: '변화와 다양성',
    minor_unit: number === '10310' ? '지질 시대의 환경과 생물' : '원소의 주기성', field_label: '통합과학',
    grade_label: '고1', author_label: '예시 출제자', match_status: 'MATCHED',
    selected_filename: number + '_최종본_3교.hwp', graph_state: 'NOT_PUBLISHED', similarity_state: 'NOT_INDEXED'};
}
function detail(number) {
  const value = entry(number);
  const text = {U: number, Q: value.major_unit, R: value.minor_unit, Z: value.field_label, Y: '기출변형',
    H: '3', J: '상', AD: value.author_label, AC: '2026-10-27', O: '고1', I: '자료 해석 능력 평가',
    AF: '<img src=x onerror=window.untrustedExecuted=true>', B: '4', N: value.selected_filename};
  return {entry: value, cells: columns.map(column => ({column, raw_text: text[column] || '', present: column in text})),
    editions: [1, 2, 3].map(edition => ({edition, available: true, match_status: 'MATCHED',
      filename: edition === 3 ? value.selected_filename : number + '_' + edition + '교.hwp', media_type: 'application/vnd.hancom.hwp'}))};
}
const graph = {source_class: 'PAST_EXAM', source_display_label: '합성 시험 17번',
  item_id: 'item_' + 'b'.repeat(32), item_revision_id: 'itemrev_' + 'c'.repeat(32),
  item_manifest_sha256: 'sha256:' + 'd'.repeat(64), graph_snapshot_revision_id: 'graphrev_' + 'e'.repeat(32),
  snapshot_sha256: 'sha256:' + 'f'.repeat(64), item_revision_state: 'APPROVED', hwpx_exam_eligible: true,
  past_exam_context: {occurrence_display_label: '합성 시험', administration_year: 2026,
    administration_month: 6, item_number: 17},
  curriculum_units: [{key:'unit-one', unit_code: '1-1', label:'물질의 규칙성'}]};
async function api(path, options = {}) {
  fixture.calls.push({path, ...structuredClone(options)});
  if (fixture.hold && path === fixture.hold) {
    fixture.hold = null;
    await new Promise(resolve => {fixture.release = resolve;});
  }
  if (path.startsWith('/item-db/assemblies?')) return {values: [], next_cursor: null};
  if (path === '/item-db/assemblies' && options.method === 'POST') {
    fixture.saved = options.body;
    return {assembly_id: 'assembly_' + '1'.repeat(32), placement_count: options.body.placements.length};
  }
  if (path === '/item-db/external-sources/search') {
    if (fixture.failNextSearch) {fixture.failNextSearch = false; throw new Error('합성 조회 실패');}
    if (options.body.cursor) return {values: [entry('10319')], has_more: false, next_cursor: null};
    return {values: [entry('10310'), entry('10318')], has_more: true, next_cursor: 'next-page'};
  }
  if (path.startsWith('/item-db/graph-items?')) {
    const params = new URL('https://fixture' + path).searchParams;
    if (params.has('item_number') && params.get('item_number') !== '17') return {values: [], has_more: false, next_cursor: null};
    return {values: [{...graph, source_class: params.get('source_class'),
      past_exam_context: params.get('source_class') === 'PAST_EXAM' ? graph.past_exam_context : null}], has_more: false, next_cursor: null};
  }
  if (path.includes('/preview?')) return {sha256: 'sha256:' + 'a'.repeat(64)};
  if (path.startsWith('/item-db/external-sources/')) {
    const value = detail(path.split('/')[3].slice(-5));
    if (fixture.staleSource) value.entry.source_revision_id = 'extitemrev_' + 'f'.repeat(32);
    return value;
  }
  throw new Error('UNEXPECTED_FIXTURE_REQUEST ' + path);
}
async function searchSimilar(pointer, key, pinnedQuery) {
  fixture.similarCalls.push({pointer: structuredClone(pointer), key, pinnedQuery: structuredClone(pinnedQuery)});
  const candidate = {...graph, source_display_label: '합성 시험 18번', item_id: 'item_' + '8'.repeat(32),
    item_revision_id: 'itemrev_' + '9'.repeat(32), past_exam_context: {...graph.past_exam_context, item_number: 18}};
  const other = entry(pointer.source_id?.endsWith('10318') ? '10310' : '10318');
  const queryPin = pinnedQuery || {schema_version: 'system-rag-reference-query-prepare-request/4.0', idempotency_key: key};
  const result = {status: 'READY', pinned_query: queryPin, candidates: [
    {kind: 'GRAPH_ITEM', entry: candidate, label: '합성 시험 18번', unit_label: '물질의 규칙성', cosine_millionths: 921234},
    {kind: 'EXTERNAL_SOURCE', entry: other, label: '고유번호 ' + other.external_number, unit_label: other.minor_unit, cosine_millionths: 870001}]};
  if (fixture.pendingSimilarity) {fixture.pendingSimilarity = false; return {status: 'PENDING', phase: 'COMPUTING', pinned_query: queryPin};}
  if (fixture.failSimilarity) {fixture.failSimilarity = false; throw new Error('합성 연결 시간 초과');}
  if (fixture.holdSimilarity) {
    const identity = pointer.source_id || pointer.item_revision_id;
    await new Promise(resolve => {fixture.releaseSimilar[identity] = resolve;});
  }
  return result;
}
const controller = createItemDb({document, api, openRegisteredItem: entry => fixture.opened.push(entry),
  openPastExamVariation: entry => fixture.variations.push(entry),
  canReadSource: () => fixture.allowSource, searchSimilar});
controller.install(); controller.open();
document.querySelectorAll('.view').forEach(view => view.classList.toggle('active', view.dataset.view === 'item-db'));
fixture.controller = controller;
fixture.ready = true;
`;

const browser = await chromium.launch({headless: true, args: ["--no-sandbox"]});
try {
  const page = await browser.newPage({viewport: {width: 1600, height: 1000}});
  const errors = [];
  const unexpected = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/*", async route => {
    const url = new URL(route.request().url());
    if (url.pathname === "/studio") return route.fulfill({contentType: "text/html", body: assets.get("index.html")});
    const name = url.pathname.split("/").at(-1);
    if (name === "app.js") return route.fulfill({contentType: "text/javascript", body: fixtureApp});
    const body = assets.get(name);
    if (body === undefined) {unexpected.push(url.pathname); return route.abort();}
    return route.fulfill({body, contentType: name.endsWith(".js") ? "text/javascript" : name.endsWith(".css") ? "text/css" : "image/svg+xml"});
  });
  await page.goto("https://item-db.invalid/studio");
  page.setDefaultTimeout(5000);
  await page.waitForFunction(() => window.dbFixture?.ready && document.querySelectorAll('#item-db-results [data-selection-key]').length === 2);
  const rows = page.locator("#item-db-results tr[data-selection-key]");
  assert.equal(await page.locator("#item-db-results article").count(), 0);
  assert.equal(await rows.count(), 2);
  assert.match(await page.locator("#item-db-table-heading").innerText(), /고유번호[\s\S]*분야[\s\S]*대단원/u);
  const left = await page.locator(".item-db-panel").boundingBox();
  const right = await page.locator("#item-db-detail-panel").boundingBox();
  assert.ok(right.x >= left.x + left.width, "desktop detail must be to the right of the metadata table");
  assert.equal(await page.evaluate(() => window.dbFixture.calls.filter(call => /^\/item-db\/external-sources\/extitem_/.test(call.path)).length), 0, "listing must not add N+1 detail calls");
  await page.evaluate(() => {window.dbFixture.hold = '/item-db/external-sources/search';});
  await page.locator("#item-db-more").click();
  await page.waitForFunction(() => typeof window.dbFixture.release === 'function');
  await rows.first().getByRole("button").click();
  await page.evaluate(() => window.dbFixture.release());
  await page.waitForFunction(() => document.querySelector('#item-db-result-count').textContent === '3개 표시');

  await rows.first().getByRole("button").click();
  await page.locator(".item-db-detail-heading h3").waitFor();
  assert.match(await page.locator("#item-db-detail").innerText(), /고유번호 10310/);
  assert.equal(await rows.first().getByRole("button").getAttribute("aria-pressed"), "true");
  assert.equal(await page.locator(".item-db-edition.is-final").count(), 1);
  assert.match(await page.locator(".item-db-edition.is-final").innerText(), /3교[\s\S]*최종본/);
  assert.match(await page.locator(".item-db-detail-summary").innerText(), /문항 분류[\s\S]*기출변형/);
  assert.equal(await page.locator("#item-db-detail img").count(), 0, "untrusted metadata must remain text");
  assert.equal(await page.evaluate(() => window.untrustedExecuted), undefined);
  await page.locator(".item-db-edition.is-final").getByRole("button", {name: "PDF 미리보기 준비"}).click();
  const preview = page.locator(".item-db-edition.is-final").getByRole("link", {name: "PDF 열기"});
  await preview.waitFor();
  assert.match(await preview.getAttribute("href"), /editions\/3\/preview\.pdf\?source_revision_id=extitemrev_0+10310$/);
  await page.getByRole("button", {name: "조립 목록에 담기", exact: true}).click();
  assert.equal(await page.locator("#item-db-draft-count").innerText(), "1개");
  assert.equal(await page.locator("#item-db-tab-count").innerText(), "1");

  // Slow A must never replace B, and closing/resetting a detail invalidates its reply.
  await page.evaluate(() => {window.dbFixture.hold = '/item-db/external-sources/extitem_' + '10310'.padStart(32, '0');});
  await rows.first().getByRole("button").click();
  await page.waitForFunction(() => typeof window.dbFixture.release === 'function');
  await rows.nth(1).getByRole("button").click();
  await page.waitForFunction(() => document.querySelector('.item-db-detail-heading h3')?.textContent === '고유번호 10318');
  await page.evaluate(() => window.dbFixture.release());
  assert.match(await page.locator("#item-db-detail").innerText(), /고유번호 10318/);
  await page.locator("#item-db-detail-close").click();
  assert.match(await page.locator("#item-db-detail").innerText(), /왼쪽 표/);
  assert.equal(await page.locator("#item-db-results .is-selected").count(), 0);
  await page.evaluate(() => {window.dbFixture.release = null; window.dbFixture.hold = '/item-db/external-sources/extitem_' + '10310'.padStart(32, '0');});
  await rows.first().getByRole("button").click();
  await page.waitForFunction(() => typeof window.dbFixture.release === 'function');
  await page.locator("#item-db-detail-close").click();
  await page.evaluate(() => window.dbFixture.release());
  assert.match(await page.locator("#item-db-detail").innerText(), /왼쪽 표/);

  // Frequent-field buttons retain the official AND/OR and eight-condition contract.
  await page.locator('[data-filter-field="U"]').click();
  let filters = page.locator(".item-db-filter-row");
  await filters.first().locator("input").fill("10318");
  await page.locator('[data-filter-field="Z"]').click();
  await filters.nth(1).locator("input").fill("화학");
  await page.locator("#item-db-match-mode").selectOption("ANY");
  await page.locator("#item-db-search").click();
  let body = await page.evaluate(() => window.dbFixture.calls.filter(call => call.path.endsWith('/search')).at(-1).body);
  assert.equal(body.match_mode, "ANY");
  assert.deepEqual(body.conditions, [{field: "U", operator: "EQ", value: "10318"}, {field: "Z", operator: "CONTAINS", value: "화학"}]);
  await filters.nth(1).locator(".item-db-filter-operator").selectOption("IS_EMPTY");
  assert.equal(await filters.nth(1).locator("input").isVisible(), false);
  await page.locator("#item-db-search").click();
  body = await page.evaluate(() => window.dbFixture.calls.filter(call => call.path.endsWith('/search')).at(-1).body);
  assert.deepEqual(body.conditions[1], {field: "Z", operator: "IS_EMPTY", value: null});
  await filters.first().getByRole("button", {name: "이 조건 지우기"}).click();
  assert.equal(await filters.count(), 1);
  await page.locator("#item-db-filter-clear").click();
  assert.equal(await filters.count(), 0);
  assert.equal(await page.locator("#item-db-match-mode").inputValue(), "ALL");
  assert.equal(await page.locator("#item-db-filter-empty").isVisible(), true);
  for (let index = 0; index < 8; index++) await page.locator('[data-filter-field="MATCH_STATUS"]').click();
  assert.equal(await filters.count(), 8);
  assert.equal(await page.locator("#item-db-filter-add").isDisabled(), true);
  assert.equal(await filters.first().locator(".item-db-status-value").isVisible(), true);
  assert.equal(await filters.first().locator("input").isVisible(), false);
  await page.locator("#item-db-filter-clear").click();

  // Published items keep exact Graph pointers and open through the existing item preview.
  await page.locator("#item-db-source").selectOption("PAST_EXAM");
  await page.waitForFunction(() => document.querySelectorAll('#item-db-results [data-selection-key]').length === 1);
  assert.equal(await page.locator("#item-db-export").isVisible(), false);
  await page.locator("#item-db-graph-year").fill("2026");
  await page.locator("#item-db-graph-month").selectOption("6");
  await page.locator("#item-db-graph-number").fill("17");
  await page.locator("#item-db-search").click();
  const pastQuery = await page.evaluate(() => window.dbFixture.calls.filter(call => call.path.startsWith('/item-db/graph-items?')).at(-1).path);
  assert.match(pastQuery, /administration_year=2026/);
  assert.match(pastQuery, /administration_month=6/);
  assert.match(pastQuery, /item_number=17/);
  await rows.first().getByRole("button").press("Enter");
  assert.match(await page.locator("#item-db-detail").innerText(), /합성 시험 17번/);
  await page.getByRole("button", {name: "1:1 기출변형"}).click();
  assert.equal(await page.evaluate(() => window.dbFixture.variations.length), 1);
  await page.getByRole("button", {name: "같은 연도·월 찾기"}).click();
  assert.equal(await page.locator("#item-db-graph-number").inputValue(), "");
  await rows.first().getByRole("button").click();
  await page.getByRole("button", {name: "문항 미리보기", exact: true}).click();
  assert.equal(await page.evaluate(() => window.dbFixture.opened.length), 1);
  await page.getByRole("button", {name: "조립 목록에 담기", exact: true}).click();
  assert.equal(await page.locator("#item-db-draft-count").innerText(), "2개");
  assert.equal(await page.locator("#item-db-tab-count").innerText(), "2");
  await page.getByRole("tab", {name: /배치/}).click();
  assert.equal(await page.locator("#item-db-search-panel").isVisible(), false);
  assert.equal(await page.locator("#item-db-assembly-panel").isVisible(), true);
  assert.equal(await page.locator("#mock-exam-submit").count(), 1);
  await page.locator("#item-db-draft-save").click();
  await page.waitForFunction(() => window.dbFixture.saved?.placements.length === 2);
  const saved = await page.evaluate(() => window.dbFixture.saved);
  assert.equal(saved.placements[0].placement_kind, "EXTERNAL_SOURCE_DOCUMENT");
  assert.equal(saved.placements[1].placement_kind, "PAST_EXAM_ITEM_REVISION");
  assert.ok(saved.placements[1].graph_snapshot_revision_id.startsWith("graphrev_"));
  assert.doesNotMatch(await page.locator('#item-db-detail').innerText(), /itemrev_|graphrev_|extitemrev_/);

  // Small screens scroll the table itself, not the entire page, and show details below.
  await page.getByRole("tab", {name: "조회", exact: true}).click();
  await page.setViewportSize({width: 390, height: 844});
  await page.locator("#item-db-source").selectOption("EXTERNAL_SOURCE");
  await page.waitForFunction(() => document.querySelectorAll('#item-db-results [data-selection-key]').length === 2);
  await rows.first().getByRole("button").click();
  await page.waitForFunction(() => document.querySelector('.item-db-detail-heading h3')?.textContent === '고유번호 10310');
  const overflow = await page.evaluate(() => ({width: window.innerWidth, scrollWidth: document.documentElement.scrollWidth,
    elements: [...document.querySelectorAll('.view.active *')].filter(node => node.getBoundingClientRect().right > window.innerWidth + 1)
      .slice(0, 8).map(node => [node.tagName, node.id, node.className, node.getBoundingClientRect().width])}));
  assert.ok(overflow.scrollWidth <= overflow.width, 'no viewport-wide horizontal overflow: ' + JSON.stringify(overflow));
  const mobileLeft = await page.locator(".item-db-panel").boundingBox();
  const mobileRight = await page.locator("#item-db-detail-panel").boundingBox();
  assert.ok(mobileRight.y >= mobileLeft.y + mobileLeft.height);
  await page.getByRole("tab", {name: /배치/}).click();
  assert.equal(await page.locator("#item-db-draft-list").isVisible(), true);
  assert.equal(await page.locator("#mock-exam-selections").isVisible(), true);
  const assemblyWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  assert.ok(assemblyWidth <= 390, "mobile assembly tab must not overflow the viewport");
  await page.getByRole("tab", {name: /배치/}).press("ArrowLeft");
  assert.equal(await page.locator("#item-db-search-panel").isVisible(), true);

  // Similarity reuses the exact lookup/detail/draft rather than a second item viewer.
  await page.setViewportSize({width: 1600, height: 1000});
  assert.equal(await page.getByRole('tab').filter({hasText: /^(조회|배치|유사도)/u}).count(), 3);
  assert.equal(await page.locator('#item-db-similarity-start').isEnabled(), true);
  await page.locator('#item-db-similarity-start').click();
  await page.waitForFunction(() => document.querySelector('#item-db-similarity-count').textContent === '2개');
  assert.equal(await page.locator('#item-db-search-panel').isVisible(), false);
  assert.equal(await page.locator('#item-db-similarity-panel').isVisible(), true);
  assert.equal(await page.locator('#item-db-similarity-tab').getAttribute('aria-selected'), 'true');
  assert.match(await page.locator('#item-db-similarity-anchor').innerText(), /10310/);
  assert.match(await page.locator('#item-db-similarity-results').innerText(), /0\.921/u);
  const selectedRequest = await page.evaluate(() => window.dbFixture.similarCalls.at(-1));
  assert.equal(selectedRequest.pointer.source_revision_id, 'extitemrev_' + '10310'.padStart(32, '0'));
  assert.equal(await page.locator('#item-db-draft-count').innerText(), '2개');
  assert.doesNotMatch(await page.locator('#item-db-similarity-panel').innerText(), /itemrev_|graphrev_|extitemrev_/u);
  await page.getByRole('button', {name: '합성 시험 18번 조회에서 열기'}).click();
  assert.equal(await page.locator('#item-db-search-panel').isVisible(), true);
  assert.match(await page.locator('#item-db-detail').innerText(), /합성 시험 18번/);
  assert.equal(await rows.count(), 2, 'similarity navigation keeps the original lookup table');
  await page.getByRole('button', {name: '문항 미리보기', exact: true}).click();
  assert.equal(await page.evaluate(() => window.dbFixture.opened.at(-1).item_revision_id), 'itemrev_' + '9'.repeat(32));
  await page.getByRole('button', {name: '조립 목록에 담기', exact: true}).click();
  assert.equal(await page.locator('#item-db-draft-count').innerText(), '3개');
  await page.getByRole('tab', {name: '유사도', exact: true}).click();
  assert.equal(await page.evaluate(() => window.dbFixture.similarCalls.length), 1, 'opening a tab does not resubmit');
  await page.getByRole('button', {name: '고유번호 10318 조회에서 열기'}).click();
  await page.waitForFunction(() => document.querySelector('.item-db-detail-heading h3')?.textContent === '고유번호 10318');
  assert.equal(await page.locator('#item-db-search-panel').isVisible(), true);
  await page.getByRole('button', {name: '조립 목록에 담기', exact: true}).click();
  assert.equal(await page.locator('#item-db-draft-count').innerText(), '4개');

  // PENDING and transient errors retain the original request key for explicit observation.
  await page.evaluate(() => {window.dbFixture.pendingSimilarity = true;});
  await page.locator('#item-db-similarity-start').click();
  await page.waitForFunction(() => document.querySelector('#item-db-similarity-count').textContent === '검색 중');
  assert.equal(await page.locator('#item-db-similarity-progress').isVisible(), true);
  assert.equal(await page.locator('#item-db-similarity-tab-progress').isVisible(), true);
  assert.match(await page.locator('#item-db-similarity-progress-label').innerText(), /계산 중/u);
  assert.match(await page.locator('#item-db-similarity-elapsed').innerText(), /요청 후/u);
  await page.waitForFunction(() => !document.querySelector('#item-db-similarity-elapsed').textContent.endsWith(' 0초'));
  assert.doesNotMatch(await page.locator('#item-db-similarity-progress').innerText(), /%/u);
  const pendingKey = await page.evaluate(() => window.dbFixture.similarCalls.at(-1).key);
  await page.locator('#item-db-similarity-refresh').click();
  await page.waitForFunction(() => document.querySelector('#item-db-similarity-count').textContent === '2개');
  assert.equal(await page.locator('#item-db-similarity-progress').isVisible(), false);
  assert.equal(await page.locator('#item-db-similarity-tab-progress').isVisible(), false);
  assert.equal(await page.evaluate(() => window.dbFixture.similarCalls.at(-1).key), pendingKey);
  assert.equal(await page.evaluate(() => window.dbFixture.similarCalls.at(-1).pinnedQuery.idempotency_key), pendingKey);

  // A confirmed accepted PENDING is observed automatically, never submitted with a new key.
  await page.evaluate(() => {window.dbFixture.pendingSimilarity = true;});
  await page.locator('#item-db-similarity-refresh').click();
  await page.waitForFunction(() => document.querySelector('#item-db-similarity-count').textContent === '검색 중');
  await page.waitForFunction(() => document.querySelector('#item-db-similarity-count').textContent === '2개');
  assert.equal(await page.evaluate(() => window.dbFixture.similarCalls.at(-1).key), pendingKey);
  await page.evaluate(() => {window.dbFixture.failSimilarity = true;});
  await page.locator('#item-db-similarity-refresh').click();
  await page.waitForFunction(() => document.querySelector('#item-db-similarity-count').textContent === '확인 필요');
  assert.equal(await page.locator('#item-db-similarity-results button').count(), 0);
  await page.locator('#item-db-similarity-refresh').click();
  await page.waitForFunction(() => document.querySelector('#item-db-similarity-count').textContent === '2개');
  assert.equal(await page.evaluate(() => window.dbFixture.similarCalls.at(-1).key), pendingKey);

  // Slow A cannot replace B; completion must not steal focus from a different tab.
  await page.getByRole('tab', {name: '조회', exact: true}).click();
  await page.evaluate(() => {window.dbFixture.holdSimilarity = true;});
  await rows.first().getByRole('button').click();
  await page.waitForFunction(() => document.querySelector('.item-db-detail-heading h3')?.textContent === '고유번호 10310');
  await page.locator('#item-db-similarity-start').click();
  await page.waitForFunction(() => Object.keys(window.dbFixture.releaseSimilar).length === 1);
  await page.getByRole('tab', {name: '조회', exact: true}).click();
  await rows.nth(1).getByRole('button').click();
  await page.waitForFunction(() => document.querySelector('.item-db-detail-heading h3')?.textContent === '고유번호 10318');
  await page.locator('#item-db-similarity-start').click();
  await page.waitForFunction(() => Object.keys(window.dbFixture.releaseSimilar).length === 2);
  await page.getByRole('tab', {name: /배치/}).click();
  assert.equal(await page.locator('#item-db-similarity-tab-progress').isVisible(), true);
  await page.evaluate(() => window.dbFixture.releaseSimilar['extitem_' + '10318'.padStart(32, '0')]());
  await page.waitForFunction(() => document.querySelector('#item-db-similarity-count').textContent === '2개');
  assert.equal(await page.locator('#item-db-assembly-panel').isVisible(), true);
  await page.evaluate(() => {window.dbFixture.releaseSimilar['extitem_' + '10310'.padStart(32, '0')](); window.dbFixture.holdSimilarity = false;});
  await page.getByRole('tab', {name: '유사도', exact: true}).click();
  assert.match(await page.locator('#item-db-similarity-anchor').innerText(), /10318/u);
  assert.match(await page.locator('#item-db-similarity-results').innerText(), /고유번호 10310/u);

  // An external result is pinned: a changed source does not silently open latest.
  await page.evaluate(() => {window.dbFixture.staleSource = true;});
  await page.getByRole('button', {name: '고유번호 10310 조회에서 열기'}).click();
  await page.waitForFunction(() => document.querySelector('#item-db-detail').textContent.includes('버전이 바뀌었습니다'));
  assert.equal(await page.locator('#item-db-similarity-start').isDisabled(), true);
  assert.equal(await page.getByRole('button', {name: '조립 목록에 담기', exact: true}).count(), 0);
  await page.evaluate(() => {window.dbFixture.staleSource = false;});
  await page.locator('#item-db-search-tab').press('End');
  assert.equal(await page.locator('#item-db-similarity-panel').isVisible(), true);
  await page.locator('#item-db-similarity-tab').press('Home');
  assert.equal(await page.locator('#item-db-search-panel').isVisible(), true);
  await page.locator('#item-db-search-tab').press('ArrowLeft');
  assert.equal(await page.locator('#item-db-similarity-panel').isVisible(), true);
  await page.getByRole('tab', {name: '조회', exact: true}).click();

  const screenshot = process.env.EOM_ITEM_DB_SCREENSHOT;
  if (screenshot) {
    await page.setViewportSize({width: 1600, height: 1000});
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({path: screenshot, fullPage: true});
  }
  await page.evaluate(() => {window.dbFixture.failNextSearch = true;});
  await page.locator("#item-db-search").click();
  await page.waitForFunction(() => document.querySelector('#item-db-result-count').textContent === '조회 실패');
  assert.match(await page.locator("#item-db-results").innerText(), /다시 조회/);
  await page.evaluate(() => window.dbFixture.controller.open());
  await page.waitForFunction(() => document.querySelectorAll('#item-db-results [data-selection-key]').length === 2);
  await page.evaluate(() => {window.dbFixture.allowSource = false; window.dbFixture.controller.open();});
  await page.waitForFunction(() => document.querySelector('#item-db-source').value === 'PAST_EXAM');
  assert.equal(await page.locator('#item-db-source option[value="EXTERNAL_SOURCE"]').evaluate(option => option.disabled), true);
  assert.equal(await page.locator('#item-db-similarity-results button').count(), 0, 'permission changes clear previous selections/results');
  assert.equal(await page.locator('#item-db-similarity-tab-progress').isVisible(), false);
  assert.deepEqual(errors, []);
  assert.deepEqual(unexpected, []);
  console.log("item_db_browser=PASS live_writes=0");
} finally {
  await browser.close();
}
