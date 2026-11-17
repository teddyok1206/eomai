import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {createServer} from "node:http";
import {createRequire} from "node:module";

const require = createRequire(import.meta.url);
const {chromium} = require(process.env.EOM_WEB_PLAYWRIGHT_MODULE);
const root = new URL("../../apps/web_gui/eom_web_gui/static/", import.meta.url);
const assets = new Map(await Promise.all(["styles.css", "kakao-archive.css", "kakao-study-editor.js"].map(async name => [name, await readFile(new URL(name, root), "utf8")])));
const program = `
import {createKakaoStudyEditor} from './kakao-study-editor.js';
const id = (prefix, n='1') => prefix+'_'+n.repeat(32);
const scope = {binding:id('kakaobinding'),packet:id('kakaopacket'),revision:id('kakaopacketrev'),student:id('kakaostudent'),studentName:'합성 학생',canEdit:true,canExport:true};
const fixture = window.fixture = {calls:[],saved:null,edits:null,keys:new Map(),failSave:true,held:false,release:null};
const copy = value => structuredClone(value);
const selection = {schema_version:'kakao-study-create/1.0',source_binding_id:scope.binding,packet_id:scope.packet,packet_revision_id:scope.revision,student_id:scope.student,title:'질문과 설명',questions:[{question_revision_id:id('kakaoquestionrev'),concept_task_id:null,blocks:[],notes:[]}]};
async function api(path, options={}) {
  fixture.calls.push({path,method:options.method||'GET',key:options.headers?.['Idempotency-Key'],body:copy(options.body)});
  const url = new URL(path,'http://fixture');
  if(url.pathname.endsWith('/study-selection')) {
    const result = copy(selection); result.student_id=url.pathname.split('/').at(-2);
    if(fixture.held){fixture.held=false;await new Promise(resolve=>fixture.release=resolve);}
    return result;
  }
  if(url.pathname==='/kakao-archive/studies' && !options.method) return {items:fixture.saved?[copy(fixture.saved)]:[],next_cursor:null};
  if(options.method && url.pathname.startsWith('/kakao-archive/studies')) {
    const key=options.headers['Idempotency-Key'];
    if(!fixture.keys.has(key)) {
      const body=options.body, version=fixture.saved?fixture.saved.resource_version+1:1;
      fixture.saved={schema_version:'kakao-stored-study/1.0',study_id:id('kakaostudy'),study_revision_id:id('kakaostudyrev',String(version)),previous_revision_id:fixture.saved?.study_revision_id||null,resource_version:version,
        source_binding_id:scope.binding,packet_id:scope.packet,packet_revision_id:scope.revision,student_id:body.student_id,title:body.title,question_count:1,manifest:{sha256:'sha256:'+'a'.repeat(64)}};
      fixture.edits=copy(body.questions);fixture.keys.set(key,copy(fixture.saved));
    }
    if(fixture.failSave){fixture.failSave=false;throw new Error('SYNTHETIC_RESPONSE_LOST_AFTER_SAVE');}
    return {study:copy(fixture.keys.get(key)),replayed:true};
  }
  if(url.pathname.includes('/studies/') && url.pathname.includes('/revisions/')) return {study:copy(fixture.saved),questions:copy(fixture.edits)};
  if(url.pathname==='/kakao-archive/study-exports') {
    fixture.exported={study:copy(options.body.study),export:{source_binding_id:scope.binding,packet_id:scope.packet,packet_revision_id:scope.revision,student_id:scope.student,export_id:id('kakaoexport'),export_revision_id:id('kakaoexportrev'),state:'COMPLETED'}};
    return {result:copy(fixture.exported),replayed:true};
  }
  if(url.pathname.includes('/study-exports/'))return copy(fixture.exported);
  throw new Error('Unexpected route: '+path);
}
const editor=createKakaoStudyEditor({document,api,explainError:()=> '합성 오류'});
fixture.editor=editor;fixture.scope=scope;fixture.open=()=>editor.open(document.querySelector('#editor'),scope);
await fixture.open();
`;
const server = createServer((req,res) => {
  const name=(req.url||'').split('/').pop().split('?')[0];
  const content=name==='fixture.js'?program:name===''?'<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><link rel="stylesheet" href="styles.css"><link rel="stylesheet" href="kakao-archive.css"><main class="kakao-archive" style="padding:24px"><section id="editor" class="kakao-study-editor"></section></main><script type="module" src="fixture.js"></script></html>':assets.get(name);
  if(content===undefined){res.writeHead(404);res.end();return;}
  res.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html');res.end(content);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser=await chromium.launch({headless:true,channel:process.env.EOM_WEB_PLAYWRIGHT_CHANNEL||undefined});
try {
  const page=await browser.newPage({viewport:{width:1280,height:1000}}),errors=[],external=[];
  page.on('pageerror',error=>errors.push(error.message));
  page.on('request',request=>{if(!request.url().startsWith('http://127.0.0.1:'))external.push(request.url());});
  await page.goto('http://127.0.0.1:'+server.address().port+'/');
  await page.getByRole('button',{name:'새 설명 자료 시작',exact:true}).click();
  await page.getByRole('button',{name:'직접 쓴 설명 추가',exact:true}).click();
  await page.getByLabel('설명 제목',{exact:true}).fill('관련 개념');
  const privateText='안전한 설명 <script>window.bad=true</script> · 다른 학생에게 노출 금지';
  await page.getByLabel('설명 내용',{exact:true}).fill(privateText);
  await page.getByRole('button',{name:'설명 자료 저장',exact:true}).click();
  await page.getByRole('button',{name:'같은 저장 요청 확인',exact:true}).waitFor();
  assert.equal(await page.getByLabel('설명 내용',{exact:true}).isDisabled(),true);
  await page.getByRole('button',{name:'같은 저장 요청 확인',exact:true}).click();
  await page.getByRole('button',{name:'설명 자료 저장',exact:true}).waitFor();
  const writes=await page.evaluate(()=>fixture.calls.filter(c=>c.method==='POST'));
  assert.equal(writes.length,2);assert.equal(writes[0].key,writes[1].key);assert.deepEqual(writes[0].body,writes[1].body);
  assert.equal(await page.evaluate(()=>fixture.keys.size),1);
  await page.getByLabel('설명 내용',{exact:true}).fill(privateText+' · 수정');
  assert.equal(await page.getByRole('button',{name:'저장한 설명으로 PDF 만들기',exact:true}).isDisabled(),true,'unsaved edits must not silently export the prior revision');
  await page.getByRole('button',{name:'설명 자료 저장',exact:true}).click();
  await page.getByRole('button',{name:/수정 1회 · 열기/}).waitFor();
  assert.equal(await page.evaluate(()=>fixture.calls.filter(c=>c.method==='PATCH').at(-1).body.expected_resource_version),1);
  await page.getByRole('button',{name:'저장한 설명으로 PDF 만들기',exact:true}).click();
  const download=page.getByRole('link',{name:'설명 자료 PDF 내려받기',exact:true});await download.waitFor();
  assert.match(await download.getAttribute('href'),/^\/studio\/api\/v1\/kakao-archive\/exports\/kakaoexport_[0-9a-f]{32}\/file\?/);
  await page.getByRole('button',{name:'PDF 상태 확인',exact:true}).click();
  assert.equal(await page.evaluate(()=>fixture.calls.filter(c=>c.path==='/kakao-archive/study-exports'&&c.method==='POST').length),1,'read must not enqueue a PDF');
  await page.evaluate(()=>fixture.open());
  await page.getByRole('button',{name:/수정 1회 · 열기/}).click();
  assert.equal(await page.getByLabel('설명 내용',{exact:true}).inputValue(),privateText+' · 수정');
  assert.equal(await page.evaluate(()=>window.bad),undefined);
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  // A delayed earlier student's response must not restore their private fields after switching.
  await page.evaluate(()=>{fixture.held=true;});
  await page.getByRole('button',{name:'새 설명 자료 시작',exact:true}).click();
  await page.waitForFunction(()=>fixture.release!==null);
  await page.evaluate(()=>fixture.editor.open(document.querySelector('#editor'),{...fixture.scope,student:'kakaostudent_'+'2'.repeat(32),studentName:'다른 학생'}));
  await page.evaluate(()=>fixture.release());
  assert.equal(await page.getByLabel('설명 내용',{exact:true}).count(),0);
  assert.equal(await page.getByRole('heading',{name:'다른 학생 · 개념·설명 자료'}).count(),1);
  await page.evaluate(()=>fixture.editor.clear());
  assert.equal(await page.locator('#editor').textContent(),'');
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  console.log('KAKAO_STUDY_EDITOR_BROWSER=PASS');
} finally {await browser.close();server.close();}
