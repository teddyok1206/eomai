import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {createServer} from "node:http";
import {createRequire} from "node:module";
const {chromium} = createRequire(import.meta.url)(process.env.EOM_WEB_PLAYWRIGHT_MODULE);
const root = new URL("../../apps/web_gui/eom_web_gui/static/", import.meta.url);
const assets = new Map(await Promise.all(["styles.css","kakao-archive.css","kakao-question-candidates.js"].map(async name => [name, await readFile(new URL(name,root),"utf8")])));
const id = (prefix,digit="1")=>prefix+"_"+digit.repeat(32), binding=id("kakaobinding"),room=id("kakaoroom"),source=id("kakaosourcerev"),mapping=id("kakaomappingrev");
const mutations=[],reads=[],receipts=new Map();let hideSaved=false,latestRevision="1";
const storedQuestion=(digit="1")=>({source_binding_id:binding,room_id:room,question_id:id("kakaoquestion"),question_revision_id:id("kakaoquestionrev",digit),resource_version:Number(digit),previous_revision_id:digit==="1"?null:id("kakaoquestionrev"),review_state:"UNREVIEWED",student:{room_mapping_revision_id:mapping}});
const candidatePage=()=>({schema_version:"kakao-question-candidate-page/1.0",source_binding_id:binding,room_id:room,source_revision_id:source,source_resolution_sha256:"sha256:"+"a".repeat(64),mapping_revision_id:mapping,total_candidates:1,unknown_sender_rows:0,next_after_ordinal:null,items:[{
 candidate_ordinal:1,student_message_count:2,reply_message_count:1,photo_count:2,first_student_at_utc:null,preview:"학생의 <img src=x> 질문 · 원문은 변경하지 않습니다.",boundary_uncertain:true,review_reasons:["SOURCE_SCOPE_UNVERIFIED"],recomposed:false,saved_question:receipts.size&&!hideSaved?{question_id:id("kakaoquestion"),question_revision_id:id("kakaoquestionrev",latestRevision)}:null
}]});
const app=`import {createKakaoQuestionCandidates} from './kakao-question-candidates.js';
const fixture=window.fixture={owner:'one',lose:false,failOpen:false,failRead:false,hold:false,release:null,opened:[]};
const api=async(path,options={})=>{
 const response=await fetch('/fixture',{method:'POST',body:JSON.stringify({path,options,owner:fixture.owner,failRead:fixture.failRead})});fixture.failRead=false;const value=await response.json();
 if(fixture.hold){fixture.hold=false;await new Promise(resolve=>fixture.release=resolve);}
 if(value.code)throw Object.assign(Error(value.code),{code:value.code});
 if(fixture.lose&&options.method==='POST'){fixture.lose=false;throw Error('RESPONSE_LOST');}return value;
};
const controller=fixture.controller=createKakaoQuestionCandidates({document,api,explainError:()=> '일시적으로 확인하지 못했습니다.',onSaved:async question=>{if(fixture.failOpen){fixture.failOpen=false;throw Error('READ_LOST');}fixture.opened.push(question);return true;},onOpen:async question=>fixture.opened.push(question)});
controller.install(document.querySelector('#candidates'));controller.setOwner('one');controller.setPermissions(['kakao_archive:read','kakao_archive:edit']);controller.setBinding({source_binding_id:'${binding}'});controller.setRoom({room_id:'${room}',mapping:{state:'MAPPED',mapping_revision_id:'${mapping}'}});controller.open();`;
const server=createServer(async(req,res)=>{
 const name=req.url.slice(1);
 if(name==='fixture'){
  let raw='';for await(const chunk of req)raw+=chunk;const {path,options,owner,failRead}=JSON.parse(raw);res.setHeader('Content-Type','application/json');
  if(options.method==='POST'){
   const key=options.headers['Idempotency-Key'];mutations.push({owner,key,body:options.body});
   assert.equal(options.body.source_revision_id,source);assert.equal(options.body.expected_mapping_revision_id,mapping);assert.equal(options.body.candidate_ordinal,1);assert.equal(options.body.source_binding_id,binding);assert.equal(options.body.room_id,room);
   const previous=receipts.get(key);if(previous){assert.deepEqual(previous.body,options.body);res.end(JSON.stringify({...previous.result,replayed:true}));return;}
   const refresh=options.body.schema_version==="kakao-question-source-refresh/1.0";
   if(refresh){assert.equal(path,"/kakao-archive/questions/"+id("kakaoquestion")+"/refresh-source");assert.equal(options.headers["If-Match"],'"v1"');assert.equal(options.body.parent_revision_id,id("kakaoquestionrev"));assert.equal(options.body.replace_display_edits,true);latestRevision="2";}
   const result={question:storedQuestion(refresh?"2":"1"),replayed:false};receipts.set(key,{body:options.body,result});res.end(JSON.stringify(result));return;
  }
  if(path.includes("/revisions/")){reads.push(path);res.end(JSON.stringify({question:storedQuestion(latestRevision)}));return;}
  reads.push(path);res.end(JSON.stringify(failRead?{code:'HTTP_503'}:candidatePage()));return;
 }
 const content=name==='fixture.js'?app:name===''?'<html lang="ko"><head><meta charset="utf-8"><link rel="stylesheet" href="styles.css"><link rel="stylesheet" href="kakao-archive.css"></head><body><main style="max-width:1000px;padding:16px"><section id="candidates"></section></main><script type="module" src="fixture.js"></script></body></html>':assets.get(name);
 if(content===undefined){res.writeHead(404);res.end();return;}res.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html');res.end(content);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const browser=await chromium.launch({headless:true,channel:"chromium"});
try{
 const page=await browser.newPage({viewport:{width:1100,height:950}}),errors=[],outbound=[];
 page.on('pageerror',error=>errors.push(error.message));page.on('request',request=>{if(!request.url().startsWith('http://127.0.0.1:'))outbound.push(request.url());});
 await page.goto('http://127.0.0.1:'+server.address().port+'/');
 await page.getByRole('button',{name:'원본에서 질문 찾기',exact:true}).click();await page.getByRole('button',{name:'질문으로 저장',exact:true}).waitFor();
 assert.equal(await page.locator('#candidates img,#candidates script').count(),0);
 await page.evaluate(()=>{fixture.lose=true;fixture.failOpen=true;});await page.getByRole('button',{name:'질문으로 저장',exact:true}).click();
 await page.getByRole('button',{name:'같은 저장 요청 확인',exact:true}).waitFor();await page.getByRole('button',{name:'같은 저장 요청 확인',exact:true}).click();
 await page.getByRole('button',{name:'저장 결과 다시 열기',exact:true}).waitFor();
 assert.equal(mutations.length,2);assert.deepEqual(mutations[0],mutations[1]);assert.equal(receipts.size,1);
 await page.getByRole('button',{name:'저장 결과 다시 열기',exact:true}).click();await page.waitForFunction(()=>fixture.opened.length===1);assert.equal(mutations.length,2);
 await page.evaluate(()=>fixture.failRead=true);await page.getByRole('button',{name:'후보 다시 확인',exact:true}).click();await page.getByText(/후보를 확인하지 못했습니다/).waitFor();
 await page.getByRole('button',{name:'원본에서 질문 찾기',exact:true}).click();await page.getByRole('button',{name:'저장한 질문 열기',exact:true}).waitFor();
 assert.ok(reads.at(-1).includes('source_revision_id='+source));
 // Simulate an earlier in-flight read after reload, before its create result was visible.
 // A reconstructed flat command must still reuse the original request key.
 hideSaved=true;await page.reload();await page.getByRole('button',{name:'원본에서 질문 찾기',exact:true}).click();await page.getByRole('button',{name:'질문으로 저장',exact:true}).click();
 await page.waitForFunction(()=>fixture.opened.length===1);assert.equal(mutations.length,3);assert.deepEqual(mutations[2],mutations[0]);assert.equal(receipts.size,1);
 assert.equal(JSON.stringify(mutations).includes('학생의'),false);
 hideSaved=false;await page.getByRole('button',{name:'후보 다시 확인',exact:true}).click();
 await page.getByRole('button',{name:'이 원본으로 새 검토본 준비',exact:true}).click();
 const refreshButton=page.getByRole('button',{name:'새 검토본 저장',exact:true});await refreshButton.waitFor();
 assert.equal(await refreshButton.isDisabled(),true);assert.equal(mutations.length,3);
 await page.getByRole('checkbox').check();await page.evaluate(()=>{fixture.lose=true;fixture.failOpen=true;});await refreshButton.click();
 await page.getByRole('button',{name:'같은 저장 요청 확인',exact:true}).click();
 await page.getByRole('button',{name:'저장 결과 다시 열기',exact:true}).waitFor();
 assert.equal(mutations.length,5);assert.deepEqual(mutations[3],mutations[4]);assert.equal(receipts.size,2);
 await page.getByRole('button',{name:'저장 결과 다시 열기',exact:true}).click();
 await page.waitForFunction(()=>fixture.opened.length===2);
 assert.equal(mutations.length,5);assert.equal(await page.locator('#candidates input[type=checkbox]').count(),0);
 await page.evaluate(()=>fixture.hold=true);await page.getByRole('button',{name:'후보 다시 확인',exact:true}).click();await page.waitForFunction(()=>fixture.release!==null);
 await page.evaluate(({binding,room,mapping})=>{fixture.owner='two';fixture.controller.setOwner('two');fixture.controller.setPermissions(['kakao_archive:read','kakao_archive:edit']);fixture.controller.setBinding({source_binding_id:binding});fixture.controller.setRoom({room_id:room,mapping:{state:'MAPPED',mapping_revision_id:mapping}});fixture.release();},{binding,room,mapping});
 await page.waitForTimeout(30);assert.equal(await page.locator('#candidates .kakao-composition-block').count(),0);
 await page.setViewportSize({width:390,height:850});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
 assert.deepEqual(errors,[]);assert.deepEqual(outbound,[]);console.log('KAKAO_CANDIDATES_BROWSER=PASS');
}finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
