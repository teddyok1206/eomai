import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {createServer} from "node:http";
import {createRequire} from "node:module";

const require = createRequire(import.meta.url);
const {chromium} = require(process.env.EOM_WEB_PLAYWRIGHT_MODULE);
const root = new URL("../../apps/web_gui/eom_web_gui/static/", import.meta.url);
const assets = new Map(await Promise.all(["styles.css", "kakao-archive.css", "kakao-question-composer.js"].map(async name => [name, await readFile(new URL(name, root), "utf8")])));
const app = `
import {createKakaoQuestionComposer} from './kakao-question-composer.js';
const id=(prefix,n)=>prefix+'_'+n.toString(16).padStart(32,'0');
const binding={source_binding_id:id('kakaobinding',1),state:'DRAFT'};
const row=(n,room=1)=>({schema_version:'kakao-stored-question/1.0',source_binding_id:binding.source_binding_id,
 room_id:id('kakaoroom',room),question_id:id('kakaoquestion',n),question_revision_id:id('kakaoquestionrev',n),resource_version:1,
 first_student_at_utc:'2026-11-16T01:00:00Z',student:{display_name:'합성 학생 '+n}});
const f=window.fixture={calls:[],saved:[],records:new Map(),lose:false,failOpen:false,hold:false,release:null,wrongReply:false};
async function api(path,options){
 f.calls.push({path,...structuredClone(options)});
 if(f.deny)throw Object.assign(new Error('synthetic denied'),{code:'KAKAO_ARCHIVE_PERMISSION_DENIED'});
 if(f.hold){f.hold=false;await new Promise(resolve=>f.release=resolve);}
 const key=options.headers['Idempotency-Key'],body=options.body;
 if(!f.records.has(key)){
  const count=body.operation==='SPLIT'?body.partitions.length:1;
  f.records.set(key,{schema_version:'kakao-question-composition-result/1.0',operation:body.operation,
   composition_id:id('kakaocomposition',f.records.size+1),source_binding_id:body.source_binding_id,room_id:body.room_id,
   inputs:body.operation==='SPLIT'?[body.input]:body.inputs,outputs:Array.from({length:count},(_,i)=>({...row(100+f.records.size*100+i),room_id:body.room_id})),replayed:false});
 }
 if(f.lose){f.lose=false;throw new Error('synthetic response lost after commit');}
 const result=structuredClone(f.records.get(key));
 return f.wrongReply?{...result,source_binding_id:id('kakaobinding',9)}:result;
}
const c=f.controller=createKakaoQuestionComposer({document,api,explainError:()=> '합성 오류',onSaved:async result=>{
 if(f.failOpen){f.failOpen=false;throw new Error('synthetic read unavailable');}
 f.saved.push(result);return true;
}});
f.binding=binding;f.row=row;
f.view=()=>({question:row(1),ordered_blocks:[
 {kind:'TEXT',block_id:'original-text',role:'student',text:'원문😀 <script>window.leaked=true</script>'},
 {kind:'IMAGE',block_id:'original-photo',role:'student',availability:'expired'},
 {kind:'TEXT',block_id:'original-reply',role:'staff',text:'원래 답변'}]});
c.install(document.querySelector('#editor'));c.setOwner('owner-a');c.setBinding(binding);c.open();
`;
const server = createServer((request, response) => {
  const name = (request.url || "").split("/").pop();
  const html = '<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><link rel="stylesheet" href="styles.css"><link rel="stylesheet" href="kakao-archive.css"><main class="kakao-archive"><section id="editor"></section></main><script type="module" src="fixture.js"></script></html>';
  const value = name === "fixture.js" ? app : name === "" ? html : assets.get(name);
  if (value === undefined) {response.writeHead(404);response.end();return;}
  response.setHeader("Content-Type", name.endsWith(".js") ? "text/javascript" : name.endsWith(".css") ? "text/css" : "text/html"); response.end(value);
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const browser = await chromium.launch({headless:true});
try {
  const page = await browser.newPage({viewport:{width:1100,height:900}}), errors = [], outbound = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => {if (!request.url().startsWith("http://127.0.0.1:")) outbound.push(request.url());});
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  await page.waitForFunction(() => window.fixture?.controller);
  const editor = page.getByRole("region", {name:"질문 구성 편집"});
  assert.equal(await editor.isHidden(), true, "read-only UI exposed editing");
  await page.evaluate(() => fixture.controller.setPermissions(["kakao_archive:read", "kakao_archive:edit"]));
  await editor.waitFor();
  await page.evaluate(() => fixture.controller.add(fixture.row(1)));
  assert.equal(await editor.getByRole("button", {name:"새 질문으로 저장",exact:true}).isDisabled(), true);
  await page.evaluate(() => {fixture.controller.add(fixture.row(1));fixture.controller.add(fixture.row(2));});
  assert.equal(await editor.locator(".kakao-composition-row").count(), 2, "duplicate selection was appended");
  await page.evaluate(() => fixture.controller.add(fixture.row(3,2)));
  assert.match(await editor.textContent(), /같은 대화방/);
  assert.equal(await editor.locator(".kakao-composition-row").count(), 2, "different room was added");
  await editor.locator(".kakao-composition-row").nth(1).getByRole("button", {name:"위로",exact:true}).click();
  await page.evaluate(() => {fixture.lose=true;});
  await editor.getByRole("button", {name:"새 질문으로 저장",exact:true}).click();
  await page.waitForFunction(() => document.querySelector("#editor").textContent.includes("결과를 확인하지 못했습니다"));
  assert.equal(await editor.locator(".kakao-composition-row").count(), 0, "uncertain save allowed body changes");
  await page.evaluate(() => {fixture.controller.close();fixture.controller.setBinding(null);fixture.controller.open();fixture.controller.setBinding(fixture.binding);});
  await editor.getByRole("button", {name:"같은 저장 요청 확인",exact:true}).click();
  await page.waitForFunction(() => fixture.saved.length===1);
  let calls = await page.evaluate(() => fixture.calls);
  assert.equal(calls.length, 2); assert.equal(calls[0].headers["Idempotency-Key"], calls[1].headers["Idempotency-Key"]);
  assert.deepEqual(calls[0].body, calls[1].body);
  assert.deepEqual(calls[0].body.inputs.map(item=>item.question_id), [2,1].map(n=>"kakaoquestion_"+n.toString(16).padStart(32,"0")));
  assert.equal(await page.evaluate(() => fixture.records.size), 1, "replay recomputed composition");

  await page.evaluate(() => fixture.controller.split(fixture.view()));
  assert.equal(await editor.locator("script").count(), 0); assert.equal(await page.evaluate(() => window.leaked), undefined);
  await editor.getByRole("button", {name:"새 질문으로 저장",exact:true}).click();
  assert.match(await editor.textContent(), /나눌 위치/); assert.equal(await page.evaluate(() => fixture.calls.length), 2);
  await editor.getByRole("checkbox", {name:"2번째 내용부터 새 질문"}).check();
  await editor.getByRole("checkbox", {name:"3번째 내용부터 새 질문"}).check();
  await page.evaluate(() => {fixture.failOpen=true;});
  await editor.getByRole("button", {name:"새 질문으로 저장",exact:true}).click();
  await page.waitForFunction(() => document.querySelector("#editor").textContent.includes("저장은 완료됐습니다"));
  assert.equal(await page.evaluate(() => fixture.calls.length), 3);
  await editor.getByRole("button", {name:"저장한 질문 열기",exact:true}).click();
  await page.waitForFunction(() => fixture.saved.length===2);
  assert.equal(await page.evaluate(() => fixture.calls.length), 3, "read failure repeated a successful POST");
  calls = await page.evaluate(() => fixture.calls);
  assert.deepEqual(calls[2].body.partitions, ["original-text", "original-photo", "original-reply"].map(block_id=>[{kind:"BLOCK",block_id}]));
  assert.equal(JSON.stringify(calls[2].body).includes("원문"), false, "full text was posted instead of IDs");

  await page.evaluate(() => {fixture.controller.add(fixture.row(1));fixture.controller.add(fixture.row(2));fixture.wrongReply=true;});
  await editor.getByRole("button", {name:"새 질문으로 저장",exact:true}).click();
  await page.waitForFunction(() => document.querySelector("#editor").textContent.includes("결과를 확인하지 못했습니다"));
  assert.equal(await page.evaluate(() => fixture.saved.length), 2, "foreign output was adopted");
  await page.evaluate(() => {fixture.wrongReply=false;});
  await editor.getByRole("button", {name:"같은 저장 요청 확인",exact:true}).click();
  await page.waitForFunction(() => fixture.saved.length===3);
  calls = await page.evaluate(() => fixture.calls);
  assert.equal(calls[3].headers["Idempotency-Key"], calls[4].headers["Idempotency-Key"]);
  assert.equal(await page.evaluate(() => fixture.records.size), 3);

  await page.evaluate(() => {fixture.controller.add(fixture.row(1));fixture.controller.add(fixture.row(2));fixture.deny=true;});
  await editor.getByRole("button", {name:"새 질문으로 저장",exact:true}).click();
  await page.waitForFunction(() => document.querySelector('#editor').hidden);
  assert.equal(await page.evaluate(() => fixture.records.size), 3, "denied request created output");
  await page.evaluate(() => {fixture.deny=false;fixture.controller.setPermissions(['kakao_archive:read','kakao_archive:edit']);});
  await editor.getByRole("button", {name:"같은 저장 요청 확인",exact:true}).click();
  await page.waitForFunction(() => fixture.saved.length===4);
  const beforeDetached = await page.evaluate(() => fixture.calls.length);

  await page.evaluate(() => {fixture.controller.split(fixture.view());fixture.oldSave=[...document.querySelectorAll('#editor button')].find(b=>b.textContent==='새 질문으로 저장');fixture.oldCut=document.querySelector('#editor input');fixture.controller.setBinding({...fixture.binding,source_binding_id:'kakaobinding_'+'9'.repeat(32)});fixture.oldSave.click();fixture.oldCut.click();});
  assert.equal(await page.evaluate(() => fixture.calls.length), beforeDetached, "detached control submitted a changed context");
  await page.evaluate(() => {fixture.controller.setBinding(fixture.binding);fixture.controller.split(fixture.view());});
  await editor.getByRole("checkbox", {name:"2번째 내용부터 새 질문"}).check();
  await page.evaluate(() => {fixture.hold=true;fixture.release=null;});
  await editor.getByRole("button", {name:"새 질문으로 저장",exact:true}).click();
  await page.waitForFunction(() => fixture.release!==null);
  await page.evaluate(() => {fixture.controller.setOwner('owner-b');fixture.release();});
  await page.waitForTimeout(40);
  assert.equal(await editor.isHidden(), true); assert.equal(await page.evaluate(() => fixture.saved.length), 4, "old owner output updated the new session");
  assert.doesNotMatch(await page.locator("#editor").textContent(), /원문|합성 학생/);
  await page.evaluate(() => {fixture.controller.setBinding(fixture.binding);fixture.controller.setPermissions(['kakao_archive:read','kakao_archive:edit']);fixture.controller.split(fixture.view());});
  await page.setViewportSize({width:375,height:900});
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth<=window.innerWidth), "mobile overflow");
  await page.evaluate(() => fixture.controller.setPermissions(['kakao_archive:read']));
  assert.equal(await editor.isHidden(), true);
  assert.deepEqual(errors, []); assert.deepEqual(outbound, []);
  console.log("KAKAO_QUESTION_COMPOSER_BROWSER=PASS");
} finally {await browser.close(); await new Promise(resolve=>server.close(resolve));}
