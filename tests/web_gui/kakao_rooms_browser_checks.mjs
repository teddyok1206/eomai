import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {createServer} from "node:http";
import {createRequire} from "node:module";
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.EOM_WEB_PLAYWRIGHT_MODULE);
const root = new URL("../../apps/web_gui/eom_web_gui/static/", import.meta.url);
const assets = new Map(await Promise.all(["styles.css", "kakao-archive.css", "kakao-rooms.js"].map(async name => [name, await readFile(new URL(name, root), "utf8")])));
const id = (prefix, digit) => prefix + '_' + digit.repeat(32);
const bindingId = id('kakaobinding','1'), roomA = id('kakaoroom','1'), roomB = id('kakaoroom','2');
const students = [1,2].map(n => ({schema_version:'kakao-student/1.0',student_id:id('kakaostudent',String(n)),display_revision_id:id('kakaostudentrev',String(n)),previous_revision_id:null,resource_version:1,display_name:'동명이인 <img src=x>',state:'ACTIVE',sha256:'sha256:'+'a'.repeat(64),created_at:'2026-11-16T00:00:00Z',updated_at:'2026-11-16T00:00:00Z'}));
const fresh = (roomId,name) => ({schema_version:'kakao-room/1.0',source_binding_id:bindingId,room_id:roomId,display_name:name,state:'ACTIVE',identity_level:'MANUAL_CONFIRMED',resource_version:1,created_at:'2026-11-16T00:00:00Z',last_observed_at:'2026-11-16T00:00:00Z',mapping:{schema_version:'kakao-room-mapping/1.0',mapping_revision_id:id('kakaomappingrev',roomId===roomA?'1':'2'),previous_revision_id:null,resource_version:1,state:'UNMAPPED',student_id:null,student_display_revision_id:null,student_display_name:null,reason:'합성 source 확인',sha256:'sha256:'+'a'.repeat(64),created_at:'2026-11-16T00:00:00Z'}});
const rooms = new Map([[roomA,fresh(roomA,'첫 번째 방 <script>')],[roomB,fresh(roomB,'두 번째 방')]]), receipts = new Map(), history = new Map();
const calls=[];let revision=4;
function result({path,options={},owner}) {
  calls.push({path,options,owner}); const url=new URL(path,'http://fixture');
  if(owner!=='owner-a') {if(url.pathname==='/kakao-archive/rooms')return {items:[],next_cursor:null};throw {code:'KAKAO_ARCHIVE_PERMISSION_DENIED'};}
  if(url.pathname==='/kakao-archive/students')return {items:students,next_cursor:null};
  if(url.searchParams.get('source_binding_id')!==bindingId)throw {code:'KAKAO_ARCHIVE_RESOURCE_NOT_FOUND'};
  if(url.pathname==='/kakao-archive/rooms')return {items:[...rooms.values()],next_cursor:null};
  const parts=url.pathname.split('/'),identity=parts[3],old=rooms.get(identity); if(!old)throw {code:'KAKAO_ARCHIVE_RESOURCE_NOT_FOUND'};
  if(options.method==='POST') {
    if(parts[4]!=='mapping')throw {code:'UNSUPPORTED'};
    const key=owner+':'+options.headers['Idempotency-Key'];
    if(receipts.has(key)){const receipt=receipts.get(key);if(JSON.stringify(options.body)!==receipt.body)throw {code:'KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT'};return {...receipt.result,replayed:true};}
    const body=options.body;
    if(options.headers['If-Match']!=='"v'+old.resource_version+'"'||body.parent_revision_id!==old.mapping.mapping_revision_id||body.expected_resource_version!==old.resource_version)throw {code:'KAKAO_ARCHIVE_PRECONDITION_FAILED'};
    const student=students.find(x=>x.student_id===body.student_id);
    if(body.action==='MAP_STUDENT'&&(!student||student.display_revision_id!==body.student_display_revision_id))throw {code:'KAKAO_ARCHIVE_STUDENT_STALE'};
    history.set(old.mapping.mapping_revision_id,structuredClone(old));
    const value={...old,resource_version:old.resource_version+1,mapping:{...old.mapping,mapping_revision_id:id('kakaomappingrev',String(revision++)),previous_revision_id:old.mapping.mapping_revision_id,resource_version:old.resource_version+1,state:student?'MAPPED':'UNMAPPED',student_id:student?.student_id||null,student_display_revision_id:student?.display_revision_id||null,student_display_name:student?.display_name||null,reason:body.reason}};
    rooms.set(identity,value);history.set(value.mapping.mapping_revision_id,structuredClone(value));const valueResult={room:value,replayed:false};receipts.set(key,{body:JSON.stringify(body),result:structuredClone(valueResult)});return valueResult;
  }
  const pin=url.searchParams.get('mapping_revision_id');return pin?history.get(pin):old;
}
const app = `
import {createKakaoRooms} from './kakao-rooms.js';
const fixture=window.fixture={owner:'owner-a',calls:[],lose:false,hold:null,release:null,deny:false};
const api=fixture.api=async(path,options={})=>{
 const captured=fixture.owner;fixture.calls.push({path,options,owner:captured});
 if(fixture.deny)throw Object.assign(Error('DENIED'),{code:'KAKAO_ARCHIVE_PERMISSION_DENIED'});
 const response=await fetch('/fixture',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path,options,owner:captured})});
 const value=await response.json();if(value.code)throw Object.assign(Error(value.code),{code:value.code});
 if(fixture.lose&&options.method==='POST'){fixture.lose=false;throw Error('RESPONSE_LOST');}
 if(fixture.hold===path){fixture.hold=null;await new Promise(resolve=>fixture.release=resolve);}
 return value;
};
const controller=fixture.controller=createKakaoRooms({document,api,explainError:error=>error.code||'합성 오류'});
controller.install(document.querySelector('#rooms'));controller.setOwner(fixture.owner);controller.setPermissions(['kakao_archive:read','kakao_archive:edit']);controller.open();
await controller.setBinding({source_binding_id:${JSON.stringify(bindingId)},state:'DRAFT',capability_state:'NOT_VERIFIED'});
`;
const server=createServer(async(request,response)=>{
  if(request.url==='/fixture') {
    const chunks=[];for await (const chunk of request)chunks.push(chunk);
    response.setHeader('Content-Type','application/json');try{response.end(JSON.stringify(result(JSON.parse(Buffer.concat(chunks).toString()))));}catch(error){response.end(JSON.stringify({code:error.code||'FIXTURE_FAILED'}));}return;
  }
  const name=(request.url||'').split('/').pop();
  const html='<!doctype html><html lang="ko"><meta charset="utf-8"><link rel="stylesheet" href="styles.css"><link rel="stylesheet" href="kakao-archive.css"><main style="max-width:700px;padding:20px"><section id="rooms"></section></main><script type="module" src="fixture.js"></script></html>';
  const content=name==='fixture.js'?app:name===''?html:assets.get(name);
  if(content===undefined){response.writeHead(404);response.end();return;}
  response.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html');response.end(content);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const browser=await chromium.launch({headless:true});
try {
  const page=await browser.newPage({viewport:{width:1100,height:950}}),errors=[],outbound=[];
  page.on('pageerror',error=>errors.push(error.message));page.on('request',request=>{if(!request.url().startsWith('http://127.0.0.1:'))outbound.push(request.url());});
  await page.goto('http://127.0.0.1:'+server.address().port+'/');
  const first=()=>page.getByRole('button',{name:'첫 번째 방 <script>',exact:true}), second=()=>page.getByRole('button',{name:'두 번째 방',exact:true});
  await first().click();const select=page.getByRole('combobox',{name:'연결할 학생',exact:true});
  await page.waitForFunction(()=>document.querySelector('[aria-label="연결할 학생"]')?.options.length===3);
  assert.equal(await page.locator('#rooms img,#rooms script').count(),0);
  await select.selectOption(students[1].student_id);await page.getByLabel('연결 변경 이유',{exact:true}).fill('학생 직접 확인');
  await page.evaluate(()=>{fixture.lose=true;});await page.getByRole('button',{name:'학생 연결 저장',exact:true}).click();
  await page.getByRole('button',{name:'같은 연결 요청 확인',exact:true}).waitFor();
  const binding={source_binding_id:bindingId,state:'DRAFT',capability_state:'NOT_VERIFIED'};
  await page.evaluate(async binding=>{fixture.controller.close();fixture.controller.open();await fixture.controller.setBinding(binding);},binding);
  await page.getByRole('button',{name:'같은 연결 요청 확인',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[data-kakao="room-detail"]').textContent.includes('연결 당시 이름'));
  const mutations=calls.filter(x=>x.options.method==='POST');assert.equal(mutations.length,2);
  assert.deepEqual(mutations[0].options,mutations[1].options);assert.equal(mutations[0].options.body.student_id,students[1].student_id);
  assert.equal(mutations[0].options.body.student_display_revision_id,students[1].display_revision_id);
  const pinned=rooms.get(roomA).mapping.mapping_revision_id;await page.reload();await first().click();
  await page.waitForFunction(()=>document.querySelector('[data-kakao="room-detail"]').textContent.includes('연결 당시 이름'));
  await page.getByLabel('연결 변경 이유',{exact:true}).fill('수동 연결 해제');
  await page.locator('[data-kakao="room-unmap-confirm"]').check();await page.getByRole('button',{name:'학생 연결 해제',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[data-kakao="room-detail"]').textContent.includes('연결된 학생이 없습니다'));
  const old=await page.evaluate(({roomA,bindingId,pinned})=>fixture.api('/kakao-archive/rooms/'+roomA+'?source_binding_id='+bindingId+'&mapping_revision_id='+pinned),{roomA,bindingId,pinned});
  assert.equal(old.mapping.student_id,students[1].student_id);assert.equal(old.mapping.mapping_revision_id,pinned);
  assert.equal(rooms.get(roomA).mapping.state,'UNMAPPED');assert.notEqual(rooms.get(roomA).mapping.mapping_revision_id,pinned);
  const path='/kakao-archive/rooms/'+roomA+'?source_binding_id='+bindingId;
  await page.evaluate(path=>{fixture.hold=path;fixture.release=null;},path);await first().click();await page.waitForFunction(()=>fixture.release!==null);
  await second().click();await page.waitForFunction(()=>document.querySelector('[data-kakao="room-detail"] h4')?.textContent==='두 번째 방');
  await page.evaluate(()=>fixture.release());await page.waitForTimeout(50);assert.equal(await page.locator('[data-kakao="room-detail"] h4').textContent(),'두 번째 방');
  await page.evaluate(path=>{fixture.hold=path;fixture.release=null;},path);await first().click();await page.waitForFunction(()=>fixture.release!==null);
  await page.evaluate(async binding=>{fixture.owner='owner-b';fixture.controller.setOwner(fixture.owner);fixture.controller.setPermissions(['kakao_archive:read','kakao_archive:edit']);await fixture.controller.setBinding(binding);fixture.release();},binding);
  await page.waitForTimeout(50);assert.doesNotMatch(await page.locator('#rooms').textContent(),/첫 번째 방|동명이인/);
  await page.evaluate(async binding=>{fixture.owner='owner-a';fixture.controller.setOwner(fixture.owner);fixture.controller.setPermissions(['kakao_archive:read','kakao_archive:edit']);await fixture.controller.setBinding(binding);},binding);
  await first().click();await select.waitFor();await page.evaluate(()=>{fixture.deny=true;});await first().click();
  await page.waitForFunction(()=>document.querySelector('#rooms [role="status"]').textContent.includes('열지 못했습니다'));
  assert.doesNotMatch(await page.locator('#rooms').textContent(),/첫 번째 방|동명이인/);
  await page.evaluate(async binding=>{fixture.deny=false;fixture.controller.setPermissions(['kakao_archive:read']);await fixture.controller.setBinding(binding);},binding);
  await first().click();assert.equal(await page.getByRole('form',{name:'대화방 학생 연결'}).count(),0);
  const unicodeName='😀'.repeat(80);rooms.get(roomA).display_name=unicodeName;students[0].display_name=unicodeName;
  await page.evaluate(async binding=>{fixture.controller.setPermissions(['kakao_archive:read','kakao_archive:edit']);await fixture.controller.setBinding(binding);},binding);
  await page.getByRole('button',{name:unicodeName,exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[aria-label="연결할 학생"]')?.options.length===3);
  await select.selectOption(students[0].student_id);
  await page.getByLabel('연결 변경 이유',{exact:true}).fill('😀'.repeat(501));
  await page.getByRole('button',{name:'학생 연결 저장',exact:true}).click();
  await page.waitForFunction(value=>document.querySelector('[data-kakao="room-detail"]').textContent.includes(value+' (연결 당시 이름)'),unicodeName);
  assert.equal(rooms.get(roomA).mapping.reason,'😀'.repeat(501));
  const unicodePosts=calls.filter(x=>x.options.method==='POST').length;
  await page.waitForFunction(()=>document.querySelector('[aria-label="연결할 학생"]')?.options.length===3);
  await select.selectOption(students[0].student_id);
  await page.getByLabel('연결 변경 이유',{exact:true}).fill('👩‍🔬'.repeat(334)); // 1002 code points.
  await page.getByRole('button',{name:'학생 연결 저장',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#rooms [role="status"]').textContent.includes('변경 이유를 적어'));
  assert.equal(calls.filter(x=>x.options.method==='POST').length,unicodePosts);
  assert.deepEqual(errors,[]);assert.deepEqual(outbound,[]);
  assert.ok(calls.every(x=>x.path.startsWith('/kakao-archive/rooms')||x.path.startsWith('/kakao-archive/students')));
  console.log('KAKAO_ROOMS_BROWSER=PASS');
} finally {await browser.close();await new Promise(resolve=>server.close(resolve));}
