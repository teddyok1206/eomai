"""Evaluate ordered rules together: the existing blanket deny must still apply."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

RULES = Path(__file__).resolve().parents[2] / "infra/polkit"
INSTANCE = "a" * 32
INDEX = f"eom-embedding-native-cpu-index@{INSTANCE}.service"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is unavailable")
@pytest.mark.parametrize(
    ("user", "action", "unit", "verb", "expected"),
    (
        ("eom-workflow-runner", "manage-units", INDEX, "start", "yes"),
        ("eom-workflow-runner", "manage-units", INDEX, "restart", "no"),
        ("eom-workflow-runner", "manage-units", INDEX, "stop", "no"),
        ("eom-workflow-runner", "manage-units", INDEX, "enable", "no"),
        ("eom-workflow-runner", "manage-units", INDEX, None, "no"),
        ("eom-workflow-runner", "manage-unit-files", INDEX, "start", None),
        ("eom-workflow-runner", "manage-units", INDEX.replace(INSTANCE, "invalid"), "start", "no"),
        (
            "eom-workflow-runner",
            "manage-units",
            INDEX.replace(INSTANCE, INSTANCE.upper()),
            "start",
            "no",
        ),
        (
            "eom-workflow-runner",
            "manage-units",
            INDEX.replace("cpu-index", "index-prepare"),
            "start",
            "no",
        ),
        (
            "eom-workflow-runner",
            "manage-units",
            INDEX.replace("cpu-index", "cpu-query"),
            "start",
            "no",
        ),
        ("eom-workflow-runner", "manage-units", "unrelated.service", "start", "no"),
        ("eom", "manage-units", INDEX, "start", "no"),
        ("eom-api", "manage-units", INDEX, "start", "no"),
        ("eom-embedding-index-cpu", "manage-units", INDEX, "start", "no"),
        ("eom-catalog-manager", "manage-units", INDEX, "start", "no"),
        ("eom-hwpx-manager", "manage-units", INDEX, "start", "no"),
        (
            "eom-workflow-runner",
            "manage-units",
            f"eom-worker-01@job_{INSTANCE}.service",
            "start",
            "yes",
        ),
        (
            "eom-workflow-runner",
            "manage-units",
            f"eom-worker-01@job_{INSTANCE}.service",
            "restart",
            "no",
        ),
    ),
)
def test_composed_start_exception_preserves_existing_deny(
    user: str, action: str, unit: str, verb: str | None, expected: str | None
) -> None:
    script = """
const fs = require('fs');
const callbacks = [];
global.polkit = {
  addRule: value => callbacks.push(value),
  Result: { YES: 'yes', NO: 'no', NOT_HANDLED: undefined }
};
for (const name of fs.readdirSync(process.argv[1]).filter(n => n.endsWith('.rules')).sort()) {
  eval(fs.readFileSync(process.argv[1] + '/' + name, 'utf8'));
}
const details = { unit: process.argv[4] };
if (process.argv[5] !== '__NONE__') details.verb = process.argv[5];
let result = null;
for (const callback of callbacks) {
  const decision = callback(
    {id: 'org.freedesktop.systemd1.' + process.argv[3], lookup: key => details[key]},
    {user: process.argv[2]}
  );
  if (decision !== undefined && decision !== null) { result = decision; break; }
}
process.stdout.write(JSON.stringify(result));
"""
    checked = subprocess.run(
        ("node", "-e", script, str(RULES), user, action, unit, verb or "__NONE__"),
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert json.loads(checked.stdout) == expected


def test_native_exception_is_before_blanket_deny_and_contains_no_mutation_grants() -> None:
    name = "49-eom-native-index.rules"
    assert name < "50-eom-worker-units.rules"
    assert not (RULES / "51-eom-native-index.rules").exists()
    source = (RULES / name).read_text()
    assert "polkit.spawn" not in source
    assert "_KEEP" not in source
    assert "manage-unit-files" not in source
    assert 'action.lookup("verb") === "start"' in source
