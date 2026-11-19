import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {createServer} from "node:http";
import {createRequire} from "node:module";

const {chromium} = createRequire(import.meta.url)(process.env.EOM_WEB_PLAYWRIGHT_MODULE);
const script = await readFile(new URL("../../apps/web_gui/eom_web_gui/static/kakao-room-collection.js", import.meta.url), "utf8");
const html = `<!doctype html><meta charset="utf-8"><section id="panel"></section><script type="module">
import {createKakaoRoomCollection} from './panel.js';
const bindingId='kakaobinding_'+'a'.repeat(32), roomA='kakaoroom_'+'b'.repeat(32), roomB='kakaoroom_'+'c'.repeat(32);
const run='kakaorun_'+'d'.repeat(32), created='2026-11-18T01:02:03Z';
const binding={state:'DRAFT', source_binding_id:bindingId,resource_version:3,policy_revision:{policy_revision_id:'kakaopolicyrev_'+'e'.repeat(32)}};
const room=id=>({room_id:id,source_binding_id:bindingId,state:'ACTIVE',identity_level:'MANUAL_CONFIRMED'});
const calls=[]; let lose=false, hold=false, release=null, state='QUEUED', version=1, reason=null;
const api=async(path,options)=>{
 calls.push({path,options:options??null});
 if(options?.method==='POST'&&lose){lose=false;throw Error('lost reply');}
 if(hold)await new Promise(resolve=>{release=resolve;});
 const collection={schema_version:'kakao-collection-status/1.0',source_binding_id:bindingId,run_id:run,state,resource_version:version,
    created_at:created,updated_at:created};
 if(reason&&path.includes('include_failure_reason=true'))return {schema_version:'kakao-collection-status-view/1.0',collection,failure_reason:reason};
 return collection;
};
const ui=createKakaoRoomCollection({document,api,explainError:()=>'fixture', schedule:setTimeout,unschedule:clearTimeout,pollMilliseconds:30000});
ui.install(document.querySelector('#panel'));
window.fixture={calls, select:(owner='owner-a',other=false,allowed=true)=>ui.setScope(owner,binding,room(other?roomB:roomA),allowed),
 lose:()=>{lose=true;},hold:()=>{hold=true;release=null;}, waiting:()=>Boolean(release),release:()=>{hold=false;release?.();},
 change:(next,hint=null)=>{state=next;reason=hint;version++;}};
fixture.select();
</script>`;
const server = createServer((request,response) => {
  if (request.url === '/panel.js') {response.setHeader('Content-Type','text/javascript'); response.end(script);}
  else if (request.url === '/') {response.setHeader('Content-Type','text/html;charset=utf-8'); response.end(html);}
  else {response.writeHead(404);response.end();}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser = await chromium.launch({headless:true,channel:process.env.EOM_WEB_PLAYWRIGHT_CHANNEL||undefined});
try {
  const page = await browser.newPage();
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  const base = 'http://127.0.0.1:'+server.address().port+'/';
  await page.goto(base);
  const button = name => page.getByRole('button',{name,exact:true});
  await button('이 방 수집 시작').waitFor();
  await page.evaluate(()=>fixture.lose());
  await button('이 방 수집 시작').click();
  await button('같은 수집 요청 확인').waitFor();
  const original = await page.evaluate(()=>fixture.calls[0]);
  await page.reload();
  await button('같은 수집 요청 확인').click();
  await page.getByText('대기 중',{exact:true}).waitFor();
  assert.deepEqual(await page.evaluate(()=>fixture.calls[0]),original);
  await page.reload();
  await page.getByText('대기 중',{exact:true}).waitFor();
  await button('수집 상태 확인').click();
  assert.ok((await page.evaluate(()=>fixture.calls)).every(call=>call.options===null));
  assert.match((await page.evaluate(()=>fixture.calls[0].path)), /\/collections\/kakaorun_[0-9a-f]+\?source_binding_id=/);
  await page.evaluate(()=>{fixture.hold();fixture.change('PARTIAL');});
  await button('수집 상태 확인').click();
  await page.waitForFunction(()=>fixture.waiting());
  await page.evaluate(()=>{fixture.select('owner-a',true);fixture.release();});
  await button('이 방 수집 시작').waitFor();
  assert.equal(await page.getByText('확인된 원본 저장 · 일부 범위 미확인',{exact:true}).count(),0);
  await page.evaluate(()=>fixture.select('owner-b',false,false));
  assert.equal(await button('이 방 수집 시작').count(),0);
  await page.evaluate(()=>fixture.select());
  await button('이 방 다시 수집').waitFor();
  await button('이 방 다시 수집').click();
  await button('수집 상태 확인').waitFor();
  const fresh=(await page.evaluate(()=>fixture.calls)).find(call=>call.options?.method==='POST');
  assert.notEqual(fresh.options.headers['Idempotency-Key'],original.options.headers['Idempotency-Key']);
  const countPosts = () => page.evaluate(()=>fixture.calls.filter(call=>call.options?.method==='POST').length);
  const posts = await countPosts();
  await page.evaluate(()=>fixture.change('FAILED','KAKAO_LOGIN_REQUIRED'));
  await button('수집 상태 확인').click();
  await page.getByText('카카오 로그인이 필요합니다.',{exact:false}).waitFor();
  await button('수집 상태 확인').click();
  await page.getByText('카카오 로그인이 필요합니다.',{exact:false}).waitFor();
  assert.equal(await countPosts(), posts);
  assert.deepEqual(errors,[]);
  console.log('KAKAO_ROOM_COLLECTION_BROWSER=PASS');
} finally { await browser.close(); await new Promise(resolve=>server.close(resolve)); }
