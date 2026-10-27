import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {createRequire} from "node:module";

const require = createRequire(import.meta.url);
const {chromium} = require(process.env.EOM_WEB_PLAYWRIGHT_MODULE);
const staticRoot = new URL("../../apps/web_gui/eom_web_gui/static/", import.meta.url);
const names = ["index.html", "styles.css", "curriculum-selector.js", "studio-permissions.js", "eom-mark.svg"];
const assets = new Map(await Promise.all(names.map(async name => [name, await readFile(new URL(name, staticRoot), "utf8")])));
const app = await readFile(new URL("app.js", staticRoot), "utf8");
const handlers = app.slice(app.indexOf("function replaceCurriculumOptions("), app.indexOf("function installWorkflow()"));
const outline = JSON.parse(await readFile(new URL("../../content/curriculum/eom-integrated-science-editorial-outline-v1.json", import.meta.url), "utf8"));

// Only the API adapter and unrelated navigation/Workflow reads are fixtures. The form,
// CSS, curriculum module and request handlers are the exact repository implementation.
const fixtureApp = `
import {curriculumAncestors, curriculumOptionsForSelection, deepestCurriculumUnitKey,
  reconcileCurriculumSelection} from './curriculum-selector.js';
import {hasPermission} from './studio-permissions.js';
const $ = selector => document.querySelector(selector);
// The request form shares curriculum delivery with the independent DB screen.
// This fixture exercises the form, not the DB controller (covered separately).
const itemDb = {setCurriculumUnits() {}};
const state = {
  operator: {effective_permissions: ['workflow:start']}, draft: null,
  draftAction: null, draftEditorRevision: 0, variationSourceEntry: null,
  curriculumOutline: {...${JSON.stringify(outline)}, graph_grounding_available: true},
  curriculumUnitsByKey: new Map(), curriculumSelection: {large: '', middle: '', small: ''},
};
const drafts = new Map();
const fixture = window.requestFixture = {
  state, calls: [], workflowLoads: 0, draftSequence: 0, submissions: [],
  holdNext: null, release: null, blocked: false,
  pendingReplies: 0, preparationKeys: [],
};
const actualTimeout = window.setTimeout.bind(window);
window.setTimeout = (callback, milliseconds, ...args) =>
  actualTimeout(callback, milliseconds === 20000 ? 0 : milliseconds, ...args);
class StudioApiError extends Error {}
function setStatus(node, tone, icon, label) {node.textContent = label; node.dataset.tone = tone;}
function showMessage(node, text) {node.textContent = text;}
function showView(view) {
  document.querySelectorAll('.view').forEach(node => node.classList.toggle('active', node.dataset.view === view));
}
async function loadWorkflow() {fixture.workflowLoads++;}
async function sha(value) {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  const hash = await crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(hash)].map(value => value.toString(16).padStart(2, '0')).join('');
}
async function api(path, options = {}) {
  fixture.calls.push({path, ...structuredClone(options)});
  if (fixture.holdNext && fixture.holdNext.method === options.method) {
    fixture.holdNext = null;
    fixture.blocked = true;
    await new Promise(resolve => {fixture.release = () => {fixture.blocked = false; resolve();};});
  }
  if (path.endsWith('/material-requirement')) {
    return {schema_version: 'content-team-material-requirement/2.0', form: 'TABLE',
      panel_count: 1, image_supporting_data: null};
  }
  if (path === '/request-drafts' && options.method === 'POST') {
    const id = 'requestdraft_' + (++fixture.draftSequence).toString(16).padStart(32, '0');
    const text = options.body.original_request_text;
    const value = {request_draft_id: id, subject: '통합과학', topic: '서버 기본 주제',
      item_format: 'multiple_choice', task_type: 'conceptual', difficulty: 'medium',
      choice_count: 5, equation_required: true, material_requirement: {
        schema_version: 'content-team-material-requirement/2.0', form: 'AUTO',
        panel_count: null, image_supporting_data: null}, quality_profile: 'balanced',
      source_intake_batch_id: null, authoring_guidance: text, knowledge_grounding: false,
      curriculum_selected_unit_key: null, past_exam_variation: null,
      original_request_text: text, original_request_sha256: await sha(text),
      authoring_guidance_sha256: 'sha256:' + await sha(text), draft_spec_sha256: await sha(text)};
    drafts.set(id, value); return structuredClone(value);
  }
  const id = path.split('/')[2];
  const stored = drafts.get(id);
  if (!stored) throw new Error('FIXTURE_DRAFT_MISSING');
  if (options.method === 'PUT') {
    const value = {...stored, ...structuredClone(options.body),
      authoring_guidance_sha256: 'sha256:' + await sha(options.body.authoring_guidance),
      draft_spec_sha256: await sha({source: stored.original_request_sha256, ...options.body})};
    drafts.set(id, value); return structuredClone(value);
  }
  if (path.endsWith('/submissions')) {
    const expectedKey = 'studio:' + id + ':' + stored.draft_spec_sha256;
    if (options.body.idempotency_key !== expectedKey) throw new Error('FIXTURE_STALE_SPEC');
    if (fixture.pendingReplies > 0) {
      fixture.pendingReplies--;
      fixture.preparationKeys.push(expectedKey);
      return {preparation_status: 'PENDING', command: null, replayed: false};
    }
    fixture.submissions.push({id, snapshot: structuredClone(stored), key: expectedKey});
    return {replayed: false, command: {resource_id: 'workflow_' + fixture.submissions.length.toString(16).padStart(32, '0')}};
  }
  throw new Error('FIXTURE_UNEXPECTED_OPERATION');
}
${handlers}
installRequestDraft(); renderCurriculumOutline(); syncCurriculumSelectorAvailability();
syncGraphGroundingCapability(); syncMaterialPanelCount(); syncDraftControls(); showView('request');
document.querySelector('.nav-item[data-view-target="request"]').addEventListener('click', () => showView('request'));
fixture.beginVariation = beginPastExamVariation;
fixture.ready = true;
`;

const browser = await chromium.launch({headless: true, timeout: 10000});
try {
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const unexpectedRequests = [];
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/*", route => {
    const url = new URL(route.request().url());
    if (url.origin !== "https://request-draft.invalid") {
      unexpectedRequests.push(url.href); return route.abort();
    }
    if (url.pathname === "/studio") return route.fulfill({contentType: "text/html", body: assets.get("index.html")});
    const name = url.pathname.split("/").at(-1);
    if (name === "app.js") return route.fulfill({contentType: "text/javascript", body: fixtureApp});
    const body = assets.get(name);
    if (body === undefined) {unexpectedRequests.push(url.pathname); return route.abort();}
    return route.fulfill({body, contentType: name.endsWith(".js") ? "text/javascript" : name.endsWith(".css") ? "text/css" : "image/svg+xml"});
  });
  await page.goto("https://request-draft.invalid/studio", {timeout: 10000});
  await page.waitForFunction(() => window.requestFixture?.ready === true, null, {timeout: 5000})
    .catch(error => {throw new Error(`${error.message}; page errors: ${JSON.stringify(errors)}`);});
  page.setDefaultTimeout(5000);
  const form = page.locator("#draft-form");
  const guidance = page.locator("#request-text");
  const ready = () => page.waitForFunction(() => window.requestFixture.state.draftAction === null);
  const calls = () => page.evaluate(() => window.requestFixture.calls);
  const openRequest = () => page.locator('.nav-item[data-view-target="request"]').click();
  const newDraft = async () => {await openRequest(); await page.locator("#draft-new").click();};
  const variationEntry = {item_id: "item_" + "a".repeat(32), item_revision_id: "itemrev_" + "b".repeat(32),
    occurrence_display_label: "합성 기출 시험", item_number: 17,
    curriculum_units: [{unit_key: "eom.is.middle.3-3"}]};

  assert.equal(await form.locator("textarea").count(), 1);
  assert.equal(await page.locator("#draft-analyze").count(), 0);
  for (const field of ["language", "subject", "choice_count", "equation_required", "quality_profile"]) {
    assert.equal(await form.locator(`[name="${field}"]`).count(), 0);
  }
  assert.equal(await form.locator('[name="task_type"]').inputValue(), "conceptual");
  await guidance.fill("짧음");
  await page.locator("#draft-submit").click();
  assert.equal(await form.evaluate(node => node.checkValidity()), false);
  assert.equal((await calls()).length, 0, "native invalid form must never prepare a request");

  const firstText = "포물선 운동 자료를 두 개의 표로 제시하고 추론하는 문항을 만들어주세요.";
  await guidance.fill(firstText);
  await form.locator('[name="curriculum_middle_unit_key"]').selectOption("eom.is.middle.3-3");
  await form.locator('[name="difficulty"]').selectOption("hard");
  await form.locator('[name="task_type"]').selectOption("data_interpretation");
  await form.locator('[name="material_form"]').selectOption("TABLE");
  await form.locator('[name="material_panel_count"]').selectOption("2");
  await page.locator("#draft-save").click(); await ready();
  let observed = await calls();
  assert.equal(observed.length, 2);
  const firstId = await page.locator("#draft-id").textContent();
  const firstUpdate = observed.at(-1).body;
  assert.equal(firstUpdate.authoring_guidance, firstText);
  assert.equal(firstUpdate.curriculum_selected_unit_key, "eom.is.middle.3-3");
  assert.equal(firstUpdate.topic, "중력장 내의 운동");
  assert.equal(firstUpdate.difficulty, "hard");
  assert.equal(firstUpdate.material_requirement.form, "TABLE");
  assert.equal(firstUpdate.material_requirement.panel_count, 2);
  assert.equal(firstUpdate.choice_count, 5);
  assert.equal(firstUpdate.equation_required, true);
  assert.equal(await guidance.inputValue(), firstText, "saved response must not overwrite editor");
  assert.equal(await page.evaluate(() => window.requestFixture.submissions.length), 0);
  await page.locator("#draft-submit").click(); await ready();
  assert.equal(await page.evaluate(() => window.requestFixture.submissions.length), 1);

  await newDraft();
  assert.equal(await guidance.inputValue(), "");
  assert.equal(await page.locator("#draft-id").textContent(), "-");
  await guidance.fill("세포 내 물질의 이동을 새로운 상황에서 판단하는 문항을 만들어주세요.");
  await page.locator("#draft-submit").click(); await ready();
  assert.notEqual(await page.locator("#draft-id").textContent(), firstId);
  assert.equal(await page.evaluate(() => window.requestFixture.submissions.length), 2);

  // Real input events invalidate the saved snapshot; native disabled controls stop double clicks.
  await newDraft();
  await guidance.fill("처음 작성한 생명 시스템의 자료를 해석하는 문항을 만들어주세요.");
  await page.evaluate(() => {window.requestFixture.holdNext = {method: "PUT"};});
  await page.locator("#draft-submit").click();
  await page.waitForFunction(() => window.requestFixture.blocked);
  const blockedCount = (await calls()).length;
  assert.equal(await page.locator("#draft-submit").isDisabled(), true);
  assert.equal(await page.locator("#draft-save").isDisabled(), true);
  assert.equal(await page.locator("#draft-new").isDisabled(), true);
  await page.evaluate(() => {
    document.querySelector("#draft-submit").click();
    document.querySelector("#draft-save").click();
    document.querySelector("#draft-new").click();
  });
  assert.equal((await calls()).length, blockedCount);
  const revisedText = "사용자가 기다리는 동안 바꾼 유전 정보의 전달에 관한 문항 요구입니다.";
  await guidance.fill(revisedText);
  await page.evaluate(() => window.requestFixture.release()); await ready();
  assert.equal(await page.evaluate(() => window.requestFixture.submissions.length), 2);
  assert.equal(await guidance.inputValue(), revisedText);
  assert.match(await page.locator("#draft-message").textContent(), /내용이 변경/);
  await page.locator("#draft-submit").click(); await ready();
  assert.equal(await page.evaluate(() => window.requestFixture.submissions.at(-1).snapshot.authoring_guidance), revisedText);

  // Clearing a variation while its old save is in flight must not resurrect the source.
  await newDraft();
  await page.evaluate(async entry => {await window.requestFixture.beginVariation(entry);}, variationEntry);
  assert.equal(await page.locator("#past-exam-variation-field").isVisible(), true);
  assert.equal(await form.locator('[name="material_form"]').inputValue(), "TABLE");
  assert.equal(await form.locator('[name="variation_axis"]:checked').count(), 4);
  const beforeClear = await page.evaluate(() => window.requestFixture.submissions.length);
  await page.evaluate(() => {window.requestFixture.holdNext = {method: "PUT"};});
  await page.locator("#draft-submit").click();
  await page.waitForFunction(() => window.requestFixture.blocked);
  await page.locator("#past-exam-variation-clear").click();
  await page.evaluate(() => window.requestFixture.release()); await ready();
  assert.equal(await page.locator("#past-exam-variation-field").isVisible(), false);
  assert.equal(await form.locator('[name="variation_axis"]:checked').count(), 0);
  assert.equal(await page.evaluate(() => window.requestFixture.submissions.length), beforeClear);
  await page.locator("#draft-submit").click(); await ready();
  assert.equal(await page.evaluate(() => window.requestFixture.submissions.at(-1).snapshot.past_exam_variation), null);

  await openRequest();
  await page.evaluate(() => {window.requestFixture.pendingReplies = 2;});
  const beforePrepared = await page.evaluate(() => window.requestFixture.submissions.length);
  await page.locator("#draft-submit").click(); await ready();
  assert.equal(await page.evaluate(() => window.requestFixture.submissions.length), beforePrepared + 1);
  assert.equal(await page.evaluate(() => window.requestFixture.preparationKeys.length), 2);
  assert.equal(await page.evaluate(() => new Set([
    ...window.requestFixture.preparationKeys, window.requestFixture.submissions.at(-1).key,
  ]).size), 1);
  await openRequest();
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({width, height: 850});
    const bounds = await guidance.boundingBox();
    assert.ok(bounds && bounds.width > 0 && bounds.x >= 0 && bounds.x + bounds.width <= width);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `request form overflows at ${width}px`);
  }
  assert.deepEqual(errors, []);
  assert.deepEqual(unexpectedRequests, []);
  console.log("request_draft_browser=PASS desktop=1440 mobile=390,320 real_handlers=YES live_writes=0");
} finally {
  await browser.close();
}
