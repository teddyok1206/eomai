import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {mkdir} from "node:fs/promises";
import {createRequire} from "node:module";

const require = createRequire(import.meta.url);
const {chromium} = require(process.env.EOM_WEB_PLAYWRIGHT_MODULE);
const root = new URL("../../apps/web_gui/eom_web_gui/static/", import.meta.url);
const names = ["index.html", "styles.css", "knowledge-map.css", "content-planning.css", "chat-model-settings.js", "eom-mark.svg"];
const assets = new Map(await Promise.all(names.map(async name => [name, await readFile(new URL(name, root), "utf8")])));
const app = `
import {createChatModelSettingsEditor} from './chat-model-settings.js';
const fixture=window.chatModelFixture={admin:true,calls:[],saves:0,fail:false,hold:null,release:null,held:false};
const state={current:{model:'model-a',reasoning_effort:'medium'},revision_id:'chatmodelrev_'+'a'.repeat(32),
 sha256:'sha256:'+'b'.repeat(64),resource_version:2,applies_to:'NEXT_TURN',dedicated_slot:'06',
 candidates:[{model:'model-a',reasoning_effort:'medium'},{model:'model-a',reasoning_effort:'high'},{model:'model-b',reasoning_effort:'high'}]};
const saved=new Map();
async function api(path,options={}) {
 fixture.calls.push({path,...structuredClone(options)});
 const method=options.method||'GET';
 if(fixture.hold===method){fixture.hold=null;fixture.held=true;await new Promise(resolve=>fixture.release=()=>{fixture.held=false;resolve();});}
 if(method==='GET') return structuredClone(state);
 const key=options.body.idempotency_key;
 if(!saved.has(key)) {fixture.saves++;state.resource_version++;state.current={model:options.body.model,reasoning_effort:options.body.reasoning_effort};
  saved.set(key,{status:'COMPLETED',resource_id:'chatmodelrev_'+'c'.repeat(32),resource_version:state.resource_version});}
 if(fixture.fail){fixture.fail=false;throw new Error('SYNTHETIC_TIMEOUT');}
 return structuredClone(saved.get(key));
}
const controller=createChatModelSettingsEditor({document,api,isAdmin:()=>fixture.admin,showMessage:(node,text)=>node.textContent=text});
controller.install(); fixture.controller=controller;fixture.state=state;
document.querySelectorAll('.view').forEach(n=>n.classList.toggle('active',n.dataset.view==='admin-settings'));
document.querySelector('#advanced-preset-policy').open=true;
await controller.refresh();fixture.ready=true;
`;
const browser = await chromium.launch({headless:true, timeout:10000});
try {
  const page = await browser.newPage({viewport:{width:1440,height:1000}});
  page.setDefaultTimeout(5000);
  const errors=[];
  page.on("pageerror", error=>errors.push(error.message));
  await page.route("**/*", route=>{
    const url=new URL(route.request().url());
    if(url.origin!=="https://chat-settings.invalid")return route.abort();
    if(url.pathname==="/studio")return route.fulfill({contentType:"text/html",body:assets.get("index.html")});
    const name=url.pathname.split("/").at(-1);
    if(name==="app.js")return route.fulfill({contentType:"text/javascript",body:app});
    if(!assets.has(name))return route.abort();
    return route.fulfill({body:assets.get(name),contentType:name.endsWith(".js")?"text/javascript":name.endsWith(".css")?"text/css":"image/svg+xml"});
  });
  await page.goto("https://chat-settings.invalid/studio");
  await page.waitForFunction(()=>window.chatModelFixture?.ready);
  assert.match(await page.locator("#chat-model-current").innerText(),/model-a/);
  assert.equal(await page.locator("#preset-base-revision").isVisible(),false);
  assert.equal(await page.locator("#preset-capacity-revision").isVisible(),false);
  await page.locator("#chat-model-select").focus();
  assert.equal(await page.locator("#chat-model-select").evaluate(node=>node===document.activeElement),true);
  if(process.env.EOM_SETTINGS_SCREENSHOT_DIR){
    await mkdir(process.env.EOM_SETTINGS_SCREENSHOT_DIR,{recursive:true});
    await page.locator("#advanced-preset-policy").screenshot({path:process.env.EOM_SETTINGS_SCREENSHOT_DIR+'/desktop.png'});
  }
  await page.locator("#chat-model-select").selectOption("model-b");
  await page.locator("#chat-model-save").click();
  await page.waitForFunction(()=>document.querySelector("#chat-model-message").textContent.includes("저장했습니다"));
  assert.equal(await page.evaluate(()=>window.chatModelFixture.saves),1);
  await page.locator("#chat-model-select").selectOption("model-a");
  await page.evaluate(()=>{window.chatModelFixture.fail=true;});
  await page.locator("#chat-model-save").click();
  await page.waitForFunction(()=>document.querySelector("#chat-model-message").textContent.includes("SYNTHETIC_TIMEOUT"));
  await page.locator("#chat-model-save").click();
  await page.waitForFunction(()=>document.querySelector("#chat-model-message").textContent.includes("저장했습니다"));
  const posts=await page.evaluate(()=>window.chatModelFixture.calls.filter(v=>v.method==='POST'));
  assert.equal(posts[1].body.idempotency_key,posts[2].body.idempotency_key);
  assert.equal(await page.evaluate(()=>window.chatModelFixture.saves),2);
  await page.evaluate(()=>{window.chatModelFixture.hold='POST';});
  await page.locator("#chat-model-select").selectOption("model-b");
  await page.locator("#chat-model-save").click();
  await page.waitForFunction(()=>window.chatModelFixture.held);
  await page.locator("#chat-model-save").evaluate(node=>node.click());
  assert.equal(await page.evaluate(()=>window.chatModelFixture.calls.filter(v=>v.method==='POST').length),4);
  await page.evaluate(()=>window.chatModelFixture.release());
  await page.waitForFunction(()=>!document.querySelector("#chat-model-save").disabled);
  await page.evaluate(()=>{window.chatModelFixture.hold='GET';});
  await page.locator("#chat-model-refresh").click();
  await page.waitForFunction(()=>window.chatModelFixture.held);
  await page.evaluate(()=>{window.chatModelFixture.admin=false;window.chatModelFixture.controller.reset();window.chatModelFixture.release();});
  await page.waitForTimeout(30);
  assert.equal(await page.locator("#chat-model-save").isDisabled(),true);
  assert.equal(await page.locator("#chat-model-current").innerText(),"설정 확인 전");
  for(const width of [390,320]){
    await page.setViewportSize({width,height:900});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true);
    if(process.env.EOM_SETTINGS_SCREENSHOT_DIR) await page.locator("#advanced-preset-policy").screenshot({path:process.env.EOM_SETTINGS_SCREENSHOT_DIR+'/'+width+'.png'});
  }
  assert.deepEqual(errors,[]);
  console.log("chat_model_settings_browser=PASS model_calls=0 live_writes=0");
} finally {await browser.close();}
