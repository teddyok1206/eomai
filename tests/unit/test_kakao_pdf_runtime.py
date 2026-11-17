"""Fixed launcher observations and configuration, not a substitute for privileged sandbox tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from eom_kakao_archive_contracts import canonical_bytes, sha256
from eom_kakao_archive_worker import fixed_render
from eom_orchestrator import kakao_pdf_runtime as runtime
from eom_orchestrator.kakao_pdf_files import KakaoPdfExecutionError

from tests.unit.test_kakao_question_render import RELEASE, identity
from tests.unit.test_kakao_question_render import prepared as prepared


def test_fixed_entry_uses_exact_attempt_and_terminal_local_result(prepared, tmp_path, monkeypatch):
    source, output, prepare = prepared
    command = prepare()
    workspace = tmp_path / command.execution.attempt_id
    workspace.mkdir()
    source.rename(workspace / "input")
    output.rename(workspace / "output")
    request = workspace / "input" / "request.json"
    request.write_bytes(canonical_bytes(command.model_dump(mode="json")))
    request.chmod(0o640)
    monkeypatch.setattr(fixed_render, "RUNTIME_ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["fixed-render", command.execution.attempt_id])
    monkeypatch.setenv("EOM_KAKAO_RENDER_RELEASE_SHA256", RELEASE)
    assert fixed_render.main() == 0
    assert (workspace / "output" / "result.json").exists()
    # Same attempt cannot overwrite its result or previously written PDF.
    before = (workspace / "output" / "report.pdf").read_bytes()
    assert fixed_render.main() == 2
    assert (workspace / "output" / "report.pdf").read_bytes() == before


@pytest.mark.parametrize("bad", ["../../private", "kakaoattempt_private-photo", "", "--input-root"])
def test_fixed_entry_has_no_path_or_authority_argv(bad, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["fixed-render", bad])
    assert fixed_render.main() == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "KAKAO_RENDER_FIXED_EXECUTION_FAILED\n"


def observations():
    before = {
        "FragmentPath": str(runtime.KAKAO_TEMPLATE),
        "DropInPaths": "",
        "User": runtime.KAKAO_WORKER,
        "Group": runtime.KAKAO_WORKER,
        "ActiveState": "inactive",
        "MainPID": "0",
        "ExecMainStartTimestampMonotonic": "0",
    }
    after = {
        **before,
        "ActiveState": "active",
        "SubState": "exited",
        "ExecMainStartTimestampMonotonic": "100",
        "Result": "success",
        "ExecMainStatus": "0",
        "InvocationID": "a" * 32,
    }
    return before, after


def launcher(monkeypatch, prepared, *, before_change=None, after_change=None):
    _, _, prepare = prepared
    command = prepare()
    before, after = observations()
    before.update(before_change or {})
    after.update(after_change or {})
    monkeypatch.setattr(runtime.FixedKakaoPdfLauncher, "_installed", lambda *args: None)
    show = Mock(side_effect=[before, after, {**before, "ExecMainStartTimestampMonotonic": "100"}])
    monkeypatch.setattr(runtime, "_show", show)
    monkeypatch.setattr(runtime, "_cgroup_quiescent", lambda _unit: None)
    run = Mock(return_value=subprocess.CompletedProcess([], 0))
    monkeypatch.setattr(runtime.subprocess, "run", run)
    value = runtime.FixedKakaoPdfLauncher("sha256:" + "b" * 64, RELEASE)
    return value, command, run, show


def test_launcher_only_invokes_fixed_start_unit_once(prepared, monkeypatch):
    value, command, run, show = launcher(monkeypatch, prepared)
    value.run(command, runtime.KAKAO_WORKSPACE_ROOT / command.execution.attempt_id)
    assert show.call_count == 3 and run.call_count == 2
    assert run.call_args_list[0].args[0] == [
        "/usr/bin/systemctl",
        "--no-ask-password",
        "start",
        f"eom-kakao-pdf@{command.execution.attempt_id}.service",
    ]
    assert run.call_args_list[0].kwargs["timeout"] == 190
    assert run.call_args_list[1].args[0][2] == "stop"
    assert run.call_args.kwargs["stdout"] == subprocess.DEVNULL


@pytest.mark.parametrize("state", ["absent", "empty", "populated", "malformed", "linked"])
def test_recovery_checks_actual_cgroup_without_starting_a_unit(
    prepared, monkeypatch, tmp_path, state
):
    _, _, prepare = prepared
    command = prepare()
    before, _ = observations()
    monkeypatch.setattr(runtime.FixedKakaoPdfLauncher, "_installed", lambda *_args: None)
    monkeypatch.setattr(runtime, "_show", lambda _unit: before)
    monkeypatch.setattr(runtime, "CGROUP_ROOT", tmp_path)
    unit = f"eom-kakao-pdf@{command.execution.attempt_id}.service"
    if state != "absent":
        cgroup = tmp_path / unit
        cgroup.mkdir()
        data = (
            b"populated 0\nfrozen 0\n"
            if state == "empty"
            else b"populated 1\n"
            if state == "populated"
            else b"unexpected"
        )
        (cgroup / "cgroup.events").write_bytes(data)
        if state == "linked":
            (cgroup / "cgroup.events").unlink()
            (cgroup / "cgroup.events").symlink_to(tmp_path / "foreign")
    process = Mock()
    monkeypatch.setattr(runtime.subprocess, "run", process)
    value = runtime.FixedKakaoPdfLauncher("sha256:" + "b" * 64, RELEASE)
    if state in {"absent", "empty"}:
        value.assert_stopped(command, runtime.KAKAO_WORKSPACE_ROOT / command.execution.attempt_id)
    else:
        with pytest.raises(KakaoPdfExecutionError, match="EXECUTION_UNCERTAIN"):
            value.assert_stopped(
                command, runtime.KAKAO_WORKSPACE_ROOT / command.execution.attempt_id
            )
    process.assert_not_called()


def test_explicit_recovery_closes_only_an_already_exited_original(prepared, monkeypatch):
    value, command, process, show = launcher(monkeypatch, prepared)
    before, after = observations()
    show.side_effect = [after, before]
    value.close_finished(command, runtime.KAKAO_WORKSPACE_ROOT / command.execution.attempt_id)
    assert process.call_count == 1
    assert process.call_args.args[0][2] == "stop"


@pytest.mark.parametrize(
    "change", [{"MainPID": "123"}, {"SubState": "running"}, {"DropInPaths": "/private"}]
)
def test_recovery_never_stops_unknown_running_processes(prepared, monkeypatch, change):
    value, command, process, show = launcher(monkeypatch, prepared)
    _before, after = observations()
    show.side_effect = [{**after, **change}]
    with pytest.raises(KakaoPdfExecutionError, match="EXECUTION_UNCERTAIN"):
        value.close_finished(command, runtime.KAKAO_WORKSPACE_ROOT / command.execution.attempt_id)
    process.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"ActiveState": "active"},
        {"ExecMainStartTimestampMonotonic": "99"},
        {"DropInPaths": "/tmp/replaced.conf"},
        {"User": "root"},
        {"FragmentPath": "/tmp/unit"},
    ],
)
def test_not_fresh_or_wrong_identity_unit_never_relaunched(prepared, monkeypatch, change):
    value, command, run, _ = launcher(monkeypatch, prepared, before_change=change)
    with pytest.raises(KakaoPdfExecutionError, match="UNIT_NOT_FRESH"):
        value.run(command, runtime.KAKAO_WORKSPACE_ROOT / command.execution.attempt_id)
    run.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"ActiveState": "inactive"},
        {"Result": "timeout"},
        {"ExecMainStatus": "1"},
        {"InvocationID": ""},
        {"ExecMainStartTimestampMonotonic": "0"},
    ],
)
def test_failed_uncertain_observation_does_not_accept_or_resubmit(prepared, monkeypatch, change):
    value, command, run, _ = launcher(monkeypatch, prepared, after_change=change)
    with pytest.raises(KakaoPdfExecutionError, match="WORKER_FAILED"):
        value.run(command, runtime.KAKAO_WORKSPACE_ROOT / command.execution.attempt_id)
    assert run.call_count == 1


def test_timeout_does_not_retry_or_kill_an_unknown_original(prepared, monkeypatch):
    value, command, run, _ = launcher(monkeypatch, prepared)
    run.side_effect = subprocess.TimeoutExpired("systemctl", 190)
    with pytest.raises(KakaoPdfExecutionError, match="EXECUTION_UNCERTAIN"):
        value.run(command, runtime.KAKAO_WORKSPACE_ROOT / command.execution.attempt_id)
    assert run.call_count == 1


def test_success_is_not_accepted_when_owned_cgroup_stop_is_uncertain(prepared, monkeypatch):
    value, command, run, _ = launcher(monkeypatch, prepared)
    run.side_effect = [subprocess.CompletedProcess([], 0), subprocess.TimeoutExpired("stop", 10)]
    with pytest.raises(KakaoPdfExecutionError, match="EXECUTION_UNCERTAIN"):
        value.run(command, runtime.KAKAO_WORKSPACE_ROOT / command.execution.attempt_id)
    assert run.call_count == 2


def test_runtime_template_is_network_off_resource_bounded_and_only_output_writable():
    raw = Path("infra/systemd/eom-kakao-pdf@.service").read_text()
    for setting in (
        "PrivateNetwork=yes",
        "NoNewPrivileges=yes",
        "ProtectSystem=strict",
        "ProtectHome=yes",
        "PrivateDevices=yes",
        "MemoryMax=1G",
        "CPUQuota=200%",
        "LimitFSIZE=67108864",
        "TimeoutStartSec=180",
        "KillMode=control-group",
        "TemporaryFileSystem=/run/eom-kakao-render:ro,mode=0755",
        "BindReadOnlyPaths=/var/lib/eom-catalog-api/staging/kakao-render/%i/input:",
        "ReadWritePaths=/run/eom-kakao-render/%i/output",
        "User=eom-kakao-render",
        "Group=eom-kakao-render",
        " -I -B -m eom_kakao_archive_worker.fixed_render %i",
    ):
        assert setting in raw
    for path in ("/mnt/nas", "/etc/eom", "/root", "/srv/eom/worker-homes", "/home/eom/EOM"):
        assert path in raw.split("InaccessiblePaths=", 1)[1]
    assert (
        "SupplementaryGroups=" not in raw and "docker" not in raw.split("InaccessiblePaths=", 1)[0]
    )


@pytest.mark.skipif(os.geteuid() == 0, reason="Root bypasses directory permission checks")
def test_descriptor_walk_requires_a_readable_private_parent(tmp_path):
    parent = tmp_path / "private-runtime"
    child = parent / "own-attempt"
    child.mkdir(parents=True)
    parent.chmod(0o111)
    try:
        assert child.is_dir()  # Path traversal itself is allowed, not directory FD reads.
        with pytest.raises(PermissionError), fixed_render.directory_descriptor(child):
            pass
    finally:
        parent.chmod(0o755)
    with fixed_render.directory_descriptor(child) as descriptor:
        assert os.fstat(descriptor).st_ino == child.stat().st_ino


def test_release_validation_rejects_wrong_root_before_launch(prepared):
    _, _, prepare = prepared
    command = prepare()
    value = runtime.FixedKakaoPdfLauncher("sha256:" + "b" * 64, RELEASE)
    with pytest.raises(KakaoPdfExecutionError, match="RUNTIME_INVALID"):
        value.run(command, Path("/tmp") / identity("attempt"))


def test_installed_template_and_exact_nonsecret_environment_are_hashed(prepared, monkeypatch):
    _, _, prepare = prepared
    command = prepare()
    unit = Path("infra/systemd/eom-kakao-pdf@.service").read_bytes()
    value = runtime.FixedKakaoPdfLauncher(sha256(unit), RELEASE)
    monkeypatch.setattr(
        runtime.pwd, "getpwnam", lambda name: type("User", (), {"pw_uid": os.getuid() + 1})()
    )
    monkeypatch.setattr(
        runtime.grp, "getgrnam", lambda name: type("Group", (), {"gr_gid": os.getgid()})()
    )
    monkeypatch.setattr(runtime, "require_native_exam_runtime_python", lambda path: path)
    # Real /etc/eom and /etc/systemd/system ownership is checked, no files are written.
    monkeypatch.setattr(
        runtime,
        "read_local",
        lambda root, name, **kwargs: (
            unit
            if name.endswith(".service")
            else f"EOM_KAKAO_RENDER_RELEASE_SHA256={RELEASE}\n".encode()
        ),
    )
    value._installed(command, runtime.KAKAO_WORKSPACE_ROOT / command.execution.attempt_id)
    monkeypatch.setattr(runtime, "read_local", lambda *args, **kwargs: b"changed")
    with pytest.raises(KakaoPdfExecutionError, match="RELEASE_MISMATCH"):
        value._installed(command, runtime.KAKAO_WORKSPACE_ROOT / command.execution.attempt_id)
