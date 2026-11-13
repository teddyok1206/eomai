import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {randomUUID, webcrypto} from "node:crypto";
import {runInNewContext} from "node:vm";
import {createDocumentReviewPendingStore, documentReviewRequestFingerprint} from "../../apps/web_gui/eom_web_gui/static/document-review-pending.js";

if (!globalThis.crypto) globalThis.crypto = webcrypto;
const source = await readFile(new URL("../../apps/web_gui/eom_web_gui/static/app.js", import.meta.url), "utf8");
const owner = `operator_${"1".repeat(32)}`;
const otherOwner = `operator_${"2".repeat(32)}`;
const workflowA = `workflow_${"a".repeat(32)}`;
const workflowB = `workflow_${"b".repeat(32)}`;
const intentId = `pdfreviewintent_${"c".repeat(32)}`;
const setId = `docreviewset_${"d".repeat(32)}`;
const callbacks = source.slice(source.indexOf("function documentReviewMutationRequest("), source.indexOf("function installPdfDocumentReview("));
const uploadFunctions = source.slice(source.indexOf("function restorePdfDocumentReviewUpload("), source.indexOf("function documentReviewMutationRequest("));
const pendingStore = () => {
  const values = new Map();
  return {values, getItem:key => values.get(key) ?? null, setItem:(key,value) => values.set(key,value), removeItem:key => values.delete(key)};
};
function node() {
  return {disabled:false, hidden:false, textContent:"", children:[], events:{},
    removeAttribute(name) {delete this[name];},
    append(value) {this.children.push(value);},
    querySelectorAll() {return [];},
    addEventListener(name, callback) {this.events[name] = callback;}};
}
function baseState() {
  return {operator:{operator_id:owner}, currentView:"pdf-review", pdfDocumentReviewRequestSequence:1,
    pdfDocumentReviewSelectedId:workflowA, pdfDocumentReviewSelected:{workflow_id:workflowA,state:"COMPLETED"},
    pdfDocumentReviewCorrectionFindingIds:new Set(["finding-1"]), pdfDocumentReviewPendingCorrection:null,
    pdfDocumentReviewPendingAnnotation:null, pdfDocumentReviewMutationRequests:new Map(),
    pdfDocumentReviewCorrection:null, pdfDocumentReviewAnnotation:null,
    pdfDocumentReviewUploadOwnerSequence:1, pdfDocumentReviewUploadSequence:0,
    pdfDocumentReviewUploadPollCount:0,
    pdfDocumentReviewUploadBusy:false, pdfDocumentReviewUploadRecoveryBlocked:false,
    pdfDocumentReviewPendingSubmission:null};
}
function harness(state = baseState()) {
  const nodes = new Map(), messages = [], timers = new Map(), selected = [], requests = [];
  let timer = 0;
  const context = {state, crypto:{randomUUID}, Uint8Array, encodeURIComponent,
    StudioApiError:class extends Error {constructor(code) {super(code); this.code=code;}},
    $:key => {if (!nodes.has(key)) nodes.set(key,node()); return nodes.get(key);},
    document:{createElement:node},
    window:{setTimeout(fn) {timers.set(++timer,fn);return timer;},clearTimeout(id) {timers.delete(id);}},
    showMessage(target,text) {target.textContent=text; target.children=[]; messages.push(text);},
    renderDocumentReviewAnnotation() {}, renderDocumentReviewCorrection() {},
    async api(path, options = {}) {requests.push({path,...options}); return {};},
    async loadPdfDocumentReviews() {}, async selectPdfDocumentReview(id) {selected.push(id);},
    documentReviewRequestFingerprint};
  runInNewContext(callbacks + uploadFunctions, context);
  return {context,nodes,messages,timers,selected,requests};
}

async function mutations() {
  for (const name of ["createDocumentReviewAnnotation","applyDocumentReviewCorrection"]) {
    const property = name.includes("Annotation") ? "pdfDocumentReviewAnnotation" : "pdfDocumentReviewCorrection";
    const pendingProperty = name.includes("Annotation") ? "pdfDocumentReviewPendingAnnotation" : "pdfDocumentReviewPendingCorrection";
    const loading=harness();loading.context.state.pdfDocumentReviewSelectedId=workflowB;
    await loading.context[name](); assert.equal(loading.requests.length,0);
    for (const transition of ["B","A_AGAIN","OWNER","LEAVE"]) {
      const h = harness(); let release, calls = 0;
      h.context.api = () => {calls++; return new Promise(resolve => {release=resolve;});};
      const first = h.context[name]();
      await h.context[name](); // An in-flight duplicate never releases the first request's flag.
      assert.equal(calls,1); assert.equal(h.context.state[pendingProperty].running,true);
      h.context.state.pdfDocumentReviewRequestSequence++;
      h.context.state.pdfDocumentReviewSelectedId=workflowB;
      h.context.state.pdfDocumentReviewSelected={workflow_id:workflowB,state:"COMPLETED"};
      h.context.state[pendingProperty]=null;
      if (transition === "A_AGAIN") {
        h.context.state.pdfDocumentReviewRequestSequence++;
        h.context.state.pdfDocumentReviewSelectedId=workflowA;
        h.context.state.pdfDocumentReviewSelected={workflow_id:workflowA,state:"COMPLETED"};
        await h.context[name](); assert.equal(calls,1);
      } else if (transition === "OWNER") h.context.state.operator={operator_id:otherOwner};
      else if (transition === "LEAVE") h.context.state.currentView="item-db";
      const button=h.context.$(name.includes("Annotation") ? "#pdf-review-annotation-submit" : "#pdf-review-correction-submit");
      button.disabled="new-selection";
      const messageCount=h.messages.length;
      release({workflow_id:workflowA,outputs:[]}); await first;
      assert.equal(h.context.state[property],null);
      assert.equal(button.disabled,"new-selection"); assert.equal(h.messages.length,messageCount);
      if (transition === "A_AGAIN") {
        await h.context[name](); assert.equal(calls,1);
        assert.equal(h.context.state[property].workflow_id,workflowA); // Reuse known result, not a new mutation.
      }
    }
    const h=harness(); let fail;
    h.context.api=()=>new Promise((_resolve,reject)=>{fail=reject;});
    const late=h.context[name]();
    h.context.state.pdfDocumentReviewRequestSequence++;
    h.context.state.pdfDocumentReviewSelectedId=workflowB;
    const before=h.messages.length;
    fail(new Error("old failure")); await late; assert.equal(h.messages.length,before);
    let seenKey;
    const wrong=harness();
    wrong.context.api=async(_path,options)=>{seenKey=options.body.idempotency_key;return{workflow_id:workflowB};};
    await wrong.context[name](); assert.equal(wrong.context.state[property],null);
    wrong.context.api=async(_path,options)=>{assert.equal(options.body.idempotency_key,seenKey);return{workflow_id:workflowA,outputs:[]};};
    await wrong.context[name](); assert.equal(wrong.context.state[property].workflow_id,workflowA);
  }
  const h=harness();
  h.context.state.pdfDocumentReviewSelected.result={findings:[{}]};
  h.context.state.pdfDocumentReviewCorrectionEligibility={source_format:"HWPX",correction_available:true,eligible_finding_ids:["finding-1"]};
  h.context.state.pdfDocumentReviewCorrection={workflow_id:workflowB,correction_id:"not-selected"};
  h.context.state.pdfDocumentReviewAnnotation={workflow_id:workflowB,outputs:[{document_role:"QUESTION"}]};
  h.context.isPairedDocumentReview=()=>false;
  runInNewContext(source.slice(source.indexOf("function renderDocumentReviewCorrection("),source.indexOf("function navigatePairedReviewAnchor(")),h.context);
  h.context.renderDocumentReviewCorrection();
  h.context.renderDocumentReviewAnnotation();
  assert.equal(h.context.$("#pdf-review-correction-download").hidden,true);
  assert.equal(h.context.$("#pdf-review-annotation-actions").children.length,0);
  const bounded=harness();
  for (let index=0;index<32;index++) bounded.context.documentReviewMutationRequest(`pending-${index}`,"test");
  assert.throws(()=>bounded.context.documentReviewMutationRequest("overflow","test"),/이전 파일 요청/);
  bounded.context.state.pdfDocumentReviewMutationRequests.get("pending-0").result={workflow_id:workflowA};
  bounded.context.documentReviewMutationRequest("replacement","test");
  assert.equal(bounded.context.state.pdfDocumentReviewMutationRequests.size,32);
  assert.equal(bounded.context.state.pdfDocumentReviewMutationRequests.has("pending-1"),true);
  console.log("document_review_mutations=PASS");
}

function file(name="synthetic.pdf", bytes="%PDF-1.7 synthetic source") {
  const blob=new Blob([bytes]);
  return {name,size:blob.size,lastModified:100,slice:(...args)=>blob.slice(...args)};
}
function form(question=file(),solution=null) {
  return {elements:{file:{files:[question]},solution_file:{files:solution?[solution]:[]},
    preset_key:{value:"MOCK_EXAM"},additional_guidance:{value:"SYNTHETIC_PRIVATE_GUIDANCE"}},
    reportValidity:()=>true,resets:0,reset() {this.resets++;}};
}
function setup(storage,selectedForm=form()) {
  const h=harness();
  h.context.documentReviewPendingStore=createDocumentReviewPendingStore(()=>storage);
  h.nodes.set("#pdf-review-form",selectedForm);
  h.form=selectedForm;
  h.submit=()=>h.context.submitPdfDocumentReview({preventDefault(){},currentTarget:selectedForm});
  h.context.restorePdfDocumentReviewUpload(owner);
  return h;
}
async function recovery() {
  const storage=pendingStore(), h=setup(storage);
  h.context.api=async(path,options={})=>{h.requests.push({path,...options}); return {upload_intent_id:intentId,state:"AWAITING_UPLOAD"};};
  let contentKey,uploads=0;
  h.context.uploadPdfDocumentReviewContent=async(_id,_file,_media,key)=>{contentKey=key;uploads++;return{upload_intent_id:intentId,state:"PROCESSING"};};
  await h.submit(); assert.equal(uploads,1); assert.equal(h.form.resets,0);
  const raw=[...storage.values.values()][0];
  assert.ok(!raw.includes("SYNTHETIC_PRIVATE_GUIDANCE") && !raw.includes("synthetic.pdf") && !raw.includes("%PDF"));
  assert.equal(JSON.parse(raw).intentId,intentId);
  const reloaded=setup(storage);
  let status="PROCESSING";
  reloaded.context.api=async(path,options={})=>{reloaded.requests.push({path,...options}); assert.equal(path,`/pdf-document-reviews/upload-intents/${intentId}`);return{upload_intent_id:intentId,state:status,workflow_id:status==="STARTED"?workflowA:null};};
  await reloaded.context.resumePdfDocumentReviewUpload();
  assert.equal(reloaded.requests.length,1); assert.equal(reloaded.timers.size,1);
  assert.equal(reloaded.context.state.pdfDocumentReviewPendingSubmission.contentKey,contentKey);
  status="STARTED"; await reloaded.context.resumePdfDocumentReviewUpload();
  assert.equal(storage.values.size,0); assert.deepEqual(reloaded.selected,[workflowA]); assert.equal(reloaded.form.resets,1);
  await reloaded.context.resumePdfDocumentReviewUpload(); assert.equal(reloaded.requests.length,2);

  // A status GET which began before a new submit must not clear its pending
  // identity while the submit is awaiting local sniffing/fingerprinting.
  const raceStore=pendingStore(),originalSubmission=setup(raceStore);
  originalSubmission.context.api=async()=>({upload_intent_id:intentId,state:"AWAITING_UPLOAD"});
  originalSubmission.context.uploadPdfDocumentReviewContent=async()=>({state:"PROCESSING"});
  await originalSubmission.submit();
  const raced=setup(raceStore),pin=raced.context.state.pdfDocumentReviewPendingSubmission;
  let releaseStatus,releaseFingerprint,statusCalls=0,postCalls=0;
  raced.context.api=async(_path,options={})=>{
    if (options.method === "POST") postCalls++;
    if (++statusCalls === 1) return new Promise(resolve=>{releaseStatus=resolve;});
    return {upload_intent_id:intentId,state:"STARTED",workflow_id:workflowA};
  };
  const observation=raced.context.resumePdfDocumentReviewUpload();
  raced.context.documentReviewRequestFingerprint=()=>new Promise(resolve=>{releaseFingerprint=resolve;});
  const submitted=raced.submit();
  while (!releaseFingerprint) await Promise.resolve();
  releaseStatus({upload_intent_id:intentId,state:"STARTED",workflow_id:workflowA});
  await observation;
  assert.equal(raced.context.state.pdfDocumentReviewPendingSubmission.intentKey,pin.intentKey);
  assert.equal(raced.form.resets,0);
  releaseFingerprint(pin.fingerprint); await submitted;
  assert.equal(postCalls,0);assert.equal(raced.form.resets,1);assert.equal(raceStore.values.size,0);

  const budgetStore=pendingStore(),budgetStart=setup(budgetStore);
  budgetStart.context.api=async()=>({upload_intent_id:intentId,state:"AWAITING_UPLOAD"});
  budgetStart.context.uploadPdfDocumentReviewContent=async()=>({state:"PROCESSING"});await budgetStart.submit();
  const budget=setup(budgetStore);
  budget.context.api=async()=>({upload_intent_id:intentId,state:"PROCESSING"});
  budget.context.state.pdfDocumentReviewUploadPollCount=59;
  await budget.context.resumePdfDocumentReviewUpload();assert.equal(budget.timers.size,0);
  assert.ok(budget.messages.at(-1).includes("자동 확인만 잠시 멈췄습니다"));
  await budget.context.resumePdfDocumentReviewUpload({resetBudget:true});assert.equal(budget.timers.size,1);

  const lostStore=pendingStore(),lost=setup(lostStore); let originalKey;
  lost.context.api=async(_path,options)=>{originalKey=options.body.idempotency_key;throw new Error("lost create response");};
  await lost.submit(); assert.equal(JSON.parse([...lostStore.values.values()][0]).intentId,null);
  const retry=setup(lostStore);
  retry.context.api=async(_path,options)=>{assert.equal(options.body.idempotency_key,originalKey);return{upload_intent_id:intentId,state:"AWAITING_UPLOAD"};};
  retry.context.uploadPdfDocumentReviewContent=async()=>({workflow_id:workflowA});
  await retry.submit(); assert.deepEqual(retry.selected,[workflowA]); assert.equal(lostStore.values.size,0);

  const unavailable=setup({getItem:()=>null,setItem:()=>{throw new Error("quota");}});
  unavailable.context.api=async()=>{throw new Error("NO_POST_ALLOWED");};
  await unavailable.submit(); assert.ok(unavailable.messages.some(message=>message.includes("quota")));
  const other=setup(storage); other.context.restorePdfDocumentReviewUpload(otherOwner);
  assert.equal(other.context.state.pdfDocumentReviewPendingSubmission,null);

  const corrupt=pendingStore(); corrupt.values.set(`eom:document-review:pending:1:${owner}`,JSON.stringify({fileBytes:"untrusted"}));
  const blocked=setup(corrupt); assert.equal(blocked.context.state.pdfDocumentReviewUploadRecoveryBlocked,true);
  await blocked.submit(); assert.equal(blocked.requests.length,0);

  const pairedStore=pendingStore(),paired=setup(pairedStore,form(file("q.pdf"),file("s.pdf")));
  const docs=[{role:"QUESTION",state:"COMMITTED"},{role:"SOLUTION",state:"AWAITING_UPLOAD"}];
  paired.context.api=async()=>({review_set_id:setId,state:"AWAITING_UPLOADS",documents:docs});
  const uploadedRoles=[];
  paired.context.uploadPairedDocumentReviewContent=async(_id,role)=>{uploadedRoles.push(role);return{workflow_id:workflowA};};
  await paired.submit(); assert.deepEqual(uploadedRoles,["SOLUTION"]); assert.deepEqual(paired.selected,[workflowA]);

  const startingStore=pendingStore(),starting=setup(startingStore,form(file("q.pdf"),file("s.pdf")));
  let memberUploads=0;
  starting.context.api=async()=>({review_set_id:setId,state:"STARTING",documents:docs.map(document=>({...document,state:"COMMITTED"}))});
  starting.context.uploadPairedDocumentReviewContent=async()=>{memberUploads++;};
  await starting.submit();assert.equal(memberUploads,0);assert.equal(starting.form.resets,0);
  const reopened=setup(startingStore);
  reopened.context.api=async(path,options={})=>{
    assert.equal(path,`/pdf-document-reviews/sets/${setId}`);assert.equal(options.method,undefined);
    return{review_set_id:setId,state:"STARTING",documents:docs};
  };
  await reopened.context.resumePdfDocumentReviewUpload();assert.equal(reopened.timers.size,1);

  const failed=setup(startingStore);
  const failedState={review_set_id:setId,state:"FAILED_FINAL",failure_code:"SYNTHETIC_FAILURE",documents:docs};
  let failureReads=0;
  failed.context.api=async(_path,options={})=>{assert.equal(options.method,undefined);failureReads++;return failedState;};
  await failed.context.resumePdfDocumentReviewUpload();
  const close=failed.context.$("#pdf-review-form-message").children[0];
  assert.ok(close);await close.events.click();
  assert.equal(failureReads,2);assert.equal(startingStore.values.size,0);assert.equal(failedState.state,"FAILED_FINAL");
  assert.equal(failed.context.state.pdfDocumentReviewPendingSubmission,null);

  const ownerStore=pendingStore(),ownerStart=setup(ownerStore);
  ownerStart.context.api=async()=>({upload_intent_id:intentId,state:"AWAITING_UPLOAD"});
  ownerStart.context.uploadPdfDocumentReviewContent=async()=>({state:"PROCESSING"});await ownerStart.submit();
  const ownerRace=setup(ownerStore);let releaseOwnerStatus;
  ownerRace.context.api=async()=>new Promise(resolve=>{releaseOwnerStatus=resolve;});
  const ownerGet=ownerRace.context.resumePdfDocumentReviewUpload();
  ownerRace.context.state.operator={operator_id:otherOwner};ownerRace.context.restorePdfDocumentReviewUpload(otherOwner);
  releaseOwnerStatus({upload_intent_id:intentId,state:"STARTED",workflow_id:workflowA});await ownerGet;
  assert.equal(ownerRace.form.resets,0);assert.equal(ownerRace.selected.length,0);assert.equal(ownerStore.values.size,1);

  const mismatchedStore=pendingStore(),first=setup(mismatchedStore);
  first.context.api=async()=>{throw new Error("connection lost");}; await first.submit();
  const different=setup(mismatchedStore,form(file("different.pdf")));
  let calls=0; different.context.api=async()=>{calls++;}; await different.submit(); assert.equal(calls,0);
  assert.ok(different.messages.some(message=>message.includes("같은 파일")));

  const sniff=setup(pendingStore());
  const original=file("시험지.hwp","PK\x03\x04 synthetic hwpx");
  const detected=await sniff.context.documentReviewSource(original);
  assert.equal(detected.source_format,"HWPX");assert.equal(detected.original_filename,"시험지.hwp.hwpx");assert.equal(original.name,"시험지.hwp");
  assert.equal((await sniff.context.documentReviewSource(file("native.hwp","\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"))).source_format,"HWP");
  assert.equal(await sniff.context.documentReviewSource(file("other.zip","PK\x03\x04 synthetic archive")),null);
  await assert.rejects(sniff.context.documentReviewSource(file(`${"x".repeat(232)}.hwp`,"PK\x03\x04 synthetic hwpx")),/파일명이 너무/);
  const normalized=setup(pendingStore(),form(original));
  normalized.context.api=async(_path,options)=>{assert.equal(options.body.original_filename,"시험지.hwp.hwpx"); return{upload_intent_id:intentId};};
  normalized.context.uploadPdfDocumentReviewContent=async()=>({state:"PROCESSING"});
  await normalized.submit(); assert.ok(normalized.messages.some(message=>message.includes("원본 파일명 시험지.hwp · 실제 HWPX 등록명 시험지.hwp.hwpx")));
  console.log("document_review_upload_recovery=PASS");
}

if (process.argv[2] === "mutations") await mutations();
else if (process.argv[2] === "recovery") await recovery();
else throw new Error("Specify mutations or recovery");
