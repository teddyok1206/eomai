import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {createServer} from "node:http";
import {createRequire} from "node:module";

const require = createRequire(import.meta.url);
const {chromium} = require(process.env.EOM_WEB_PLAYWRIGHT_MODULE);
const root = new URL("../../apps/web_gui/eom_web_gui/static/", import.meta.url);
const assets = new Map(await Promise.all(["styles.css", "kakao-archive.css", "kakao-manual.js"].map(async name => [name, await readFile(new URL(name, root), "utf8")])));
const app = `
import {createKakaoManual} from './kakao-manual.js';
const id=p=>p+'_'+'1'.repeat(32), binding={source_binding_id:id('kakaobinding'),state:'DRAFT'};
const f=window.fixture={calls:[],timers:new Map(),serial:0,time:Date.now(),current:null,receipts:new Map(),failStart:true,failRenew:false,holdRead:false,release:null,configEnabled:false,holdConfig:false,releaseConfig:null};
const prepare=()=>({schema_version:'kakao-manual-session/1.0',lease_id:id('kakaoremotelease'),source_binding_id:binding.source_binding_id,
 phase:'PREPARING',resource_version:1,grant_revision:0,created_at:new Date(f.time).toISOString(),expires_at:null,
 absolute_expires_at:new Date(f.time+1200000).toISOString(),ready:false,last_error:null,ended_reason:null,closed_at:null});
const api=async(path,options={})=>{
 const call={path,method:options.method||'GET',body:options.body,headers:options.headers};f.calls.push(call);
 if(path.endsWith('/remote/configuration')) {const enabled=f.configEnabled;if(f.holdConfig){f.holdConfig=false;await new Promise(r=>f.releaseConfig=r);}return {schema_version:'kakao-remote-presentation/1.0',remote_view_enabled:enabled};}
 if(call.method==='GET') {const result=structuredClone(f.current);if(f.holdRead){f.holdRead=false;await new Promise(r=>f.release=r);}return result;}
 const key=options.headers['Idempotency-Key'];if(f.receipts.has(key))return {...structuredClone(f.receipts.get(key)),replayed:true};
 if(f.refuseProfile&&path.endsWith('/manual-sessions')) {f.refuseProfile=false;throw Object.assign(Error('admission refused'),{code:'KAKAO_ARCHIVE_REMOTE_PROFILE_UNAVAILABLE'});}
 if(path.endsWith('/manual-sessions')) f.current=prepare();
 else if(options.body.action==='RENEW') {
  assertGrant(options.body.expected_grant_revision);f.current={...f.current,grant_revision:f.current.grant_revision+1,resource_version:f.current.resource_version+1,expires_at:new Date(f.time+30000).toISOString()};
 } else {if(options.headers['If-Match']!=='"v'+f.current.resource_version+'"')throw Error('wrong etag');f.current={...f.current,phase:'STOPPING',ready:false,resource_version:f.current.resource_version+1,ended_reason:'USER_ENDED'};}
 const result={session:structuredClone(f.current),replayed:false};f.receipts.set(key,result);
 if(f.failStart&&path.endsWith('/manual-sessions')){f.failStart=false;throw Error('lost response');}
 if(f.failRenew&&options.body.action==='RENEW'){f.failRenew=false;throw Error('lost renewal');}return result;
};
function assertGrant(value){if(value!==f.current.grant_revision)throw Error('wrong grant');}
f.ready=()=>{f.current={...f.current,phase:'ACTIVE',ready:true,resource_version:3,grant_revision:1,expires_at:new Date(f.time+30000).toISOString()};};
f.runHeartbeat=()=>{const entry=[...f.timers].find(([,v])=>v.delay===10000);if(!entry)throw Error('missing heartbeat');f.timers.delete(entry[0]);entry[1].fn();};
f.mount=async(enabled=false)=>{f.controller?.close();f.current=null;f.receipts.clear();f.failStart=false;
 f.controller=createKakaoManual({document,api,explainError:()=> '합성 오류',now:()=>f.time,remoteViewEnabled:enabled,
 schedule:(fn,delay)=>{const key=++f.serial;f.timers.set(key,{fn,delay});return key;},unschedule:key=>f.timers.delete(key)});
 f.controller.install(document.querySelector('main'));f.controller.setOwner('owner-a');f.controller.setRoles(['ADMIN']);
 f.controller.setPermissions(['kakao_archive:remote']);await f.controller.setBinding(binding);f.controller.open();
};
await f.mount();f.failStart=true;
`;
const server=createServer((request,response)=>{
  const name=(request.url||'').split('/').pop();
  const content=name==='fixture.js'?app:name===''?'<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><link rel="stylesheet" href="styles.css"><link rel="stylesheet" href="kakao-archive.css"><main style="padding:20px"></main><script type="module" src="fixture.js"></script></html>':assets.get(name);
  if(content===undefined){response.writeHead(404);response.end();return;}
  response.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html');response.end(content);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser=await chromium.launch({headless:true});
try {
  const page=await browser.newPage({viewport:{width:1000,height:800}}),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto('http://127.0.0.1:'+server.address().port+'/');
  const start=page.getByRole('button',{name:'카카오 로그인 준비',exact:true});
  await start.click();await page.getByRole('button',{name:'같은 로그인 요청 확인'}).waitFor();
  assert.equal(await page.locator('iframe').count(),0);
  await page.getByRole('button',{name:'같은 로그인 요청 확인'}).click();
  await page.getByText('로그인 화면을 준비하고 있습니다.',{exact:true}).waitFor();
  const requests=await page.evaluate(()=>fixture.calls.filter(v=>v.method==='POST'));
  assert.equal(requests.length,2);assert.equal(requests[0].headers['Idempotency-Key'],requests[1].headers['Idempotency-Key']);assert.deepEqual(requests[0].body,requests[1].body);
  await page.evaluate(()=>fixture.ready());await page.getByRole('button',{name:'로그인 상태 확인'}).click();
  await page.getByText('서버의 원격 화면 연결이 아직 활성화되지 않았습니다.',{exact:false}).waitFor();
  assert.equal(await page.locator('iframe').count(),0,'READY did not authorize uninstalled proxy');
  await page.evaluate(()=>{fixture.time+=10000;fixture.failRenew=true;fixture.runHeartbeat();});
  await page.getByRole('button',{name:'같은 로그인 요청 확인'}).waitFor();
  await page.getByRole('button',{name:'같은 로그인 요청 확인'}).click();
  await page.getByText('로그인 연결이 준비됐습니다.',{exact:true}).waitFor();
  const renewals=await page.evaluate(()=>fixture.calls.filter(v=>v.body?.action==='RENEW'));
  assert.equal(renewals.length,2);assert.deepEqual(renewals[0],renewals[1]);
  await page.getByRole('button',{name:'로그인 연결 종료'}).click();
  await page.getByText('로그인 연결을 안전하게 닫고 있습니다.',{exact:true}).waitFor();
  const ending=await page.evaluate(()=>fixture.calls.at(-1));assert.equal(ending.headers['If-Match'],'"v4"');
  await page.evaluate(()=>fixture.controller.close());assert.equal(await page.evaluate(()=>fixture.timers.size),0);
  // Source feature flag alone is insufficient; active lease still required.
  await page.evaluate(()=>fixture.mount(true));await start.click();assert.equal(await page.locator('iframe').count(),0);
  await page.evaluate(()=>fixture.ready());await page.getByRole('button',{name:'로그인 상태 확인'}).click();
  await page.locator('iframe').waitFor();assert.equal(await page.locator('iframe').getAttribute('src'),'/studio/admin/remote/vnc.html');
  const frameHandle=await page.locator('iframe').elementHandle();
  await page.evaluate(()=>{fixture.time+=10000;fixture.runHeartbeat();});await page.waitForFunction(()=>fixture.current.grant_revision===2);
  assert.ok(await frameHandle.evaluate(el=>el.isConnected),'renewal replaced the live login frame');
  await page.evaluate(()=>{fixture.holdRead=true;void fixture.controller.refresh();});await page.waitForFunction(()=>fixture.release!==null);
  await page.evaluate(()=>{fixture.controller.setOwner('owner-b');fixture.release();});
  await page.waitForTimeout(50);assert.equal(await page.locator('iframe').count(),0);
  assert.equal(await page.evaluate(()=>fixture.timers.size),0);
  assert.equal(await page.locator('main').isVisible(),false);
  // Production controller reads presentation configuration, not a hard-coded flag.
  await page.evaluate(()=>{fixture.configEnabled=true;return fixture.mount(null);});
  await start.click();assert.equal(await page.locator('iframe').count(),0);
  await page.evaluate(()=>fixture.ready());await page.getByRole('button',{name:'로그인 상태 확인'}).click();
  await page.locator('iframe').waitFor();
  await page.evaluate(()=>{fixture.holdConfig=true;return fixture.mount(null);});
  await page.waitForFunction(()=>fixture.releaseConfig!==null);
  await page.evaluate(()=>{fixture.controller.setOwner('other-owner');fixture.releaseConfig();});
  await page.waitForTimeout(50);assert.equal(await page.locator('iframe').count(),0);
  assert.equal(await page.evaluate(()=>localStorage.length),0);
  assert.equal(await page.evaluate(()=>sessionStorage.length),0);
  await page.evaluate(()=>fixture.mount(true));
  await page.evaluate(()=>{fixture.refuseProfile=true;});
  await start.click();
  await page.getByText('선택한 연결과 로그인 프로필 상태를 확인해 주세요. 같은 이름의 연결이 여러 개라면 연결 번호를 구분해 선택해 주세요.',{exact:true}).waitFor();
  assert.equal(await start.isDisabled(),false,'explicit refusal kept a locked uncertain intent');
  const refused=await page.evaluate(()=>fixture.calls.at(-1));
  await start.click();
  const corrected=await page.evaluate(()=>fixture.calls.at(-1));
  assert.notEqual(refused.headers['Idempotency-Key'],corrected.headers['Idempotency-Key']);
  assert.deepEqual(errors,[]);console.log('KAKAO_MANUAL_BROWSER=PASS');
} finally {await browser.close();await new Promise(resolve=>server.close(resolve));}
