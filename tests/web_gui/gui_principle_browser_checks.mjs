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
  assert.deepEqual([...views].sort(), ['excel', 'chat', 'workflow', 'request', 'item', 'item-db', 'hwpx', 'control', 'admin-settings', 'account', 'learning', 'knowledge', 'knowledge-quality', 'explorer', 'quality-review', 'pdf-review', 'support', 'dashboard'].sort());
  const icons = await page.locator('.navigation .nav-item').evaluateAll(nodes => nodes.map(node => {
    const icon = node.querySelector('svg.nav-icon');
    const style = icon && getComputedStyle(icon);
    return {count: node.querySelectorAll('svg').length, label: node.textContent.trim(), box: icon?.getAttribute('viewBox'), hidden: icon?.getAttribute('aria-hidden'), width: style?.width, height: style?.height, stroke: style?.strokeWidth, fill: style?.fill};
  }));
  for (const icon of icons) {
    assert.equal(icon.count, 1, icon.label);
    assert.equal(icon.box, '0 0 24 24', icon.label);
    assert.equal(icon.hidden, 'true', icon.label);
    assert.equal(icon.width, '20px', icon.label);
    assert.equal(icon.height, '20px', icon.label);
    assert.equal(icon.stroke, '1.7px', icon.label);
    assert.equal(icon.fill, 'none', icon.label);
    assert.ok(icon.label);
  }
  // Synthetic rows exercise layout only; populated application/request tests remain separate.
  await page.evaluate(() => {
    const headings = document.getElementById('item-db-table-heading');
    const headingRow = document.createElement('tr');
    for (const label of ['고유번호', '문항 이름', '소속 단원', '승인 상태']) {
      const cell = document.createElement('th');
      cell.textContent = label;
      headingRow.append(cell);
    }
    headings.replaceChildren(headingRow);
    const rows = [1, 2, 3].map(ordinal => {
      const row = document.createElement('tr');
      if (ordinal === 1) row.className = 'is-selected';
      for (const text of [`T000${ordinal}`, '화면 배치 검사용 긴 문항 이름과 상세 설명', '여러 하위 단원명을 가진 교육과정 단원', '승인 완료']) {
        const cell = document.createElement('td');
        cell.textContent = text;
        row.append(cell);
      }
      return row;
    });
    document.getElementById('item-db-results').replaceChildren(...rows);
  });
  const checks = [];
  const dbPositions = [];
  for (const width of [1440, 1360, 1024, 390]) {
    await page.setViewportSize({width, height: 1000});
    for (const view of views) {
      await page.evaluate(view => {
        document.querySelectorAll('.view').forEach(node => node.classList.toggle('active', node.dataset.view === view));
        document.querySelectorAll('.view').forEach(node => node.removeAttribute('hidden'));
        scrollTo(0, 0);
      }, view);
      const layout = await page.evaluate(() => ({scroll: document.documentElement.scrollWidth, width: innerWidth, overflow: document.documentElement.scrollWidth > innerWidth + 1 ? [...document.querySelectorAll('.view.active *')].map(node => ({element: node.id || node.className || node.tagName, right: Math.round(node.getBoundingClientRect().right)})).filter(node => node.right > innerWidth + 1).slice(0, 8) : []}));
      checks.push({view, width, ...layout});
      // Horizontal content belongs in bounded tables, not in the page viewport.
      const active = page.locator('.view.active');
      assert.equal(await active.locator('h1').count(), 1, `${view}: one page title`);
      if (view === 'learning') {
        const box = await page.locator('#material-rights').boundingBox();
        const text = await page.locator('#material-rights + span').boundingBox();
        assert.ok(text.x >= box.x + box.width && Math.abs(text.y - box.y) < 5, 'consent stays beside its checkbox');
      }
      if (view === 'item-db') {
        const form = await page.locator('#item-db-form').boundingBox();
        const results = await page.locator('#item-db-search-panel .item-db-table-wrap').boundingBox();
        dbPositions.push({width, formHeight: Math.round(form.height), resultTop: Math.round(results.y)});
        assert.ok(form.height <= (width < 700 ? 410 : 310), `DB ${width}: filters consume ${form.height}px`);
        assert.ok(results.y < 800, `DB ${width}: results must start in the initial viewport`);
        const search = await page.locator('#item-db-search').boundingBox();
        const usage = await page.locator('.item-db-usage-filter > summary').boundingBox();
        assert.ok(Math.abs(search.y - usage.y) <= 1, `DB ${width}: search shares the usage-filter row`);
        for (const selector of ['#item-db-source', '#item-db-approval', '#item-db-filter-add', '#item-db-search', '.item-db-filter-chip']) {
          const sizes = await page.locator(selector).evaluateAll(nodes => nodes.map(node => ({height: node.getBoundingClientRect().height, font: parseFloat(getComputedStyle(node).fontSize)})));
          assert.ok(sizes.every(size => size.height >= 40 && size.font >= 13), `DB ${width}: ${selector} remains readable and usable`);
        }
      }
      if (process.env.EOM_GUI_SCREENSHOT_DIR && ['learning', 'knowledge', 'chat', 'item-db'].includes(view)) {
        await mkdir(process.env.EOM_GUI_SCREENSHOT_DIR, {recursive: true});
        await page.screenshot({path: `${process.env.EOM_GUI_SCREENSHOT_DIR}/${view}-${width}.png`, fullPage: true});
      }
    }
    // The exact-ID path stays available without occupying the default work surface.
    const opener = page.locator('.global-opener');
    const summary = opener.locator('summary');
    assert.equal(await opener.getAttribute('open'), null);
    assert.equal(await page.locator('#global-id').isVisible(), false);
    await summary.focus();
    await page.keyboard.press('Tab');
    await page.keyboard.press('Shift+Tab');
    const focus = await summary.evaluate(node => ({active: document.activeElement === node, style: getComputedStyle(node).outlineStyle, width: parseFloat(getComputedStyle(node).outlineWidth)}));
    assert.ok(focus.active && focus.style !== 'none' && focus.width >= 2, `ID disclosure ${width}: visible keyboard focus`);
    await page.keyboard.press('Enter');
    assert.equal(await page.locator('#global-id').isVisible(), true);
    const panel = await page.locator('.global-opener-panel').boundingBox();
    assert.ok(panel.x >= 0 && panel.x + panel.width <= width + 1, `ID disclosure ${width}: panel stays on-screen`);
    await page.keyboard.press('Tab');
    assert.equal(await page.locator('#global-id').evaluate(node => document.activeElement === node), true);
    await page.locator('#global-id').fill('workflow_visual_fixture');
    await page.keyboard.press('Tab');
    assert.equal(await page.locator('#global-load').evaluate(node => document.activeElement === node), true);
    await summary.focus();
    await page.keyboard.press('Space');
    assert.equal(await opener.getAttribute('open'), null);
    assert.equal(await page.locator('#global-id').inputValue(), 'workflow_visual_fixture');
    // Only presentation changes: preserve warning/error text at every tested width.
    const health = await page.locator('#api-health, #observe-health').evaluateAll(nodes => nodes.map(node => ({id: node.id, className: node.className, text: node.textContent})));
    await page.locator('#api-health, #observe-health').evaluateAll(nodes => nodes.forEach(node => {node.className = 'status-badge tone-success';}));
    if (width >= 980) {
      const normalStyles = await page.locator('#api-health, #observe-health').evaluateAll(nodes => nodes.map(node => {
        const style = getComputedStyle(node);
        return {background: style.backgroundColor, border: style.borderTopColor, weight: style.fontWeight};
      }));
      for (const style of normalStyles) {
        assert.equal(style.background, 'rgba(0, 0, 0, 0)', 'normal health has no alarm surface');
        assert.equal(style.border, 'rgba(0, 0, 0, 0)', 'normal health has no alarm border');
        assert.equal(style.weight, '500');
      }
    }
    for (const tone of ['warning', 'danger']) {
      await page.locator('#api-health, #observe-health').evaluateAll((nodes, tone) => nodes.forEach(node => {
        node.className = `status-badge tone-${tone}`;
        node.textContent = node.id === 'api-health' ? '핵심 서비스 점검 필요' : '운영 상태 미확인';
      }), tone);
      for (const selector of ['#api-health', '#observe-health']) {
        assert.equal(await page.locator(selector).isVisible(), true, `${selector} ${tone} ${width}`);
        const box = await page.locator(selector).boundingBox();
        assert.ok(box.x >= 0 && box.x + box.width <= width + 1 && box.height > 0, `${selector} ${tone} ${width}: visible bounds`);
        assert.ok((await page.locator(selector).innerText()).trim().length > 0);
      }
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `health ${tone} ${width}: no page overflow`);
    }
    await page.evaluate(health => health.forEach(value => {
      const node = document.getElementById(value.id);
      node.className = value.className;
      node.textContent = value.text;
    }), health);
  }
  const overflows = checks.filter(check => check.scroll > check.width + 1);
  assert.deepEqual(overflows, [], `view overflow: ${JSON.stringify(overflows)}`);
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
  console.log(`gui_principle_browser=PASS views=${views.length} layouts=${checks.length} db=${JSON.stringify(dbPositions)} no-live-requests`);
} finally {await browser.close();}
