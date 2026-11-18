import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {createServer} from "node:http";
import {createRequire} from "node:module";

const require = createRequire(import.meta.url);
const {chromium} = require(process.env.EOM_WEB_PLAYWRIGHT_MODULE);
const root = new URL("../../apps/web_gui/eom_web_gui/static/", import.meta.url);
const assets = new Map(await Promise.all(["styles.css", "kakao-archive.css", "kakao-archive.js", "kakao-publications.js", "kakao-study-editor.js", "kakao-concept-picker.js", "kakao-question-composer.js", "kakao-question-candidates.js", "kakao-students.js", "kakao-rooms.js", "kakao-room-collection.js", "kakao-manual.js", "kakao-captures.js"].map(async name => [name, await readFile(new URL(name, root), "utf8")])));
const app = `
import {createKakaoArchive} from './kakao-archive.js';
const id=(prefix,n)=>prefix+'_'+n.toString(16).padStart(32,'0');
const fixture=window.fixture={owner:'owner-a',calls:[],stores:new Map(),receipts:new Map(),next:3,hold:null,releases:{},lose:false,deny:false,stale:false};
const fresh=(n,name)=>({schema_version:'kakao-student/1.0',student_id:id('kakaostudent',n),display_revision_id:id('kakaostudentrev',n),previous_revision_id:null,resource_version:1,
  display_name:name,state:'ACTIVE',sha256:'sha256:'+'a'.repeat(64),created_at:'2026-11-16T00:00:00Z',updated_at:'2026-11-16T00:00:00Z'});
fixture.ids=[id('kakaostudent',1),id('kakaostudent',2)];
fixture.stores.set('owner-a',new Map([[fixture.ids[0],fresh(1,'동명이인 <img src=x>')],[fixture.ids[1],fresh(2,'동명이인 <img src=x>')]]));
fixture.stores.set('owner-b',new Map());
const api=async(path,options={})=>{
  const currentOwner=fixture.owner,method=options.method||'GET',url=new URL(path,'http://fixture');
  fixture.calls.push({owner:currentOwner,path,method,body:options.body,headers:options.headers});
  if(url.pathname==='/kakao-archive/source-bindings')return {items:[],next_cursor:null};
  const store=fixture.stores.get(currentOwner),key=currentOwner+':'+options.headers?.['Idempotency-Key'];
  let result;
  if(options.method==='POST'){
    if(fixture.receipts.has(key))result={...fixture.receipts.get(key),replayed:true};
    else{
      if(url.pathname==='/kakao-archive/students'){
        const value=fresh(fixture.next++,options.body.display_name);store.set(value.student_id,value);result={student:value,replayed:false};
      }else if(url.pathname.endsWith('/commands')){
        const target=url.pathname.split('/').at(-2),old=store.get(target);
        if(fixture.stale){fixture.stale=false;throw Object.assign(new Error('STALE'),{code:'KAKAO_ARCHIVE_PRECONDITION_FAILED'});}
        if(options.headers['If-Match']!=='"v'+old.resource_version+'"'||options.body.parent_revision_id!==old.display_revision_id)throw Error('INCORRECT_PARENT');
        const value={...old,previous_revision_id:old.display_revision_id,display_revision_id:id('kakaostudentrev',100+fixture.next++),resource_version:old.resource_version+1,
          display_name:options.body.action==='RENAME'?options.body.display_name:old.display_name,state:options.body.action==='RETIRE'?'RETIRED':'ACTIVE'};
        store.set(target,value);result={student:value,replayed:false};
      }else throw Error('UNIMPLEMENTED:'+path);
      fixture.receipts.set(key,structuredClone(result));
      if(fixture.lose){fixture.lose=false;throw Error('RESPONSE_LOST');}
    }
  }else if(url.pathname==='/kakao-archive/students'){
    let values=[...store.values()].sort((a,b)=>a.student_id.localeCompare(b.student_id));
    const cursor=url.searchParams.get('cursor');if(cursor)values=values.filter(value=>value.student_id>cursor);
    result={items:values.slice(0,50),next_cursor:values.length>50?values[49].student_id:null};
  }else if(url.pathname.startsWith('/kakao-archive/students/')){
    if(fixture.deny)throw Object.assign(new Error('DENIED'),{code:'KAKAO_ARCHIVE_PERMISSION_DENIED'});
    result=store.get(url.pathname.split('/').at(-1));
  }else throw Error('UNIMPLEMENTED:'+path);
  result=structuredClone(result);
  if(fixture.hold&&fixture.hold.method===method&&fixture.hold.path===url.pathname){const hold=fixture.hold;fixture.hold=null;await new Promise(resolve=>fixture.releases[hold.tag]=resolve);}
  return result;
};
const controller=createKakaoArchive({document,api,explainError:error=>error.code||'합성 오류',setStateStatus(el,_domain,value){el.textContent=value;}});
fixture.controller=controller;controller.install();controller.setOwner(fixture.owner);controller.setRoles(['VIEWER']);controller.setPermissions(['kakao_archive:read']);await controller.open();
fixture.addMany=()=>{const store=fixture.stores.get(fixture.owner);for(let n=1000;n<1051;n++){const value=fresh(n,'페이지 학생 '+n);store.set(value.student_id,value);}};
`;
const server=createServer((request,response)=>{
  const name=(request.url||'').split('/').pop();
  const html='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><link rel="stylesheet" href="styles.css"><link rel="stylesheet" href="kakao-archive.css"><main style="padding:20px"><section id="kakao-archive-root"></section></main><script type="module" src="fixture.js"></script></html>';
  const content=name==='fixture.js'?app:name===''?html:assets.get(name);
  if(content===undefined){response.writeHead(404);response.end();return;}
  response.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html');response.end(content);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser=await chromium.launch({headless:true,channel:process.env.EOM_WEB_PLAYWRIGHT_CHANNEL||undefined});
try {
  const page=await browser.newPage({viewport:{width:1200,height:900}}),errors=[],outbound=[];
  page.on('pageerror',error=>errors.push(error.message));
  page.on('request',request=>{if(!request.url().startsWith('http://127.0.0.1:'))outbound.push(request.url());});
  await page.goto('http://127.0.0.1:'+server.address().port+'/');
  const region=page.getByRole('region',{name:'학생 관리'}),status=region.getByRole('status'),select=page.getByRole('combobox',{name:'학생',exact:true});
  await region.waitFor();await page.waitForFunction(()=>document.querySelector('[aria-label="학생"]')?.options.length===3);
  assert.equal(await page.getByRole('form',{name:'학생 추가',exact:true}).isVisible(),false);
  assert.equal(await page.getByRole('form',{name:'채널 연결 준비'}).isVisible(),false);
  const ids=await page.evaluate(()=>fixture.ids);await select.selectOption(ids[0]);
  await page.waitForFunction(()=>document.querySelector('[data-kakao="student-detail"]').textContent.includes('동명이인'));
  assert.equal(await page.getByRole('button',{name:'이름 저장',exact:true}).count(),0);
  assert.equal(await region.locator('img').count(),0);
  await page.evaluate(()=>fixture.controller.setPermissions(['kakao_archive:read','kakao_archive:edit']));
  await select.selectOption(ids[0]);await page.getByRole('textbox',{name:'표시 이름',exact:true}).waitFor();
  assert.equal(await page.getByRole('form',{name:'채널 연결 준비'}).isVisible(),false,'student EDIT became channel ADMIN');
  await page.getByRole('textbox',{name:'표시 이름',exact:true}).fill('이름 변경 <script>');
  await page.evaluate(()=>{fixture.lose=true;});await page.getByRole('button',{name:'이름 저장',exact:true}).click();
  await status.filter({hasText:'처리 여부를 확인하지 못했습니다'}).waitFor();
  await page.getByRole('button',{name:'새로고침',exact:true}).click();
  await select.selectOption(ids[0]);
  await page.getByRole('button',{name:'같은 학생 요청 확인',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[data-kakao="student-detail"] h3')?.textContent==='이름 변경 <script>');
  let posts=await page.evaluate(()=>fixture.calls.filter(call=>call.method==='POST'));
  assert.equal(posts.length,2);assert.equal(posts[0].headers['Idempotency-Key'],posts[1].headers['Idempotency-Key']);
  assert.deepEqual(posts[0].body,posts[1].body);assert.equal(posts[0].headers['If-Match'],'"v1"');
  assert.equal(await region.locator('script').count(),0);

  // Same name remains a separate student; successful explicit creates receive new identities.
  const name=page.getByRole('textbox',{name:'새 학생 이름',exact:true});
  for(let i=0;i<2;i++){
    await name.fill('동명이인 <img src=x>');await page.getByRole('button',{name:'학생 추가',exact:true}).click();
    await page.waitForFunction(expected=>document.querySelector('[aria-label="학생"]')?.options.length===expected,4+i);
    await page.getByRole('button',{name:'학생 추가',exact:true}).waitFor({state:'visible'});
    await page.waitForFunction(()=>!document.querySelector('[aria-label="학생 추가"] button').disabled);
  }
  posts=await page.evaluate(()=>fixture.calls.filter(call=>call.method==='POST'));
  assert.notEqual(posts[2].headers['Idempotency-Key'],posts[3].headers['Idempotency-Key']);
  const createdIds=await page.evaluate(()=>[...fixture.stores.get('owner-a').keys()].slice(-2));
  assert.notEqual(createdIds[0],createdIds[1]);

  // An earlier selection must not overwrite the later student's detail.
  await page.evaluate(id=>{fixture.hold={method:'GET',path:'/kakao-archive/students/'+id,tag:'first'};},ids[0]);
  await select.selectOption(ids[0]);await page.waitForFunction(()=>fixture.releases.first);
  await select.selectOption(ids[1]);await page.waitForFunction(()=>document.querySelector('[data-kakao="student-detail"] h3')?.textContent==='동명이인 <img src=x>');
  await page.evaluate(()=>fixture.releases.first());await page.waitForTimeout(30);
  assert.equal(await page.locator('[data-kakao="student-detail"] h3').textContent(),'동명이인 <img src=x>');

  // Lost retirement response is replayable after current reads already show RETIRED.
  await page.locator('[data-kakao="student-retire-confirm"]').check();await page.evaluate(()=>{fixture.lose=true;});
  await page.getByRole('button',{name:'학생 사용 중지',exact:true}).click();await status.filter({hasText:'처리 여부를 확인하지 못했습니다'}).waitFor();
  await page.evaluate(async()=>{fixture.controller.close();await fixture.controller.open();});
  await select.selectOption(ids[1]);
  await page.waitForFunction(()=>document.querySelector('[data-kakao="student-detail"]').textContent.includes('사용 중지'));
  await page.getByRole('button',{name:'같은 학생 요청 확인',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('.kakao-students').textContent.includes('같은 학생 요청 확인'));
  posts=await page.evaluate(()=>fixture.calls.filter(call=>call.method==='POST'));
  assert.deepEqual(posts.at(-2).body,posts.at(-1).body);assert.equal(posts.at(-2).headers['Idempotency-Key'],posts.at(-1).headers['Idempotency-Key']);
  assert.equal(await page.getByRole('button',{name:'학생 사용 중지',exact:true}).count(),0);

  // A denied read removes formerly rendered private names and details, not just the error label.
  await page.evaluate(()=>{fixture.deny=true;});await select.selectOption(ids[0]);
  await status.filter({hasText:'학생 정보를 열지 못했습니다'}).waitFor();
  assert.doesNotMatch(await region.textContent(),/이름 변경|동명이인/);
  await page.evaluate(()=>{fixture.deny=false;});await page.getByRole('button',{name:'새로고침',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[aria-label="학생"]')?.options.length===5);

  // Owner reset clears names/permissions. The old response cannot unlock a newer owner's request.
  await name.fill('이전 계정 비공개');await page.evaluate(()=>{fixture.hold={method:'POST',path:'/kakao-archive/students',tag:'owner-a'};});
  await page.getByRole('button',{name:'학생 추가',exact:true}).click();await page.waitForFunction(()=>fixture.releases['owner-a']);
  await page.evaluate(async()=>{fixture.owner='owner-b';fixture.controller.setOwner('owner-b');await fixture.controller.open();});
  assert.equal(await region.isVisible(),false);
  assert.doesNotMatch(await page.locator('#kakao-archive-root').textContent(),/이전 계정 비공개/);
  await page.evaluate(()=>fixture.controller.setPermissions(['kakao_archive:read','kakao_archive:edit']));
  await name.fill('새 계정 비공개');await page.evaluate(()=>{fixture.hold={method:'POST',path:'/kakao-archive/students',tag:'owner-b'};});
  await page.getByRole('button',{name:'학생 추가',exact:true}).click();await page.waitForFunction(()=>fixture.releases['owner-b']);
  await page.evaluate(()=>fixture.releases['owner-a']());await page.waitForTimeout(30);
  assert.equal(await page.getByRole('button',{name:'학생 추가',exact:true}).isDisabled(),true);
  await page.evaluate(()=>fixture.releases['owner-b']());await page.waitForFunction(()=>!document.querySelector('[aria-label="학생 추가"] button').disabled);
  assert.doesNotMatch(await region.textContent(),/이전 계정 비공개/);

  // A stale command is not silently rebased or retried with a fresh parent/key.
  await page.getByRole('textbox',{name:'표시 이름',exact:true}).fill('오래된 변경');
  await page.evaluate(()=>{fixture.stale=true;});
  const beforeStale=await page.evaluate(()=>fixture.calls.filter(call=>call.method==='POST').length);
  await page.getByRole('button',{name:'이름 저장',exact:true}).click();
  await status.filter({hasText:'학생 상태나 권한이 변경됐습니다'}).waitFor();
  await page.waitForTimeout(30);
  assert.equal(await page.evaluate(()=>fixture.calls.filter(call=>call.method==='POST').length),beforeStale+1);
  assert.equal(await page.getByRole('button',{name:'같은 학생 요청 확인',exact:true}).count(),0);

  // Keyset pages keep separate identities and never silently truncate after the first 50.
  await page.evaluate(()=>fixture.addMany());await page.getByRole('button',{name:'새로고침',exact:true}).click();
  await page.getByRole('button',{name:'학생 더 보기',exact:true}).waitFor();
  assert.equal(await select.locator('option').count(),51);
  // Add an identity beyond this page; the next page may legally include it again.
  await page.evaluate(()=>{fixture.next=2000;});await name.fill('다음 페이지에도 나올 학생');
  await page.getByRole('button',{name:'학생 추가',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('[aria-label="학생 추가"] button').disabled);
  assert.equal(await select.locator('option').count(),52);
  await page.getByRole('button',{name:'학생 더 보기',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[aria-label="학생"]')?.options.length===54);
  assert.equal(await page.getByRole('button',{name:'학생 더 보기',exact:true}).isVisible(),false);
  // JSON Schema counts code points, not UTF-16 units or rendered graphemes.
  const emojiName='😀'.repeat(80);await name.fill(emojiName);
  await page.getByRole('button',{name:'학생 추가',exact:true}).click();
  await page.waitForFunction(value=>document.querySelector('[data-kakao="student-detail"] h3')?.textContent===value,emojiName);
  const unicodePosts=await page.evaluate(()=>fixture.calls.filter(call=>call.method==='POST').length);
  const rename=page.getByRole('textbox',{name:'표시 이름',exact:true});
  await rename.fill('👩‍🔬'.repeat(64)); // 64 glyphs, 192 Unicode code points: too long.
  await page.getByRole('button',{name:'이름 저장',exact:true}).click();
  await status.filter({hasText:'학생 이름을 확인해 주세요'}).waitFor();
  assert.equal(await page.evaluate(()=>fixture.calls.filter(call=>call.method==='POST').length),unicodePosts);
  await rename.fill('😀'.repeat(128));await page.getByRole('button',{name:'이름 저장',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[data-kakao="student-detail"] h3')?.textContent==='😀'.repeat(128));
  await page.setViewportSize({width:375,height:900});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'student UI overflowed mobile');
  assert.deepEqual(errors,[]);assert.deepEqual(outbound,[]);
  console.log('KAKAO_STUDENTS_BROWSER=PASS');
}finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
