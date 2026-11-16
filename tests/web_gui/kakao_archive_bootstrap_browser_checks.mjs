import assert from "node:assert/strict";
import {createHash} from "node:crypto";
import {readFile} from "node:fs/promises";
import {createServer} from "node:http";
import {createRequire} from "node:module";

const require = createRequire(import.meta.url);
const {chromium} = require(process.env.EOM_WEB_PLAYWRIGHT_MODULE);
const root = new URL("../../apps/web_gui/eom_web_gui/static/", import.meta.url);
const assets = new Map(await Promise.all(["styles.css", "kakao-archive.css", "kakao-archive.js", "kakao-students.js", "kakao-rooms.js"].map(async name => [name, await readFile(new URL(name, root), "utf8")])));
const policy = {include_images:true,interval_minutes:1440,question_rule_version:"turn_v1",source_timezone:"unknown"};
const policyHash = "sha256:" + createHash("sha256").update(JSON.stringify(policy)).digest("hex");
const app = `
import {createKakaoArchive} from './kakao-archive.js';
const id = prefix => prefix + '_' + '1'.repeat(32), bindingId=id('kakaobinding');
const fixture=window.fixture={calls:[],binding:null,failCreate:true,failRetire:false,staleRetire:false,held:false,release:null,receipts:new Map()};
const fresh=name=>({schema_version:'kakao-source-binding/1.0',source_binding_id:bindingId,display_name:name,state:'DRAFT',resource_version:1,
  policy_revision:{source_binding_id:bindingId,policy_revision_id:id('kakaopolicyrev'),previous_revision_id:null,revision_number:1,
    sha256:${JSON.stringify(policyHash)},policy:${JSON.stringify(policy)},created_at:'2026-11-16T00:00:00Z'},
  schedule_enabled:false,capability_state:'NOT_VERIFIED',created_at:'2026-11-16T00:00:00Z',updated_at:'2026-11-16T00:00:00Z'});
const api=async(path,options={})=>{
  fixture.calls.push({path,method:options.method||'GET',body:options.body,headers:options.headers,mutation:options.mutation});
  if(path.startsWith('/kakao-archive/students?'))return {items:[],next_cursor:null};
  if(path.startsWith('/kakao-archive/rooms?'))return {items:[],next_cursor:null};
  if(fixture.held&&options.method==='POST'){fixture.held=false;await new Promise(resolve=>fixture.release=resolve);}
  if(path==='/kakao-archive/source-bindings'){
    if(options.method!=='POST')return {items:fixture.binding?[fixture.binding]:[],next_cursor:null};
    const key=options.headers['Idempotency-Key'];
    if(fixture.receipts.has(key))return {...fixture.receipts.get(key),replayed:true};
    fixture.binding=fresh(options.body.display_name);const result={binding:fixture.binding,replayed:false};fixture.receipts.set(key,result);
    if(fixture.failCreate){fixture.failCreate=false;throw new Error('RESPONSE_LOST');}return result;
  }
  if(path==='/kakao-archive/source-bindings/'+bindingId)return fixture.binding;
  if(path==='/kakao-archive/source-bindings/'+bindingId+'/commands'){
    const key=options.headers['Idempotency-Key'];if(fixture.receipts.has(key))return {...fixture.receipts.get(key),replayed:true};
    if(fixture.staleRetire){fixture.staleRetire=false;fixture.binding={...fixture.binding,resource_version:2};throw Object.assign(new Error('STALE'),{code:'KAKAO_ARCHIVE_PRECONDITION_FAILED'});}
    if(options.headers['If-Match']!=='"v'+fixture.binding.resource_version+'"'||options.body.expected_resource_version!==fixture.binding.resource_version)throw Error('INVALID_ETAG');
    fixture.binding={...fixture.binding,state:'RETIRED',resource_version:fixture.binding.resource_version+1};
    const result={binding:fixture.binding,replayed:false};fixture.receipts.set(key,result);
    if(fixture.failRetire){fixture.failRetire=false;throw new Error('RESPONSE_LOST');}return result;
  }
  throw Error('UNIMPLEMENTED_DOWNSTREAM_ROUTE:'+path);
};
const controller=createKakaoArchive({document,api,explainError:error=>error.code||'합성 오류',setStateStatus(el,_domain,value){el.textContent=value;}});
fixture.controller=controller;fixture.id=bindingId;controller.install();controller.setOwner('owner-a');
controller.setPermissions(['kakao_archive:read','kakao_archive:collect']);await controller.open();
`;
const server=createServer((request,response)=>{
  const name=(request.url||'').split('/').pop();
  const html='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><link rel="stylesheet" href="styles.css"><link rel="stylesheet" href="kakao-archive.css"><main style="padding:20px"><section id="kakao-archive-root"></section></main><script type="module" src="fixture.js"></script></html>';
  const content=name==='fixture.js'?app:name===''?html:assets.get(name);
  if(content===undefined){response.writeHead(404);response.end();return;}
  response.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html');response.end(content);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser=await chromium.launch({headless:true});
try {
  const page=await browser.newPage({viewport:{width:1200,height:900}}),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto('http://127.0.0.1:'+server.address().port+'/');
  await page.getByRole('heading',{name:'KakaoTalk',exact:true}).waitFor();
  assert.equal(await page.getByRole('form',{name:'채널 연결 준비'}).isVisible(),false,'collect without ADMIN exposed bootstrap');
  await page.evaluate(()=>fixture.controller.setRoles(['ADMIN']));
  const name=page.getByLabel('채널 이름',{exact:true});await name.fill('합성 채널 <script>');
  await page.getByRole('button',{name:'연결 준비 저장',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[role="status"]').textContent.includes('처리 여부를 확인하지 못했습니다'));
  assert.equal(await name.isDisabled(),true,'unknown create intent remained editable');
  await page.evaluate(async()=>{fixture.controller.close();await fixture.controller.open();});
  assert.equal(await name.inputValue(),'합성 채널 <script>','navigation lost exact retry intent');
  await page.getByRole('button',{name:'같은 준비 요청 확인',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[role="status"]').textContent.includes('연결 준비만 저장'));
  let mutations=await page.evaluate(()=>fixture.calls.filter(call=>call.method==='POST'));
  assert.equal(mutations.length,2);assert.equal(mutations[0].headers['Idempotency-Key'],mutations[1].headers['Idempotency-Key']);
  assert.deepEqual(mutations[0].body,mutations[1].body);assert.equal(mutations[0].mutation,true);
  assert.equal(mutations[0].body.schema_version,'kakao-binding-create/1.0');
  assert.deepEqual(mutations[0].body.policy,{interval_minutes:1440,include_images:true,source_timezone:'unknown',question_rule_version:'turn_v1'});
  assert.equal(await page.locator('#kakao-archive-root script').count(),0);
  assert.equal(await page.locator('[data-kakao="collect"]').count(),0,'unverified binding enabled collection');
  assert.equal(await page.getByRole('button',{name:'학생별 PDF 보기'}).count(),0);
  assert.ok(await page.evaluate(()=>fixture.calls.every(call=>call.path.startsWith('/kakao-archive/source-bindings')||call.path.startsWith('/kakao-archive/students?')||call.path.startsWith('/kakao-archive/rooms?'))),'DRAFT read nonexistent downstream');

  // A stale version is rejected, not replayed with a silently substituted latest revision.
  await page.getByRole('button',{name:'연결 준비 해제',exact:true}).click();
  assert.equal(await page.evaluate(()=>fixture.calls.filter(call=>call.method==='POST').length),2,'retired without explicit confirmation');
  await page.locator('[data-kakao="retire-confirm"]').check();
  await page.evaluate(()=>{fixture.staleRetire=true;});
  await page.getByRole('button',{name:'연결 준비 해제',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[role="status"]').textContent.includes('연결 상태나 권한이 변경'));
  mutations=await page.evaluate(()=>fixture.calls.filter(call=>call.method==='POST'));
  assert.equal(mutations.at(-1).headers['If-Match'],'"v1"');
  assert.equal(mutations.at(-1).body.expected_resource_version,1);
  await page.getByRole('button',{name:'새로고침',exact:true}).click();
  await page.getByRole('combobox',{name:'카카오 채널'}).selectOption({label:'합성 채널 <script>'});
  await page.locator('[data-kakao="retire-confirm"]').check();
  await page.evaluate(()=>{fixture.failRetire=true;});
  await page.getByRole('button',{name:'연결 준비 해제',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[role="status"]').textContent.includes('처리 여부를 확인하지 못했습니다'));
  // A completed mutation with a lost response remains replayable after a new view
  // reads the server's RETIRED state and hides the original action button.
  await page.evaluate(async()=>{fixture.controller.close();const opening=fixture.controller.open();await fixture.controller.restoreLocation({source_binding_id:fixture.id});await opening;});
  assert.equal(await page.getByRole('button',{name:'연결 준비 해제',exact:true}).count(),0);
  await page.getByRole('button',{name:'같은 해제 요청 확인',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[role="status"]').textContent==='연결 준비를 해제했습니다.');
  mutations=await page.evaluate(()=>fixture.calls.filter(call=>call.method==='POST'));
  assert.equal(mutations.length,5);assert.equal(mutations[3].headers['If-Match'],'"v2"');
  assert.equal(mutations[3].headers['Idempotency-Key'],mutations[4].headers['Idempotency-Key']);
  assert.notEqual(mutations[2].headers['Idempotency-Key'],mutations[3].headers['Idempotency-Key']);
  assert.deepEqual(mutations[3].body,mutations[4].body);
  assert.equal(await page.getByRole('button',{name:'연결 준비 해제',exact:true}).count(),0);

  await page.setViewportSize({width:375,height:900});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'bootstrap overflows mobile');
  await name.fill('이전 계정의 새 채널');await page.evaluate(()=>{fixture.held=true;fixture.release=null;});
  await page.getByRole('button',{name:'연결 준비 저장',exact:true}).click();
  await page.waitForFunction(()=>fixture.release!==null);
  await page.evaluate(()=>fixture.controller.setOwner('owner-b'));
  const before=await page.evaluate(()=>fixture.calls.length);
  await page.evaluate(async()=>{await fixture.controller.open();fixture.release();});
  await page.waitForTimeout(30);
  assert.equal(await page.evaluate(()=>fixture.calls.length),before,'owner switched but reused privileges');
  assert.equal(await page.getByRole('form',{name:'채널 연결 준비'}).isVisible(),false);
  assert.doesNotMatch(await page.locator('#kakao-archive-root').textContent(),/이전 계정의 새 채널/);
  assert.equal(await name.inputValue(),'');assert.deepEqual(errors,[]);
  console.log('KAKAO_ARCHIVE_BOOTSTRAP_BROWSER=PASS');
} finally {await browser.close();await new Promise(resolve=>server.close(resolve));}
