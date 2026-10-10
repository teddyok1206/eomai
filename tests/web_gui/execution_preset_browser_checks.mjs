import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {createRequire} from "node:module";

const require = createRequire(import.meta.url);
const {chromium} = require(process.env.EOM_WEB_PLAYWRIGHT_MODULE);
const staticRoot = new URL("../../apps/web_gui/eom_web_gui/static/", import.meta.url);
const names = ["index.html", "styles.css", "execution-preset-controller.js", "execution-preset-editor.js", "eom-mark.svg"];
const assets = new Map(await Promise.all(names.map(async name => [name, await readFile(new URL(name, staticRoot), "utf8")])));
const projectedPresets = process.env.EOM_WEB_PRESET_FIXTURE_PATH
  ? JSON.parse(await readFile(process.env.EOM_WEB_PRESET_FIXTURE_PATH, "utf8")) : null;

// Only the service adapter is mocked. No real application, worker or model is called.
const fixtureApp = `
import {createExecutionPresetEditor} from './execution-preset-controller.js';
const id = (prefix, value) => prefix + value.repeat(32);
const artifact = seed => ({artifact_id:id('artifact_',seed),artifact_revision_id:id('rev_',seed),
 sha256:'sha256:'+seed.repeat(64),schema_ref:'test/1.0',media_type:'application/json',logical_name:'manifest.json'});
const bundle = (kind,seed) => ({bundle_id:id(kind+'bundle_',seed),bundle_revision_id:id(kind+'rev_',seed),
 manifest_artifact:artifact(seed),manifest_sha256:'sha256:'+seed.repeat(64)});
const role = (name, candidates) => ({role:name,model_candidates:candidates,instruction_bundle:bundle('instr','3'),
 reference_bundle:bundle('ref','4'),worker_pool_key:'item-workers',timeout_seconds:1800,sandbox:'read-only',network:'disabled',
 evidence_access:name==='image'?'NONE':'EVIDENCE_CONTEXT'});
const pair = (model,reasoning_effort) => ({model,reasoning_effort});
const syntheticRevision = {schema_version:'execution-preset-revision/2.0',preset_revision_id:id('execpresetrev_','2'),state:'RELEASED',
 revision_number:1,display_name:'합성 출제 설정',description:'합성 정책',capacity_policy_revision_id:id('capacityrev_','5'),
 general_knowledge_policy:'ALLOW_WITH_PROVENANCE',compatible_workflow_protocols:['workflow-role/1.35.0'],
 role_policies:[role('authoring',[pair('model-a','high')]),role('review',[pair('model-a','medium'),pair('model-b','xhigh')]),role('image',[pair('model-a','high')])],
 retrieval_policy:{access_policy_revision_id:id('accessrev_','6'),access_policy_sha256:'sha256:'+'7'.repeat(64),
 allowed_corpus_keys:['exam_corpus'],allowed_query_kinds:['ITEM_PREPARATION'],allowed_source_classes:['PAST_EXAM','TEXTBOOK'],
 maximum_budget:{max_documents:8,max_item_revisions:8,max_graph_nodes:32,max_claims:16,max_context_tokens:4000}}};
const projectedPresets = ${JSON.stringify(projectedPresets)};
const preset = projectedPresets?.[0] || {preset_id:id('execpreset_','1'),preset_key:'knowledge-grounded-item',current_revision_id:syntheticRevision.preset_revision_id,state:'ACTIVE',revisions:[syntheticRevision]};
const revision = preset.revisions.find(value=>value.preset_revision_id===preset.current_revision_id);
const alternatePreset = {...structuredClone(preset),preset_id:id('execpreset_','d'),preset_key:'alternate-item',
 current_revision_id:id('execpresetrev_','f')};
alternatePreset.revisions[0].preset_revision_id=alternatePreset.current_revision_id;
alternatePreset.revisions[0].display_name='다른 출제 설정';
const options = {preset_revision_id:revision.preset_revision_id,catalog_is_entitlement:false,
 roles:revision.role_policies.map(policy => ({role:policy.role,worker_pool_key:policy.worker_pool_key,
 candidates:[pair('model-a','medium'),pair('model-a','high'),pair('model-b','high'),pair('model-b','xhigh')]}))};
const fixture = window.presetFixture = {calls:[],created:0,released:0,validationStatus:'SUCCEEDED',held:false,
 holdNext:null,release:null,failNextDraft:false,failNextEvaluation:false,failNextRelease:false,emptyRole:null,
 missingFixedPairRole:null,invalidNextRelease:false};
const results = new Map();
async function api(path, request = {}) {
 fixture.calls.push({path,...structuredClone(request)});
 const kind = path.endsWith('/model-options')?'OPTIONS':path.endsWith('/evaluations')?'EVALUATE':
  path.endsWith('/releases')?'RELEASE':path.includes('/execution-preset-validations/')?'STATUS':'DRAFT';
 if (fixture.holdNext === kind) {fixture.holdNext=null;fixture.held=true;
  await new Promise(resolve => {fixture.release=()=>{fixture.held=false;resolve();};});}
 if (kind==='OPTIONS') {
  const observed=structuredClone(options);
  if (path.includes(alternatePreset.preset_id)) observed.preset_revision_id=alternatePreset.current_revision_id;
  for (const role of observed.roles) if (role.role===fixture.emptyRole) role.candidates=[];
  for (const role of observed.roles) if (role.role===fixture.missingFixedPairRole)
   role.candidates=role.candidates.filter(pair=>pair.model!=='model-a'||pair.reasoning_effort!=='high');
  return observed;
 }
 if (kind==='DRAFT') {
  const key=request.body.idempotency_key;
  if (!results.has(key)) {
   fixture.created++; const draft={...structuredClone(request.body),state:'DRAFT',
    schema_version:request.body.target_revision_schema_version,preset_revision_id:id('execpresetrev_','8'),revision_number:revision.revision_number+1};
   delete draft.idempotency_key;delete draft.target_revision_schema_version;
   preset.revisions.push(draft);results.set(key,{resource_id:draft.preset_revision_id,status:'COMPLETED'});
  }
  if (fixture.failNextDraft) {fixture.failNextDraft=false;throw new Error('SYNTHETIC_TIMEOUT');}
  return structuredClone(results.get(key));
 }
 if (kind==='EVALUATE') {
  const key=request.body.idempotency_key;
  if (!results.has(key)) results.set(key,{resource_id:id('job_','9'),status:'ACCEPTED'});
  if (fixture.failNextEvaluation) {fixture.failNextEvaluation=false;throw new Error('SYNTHETIC_TIMEOUT');}
  return structuredClone(results.get(key));
 }
 if (kind==='STATUS') return {validation_id:id('job_','9'),preset_revision_id:id('execpresetrev_','8'),base_revision_id:revision.preset_revision_id,
  preset_policy_sha256:'sha256:'+'a'.repeat(64),status:fixture.validationStatus,scope:'NON_LIVE',quality_evaluated:false,
  error_code:fixture.validationStatus==='FAILED'?'CONTROL_PRESET_VALIDATION_FAILED':null,
  evaluation_id:fixture.validationStatus==='SUCCEEDED'?id('preseteval_','b'):null,
  cases_total:12,cases_passed:fixture.validationStatus==='SUCCEEDED'?12:0,
  completed_at:['SUCCEEDED','FAILED'].includes(fixture.validationStatus)?'2026-10-09T00:00:00Z':null};
 if (kind==='RELEASE') {
  const key=request.body.idempotency_key;
  if (!results.has(key)) {fixture.released++;results.set(key,{resource_id:id('execpresetrev_','c'),status:'COMPLETED'});}
  if (fixture.failNextRelease) {fixture.failNextRelease=false;throw new Error('SYNTHETIC_TIMEOUT');}
  if (fixture.invalidNextRelease) {fixture.invalidNextRelease=false;return {resource_id:'invalid',status:'ACCEPTED'};}
  return structuredClone(results.get(key));
 }
 throw new Error('UNEXPECTED_FIXTURE_OPERATION');
}
const controller = createExecutionPresetEditor({document,api,isAdmin:()=>true,
 refresh:async()=>controller.setPresets([preset,alternatePreset]),showMessage:(node,text)=>{node.textContent=text;},
 addDetail:(node,label,value)=>{const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=value;node.append(dt,dd);}});
controller.install();controller.setPresets([preset,alternatePreset]);
document.querySelectorAll('.view').forEach(node=>node.classList.toggle('active',node.dataset.view==='admin-settings'));
document.querySelector('#advanced-preset-policy').open=true;
fixture.controller=controller;fixture.preset=preset;fixture.ready=true;
`;

const browser = await chromium.launch({headless: true, timeout: 10000});
try {
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  page.setDefaultTimeout(5000);
  const errors = [];
  const unexpected = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/*", route => {
    const url = new URL(route.request().url());
    if (url.origin !== "https://preset-editor.invalid") {unexpected.push(url.href);return route.abort();}
    if (url.pathname === "/studio") return route.fulfill({contentType: "text/html", body: assets.get("index.html")});
    const name = url.pathname.split("/").at(-1);
    if (name === "app.js") return route.fulfill({contentType: "text/javascript", body: fixtureApp});
    const body = assets.get(name);
    if (body === undefined) {unexpected.push(url.pathname);return route.abort();}
    return route.fulfill({body, contentType: name.endsWith(".js") ? "text/javascript" : name.endsWith(".css") ? "text/css" : "image/svg+xml"});
  });
  const reset = async () => {
    await page.goto("https://preset-editor.invalid/studio", {timeout: 10000});
    await page.waitForFunction(() => window.presetFixture?.ready === true);
    await page.locator("#preset-base-select").selectOption("execpresetrev_" + "2".repeat(32));
    await page.waitForFunction(() => !document.querySelector("#preset-review-open").disabled);
  };
  const model = index => page.locator(`[data-preset-model][data-role-index="${index}"][data-candidate-index="0"]`);
  const effort = index => page.locator(`[data-preset-effort][data-role-index="${index}"][data-candidate-index="0"]`);
  const review = async () => {await model(0).selectOption("model-b");await page.locator("#preset-review-open").click();await page.locator("#preset-review-confirm").check();};
  const save = async () => {await review();await page.locator("#preset-draft-submit").click();await page.waitForFunction(() => !document.querySelector("#preset-release-panel").hidden);};
  const held = () => page.waitForFunction(() => window.presetFixture.held);
  const releaseHeld = () => page.evaluate(() => window.presetFixture.release());
  const calls = () => page.evaluate(() => window.presetFixture.calls);

  await reset();
  assert.equal(await page.locator("[data-preset-model]").count(), 3);
  assert.equal(await page.locator("[data-preset-effort]").count(), 3);
  assert.match(await page.locator("#preset-role-editors").innerText(), /기본 검토/);
  assert.match(await page.locator("#preset-role-editors").innerText(), /강화 검토/);
  assert.equal(await page.locator('option[value="max"],option[value="ultra"]').count(), 0);
  await save();
  const draft = (await calls()).find(call => call.path === "/admin/execution-presets" && call.method === "POST").body;
  assert.equal(draft.target_revision_schema_version, "execution-preset-revision/2.0");
  assert.equal(draft.role_policies[0].model_candidates[0].model, "model-b");
  assert.deepEqual(draft.retrieval_policy.allowed_source_classes, ["PAST_EXAM", "TEXTBOOK"]);
  assert.equal(draft.role_policies[2].model_candidates[0].model, "model-a");
  assert.equal(await page.locator("#preset-release-submit").isDisabled(), true);
  await page.evaluate(() => {window.presetFixture.failNextEvaluation=true;});
  await page.locator("#preset-validation-submit").click();
  await page.waitForFunction(() => document.querySelector("#preset-draft-message").textContent.includes("SYNTHETIC_TIMEOUT"));
  await page.locator("#preset-validation-submit").click();
  await page.waitForFunction(() => !document.querySelector("#preset-release-confirm").disabled);
  const evaluationReplay = (await calls()).filter(call => call.path.endsWith("/evaluations"));
  assert.equal(evaluationReplay.length, 2);
  assert.equal(evaluationReplay[0].body.idempotency_key, evaluationReplay[1].body.idempotency_key);
  assert.equal(await page.locator("#preset-release-submit").isDisabled(), true);
  await page.locator("#preset-release-confirm").check();
  await page.evaluate(() => {window.presetFixture.failNextRelease=true;});
  await page.locator("#preset-release-submit").click();
  await page.waitForFunction(() => document.querySelector("#preset-draft-message").textContent.includes("설정 적용 실패"));
  assert.equal(await page.evaluate(() => window.presetFixture.released), 1);
  await page.locator("#preset-release-submit").click();
  await page.waitForFunction(() => document.querySelector("#preset-release-panel").hidden);
  assert.equal(await page.locator("#preset-release-panel").isHidden(), true);
  const releaseReplay = (await calls()).filter(call => call.path.endsWith("/releases"));
  assert.equal(releaseReplay[0].body.idempotency_key, releaseReplay[1].body.idempotency_key);

  // A transport timeout after commit replays the same intent, not a new draft.
  await reset();await review();
  await page.evaluate(() => {window.presetFixture.holdNext="DRAFT";window.presetFixture.failNextDraft=true;});
  await page.locator("#preset-draft-submit").click();await held();
  await page.locator("#preset-draft-submit").evaluate(node => node.click());
  assert.equal((await calls()).filter(call => call.path === "/admin/execution-presets").length, 1);
  await releaseHeld();
  await page.waitForFunction(() => document.querySelector("#preset-draft-message").textContent.includes("SYNTHETIC_TIMEOUT"));
  await page.locator("#preset-draft-submit").click();
  await page.waitForFunction(() => !document.querySelector("#preset-release-panel").hidden);
  const replay = (await calls()).filter(call => call.path === "/admin/execution-presets");
  assert.equal(replay[0].body.idempotency_key, replay[1].body.idempotency_key);
  assert.equal(await page.evaluate(() => window.presetFixture.created), 1);

  // Closing the panel cancels late status presentation and cannot enable release.
  await page.evaluate(() => {window.presetFixture.holdNext="STATUS";});
  await page.locator("#preset-validation-submit").click();await held();
  await page.locator("#preset-release-cancel").click();await releaseHeld();
  await page.waitForFunction(() => document.querySelector("#preset-release-panel").hidden);
  assert.equal(await page.locator("#preset-release-submit").isDisabled(), true);

  // A pending accepted evaluation keeps its identity without restarting a suspended view.
  await reset();await save();
  await page.evaluate(() => {window.presetFixture.holdNext="EVALUATE";});
  await page.locator("#preset-validation-submit").click();await held();
  await page.evaluate(() => window.presetFixture.controller.stopPolling());
  await releaseHeld();
  await page.waitForFunction(() => !document.querySelector("#preset-validation-refresh").disabled);
  assert.equal((await calls()).filter(call => call.path.includes("/execution-preset-validations/")).length, 0);
  assert.equal(await page.locator("#preset-release-confirm").isDisabled(), true);
  await page.locator("#preset-validation-refresh").click();
  await page.waitForFunction(() => !document.querySelector("#preset-release-confirm").disabled);

  // Ending the session also discards mutation/read responses that arrive afterward.
  await reset();await save();
  await page.evaluate(() => {window.presetFixture.holdNext="EVALUATE";});
  await page.locator("#preset-validation-submit").click();await held();
  await page.evaluate(() => window.presetFixture.controller.reset());
  await releaseHeld();
  await page.waitForFunction(() => !document.querySelector("#preset-base-select").disabled);
  assert.equal((await calls()).filter(call => call.path.includes("/execution-preset-validations/")).length, 0);
  assert.equal(await page.locator("#preset-release-panel").isHidden(), true);

  // A malformed release acknowledgement is not presented as a successful application.
  await reset();await save();
  await page.locator("#preset-validation-submit").click();
  await page.waitForFunction(() => !document.querySelector("#preset-release-confirm").disabled);
  await page.locator("#preset-release-confirm").check();
  await page.evaluate(() => {window.presetFixture.invalidNextRelease=true;});
  await page.locator("#preset-release-submit").click();
  await page.waitForFunction(() => document.querySelector("#preset-draft-message").textContent.includes("APPLICATION_API_RESPONSE_INVALID"));
  assert.equal(await page.locator("#preset-release-panel").isHidden(), false);
  await page.locator("#preset-release-submit").click();
  await page.waitForFunction(() => document.querySelector("#preset-release-panel").hidden);
  const invalidReleaseReplay = (await calls()).filter(call => call.path.endsWith("/releases"));
  assert.equal(invalidReleaseReplay[0].body.idempotency_key, invalidReleaseReplay[1].body.idempotency_key);
  assert.equal(await page.evaluate(() => window.presetFixture.released), 1);

  // Switching the pinned base cannot let an older catalog response replace the new selection.
  await reset();
  await page.evaluate(() => {window.presetFixture.holdNext="OPTIONS";});
  await page.locator("#preset-base-select").selectOption("");
  await page.locator("#preset-base-select").selectOption("execpresetrev_" + "2".repeat(32));await held();
  await page.locator("#preset-base-select").selectOption("execpresetrev_" + "f".repeat(32));
  await page.waitForFunction(() => !document.querySelector("#preset-review-open").disabled);
  await releaseHeld();
  assert.equal(await page.locator("#preset-base-revision").inputValue(), "execpresetrev_" + "f".repeat(32));
  assert.equal(await page.locator("#preset-display-name").inputValue(), "다른 출제 설정");

  // Failures and incomplete checks never become a releaseable configuration.
  await reset();await save();
  await page.evaluate(() => {window.presetFixture.validationStatus="FAILED";});
  await page.locator("#preset-validation-submit").click();
  await page.waitForFunction(() => document.querySelector("#preset-validation-status").textContent === "확인 실패");
  assert.equal(await page.locator("#preset-release-confirm").isDisabled(), true);

  // An edit while a save response is late preserves the newer editor intent.
  await reset();await review();
  await page.evaluate(() => {window.presetFixture.holdNext="DRAFT";});
  await page.locator("#preset-draft-submit").click();await held();
  await page.evaluate(() => {const field=document.querySelector("#preset-description");field.value="새 입력";field.dispatchEvent(new Event("input",{bubbles:true}));});
  await releaseHeld();
  await page.waitForFunction(() => !document.querySelector("#preset-review-open").disabled);
  assert.equal(await page.locator("#preset-description").inputValue(), "새 입력");
  assert.equal(await page.locator("#preset-release-panel").isHidden(), true);

  // An empty discovery/admission projection is unknown, not proof a model is unavailable.
  // Fixed roles also require a fresh observation; no hidden status-check job is queued.
  for (const role of ["authoring", "review", "image"]) {
    await reset();
    await page.evaluate(value => {window.presetFixture.emptyRole=value;}, role);
    await page.locator("#preset-base-select").selectOption("");
    await page.locator("#preset-base-select").selectOption("execpresetrev_" + "2".repeat(32));
    await page.waitForFunction(() => document.querySelector("#preset-draft-message").textContent.includes("‘상태 확인’"));
    assert.match(await page.locator("#preset-draft-message").innerText(), /로그인 상태/);
    assert.equal(await page.locator("#preset-review-open").isDisabled(), true);
    assert.equal(await page.locator("#preset-role-editors").innerText().then(text => text.includes("현재 설정 사용 불가")), false);
    if (role !== "image") assert.match(await page.locator("#preset-role-editors").innerText(), /모델 목록 확인 필요/);
    assert.equal((await calls()).some(call => call.method === "POST"), false);
    assert.equal((await calls()).some(call => !call.path.endsWith("/model-options")), false);
  }

  // A nonempty fixed-role list must admit its preserved model/effort pair too.
  await reset();
  await page.evaluate(() => {window.presetFixture.missingFixedPairRole="image";});
  await page.locator("#preset-base-select").selectOption("");
  await page.locator("#preset-base-select").selectOption("execpresetrev_" + "2".repeat(32));
  await page.waitForFunction(() => document.querySelector("#preset-draft-message").textContent.includes("승인 목록에 없습니다"));
  assert.equal(await page.locator("#preset-review-open").isDisabled(), true);
  assert.equal((await calls()).some(call => call.method === "POST"), false);

  // Source/render packaging and the new controls fit narrow phone layouts.
  for (const width of [390, 320]) {
    await page.setViewportSize({width, height: 900});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
  }
  assert.deepEqual(errors, []);
  assert.deepEqual(unexpected, []);
  console.log("execution_preset_browser=PASS live_writes=0 model_calls=0");
} finally {
  await browser.close();
}
