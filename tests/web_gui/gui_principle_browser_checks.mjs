import assert from 'node:assert/strict';
import {readFile, mkdir} from 'node:fs/promises';
import {createRequire} from 'node:module';

const require = createRequire(import.meta.url);
const {chromium} = require(process.env.EOM_WEB_PLAYWRIGHT_MODULE);
const root = new URL('../../apps/web_gui/eom_web_gui/static/', import.meta.url);
const names = ['index.html', 'login.html', 'styles.css', 'knowledge-map.css', 'content-planning.css', 'guide-content.js', 'guide-mode.js', 'eom-mark.svg'];
const assets = new Map(await Promise.all(names.map(async name => [name, await readFile(new URL(name, root), 'utf8')])));
const browser = await chromium.launch({headless: true});
try {
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}, reducedMotion: 'reduce'});
  const errors = [], unexpected = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('https://design.invalid/**', route => {
    const path = new URL(route.request().url()).pathname;
    const name = path === '/studio/' ? 'index.html' : path.split('/').at(-1);
    if (name === 'app.js') return route.fulfill({contentType: 'text/javascript', body: 'import {installGuideMode} from "./guide-mode.js"; installGuideMode(); window.ready=true;'});
    if (name === 'login.js') return route.fulfill({contentType: 'text/javascript', body: ''});
    if (!assets.has(name)) {unexpected.push(path); return route.abort();}
    return route.fulfill({body: assets.get(name), contentType: name.endsWith('.html') ? 'text/html' : name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : 'image/svg+xml'});
  });
  await page.goto('https://design.invalid/studio/');
  await page.waitForFunction(() => window.ready);
  const views = await page.locator('.view').evaluateAll(nodes => nodes.map(node => node.dataset.view));
  const checks = [];
  for (const width of [1440, 390]) {
    await page.setViewportSize({width, height: 1000});
    for (const view of views) {
      await page.evaluate(view => {
        document.querySelectorAll('.view').forEach(node => node.classList.toggle('active', node.dataset.view === view));
        document.querySelectorAll('.view').forEach(node => node.removeAttribute('hidden'));
        scrollTo(0, 0);
      }, view);
      const layout = await page.evaluate(() => ({scroll: document.documentElement.scrollWidth, width: innerWidth}));
      checks.push({view, width, ...layout});
      // Horizontal content belongs in bounded tables, not in the page viewport.
      assert.ok(layout.scroll <= width + 1, `${view} at ${width}: page width ${layout.scroll}`);
      const active = page.locator('.view.active');
      assert.equal(await active.locator('h1').count(), 1, `${view}: one page title`);
      if (view === 'learning') {
        const box = await page.locator('#material-rights').boundingBox();
        const text = await page.locator('#material-rights + span').boundingBox();
        assert.ok(text.x >= box.x + box.width && Math.abs(text.y - box.y) < 5, 'consent stays beside its checkbox');
      }
      if (process.env.EOM_GUI_SCREENSHOT_DIR && ['learning', 'knowledge', 'chat', 'item-db'].includes(view)) {
        await mkdir(process.env.EOM_GUI_SCREENSHOT_DIR, {recursive: true});
        await page.screenshot({path: `${process.env.EOM_GUI_SCREENSHOT_DIR}/${view}-${width}.png`, fullPage: true});
      }
    }
  }
  await page.setViewportSize({width: 1440, height: 1000});
  const layerColors = await page.locator('#map-layer-controls button:not([data-layer=""])').evaluateAll(nodes => nodes.map(node => getComputedStyle(node, '::before').backgroundColor));
  assert.equal(new Set(layerColors).size, 5, 'legend must retain the five actual layer colors');
  for (const [view, selectors] of Object.entries({learning: ['#material-title', '#material-kind', '#material-main', '#material-instructions'], knowledge: ['#map-query', '#map-layer'], chat: ['#chat-knowledge-query', '#chat-knowledge-exam-year']})) {
    await page.evaluate(view => document.querySelectorAll('.view').forEach(node => node.classList.toggle('active', node.dataset.view === view)), view);
    for (const selector of selectors) {
      const style = await page.locator(selector).evaluate(node => {
        const s = getComputedStyle(node); return {radius: s.borderRadius, height: parseFloat(s.minHeight), font: parseFloat(s.fontSize)};
      });
      assert.equal(style.radius, '10px', selector);
      assert.ok(style.height >= 40 && style.font >= 13, selector);
    }
  }
  await page.evaluate(() => document.querySelectorAll('.view').forEach(node => node.classList.toggle('active', node.dataset.view === 'learning')));
  const rights = await page.locator('#material-rights').boundingBox();
  assert.ok(rights.width <= 20 && rights.height <= 20, 'checkbox must not become a text input');
  const mainFile = await page.locator('#material-main').boundingBox(), solutionFile = await page.locator('#material-solutions').boundingBox();
  assert.equal(mainFile.y, solutionFile.y, 'paired file inputs must align despite optional label');
  const before = await page.locator('#material-title').boundingBox();
  assert.equal(await page.locator('#guide-mode-toggle').getAttribute('aria-checked'), 'false');
  await page.locator('#guide-mode-toggle').click();
  await page.locator('#material-title').focus();
  await page.locator('#guide-tooltip').waitFor({state: 'visible'});
  assert.match(await page.locator('#guide-tooltip').innerText(), /출처 설명/);
  assert.deepEqual(await page.locator('#material-title').boundingBox(), before, 'guide must not move content');
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#guide-tooltip').isVisible(), false);
  await page.locator('#guide-mode-toggle').click();
  await page.goto('https://design.invalid/login.html');
  assert.ok(await page.locator('input[type="password"]').evaluate(node => node.getBoundingClientRect().height >= 44));
  assert.deepEqual(errors, []);
  assert.deepEqual(unexpected, []);
  console.log(`gui_principle_browser=PASS views=${views.length} layouts=${checks.length} no-live-requests`);
} finally {await browser.close();}
