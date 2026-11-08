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
const start = source.indexOf('similaritySearches: ')+'similaritySearches: '.length;
const end = source.indexOf('\n  },', start);
assert.ok(start > 0 && end > start, 'production binding must have a bounded source slice');
const binding = source.slice(start, end + '\n  }'.length).trim();
const selection = {kind:'EXTERNAL_SOURCE', source_id:'extitem_a',
 source_revision_id:'extitemrev_a'};
const calls=[];
const result={status:'PENDING',search_id:'dbsearch_original'};
const state={csrf:'current-session-token'};
const context={state, API:'/studio/api/v1', JSON, StudioApiError:class extends Error{},
 WEB_REQUEST_ID_PATTERN:/^webreq_[a-f0-9]{24}$/,
 fetch:async (path, request)=>{
   calls.push({path, request});
   assert.equal(request.credentials, 'same-origin');
   if (request.method === 'POST') assert.equal(request.headers['X-CSRF-Token'], state.csrf);
   if (request.body) {
     assert.equal(request.headers['Content-Type'], 'application/json');
     assert.equal(request.headers['Idempotency-Key'], 'same-original-key');
     const value=JSON.parse(request.body);
     assert.deepEqual(value.selections, [selection]);
     assert.equal(value.top_k,10);
   }
   return {ok:true,status:200,json:async()=>result};
 }};
vm.createContext(context);
vm.runInContext(transport+'\nthis.searches='+binding+';',context);
(async()=>{
 assert.equal(await context.searches.submit([selection],10,'same-original-key'), result);
 state.csrf='updated-session-token';
 assert.equal(await context.searches.check('dbsearch_original'),result);
 assert.equal(await context.searches.result('dbsearch_original',0),result);
 assert.equal(await context.searches.result('dbsearch_original',0),result);
 assert.equal(calls.length,4);
 assert.equal(calls[0].path,'/studio/api/v1/item-db/similarity/searches');
 assert.equal(calls[1].request.method,'POST');
 assert(calls.slice(2).every(call=>call.request.method==='GET'
   && !call.request.headers['Idempotency-Key']));
 console.log('similarity_browser_transport=PASS');
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run(
        [node, "-e", program, str(source)], capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stderr


def test_preparing_progress_and_failed_observation_preserve_original_query_pin():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the production presentation check")
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            node,
            "--experimental-default-type=module",
            str(root / "tests/web_gui/item_db_similarity_progress_checks.mjs"),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "similarity_preparing_original_pin_and_timeout_replay=PASS" in result.stdout


def test_relogin_preserves_same_request_without_credentials_or_automatic_execution():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the production presentation check")
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            node,
            "--experimental-default-type=module",
            str(root / "tests/web_gui/item_db_similarity_continuation_checks.mjs"),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "similarity_same_owner_relogin_original_request_continuation=PASS" in result.stdout
    source = (root / "apps/web_gui/eom_web_gui/static/app.js").read_text()
    assert "itemDb.setOwner(session.operator.operator_id)" in source
    logout = source[source.index("async function logout()") : source.index("async function boot()")]
    assert "itemDb.setOwner(null)" in logout


def test_list_history_preview_selection_and_completed_confirmation_have_no_recompute():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the production presentation check")
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            node,
            "--experimental-default-type=module",
            str(root / "tests/web_gui/item_db_similarity_list_checks.mjs"),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "item_db_list_history_result_reads=PASS" in result.stdout
