import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {createRequire} from 'node:module';

const require = createRequire(import.meta.url);
const {chromium} = require(process.env.EOM_WEB_PLAYWRIGHT_MODULE);
const root = new URL('../../apps/web_gui/eom_web_gui/static/', import.meta.url);
const assets = new Map(await Promise.all(['index.html', 'styles.css', 'knowledge-map.css', 'material-learning.js', 'eom-mark.svg'].map(async name => [name, await readFile(new URL(name, root), 'utf8')])));
const app = `
import {createMaterialLearning} from './material-learning.js';
const runId = 'materialrun_' + '1'.repeat(32);
const fixture = window.fixture = {calls: [], runs: [], failCreate: true, held: false, release: null};
async function api(path, options = {}) {
  fixture.calls.push({path, key: options.headers?.['Idempotency-Key'], body: options.body instanceof File ? options.body.name : options.body});
  if (path.startsWith('/material-learning/sources?')) return {original_filename: options.body.name, source_format: 'PDF'};
  if (path === '/material-learning' && options.method === 'POST') {
    if (fixture.failCreate) { fixture.failCreate = false; throw new Error('일시적인 접수 오류'); }
    fixture.runs = [{run_id: runId, title: options.body.upload.title, material_kind: 'WORKBOOK', state: 'PROCESSING', task_counts: [{state: 'COMPLETED', count: 2}, {state: 'RUNNING', count: 1}], created_at: '2026-11-05T20:00:00Z'}];
    return {run_id: runId};
  }
  if (path === '/material-learning') return {runs: fixture.runs};
  if (fixture.held) {fixture.held = false; await new Promise(resolve => fixture.release = resolve);}
  return {run: fixture.runs[0], tasks: [{task_kind: 'QUESTION', state: 'RUNNING', error_code: null}], next_ordinal: null};
}
const controller = createMaterialLearning({document, api});
controller.install(); controller.setOwner('owner'); controller.open(); fixture.controller = controller;
document.querySelectorAll('.view').forEach(view => view.classList.toggle('active', view.dataset.view === 'learning'));
`;
const server = createServer((request, response) => {
  const name = (request.url || '').split('/').pop().split('?')[0] || 'index.html';
  const content = name === 'app.js' ? app : assets.get(name);
  if (content === undefined) {response.writeHead(404); response.end(); return;}
  response.setHeader('Content-Type', name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : name.endsWith('.svg') ? 'image/svg+xml' : 'text/html');
  response.end(content);
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const browser = await chromium.launch({headless: true});
try {
  const page = await browser.newPage({viewport: {width: 1440, height: 1100}});
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto('http://127.0.0.1:' + server.address().port + '/studio/');
  await page.locator('#material-title').fill('혼합 교재 테스트');
  await page.locator('#material-description').fill('내부 검증용 합성 자료');
  await page.locator('#material-main').setInputFiles({name: '문제.hwp', mimeType: 'application/octet-stream', buffer: Buffer.from('%PDF-1.7\nmain')});
  await page.locator('#material-solutions').setInputFiles({name: '해설.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.7\nsolutions')});
  await page.locator('#material-rights').check();
  await page.locator('#material-learning-start').click();
  await page.waitForFunction(() => document.querySelector('#material-learning-message').textContent.includes('접수하지 못했습니다'));
  assert.equal(await page.evaluate(() => fixture.calls.filter(call => call.path.startsWith('/material-learning/sources?')).length), 2);
  await page.locator('#material-learning-start').click();
  await page.waitForFunction(() => document.querySelector('#material-learning-runs').textContent.includes('혼합 교재 테스트'));
  assert.equal(await page.evaluate(() => fixture.calls.filter(call => call.path.startsWith('/material-learning/sources?')).length), 2, 'retry recopied original sources');
  const submissions = await page.evaluate(() => fixture.calls.filter(call => call.body?.idempotency_key));
  assert.equal(submissions.length, 2);
  assert.deepEqual(submissions[0].body, submissions[1].body, 'retry changed the durable request');
  assert.match(await page.locator('#material-learning-runs').textContent(), /2\/3 단계/);
  await page.getByRole('button', {name: '상세 보기', exact: true}).click();
  assert.match(await page.locator('#material-learning-detail').textContent(), /문항 읽는 중/);
  await page.evaluate(() => {fixture.held = true; fixture.release = null;});
  await page.getByRole('button', {name: '상세 보기', exact: true}).click();
  await page.waitForFunction(() => fixture.release !== null);
  await page.evaluate(() => {fixture.controller.setOwner('new-owner'); fixture.release();});
  await page.waitForTimeout(100);
  assert.equal(await page.locator('#material-learning-detail').textContent(), '');
  assert.equal(await page.locator('#material-learning-runs').textContent(), '');
  assert.deepEqual(errors, []);
  console.log('MATERIAL_LEARNING_BROWSER=PASS upload-pair same-request-retry no-source-recopy progress stale-owner live-writes=0');
} finally {await browser.close(); await new Promise(resolve => server.close(resolve));}
