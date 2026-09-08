from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIBRARY = ROOT / "scripts/api/workflow_runner_deployment_hold.sh"


def _systemctl(tmp_path: Path, output: str) -> Path:
    path = tmp_path / "systemctl"
    path.write_text(
        "#!/usr/bin/env bash\n"
        '[[ "$1" == show ]] || exit 91\n'
        '[[ "$2" == eom-workflow-runner.service ]] || exit 92\n'
        f"printf '%b' {output!r}\n",
        encoding="utf-8",
    )
    path.chmod(0o700)
    return path


def _check(function: str, fake: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (
            "/usr/bin/bash",
            "-c",
            'source "$1"; "$2" "$3" eom-workflow-runner.service',
            "hold-test",
            str(LIBRARY),
            function,
            str(fake),
        ),
        check=False,
        capture_output=True,
        text=True,
    )


def test_hold_helper_accepts_only_exact_stopped_and_runtime_masked_snapshots(
    tmp_path: Path,
) -> None:
    stopped = _systemctl(
        tmp_path,
        "ActiveState=inactive\nSubState=dead\nUnitFileState=enabled\nMainPID=0\n",
    )
    assert _check("workflow_runner_require_stopped", stopped).returncode == 0
    assert _check("workflow_runner_require_runtime_hold", stopped).returncode != 0

    held = _systemctl(
        tmp_path,
        "ActiveState=inactive\nSubState=dead\nUnitFileState=masked-runtime\nMainPID=0\n",
    )
    assert _check("workflow_runner_require_runtime_hold", held).returncode == 0


@pytest.mark.parametrize(
    "output",
    (
        "ActiveState=active\nSubState=running\nUnitFileState=masked-runtime\nMainPID=42\n",
        "ActiveState=activating\nSubState=start\nUnitFileState=masked-runtime\nMainPID=42\n",
        "ActiveState=deactivating\nSubState=stop-sigterm\nUnitFileState=masked-runtime\nMainPID=42\n",
        "ActiveState=failed\nSubState=failed\nUnitFileState=masked-runtime\nMainPID=0\n",
        "ActiveState=inactive\nSubState=dead\nUnitFileState=enabled\nMainPID=0\n",
        "ActiveState=inactive\nSubState=dead\nUnitFileState=masked-runtime\nMainPID=9\n",
        "ActiveState=inactive\nSubState=dead\nUnitFileState=masked-runtime\n",
        (
            "ActiveState=inactive\nActiveState=inactive\nSubState=dead\n"
            "UnitFileState=masked-runtime\nMainPID=0\n"
        ),
    ),
)
def test_hold_helper_rejects_live_transitional_failed_unmasked_or_malformed_state(
    tmp_path: Path,
    output: str,
) -> None:
    fake = _systemctl(tmp_path, output)

    result = _check("workflow_runner_require_runtime_hold", fake)

    assert result.returncode != 0
    assert result.stdout == ""
