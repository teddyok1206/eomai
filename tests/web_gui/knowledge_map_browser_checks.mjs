import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {createRequire} from 'node:module';

const require = createRequire(import.meta.url);
const {chromium} = require(process.env.EOM_WEB_PLAYWRIGHT_MODULE);
const root = new URL('../../apps/web_gui/eom_web_gui/static/', import.meta.url);
const assets = new Map(await Promise.all(['index.html', 'styles.css', 'knowledge-map.css', 'knowledge-map.js', 'eom-mark.svg'].map(async name => [name, await readFile(new URL(name, root), 'utf8')])));
const app = `
import {createKnowledgeMap} from './knowledge-map.js';
const ids = ['a','b','c','d','5'].map(value => 'knode_' + value.repeat(32));
const snapshot = 'graphrev_' + 'e'.repeat(32), hash = 'sha256:' + 'f'.repeat(64);
const fixture = window.fixture = {calls: [], opens: [], held: null, release: null};
const nodes = ids.map((node_id, i) => ({node_id, node_type: i ? 'ITEM_REVISION' : 'CONCEPT', label: ['전자기 유도', '기출 문항', '창작 문항', 'AI 문항', '외부 교재 문항'][i], layers: i === 0 ? ['PAST_EXAM', 'TEXTBOOK'] : [i === 1 ? 'PAST_EXAM' : i === 2 ? 'CREATIVE' : i === 3 ? 'AI' : 'EXTERNAL']}));
const edges = ids.slice(1, 4).map((id, i) => ({edge_id: 'kedge_' + String(i + 1).repeat(32), from_node_id: ids[0], to_node_id: id, edge_type: 'ASSESSES_CONCEPT'}));
const base = {schema_version: 'knowledge-map-view/2.0', graph_snapshot_revision_id: snapshot, snapshot_sha256: hash, nodes: nodes.slice(0, 4), edges, sources: [], focus_node_id: null, selected_edge_id: null, truncated: false, total_nodes: 40000, total_edges: 80000};
async function api(path) {
  fixture.calls.push(path);
  if (path.startsWith('/knowledge-map/items/')) return {item_id: 'item_' + '1'.repeat(32), item_revision_id: 'itemrev_' + '2'.repeat(32)};
  const params = new URL('http://fixture' + path).searchParams;
  if (fixture.held && params.get('node_id') === fixture.held) {fixture.held = null; await new Promise(resolve => fixture.release = resolve);}
  if (fixture.heldLayer && params.get('layer') === fixture.heldLayer) {fixture.heldLayer = null; await new Promise(resolve => fixture.layerRelease = resolve);}
  const source = {source_revision_id: 'itemrev_' + '2'.repeat(32), item_id: 'item_' + '1'.repeat(32), item_manifest_sha256: hash, source_class: params.get('layer') === 'EXTERNAL' ? 'APPROVED_ITEM' : 'PAST_EXAM', layer: params.get('layer') || 'PAST_EXAM', analysis_run_id: 'analysisrun_' + '3'.repeat(32), source_artifact_id: 'artifact_' + '4'.repeat(32), artifact_revision_id: 'rev_' + '5'.repeat(32), source_sha256: hash, anchor_id: 'source-anchor', excerpt_sha256: hash, available: true, title: '합성 문항'};
  return {...structuredClone(base), ...(params.get('layer') === 'EXTERNAL' ? {nodes: [nodes[4]], edges: []} : {}), focus_node_id: params.get('node_id'), selected_edge_id: params.get('edge_id'), sources: params.has('node_id') || params.has('edge_id') ? [source] : []};
}
const controller = createKnowledgeMap({document, api, openItem: entry => fixture.opens.push(entry), previewItem: async (_pointer, root, isCurrent) => {if (isCurrent()) root.textContent = '합성 문항 미리보기';}});
controller.install(); controller.setOwner('owner'); controller.open(); fixture.controller = controller;
document.querySelectorAll('.view').forEach(view => view.classList.toggle('active', view.dataset.view === 'knowledge'));
`;
const server = createServer((request, response) => {
  let name = (request.url || '').split('/').pop().split('?')[0] || 'index.html';
  const content = name === 'app.js' ? app : assets.get(name);
  if (content === undefined) {response.writeHead(404); response.end(); return;}
  response.setHeader('Content-Type', name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : name.endsWith('.svg') ? 'image/svg+xml' : 'text/html');
  response.end(content);
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const browser = await chromium.launch({headless: true});
try {
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto('http://127.0.0.1:' + server.address().port + '/studio/');
  await page.waitForFunction(() => document.querySelectorAll('.map-node').length === 4);
  assert.equal(await page.locator('.map-layer-ring').count(), 2);
  assert.equal(await page.locator('[data-view-target="knowledge"]').textContent().then(value => value.trim()), '⌬ Map');
  const navLabels = await page.locator('.nav-group-label, .nav-item').allTextContents();
  assert(navLabels.findIndex(value => value.trim() === '⌬ Map') > navLabels.findIndex(value => value.trim() === '데이터'));
  assert(navLabels.findIndex(value => value.trim() === '⌬ Map') < navLabels.findIndex(value => value.trim() === '운영 도구'));
  await page.locator('.map-node').first().click();
  await page.getByRole('button', {name: 'DB에서 문항 열기', exact: true}).waitFor();
  await page.getByRole('button', {name: '미리보기', exact: true}).click();
  assert.match(await page.locator('.map-preview').textContent(), /합성 문항 미리보기/);
  await page.getByRole('button', {name: 'DB에서 문항 열기', exact: true}).click();
  assert.equal(await page.evaluate(() => fixture.opens.length), 1);
  await page.getByRole('button', {name: '주변 연결 펼치기'}).click();
  await page.locator('.map-edge').first().click();
  await page.waitForFunction(() => document.querySelector('#map-inspector h2').textContent === '평가하는 개념');
  await page.locator('#map-layer').selectOption('CREATIVE');
  await page.waitForFunction(() => document.querySelectorAll('.map-node').length === 1);
  assert(await page.evaluate(() => fixture.calls.some(value => new URL('http://fixture' + value).searchParams.get('layer') === 'CREATIVE')));
  await page.locator('#map-layer-controls button[data-layer="EXTERNAL"]').click();
  await page.waitForFunction(() => document.querySelector('[data-node-id="knode_' + '5'.repeat(32) + '"]'));
  assert.equal(await page.locator('#map-layer').inputValue(), 'EXTERNAL');
  assert.equal(await page.locator('#map-layer-controls button[data-layer="EXTERNAL"]').getAttribute('aria-pressed'), 'true');
  await page.locator('.map-node[data-layer="EXTERNAL"]').click();
  await page.waitForFunction(() => document.querySelector('.map-source strong')?.textContent.includes('외부'));
  await page.locator('#map-layer').selectOption('');
  await page.waitForFunction(() => document.querySelectorAll('.map-node').length === 4);
  await page.evaluate(() => {fixture.heldLayer = 'EXTERNAL'; fixture.layerRelease = null;});
  await page.locator('#map-layer').selectOption('EXTERNAL');
  await page.waitForFunction(() => fixture.layerRelease !== null);
  await page.locator('#map-layer').selectOption('AI');
  await page.waitForFunction(() => document.querySelector('.map-node[data-layer="AI"]'));
  await page.evaluate(() => fixture.layerRelease());
  await page.waitForTimeout(50);
  assert.equal(await page.locator('.map-node').count(), 1);
  assert.equal(await page.locator('.map-node').getAttribute('data-layer'), 'AI');
  await page.locator('#map-layer').selectOption('');
  await page.waitForFunction(() => document.querySelectorAll('.map-node').length === 4);
  await page.locator('#map-query').fill('전자기 유도');
  await page.locator('#map-search').getByRole('button', {name: '찾기', exact: true}).click();
  await page.waitForFunction(() => fixture.calls.some(value => value.includes('query=')));
  const calls = await page.evaluate(() => fixture.calls);
  assert(calls.filter(value => value.includes('node_id=') || value.includes('edge_id=')).every(value => value.includes('graph_snapshot_revision_id=') && value.includes('snapshot_sha256=')));
  await page.evaluate(() => {fixture.held = 'knode_' + 'a'.repeat(32); fixture.release = null;});
  await page.locator('[data-node-id="knode_' + 'a'.repeat(32) + '"]').click();
  await page.waitForFunction(() => fixture.release !== null);
  await page.locator('#map-layer').selectOption('EXTERNAL');
  await page.waitForFunction(() => document.querySelector('.map-node[data-layer="EXTERNAL"]'));
  await page.evaluate(() => fixture.release());
  await page.waitForTimeout(50);
  assert.equal(await page.locator('.map-source').count(), 0);
  await page.locator('#map-layer').selectOption('');
  await page.waitForFunction(() => document.querySelectorAll('.map-node').length === 4);
  await page.evaluate(() => {fixture.release = null;});
  await page.evaluate(() => {fixture.held = 'knode_' + 'a'.repeat(32);});
  await page.locator('[data-node-id="knode_' + 'a'.repeat(32) + '"]').click();
  await page.waitForFunction(() => fixture.release !== null);
  await page.evaluate(() => {fixture.controller.setOwner('new-owner'); fixture.release();});
  await page.waitForTimeout(100);
  assert.equal(await page.locator('.map-node').count(), 0);
  assert(!await page.locator('#map-inspector').textContent().then(value => value.includes('합성 문항')));
  assert.deepEqual(errors, []);
  console.log('MAP_BROWSER=PASS navigation search node edge expansion preview DB handoff layer stale-account');
} finally {await browser.close(); await new Promise(resolve => server.close(resolve));}
