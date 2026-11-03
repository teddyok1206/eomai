"""Evaluate the extra grant before the unchanged, existing blanket deny."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
UNIT = "eom-worker-analysis-03@job_" + "a" * 32 + ".service"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is unavailable")
@pytest.mark.parametrize(
    "user,unit,verb,expected",
    [
        ("eom-workflow-runner", UNIT, "start", "yes"),
        ("eom-workflow-runner", UNIT, "restart", "no"),
        ("eom-workflow-runner", UNIT, "stop", "no"),
        ("eom", UNIT, "start", "no"),
        ("eom-cdx-03", UNIT, "start", None),
        ("eom-api", UNIT, "start", None),
        ("eom-workflow-runner", UNIT + "\n", "start", "no"),
        ("eom-workflow-runner", UNIT.replace("job_", "job_/"), "start", "no"),
        ("eom-workflow-runner", UNIT.replace("03@", "05@"), "start", "no"),
        ("eom-workflow-runner", UNIT.replace("03@", "04@"), "start", "yes"),
    ],
)
def test_office_report_grant_is_exact_and_does_not_override_existing_denials(
    user, unit, verb, expected
):
    script = """
const fs = require('fs'); const rules = [];
global.polkit = {addRule: x => rules.push(x), Result: {YES:'yes', NO:'no', NOT_HANDLED:null}};
for (const file of process.argv.slice(1, 3)) eval(fs.readFileSync(file, 'utf8'));
const details = {unit:process.argv[4],verb:process.argv[5]};
const action = {id:'org.freedesktop.systemd1.manage-units', lookup:k=>details[k]};
let result=null;
for (const rule of rules) { result=rule(action,{user:process.argv[3]}); if(result!==null)break; }
process.stdout.write(JSON.stringify(result));
"""
    paths = [
        ROOT / "infra/polkit" / name
        for name in ("48-eom-native-office-report-worker.rules", "50-eom-worker-units.rules")
    ]
    result = subprocess.run(
        ["node", "-e", script, *map(str, paths), user, unit, verb],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(result.stdout) == expected
