"""No live accounts: OBSERVE, catalog presentation, retries and logout in Node."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def test_model_catalog_observation_reuses_owner_and_preserves_pending_identity(
    tmp_path: Path,
) -> None:
    source = (
        Path(__file__).parents[2] / "apps/web_gui/eom_web_gui/static/model-catalog-observation.js"
    )
    module = tmp_path / "observation.mjs"
    shutil.copyfile(source, module)
    script = r"""
import assert from 'node:assert/strict';
import {createModelCatalogObservation} from './observation.mjs';
const future = new Date(Date.now()+60000).toISOString();
const past = new Date(Date.now()-60000).toISOString();
const account = (id,purpose='GENERAL_WORK') => ({binding_id:id,slot_key:id,resource_version:3,
 assignment_purpose:purpose,model_catalog:{state:'OBSERVED',observed_at:past,valid_until:future,
 models:[{model:'discovered',hidden:false,supported_reasoning_efforts:['high','ultra']},
 {model:'secret-hidden',hidden:true,supported_reasoning_efforts:['high']}]}});
let accounts=[account('one'),account('two'),account('chat','GENERAL_CHAT')];
let admin=true,ackFailure=false,hold,release,state='SUCCEEDED',failSlot=null;
const calls=[];
const api=async(path,request={})=>{
 calls.push({path,...structuredClone(request)});
 if(path==='/admin/codex-accounts')return accounts;
 if(request.method==='POST'){
  if(hold){hold=false;await new Promise(resolve=>{release=resolve;});}
  if(ackFailure){ackFailure=false;throw new Error('HTTP_TIMEOUT');}
  return {command_id:path.split('/')[3]};
 }
 return {state:path.endsWith('/'+failSlot)?'FAILED':state,error_code:'SYNTHETIC_FAILURE'};
};
const view=createModelCatalogObservation({api,isAdmin:()=>admin,delay:async()=>{}});
let value=await view.load('WORKFLOW');
assert.deepEqual(value.models,[{model:'discovered',efforts:['high','ultra']}]);
assert.equal(calls.filter(v=>v.method).length,0);
await view.load('CHAT',{refresh:true});
assert.deepEqual(calls.filter(v=>v.method).map(v=>v.path),['/admin/codex-accounts/chat/commands']);
calls.length=0;
hold=true;
const first=view.observe(accounts[0]);
const second=view.observe(accounts[0]);
await Promise.resolve();release();await Promise.all([first,second]);
assert.equal(calls.filter(v=>v.method).length,1);

calls.length=0;ackFailure=true;
await assert.rejects(view.observe(accounts[0]),/HTTP_TIMEOUT/);
await view.observe(accounts[0]);
const posts=calls.filter(v=>v.method);
assert.equal(posts.length,2);
assert.deepEqual(posts[0].body,posts[1].body);
assert.equal(posts[0].body.command_type,'OBSERVE');

calls.length=0;state='RUNNING';
await assert.rejects(view.observe(accounts[0]),/같은 확인/);
state='SUCCEEDED';await view.observe(accounts[0]);
assert.equal(calls.filter(v=>v.method).length,1);

calls.length=0;failSlot='two';
value=await view.load('WORKFLOW',{refresh:true});
assert.equal(value.failures.length,1);
assert.match(value.failures[0],/two: SYNTHETIC_FAILURE/);
assert.equal(calls.filter(v=>v.method).length,2);
assert.ok(calls.every(v=>!v.method||v.body.command_type==='OBSERVE'));

calls.length=0;hold=true;
const older=view.load('CHAT',{refresh:true});
while(!calls.some(v=>v.method))await Promise.resolve();
view.reset();admin=false;release();
await assert.rejects(older,/로그인 상태/);
assert.equal(calls.filter(v=>v.path.includes('control-commands')).length,0);
await assert.rejects(view.load('CHAT'),/관리자 로그인/);

admin=true;accounts=[{...account('one'),model_catalog:{...account('one').model_catalog,valid_until:past}}];
assert.deepEqual((await view.load('WORKFLOW')).models,[]);
await assert.rejects(
 view.observe({...account('one'),active_auth_enrollment_id:'changing'}),/로그인 변경/);
console.log('PASS');
"""
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "PASS" in result.stdout
