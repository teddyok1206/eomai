"""Synthetic actual-browser checks, with no Kakao authentication or live collection."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("script", "marker"),
    [
        ("kakao_archive_browser_checks.mjs", "KAKAO_ARCHIVE_BROWSER=PASS"),
        ("kakao_archive_bootstrap_browser_checks.mjs", "KAKAO_ARCHIVE_BOOTSTRAP_BROWSER=PASS"),
        ("kakao_students_browser_checks.mjs", "KAKAO_STUDENTS_BROWSER=PASS"),
        ("kakao_rooms_browser_checks.mjs", "KAKAO_ROOMS_BROWSER=PASS"),
        ("kakao_room_collection_browser_checks.mjs", "KAKAO_ROOM_COLLECTION_BROWSER=PASS"),
        ("kakao_manual_browser_checks.mjs", "KAKAO_MANUAL_BROWSER=PASS"),
        ("kakao_captures_browser_checks.mjs", "KAKAO_CAPTURES_BROWSER=PASS"),
        ("kakao_question_composer_browser_checks.mjs", "KAKAO_QUESTION_COMPOSER_BROWSER=PASS"),
        ("kakao_text_span_browser_checks.mjs", "KAKAO_TEXT_SPAN_BROWSER=PASS"),
        ("kakao_candidates_browser_checks.mjs", "KAKAO_CANDIDATES_BROWSER=PASS"),
        ("kakao_study_editor_browser_checks.mjs", "KAKAO_STUDY_EDITOR_BROWSER=PASS"),
    ],
)
def test_kakao_archive_browser_owner_replay_pins_and_safe_dom(script: str, marker: str) -> None:
    if not os.environ.get("EOM_WEB_PLAYWRIGHT_MODULE"):
        pytest.skip("Opt-in check requires an existing local Playwright environment")
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the isolated Kakao archive browser check")
    result = subprocess.run(
        [node, str(Path(__file__).with_name(script))],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert marker in result.stdout


def test_kakao_shell_navigation_and_actual_session_lifecycle() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the actual Studio lifecycle checks")
    root = Path(__file__).resolve().parents[2]
    static = root / "apps/web_gui/eom_web_gui/static"
    html = (static / "index.html").read_text()
    general = html[html.index(">일반</p>") : html.index(">문항 제작</p>")]
    assert general.count('data-view-target="kakao-archive"') == 1
    assert "KakaoTalk" in general
    assert 'data-required-permission="kakao_archive:read" hidden' in general
    assert len(re.findall(r'id="kakao-archive-root"', html)) == 1
    program = r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[1],'utf8'),calls=[];
const initialize=source.slice(source.indexOf('async function initializeSession() {'),
 source.indexOf('\nasync function openStudioWorkbenchItem'));
const show=source.slice(source.indexOf('function showView('),
 source.indexOf('\nfunction installNavigation()'));
const logout=source.slice(source.indexOf('async function logout() {'),
 source.indexOf('\nasync function boot()'));
const operator={operator_id:'actual-owner',roles:['ADMIN'],
 effective_permissions:['kakao_archive:read','kakao_archive:collect'],password_change_required:false};
const component={setOwner(){},open(){},close(){},reset(){},stopPolling(){}};
const element={classList:{contains:()=>false,toggle(){}},setAttribute(){}};
const state={operator:null,navigationVersion:0,currentView:'dashboard'};
const context={state,api:async()=>({operator,csrf_token:'session-csrf'}),
  kakaoArchive:{setOwner:value=>calls.push(['owner',value]),setRoles:value=>calls.push(['roles',value]),setPermissions:value=>calls.push(['permissions',value]),open:()=>calls.push(['open']),close:()=>calls.push(['close'])},
  generalChat:component,itemDb:component,knowledgeMap:component,materialLearning:component,contentPlanning:component,presetEditor:component,chatModelEditor:component,modelCatalogObservation:component,
  $:()=>element,$$:()=>[],document:{},window:{clearTimeout(){},matchMedia:()=>({matches:true}),scrollTo(){},location:{replace:path=>calls.push(['redirect',path])}},
  UI_MODE_BY_VIEW:{dashboard:'human','kakao-archive':'human',chat:'human'},
  ADMIN_VIEW_NAMES:new Set(),
  hasPermission:(value,key)=>value?.effective_permissions?.includes(key),hasAdminRole:()=>true,
  restorePdfDocumentReviewUpload(){},roleLabel:value=>value,applyPermissionVisibility(){},syncDraftControls(){},renderOwnAccount(){},
  syncUiMode(){},closeMobileNavigation(){},stopHwpxBuildObservation(){},stopWorkflowUpdates(){},stopCustomerSupportPolling(){},stopPdfDocumentReviewPolling(){},loadStudioWorkbench(){}};
vm.createContext(context);vm.runInContext(initialize+'\n'+show+'\n'+logout+'\nthis.initialize=initializeSession;this.show=showView;this.logout=logout;',context);
(async()=>{
 await context.initialize();
 assert.deepEqual(calls.slice(0,3),[['owner','actual-owner'],['roles',operator.roles],['permissions',operator.effective_permissions]]);
 operator.effective_permissions=[];context.show('kakao-archive',{history:false});
 assert.equal(state.currentView,'dashboard');assert.equal(calls.filter(call=>call[0]==='open').length,0);
 operator.effective_permissions=['kakao_archive:read'];context.show('kakao-archive',{history:false});
 assert.equal(state.currentView,'kakao-archive');assert.equal(calls.filter(call=>call[0]==='open').length,1);
 context.show('chat',{history:false});assert.equal(calls.at(-1)[0],'close');
 await context.logout();assert.ok(calls.some(call=>call[0]==='owner'&&call[1]===null));
 assert.deepEqual(calls.at(-1),['redirect','/studio/login']);
 console.log('KAKAO_SHELL_LIFECYCLE=PASS');
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run(
        [node, "-e", program, str(static / "app.js")],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "KAKAO_SHELL_LIFECYCLE=PASS" in result.stdout
