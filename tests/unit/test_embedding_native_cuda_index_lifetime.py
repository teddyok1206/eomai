"""Synthetic original-unit root ports with real local records; no root signal, GPU or model."""

from __future__ import annotations

import ast
import json
import os
import stat
import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_service import embedding_native_cuda_index_lifetime as owner
from eom_catalog_service.embedding_cuda_probe_resource_observation import (
    CudaProbeResourceObservation,
)
from eom_catalog_service.unit_effect_records import write_unit_effect_record
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.worker_systemd import FixedUnitStatus
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter

from tests.unit.embedding_installed_runtime_fixtures import runtime_proof
from tests.unit.test_embedding_cuda_nvml_admission import metadata
from tests.unit.test_embedding_native_probe_observation import running, terminal


@pytest.fixture
def lifetime(tmp_path, monkeypatch):
    unit_name = owner.CUDA_INDEX_TEMPLATE.replace("@.service", "@" + "a" * 32 + ".service")
    unit = replace(running(), fragment_path="/etc/systemd/system/" + owner.CUDA_INDEX_TEMPLATE)
    receipt = metadata()["receipt"]
    ready = owner.NativeCudaIndexReadyObservation(
        "a" * 32,
        "job_" + "c" * 32,
        unit,
        123,
        987,
        "/system.slice/" + unit_name,
        "sha256:" + "1" * 64,
        "sha256:" + "2" * 64,
        "sha256:" + "3" * 64,
        (1, 2, 0, 1000, stat.S_IFREG | 0o640, 1, 1000, 2, 3),
        "sha256:" + "4" * 64,
        "sha256:" + "5" * 64,
        "sha256:" + "6" * 64,
        (),
        CudaProbeResourceObservation(receipt.device_nodes, receipt.shared_gpu_lease, 80),
        runtime_proof("CUDA_INDEX_FP32").device_capture,
    )
    ended = replace(terminal(), fragment_path=unit.fragment_path)
    original = owner.NativeCudaIndexTerminalObservation(
        ready, ended, "SUCCEEDED", "2026-10-18T12:00:00Z"
    )
    captured = object.__new__(owner.CapturedNativeCudaIndexLaunchFiles)
    state = SimpleNamespace(
        ready=ready,
        terminal=original,
        captured=captured,
        unit=unit_name,
        root=tmp_path,
        commands=[],
        events=[],
        rechecks=0,
        terminal_rechecks=0,
        fault=None,
        retired=False,
        store=1,
        held=False,
        directories=[],
    )

    def capture_current(self):
        assert self is captured
        state.events.append("capture")
        if state.fault == "capture":
            raise ValueError("synthetic pinned file drift")

    def basis(actual_ready, actual_captured):
        assert actual_captured is captured
        if state.fault == "basis":
            raise ValueError("synthetic wrong original basis")
        assert actual_ready.execution_id == ready.execution_id
        return unit_name

    def fresh(actual_captured):
        assert actual_captured is captured
        state.rechecks += 1
        if state.fault == "initial_frame" or (state.fault == "late_frame" and state.rechecks == 2):
            return replace(ready, pid=ready.pid + 1)
        return ready

    def terminal_current(actual_ready, actual_captured):
        assert actual_ready == ready and actual_captured is captured
        state.terminal_rechecks += 1
        if state.fault == "late_terminal" and state.terminal_rechecks == 2:
            return replace(state.terminal, terminal_unit=replace(ended, invocation_id="f" * 32))
        return state.terminal

    def reserve(root, name, invocation, phase):
        assert root == owner._ROOT and name == unit_name and invocation == ready.unit.invocation_id
        directory = tmp_path / phase
        directory.mkdir(mode=0o700)
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        state.directories.append(fd)
        return fd

    def command(arguments, **kwargs):
        assert arguments[:2] == ("/usr/bin/systemctl", "--no-ask-password")
        assert arguments[-1] == unit_name
        assert kwargs == dict(capture_output=True, check=False, timeout=10, env=owner._ENV)
        action = arguments[2]
        phase = "ack" if action == "kill" else "retirement"
        assert (tmp_path / phase / "intent.json").is_file()
        assert not (tmp_path / phase / "result.json").exists()
        if action == "kill":
            assert arguments[3:-1] == ("--kill-whom=main", "--signal=SIGUSR1")
            assert state.rechecks >= 2
        elif action == "clean":
            assert arguments[3:-1] == ("--what=fdstore",) and state.retired and state.store == 1
        state.commands.append(arguments)
        state.events.append(action)
        if state.fault in {"timeout", "oserror"} or (
            state.fault == "clean_timeout" and action == "clean"
        ):
            if state.fault == "oserror":
                raise OSError("synthetic uncertain effect")
            raise subprocess.TimeoutExpired(arguments, 10)
        if action in {"stop", "reset-failed"}:
            state.retired = True
        elif action == "clean":
            state.store = 0
        return SimpleNamespace(
            returncode=1 if state.fault == "exit" else 0,
            stdout=b"x" * 16385 if state.fault == "output" else b"",
            stderr=b"",
        )

    def stopped(name, *, template, invocation):
        assert name == unit_name and template == owner.CUDA_INDEX_TEMPLATE
        assert invocation == ready.unit.invocation_id and state.retired
        state.events.append("stopped")
        return owner.StoppedGpuUnit("loaded", invocation, state.store)

    def processes(actual):
        assert actual is ready
        state.events.append("ended")
        if state.fault == "old_pid":
            raise ValueError("synthetic old process still alive")

    def device(actual):
        assert actual is ready.device
        state.events.append("device")

    def clients(actual):
        assert actual is ready.device and (state.held or state.retired)
        state.events.append("clients")
        return ("synthetic busy GPU",) if state.fault == "gpu_busy" else ()

    def retained(resources, *, unit):
        assert resources is ready.resources and unit == unit_name and state.store == 1
        state.events.append("retained")
        if state.fault == "lost_retention":
            raise ValueError("synthetic lost original PID1 lock")
        return resources

    @contextmanager
    def released(resources, *, unit):
        assert resources is ready.resources and unit == unit_name and state.store == 0
        if state.fault == "still_locked":
            raise ValueError("synthetic same inode remains locked")
        state.events.append("hold")
        state.held = True
        try:
            yield
        finally:
            state.held = False
            state.events.append("close-hold")

    monkeypatch.setattr(owner.os, "getresuid", lambda: (0, 0, 0))
    monkeypatch.setattr(owner.CapturedNativeCudaIndexLaunchFiles, "assert_current", capture_current)
    monkeypatch.setattr(owner, "require_native_cuda_index_observation_basis", basis)
    monkeypatch.setattr(owner, "observe_native_cuda_index_ready", fresh)
    monkeypatch.setattr(owner, "verify_native_cuda_index_terminal", terminal_current)
    monkeypatch.setattr(owner, "reserve_unit_effect_phase", reserve)
    monkeypatch.setattr(
        owner, "subprocess", SimpleNamespace(run=command, TimeoutExpired=subprocess.TimeoutExpired)
    )
    monkeypatch.setattr(owner, "observe_stopped_gpu_unit", stopped)
    monkeypatch.setattr(owner, "require_native_cuda_index_processes_ended", processes)
    monkeypatch.setattr(owner, "observe_runtime_device", device)
    monkeypatch.setattr(owner, "observe_cuda_probe_gpu_clients", clients)
    monkeypatch.setattr(owner, "observe_native_cuda_index_retained_resources", retained)
    monkeypatch.setattr(owner, "hold_released_native_cuda_index_resources", released)
    return state


def ack(state):
    return owner.acknowledge_native_cuda_index_ready(state.ready, state.captured)


def retire(state):
    return owner.retire_native_cuda_index_unit(state.terminal, state.captured)


def test_ack_records_canonical_metadata_before_one_exact_original_main_signal(lifetime):
    result = ack(lifetime)
    assert result.ready == lifetime.ready and result.acknowledged_at_utc.endswith("Z")
    assert lifetime.rechecks == 2 and len(lifetime.commands) == 1
    for name, model in (("intent.json", type(lifetime.ready)), ("result.json", type(result))):
        raw = (lifetime.root / "ack" / name).read_bytes()
        record = json.loads(raw)
        assert canonical_json_bytes(record) == raw and record["admission_granted"] is False
        assert len(raw) <= 256 * 1024 and "request" not in record["observation"]
        Draft202012Validator(TypeAdapter(model).json_schema()).validate(record["observation"])
        assert stat.S_IMODE((lifetime.root / "ack" / name).stat().st_mode) == 0o400
    with pytest.raises(FrozenInstanceError):
        result.acknowledged_at_utc = "changed"
    with pytest.raises(ValueError, match="ALREADY_RESERVED"):
        ack(lifetime)
    assert len(lifetime.commands) == 1


@pytest.mark.parametrize(
    "fault", ["initial_frame", "late_frame", "timeout", "oserror", "exit", "output"]
)
def test_changed_or_uncertain_ack_never_replays(lifetime, fault):
    lifetime.fault = fault
    with pytest.raises(ValueError):
        ack(lifetime)
    assert len(lifetime.commands) == (0 if fault in {"initial_frame", "late_frame"} else 1)
    assert (lifetime.root / "ack/intent.json").exists() == (fault != "initial_frame")
    assert not (lifetime.root / "ack/result.json").exists()
    if fault != "initial_frame":
        lifetime.fault = None
        before = tuple(lifetime.commands)
        with pytest.raises(ValueError, match="ALREADY_RESERVED"):
            ack(lifetime)
        assert tuple(lifetime.commands) == before


@pytest.mark.parametrize("phase", ["ack", "retirement"])
@pytest.mark.parametrize("member", ["intent.json", "result.json"])
def test_partial_record_write_never_permits_effect_replay(lifetime, monkeypatch, phase, member):
    def uncertain(directory, name, raw):
        if name == member:
            write_unit_effect_record(directory, name, raw[:5])
            raise OSError("synthetic partial original record")
        write_unit_effect_record(directory, name, raw)

    monkeypatch.setattr(owner, "write_unit_effect_record", uncertain)
    action = ack if phase == "ack" else retire
    with pytest.raises(ValueError, match="RECORD_UNCERTAIN"):
        action(lifetime)
    assert len((lifetime.root / phase / member).read_bytes()) == 5
    previous = tuple(lifetime.commands)
    with pytest.raises(ValueError, match="ALREADY_RESERVED"):
        action(lifetime)
    assert tuple(lifetime.commands) == previous


@pytest.mark.parametrize("action", ["ack", "retire", "observe"])
def test_nonroot_or_missing_ready_never_effects_or_borrows_another_family(
    lifetime, monkeypatch, action
):
    call = {
        "ack": lambda: ack(lifetime),
        "retire": lambda: retire(lifetime),
        "observe": lambda: owner.observe_retired_native_cuda_index_unit(
            lifetime.terminal, lifetime.captured
        ),
    }[action]
    monkeypatch.setattr(owner.os, "getresuid", lambda: (0, 1000, 0))
    with pytest.raises(ValueError, match="ROOT_REQUIRED"):
        call()
    assert not lifetime.commands and not tuple(lifetime.root.iterdir())


def test_concurrent_same_original_ack_has_one_effect_winner(lifetime):
    def attempt(_):
        try:
            return ack(lifetime)
        except ValueError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(attempt, range(2)))
    assert sum(isinstance(value, owner.NativeCudaIndexAcknowledgement) for value in results) == 1
    assert len(lifetime.commands) == 1


@pytest.mark.parametrize("outcome", ["SUCCEEDED", "exit-code", "signal", "timeout", "oom-kill"])
def test_retirement_preserves_original_outcome_and_cleans_store_once(lifetime, outcome):
    if outcome != "SUCCEEDED":
        ended = replace(
            lifetime.terminal.terminal_unit,
            status=FixedUnitStatus("loaded", "failed", "failed", outcome, 1, 1, 100, False),
        )
        lifetime.terminal = replace(
            lifetime.terminal, terminal_unit=ended, original_outcome="FAILED"
        )
    original = lifetime.terminal
    result = retire(lifetime)
    assert result.original_terminal is original and result.retired_unit.stored_descriptors == 0
    assert result.observed_at_utc.endswith("Z") and lifetime.terminal_rechecks == 2
    actions = [command[2] for command in lifetime.commands]
    assert actions == ["stop" if outcome == "SUCCEEDED" else "reset-failed", "clean"]
    assert (
        lifetime.events.index("retained")
        < lifetime.events.index("clean")
        < lifetime.events.index("hold")
    )
    record = json.loads((lifetime.root / "retirement/result.json").read_bytes())
    assert record["admission_granted"] is False
    assert (
        record["observation"]["original_terminal"]["original_outcome"] == original.original_outcome
    )
    with pytest.raises(ValueError, match="ALREADY_RESERVED"):
        retire(lifetime)
    assert len(lifetime.commands) == 2


@pytest.mark.parametrize(
    "fault",
    ["late_terminal", "old_pid", "lost_retention", "gpu_busy", "clean_timeout", "still_locked"],
)
def test_uncertain_retirement_preserves_intent_and_never_claims_completion(lifetime, fault):
    lifetime.fault = fault
    with pytest.raises(ValueError):
        retire(lifetime)
    assert (lifetime.root / "retirement/intent.json").exists()
    assert not (lifetime.root / "retirement/result.json").exists()
    previous = tuple(lifetime.commands)
    lifetime.fault = None
    with pytest.raises(ValueError, match="ALREADY_RESERVED"):
        retire(lifetime)
    assert tuple(lifetime.commands) == previous


def test_readonly_recovery_never_effects_and_ignores_dead_owner_expired_compute(lifetime):
    # No active-owner/deadline fields are supplied on this captured test object at all.
    lifetime.retired, lifetime.store = True, 0
    result = owner.observe_retired_native_cuda_index_unit(lifetime.terminal, lifetime.captured)
    assert result.original_terminal == lifetime.terminal and not lifetime.commands
    assert not tuple(lifetime.root.iterdir()) and lifetime.events.count("ended") == 2


def test_readonly_recovery_with_retained_store_is_not_implicit_clean(lifetime):
    lifetime.retired = True
    with pytest.raises(ValueError, match="RETIREMENT_UNCERTAIN"):
        owner.observe_retired_native_cuda_index_unit(lifetime.terminal, lifetime.captured)
    assert not lifetime.commands and "hold" not in lifetime.events


@pytest.mark.parametrize(
    "fault", ["outcome", "invocation", "start", "missing_ready", "basis", "capture"]
)
def test_wrong_original_terminal_or_before_ready_is_not_reinterpreted(lifetime, fault):
    if fault == "outcome":
        lifetime.terminal = replace(lifetime.terminal, original_outcome="FAILED")
    elif fault == "invocation":
        lifetime.terminal = replace(
            lifetime.terminal,
            terminal_unit=replace(lifetime.terminal.terminal_unit, invocation_id="f" * 32),
        )
    elif fault == "start":
        lifetime.terminal = replace(
            lifetime.terminal,
            terminal_unit=replace(
                lifetime.terminal.terminal_unit,
                status=replace(
                    lifetime.terminal.terminal_unit.status, exec_main_started_monotonic=101
                ),
            ),
        )
    elif fault == "missing_ready":
        lifetime.terminal = replace(lifetime.terminal, ready=None)
    else:
        lifetime.fault = fault
    with pytest.raises(ValueError):
        retire(lifetime)
    assert not lifetime.commands and not tuple(lifetime.root.iterdir())


def test_lifetime_has_only_closed_index_effects_no_source_model_or_benchmark_authority():
    source = Path(owner.__file__).read_text()
    modules = [
        node.module or ""
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
    ]
    assert not any("benchmark" in module for module in modules)
    assert not any(
        module.startswith(("torch", "transformers", "sqlalchemy", "eom_workflow"))
        for module in modules
    )
    assert "FDSTOREREMOVE" not in source and "LOCK_UN" not in source
    assert "time.monotonic" not in source and "owner_pid" not in source
    assert str(owner._ROOT) == "/opt/eom/embedding-native-cuda-index-lifetimes"
