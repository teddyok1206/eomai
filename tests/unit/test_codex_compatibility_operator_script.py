"""Exercise only substituted temporary commands, never a runtime unit or root operation."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/workflow/run_codex_compatibility.sh"
COMMIT = "a" * 40
UNITS = (
    "eom-general-chat.service",
    "eom-general-chat-worker.service",
    "eom-workflow-maintenance.service",
    "eom-workflow-runner.service",
    "eom-codex-auth-broker.service",
)


def _isolated_script(
    tmp_path: Path,
    *,
    preflight_failure: bool = False,
    verify_failure: bool = False,
    stop_failure: bool = False,
    restoration_failure: bool = False,
    verify_signal: bool = False,
    source_drift: bool = False,
    inactive: str | None = None,
    runner_primary_group: str = "eom",
) -> tuple[Path, Path, Path]:
    events = tmp_path / "events.jsonl"
    configuration = tmp_path / "commands.json"
    configuration.write_text(
        json.dumps(
            {
                "events": str(events),
                "preflight_failure": preflight_failure,
                "verify_failure": verify_failure,
                "stop_failure": stop_failure,
                "restoration_failure": restoration_failure,
                "verify_signal": verify_signal,
                "source_drift": source_drift,
                "inactive": inactive,
                "runner_primary_group": runner_primary_group,
            }
        )
    )
    command_source = f"""#!/srv/eom/conda/envs/eom-api/bin/python
import json
import sys
from pathlib import Path
c = json.loads(Path({str(configuration)!r}).read_text())
name, args = Path(sys.argv[0]).name, sys.argv[1:]
def record(value):
    with Path(c["events"]).open("a") as stream:
        stream.write(json.dumps(value) + "\\n")
if name == "git-stub":
    if "rev-parse" in args:
        print({COMMIT!r})
elif name == "python-stub":
    print("b" * 40 if c["source_drift"] and Path(c["events"]).exists() else {COMMIT!r})
elif name == "id-stub":
    assert args == ["-gn", "eom-workflow-runner"]
    print(c["runner_primary_group"])
elif name == "stat-stub":
    if args[1] == "%U:%G:%a:%h":
        print("eom-workflow-runner:eom:600:1")
    elif Path(args[-1]).name == "policy":
        print("root:root:644")
    else:
        print("root:eom:640")
elif name == "systemctl-stub":
    if args[0] == "show":
        print("inactive" if args[-1] == c["inactive"] else "active")
    else:
        record([args[0], args[-1]])
        if c["stop_failure"] and args[0] == "stop" and args[-1].endswith("worker.service"):
            sys.exit(7)
elif name == "runuser-stub":
    assert args[:3] == ["-u", "eom-workflow-runner", "--"]
    command = next(
        value for value in ("maintenance-preflight", "restoration-preflight", "verify")
        if value in args
    )
    record([command])
    if command == "verify" and c["verify_signal"]:
        import os
        import signal
        os.kill(os.getppid(), signal.SIGTERM)
    if (command == "maintenance-preflight" and c["preflight_failure"]) or (
        command == "verify" and c["verify_failure"]
    ) or (
        command == "restoration-preflight" and c["restoration_failure"]
    ):
        sys.exit(9)
else:
    raise AssertionError("unexpected temporary command")
"""
    paths: dict[str, Path] = {}
    for name in ("git", "python", "id", "stat", "systemctl", "runuser"):
        path = tmp_path / f"{name}-stub"
        path.write_text(command_source)
        path.chmod(0o700)
        paths[name] = path
    for name in ("postgres", "worker", "policy"):
        (tmp_path / name).write_text("synthetic; no runtime secret")
    request = tmp_path / "request.json"
    request.write_text("synthetic; stub application does not execute")
    request.chmod(0o600)
    source = SCRIPT.read_text()
    assert "[[ ${EUID} -eq 0 ]]" in source
    source = source.replace("[[ ${EUID} -eq 0 ]]", "[[ 0 -eq 0 ]]")
    substitutions = {
        "PYTHON=/srv/eom/conda/envs/eom-api/bin/python": f"PYTHON={paths['python']}",
        "RUNUSER=/usr/sbin/runuser": f"RUNUSER={paths['runuser']}",
        "SYSTEMCTL=/usr/bin/systemctl": f"SYSTEMCTL={paths['systemctl']}",
        "POSTGRES_ENV=/etc/eom/secrets/postgres.env": f"POSTGRES_ENV={tmp_path / 'postgres'}",
        "WORKER_CONFIG=/etc/eom/worker-slots.yaml": f"WORKER_CONFIG={tmp_path / 'worker'}",
        "CAPABILITY_POLICY=/etc/eom/codex-capabilities.yaml": (
            f"CAPABILITY_POLICY={tmp_path / 'policy'}"
        ),
        "git -C": f"{paths['git']} -C",
        "/usr/bin/id -gn": f"{paths['id']} -gn",
        "$(stat -c": f"$({paths['stat']} -c",
    }
    for original, replacement in substitutions.items():
        assert original in source
        source = source.replace(original, replacement)
    isolated = tmp_path / "operator.sh"
    isolated.write_text(source)
    return isolated, request, events


def _events(path: Path) -> list[list[str]]:
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_original_wrapper_has_fixed_source_identity_and_no_automatic_install() -> None:
    source = SCRIPT.read_text()
    assert "get_build_info().source_commit" in source
    assert "git -C" in source and "status --porcelain=v1" in source
    assert "runuser" in source and "/usr/bin/env -i" in source
    assert '"${RUNUSER}" -u eom-workflow-runner --' in source
    assert '"${RUNUSER}" -u eom-workflow-runner -g' not in source
    assert "/usr/bin/id -gn eom-workflow-runner" in source
    assert '"${PYTHON}" -I -m eomctl.cli control-plane codex-runtime' in source
    assert source.index("run_installed maintenance-preflight") < source.index("WINDOW_STARTED=1")
    assert "trap restore_units EXIT" in source
    assert "trap 'exit 130' INT" in source
    assert "trap 'exit 143' TERM" in source
    assert source.index("run_installed restoration-preflight") < source.index(
        '"${SYSTEMCTL}" start'
    )
    assert "\nsource " not in source and "\n. " not in source
    assert "npm " not in source and "codex update" not in source
    assert "enable " not in source and "disable " not in source
    assert "reset-failed" not in source and "UPDATE " not in source and "DELETE " not in source
    result = subprocess.run(["/bin/bash", "-n", str(SCRIPT)], capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


def test_preflight_failure_does_not_stop_or_start_any_unit(tmp_path: Path) -> None:
    script, request, events = _isolated_script(tmp_path, preflight_failure=True)
    result = subprocess.run(
        ["/bin/bash", str(script), COMMIT, str(request)], capture_output=True, check=False
    )
    assert result.returncode == 1
    assert _events(events) == [["maintenance-preflight"]]


def test_changed_runner_primary_group_refuses_before_application_or_service_changes(
    tmp_path: Path,
) -> None:
    script, request, events = _isolated_script(tmp_path, runner_primary_group="unexpected")
    result = subprocess.run(
        ["/bin/bash", str(script), COMMIT, str(request)], capture_output=True, check=False
    )
    assert result.returncode == 1
    assert _events(events) == []
    assert b"runner primary group differs" in result.stderr


@pytest.mark.parametrize("failure", [None, "verify", "stop"])
def test_success_and_failures_restore_only_previously_active_units_in_dependency_order(
    failure: str | None, tmp_path: Path
) -> None:
    inactive = "eom-workflow-maintenance.service"
    script, request, events = _isolated_script(
        tmp_path,
        verify_failure=failure == "verify",
        stop_failure=failure == "stop",
        inactive=inactive,
    )
    result = subprocess.run(
        ["/bin/bash", str(script), COMMIT, str(request)], capture_output=True, check=False
    )
    assert result.returncode == ({None: 0, "verify": 9, "stop": 7}[failure]), result.stderr
    observed = _events(events)
    assert observed[0] == ["maintenance-preflight"]
    stopped = [event[1] for event in observed if event[0] == "stop"]
    assert stopped == list(UNITS[:2] if failure == "stop" else UNITS)
    if failure == "stop":
        assert ["verify"] not in observed
    else:
        assert ["verify"] in observed
    assert ["restoration-preflight"] in observed
    started = [event[1] for event in observed if event[0] == "start"]
    assert started == [
        "eom-codex-auth-broker.service",
        "eom-workflow-runner.service",
        "eom-general-chat-worker.service",
        "eom-general-chat.service",
    ]
    assert inactive not in started


def test_inconsistent_chat_wants_state_refuses_before_any_stop(tmp_path: Path) -> None:
    script, request, events = _isolated_script(tmp_path, inactive="eom-general-chat-worker.service")
    result = subprocess.run(
        ["/bin/bash", str(script), COMMIT, str(request)], capture_output=True, check=False
    )
    assert result.returncode == 1
    assert _events(events) == [["maintenance-preflight"]]


@pytest.mark.parametrize("verify_failure", [False, True])
def test_busy_or_unconfirmed_worker_leaves_all_producers_stopped(
    verify_failure: bool, tmp_path: Path
) -> None:
    script, request, events = _isolated_script(
        tmp_path, verify_failure=verify_failure, restoration_failure=True
    )
    result = subprocess.run(
        ["/bin/bash", str(script), COMMIT, str(request)], capture_output=True, check=False
    )
    assert result.returncode == 1
    observed = _events(events)
    assert ["verify"] in observed
    assert observed[-1] == ["restoration-preflight"]
    assert all(event[0] != "start" for event in observed)
    assert b"CODEX_COMPATIBILITY_RESTORATION_UNCONFIRMED" in result.stderr


def test_interrupted_owner_with_surviving_worker_never_restores_producers(tmp_path: Path) -> None:
    script, request, events = _isolated_script(
        tmp_path, verify_signal=True, restoration_failure=True
    )
    result = subprocess.run(
        ["/bin/bash", str(script), COMMIT, str(request)],
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 1
    observed = _events(events)
    assert ["verify"] in observed
    assert observed[-1] == ["restoration-preflight"]
    assert all(event[0] != "start" for event in observed)


def test_changed_installed_source_blocks_every_restore_before_worker_preflight(
    tmp_path: Path,
) -> None:
    script, request, events = _isolated_script(tmp_path, source_drift=True)
    result = subprocess.run(
        ["/bin/bash", str(script), COMMIT, str(request)], capture_output=True, check=False
    )
    assert result.returncode == 1
    observed = _events(events)
    assert observed[-1] == ["verify"]
    assert all(event[0] != "start" for event in observed)
    assert b"CODEX_COMPATIBILITY_RESTORATION_UNCONFIRMED" in result.stderr
