"""Original terminal/cleanup over synthetic OS ports; no systemctl, unit or GPU effects."""

from __future__ import annotations

import json
import subprocess
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_service import embedding_gpu_batch_lifetime as lifetime
from eom_catalog_service import embedding_gpu_batch_observation as observer
from eom_catalog_service.gpu_unit_terminal_observation import StoppedGpuUnit
from eom_orchestrator.worker_systemd import FixedUnitStatus

from tests.unit.test_embedding_gpu_batch_observation import machine as machine
from tests.unit.test_embedding_native_probe_observation import process_stat


@pytest.fixture
def ending(machine, monkeypatch):
    captured = observer.capture_embedding_gpu_batch_machine(machine.prepared)
    ready = observer.observe_embedding_gpu_batch_ready(captured, machine.ready)
    terminal = replace(
        ready.unit,
        main_pid=0,
        exited_monotonic=200,
        status=FixedUnitStatus("loaded", "active", "exited", "success", 1, 0, 100, False),
    )
    state = SimpleNamespace(
        captured=captured,
        ready=ready,
        terminal=terminal,
        alive=False,
        pids=(),
        clients=(),
        retained=True,
        reserved=False,
        records=[],
        effects=[],
        closed=[],
        release=[],
        stopped=StoppedGpuUnit("loaded", ready.unit.invocation_id, 1),
        effect_fault=False,
        gpu_after_stop=False,
        no_store_after_stop=False,
    )
    lstat = Path.lstat

    def process(path, *args, **kwargs):
        if path == Path("/proc/123"):
            if state.alive:
                return SimpleNamespace(st_uid=1234)
            raise FileNotFoundError(path)
        return lstat(path, *args, **kwargs)

    def retained(value, *, unit):
        assert value is ready.resources and unit == machine.unit_name
        if not state.retained:
            raise ValueError("retained physical fence lost")
        return value

    @contextmanager
    def released(value, *, unit):
        assert value is ready.resources and unit == machine.unit_name
        assert state.stopped.stored_descriptors == 0
        state.release.append("hold-same-inode")
        try:
            yield
        finally:
            state.release.append("close-new-description")

    def reserve(root, unit, invocation, phase):
        assert (
            unit == machine.unit_name
            and invocation == ready.unit.invocation_id
            and phase == "retirement"
        )
        if state.reserved:
            raise FileExistsError("original phase already reserved")
        state.reserved = True
        return 901

    def record(fd, name, raw):
        assert fd == 901
        state.records.append((name, json.loads(raw)))

    def effect(action, unit):
        assert unit == machine.unit_name
        state.effects.append(action)
        if state.effect_fault:
            raise ValueError("effect result unknown")
        if action == "CLEAN_FDSTORE" or state.no_store_after_stop:
            state.stopped = replace(state.stopped, stored_descriptors=0)
        if state.gpu_after_stop:
            state.clients = (999,)

    monkeypatch.setattr(
        lifetime,
        "os",
        SimpleNamespace(getresuid=lambda: (0, 0, 0), close=lambda fd: state.closed.append(fd)),
    )
    monkeypatch.setattr(Path, "lstat", process)
    monkeypatch.setattr(lifetime, "inspect_cpu_unit", lambda *_a, **_kw: state.terminal)
    monkeypatch.setattr(
        lifetime,
        "read_live_runtime_os_file",
        lambda *_a, **_kw: process_stat(123, start=ready.readiness.start_time_ticks),
    )
    monkeypatch.setattr(lifetime, "root_owned_unit_processes", lambda _: state.pids)
    monkeypatch.setattr(lifetime, "observe_runtime_device", lambda _: None)
    monkeypatch.setattr(lifetime, "observe_cuda_probe_gpu_clients", lambda _: state.clients)
    monkeypatch.setattr(lifetime, "observe_embedding_gpu_batch_retained_resources", retained)
    monkeypatch.setattr(
        lifetime, "observe_embedding_gpu_batch_unit_policy", lambda _: ready.effective_policy_sha256
    )
    monkeypatch.setattr(lifetime, "observe_stopped_gpu_unit", lambda *_a, **_kw: state.stopped)
    monkeypatch.setattr(lifetime, "hold_released_embedding_gpu_batch_resources", released)
    monkeypatch.setattr(lifetime, "reserve_unit_effect_phase", reserve)
    monkeypatch.setattr(lifetime, "write_unit_effect_record", record)
    monkeypatch.setattr(lifetime, "apply_embedding_gpu_batch_effect", effect)
    return state


@pytest.mark.parametrize("outcome", ["SUCCEEDED", "FAILED"])
@pytest.mark.parametrize("no_store", [False, True])
def test_terminal_retirement_preserves_outcome_and_proves_same_inode_release(
    ending, outcome, no_store
):
    if outcome == "FAILED":
        ending.terminal = replace(
            ending.terminal,
            status=FixedUnitStatus("loaded", "failed", "failed", "exit-code", 1, 1, 100, False),
        )
    ending.no_store_after_stop = no_store
    terminal = lifetime.observe_embedding_gpu_batch_terminal(ending.ready, ending.captured)
    assert terminal.original_outcome == outcome
    result = lifetime.retire_embedding_gpu_batch(terminal, ending.captured)
    assert result.original_terminal == terminal and result.retired_unit.stored_descriptors == 0
    assert ending.effects == (["STOP"] if outcome == "SUCCEEDED" else ["RESET_FAILED"]) + (
        [] if no_store else ["CLEAN_FDSTORE"]
    )
    assert [name for name, _ in ending.records] == ["intent.json", "result.json"]
    assert ending.records[-1][1]["observation"]["original_terminal"]["original_outcome"] == outcome
    assert ending.release == ["hold-same-inode", "close-new-description"]
    assert ending.closed == [901]


@pytest.mark.parametrize(
    "fault",
    ["root", "invocation", "start", "alive", "pids", "GPU", "retained", "files", "copied_outcome"],
)
def test_foreign_or_unfinished_work_cannot_reserve_cleanup_or_change_history(
    ending, monkeypatch, fault
):
    original = lifetime.observe_embedding_gpu_batch_terminal(ending.ready, ending.captured)
    terminal = original
    if fault == "root":
        monkeypatch.setattr(lifetime.os, "getresuid", lambda: (0, 1234, 0))
    elif fault == "invocation":
        ending.terminal = replace(ending.terminal, invocation_id="c" * 32)
    elif fault == "start":
        ending.terminal = replace(
            ending.terminal, status=replace(ending.terminal.status, exec_main_started_monotonic=101)
        )
    elif fault == "alive":
        ending.alive = True
    elif fault == "pids":
        ending.pids = (124,)
    elif fault == "GPU":
        ending.clients = (123,)
    elif fault == "retained":
        ending.retained = False
    elif fault == "files":
        ending.captured.files.assert_unchanged = lambda: (_ for _ in ()).throw(
            ValueError("file drift")
        )
    else:
        terminal = replace(original, original_outcome="FAILED")
    with pytest.raises(ValueError):
        lifetime.retire_embedding_gpu_batch(terminal, ending.captured)
    assert not ending.effects and not ending.records and not ending.reserved


def test_other_gpu_client_after_stop_never_grants_fdstore_cleanup(ending):
    terminal = lifetime.observe_embedding_gpu_batch_terminal(ending.ready, ending.captured)
    ending.gpu_after_stop = True
    with pytest.raises(ValueError):
        lifetime.retire_embedding_gpu_batch(terminal, ending.captured)
    assert ending.effects == ["STOP"] and [name for name, _ in ending.records] == ["intent.json"]
    assert ending.closed == [901] and not ending.release


def test_uncertain_effect_is_not_repeated_and_readonly_reconcile_has_no_mutation(ending):
    terminal = lifetime.observe_embedding_gpu_batch_terminal(ending.ready, ending.captured)
    ending.effect_fault = True
    with pytest.raises(ValueError):
        lifetime.retire_embedding_gpu_batch(terminal, ending.captured)
    assert ending.effects == ["STOP"] and len(ending.records) == 1
    with pytest.raises(FileExistsError):
        lifetime.retire_embedding_gpu_batch(terminal, ending.captured)
    assert ending.effects == ["STOP"] and len(ending.records) == 1
    ending.stopped = replace(ending.stopped, stored_descriptors=0)
    restored = lifetime.observe_retired_embedding_gpu_batch(terminal, ending.captured)
    assert restored.original_terminal == terminal and ending.effects == ["STOP"]
    assert len(ending.records) == 1  # observation is not a forged successful effect record


@pytest.mark.parametrize("fault", [None, "unit", "action", "timeout", "code", "large"])
def test_effect_dispatch_is_closed_bounded_and_never_accepts_arbitrary_units(monkeypatch, fault):
    unit, action = "eom-embedding-native-gpu-batch@" + "a" * 32 + ".service", "STOP"
    calls = []

    def run(arguments, **kwargs):
        calls.append(arguments)
        assert kwargs["timeout"] == 10 and kwargs["env"] == {
            "PATH": "/usr/bin:/bin",
            "TZ": "UTC",
            "LANG": "C.UTF-8",
        }
        if fault == "timeout":
            raise subprocess.TimeoutExpired(arguments, 10)
        return SimpleNamespace(
            returncode=1 if fault == "code" else 0,
            stdout=b"x" * 16385 if fault == "large" else b"",
            stderr=b"",
        )

    monkeypatch.setattr(lifetime, "os", SimpleNamespace(getresuid=lambda: (0, 0, 0)))
    monkeypatch.setattr(
        lifetime, "subprocess", SimpleNamespace(run=run, TimeoutExpired=subprocess.TimeoutExpired)
    )
    if fault == "unit":
        unit = "eom-embedding-native-cuda-index@" + "a" * 32 + ".service"
    elif fault == "action":
        action = "START"
    if fault is None:
        lifetime.apply_embedding_gpu_batch_effect(action, unit)
    else:
        with pytest.raises(ValueError):
            lifetime.apply_embedding_gpu_batch_effect(action, unit)
    assert len(calls) == (0 if fault in ("unit", "action") else 1)
