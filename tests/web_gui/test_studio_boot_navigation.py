"""The actual boot function must not overwrite newer navigation after async reads."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_late_boot_preserves_navigation_and_rechecks_admin_boundary():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for browser entrypoint checks")
    script = Path(__file__).resolve().parents[2] / "apps/web_gui/eom_web_gui/static/app.js"
    program = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[1], 'utf8');
const boot = source.slice(source.indexOf('async function boot() {'),
  source.indexOf('\nboot().catch'));
async function check(navigate, admin, expected) {
  let release, reached, restored = 0, fallback = 0;
  const pending = new Promise(r => {release = r;});
  const started = new Promise(r => {reached = r;});
  const state = {navigationVersion:0, operator:{password_change_required:false},
    currentView:'dashboard'};
  const context = {state, document:{}, window:{location:{}}, generalChat:{install(){}},
    studioRouteFromLocation:()=>({view:'chat'}), syncUiMode(){},
    loadPresentationVocabulary:async()=>{}, initializeSession:async()=>{},
    loadCurriculumOutline:async()=>{reached(); await pending;},
    loadHealth:async()=>{}, loadHwpx:async()=>{}, loadRecentHwpxBuilds:async()=>{},
    loadRecentItems:async()=>{}, restoreStudioRoute:async()=>{restored++;},
    ADMIN_VIEW_NAMES:new Set(['admin-settings']), hasAdminRole:()=>admin,
    showView:()=>{fallback++;}, showMessage(){}, logout(){}, loadStudioWorkbench(){},
    $:()=>({addEventListener(){}})};
  for (const name of boot.match(/install[A-Za-z]+(?=\()/g)) context[name]=()=>{};
  vm.createContext(context); vm.runInContext(boot+'\nthis.executeBoot=boot;', context);
  const running = context.executeBoot(); await started;
  if (navigate) {state.navigationVersion++; state.currentView=navigate;}
  release(); await running;
  assert.deepEqual([restored,fallback], expected);
}
(async()=>{
 await check(null,true,[1,0]);
 await check('chat',true,[0,0]);
 await check('admin-settings',false,[0,1]);
 console.log('late_boot_navigation=PASS');
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    result = subprocess.run(
        [node, "-e", program, str(script)], capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stderr
