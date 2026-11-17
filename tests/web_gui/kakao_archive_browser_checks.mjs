import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {createServer} from "node:http";
import {createRequire} from "node:module";

const require = createRequire(import.meta.url);
const {chromium} = require(process.env.EOM_WEB_PLAYWRIGHT_MODULE);
const root = new URL("../../apps/web_gui/eom_web_gui/static/", import.meta.url);
const assets = new Map(await Promise.all(["styles.css", "kakao-archive.css", "kakao-archive.js", "kakao-publications.js", "kakao-question-composer.js", "kakao-question-candidates.js", "kakao-students.js", "kakao-rooms.js", "kakao-manual.js", "kakao-captures.js"].map(async name => [name, await readFile(new URL(name, root), "utf8")])));
const app = `
import {createKakaoArchive} from './kakao-archive.js';
const id = (prefix, digit = '1') => prefix + '_' + digit.repeat(32);
const bindingId = id('kakaobinding'), roomId = id('kakaoroom'), questionA = id('kakaoquestion'), questionB = id('kakaoquestion', '2');
const revisionA = id('kakaoquestionrev'), revisionB = id('kakaoquestionrev', '2'), packetId = id('kakaopacket'), packetRevision = id('kakaopacketrev');
// Question/packet/export projections match the public DTO. Collection is still a future fixture.
const fixture = window.fixture = {calls: [], failCollection: true, held: null, release: null, failBindings: false, denyExports: false, duplicateInstall: false, secondRoom: false,confirmed:null,failReview:true,savedPacket:null,latestExport:null,failPacket:true,failExport:true};
const row = (number) => ({schema_version:'kakao-stored-question/1.0',source_binding_id:bindingId,room_id:roomId,
  question_id:number===1?questionA:questionB,question_revision_id:number===1?revisionA:revisionB,
  previous_revision_id:null,resource_version:1,review_state:'UNREVIEWED',first_student_at_utc:'2026-10-31T15:20:00Z',
  student:{student_id:id('kakaostudent',String(number)),student_display_revision_id:id('kakaostudentrev',String(number)),
    room_mapping_revision_id:id('kakaomappingrev',String(number)),display_name:number===1?'첫 번째 학생':'두 번째 학생'},
  manifest:{artifact_id:id('artifact'),artifact_revision_id:id('rev'),member_path:'question.json',media_type:'application/json',
    sha256:'sha256:'+'a'.repeat(64),schema_ref:'eom://schemas/kakao-archive/question-manifest-v1/1.0'},created_at:'2026-11-16T00:00:00Z'});
const binding = {source_binding_id: bindingId, display_name:'합성 채널', state:'ACTIVE', capability_state:'VERIFIED', collection_policy_revision_id:id('kakaopolicyrev'), allowed_actions:['READ_ARCHIVE','COLLECT']};
const page = items => ({items,next_cursor:null});
const packet = {schema_version:'kakao-stored-packet/1.0',source_binding_id:bindingId,packet_id:packetId,packet_revision_id:packetRevision,
  previous_revision_id:null,resource_version:1,title:'10월 질문 자료',manifest:{...row(1).manifest,member_path:'packet.json',schema_ref:'eom://schemas/kakao-archive/question-packet-v1/1.0'},
  display_start_date:'2026-10-01',display_end_date_inclusive:'2026-11-01',mode:'DRAFT',include_replies:false,question_count:2,student_count:2,created_at:'2026-11-16T00:00:00Z'};
const exported = {schema_version:'kakao-export/1.0',source_binding_id:bindingId,packet_id:packetId,packet_revision_id:packetRevision,student_id:row(1).student.student_id,
  export_id:id('kakaoexport'),profile:{renderer_release_sha256:'sha256:'+'a'.repeat(64),font_sha256:'sha256:'+'b'.repeat(64),font_size_bytes:100,layout_policy:'student-question-a4/1.0'},
  subset_sha256:'sha256:'+'c'.repeat(64),mode:'DRAFT',state:'COMPLETED',created_at:'2026-11-16T00:00:00Z',completed_at:'2026-11-16T00:01:00Z',export_revision_id:id('kakaoexportrev'),page_count:1,
  pdf:{...row(1).manifest,member_path:'report.pdf',media_type:'application/pdf',schema_ref:'eom://schemas/kakao-archive/question-pdf/1.0'},
  layout:{...row(1).manifest,member_path:'layout.json',schema_ref:'eom://schemas/kakao-archive/worker-question-layout/1.0'},error_code:null};
const room = (digit='1') => ({schema_version:'kakao-room/1.0',source_binding_id:bindingId,room_id:id('kakaoroom',digit),display_name:digit==='1'?'합성 대화방':'두 번째 대화방',state:'ACTIVE',identity_level:'MANUAL_CONFIRMED',resource_version:1,created_at:'2026-11-16T00:00:00Z',last_observed_at:'2026-11-16T00:00:00Z',mapping:{schema_version:'kakao-room-mapping/1.0',mapping_revision_id:id('kakaomappingrev',digit),previous_revision_id:null,resource_version:1,state:'UNMAPPED',student_id:null,student_display_revision_id:null,student_display_name:null,reason:'합성 확인',sha256:'sha256:'+'a'.repeat(64),created_at:'2026-11-16T00:00:00Z'}});
async function api(path, options = {}) {
  fixture.calls.push({path,method:options.method || 'GET',body:options.body,key:options.headers?.['Idempotency-Key']});
  const url = new URL(path,'http://fixture');
  if (url.pathname === '/kakao-archive/students') return page([]);
  if (fixture.held === path || (url.pathname.includes('/questions/') && fixture.held===url.pathname)) {fixture.held = null; await new Promise(resolve => fixture.release = resolve);}
  if (url.pathname === '/kakao-archive/source-bindings') {
    if (fixture.failBindings) throw new Error('SYNTHETIC_UNAVAILABLE');
    return page([binding,...(fixture.duplicateBindings?[{...binding,source_binding_id:id('kakaobinding','9')}]:[])]);
  }
  if (url.pathname.startsWith('/kakao-archive/source-bindings/')) return binding;
  if (url.pathname === '/kakao-archive/rooms') return page([room(),...(fixture.secondRoom?[room('2')]:[])]);
  if (url.pathname.startsWith('/kakao-archive/rooms/')) return room(url.pathname.endsWith(id('kakaoroom','2'))?'2':'1');
  if (url.pathname === '/kakao-archive/questions') return page(url.searchParams.get('room_id')===id('kakaoroom','2')?[{...row(2),room_id:id('kakaoroom','2')}]:[...(fixture.compositionRows||[fixture.confirmed||row(1)]),row(2)]);
  if (url.pathname === '/kakao-archive/questions/compose') {
    const body=options.body,inputs=body.operation==='SPLIT'?[body.input]:body.inputs;
    fixture.compositionRows=(body.operation==='SPLIT'?['4','5']:['6']).map(digit=>({...row(1),question_id:id('kakaoquestion',digit),question_revision_id:id('kakaoquestionrev',digit)}));
    return {schema_version:'kakao-question-composition-result/1.0',composition_id:id('kakaocomposition',body.operation==='SPLIT'?'1':'2'),operation:body.operation,source_binding_id:body.source_binding_id,room_id:body.room_id,inputs,outputs:fixture.compositionRows,replayed:false};
  }
  if (url.pathname.endsWith('/review')) {
    if(fixture.failReview){fixture.failReview=false;throw new Error('SYNTHETIC_RESPONSE_LOST');}
    fixture.confirmed={...row(1),question_revision_id:id('kakaoquestionrev','3'),previous_revision_id:revisionA,resource_version:2,review_state:'CONFIRMED'};
    return {schema_version:'kakao-question-mutation/1.0',question:fixture.confirmed,replayed:true};
  }
  if (url.pathname.startsWith('/kakao-archive/questions/')) {
    const first = path.includes(questionA + '/');
    const composed=fixture.compositionRows?.find(q=>url.pathname.includes(q.question_id+'/'));
    return {schema_version:'kakao-question-view/1.0',question:composed||(first?(fixture.confirmed||row(1)):row(2)),review_reasons:['BOUNDARY_REVIEW'],boundary_uncertain:true,
      ordered_blocks:[{kind:'TEXT',block_id:'text-1',role:'student',text:first?'첫째 줄\\n<script>window.privateLeak=true</script>':'두 번째 학생의 질문 본문'},
        {kind:'IMAGE',block_id:'photo-1',role:'student',availability:'expired',attachment_id:id('kakaoattachment','2'),attachment_revision_id:id('kakaoattachmentrev','2'),source_quality:'UNKNOWN'},
        {kind:'IMAGE',block_id:'photo-2',role:'student',availability:'available',attachment_id:id('kakaoattachment'),attachment_revision_id:id('kakaoattachmentrev'),source_quality:'ORIGINAL'}]};
  }
  if (url.pathname === '/kakao-archive/question-packets' && options.method==='POST') {
    if (options.body.mode==='FINAL') throw Object.assign(new Error('confirmation required'),{code:'KAKAO_ARCHIVE_FINAL_BLOCKED'});
    fixture.savedPacket||={...packet,packet_id:id('kakaopacket','4'),packet_revision_id:id('kakaopacketrev','4'),title:options.body.title,display_start_date:options.body.display_start_date,display_end_date_inclusive:options.body.display_end_date_inclusive,mode:options.body.mode,include_replies:options.body.include_replies,question_count:1,student_count:1};
    fixture.savedQuestions=options.body.questions;
    if(fixture.failPacket){fixture.failPacket=false;throw new Error('SYNTHETIC_LOST_AFTER_SAVE');}
    return {schema_version:'kakao-packet-mutation/1.0',packet:fixture.savedPacket,replayed:true};
  }
  if (url.pathname === '/kakao-archive/question-packets') return page([packet,...(fixture.savedPacket?[fixture.savedPacket]:[])]);
  if (url.pathname.startsWith('/kakao-archive/question-packets/')) {
    const saved=url.pathname.includes(id('kakaopacket','4'));
    return {schema_version:'kakao-packet-view/1.0',packet:saved?fixture.savedPacket:packet,
      questions:saved?fixture.savedQuestions:[row(1),row(2)].map(q=>({question_id:q.question_id,question_revision_id:q.question_revision_id})),
      students:(saved?[row(1)]:[row(1),row(2)]).map(q=>({student_id:q.student.student_id,student_display_revision_id:q.student.student_display_revision_id,display_name:q.student.display_name,question_count:1}))};
  }
  if (url.pathname === '/kakao-archive/exports' && options.method==='POST') {
    fixture.latestExport||={...exported,schema_version:'kakao-export/2.0',profile:{...exported.profile,layout_policy:'student-study-a4/1.0'},export_id:id('kakaoexport','4'),packet_id:options.body.packet_id,packet_revision_id:options.body.packet_revision_id,student_id:options.body.student_id,state:'PENDING',completed_at:null,export_revision_id:null,page_count:0,pdf:null,layout:null};
    if(fixture.failExport){fixture.failExport=false;throw new Error('SYNTHETIC_LOST_AFTER_REQUEST');}
    return {schema_version:'kakao-export-mutation/2.0',export:fixture.latestExport,replayed:true};
  }
  if (url.pathname.startsWith('/kakao-archive/exports/')) {
    fixture.latestExport={...fixture.latestExport,state:'COMPLETED',completed_at:'2026-11-16T00:01:00Z',export_revision_id:id('kakaoexportrev','4'),page_count:2,pdf:exported.pdf,layout:{...exported.layout,schema_ref:'eom://schemas/kakao-archive/worker-study-layout/1.0'}};
    return fixture.latestExport;
  }
  if (url.pathname === '/kakao-archive/exports') {
    if (fixture.denyExports) throw Object.assign(new Error('SYNTHETIC_DENIED'),{code:'PERMISSION_DENIED'});
    return page([exported,...(fixture.latestExport?[fixture.latestExport]:[])]);
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
  if (request.url.includes('/images/kakaoattachment_')) {
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
const browser = await chromium.launch({headless:true,channel:process.env.EOM_WEB_PLAYWRIGHT_CHANNEL||undefined});
try {
  const page = await browser.newPage({viewport:{width:1440,height:1000}}), errors = [], outbound = [];
  page.on('pageerror',error=>errors.push(error.message));
  page.on('request',request=>{if(!request.url().startsWith('http://127.0.0.1:'))outbound.push(request.url());});
  await page.goto('http://127.0.0.1:'+server.address().port+'/');
  await page.getByRole('combobox',{name:'카카오 채널'}).selectOption({label:'합성 채널'});
  await page.getByRole('button',{name:'첫 번째 학생의 질문',exact:true}).waitFor();
  assert.equal(await page.getByRole('heading',{name:'KakaoTalk',exact:true}).count(),1,'install duplicated listeners/markup');
  assert.equal(await page.getByRole('checkbox',{name:'조교 답변도 함께 넣기'}).isChecked(),true);
  assert.match(await page.locator('[data-kakao="rooms"]').textContent(),/학생 연결 필요/);
  await page.getByRole('button',{name:'첫 번째 학생의 질문',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[data-kakao="detail"]').textContent.includes('첫째 줄'));
  assert.match(await page.locator('[data-kakao="detail"]').textContent(),/2026.*11.*1/,'date was not KST');
  assert.equal(await page.locator('[data-kakao="detail"] script').count(),0);
  assert.equal(await page.evaluate(()=>window.privateLeak),undefined);
  assert.match(await page.locator('[data-kakao="detail"]').textContent(),/미확보 사진/);
  assert.match(await page.locator('[data-kakao="detail"] img').getAttribute('src'),/\/studio\/api\/v1\/kakao-archive\/questions\/kakaoquestion_.*\/revisions\/kakaoquestionrev_.*\/images\/kakaoattachment_.*source_binding_id=kakaobinding_.*room_id=kakaoroom_/);
  await page.getByRole('button',{name:'학생별 PDF 보기',exact:true}).click();
  const download = page.getByRole('link',{name:'PDF 내려받기'}); await download.waitFor();
  assert.match(await download.getAttribute('href'),/\/studio\/api\/v1\/kakao-archive\/exports\/kakaoexport_.*\/file\?source_binding_id=kakaobinding_.*revision_id=kakaoexportrev_/);
  assert.equal(outbound.length,0,'untrusted upstream URLs escaped same-origin delivery');
  await page.evaluate(()=>{fixture.denyExports=true;});
  await page.getByRole('button',{name:'학생별 PDF 보기',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.kakao-packet-detail').textContent.includes('자료를 열지 못했습니다'));
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
  await page.getByRole('button',{name:'첫 번째 학생의 질문',exact:true}).waitFor();
  assert.equal(await page.locator('[data-kakao="collect"]').isDisabled(),true);
  await page.evaluate(()=>fixture.release());
  await page.waitForFunction(()=>!document.querySelector('[data-kakao="collect"]').disabled);
  assert.equal(await page.locator('[data-kakao="collect"]').textContent(),'수집 상태 확인');
  await page.getByRole('button',{name:'수집 상태 확인',exact:true}).click();
  assert.equal(await page.evaluate(()=>fixture.calls.filter(call=>call.method==='POST').length),3,'reopened view retried accepted command');

  await page.evaluate(()=>{fixture.held='/kakao-archive/questions/'+fixture.ids.questionA+'/revisions/'+fixture.ids.revisionA;fixture.release=null;});
  await page.getByRole('button',{name:'첫 번째 학생의 질문',exact:true}).click();
  await page.waitForFunction(()=>fixture.release!==null);
  await page.getByRole('button',{name:'두 번째 학생의 질문',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[data-kakao="detail"]').textContent.includes('두 번째 학생의 질문 본문'));
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
  await page.waitForFunction(()=>document.querySelector('[data-kakao="questions"]').textContent.includes('두 번째 학생의 질문')&&!document.querySelector('[data-kakao="questions"]').textContent.includes('첫 번째 학생의 질문'));
  await page.evaluate(()=>fixture.release());await page.waitForTimeout(40);
  assert.equal(await page.getByRole('button',{name:'첫 번째 학생의 질문',exact:true}).count(),0,'late room A response overwrote room B');
  await page.getByRole('button',{name:'합성 대화방',exact:true}).click();
  await page.getByRole('button',{name:'첫 번째 학생의 질문',exact:true}).waitFor();

  // A detached old button cannot override the newly selected room or suppress its list.
  await page.evaluate(()=>{
    fixture.oldQuestion=[...document.querySelectorAll('button')].find(button=>button.textContent==='첫 번째 학생의 질문');
    const query=new URLSearchParams({source_binding_id:fixture.ids.bindingId,limit:'50',room_id:'kakaoroom_'+'2'.repeat(32)});
    fixture.held='/kakao-archive/questions?'+query;fixture.release=null;
  });
  await page.getByRole('button',{name:'두 번째 대화방',exact:true}).click();
  await page.waitForFunction(()=>fixture.release!==null);
  assert.equal(await page.getByRole('button',{name:'첫 번째 학생의 질문',exact:true}).count(),0,'old question remained during room load');
  const detailCalls=await page.evaluate(()=>fixture.calls.filter(call=>call.path.includes('/revisions/')).length);
  await page.evaluate(()=>{fixture.oldQuestion.click();fixture.release();});
  await page.getByRole('button',{name:'두 번째 학생의 질문',exact:true}).waitFor();
  assert.equal(await page.evaluate(()=>fixture.calls.filter(call=>call.path.includes('/revisions/')).length),detailCalls,'detached old button dispatched request');
  assert.equal(await page.getByRole('button',{name:'첫 번째 학생의 질문',exact:true}).count(),0);
  await page.getByRole('button',{name:'합성 대화방',exact:true}).click();
  await page.getByRole('button',{name:'첫 번째 학생의 질문',exact:true}).waitFor();

  await page.setViewportSize({width:375,height:900});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'mobile layout overflow');
  assert.ok(await page.getByRole('button',{name:'새로고침',exact:true}).evaluate(element=>element.getBoundingClientRect().height>=40));
  await page.evaluate(()=>{fixture.held='/kakao-archive/questions/'+fixture.ids.questionA+'/revisions/'+fixture.ids.revisionA;fixture.release=null;});
  await page.getByRole('button',{name:'첫 번째 학생의 질문',exact:true}).click();
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
  await page.getByRole('button',{name:'첫 번째 학생의 질문',exact:true}).waitFor();
  await page.evaluate(()=>{fixture.failBindings=true;});
  await page.getByRole('button',{name:'새로고침',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[role="status"]').textContent.includes('연결을 확인하지 못했습니다'));
  assert.equal(await page.getByRole('button',{name:'첫 번째 학생의 질문',exact:true}).count(),0,'failed authority read kept private data');
  assert.doesNotMatch(await page.locator('#kakao-archive-root').textContent(),/아직 연결된 채널이 없습니다/,'failure became empty success');
  await page.evaluate(()=>{fixture.failBindings=false;fixture.controller.setPermissions(['kakao_archive:read','kakao_archive:collect','kakao_archive:export','kakao_archive:edit']);});
  await page.getByRole('combobox',{name:'카카오 채널'}).selectOption({label:'합성 채널'});
  await page.getByRole('button',{name:'첫 번째 학생의 질문',exact:true}).click();
  const review=page.getByRole('form',{name:'질문 확인 저장'});
  await review.waitFor();
  assert.equal(await review.getByRole('button',{name:'질문 확인 완료',exact:true}).isDisabled(),true);
  await review.getByLabel('확인 메모').fill('원문과 사진 확인\n질문 경계도 확인');
  await review.getByRole('checkbox').check();
  await review.getByRole('button',{name:'질문 확인 완료',exact:true}).click();
  await review.getByRole('button',{name:'같은 확인 저장 요청 확인',exact:true}).waitFor();
  assert.equal(await review.getByLabel('확인 메모').isDisabled(),true,'uncertain intent allowed a different body');
  await review.getByRole('button',{name:'같은 확인 저장 요청 확인',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[data-kakao="detail"]').textContent.includes('CONFIRMED'));
  const reviews=await page.evaluate(()=>fixture.calls.filter(call=>call.path.includes('/review?')));
  assert.equal(reviews.length,2);assert.equal(reviews[0].key,reviews[1].key);
  assert.deepEqual(reviews[0].body,reviews[1].body);
  assert.equal(reviews[0].body.reason,'원문과 사진 확인\n질문 경계도 확인');
  assert.equal(reviews[0].body.parent_revision_id,await page.evaluate(()=>fixture.ids.revisionA));
  await page.getByRole('button',{name:'새로고침',exact:true}).click();
  await page.getByRole('button',{name:'첫 번째 학생의 질문',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[data-kakao="detail"]').textContent.includes('CONFIRMED'));
  await page.getByRole('button',{name:'자료에 넣기',exact:true}).first().click();
  const packetForm=page.getByRole('form',{name:'질문 자료 만들기'});
  await packetForm.getByLabel('자료 이름').fill('새 질문 자료');
  await packetForm.getByLabel('시작 날짜').fill('2026-01-01');
  await packetForm.getByLabel('마지막 날짜').fill('2026-12-31');
  await packetForm.getByLabel('자료 상태').selectOption('FINAL');
  await packetForm.getByRole('button',{name:'선택한 질문으로 자료 저장',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.kakao-packet-form [role="status"]').textContent.includes('확인 상태와 날짜'));
  assert.equal(await packetForm.getByLabel('자료 이름').isDisabled(),false,'domain refusal trapped immutable intent');
  await packetForm.getByLabel('자료 상태').selectOption('DRAFT');
  await packetForm.getByRole('button',{name:'선택한 질문으로 자료 저장',exact:true}).click();
  await packetForm.getByRole('button',{name:'같은 자료 저장 요청 확인',exact:true}).waitFor();
  assert.equal(await packetForm.getByLabel('자료 이름').isDisabled(),true);
  await packetForm.getByRole('button',{name:'같은 자료 저장 요청 확인',exact:true}).click();
  await page.getByRole('heading',{name:'새 질문 자료',exact:true}).waitFor();
  const packetCalls=await page.evaluate(()=>fixture.calls.filter(call=>call.path==='/kakao-archive/question-packets'&&call.method==='POST'));
  assert.equal(packetCalls[1].body.include_replies,true,'new packet omitted replies by default');
  assert.equal(packetCalls.length,3);assert.notEqual(packetCalls[0].key,packetCalls[1].key);assert.equal(packetCalls[1].key,packetCalls[2].key);assert.deepEqual(packetCalls[1].body,packetCalls[2].body);
  assert.equal(packetCalls[1].body.questions[0].question_revision_id,await page.evaluate(()=>fixture.confirmed.question_revision_id));
  await page.getByRole('button',{name:'학생 PDF 만들기',exact:true}).click();
  await page.getByRole('button',{name:'같은 PDF 요청 확인',exact:true}).waitFor();
  await page.getByRole('button',{name:'같은 PDF 요청 확인',exact:true}).click();
  await page.getByRole('button',{name:'상태 확인',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.kakao-packet-detail').textContent.includes('COMPLETED'));
  assert.match(await page.locator('.kakao-packet-detail').textContent(),/질문·답변과 기록 정보/);
  const exportCalls=await page.evaluate(()=>fixture.calls.filter(call=>call.path==='/kakao-archive/exports'&&call.method==='POST'));
  assert.equal(exportCalls.length,2);assert.equal(exportCalls[0].key,exportCalls[1].key);assert.deepEqual(exportCalls[0].body,exportCalls[1].body);
  const links=page.getByRole('link',{name:'PDF 내려받기',exact:true});
  assert.equal(await links.count(),2);
  assert.equal(await links.nth(0).getAttribute('href'),await links.nth(1).getAttribute('href'));
  await page.getByRole('button',{name:'상태 확인',exact:true}).first().click();
  assert.equal(await page.evaluate(()=>fixture.calls.filter(call=>call.path==='/kakao-archive/exports'&&call.method==='POST').length),2,'status read dispatched new PDF');
  await page.getByRole('button',{name:'새로고침',exact:true}).click();
  await page.getByRole('button',{name:'학생별 PDF 보기',exact:true}).last().click();
  await page.getByRole('heading',{name:'새 질문 자료',exact:true}).waitFor();
  assert.equal(await page.getByRole('link',{name:'PDF 내려받기',exact:true}).count(),1,'saved output history was lost');
  await page.getByRole('button',{name:'첫 번째 학생의 질문',exact:true}).click();
  await page.getByRole('button',{name:'질문 나누기 준비',exact:true}).click();
  const composer=page.getByRole('region',{name:'질문 구성 편집'});
  await composer.getByRole('checkbox',{name:'2번째 내용부터 새 질문'}).check();
  await page.evaluate(()=>{fixture.held='/kakao-archive/questions/compose';fixture.release=null;});
  await composer.getByRole('button',{name:'새 질문으로 저장',exact:true}).click();
  await page.waitForFunction(()=>fixture.release!==null);
  await page.getByRole('button',{name:'두 번째 학생의 질문',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[data-kakao="detail"]').textContent.includes('두 번째 학생의 질문 본문'));
  await page.evaluate(()=>fixture.release());
  await composer.getByRole('button',{name:'저장한 질문 열기',exact:true}).waitFor();
  assert.match(await page.locator('[data-kakao="detail"]').textContent(),/두 번째 학생의 질문 본문/,'late saved output overwrote the newer selection');
  await composer.getByRole('button',{name:'저장한 질문 열기',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.kakao-question-composer').textContent.includes('새 질문을 저장했습니다'));
  assert.match(await page.locator('[data-kakao="detail"] details').textContent(),/kakaoquestion_4444/,'split output was not opened');
  await page.getByRole('button',{name:'합칠 목록에 추가',exact:true}).nth(0).click();
  await page.getByRole('button',{name:'합칠 목록에 추가',exact:true}).nth(1).click();
  await composer.getByRole('button',{name:'새 질문으로 저장',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[data-kakao="detail"] details').textContent.includes('kakaoquestion_6666'));
  const compositions=await page.evaluate(()=>fixture.calls.filter(call=>call.path==='/kakao-archive/questions/compose'));
  assert.equal(compositions.length,2);assert.equal(compositions[0].body.input.question_revision_id,await page.evaluate(()=>fixture.confirmed.question_revision_id));
  assert.deepEqual(compositions[0].body.partitions,[[{kind:'BLOCK',block_id:'text-1'}],[{kind:'BLOCK',block_id:'photo-1'},{kind:'BLOCK',block_id:'photo-2'}]]);
  assert.deepEqual(compositions[1].body.inputs.map(q=>q.question_id),['4','5'].map(digit=>'kakaoquestion_'+digit.repeat(32)));
  assert.equal(await page.evaluate(()=>fixture.savedQuestions[0].question_revision_id),await page.evaluate(()=>fixture.confirmed.question_revision_id),'composition rewrote a saved packet');
  await page.evaluate(()=>{fixture.duplicateBindings=true;return fixture.controller.refresh();});
  const channel=page.getByRole('combobox',{name:'카카오 채널'});
  assert.equal(await channel.getByRole('option',{name:'합성 채널 · 연결 1',exact:true}).getAttribute('value'),await page.evaluate(()=>fixture.ids.bindingId));
  assert.notEqual(await channel.getByRole('option',{name:'합성 채널 · 연결 2',exact:true}).getAttribute('value'),await page.evaluate(()=>fixture.ids.bindingId));
  const before = await page.evaluate(()=>fixture.calls.length);
  await page.evaluate(()=>{fixture.controller.setPermissions([]);fixture.controller.close();});
  await page.waitForTimeout(20);
  assert.equal(await page.evaluate(()=>fixture.calls.length),before,'close/permission loss dispatched a mutation');
  assert.equal(await packetForm.getByLabel('자료 이름').inputValue(),'학생 질문 자료','permission loss retained private form title');
  assert.deepEqual(errors,[]);
  console.log('KAKAO_ARCHIVE_BROWSER=PASS');
} finally {await browser.close(); await new Promise(resolve=>server.close(resolve));}
