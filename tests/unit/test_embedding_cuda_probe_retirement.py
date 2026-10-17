"""Synthetic root retirement ports and real temporary record I/O; no service/lease mutation."""

from __future__ import annotations

import json
import os
import stat
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_service import embedding_cuda_probe_retirement as owner
from eom_catalog_service.embedding_native_cuda_probe_observation import (
    NativeCudaProbeFailedTerminalObservation,
    verify_native_cuda_probe_failed_terminal,
)
from pydantic import TypeAdapter

from tests.unit.test_embedding_native_cuda_probe import case as case
from tests.unit.test_embedding_native_cuda_probe_observation import (
    failed_ended as failed_ended,
)
from tests.unit.test_embedding_native_cuda_probe_observation import process as process
from tests.unit.test_embedding_native_cuda_probe_ready import ready_case as ready_case
from tests.unit.test_embedding_native_probe_observation import ledger as ledger


@pytest.fixture
def retirement(failed_ended, monkeypatch, tmp_path):
    process, ready, state, _ = failed_ended
    report = process[0]
    failed = verify_native_cuda_probe_failed_terminal(ready, report)
    events = []
    state["retired"] = False
    state["fence_held"] = False

    @contextmanager
    def guard():
        events.append("guard")
        yield
        events.append("guard-close")

    @contextmanager
    def released(resources):
        assert state["retired"] and resources == ready.resources
        state["fence_held"] = True
        events.append("released-lock")
        try:
            yield
        finally:
            state["fence_held"] = False
            events.append("lock-close")

    def records(execution):
        assert execution == ready.execution_id
        (tmp_path / execution).mkdir()
        return os.open(tmp_path / execution, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)

    def command(args, **kwargs):
        if args[1] == "--no-ask-password":
            assert args == ("/usr/bin/systemctl", "--no-ask-password", "reset-failed", process[-1])
            assert (tmp_path / ready.execution_id / "intent.json").is_file()
            events.append("reset")
            state["retired"] = True
            return SimpleNamespace(returncode=0)
        assert args[:3] == ("/usr/bin/systemctl", "show", process[-1])
        values = {
            "LoadState": "loaded",
            "ActiveState": "inactive",
            "SubState": "dead",
            "MainPID": "0",
            "NFileDescriptorStore": "0",
            "InvocationID": "",
            "NeedDaemonReload": "no",
            "DropInPaths": "",
            "FragmentPath": "/etc/systemd/system/" + owner.CUDA_PROBE_TEMPLATE,
        } | state.get("unit_changes", {})
        return SimpleNamespace(
            returncode=0,
            stdout="".join(f"{key}={value}\n" for key, value in values.items()).encode(),
            stderr=b"",
        )

    monkeypatch.setattr(owner, "_publication_guard", guard)
    monkeypatch.setattr(owner, "_records", records)
    monkeypatch.setattr(owner, "hold_released_cuda_probe_resources", released)
    monkeypatch.setattr(
        owner,
        "require_native_cuda_probe_unit",
        lambda: (report.worker_uid, report.worker_gid, report.supplementary_gids[0]),
    )
    monkeypatch.setattr(owner, "observe_runtime_device", lambda _: events.append("device"))
    monkeypatch.setattr(owner, "observe_cuda_probe_gpu_clients", lambda _: state["gpu_pids"])
    monkeypatch.setattr(owner.subprocess, "run", command)
    return failed, report, state, events, tmp_path


def test_only_original_failed_unit_is_retired_after_durable_intent_and_independent_checks(
    retirement,
):
    failed, report, state, events, tmp = retirement
    result = owner.retire_failed_native_cuda_probe(failed, report)
    assert result.original_failure.failed_unit.failed
    assert result.original_failure.ready_observation == failed.ready_observation
    assert result.retired_unit.load_state == "loaded" and result.observed_at_utc.endswith("Z")
    assert state["retired"] and not state["fence_held"]
    assert events.index("reset") < events.index("released-lock") < events.index("guard-close")
    intent = json.loads((tmp / report.execution_id / "intent.json").read_bytes())
    final = json.loads((tmp / report.execution_id / "result.json").read_bytes())
    assert intent["observation"]["failed_unit"]["status"]["result"] == "exit-code"
    assert (
        TypeAdapter(NativeCudaProbeFailedTerminalObservation).validate_python(intent["observation"])
        == result.original_failure
    )
    assert intent["admission_granted"] is False and final["admission_granted"] is False
    assert final["event"] == "FAILED_PROBE_RETIRED_NOT_ADMITTED"
    assert stat.S_IMODE((tmp / report.execution_id / "intent.json").stat().st_mode) == 0o400


def test_record_failure_never_submits_reset(retirement, monkeypatch):
    failed, report, _, events, _ = retirement

    def denied(*_args):
        raise OSError("synthetic fsync/storage error")

    monkeypatch.setattr(owner, "_save_record", denied)
    with pytest.raises(OSError):
        owner.retire_failed_native_cuda_probe(failed, report)
    assert "reset" not in events


def test_changed_invocation_after_intent_prevents_reset(retirement, monkeypatch):
    failed, report, _, events, _ = retirement
    count = 0

    def recheck(*_args):
        nonlocal count
        count += 1
        return (
            failed
            if count == 1
            else replace(failed, failed_unit=replace(failed.failed_unit, invocation_id="c" * 32))
        )

    monkeypatch.setattr(owner, "verify_native_cuda_probe_failed_terminal", recheck)
    with pytest.raises(ValueError, match="IDENTITY_CHANGED"):
        owner.retire_failed_native_cuda_probe(failed, report)
    assert count == 2 and "reset" not in events


@pytest.mark.parametrize("fault", ("timeout", "nonzero", "os_error"))
def test_uncertain_reset_is_preserved_and_never_automatically_retried(
    retirement, monkeypatch, fault
):
    failed, report, _, _, tmp = retirement
    calls = []

    def uncertain(args, **kwargs):
        calls.append(args)
        if fault == "timeout":
            raise owner.subprocess.TimeoutExpired(args, 10)
        if fault == "os_error":
            raise OSError("synthetic transport failure")
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(owner.subprocess, "run", uncertain)
    with pytest.raises(ValueError, match="OUTCOME_UNCERTAIN"):
        owner.retire_failed_native_cuda_probe(failed, report)
    assert len(calls) == 1 and calls[0][2] == "reset-failed"
    assert (tmp / report.execution_id / "intent.json").is_file()
    assert not (tmp / report.execution_id / "result.json").exists()


def test_existing_intent_reservation_prevents_second_mutation(retirement):
    failed, report, _, events, tmp = retirement
    (tmp / report.execution_id).mkdir()
    with pytest.raises(FileExistsError):
        owner.retire_failed_native_cuda_probe(failed, report)
    assert "reset" not in events


def test_readonly_recovery_can_finish_observation_without_reissuing_reset(retirement):
    failed, report, state, events, _ = retirement
    state["retired"] = True
    result = owner.observe_retired_native_cuda_probe(failed, report)
    assert result.original_failure == failed and "reset" not in events


@pytest.mark.parametrize(
    "key,value",
    [
        ("ActiveState", "failed"),
        ("SubState", "running"),
        ("MainPID", "123"),
        ("NFileDescriptorStore", "1"),
        ("InvocationID", "c" * 32),
        ("NeedDaemonReload", "yes"),
        ("DropInPaths", "/tmp/override.conf"),
        ("FragmentPath", "/tmp/other.service"),
        ("LoadState", "error"),
    ],
)
def test_post_unit_requires_actual_empty_fixed_or_collected_state(retirement, key, value):
    failed, report, state, _, tmp = retirement
    state["unit_changes"] = {key: value}
    with pytest.raises(ValueError, match="OUTCOME_UNCERTAIN"):
        owner.retire_failed_native_cuda_probe(failed, report)
    assert (tmp / report.execution_id / "intent.json").is_file()
    assert not (tmp / report.execution_id / "result.json").exists()


def test_collected_unit_is_allowed_but_does_not_hide_original_failure(retirement):
    failed, report, state, _, _ = retirement
    state["unit_changes"] = {"LoadState": "not-found", "FragmentPath": ""}
    assert owner.retire_failed_native_cuda_probe(failed, report).original_failure.failed_unit.failed


def test_gpu_work_blocks_reset_before_intent(retirement):
    failed, report, state, _, tmp = retirement
    state["gpu_pids"] = (report.pid,)
    # The first pre-reset failure check rejects this even before any intent/mutation.
    with pytest.raises(ValueError, match="GPU_CLEANUP_UNCERTAIN"):
        owner.retire_failed_native_cuda_probe(failed, report)
    assert not (tmp / report.execution_id).exists()


def test_post_gpu_failure_preserves_intent_without_a_success_record(retirement, monkeypatch):
    failed, report, state, events, tmp = retirement

    def client(_):
        assert state["fence_held"]
        return (report.pid,)

    monkeypatch.setattr(owner, "observe_cuda_probe_gpu_clients", client)
    with pytest.raises(ValueError, match="OUTCOME_UNCERTAIN"):
        owner.retire_failed_native_cuda_probe(failed, report)
    assert events.count("reset") == 1 and not state["fence_held"]
    assert (tmp / report.execution_id / "intent.json").is_file()
    assert not (tmp / report.execution_id / "result.json").exists()


@pytest.mark.parametrize("fault", ("process", "cgroup"))
def test_post_process_or_cgroup_race_is_not_retirement_success(retirement, monkeypatch, fault):
    failed, report, state, events, tmp = retirement
    original = owner.subprocess.run

    def changed(args, **kwargs):
        result = original(args, **kwargs)
        if args[1] == "--no-ask-password":
            state["proc_exists" if fault == "process" else "pids"] = (
                True if fault == "process" else (123,)
            )
        return result

    monkeypatch.setattr(owner.subprocess, "run", changed)
    with pytest.raises(ValueError, match="UNCERTAIN"):
        owner.retire_failed_native_cuda_probe(failed, report)
    assert events.count("reset") == 1 and not (tmp / report.execution_id / "result.json").exists()


@pytest.mark.parametrize("raw", (b"\xff", b"x" * 16385, b"unknown=1\n", b"LoadState=loaded\n" * 2))
def test_unit_projection_is_bounded_unique_utf8_and_closed(monkeypatch, raw):
    monkeypatch.setattr(
        owner.subprocess,
        "run",
        lambda *_a, **_kw: SimpleNamespace(returncode=0, stdout=raw, stderr=b""),
    )
    with pytest.raises(ValueError, match="OUTCOME_UNCERTAIN"):
        owner._retired_unit("fixed", "b" * 32)


def test_publication_guard_reuses_existing_real_flock_and_closes_its_descriptor(
    tmp_path, monkeypatch
):
    path = tmp_path / "publication.lock"
    path.touch(mode=0o600)
    original_lstat = Path.lstat

    def root_stat(value):
        fields = list(value)
        fields[4] = 0  # Synthetic root metadata only; actual file descriptions are real.
        return os.stat_result(fields)

    def lstat(member, *args, **kwargs):
        value = original_lstat(member, *args, **kwargs)
        return root_stat(value) if member == path else value

    class Files:
        def __init__(self, uid):
            assert uid == 0

        def observe_protected_member_identity(self, member):
            assert member == path

        def assert_unchanged(self):
            pass

    monkeypatch.setattr(owner, "_PUBLICATION_LOCK", path)
    monkeypatch.setattr(owner, "NumericalRuntimeFileSnapshots", Files)
    monkeypatch.setattr(Path, "lstat", lstat)
    monkeypatch.setattr(
        owner,
        "os",
        SimpleNamespace(
            open=os.open,
            close=os.close,
            fstat=lambda descriptor: root_stat(os.fstat(descriptor)),
            O_RDONLY=os.O_RDONLY,
            O_NOFOLLOW=os.O_NOFOLLOW,
            O_CLOEXEC=os.O_CLOEXEC,
        ),
    )
    contender = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    try:
        with owner._publication_guard(), pytest.raises(BlockingIOError):
            owner.fcntl.flock(contender, owner.fcntl.LOCK_EX | owner.fcntl.LOCK_NB)
        owner.fcntl.flock(contender, owner.fcntl.LOCK_EX | owner.fcntl.LOCK_NB)
    finally:
        os.close(contender)


def test_record_creation_is_no_clobber_and_directory_is_real_not_symlink(tmp_path, monkeypatch):
    root = tmp_path / "retirements"
    monkeypatch.setattr(owner, "_ROOT", root)
    original = Path.lstat
    ancestors = {*root.parents, root}

    def protected(path, *args, **kwargs):
        value = original(path, *args, **kwargs)
        if path in ancestors and stat.S_ISDIR(value.st_mode):
            fields = list(value)
            fields[0], fields[4] = stat.S_IFDIR | 0o700, 0
            return os.stat_result(fields)
        return value

    monkeypatch.setattr(Path, "lstat", protected)
    execution = "a" * 32
    descriptor = owner._records(execution)
    os.close(descriptor)
    with pytest.raises(FileExistsError):
        owner._records(execution)
    other = tmp_path / "other"
    other.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    monkeypatch.setattr(owner, "_ROOT", linked)
    with pytest.raises(ValueError, match="RECORD_DIRECTORY_INVALID"):
        owner._records("b" * 32)
