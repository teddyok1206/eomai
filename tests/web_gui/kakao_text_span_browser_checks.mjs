import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {createServer} from "node:http";
import {createRequire} from "node:module";
const {chromium} = createRequire(import.meta.url)(process.env.EOM_WEB_PLAYWRIGHT_MODULE);
const root = new URL("../../apps/web_gui/eom_web_gui/static/", import.meta.url);
const files = new Map(await Promise.all(["styles.css","kakao-archive.css","kakao-question-composer.js"].map(async name => [name,await readFile(new URL(name,root),"utf8")])));
const id = (prefix,char) => `${prefix}_${char.repeat(32)}`;
const q = {source_binding_id:id("kakaobinding","a"),room_id:id("kakaoroom","b"),question_id:id("kakaoquestion","1"),question_revision_id:id("kakaoquestionrev","2"),resource_version:1};
const text = "😀가\r\n가나 끝";
const view = {question:q,ordered_blocks:[{kind:"TEXT",block_id:"text-1",text},{kind:"IMAGE",block_id:"picture-1"}]};
const context = {schema_version:"kakao-question-edit-context/1.0",...q,text_blocks:[{block_id:"text-1",can_split:true,start_codepoint:7,end_codepoint:7+[...text].length}]};
const fixture = `import {createKakaoQuestionComposer} from './kakao-question-composer.js';
const view=${JSON.stringify(view)},context=${JSON.stringify(context)};
const state=window.fixture={view,context,posts:[],receipts:new Map(),opened:[],lose:true,hold:false,release:null};
const api=async(path,options={})=>{
 if(path.includes('/edit-context?')) {const value=structuredClone(state.context);if(state.hold){state.hold=false;await new Promise(resolve=>state.release=resolve);}return value;}
 if(path!=='/kakao-archive/questions/compose')throw Error('unexpected request');
 const body=structuredClone(options.body),key=options.headers['Idempotency-Key'];state.posts.push({body,key});
 let result=state.receipts.get(key);
 if(!result){result={schema_version:'kakao-question-composition-result/1.0',operation:body.operation,source_binding_id:body.source_binding_id,room_id:body.room_id,inputs:[body.input],outputs:body.partitions.map((_,i)=>({...view.question,question_id:'kakaoquestion_'+String(i+3).repeat(32),question_revision_id:'kakaoquestionrev_'+String(i+3).repeat(32),resource_version:1}))};state.receipts.set(key,result);}
 if(state.lose){state.lose=false;throw Error('RESPONSE_LOST');}return result;
};
const controller=state.controller=createKakaoQuestionComposer({document,api,explainError:()=> '확인 필요',onSaved:async result=>{state.opened.push(result);return true;}});
controller.install(document.querySelector('#composer'));controller.setOwner('one');controller.setPermissions(['kakao_archive:read','kakao_archive:edit']);controller.setBinding({source_binding_id:view.question.source_binding_id,state:'DRAFT'});controller.open();controller.split(view);`;
const server = createServer((request,response) => {
 const name = request.url.slice(1);
 const body = name === 'fixture.js' ? fixture : name === '' ? '<html lang="ko"><head><meta charset="utf-8"><link rel="stylesheet" href="styles.css"><link rel="stylesheet" href="kakao-archive.css"></head><body><main style="max-width:900px;padding:16px"><section id="composer"></section></main><script type="module" src="fixture.js"></script></body></html>' : files.get(name);
 if(body===undefined){response.writeHead(404);response.end();return;}
 response.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html');response.end(body);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser=await chromium.launch({headless:true});
try {
 const page=await browser.newPage({viewport:{width:1100,height:950}}),errors=[],external=[];
 page.on('pageerror',error=>errors.push(error.message));page.on('request',request=>{if(!request.url().startsWith('http://127.0.0.1:'))external.push(request.url());});
 await page.goto(`http://127.0.0.1:${server.address().port}/`);
 await page.getByRole('button',{name:'문장 안에서 나누기',exact:true}).click();
 const area=page.getByLabel('1번째 내용에서 나눌 위치',{exact:true});await area.waitFor();
 assert.equal(await area.evaluate(node=>node.readOnly),true);
 assert.equal(await area.inputValue(),text.replace(/\r\n?/g,'\n'));
 for(const bad of [1,'😀가\nᄀ'.length]) {
  await area.evaluate((node,position)=>node.setSelectionRange(position,position),bad);
  await page.getByRole('button',{name:'여기서 나누기',exact:true}).click();
  await page.getByText('문장의 맨 앞·뒤나 글자 중간이 아닌 곳에 커서를 놓아 주세요.',{exact:true}).waitFor();
 }
 for(const prefix of ['😀가\n','😀가\n가']) {
  await area.evaluate((node,position)=>node.setSelectionRange(position,position),prefix.length);
  await page.getByRole('button',{name:'여기서 나누기',exact:true}).click();
 }
 await page.getByRole('button',{name:'새 질문으로 저장',exact:true}).click();
 await page.getByRole('button',{name:'같은 저장 요청 확인',exact:true}).waitFor();
 await page.getByRole('button',{name:'같은 저장 요청 확인',exact:true}).click();
 await page.waitForFunction(()=>fixture.opened.length===1);
 const saved=await page.evaluate(()=>fixture.posts);
 assert.equal(saved.length,2);assert.deepEqual(saved[0],saved[1]);
 assert.deepEqual(saved[0].body.partitions,[
  [{kind:'TEXT_SPAN',block_id:'text-1',start_codepoint:7,end_codepoint:11}],
  [{kind:'TEXT_SPAN',block_id:'text-1',start_codepoint:11,end_codepoint:13}],
  [{kind:'TEXT_SPAN',block_id:'text-1',start_codepoint:13,end_codepoint:16},{kind:'BLOCK',block_id:'picture-1'}]
 ]);
 assert.equal(JSON.stringify(saved[0].body).includes(text),false);
 assert.equal(await page.evaluate(()=>fixture.receipts.size),1);
 await page.evaluate(()=>{fixture.context.resource_version=2;fixture.controller.split(fixture.view);});
 await page.getByRole('button',{name:'문장 안에서 나누기',exact:true}).click();
 await page.getByText('질문 버전이 바뀌었습니다. 현재 질문을 다시 열어 주세요.',{exact:true}).waitFor();
 assert.equal(await page.locator('textarea').count(),0);
 await page.evaluate(()=>{fixture.context.resource_version=1;fixture.controller.split(fixture.view);fixture.hold=true;});
 await page.getByRole('button',{name:'문장 안에서 나누기',exact:true}).click();
 await page.waitForFunction(()=>fixture.release!==null);
 await page.evaluate(()=>{fixture.controller.setOwner('two');fixture.release();});
 await page.waitForTimeout(40);
 assert.equal(await page.locator('#composer').textContent(),'');
 await page.evaluate(()=>{fixture.controller.setOwner('one');fixture.controller.setPermissions(['kakao_archive:read','kakao_archive:edit']);fixture.controller.setBinding({source_binding_id:fixture.view.question.source_binding_id,state:'DRAFT'});fixture.controller.split(fixture.view);});
 await page.getByRole('button',{name:'문장 안에서 나누기',exact:true}).click();await area.waitFor();
 await page.setViewportSize({width:390,height:900});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
 assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
 console.log('KAKAO_TEXT_SPAN_BROWSER=PASS');
} finally {await browser.close();await new Promise(resolve=>server.close(resolve));}
