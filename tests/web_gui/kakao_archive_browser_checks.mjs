import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {createServer} from "node:http";
import {createRequire} from "node:module";

const require = createRequire(import.meta.url);
const {chromium} = require(process.env.EOM_WEB_PLAYWRIGHT_MODULE);
const root = new URL("../../apps/web_gui/eom_web_gui/static/", import.meta.url);
const assets = new Map(await Promise.all(["styles.css", "kakao-archive.css", "kakao-archive.js", "kakao-students.js", "kakao-rooms.js"].map(async name => [name, await readFile(new URL(name, root), "utf8")])));
const app = `
import {createKakaoArchive} from './kakao-archive.js';
const id = (prefix, digit = '1') => prefix + '_' + digit.repeat(32);
const bindingId = id('kakaobinding'), roomId = id('kakaoroom'), questionA = id('kakaoquestion'), questionB = id('kakaoquestion', '2');
const revisionA = id('kakaoquestionrev'), revisionB = id('kakaoquestionrev', '2'), packetId = id('kakaopacket'), packetRevision = id('kakaopacketrev');
// Future archive projections are isolated fixtures, not the current DRAFT public API.
const fixture = window.fixture = {calls: [], failCollection: true, held: null, release: null, failBindings: false, denyExports: false, duplicateInstall: false, secondRoom: false};
const row = (number) => ({question_id: number === 1 ? questionA : questionB, current_revision_id: number === 1 ? revisionA : revisionB,
  title: number === 1 ? '첫 번째 질문' : '두 번째 질문', student_display_name: '학생 <img src=x>', first_student_at_utc: '2026-10-31T15:20:00Z', review_state: 'CANDIDATE'});
const binding = {source_binding_id: bindingId, display_name:'합성 채널', state:'ACTIVE', capability_state:'VERIFIED', collection_policy_revision_id:id('kakaopolicyrev'), allowed_actions:['READ_ARCHIVE','COLLECT']};
const page = items => ({items,next_cursor:null});
const room = (digit='1') => ({schema_version:'kakao-room/1.0',source_binding_id:bindingId,room_id:id('kakaoroom',digit),display_name:digit==='1'?'합성 대화방':'두 번째 대화방',state:'ACTIVE',identity_level:'MANUAL_CONFIRMED',resource_version:1,created_at:'2026-11-16T00:00:00Z',last_observed_at:'2026-11-16T00:00:00Z',mapping:{schema_version:'kakao-room-mapping/1.0',mapping_revision_id:id('kakaomappingrev',digit),previous_revision_id:null,resource_version:1,state:'UNMAPPED',student_id:null,student_display_revision_id:null,student_display_name:null,reason:'합성 확인',sha256:'sha256:'+'a'.repeat(64),created_at:'2026-11-16T00:00:00Z'}});
async function api(path, options = {}) {
  fixture.calls.push({path,method:options.method || 'GET',body:options.body,key:options.headers?.['Idempotency-Key']});
  const url = new URL(path,'http://fixture');
  if (url.pathname === '/kakao-archive/students') return page([]);
  if (fixture.held === path) {fixture.held = null; await new Promise(resolve => fixture.release = resolve);}
  if (url.pathname === '/kakao-archive/source-bindings') {
    if (fixture.failBindings) throw new Error('SYNTHETIC_UNAVAILABLE');
    return page([binding]);
  }
  if (url.pathname.startsWith('/kakao-archive/source-bindings/')) return binding;
  if (url.pathname === '/kakao-archive/rooms') return page([room(),...(fixture.secondRoom?[room('2')]:[])]);
  if (url.pathname.startsWith('/kakao-archive/rooms/')) return room(url.pathname.endsWith(id('kakaoroom','2'))?'2':'1');
  if (url.pathname === '/kakao-archive/questions') return page(url.searchParams.get('room_id')===id('kakaoroom','2')?[row(2)]:[row(1),row(2)]);
  if (url.pathname.startsWith('/kakao-archive/questions/')) {
    const first = path.includes(questionA + '/');
    return {question_id:first?questionA:questionB,revision_id:first?revisionA:revisionB,source_binding_id:bindingId,student_display_name:'합성 학생',
      first_student_at_utc:'2026-10-31T15:20:00Z',review_state:'CANDIDATE',review_reasons:['BOUNDARY_REVIEW'],alignment_level:'SNAPSHOT_ONLY',
      ordered_blocks:[{kind:'TEXT',text:first?'첫째 줄\\n<script>window.privateLeak=true</script>':'두 번째 질문 본문'},
        {kind:'IMAGE',availability:'expired'},
        {kind:'IMAGE',availability:'available',attachment_id:id('kakaoattachment'),attachment_revision_id:id('kakaoattachmentrev'),preview_url:'https://example.invalid/private'}]};
  }
  if (url.pathname === '/kakao-archive/question-packets') return page([{packet_id:packetId,current_revision_id:packetRevision,title:'10월 질문 자료',question_count:2}]);
  if (url.pathname === '/kakao-archive/exports') {
    if (fixture.denyExports) throw Object.assign(new Error('SYNTHETIC_DENIED'),{code:'PERMISSION_DENIED'});
    return page([{source_binding_id:bindingId,packet_revision_id:packetRevision,student_display_name:'합성 학생',mode:'FINAL',state:'SUCCEEDED',export_id:id('kakaoexport'),export_revision_id:id('kakaoexportrev'),page_count:2,download_url:'https://example.invalid/private'}]);
  }
  if (url.pathname === '/kakao-archive/collection-runs') {
    if (fixture.failCollection) {fixture.failCollection=false; throw new Error('SYNTHETIC_RESPONSE_LOST');}
    return {resource_type:'kakao_collection_run',resource_id:id('kakaorun'),status:'ACCEPTED'};
  }
  if (url.pathname.startsWith('/kakao-archive/collection-runs/')) return {run_id:id('kakaorun'),source_binding_id:bindingId,state:'COMPLETED',coverage:{inventory_complete:false},counters:{rooms_exported:1,rooms_discovered:2,attachment_files_downloaded:2,attachment_files_discovered:3}};
  throw new Error('Unexpected fixture route: '+path);
}
const controller = createKakaoArchive({document,api,setStateStatus(element,_domain,value){element.textContent=value;element.dataset.rawState=value;},explainError:()=> '합성 오류'});
fixture.controller=controller;fixture.ids={bindingId,roomId,questionA,questionB,revisionA,revisionB};
controller.install();controller.install();controller.setOwner('owner-a');controller.setPermissions(['kakao_archive:read','kakao_archive:collect','kakao_archive:export']);
await controller.open();
`;
const server = createServer((request, response) => {
  if (request.url.includes('/preview?revision_id=')) {
    response.setHeader('Content-Type','image/png');
    response.end(Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jxioAAAAASUVORK5CYII=','base64')); return;
  }
  const name = (request.url || '').split('/').pop().split('?')[0];
  const html = '<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><link rel="stylesheet" href="styles.css"><link rel="stylesheet" href="kakao-archive.css"><main style="padding:20px"><section id="kakao-archive-root"></section></main><script type="module" src="fixture.js"></script></html>';
  const content = name === 'fixture.js' ? app : name === '' ? html : assets.get(name);
  if (content === undefined) {response.writeHead(404);response.end();return;}
  response.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html');response.end(content);
});
await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
const browser = await chromium.launch({headless:true});
try {
  const page = await browser.newPage({viewport:{width:1440,height:1000}}), errors = [], outbound = [];
  page.on('pageerror',error=>errors.push(error.message));
  page.on('request',request=>{if(!request.url().startsWith('http://127.0.0.1:'))outbound.push(request.url());});
  await page.goto('http://127.0.0.1:'+server.address().port+'/');
  await page.getByRole('combobox',{name:'카카오 채널'}).selectOption({label:'합성 채널'});
  await page.getByRole('button',{name:'첫 번째 질문',exact:true}).waitFor();
  assert.equal(await page.getByRole('heading',{name:'KakaoTalk',exact:true}).count(),1,'install duplicated listeners/markup');
  assert.match(await page.locator('[data-kakao="rooms"]').textContent(),/학생 연결 필요/);
  await page.getByRole('button',{name:'첫 번째 질문',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[data-kakao="detail"]').textContent.includes('첫째 줄'));
  assert.match(await page.locator('[data-kakao="detail"]').textContent(),/2026.*11.*1/,'date was not KST');
  assert.equal(await page.locator('[data-kakao="detail"] script').count(),0);
  assert.equal(await page.evaluate(()=>window.privateLeak),undefined);
  assert.match(await page.locator('[data-kakao="detail"]').textContent(),/미확보 사진/);
  assert.match(await page.locator('[data-kakao="detail"] img').getAttribute('src'),/\/studio\/api\/v1\/kakao-archive\/attachments\/kakaoattachment_.*revision_id=kakaoattachmentrev_/);
  await page.getByRole('button',{name:'학생별 PDF 보기',exact:true}).click();
  const download = page.getByRole('link',{name:'PDF 내려받기'}); await download.waitFor();
  assert.match(await download.getAttribute('href'),/\/studio\/api\/v1\/kakao-archive\/exports\/kakaoexport_.*revision_id=kakaoexportrev_/);
  assert.equal(outbound.length,0,'untrusted upstream URLs escaped same-origin delivery');
  await page.evaluate(()=>{fixture.denyExports=true;});
  await page.getByRole('button',{name:'학생별 PDF 보기',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('.kakao-exports'));
  assert.equal(await page.getByRole('link',{name:'PDF 내려받기'}).count(),0,'permission denial retained private download');
  await page.evaluate(()=>{fixture.denyExports=false;});

  await page.getByRole('button',{name:'전체 다시 수집',exact:true}).click();
  await page.getByRole('button',{name:'같은 수집 요청 확인',exact:true}).waitFor();
  await page.getByRole('button',{name:'같은 수집 요청 확인',exact:true}).click();
  await page.getByRole('button',{name:'수집 상태 확인',exact:true}).waitFor();
  let commands = await page.evaluate(()=>fixture.calls.filter(call=>call.method==='POST'));
  assert.equal(commands.length,2);assert.equal(commands[0].key,commands[1].key);
  assert.deepEqual(commands[0].body,commands[1].body);
  assert.equal(commands[0].body.mode,'REPEAT');
  assert.match(await page.getByRole('region',{name:'수집 진행'}).textContent(),/전체 방 목록이 확인되지 않았습니다/);
  await page.getByRole('button',{name:'수집 상태 확인',exact:true}).click();
  assert.equal(await page.evaluate(()=>fixture.calls.filter(call=>call.method==='POST').length),2,'status read re-collected');

  // Navigation during an accepted command must not strand the new view's busy button.
  await page.evaluate(()=>{fixture.held='/kakao-archive/collection-runs';fixture.release=null;});
  await page.getByRole('button',{name:'새로 수집하기',exact:true}).click();
  await page.waitForFunction(()=>fixture.release!==null);
  await page.evaluate(async()=>{fixture.controller.close();await fixture.controller.open();});
  await page.getByRole('combobox',{name:'카카오 채널'}).selectOption({label:'합성 채널'});
  await page.getByRole('button',{name:'첫 번째 질문',exact:true}).waitFor();
  assert.equal(await page.locator('[data-kakao="collect"]').isDisabled(),true);
  await page.evaluate(()=>fixture.release());
  await page.waitForFunction(()=>!document.querySelector('[data-kakao="collect"]').disabled);
  assert.equal(await page.locator('[data-kakao="collect"]').textContent(),'수집 상태 확인');
  await page.getByRole('button',{name:'수집 상태 확인',exact:true}).click();
  assert.equal(await page.evaluate(()=>fixture.calls.filter(call=>call.method==='POST').length),3,'reopened view retried accepted command');

  await page.evaluate(()=>{fixture.held='/kakao-archive/questions/'+fixture.ids.questionA+'/revisions/'+fixture.ids.revisionA;fixture.release=null;});
  await page.getByRole('button',{name:'첫 번째 질문',exact:true}).click();
  await page.waitForFunction(()=>fixture.release!==null);
  await page.getByRole('button',{name:'두 번째 질문',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[data-kakao="detail"]').textContent.includes('두 번째 질문 본문'));
  await page.evaluate(()=>fixture.release());
  await page.waitForTimeout(40);
  assert.doesNotMatch(await page.locator('[data-kakao="detail"]').textContent(),/첫째 줄/,'late selection overwrote current');

  await page.evaluate(()=>{fixture.secondRoom=true;});
  await page.getByRole('button',{name:'새로고침',exact:true}).click();
  await page.getByRole('button',{name:'두 번째 대화방',exact:true}).waitFor();
  await page.evaluate(()=>{const query=new URLSearchParams({source_binding_id:fixture.ids.bindingId,limit:'50',room_id:fixture.ids.roomId});fixture.held='/kakao-archive/questions?'+query;fixture.release=null;});
  await page.getByRole('button',{name:'합성 대화방',exact:true}).click();
  await page.waitForFunction(()=>fixture.release!==null);
  await page.getByRole('button',{name:'두 번째 대화방',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[data-kakao="questions"]').textContent.includes('두 번째 질문')&&!document.querySelector('[data-kakao="questions"]').textContent.includes('첫 번째 질문'));
  await page.evaluate(()=>fixture.release());await page.waitForTimeout(40);
  assert.equal(await page.getByRole('button',{name:'첫 번째 질문',exact:true}).count(),0,'late room A response overwrote room B');
  await page.getByRole('button',{name:'합성 대화방',exact:true}).click();
  await page.getByRole('button',{name:'첫 번째 질문',exact:true}).waitFor();

  // A detached old button cannot override the newly selected room or suppress its list.
  await page.evaluate(()=>{
    fixture.oldQuestion=[...document.querySelectorAll('button')].find(button=>button.textContent==='첫 번째 질문');
    const query=new URLSearchParams({source_binding_id:fixture.ids.bindingId,limit:'50',room_id:'kakaoroom_'+'2'.repeat(32)});
    fixture.held='/kakao-archive/questions?'+query;fixture.release=null;
  });
  await page.getByRole('button',{name:'두 번째 대화방',exact:true}).click();
  await page.waitForFunction(()=>fixture.release!==null);
  assert.equal(await page.getByRole('button',{name:'첫 번째 질문',exact:true}).count(),0,'old question remained during room load');
  const detailCalls=await page.evaluate(()=>fixture.calls.filter(call=>call.path.includes('/revisions/')).length);
  await page.evaluate(()=>{fixture.oldQuestion.click();fixture.release();});
  await page.getByRole('button',{name:'두 번째 질문',exact:true}).waitFor();
  assert.equal(await page.evaluate(()=>fixture.calls.filter(call=>call.path.includes('/revisions/')).length),detailCalls,'detached old button dispatched request');
  assert.equal(await page.getByRole('button',{name:'첫 번째 질문',exact:true}).count(),0);
  await page.getByRole('button',{name:'합성 대화방',exact:true}).click();
  await page.getByRole('button',{name:'첫 번째 질문',exact:true}).waitFor();

  await page.setViewportSize({width:375,height:900});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'mobile layout overflow');
  assert.ok(await page.getByRole('button',{name:'새로고침',exact:true}).evaluate(element=>element.getBoundingClientRect().height>=40));
  await page.evaluate(()=>{fixture.held='/kakao-archive/questions/'+fixture.ids.questionA+'/revisions/'+fixture.ids.revisionA;fixture.release=null;});
  await page.getByRole('button',{name:'첫 번째 질문',exact:true}).click();
  await page.waitForFunction(()=>fixture.release!==null);
  await page.evaluate(()=>{fixture.controller.setOwner('owner-b');fixture.release();});
  await page.waitForTimeout(40);
  assert.equal(await page.locator('[data-kakao="detail"] img').count(),0);
  assert.equal(await page.getByRole('link',{name:'PDF 내려받기'}).count(),0);
  assert.doesNotMatch(await page.locator('#kakao-archive-root').textContent(),/합성 학생|첫째 줄/);

  const ownerCalls=await page.evaluate(()=>fixture.calls.length);
  await page.evaluate(()=>fixture.controller.open());
  assert.equal(await page.evaluate(()=>fixture.calls.length),ownerCalls,'new owner reused old permissions');
  await page.evaluate(()=>fixture.controller.setPermissions(['kakao_archive:read','kakao_archive:collect','kakao_archive:export']));
  await page.getByRole('combobox',{name:'카카오 채널'}).selectOption({label:'합성 채널'});
  await page.getByRole('button',{name:'첫 번째 질문',exact:true}).waitFor();
  await page.evaluate(()=>{fixture.failBindings=true;});
  await page.getByRole('button',{name:'새로고침',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[role="status"]').textContent.includes('연결을 확인하지 못했습니다'));
  assert.equal(await page.getByRole('button',{name:'첫 번째 질문',exact:true}).count(),0,'failed authority read kept private data');
  assert.doesNotMatch(await page.locator('#kakao-archive-root').textContent(),/아직 연결된 채널이 없습니다/,'failure became empty success');
  const before = await page.evaluate(()=>fixture.calls.length);
  await page.evaluate(()=>{fixture.controller.setPermissions([]);fixture.controller.close();});
  await page.waitForTimeout(20);
  assert.equal(await page.evaluate(()=>fixture.calls.length),before,'close/permission loss dispatched a mutation');
  assert.deepEqual(errors,[]);
  console.log('KAKAO_ARCHIVE_BROWSER=PASS');
} finally {await browser.close(); await new Promise(resolve=>server.close(resolve));}
