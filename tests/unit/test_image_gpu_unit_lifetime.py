"""Synthetic root/systemd/physical-lease ports; real no-clobber temporary audit I/O."""

from __future__ import annotations

import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest
from eom_catalog_service import image_gpu_unit_lifetime as owner
from eom_catalog_service import image_gpu_unit_observation as observation
from eom_identifiers import canonical_json_bytes
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter

from tests.unit.test_embedding_native_probe_observation import terminal as terminal_unit
from tests.unit.test_image_gpu_unit_observation import UNIT, observe
from tests.unit.test_image_gpu_unit_observation import image as image


@pytest.fixture
def lifetime(image, monkeypatch, tmp_path):
    ready = observe(image)
    ended = replace(terminal_unit(), fragment_path=ready.unit.fragment_path)
    terminal = observation.ImageGpuUnitTerminalObservation(
        ready, ended, "SUCCEEDED", "2026-10-17T03:00:00Z"
    )
    state = {
        "ready": ready,
        "terminal": terminal,
        "retired": False,
        "held": False,
        "commands": [],
        "events": [],
        "changes": {},
        "gpu_clients": (),
        "pids": (),
        "rechecks": 0,
    }

    def reserve(value, phase):
        assert value == ready
        (tmp_path / phase).mkdir(mode=0o700)
        return os.open(tmp_path / phase, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)

    def recheck(*args, **kwargs):
        state["rechecks"] += 1
        return state["ready"]

    def command(args, **kwargs):
        state["commands"].append(args)
        if args[1] == "--no-ask-password":
            phase = "ack" if args[2] == "kill" else "retirement"
            assert (tmp_path / phase / "intent.json").is_file()
            assert not (tmp_path / phase / "result.json").exists()
            state["events"].append(args[2])
            if args[2] in {"stop", "reset-failed"}:
                state["retired"] = True
            return SimpleNamespace(returncode=0)
        assert args[:3] == ("/usr/bin/systemctl", "show", UNIT)
        assert state["retired"]
        values = {
            "LoadState": "loaded",
            "ActiveState": "inactive",
            "SubState": "dead",
            "MainPID": "0",
            "NFileDescriptorStore": "0",
            "InvocationID": "",
            "NeedDaemonReload": "no",
            "FragmentPath": ready.unit.fragment_path,
            "DropInPaths": "",
        } | state["changes"]
        return SimpleNamespace(
            returncode=0,
            stdout="".join(f"{key}={value}\n" for key, value in values.items()).encode(),
            stderr=b"",
        )

    @contextmanager
    def released(resources):
        assert resources == ready.resources and state["retired"]
        state["events"].append("hold")
        state["held"] = True
        try:
            yield
        finally:
            state["held"] = False
            state["events"].append("close")

    def clients(device):
        assert device == ready.device and state["held"]
        return state["gpu_clients"]

    monkeypatch.setattr(owner.os, "getresuid", lambda: (0, 0, 0))
    monkeypatch.setattr(owner, "_reserve", reserve)
    monkeypatch.setattr(owner, "observe_image_gpu_unit_ready", recheck)
    monkeypatch.setattr(owner, "verify_image_gpu_unit_terminal", lambda _: state["terminal"])
    monkeypatch.setattr(owner.subprocess, "run", command)
    monkeypatch.setattr(owner, "hold_released_image_unit_gpu_resources", released)
    monkeypatch.setattr(owner, "observe_cuda_probe_gpu_clients", clients)
    monkeypatch.setattr(owner, "observe_runtime_device", lambda _: None)
    monkeypatch.setattr(owner, "root_owned_unit_processes", lambda _: state["pids"])
    monkeypatch.setattr(
        owner, "NumericalRuntimeFileSnapshots", observation.NumericalRuntimeFileSnapshots
    )
    return ready, terminal, state, tmp_path


def test_ack_intent_precedes_one_exact_main_signal_and_records_no_model_admission(lifetime):
    ready, _, state, tmp = lifetime
    result = owner.acknowledge_image_gpu_unit_ready(ready)
    assert result.ready == ready and result.acknowledged_at_utc.endswith("Z")
    assert state["rechecks"] == 2
    assert state["commands"] == [
        (
            "/usr/bin/systemctl",
            "--no-ask-password",
            "kill",
            "--kill-whom=main",
            "--signal=SIGUSR1",
            UNIT,
        )
    ]
    raw = (tmp / "ack" / "result.json").read_bytes()
    record = json.loads(raw)
    assert canonical_json_bytes(record) == raw and record["admission_granted"] is False
    adapter = TypeAdapter(owner.ImageGpuUnitAcknowledgement)
    Draft202012Validator(adapter.json_schema()).validate(record["observation"])
    assert adapter.validate_python(record["observation"]) == result


@pytest.mark.parametrize("phase", ("ack", "retirement"))
def test_existing_reservation_prevents_second_effect(lifetime, phase):
    ready, terminal, state, _ = lifetime
    action, value = (
        (owner.acknowledge_image_gpu_unit_ready, ready)
        if phase == "ack"
        else (owner.retire_image_gpu_unit, terminal)
    )
    action(value)
    count = len(state["commands"])
    with pytest.raises(FileExistsError):
        action(value)
    assert len(state["commands"]) == count


@pytest.mark.parametrize("phase", ("ack", "retirement"))
@pytest.mark.parametrize("fault", ("timeout", "os_error", "nonzero"))
def test_uncertain_effect_preserves_intent_without_success_or_automatic_retry(
    lifetime,
    monkeypatch,
    phase,
    fault,
):
    ready, terminal, state, tmp = lifetime
    calls = []

    def uncertain(args, **kwargs):
        calls.append(args)
        assert (tmp / phase / "intent.json").is_file()
        if fault == "timeout":
            raise owner.subprocess.TimeoutExpired(args, 10)
        if fault == "os_error":
            raise OSError("synthetic transport failure")
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(owner.subprocess, "run", uncertain)
    with pytest.raises(ValueError, match="EFFECT_UNCERTAIN"):
        if phase == "ack":
            owner.acknowledge_image_gpu_unit_ready(ready)
        else:
            owner.retire_image_gpu_unit(terminal)
    assert len(calls) == 1 and not (tmp / phase / "result.json").exists()
    assert state["events"] == []


@pytest.mark.parametrize("phase", ("ack", "retirement"))
def test_identity_drift_after_durable_intent_blocks_effect(lifetime, monkeypatch, phase):
    ready, terminal, state, tmp = lifetime
    if phase == "ack":

        def recheck(*args, **kwargs):
            state["rechecks"] += 1
            return ready if state["rechecks"] == 1 else replace(ready, pid=999)

        monkeypatch.setattr(owner, "observe_image_gpu_unit_ready", recheck)
    else:

        def recheck(*args, **kwargs):
            state["rechecks"] += 1
            return (
                terminal if state["rechecks"] == 1 else replace(terminal, original_outcome="FAILED")
            )

        monkeypatch.setattr(owner, "verify_image_gpu_unit_terminal", recheck)
    with pytest.raises(ValueError, match="IDENTITY_CHANGED"):
        if phase == "ack":
            owner.acknowledge_image_gpu_unit_ready(ready)
        else:
            owner.retire_image_gpu_unit(terminal)
    assert (tmp / phase / "intent.json").is_file() and state["commands"] == []


@pytest.mark.parametrize(
    "outcome,result", (("SUCCEEDED", "success"), ("FAILED", "exit-code"), ("FAILED", "timeout"))
)
def test_retirement_preserves_original_success_failure_timeout(lifetime, outcome, result):
    _, terminal, state, tmp = lifetime
    if outcome == "FAILED":
        ended = terminal.terminal_unit
        terminal = replace(
            terminal,
            original_outcome="FAILED",
            terminal_unit=replace(
                ended,
                status=replace(
                    ended.status,
                    active_state="failed",
                    sub_state="failed",
                    result=result,
                    exec_main_status=7,
                ),
            ),
        )
    state["terminal"] = terminal
    observation_result = owner.retire_image_gpu_unit(terminal)
    assert observation_result.original_terminal == terminal
    assert state["events"] == [
        "stop" if outcome == "SUCCEEDED" else "reset-failed",
        "hold",
        "close",
    ]
    record = json.loads((tmp / "retirement" / "intent.json").read_bytes())
    assert record["observation"]["original_outcome"] == outcome
    assert record["observation"]["terminal_unit"]["status"]["result"] == result
    assert (
        json.loads((tmp / "retirement" / "result.json").read_bytes())["admission_granted"] is False
    )


@pytest.mark.parametrize(
    "field,value",
    (
        ("LoadState", "error"),
        ("ActiveState", "failed"),
        ("SubState", "running"),
        ("MainPID", "123"),
        ("NFileDescriptorStore", "1"),
        ("InvocationID", "c" * 32),
        ("NeedDaemonReload", "yes"),
        ("DropInPaths", "/tmp/override.conf"),
        ("FragmentPath", "/tmp/other.service"),
    ),
)
def test_uncertain_post_state_keeps_original_intent_not_result(lifetime, field, value):
    _, terminal, state, tmp = lifetime
    state["changes"] = {field: value}
    with pytest.raises(ValueError, match="RETIREMENT_UNCERTAIN"):
        owner.retire_image_gpu_unit(terminal)
    assert (tmp / "retirement" / "intent.json").is_file()
    assert not (tmp / "retirement" / "result.json").exists()
    assert state["events"].count("stop") == 1


def test_collected_unit_is_allowed_without_losing_original_terminal(lifetime):
    _, terminal, state, _ = lifetime
    state["changes"] = {"LoadState": "not-found", "FragmentPath": ""}
    result = owner.retire_image_gpu_unit(terminal)
    assert result.retired_unit.load_state == "not-found" and result.original_terminal == terminal


@pytest.mark.parametrize("fault", ("gpu", "child", "lease", "source"))
def test_post_cleanup_failure_never_records_retirement_success(lifetime, monkeypatch, fault):
    _, terminal, state, tmp = lifetime
    if fault == "gpu":
        state["gpu_clients"] = (999,)
    elif fault == "child":
        state["pids"] = (999,)
    else:

        def rejected(*args, **kwargs):
            raise ValueError("synthetic cleanup rejection")

        monkeypatch.setattr(
            owner,
            "hold_released_image_unit_gpu_resources"
            if fault == "lease"
            else "NumericalRuntimeFileSnapshots",
            rejected,
        )
    with pytest.raises(ValueError):
        owner.retire_image_gpu_unit(terminal)
    assert (tmp / "retirement" / "intent.json").is_file()
    assert not (tmp / "retirement" / "result.json").exists()


def test_readonly_recovery_never_repeats_stop_or_reset(lifetime):
    _, terminal, state, _ = lifetime
    state["retired"] = True
    result = owner.observe_retired_image_gpu_unit(terminal)
    assert result.original_terminal == terminal and state["events"] == ["hold", "close"]
    assert all(args[1] == "show" for args in state["commands"])


@pytest.mark.parametrize("action", ("ack", "retire", "recover"))
def test_nonroot_cannot_signal_retire_or_use_recovery(lifetime, monkeypatch, action):
    ready, terminal, state, tmp = lifetime
    monkeypatch.setattr(owner.os, "getresuid", lambda: (984, 984, 984))
    with pytest.raises(ValueError, match="OWNER_REQUIRED"):
        if action == "ack":
            owner.acknowledge_image_gpu_unit_ready(ready)
        elif action == "retire":
            owner.retire_image_gpu_unit(terminal)
        else:
            owner.observe_retired_image_gpu_unit(terminal)
    assert state["commands"] == [] and list(tmp.iterdir()) == []


def test_real_record_no_clobber_and_partial_write_failure_remains_failed(lifetime, monkeypatch):
    ready, _, _, tmp_path = lifetime
    descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:

        def failed_write(*args):
            return 0

        monkeypatch.setattr(owner.os, "write", failed_write)
        with pytest.raises(ValueError, match="RECORD_WRITE_FAILED"):
            owner._save(descriptor, "intent.json", "SYNTHETIC", ready)
        assert (tmp_path / "intent.json").read_bytes() == b""
        with pytest.raises(FileExistsError):
            owner._save(descriptor, "intent.json", "SYNTHETIC", ready)
    finally:
        os.close(descriptor)


@pytest.fixture
def record_tree(image, monkeypatch, tmp_path):
    """Real temp directory/FD operations, synthetic root ownership/ancestor protection."""
    ready = observe(image)
    root = tmp_path / "lifetimes"
    original_lstat, original_stat, original_fstat = Path.lstat, os.stat, os.fstat

    def owned(value, *, ancestor=False):
        values = list(value)
        values[4] = 0
        if ancestor:
            values[0] &= ~0o022
        return os.stat_result(values)

    def lstat(path, *args, **kwargs):
        return owned(original_lstat(path, *args, **kwargs), ancestor=path in root.parents)

    monkeypatch.setattr(owner, "_ROOT", root)
    monkeypatch.setattr(owner.os, "getresuid", lambda: (0, 0, 0))
    monkeypatch.setattr(Path, "lstat", lstat)
    monkeypatch.setattr(owner.os, "fstat", lambda descriptor: owned(original_fstat(descriptor)))
    monkeypatch.setattr(
        owner.os, "stat", lambda *args, **kwargs: owned(original_stat(*args, **kwargs))
    )
    return ready, root


def test_phase_reservations_are_no_clobber_and_bound_to_original_unit_invocation(record_tree):
    ready, root = record_tree
    descriptor = owner._reserve(ready, "ack")
    try:
        expected = root / UNIT / ready.unit.invocation_id / "ack"
        assert os.readlink(f"/proc/self/fd/{descriptor}") == str(expected)
        assert stat.S_IMODE(expected.lstat().st_mode) == 0o700
    finally:
        os.close(descriptor)
    with pytest.raises(FileExistsError):
        owner._reserve(ready, "ack")
    descriptor = owner._reserve(ready, "retirement")
    os.close(descriptor)


def test_concurrent_phase_reservation_has_at_most_one_winner(record_tree):
    ready, root = record_tree
    parent = root / UNIT / ready.unit.invocation_id
    parent.mkdir(parents=True, mode=0o700)
    for path in (root, root / UNIT):
        path.chmod(0o700)
    barrier = Barrier(2)

    def reserve():
        barrier.wait(timeout=5)
        try:
            descriptor = owner._reserve(ready, "ack")
        except (FileExistsError, ValueError):
            return False
        os.close(descriptor)
        return True

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _: reserve(), range(2)))
    assert sum(results) == 1 and (parent / "ack").is_dir()


def test_readonly_recovery_rejects_original_outcome_relabeling(lifetime):
    _, terminal, state, _ = lifetime
    state["retired"] = True
    with pytest.raises(ValueError, match="IDENTITY_INVALID"):
        owner.observe_retired_image_gpu_unit(replace(terminal, original_outcome="FAILED"))
    assert state["commands"] == []


@pytest.mark.parametrize("phase", ("ack", "retirement"))
def test_result_record_failure_does_not_allow_effect_replay(lifetime, monkeypatch, phase):
    ready, terminal, state, tmp = lifetime
    original_save = owner._save

    def save(directory, name, event, observation):
        if name == "result.json":
            raise OSError("synthetic disk failure after effect")
        original_save(directory, name, event, observation)

    monkeypatch.setattr(owner, "_save", save)
    action, value = (
        (owner.acknowledge_image_gpu_unit_ready, ready)
        if phase == "ack"
        else (owner.retire_image_gpu_unit, terminal)
    )
    with pytest.raises(OSError, match="disk failure"):
        action(value)
    calls = len(state["commands"])
    assert (tmp / phase / "intent.json").is_file()
    assert not (tmp / phase / "result.json").exists()
    with pytest.raises(FileExistsError):
        action(value)
    assert len(state["commands"]) == calls


@pytest.mark.parametrize("phase", ("ack", "retirement"))
def test_failed_intent_record_does_not_submit_any_effect(lifetime, monkeypatch, phase):
    ready, terminal, state, _ = lifetime

    def failed_save(*args, **kwargs):
        raise OSError("synthetic disk failure before effect")

    monkeypatch.setattr(owner, "_save", failed_save)
    with pytest.raises(OSError, match="disk failure"):
        if phase == "ack":
            owner.acknowledge_image_gpu_unit_ready(ready)
        else:
            owner.retire_image_gpu_unit(terminal)
    assert state["commands"] == []


@pytest.mark.parametrize("failed", (False, True))
def test_no_lease_exit_retirement_never_touches_another_gpu_holder(lifetime, monkeypatch, failed):
    ready, terminal, state, tmp = lifetime
    ended = terminal.terminal_unit
    if failed:
        ended = replace(
            ended,
            status=replace(
                ended.status,
                active_state="failed",
                sub_state="failed",
                result="exit-code",
                exec_main_status=1,
            ),
        )
    unleased = observation.ImageGpuUnitUnleasedTerminalObservation(
        ready.unit_name,
        ready.template_sha256,
        ready.bootstrap_sha256,
        ready.effective_policy_sha256,
        ended,
        "FAILED" if failed else "SUCCEEDED",
        "2026-10-17T03:00:00Z",
    )
    reserve = owner._reserve

    def unleased_reserve(value, phase):
        assert value is unleased and phase == "retirement"
        return reserve(ready, phase)

    def forbidden(*args, **kwargs):
        pytest.fail("no-lease terminal must not release or inspect another GPU lease")

    monkeypatch.setattr(owner, "_reserve", unleased_reserve)
    monkeypatch.setattr(
        owner, "observe_unleased_image_gpu_unit_terminal", lambda *args, **kwargs: unleased
    )
    monkeypatch.setattr(owner, "hold_released_image_unit_gpu_resources", forbidden)
    monkeypatch.setattr(owner, "observe_runtime_device", forbidden)
    monkeypatch.setattr(owner, "observe_cuda_probe_gpu_clients", forbidden)
    result = owner.retire_unleased_image_gpu_unit(unleased)
    assert result.original_terminal == unleased
    assert state["events"] == ["reset-failed" if failed else "stop"]
    assert json.loads((tmp / "retirement" / "intent.json").read_bytes())["observation"][
        "original_outcome"
    ] == ("FAILED" if failed else "SUCCEEDED")
    state["commands"].clear()
    assert owner.observe_retired_unleased_image_gpu_unit(unleased).original_terminal == unleased
    assert all(args[1] == "show" for args in state["commands"])


@pytest.mark.parametrize("level", ("root", "unit", "invocation"))
def test_record_tree_rejects_symlink_and_writable_or_wrong_mode(record_tree, level):
    ready, root = record_tree
    paths = {
        "root": root,
        "unit": root / UNIT,
        "invocation": root / UNIT / ready.unit.invocation_id,
    }
    selected = paths[level]
    selected.mkdir(parents=True, mode=0o700)
    # mkdir(parents=True) follows ambient umask; secure each intermediate fixture explicitly.
    for path in (root, root / UNIT):
        if path.exists():
            path.chmod(0o700)
    selected.chmod(0o770 if level == "root" else 0o755)
    with pytest.raises(ValueError, match="RECORD_DIRECTORY_INVALID"):
        owner._reserve(ready, "ack")


@pytest.mark.parametrize("level", ("root", "unit", "invocation"))
def test_record_tree_never_follows_symlink(record_tree, level, tmp_path):
    ready, root = record_tree
    target = tmp_path / "other"
    target.mkdir(mode=0o700)
    selected = {
        "root": root,
        "unit": root / UNIT,
        "invocation": root / UNIT / ready.unit.invocation_id,
    }[level]
    selected.parent.mkdir(parents=True, exist_ok=True)
    for path in (root, root / UNIT):
        if path.exists():
            path.chmod(0o700)
    selected.symlink_to(target, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        owner._reserve(ready, "ack")
    assert list(target.iterdir()) == []


def test_record_save_never_follows_preexisting_symlink(lifetime):
    ready, _, _, tmp = lifetime
    original = tmp / "original"
    original.write_bytes(b"unchanged synthetic fixture")
    (tmp / "intent.json").symlink_to(original)
    descriptor = os.open(tmp, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(FileExistsError):
            owner._save(descriptor, "intent.json", "SYNTHETIC", ready)
    finally:
        os.close(descriptor)
    assert original.read_bytes() == b"unchanged synthetic fixture"
