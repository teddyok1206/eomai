import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {createServer} from "node:http";
import {createRequire} from "node:module";
const {chromium} = createRequire(import.meta.url)(process.env.EOM_WEB_PLAYWRIGHT_MODULE);
const root = new URL("../../apps/web_gui/eom_web_gui/static/", import.meta.url);
const assets = new Map(await Promise.all(["styles.css","kakao-archive.css","kakao-captures.js"].map(async name => [name,await readFile(new URL(name,root),"utf8")])));
const id = prefix => prefix+'_'+'1'.repeat(32), binding=id('kakaobinding');
const payload = {schema_version:'kakao-manual-capture-page/1.0',source_binding_id:binding,binding_resource_version:1,scope:'RECENT_EIGHT_MANUAL_SESSIONS',truncated:false,items:[
  {manual_lease_id:id('kakaoremotelease'),capture_id:id('kakaodownload'),started_at:'2026-11-16T00:00:00Z',completed_at:'2026-11-16T00:00:01Z',size_bytes:1024,state:'ROOM_IDENTITY_OBSERVED',preview_sha256:'sha256:'+'a'.repeat(64)},
  {manual_lease_id:id('kakaoremotelease'),capture_id:'kakaodownload_'+'2'.repeat(32),started_at:'2026-11-16T00:00:00Z',completed_at:'2026-11-16T00:00:01Z',size_bytes:1024,state:'NO_OBSERVATION',preview_sha256:null}
]};
const mutations=[],receipts=new Map();
const app = `import {createKakaoCaptures} from './kakao-captures.js';
const state=window.fixture={owner:'one',lose:false,hold:false,release:null,opened:[]};
const api=async(path,options={})=>{
 const response=await fetch('/fixture',{method:'POST',body:JSON.stringify({path,options,owner:state.owner})});const value=await response.json();
 if(value.code)throw Object.assign(Error(value.code),{code:value.code});
 if(state.lose&&options.method==='POST'){state.lose=false;throw Error('RESPONSE_LOST');}
 if(state.hold){state.hold=false;await new Promise(resolve=>state.release=resolve);}
 return value;
};
const controller=state.controller=createKakaoCaptures({document,api,explainError:()=> '확인 필요',onConfirmed:async room=>state.opened.push(room.room_id)});
controller.install(document.querySelector('#captures'));controller.setOwner('one');controller.setRoles(['ADMIN']);controller.setPermissions(['kakao_archive:collect']);controller.open();controller.setBinding({source_binding_id:'${binding}',state:'DRAFT'});`;
const server=createServer(async(req,res)=>{
 const name=req.url.slice(1);
 if(name==='fixture'){
  let raw='';for await(const chunk of req)raw+=chunk;const {options,owner}=JSON.parse(raw);res.setHeader('Content-Type','application/json');
  if(owner!=='one'){res.end(JSON.stringify({code:'KAKAO_ARCHIVE_RESOURCE_NOT_FOUND'}));return;}
  if(options.method==='POST'){
   mutations.push(options);const key=options.headers['Idempotency-Key'];const prior=receipts.get(key);
   if(prior){assert.deepEqual(prior.body,options.body);res.end(JSON.stringify({...prior.result,replayed:true}));return;}
   assert.equal(options.headers['If-Match'],'"v1"');assert.equal(options.body.channel_and_room_confirmed,true);
   const result={room:{source_binding_id:binding,room_id:id('kakaoroom')},replayed:false};receipts.set(key,{body:options.body,result});res.end(JSON.stringify(result));return;
  }
  res.end(JSON.stringify(payload));return;
 }
 const content=name==='fixture.js'?app:name===''?'<html lang="ko"><head><meta charset="utf-8"><link rel="stylesheet" href="styles.css"><link rel="stylesheet" href="kakao-archive.css"></head><body><main style="max-width:1000px;padding:16px"><section id="captures"></section></main><script type="module" src="fixture.js"></script></body></html>':assets.get(name);
 if(content===undefined){res.writeHead(404);res.end();return;}
 res.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html');res.end(content);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const browser=await chromium.launch({headless:true});
try{
 const page=await browser.newPage({viewport:{width:1100,height:950}}),errors=[],outbound=[];
 page.on('pageerror',error=>errors.push(error.message));page.on('request',request=>{if(!request.url().startsWith('http://127.0.0.1:'))outbound.push(request.url());});
 await page.goto('http://127.0.0.1:'+server.address().port+'/');
 await page.getByRole('button',{name:'받은 자료 새로고침',exact:true}).click();
 await page.getByRole('button',{name:/^1\./}).waitFor();
 assert.equal(await page.getByRole('button',{name:/방 확인 정보 없음/}).isDisabled(),true);
 assert.equal(await page.getByRole('form',{name:'수신 대화방 확인'}).isVisible(),false);
 await page.getByRole('button',{name:/대화방 확인 정보 있음/}).click();
 await page.getByLabel('저장할 대화방 이름',{exact:true}).fill('학생 <img src=x> 방');
 await page.getByRole('checkbox').check();await page.evaluate(()=>fixture.lose=true);
 await page.getByRole('button',{name:'대화방 확인 저장',exact:true}).click();
 await page.getByRole('button',{name:'같은 방 확인 요청 확인',exact:true}).waitFor();
 await page.getByRole('button',{name:'같은 방 확인 요청 확인',exact:true}).click();
 await page.waitForFunction(()=>fixture.opened.length===1);
 assert.equal(mutations.length,2);assert.deepEqual(mutations[0],mutations[1]);assert.equal(receipts.size,1);
 assert.equal(await page.locator('#captures img,#captures script').count(),0);
 await page.reload();await page.getByRole('button',{name:'받은 자료 새로고침',exact:true}).click();
 await page.getByRole('button',{name:/대화방 확인 정보 있음/}).waitFor();assert.equal(mutations.length,2);
 await page.evaluate(()=>fixture.hold=true);await page.getByRole('button',{name:'받은 자료 새로고침',exact:true}).click();
 await page.waitForFunction(()=>fixture.release!==null);
 await page.evaluate(binding=>{fixture.owner='two';fixture.controller.setOwner('two');fixture.controller.setRoles(['ADMIN']);fixture.controller.setPermissions(['kakao_archive:collect']);fixture.controller.setBinding({source_binding_id:binding,state:'DRAFT'});fixture.release();},binding);
 await page.waitForTimeout(30);assert.equal(await page.locator('#captures .kakao-list-row').count(),0);
 await page.setViewportSize({width:390,height:850});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
 assert.deepEqual(errors,[]);assert.deepEqual(outbound,[]);console.log('KAKAO_CAPTURES_BROWSER=PASS');
}finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
