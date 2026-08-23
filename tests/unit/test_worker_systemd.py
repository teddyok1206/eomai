from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest
from eom_orchestrator.errors import PlatformError
from eom_orchestrator.worker_exec import codex_command, expected_workspace, validate_job_id
from eom_orchestrator.worker_registry import WorkerSlot
from eom_orchestrator.worker_systemd import (
    PROBE_TEMPLATE_SHA256,
    WORKER_EXECUTABLE_SHA256,
    WORKER_TEMPLATE_SHA256,
    FixedUnitRun,
    FixedUnitStatus,
    launch_worker_unit,
    parse_unit_status,
    probe_unit_name,
    probe_worker_systemd_authorization,
    systemctl_is_active_argv,
    systemctl_show_argv,
    systemctl_start_argv,
    worker_unit_name,
)
from eom_protocol import ErrorCode

ROOT = Path(__file__).resolve().parents[2]
JOB_ID = "job_0123456789abcdef0123456789abcdef"
PROBE_UNIT = "eom-worker-probe-01@probe_0123456789abcdef0123456789abcdef.service"


def _slot(index: int = 1) -> WorkerSlot:
    slot_id = f"{index:02d}"
    return WorkerSlot(
        slot_id=slot_id,
        linux_user=f"eom-cdx-{slot_id}",
        role="authoring",
        enabled=True,
    )


def _status(
    *,
    result: str = "success",
    main_code: int = 1,
    main_status: int = 0,
    active_state: str = "inactive",
    started: int = 100,
) -> FixedUnitStatus:
    return FixedUnitStatus(
        load_state="loaded",
        active_state=active_state,
        sub_state="dead",
        result=result,
        exec_main_code=main_code,
        exec_main_status=main_status,
        exec_main_started_monotonic=started,
        need_daemon_reload=False,
    )


def test_fixed_unit_name_accepts_only_canonical_job_identity() -> None:
    assert worker_unit_name(_slot(), JOB_ID) == f"eom-worker-01@{JOB_ID}.service"
    assert probe_unit_name(_slot(), "probe_0123456789abcdef0123456789abcdef") == (
        "eom-worker-probe-01@probe_0123456789abcdef0123456789abcdef.service"
    )
    for invalid in (
        "job_test",
        "../job_0123456789abcdef0123456789abcdef",
        "job_0123456789abcdef0123456789abcdef.service",
        "job_0123456789abcdef0123456789abcde;",
        "job_0123456789abcdef0123456789abcdef ",
    ):
        with pytest.raises(ValueError):
            worker_unit_name(_slot(), invalid)


@pytest.mark.skipif(shutil.which("systemd-escape") is None, reason="systemd-escape unavailable")
def test_canonical_job_id_has_stable_systemd_instance_escaping() -> None:
    completed = subprocess.run(
        ["systemd-escape", "--template=eom-worker-01@.service", JOB_ID],
        capture_output=True,
        check=True,
        text=True,
    )
    assert completed.stdout.strip() == f"eom-worker-01@{JOB_ID}.service"


def test_systemctl_command_cannot_select_identity_command_or_properties() -> None:
    argv = systemctl_start_argv(worker_unit_name(_slot(), JOB_ID))
    assert argv == (
        "/usr/bin/systemctl",
        "--no-ask-password",
        "--wait",
        "start",
        f"eom-worker-01@{JOB_ID}.service",
    )
    command = " ".join(argv)
    assert "systemd-run" not in command
    assert "--uid" not in command
    assert "--gid" not in command
    assert "--property" not in command


def test_unit_status_parsing_and_exit_mapping() -> None:
    status = parse_unit_status(
        "LoadState=loaded\n"
        "ActiveState=failed\n"
        "SubState=failed\n"
        "Result=exit-code\n"
        "ExecMainCode=1\n"
        "ExecMainStatus=74\n"
        "ExecMainStartTimestampMonotonic=123\n"
        "NeedDaemonReload=no\n"
    )
    assert status.process_started
    assert not status.process_lingering
    assert status.exit_code == 74


def test_launcher_preserves_worker_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    unit = worker_unit_name(_slot(), JOB_ID)
    monkeypatch.setattr(
        "eom_orchestrator.worker_systemd._start_unit",
        lambda *_args, **_kwargs: FixedUnitRun(
            unit, 1, b"", b"", _status(result="exit-code", main_status=1), 3
        ),
    )

    run = launch_worker_unit(_slot(), JOB_ID, timeout_seconds=600)

    assert run.exit_code == 1


def test_launcher_distinguishes_unit_start_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    unit = worker_unit_name(_slot(), JOB_ID)
    monkeypatch.setattr(
        "eom_orchestrator.worker_systemd._start_unit",
        lambda *_args, **_kwargs: FixedUnitRun(
            unit,
            1,
            b"",
            b"Interactive authentication required.",
            _status(main_code=0, started=0),
            4,
        ),
    )

    with pytest.raises(PlatformError) as captured:
        launch_worker_unit(_slot(), JOB_ID, timeout_seconds=600)

    assert captured.value.code is ErrorCode.WORKER_UNAVAILABLE


def test_launcher_distinguishes_systemd_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    unit = worker_unit_name(_slot(), JOB_ID)
    monkeypatch.setattr(
        "eom_orchestrator.worker_systemd._start_unit",
        lambda *_args, **_kwargs: FixedUnitRun(
            unit, 1, b"", b"", _status(result="timeout", main_status=15), 3
        ),
    )

    with pytest.raises(PlatformError) as captured:
        launch_worker_unit(_slot(), JOB_ID, timeout_seconds=600)

    assert captured.value.code is ErrorCode.WORKER_TIMEOUT


def test_launcher_accepts_success_with_retained_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    unit = worker_unit_name(_slot(), JOB_ID)
    monkeypatch.setattr(
        "eom_orchestrator.worker_systemd._start_unit",
        lambda *_args, **_kwargs: FixedUnitRun(unit, 0, b"", b"", _status(), 3),
    )

    run = launch_worker_unit(_slot(), JOB_ID, timeout_seconds=600)

    assert run.exit_code == 0
    assert run.status is not None and run.status.process_started


def test_launcher_accepts_success_with_collected_reset_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unit = worker_unit_name(_slot(), JOB_ID)
    reset = _status(main_code=0, started=0)
    monkeypatch.setattr(
        "eom_orchestrator.worker_systemd._start_unit",
        lambda *_args, **_kwargs: FixedUnitRun(unit, 0, b"", b"", reset, 3),
    )

    run = launch_worker_unit(_slot(), JOB_ID, timeout_seconds=600)

    assert run.exit_code == 0
    assert run.status == reset
    assert not reset.process_started


def test_launcher_accepts_production_collected_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unit = worker_unit_name(_slot(), JOB_ID)
    calls: list[tuple[str, ...]] = []
    results = iter(
        (
            subprocess.CompletedProcess((), 0, b"", b""),
            subprocess.CompletedProcess((), 3, b"", b""),
            subprocess.CompletedProcess(
                (),
                0,
                (
                    b"LoadState=loaded\nActiveState=inactive\nSubState=dead\n"
                    b"Result=success\nExecMainCode=0\nExecMainStatus=0\n"
                    b"ExecMainStartTimestampMonotonic=0\nNeedDaemonReload=no\n"
                ),
                b"",
            ),
        )
    )

    def run(argv: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        return next(results)

    monkeypatch.setattr("eom_orchestrator.worker_systemd.subprocess.run", run)

    result = launch_worker_unit(_slot(), JOB_ID, timeout_seconds=600)

    assert result.exit_code == 0
    assert result.status is not None and not result.status.process_started
    assert calls == [
        systemctl_start_argv(unit),
        systemctl_is_active_argv(unit),
        systemctl_show_argv(unit),
    ]


def test_launcher_accepts_success_when_collected_status_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unit = worker_unit_name(_slot(), JOB_ID)
    monkeypatch.setattr(
        "eom_orchestrator.worker_systemd._start_unit",
        lambda *_args, **_kwargs: FixedUnitRun(unit, 0, b"", b"", None, 4),
    )

    run = launch_worker_unit(_slot(), JOB_ID, timeout_seconds=600)

    assert run.exit_code == 0
    assert run.status is None


def test_launcher_rejects_missing_unit(monkeypatch: pytest.MonkeyPatch) -> None:
    unit = worker_unit_name(_slot(), JOB_ID)
    monkeypatch.setattr(
        "eom_orchestrator.worker_systemd._start_unit",
        lambda *_args, **_kwargs: FixedUnitRun(unit, 5, b"", b"Unit not found", None, 4),
    )

    with pytest.raises(PlatformError) as captured:
        launch_worker_unit(_slot(), JOB_ID, timeout_seconds=600)

    assert captured.value.code is ErrorCode.WORKER_UNAVAILABLE


def test_launcher_rejects_lingering_unit(monkeypatch: pytest.MonkeyPatch) -> None:
    unit = worker_unit_name(_slot(), JOB_ID)
    monkeypatch.setattr(
        "eom_orchestrator.worker_systemd._start_unit",
        lambda *_args, **_kwargs: FixedUnitRun(
            unit, 0, b"", b"", _status(active_state="active"), 0
        ),
    )

    with pytest.raises(PlatformError) as captured:
        launch_worker_unit(_slot(), JOB_ID, timeout_seconds=600)

    assert captured.value.code is ErrorCode.WORKER_UNAVAILABLE


def test_launcher_rejects_unexpected_activity_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unit = worker_unit_name(_slot(), JOB_ID)
    monkeypatch.setattr(
        "eom_orchestrator.worker_systemd._start_unit",
        lambda *_args, **_kwargs: FixedUnitRun(unit, 0, b"", b"", None, 1),
    )

    with pytest.raises(PlatformError) as captured:
        launch_worker_unit(_slot(), JOB_ID, timeout_seconds=600)

    assert captured.value.code is ErrorCode.WORKER_UNAVAILABLE


def test_launcher_rejects_timeout_outside_fixed_unit_contract() -> None:
    with pytest.raises(PlatformError) as captured:
        launch_worker_unit(_slot(), JOB_ID, timeout_seconds=599)

    assert captured.value.code is ErrorCode.WORKER_UNAVAILABLE


def test_collected_probe_status_is_not_a_lingering_process() -> None:
    collected = FixedUnitStatus(
        load_state="not-found",
        active_state="inactive",
        sub_state="dead",
        result="success",
        exec_main_code=0,
        exec_main_status=0,
        exec_main_started_monotonic=0,
        need_daemon_reload=False,
    )
    assert not collected.process_lingering


@pytest.mark.parametrize("inactive_exit_code", (3, 4))
def test_authorization_probe_accepts_inactive_or_collected_unit(
    inactive_exit_code: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []
    results = iter(
        (
            subprocess.CompletedProcess((), 0, b"", b""),
            subprocess.CompletedProcess((), inactive_exit_code, b"", b""),
        )
    )

    def run(argv: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        return next(results)

    monkeypatch.setattr("eom_orchestrator.worker_systemd.probe_unit_name", lambda _slot: PROBE_UNIT)
    monkeypatch.setattr("eom_orchestrator.worker_systemd.subprocess.run", run)

    result = probe_worker_systemd_authorization(_slot())

    assert result.ready
    assert result.code == "READY"
    assert calls == [systemctl_start_argv(PROBE_UNIT), systemctl_is_active_argv(PROBE_UNIT)]


def test_authorization_probe_classifies_start_denial(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "eom_orchestrator.worker_systemd.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            (), 1, b"", b"Interactive authentication required."
        ),
    )

    result = probe_worker_systemd_authorization(_slot())

    assert not result.ready
    assert result.code == "WORKER_SYSTEMD_AUTHORIZATION_DENIED"


def test_authorization_probe_does_not_misclassify_probe_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "eom_orchestrator.worker_systemd.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            (), 1, b"", b"Job failed because the control process exited with error code."
        ),
    )

    result = probe_worker_systemd_authorization(_slot())

    assert not result.ready
    assert result.code == "WORKER_SYSTEMD_PROBE_FAILED"


def test_authorization_probe_rejects_lingering_unit(monkeypatch: pytest.MonkeyPatch) -> None:
    results = iter(
        (
            subprocess.CompletedProcess((), 0, b"", b""),
            subprocess.CompletedProcess((), 0, b"active\n", b""),
        )
    )
    monkeypatch.setattr(
        "eom_orchestrator.worker_systemd.subprocess.run",
        lambda *_args, **_kwargs: next(results),
    )

    result = probe_worker_systemd_authorization(_slot())

    assert not result.ready
    assert result.code == "WORKER_SYSTEMD_PROBE_LINGERING"


def test_authorization_probe_rejects_unexpected_status(monkeypatch: pytest.MonkeyPatch) -> None:
    results = iter(
        (
            subprocess.CompletedProcess((), 0, b"", b""),
            subprocess.CompletedProcess((), 1, b"", b"status unavailable"),
        )
    )
    monkeypatch.setattr(
        "eom_orchestrator.worker_systemd.subprocess.run",
        lambda *_args, **_kwargs: next(results),
    )

    result = probe_worker_systemd_authorization(_slot())

    assert not result.ready
    assert result.code == "WORKER_SYSTEMD_STATUS_UNEXPECTED"


def test_authorization_probe_classifies_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(("systemctl",), 30)

    monkeypatch.setattr("eom_orchestrator.worker_systemd.subprocess.run", timeout)

    result = probe_worker_systemd_authorization(_slot())

    assert not result.ready
    assert result.code == "WORKER_SYSTEMD_PROBE_TIMEOUT"


def test_worker_exec_uses_fixed_workspace_and_codex_contract() -> None:
    assert validate_job_id(JOB_ID) == JOB_ID
    linux_user, root, workspace = expected_workspace("03", JOB_ID)
    assert linux_user == "eom-cdx-03"
    assert root == Path("/srv/eom/workspaces/eom-cdx-03")
    assert workspace == root / JOB_ID
    command = codex_command(workspace)
    assert command[0] == "/usr/local/bin/codex"
    assert command[1] == "exec"
    assert "--ask-for-approval" not in command
    assert command[-1] == "-"


def test_canonical_unit_and_helper_hashes_match_runtime_contract() -> None:
    for slot_id in sorted(WORKER_TEMPLATE_SHA256):
        worker = ROOT / "infra/systemd" / f"eom-worker-{slot_id}@.service"
        probe = ROOT / "infra/systemd" / f"eom-worker-probe-{slot_id}@.service"
        assert hashlib.sha256(worker.read_bytes()).hexdigest() == WORKER_TEMPLATE_SHA256[slot_id]
        assert hashlib.sha256(probe.read_bytes()).hexdigest() == PROBE_TEMPLATE_SHA256[slot_id]
    executable = ROOT / "services/orchestrator/eom_orchestrator/worker_exec.py"
    assert hashlib.sha256(executable.read_bytes()).hexdigest() == WORKER_EXECUTABLE_SHA256


def test_collect_mode_is_only_in_probe_unit_sections() -> None:
    def directive_sections(path: Path, directive: str) -> list[str]:
        section = ""
        matches: list[str] = []
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
            elif line.startswith(f"{directive}="):
                matches.append(section)
        return matches

    for index in range(1, 6):
        slot_id = f"{index:02d}"
        worker = ROOT / "infra/systemd" / f"eom-worker-{slot_id}@.service"
        probe = ROOT / "infra/systemd" / f"eom-worker-probe-{slot_id}@.service"
        assert directive_sections(worker, "CollectMode") == []
        assert directive_sections(probe, "CollectMode") == ["Unit"]


@pytest.mark.skipif(shutil.which("systemd-analyze") is None, reason="systemd-analyze unavailable")
def test_all_worker_templates_verify_without_diagnostics(tmp_path: Path) -> None:
    root = tmp_path / "root"
    unit_root = root / "etc/systemd/system"
    worker_exec = root / "usr/local/libexec/eom-worker-exec"
    true_binary = root / "usr/bin/true"
    unit_root.mkdir(parents=True)
    worker_exec.parent.mkdir(parents=True)
    true_binary.parent.mkdir(parents=True)
    shutil.copy2("/usr/bin/true", worker_exec)
    shutil.copy2("/usr/bin/true", true_binary)

    unit_paths: list[str] = []
    for index in range(1, 6):
        slot_id = f"{index:02d}"
        for name in (
            f"eom-worker-{slot_id}@.service",
            f"eom-worker-probe-{slot_id}@.service",
        ):
            shutil.copy2(ROOT / "infra/systemd" / name, unit_root / name)
            unit_paths.append(f"/etc/systemd/system/{name}")

    completed = subprocess.run(
        [
            "systemd-analyze",
            "verify",
            "--recursive-errors=no",
            f"--root={root}",
            *unit_paths,
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ""
    assert completed.stderr == ""


def test_worker_templates_fix_identity_command_and_sandbox() -> None:
    required = (
        "NoNewPrivileges=true",
        "ProtectSystem=strict",
        "ProtectHome=read-only",
        "PrivateTmp=true",
        "ProtectKernelTunables=true",
        "ProtectKernelModules=true",
        "ProtectControlGroups=true",
        "RestrictSUIDSGID=true",
        "LockPersonality=true",
        "RestrictRealtime=true",
        "CapabilityBoundingSet=",
        "UMask=0007",
        "MemoryMax=6G",
        "CPUQuota=200%",
        "TasksMax=256",
        "InaccessiblePaths=/mnt/nas",
        "InaccessiblePaths=/var/run/docker.sock",
        "InaccessiblePaths=/home/eom/EOM",
        "InaccessiblePaths=/srv/eom/staging",
    )
    for index in range(1, 6):
        slot_id = f"{index:02d}"
        source = (ROOT / "infra/systemd" / f"eom-worker-{slot_id}@.service").read_text(
            encoding="utf-8"
        )
        assert f"User=eom-cdx-{slot_id}" in source
        assert f"Group=eom-cdx-{slot_id}" in source
        assert (
            f"ExecStart=/usr/local/libexec/eom-worker-exec --slot {slot_id} --job-id %i" in source
        )
        assert "systemd-run" not in source
        assert all(setting in source for setting in required)


def test_workflow_worker_runtime_contains_no_transient_launcher() -> None:
    for relative in (
        "services/orchestrator/eom_orchestrator/worker.py",
        "services/orchestrator/eom_orchestrator/worker_exec.py",
        "services/orchestrator/eom_orchestrator/worker_systemd.py",
        "services/workflow_runner/eom_workflow_runner/readiness.py",
    ):
        assert "systemd-run" not in (ROOT / relative).read_text(encoding="utf-8")


def test_polkit_rule_has_no_external_execution_or_cached_authorization() -> None:
    source = (ROOT / "infra/polkit/50-eom-worker-units.rules").read_text(encoding="utf-8")
    assert "polkit.spawn" not in source
    assert "_KEEP" not in source
    assert "manage-unit-files" not in source


@pytest.mark.skipif(shutil.which("node") is None, reason="node is unavailable")
@pytest.mark.parametrize(
    ("user", "action_id", "unit", "verb", "expected"),
    (
        (
            "eom-workflow-runner",
            "org.freedesktop.systemd1.manage-units",
            f"eom-worker-01@{JOB_ID}.service",
            "start",
            "yes",
        ),
        (
            "eom-workflow-runner",
            "org.freedesktop.systemd1.manage-units",
            "eom-worker-probe-05@probe_0123456789abcdef0123456789abcdef.service",
            "start",
            "yes",
        ),
        (
            "eom-hwpx-manager",
            "org.freedesktop.systemd1.manage-units",
            "eom-hwpx-kordoc@hwpxbuild_0123456789abcdef0123456789abcdef.service",
            "start",
            "yes",
        ),
        (
            "eom-hwpx-manager",
            "org.freedesktop.systemd1.manage-units",
            "eom-hwpx-builder@hwpxbuild_0123456789abcdef0123456789abcdef.service",
            "start",
            "yes",
        ),
        (
            "eom",
            "org.freedesktop.systemd1.manage-units",
            "eom-worker-probe-05@probe_0123456789abcdef0123456789abcdef.service",
            "start",
            "yes",
        ),
        (
            "eom",
            "org.freedesktop.systemd1.manage-units",
            f"eom-worker-01@{JOB_ID}.service",
            "start",
            "no",
        ),
        (
            "eom-workflow-runner",
            "org.freedesktop.systemd1.manage-units",
            "eom-hwpx-builder@hwpxbuild_0123456789abcdef0123456789abcdef.service",
            "start",
            "no",
        ),
        (
            "eom-hwpx-manager",
            "org.freedesktop.systemd1.manage-units",
            f"eom-worker-01@{JOB_ID}.service",
            "start",
            "no",
        ),
        (
            "other",
            "org.freedesktop.systemd1.manage-units",
            f"eom-worker-01@{JOB_ID}.service",
            "start",
            None,
        ),
        (
            "eom-workflow-runner",
            "org.freedesktop.systemd1.manage-units",
            "ssh.service",
            "start",
            "no",
        ),
        (
            "eom-workflow-runner",
            "org.freedesktop.systemd1.manage-units",
            "eom-worker-01@../../root.service",
            "start",
            "no",
        ),
        (
            "eom-workflow-runner",
            "org.freedesktop.systemd1.manage-units",
            f"eom-worker-01@{JOB_ID}.service",
            "restart",
            "no",
        ),
        (
            "eom-workflow-runner",
            "org.freedesktop.systemd1.manage-units",
            "run-u1.service",
            None,
            "no",
        ),
        (
            "eom-hwpx-manager",
            "org.freedesktop.systemd1.manage-units",
            "eom-hwpx-kordoc@../../root.service",
            "start",
            "no",
        ),
        (
            "eom-hwpx-manager",
            "org.freedesktop.systemd1.manage-units",
            "eom-hwpx-builder@../../root.service",
            "start",
            "no",
        ),
        (
            "eom-workflow-runner",
            "org.freedesktop.systemd1.manage-unit-files",
            f"eom-worker-01@{JOB_ID}.service",
            "enable",
            None,
        ),
    ),
)
def test_polkit_rule_is_a_strict_start_only_allowlist(
    user: str, action_id: str, unit: str, verb: str | None, expected: str | None
) -> None:
    rule = ROOT / "infra/polkit/50-eom-worker-units.rules"
    script = """
const fs = require('fs');
let callback;
global.polkit = {
  addRule: function(value) { callback = value; },
  Result: { YES: 'yes', NO: 'no', NOT_HANDLED: null }
};
eval(fs.readFileSync(process.argv[1], 'utf8'));
const details = { unit: process.argv[4] };
if (process.argv[5] !== '__NONE__') details.verb = process.argv[5];
const result = callback(
  { id: process.argv[3], lookup: function(key) { return details[key]; } },
  { user: process.argv[2] }
);
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        [
            "node",
            "-e",
            script,
            str(rule),
            user,
            action_id,
            unit,
            verb if verb is not None else "__NONE__",
        ],
        capture_output=True,
        check=True,
        text=True,
    )
    serialized = "null" if expected is None else f'"{expected}"'
    assert completed.stdout == serialized
