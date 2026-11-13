import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {createServer} from "node:http";
import {createRequire} from "node:module";
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.EOM_WEB_PLAYWRIGHT_MODULE);
const root = new URL("../../apps/web_gui/eom_web_gui/static/", import.meta.url);
const names = ["index.html", "styles.css", "content-planning.css", "content-planning-import.js", "knowledge-map.css", "eom-mark.svg"];
const assets = new Map(await Promise.all(names.map(async name => [name, await readFile(new URL(name, root), "utf8")])));
const application = `
import {createContentWorkbookImport} from './content-planning-import.js';
const id = (prefix, n = 1) => prefix + '_' + n.toString(16).padStart(32, '0');
const sha = 'sha256:' + 'a'.repeat(64);
const f = window.fixture = {calls: [], opens: [], unresolved: false, printed: true, total: 101, hold: null, release: null, fail: false, forbidden: null, owner: 'operator-a', localBlocked: false};
f.pointer = {artifact_id: id('artifact'), artifact_revision_id: id('rev'), member_path: 'proposal.json', schema_ref: 'eom://schemas/content-planning/workbook-proposal/1.0', media_type: 'application/json', sha256: sha};
function preview(offset = 0) {
  const unresolved = f.unresolved, end = Math.min(offset + 100, f.total);
  return {schema_version: 'content-workbook-preview/1.0', proposal: {...f.pointer}, original_filename: '교재.xlsx', workbook_sha256: sha,
    metadata: {content_title: '<img src=x onerror=alert(1)> 검증 교재', content_type: 'TEXTBOOK', edition_label: '2027 초판', academic_year: 2027, print_status: f.printed ? 'PRINTED' : 'NOT_PRINTED', printed_on: f.printed ? '2026-11-01' : null},
    total_rows: f.total, matched_rows: f.total - (unresolved ? 1 : 0), unresolved_rows: unresolved ? 1 : 0, duplicate_uses: f.total > 1 ? 1 : 0,
    can_commit: !unresolved, offset, next_offset: end < f.total ? end : null,
    rows: Array.from({length: end - offset}, (_, i) => ({row: {row_number: offset + i + 2, group_label: '역학', section_label: '1회차', display_number: String(offset + i + 1), external_number: '10321', points_milli: 2500, note: '<script>bad()</script>'}, resolution: {row_number: offset + i + 2, status: unresolved && i === 0 ? 'MISSING' : 'MATCHED', title: unresolved && i === 0 ? null : '합성 문항', target: null}}))};
}
async function api(path, options = {}) {
  f.calls.push({path, body: options.body instanceof File ? {file: options.body.name, size: options.body.size} : structuredClone(options.body), key: options.headers?.['Idempotency-Key'], mutation: options.mutation});
  const kind = path.endsWith('/commit') ? 'commit' : path.endsWith('/query') ? 'query' : 'upload';
  if (f.hold === kind) {f.hold = null; await new Promise(resolve => f.release = resolve);}
  if (kind === 'upload' && f.failUpload) {f.failUpload = false; throw new Error('합성 업로드 시간 초과');}
  const code = kind === 'commit' ? f.rejectCode : kind === 'query' ? f.queryCode : null;
  if (code) {const error = new Error('합성 서버 거절'); error.code = code; throw error;}
  if (kind === 'commit') {
    if (f.fail) {f.fail = false; throw new Error('합성 응답 지연');}
    return {schema_version: 'content-workbook-import-result/1.0', disposition: 'IMPORTED', replayed: false,
      composition: {edition_id: id('edition'), deliverable_id: id('deliverable'), deliverable_revision_id: id('delivrev'), content_title: '가져온 교재', edition_label: '2027 초판'}, current_revision_id: id('delivrev'), print_record_id: f.printed ? id('print') : null};
  }
  const result = preview(kind === 'query' ? options.body.offset : 0);
  if (f.mismatch && kind === 'query') result.proposal.artifact_revision_id = id('rev', 99);
  return result;
}
function mount() {
  const previous = document.getElementById('excel-import-panel');
  const copy = previous.cloneNode(true); previous.replaceWith(copy);
  f.ui = createContentWorkbookImport({document, api, can: permission => permission !== f.forbidden, storage: sessionStorage,
    isBlocked: () => f.localBlocked, onImported: result => {f.opens.push(structuredClone(result));},
    confirm: text => {f.confirmations = [...(f.confirmations || []), text]; return f.confirmResult !== false;}});
  f.ui.install(); f.ui.setOwner(f.owner); f.ui.open();
}
f.mount = mount;
document.querySelectorAll('.view').forEach(view => view.classList.toggle('active', view.dataset.view === 'excel'));
document.getElementById('excel-import-panel').open = true;
mount();
window.ready = true;
`;
const server = createServer((request, response) => {
  const name = request.url === "/studio/" ? "index.html" : request.url.split("/").pop();
  let content = name === "app.js" ? application : assets.get(name);
  if (!content) {response.writeHead(404); response.end(); return;}
  response.setHeader("Content-Type", name.endsWith(".js") ? "text/javascript" : name.endsWith(".css") ? "text/css" : name.endsWith(".svg") ? "image/svg+xml" : "text/html");
  response.end(content);
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const browser = await chromium.launch({headless: true});
try {
  const page = await browser.newPage({viewport: {width: 1440, height: 1100}});
  const errors = []; page.on("pageerror", error => errors.push(error.message));
  await page.goto(`http://127.0.0.1:${server.address().port}/studio/`);
  await page.waitForFunction(() => window.ready);
  const upload = async () => {
    await page.locator("#excel-import-file").setInputFiles({name: "교재.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: Buffer.from("PKsynthetic-xlsx")});
    await page.locator("#excel-import-read").click();
    await page.waitForFunction(() => !document.getElementById("excel-import-refresh").disabled);
  };
  await upload();
  assert.equal(await page.locator("#excel-import-rows tr").count(), 100);
  assert.equal(await page.locator("#excel-import-title img").count(), 0);
  assert.match(await page.locator("#excel-import-title").textContent(), /<img/);
  assert.match(await page.locator("#excel-import-confirm-label").textContent(), /인쇄 기록.*2026-11-01/);
  assert.equal(await page.locator("#excel-import-save").isDisabled(), true);
  assert.equal(await page.evaluate(() => fixture.calls.filter(c => c.path.endsWith("/commit")).length), 0);
  await page.locator("#excel-import-confirm").check();
  await page.locator("#excel-import-next").click();
  await page.waitForFunction(() => document.getElementById("excel-import-page").textContent === "101–101 / 101");
  assert.equal(await page.locator("#excel-import-rows tr").count(), 1);
  assert.equal(await page.locator("#excel-import-confirm").isChecked(), true);
  assert.equal(await page.evaluate(() => fixture.calls.filter(c => c.path.includes("original_filename")).length), 1);
  await page.locator("#excel-import-previous").click();
  await page.waitForFunction(() => document.getElementById("excel-import-rows").children.length === 100);
  await page.evaluate(() => {fixture.fail = true;});
  await page.locator("#excel-import-save").click();
  await page.waitForFunction(() => document.getElementById("excel-import-message").textContent.includes("合成") || document.getElementById("excel-import-message").textContent.includes("합성 응답 지연"));
  assert.equal(await page.locator("#excel-import-file").isDisabled(), true);
  const key = await page.evaluate(() => fixture.calls.find(c => c.path.endsWith("/commit")).key);
  assert.equal(await page.evaluate(() => {const saved = JSON.parse(sessionStorage.getItem('eom:excel:workbook:1:operator-a')); return Object.keys(saved).sort().join(',');}), "key,proposal");
  await page.evaluate(() => fixture.mount());
  await page.waitForFunction(() => document.getElementById("excel-import-message").textContent.includes("이전 저장 요청"));
  assert.equal(await page.evaluate(() => fixture.calls.filter(c => c.path.endsWith("/commit")).length), 1);
  await page.locator("#excel-import-save").click();
  await page.waitForFunction(() => fixture.opens.length === 1);
  assert.deepEqual(await page.evaluate(() => fixture.calls.filter(c => c.path.endsWith("/commit")).map(c => c.key)), [key, key]);
  assert.equal(await page.evaluate(() => sessionStorage.getItem('eom:excel:workbook:1:operator-a')), null);
  assert.equal(await page.locator("#excel-import-preview").isHidden(), true);
  await page.locator("#excel-import-open").click();
  await page.waitForFunction(() => fixture.opens.length === 2);
  assert.equal(await page.evaluate(() => fixture.calls.filter(c => c.path.endsWith("/commit")).length), 2);

  // Missing numbers never cause partial commit; file changes require a new preview.
  await page.evaluate(() => {fixture.unresolved = true; fixture.total = 1;});
  await upload();
  assert.match(await page.locator("#excel-import-notice").textContent(), /일부 문항만 저장하지 않습니다/);
  assert.equal(await page.locator("#excel-import-save").isDisabled(), true);
  assert.match(await page.locator("#excel-import-rows").textContent(), /DB에 없는 고유번호/);

  // Restoring another owner must not show the preceding owner's file or rows.
  await page.evaluate(() => {fixture.ui.setOwner('operator-b'); fixture.owner = 'operator-b';});
  assert.equal(await page.locator("#excel-import-preview").isHidden(), true);
  await page.evaluate(() => {fixture.unresolved = false; fixture.hold = 'upload';});
  await page.locator("#excel-import-file").setInputFiles({name: "교재.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: Buffer.from("PKsynthetic-xlsx")});
  await page.locator("#excel-import-read").click();
  await page.waitForFunction(() => fixture.release !== null);
  await page.evaluate(() => {fixture.ui.setOwner('operator-c'); fixture.owner = 'operator-c'; fixture.release(); fixture.release = null;});
  await page.waitForTimeout(50);
  assert.equal(await page.locator("#excel-import-preview").isHidden(), true);
  assert.equal(await page.evaluate(() => sessionStorage.getItem('eom:excel:workbook:1:operator-c')), null);

  // Permission and response-pointer checks do not rely on button rendering alone.
  await upload();
  await page.evaluate(() => {fixture.forbidden = 'usage:fulfill_plan'; fixture.ui.sync();});
  await page.locator("#excel-import-confirm").check();
  assert.equal(await page.locator("#excel-import-save").isDisabled(), true);
  await page.evaluate(() => {fixture.forbidden = null; fixture.mismatch = true; fixture.ui.sync();});
  await page.locator("#excel-import-refresh").click();
  await page.waitForFunction(() => document.getElementById("excel-import-message").textContent.includes("요청한 엑셀의 연결 내역과 다릅니다"));
  // Selecting a new file must invalidate the old preview and its confirmation.
  // A retry of the same still-selected upload retains its original replay key.
  await page.evaluate(() => {fixture.mismatch = false; fixture.failUpload = true;});
  await page.locator("#excel-import-file").setInputFiles({name: "교재.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: Buffer.from("PKsynthetic-xlsx")});
  assert.equal(await page.locator("#excel-import-preview").isHidden(), true);
  assert.equal(await page.locator("#excel-import-confirm").isChecked(), false);
  await page.locator("#excel-import-read").click();
  await page.waitForFunction(() => document.getElementById("excel-import-message").textContent.includes("합성 업로드 시간 초과"));
  const uploadKey = await page.evaluate(() => fixture.calls.at(-1).key);
  await page.locator("#excel-import-read").click();
  await page.waitForFunction(() => !document.getElementById("excel-import-preview").hidden);
  assert.equal(await page.evaluate(() => fixture.calls.at(-1).key), uploadKey);
  // A terminal owner rejection may happen on replay of an earlier commit.
  // Let users inspect Excel and explicitly close only the local replay pin;
  // never claim nothing was saved and never automatically make another import.
  await page.evaluate(() => {fixture.rejectCode = 'CURATED_SOURCE_STALE';});
  await page.locator("#excel-import-confirm").check();
  await page.locator("#excel-import-save").click();
  await page.waitForFunction(() => document.getElementById("excel-import-message").textContent.includes("이미 저장됐을 수"));
  assert.equal(await page.evaluate(() => fixture.ui.locked()), false);
  assert.equal(await page.locator("#excel-import-save").isDisabled(), true);
  assert.equal(await page.locator("#excel-import-file").isDisabled(), true);
  assert.equal(await page.locator("#excel-import-clear").isEnabled(), true);
  assert.match(await page.locator("#excel-import-clear").textContent(), /기존 저장 확인/);
  const rejectedCalls = await page.evaluate(() => fixture.calls.length);
  const rejectedPin = await page.evaluate(() => sessionStorage.getItem('eom:excel:workbook:1:operator-c'));
  await page.evaluate(() => {fixture.confirmResult = false;});
  await page.locator("#excel-import-clear").click();
  assert.equal(await page.evaluate(() => sessionStorage.getItem('eom:excel:workbook:1:operator-c')), rejectedPin);
  await page.evaluate(() => {fixture.confirmResult = true;});
  await page.locator("#excel-import-clear").click();
  assert.equal(await page.evaluate(() => sessionStorage.getItem('eom:excel:workbook:1:operator-c')), null);
  assert.equal(await page.evaluate(() => fixture.calls.length), rejectedCalls);
  assert.equal(await page.locator("#excel-import-preview").isHidden(), true);
  assert.equal(await page.locator("#excel-import-file").inputValue(), "");
  assert.match(await page.evaluate(() => fixture.confirmations.at(-1)), /서버 기록은 삭제하지 않습니다/);

  // A historical proposal may be valid V1 but exceed the actual Edition tree
  // bound. Its read rejection must remove the old "ready" preview, not leave
  // a save button enabled; server Artifact/receipt identities stay untouched.
  await upload();
  await page.locator("#excel-import-confirm").check();
  const boundedPin = await page.evaluate(() => sessionStorage.getItem('eom:excel:workbook:1:operator-c'));
  await page.evaluate(() => {fixture.queryCode = 'CONTENT_WORKBOOK_STRUCTURE_TOO_LARGE';});
  await page.locator("#excel-import-refresh").click();
  await page.waitForFunction(() => document.getElementById("excel-import-message").textContent.includes("합성 서버 거절"));
  assert.equal(await page.locator("#excel-import-preview").isHidden(), true);
  assert.equal(await page.locator("#excel-import-save").isDisabled(), true);
  assert.equal(await page.locator("#excel-import-clear").isEnabled(), true);
  assert.equal(await page.evaluate(() => sessionStorage.getItem('eom:excel:workbook:1:operator-c')), boundedPin);
  await page.locator("#excel-import-clear").click();
  await page.evaluate(() => {fixture.queryCode = null;});

  // Timeout, invalid response and an unknown source-prefixed code are NOT
  // terminal-rejection proof. They retain the exact pending command/key.
  for (const code of ["HTTP_504", "APPLICATION_API_RESPONSE_INVALID", "CURATED_SOURCE_OTHER"]) {
    await page.evaluate(code => {fixture.rejectCode = code;}, code);
    await upload();
    await page.locator("#excel-import-confirm").check();
    await page.locator("#excel-import-save").click();
    await page.waitForFunction(() => document.getElementById("excel-import-message").textContent.includes("같은 저장 요청 다시 확인"));
    assert.equal(await page.evaluate(() => fixture.ui.locked()), true);
    assert.equal(await page.locator("#excel-import-clear").isDisabled(), true);
    const retryKey = await page.evaluate(() => fixture.calls.at(-1).key);
    await page.evaluate(() => {fixture.rejectCode = null;});
    await page.locator("#excel-import-save").click();
    await page.waitForFunction(() => document.getElementById("excel-import-preview").hidden);
    assert.equal(await page.evaluate(() => fixture.calls.at(-1).key), retryKey);
  }
  // A restored pending command can receive a definitive owner rejection even
  // before its preview loads. The same explicit close remains available.
  await upload();
  await page.evaluate(() => {fixture.rejectCode = 'HTTP_504';});
  await page.locator("#excel-import-confirm").check();
  await page.locator("#excel-import-save").click();
  await page.waitForFunction(() => document.getElementById("excel-import-message").textContent.includes("같은 저장 요청 다시 확인"));
  await page.evaluate(() => {fixture.queryCode = 'CONTENT_WORKBOOK_PROPOSAL_OWNER_MISMATCH'; fixture.mount();});
  await page.waitForFunction(() => document.getElementById("excel-import-message").textContent.includes("이미 저장됐을 수"));
  assert.equal(await page.locator("#excel-import-clear").isEnabled(), true);
  assert.equal(await page.evaluate(() => fixture.ui.locked()), false);
  await page.locator("#excel-import-clear").click();
  assert.equal(await page.evaluate(() => sessionStorage.getItem('eom:excel:workbook:1:operator-c')), null);
  assert.equal(errors.length, 0, errors.join("\n"));
  console.log("CONTENT_WORKBOOK_IMPORT_BROWSER=PASS live_writes=0 cases=explicit-save,paging,pointer,owner,print,replay,xss,missing,open,new-file,upload-retry,known-rejection-close,unknown-replay-fence,structure-limit");
} finally {await browser.close(); server.close();}
