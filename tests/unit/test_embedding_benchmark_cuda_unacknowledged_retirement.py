"""Real audit IO and pre-ACK checks; synthetic unit/physical OS ports, no real GPU."""

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from eom_catalog_service import embedding_benchmark_cuda_lifetime as owner
from eom_catalog_service import embedding_benchmark_cuda_unacknowledged as observation
from eom_catalog_service.gpu_unit_terminal_observation import StoppedGpuUnit
from eom_catalog_service.unit_effect_records import write_unit_effect_record
from eom_identifiers import canonical_json_bytes
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter

from tests.unit.test_embedding_benchmark_cuda_observation import benchmark as benchmark
from tests.unit.test_embedding_benchmark_cuda_unacknowledged import observe
from tests.unit.test_embedding_benchmark_cuda_unacknowledged import unacknowledged as unacknowledged
from tests.unit.test_embedding_native_probe_observation import ledger as ledger


@pytest.fixture
def recovery(unacknowledged, tmp_path, monkeypatch):
    state = unacknowledged
    state.root = tmp_path
    state.calls = []
    state.effect_fault = None
    state.stopped = False
    state.held = False
    state.directory = None

    def reserve(root, unit, invocation, phase):
        assert root == owner._ROOT and unit == state.unit_name and phase == "retirement"
        assert invocation == state.expected_terminal.invocation_id
        path = tmp_path / phase
        path.mkdir(mode=0o700)
        state.directory = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        return state.directory

    def stopped(unit, **kwargs):
        assert state.stopped and unit == state.unit_name
        assert kwargs == dict(
            template=owner.CUDA_BENCHMARK_TEMPLATE, invocation=state.expected_terminal.invocation_id
        )
        return StoppedGpuUnit("loaded", state.expected_terminal.invocation_id, state.stored)

    @contextmanager
    def released(resources):
        assert resources == state.unack_resources and state.stopped and state.stored == 0
        if state.effect_fault == "lease_busy":
            raise ValueError("synthetic original lease still busy")
        state.held = True
        try:
            yield
        finally:
            state.held = False

    def effect(arguments, **kwargs):
        assert arguments[:2] == ("/usr/bin/systemctl", "--no-ask-password")
        assert arguments[-1] == state.unit_name
        assert kwargs == dict(capture_output=True, check=False, timeout=10, env=owner._ENV)
        action = arguments[2:-1]
        assert action in {("reset-failed",), ("clean", "--what=fdstore")}
        record = json.loads((tmp_path / "retirement/intent.json").read_bytes())
        assert record["event"] == "BENCHMARK_CUDA_UNACKNOWLEDGED_RETIREMENT_INTENT"
        assert record["admission_granted"] is False
        assert not (tmp_path / "retirement/result.json").exists()
        state.calls.append(action)
        label = "clean" if action[0] == "clean" else "reset"
        if state.effect_fault == label + "_before":
            raise subprocess.TimeoutExpired(arguments, 10)
        if label == "clean":
            assert state.stopped and state.stored == 1
            state.stored = 0
        else:
            assert not state.stopped
            state.stopped = True
            if state.effect_fault == "late_ack":
                state.ack_present = True
        if state.effect_fault == label + "_after":
            raise subprocess.TimeoutExpired(arguments, 10)
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(owner, "reserve_unit_effect_phase", reserve)
    monkeypatch.setattr(owner, "observe_stopped_gpu_unit", stopped)
    monkeypatch.setattr(owner, "hold_released_unacknowledged_benchmark_resources", released)
    monkeypatch.setattr(
        owner,
        "observe_unacknowledged_benchmark_gpu_resources",
        observation.observe_unacknowledged_benchmark_gpu_resources,
    )
    monkeypatch.setattr(owner, "observe_cuda_probe_gpu_clients", lambda *_a: state.clients)
    monkeypatch.setattr(owner, "observe_runtime_device", lambda identity: identity)
    monkeypatch.setattr(
        owner, "subprocess", SimpleNamespace(run=effect, TimeoutExpired=subprocess.TimeoutExpired)
    )
    return state


def invoke(state, terminal, *, readonly=False):
    function = (
        owner.observe_retired_unacknowledged_benchmark_cuda_unit
        if readonly
        else owner.retire_unacknowledged_benchmark_cuda_unit
    )
    return function(
        terminal,
        state.invocation,
        state.environment,
        backend=state.backend,
        inventory=state.inventory,
        host=state.host,
    )


@pytest.mark.parametrize("stored", (0, 1))
def test_exact_cleanup_preserves_pre_ack_failure_and_does_not_touch_competing_holder(
    recovery, stored
):
    state = recovery
    state.stored = stored
    if not stored:
        state.clients = (999,)
    terminal = observe(state)
    result = invoke(state, terminal)
    assert (
        result.original_terminal is terminal
        and result.original_terminal.original_outcome == "FAILED"
    )
    assert result.retired_unit.stored_descriptors == 0 and not state.held
    assert state.calls == [("reset-failed",)] + ([("clean", "--what=fdstore")] if stored else [])
    record = json.loads((state.root / "retirement/result.json").read_bytes())
    assert record["event"] == "BENCHMARK_CUDA_UNACKNOWLEDGED_RETIRED_NOT_ADMITTED"
    assert record["admission_granted"] is False
    assert canonical_json_bytes(record) == (state.root / "retirement/result.json").read_bytes()
    Draft202012Validator(TypeAdapter(type(result)).json_schema()).validate(record["observation"])
    with pytest.raises(OSError):
        os.fstat(state.directory)


@pytest.mark.parametrize("fault", ("reset_before", "reset_after", "clean_before", "clean_after"))
def test_uncertain_effect_retains_intent_and_never_replays(recovery, fault):
    state = recovery
    terminal = observe(state)
    state.effect_fault = fault
    with pytest.raises(ValueError, match="EFFECT_UNCERTAIN"):
        invoke(state, terminal)
    assert (state.root / "retirement/intent.json").is_file()
    assert not (state.root / "retirement/result.json").exists()
    calls = tuple(state.calls)
    state.effect_fault = None
    with pytest.raises(ValueError):
        invoke(state, terminal)
    assert tuple(state.calls) == calls


def test_readonly_recovery_never_replays_an_uncertain_clean(recovery):
    state = recovery
    terminal = observe(state)
    state.effect_fault = "clean_after"
    with pytest.raises(ValueError, match="EFFECT_UNCERTAIN"):
        invoke(state, terminal)
    calls = tuple(state.calls)
    state.effect_fault = None
    result = invoke(state, terminal, readonly=True)
    assert result.original_terminal is terminal and tuple(state.calls) == calls
    assert not (state.root / "retirement/result.json").exists()


@pytest.mark.parametrize("fault", ("late_ack", "lease_busy"))
def test_ambiguous_ack_or_release_never_becomes_retirement_success(recovery, fault):
    state = recovery
    terminal = observe(state)
    state.effect_fault = fault
    with pytest.raises(
        ValueError, match=r"RECORD_PHASE_PRESENT|synthetic original lease still busy"
    ):
        invoke(state, terminal)
    assert not (state.root / "retirement/result.json").exists()
    if fault == "late_ack":
        assert state.calls == [("reset-failed",)] and state.stored == 1


@pytest.mark.parametrize("member", ("intent.json", "result.json"))
def test_partial_record_is_preserved_without_second_cleanup(recovery, monkeypatch, member):
    state = recovery
    terminal = observe(state)

    def uncertain(directory, name, raw):
        if name == member:
            write_unit_effect_record(directory, name, raw[:5])
            raise OSError("synthetic record uncertainty")
        write_unit_effect_record(directory, name, raw)

    monkeypatch.setattr(owner, "write_unit_effect_record", uncertain)
    with pytest.raises(ValueError, match="RECORD_UNCERTAIN"):
        invoke(state, terminal)
    calls = tuple(state.calls)
    assert len((state.root / "retirement" / member).read_bytes()) == 5
    with pytest.raises(ValueError):
        invoke(state, terminal)
    assert tuple(state.calls) == calls


@pytest.mark.parametrize("readonly", (False, True))
def test_nonroot_cannot_cleanup_or_reconcile_pre_ack_failure(recovery, monkeypatch, readonly):
    terminal = observe(recovery)
    monkeypatch.setattr(owner.os, "getresuid", lambda: (1000,) * 3)
    with pytest.raises(ValueError, match="ROOT_REQUIRED"):
        invoke(recovery, terminal, readonly=readonly)
    assert not recovery.calls and not tuple(recovery.root.iterdir())


def test_concurrent_pre_ack_recovery_has_one_original_effect_winner(recovery):
    state = recovery
    terminal = observe(state)

    def attempt():
        try:
            return invoke(state, terminal)
        except ValueError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _i: attempt(), range(2)))
    assert sum(isinstance(row, owner.UnacknowledgedBenchmarkCudaRetirement) for row in results) == 1
    assert state.calls == [("reset-failed",), ("clean", "--what=fdstore")]
