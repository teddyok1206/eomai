"""Synthetic late root/unit/driver ports, never actual termination or GPU cleanup."""

from dataclasses import replace
from pathlib import Path

import pytest
from eom_catalog_service import embedding_benchmark_cuda_observation as owner

from tests.unit.test_embedding_benchmark_cuda_observation import benchmark as benchmark
from tests.unit.test_embedding_benchmark_cuda_observation import observe
from tests.unit.test_embedding_native_probe_observation import ledger as ledger
from tests.unit.test_embedding_native_probe_observation import terminal as terminal_unit


@pytest.fixture
def ended(benchmark, monkeypatch):
    state = benchmark
    ready = observe(state)
    state.observed_ready = ready
    state.unit = replace(terminal_unit(), fragment_path=ready.unit.fragment_path)
    state.pids = ()
    state.original_exists = False
    state.retained_calls = 0
    original = Path.lstat

    def lstat(path, *args, **kwargs):
        if path == Path("/proc/123"):
            if not state.original_exists:
                raise FileNotFoundError("synthetic ended process")
            from types import SimpleNamespace

            return SimpleNamespace(st_uid=1234)
        return original(path, *args, **kwargs)

    def retained(resources, *, unit):
        assert resources == ready.resources and unit == state.unit_name
        state.retained_calls += 1
        if state.fault == "retained":
            raise ValueError("synthetic retained descriptor changed")
        return resources

    monkeypatch.setattr(Path, "lstat", lstat)
    monkeypatch.setattr(owner, "observe_cuda_probe_retained_resources", retained)
    return state


def verify(state):
    return owner.verify_benchmark_cuda_terminal(
        state.observed_ready,
        state.invocation,
        state.environment,
        backend=state.backend,
        inventory=state.inventory,
        host=state.host,
    )


@pytest.mark.parametrize("outcome", ("success", "failed", "timeout"))
def test_original_outcome_is_preserved_and_expired_live_window_does_not_block_cleanup(
    ended, monkeypatch, outcome
):
    state = ended
    if outcome != "success":
        state.unit = replace(
            state.unit,
            status=replace(
                state.unit.status,
                active_state="failed",
                sub_state="failed",
                result="timeout" if outcome == "timeout" else "exit-code",
                exec_main_status=1,
            ),
        )
    monkeypatch.setattr(owner.time, "monotonic_ns", lambda: state.pins.expires_ns + 1)
    monkeypatch.setattr(
        owner,
        "benchmark_owner_start_ticks",
        lambda *_a, **_kw: pytest.fail("cleanup requires live actor"),
    )
    result = verify(state)
    assert result.ready is state.observed_ready and result.terminal_unit == state.unit
    assert result.original_outcome == ("SUCCEEDED" if outcome == "success" else "FAILED")
    assert result.terminal_unit.status.result == (
        "timeout" if outcome == "timeout" else "exit-code" if outcome == "failed" else "success"
    )
    assert state.retained_calls == 2


@pytest.mark.parametrize(
    "fault",
    (
        "root",
        "running",
        "invocation",
        "start",
        "same_process",
        "child",
        "gpu",
        "retained",
        "file",
        "ready_hash",
        "policy",
    ),
)
def test_unknown_or_changed_terminal_state_never_proves_cleanup(ended, monkeypatch, fault):
    state = ended
    state.fault = fault
    if fault == "root":
        monkeypatch.setattr(owner.os, "getresuid", lambda: (1000,) * 3)
    elif fault == "running":
        state.unit = state.observed_ready.unit
    elif fault == "invocation":
        state.unit = replace(state.unit, invocation_id="a" * 32)
    elif fault == "start":
        state.unit = replace(
            state.unit, status=replace(state.unit.status, exec_main_started_monotonic=101)
        )
    elif fault == "same_process":
        state.original_exists = True
    elif fault == "child":
        state.pids = (124,)
    elif fault == "gpu":
        state.clients = (123,)
    elif fault == "file":
        state.drift = True
    elif fault == "ready_hash":
        state.observed_ready = replace(state.observed_ready, ready_raw_sha256="sha256:" + "a" * 64)
    elif fault == "policy":
        state.policy = state.policy.replace(b"Restart=no", b"Restart=always")
    with pytest.raises(ValueError):
        verify(state)


def test_reused_pid_is_not_mistaken_for_the_ended_original_process(ended):
    state = ended
    state.original_exists = True
    state.start += 1
    result = verify(state)
    assert result.original_outcome == "SUCCEEDED" and result.ready.start_time_ticks != state.start


def test_pinned_file_capture_is_not_a_live_ready_or_model_grant(ended, monkeypatch):
    state = ended
    monkeypatch.setattr(owner.time, "monotonic_ns", lambda: state.pins.expires_ns + 1)
    captured = owner.capture_benchmark_cuda_pinned_files(
        state.invocation, state.environment, backend=state.backend, inventory=state.inventory
    )
    captured.assert_current()
    assert captured.ready == state.ready
    with pytest.raises(ValueError, match="NOT_RUNNING"):
        observe(state)
