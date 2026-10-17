"""Synthetic systemd/driver ports with real no-replay IO; no actual GPU effects."""

import json
import os
import subprocess
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
from eom_catalog_service import embedding_benchmark_cuda_lifetime as owner
from eom_catalog_service.embedding_benchmark_cuda_observation import verify_benchmark_cuda_terminal
from eom_catalog_service.gpu_unit_terminal_observation import StoppedGpuUnit
from eom_catalog_service.unit_effect_records import write_unit_effect_record

from tests.unit.test_embedding_benchmark_cuda_observation import benchmark as benchmark
from tests.unit.test_embedding_benchmark_cuda_terminal import ended as ended
from tests.unit.test_embedding_native_probe_observation import ledger as ledger


@pytest.fixture
def retirement(ended, tmp_path, monkeypatch):
    source = ended
    terminal = verify_benchmark_cuda_terminal(
        source.observed_ready,
        source.invocation,
        source.environment,
        backend=source.backend,
        inventory=source.inventory,
        host=source.host,
    )
    state = SimpleNamespace(
        source=source,
        terminal=terminal,
        root=tmp_path,
        calls=[],
        rechecks=0,
        fault=None,
        stored=1,
        stopped=False,
        held=False,
        directory=None,
    )

    def verify(ready, invocation, environment, **kwargs):
        assert ready is source.observed_ready
        assert invocation is source.invocation and environment is source.environment
        assert kwargs == dict(backend=source.backend, inventory=source.inventory, host=source.host)
        state.rechecks += 1
        if state.fault == "initial_frame" or (state.fault == "late_frame" and state.rechecks == 2):
            return replace(state.terminal, original_outcome="FAILED")
        return state.terminal

    def reserve(root, unit, invocation, phase):
        assert root == owner._ROOT and unit == source.unit_name
        assert invocation == terminal.ready.unit.invocation_id and phase == "retirement"
        directory = tmp_path / phase
        directory.mkdir(mode=0o700)
        state.directory = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        return state.directory

    def stopped(unit, **kwargs):
        assert unit == source.unit_name and state.stopped
        assert kwargs == dict(
            template=owner.CUDA_BENCHMARK_TEMPLATE, invocation=terminal.ready.unit.invocation_id
        )
        return StoppedGpuUnit("loaded", terminal.ready.unit.invocation_id, state.stored)

    def retained(resources, *, unit):
        assert resources == terminal.ready.resources and unit == source.unit_name
        assert state.stopped and state.stored == 1
        if state.fault == "retained":
            raise ValueError("synthetic retained descriptor changed")
        return resources

    def clients(device):
        assert device == terminal.ready.device
        return (123,) if state.fault == "gpu" else ()

    def device(identity):
        assert identity == terminal.ready.device
        if state.fault == "device":
            raise ValueError("synthetic device identity changed")
        return identity

    def ended_processes(ready):
        assert ready is terminal.ready
        if state.fault == "child":
            raise ValueError("synthetic remaining child")

    @contextmanager
    def released(resources):
        assert resources == terminal.ready.resources and state.stopped and state.stored == 0
        if state.fault == "lease_busy":
            raise ValueError("synthetic same-inode lease still busy")
        state.held = True
        try:
            yield
        finally:
            state.held = False

    def effect(arguments, **kwargs):
        assert arguments[:2] == ("/usr/bin/systemctl", "--no-ask-password")
        assert arguments[-1] == source.unit_name
        assert kwargs == dict(capture_output=True, check=False, timeout=10, env=owner._ENV)
        action = arguments[2:-1]
        assert action in {("stop",), ("reset-failed",), ("clean", "--what=fdstore")}
        record = json.loads((tmp_path / "retirement/intent.json").read_bytes())
        assert record["event"] == "BENCHMARK_CUDA_RETIREMENT_INTENT"
        assert record["admission_granted"] is False and state.rechecks == 2
        assert not (tmp_path / "retirement/result.json").exists()
        state.calls.append(action)
        clean = action[0] == "clean"
        if state.fault == ("clean_before" if clean else "stop_before"):
            raise subprocess.TimeoutExpired(arguments, 10)
        if clean:
            assert state.stopped and state.stored == 1
            state.stored = 0
        else:
            assert not state.stopped
            state.stopped = True
        if state.fault == ("clean_after" if clean else "stop_after"):
            raise subprocess.TimeoutExpired(arguments, 10)
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(owner, "verify_benchmark_cuda_terminal", verify)
    monkeypatch.setattr(owner, "reserve_unit_effect_phase", reserve)
    monkeypatch.setattr(owner, "observe_stopped_gpu_unit", stopped)
    monkeypatch.setattr(owner, "observe_benchmark_cuda_retained_resources", retained)
    monkeypatch.setattr(owner, "observe_cuda_probe_gpu_clients", clients)
    monkeypatch.setattr(owner, "observe_runtime_device", device)
    monkeypatch.setattr(owner, "require_benchmark_cuda_processes_ended", ended_processes)
    monkeypatch.setattr(owner, "hold_released_cuda_probe_resources", released)
    monkeypatch.setattr(
        owner, "subprocess", SimpleNamespace(run=effect, TimeoutExpired=subprocess.TimeoutExpired)
    )
    return state


def invoke(state, *, readonly=False):
    source = state.source
    function = (
        owner.observe_retired_benchmark_cuda_unit if readonly else owner.retire_benchmark_cuda_unit
    )
    return function(
        state.terminal,
        source.invocation,
        source.environment,
        backend=source.backend,
        inventory=source.inventory,
        host=source.host,
    )


@pytest.mark.parametrize("outcome", ("success", "failed", "timeout"))
@pytest.mark.parametrize("stored", (0, 1))
def test_cleanup_preserves_original_outcome_and_only_releases_original_store(
    retirement, outcome, stored
):
    state = retirement
    state.stored = stored
    if outcome != "success":
        unit = state.terminal.terminal_unit
        state.terminal = replace(
            state.terminal,
            original_outcome="FAILED",
            terminal_unit=replace(
                unit,
                status=replace(
                    unit.status,
                    active_state="failed",
                    sub_state="failed",
                    result="timeout" if outcome == "timeout" else "exit-code",
                    exec_main_status=1,
                ),
            ),
        )
    result = invoke(state)
    assert result.original_terminal is state.terminal
    assert result.retired_unit.stored_descriptors == 0 and not state.held
    assert state.calls == [("stop" if outcome == "success" else "reset-failed",)] + (
        [("clean", "--what=fdstore")] if stored else []
    )
    record = json.loads((state.root / "retirement/result.json").read_bytes())
    assert record["event"] == "BENCHMARK_CUDA_RETIRED_NOT_ADMITTED"
    assert (
        record["observation"]["original_terminal"]["original_outcome"]
        == state.terminal.original_outcome
    )
    assert record["admission_granted"] is False
    with pytest.raises(OSError):
        os.fstat(state.directory)


@pytest.mark.parametrize(
    "fault",
    (
        "initial_frame",
        "late_frame",
        "stop_before",
        "stop_after",
        "clean_before",
        "clean_after",
        "gpu",
        "retained",
        "child",
        "lease_busy",
        "device",
    ),
)
def test_uncertain_cleanup_preserves_intent_and_never_replays(retirement, fault):
    state = retirement
    state.fault = fault
    expected = {
        "initial_frame": "IDENTITY_CHANGED",
        "late_frame": "IDENTITY_CHANGED",
        "stop_before": "EFFECT_UNCERTAIN",
        "stop_after": "EFFECT_UNCERTAIN",
        "clean_before": "EFFECT_UNCERTAIN",
        "clean_after": "EFFECT_UNCERTAIN",
        "gpu": "RETIREMENT_UNCERTAIN",
        "retained": "synthetic retained descriptor changed",
        "child": "synthetic remaining child",
        "lease_busy": "synthetic same-inode lease still busy",
        "device": "synthetic device identity changed",
    }[fault]
    with pytest.raises(ValueError, match=expected):
        invoke(state)
    assert not (state.root / "retirement/result.json").exists()
    assert (state.root / "retirement/intent.json").exists() == (fault != "initial_frame")
    if fault != "initial_frame":
        calls = tuple(state.calls)
        state.fault = None
        with pytest.raises(ValueError, match="ALREADY_RESERVED"):
            invoke(state)
        assert tuple(state.calls) == calls


@pytest.mark.parametrize("name", ("intent.json", "result.json"))
def test_uncertain_record_is_not_overwritten_or_retried(retirement, monkeypatch, name):
    state = retirement

    def uncertain(directory, member, raw):
        if member == name:
            write_unit_effect_record(directory, member, raw[:5])
            raise OSError("synthetic uncertain record")
        write_unit_effect_record(directory, member, raw)

    monkeypatch.setattr(owner, "write_unit_effect_record", uncertain)
    with pytest.raises(ValueError, match="RECORD_UNCERTAIN"):
        invoke(state)
    calls = tuple(state.calls)
    assert len(calls) == (0 if name == "intent.json" else 2)
    assert len((state.root / "retirement" / name).read_bytes()) == 5
    with pytest.raises(ValueError, match="ALREADY_RESERVED"):
        invoke(state)
    assert tuple(state.calls) == calls


def test_readonly_reconciliation_proves_release_without_replaying_uncertain_clean(retirement):
    state = retirement
    state.fault = "clean_after"
    with pytest.raises(ValueError, match="EFFECT_UNCERTAIN"):
        invoke(state)
    calls = tuple(state.calls)
    state.fault = None
    result = invoke(state, readonly=True)
    assert (
        result.original_terminal is state.terminal and result.retired_unit.stored_descriptors == 0
    )
    assert tuple(state.calls) == calls
    assert not (state.root / "retirement/result.json").exists()


def test_readonly_reconciliation_does_not_clean_retained_store(retirement):
    state = retirement
    state.stopped = True
    with pytest.raises(ValueError, match="RETIREMENT_UNCERTAIN"):
        invoke(state, readonly=True)
    assert not state.calls and not tuple(state.root.iterdir())


@pytest.mark.parametrize("readonly", (False, True))
def test_nonroot_never_changes_or_recovers_unit(retirement, monkeypatch, readonly):
    monkeypatch.setattr(owner.os, "getresuid", lambda: (1000,) * 3)
    with pytest.raises(ValueError, match="ROOT_REQUIRED"):
        invoke(retirement, readonly=readonly)
    assert not retirement.calls and not tuple(retirement.root.iterdir())


def test_retirement_calls_real_benchmark_family_guard_not_probe_only_reader(
    retirement, monkeypatch
):
    from eom_catalog_service import embedding_cuda_probe_resource_observation as resources

    calls = []

    def retained(observed, unit):
        assert (
            observed == retirement.terminal.ready.resources and unit == retirement.source.unit_name
        )
        calls.append(unit)

    monkeypatch.setattr(resources, "_assert_retained_resources", retained)
    monkeypatch.setattr(
        owner,
        "observe_benchmark_cuda_retained_resources",
        resources.observe_benchmark_cuda_retained_resources,
    )
    assert invoke(retirement).retired_unit.stored_descriptors == 0
    assert calls == [retirement.source.unit_name]
