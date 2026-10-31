"""Run the production binding and transport together, not an invented API stub."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_similarity_start_and_observe_include_csrf_and_single_json_encoding():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the production browser transport check")
    source = Path(__file__).resolve().parents[2] / "apps/web_gui/eom_web_gui/static/app.js"
    program = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[1], 'utf8');
const transport = source.slice(source.indexOf('async function api(path, options = {}) {'),
 source.indexOf('\nclass StudioApiError'));
const binding = source.slice(source.indexOf('searchSimilar: ')+14,
 source.indexOf('\n  canReadSource:')).trim().replace(/,$/, '');
const selection = {kind:'EXTERNAL_SOURCE', source_id:'extitem_a',
 source_revision_id:'extitemrev_a'};
const pinned = {request_id:'original-query', model_revision:'pinned'};
const calls=[];
const result={status:'PENDING',pinned_query:pinned};
const state={csrf:'current-session-token'};
const context={state, API:'/studio/api/v1', JSON, StudioApiError:class extends Error{},
 WEB_REQUEST_ID_PATTERN:/^webreq_[a-f0-9]{24}$/,
 fetch:async (path, request)=>{
   calls.push({path, request});
   assert.equal(request.method, 'POST');
   assert.equal(request.credentials, 'same-origin');
   assert.equal(request.headers['X-CSRF-Token'], state.csrf);
   assert.equal(request.headers['Content-Type'], 'application/json');
   assert.equal(request.headers['Idempotency-Key'], 'same-original-key');
   const value=JSON.parse(request.body);
   assert.equal(typeof value, 'object');
   assert.deepEqual(value.selection, selection);
   return {ok:true,status:200,json:async()=>result};
 }};
vm.createContext(context);
vm.runInContext(transport+'\nthis.searchSimilar='+binding+';',context);
(async()=>{
 assert.equal(await context.searchSimilar(selection,'same-original-key',null), result);
 assert.equal(JSON.parse(calls[0].request.body).pinned_query,null);
 state.csrf='updated-session-token';
 assert.equal(await context.searchSimilar(selection,'same-original-key',pinned), result);
 assert.deepEqual(JSON.parse(calls[1].request.body).pinned_query,pinned);
 assert.equal(calls.length,2);
 assert(calls.every(call=>call.path==='/studio/api/v1/item-db/similarity'));
 console.log('similarity_browser_transport=PASS');
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run(
        [node, "-e", program, str(source)], capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stderr
