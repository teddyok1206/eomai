"""Synthetic root/unit fences with real local intent/result IO; no signal or model."""

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace

import pytest
from eom_catalog_service import embedding_benchmark_cuda_lifetime as owner
from eom_catalog_service.unit_effect_records import write_unit_effect_record
from eom_identifiers import canonical_json_bytes
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter

from tests.unit.test_embedding_benchmark_cuda_observation import benchmark as benchmark
from tests.unit.test_embedding_benchmark_cuda_observation import observe
from tests.unit.test_embedding_native_probe_observation import ledger as ledger


@pytest.fixture
def lifetime(benchmark, tmp_path, monkeypatch):
    ready = observe(benchmark)
    state = SimpleNamespace(
        source=benchmark, ready=ready, calls=[], rechecks=0, fault=None, directory=None
    )

    def recheck(invocation, environment, **kwargs):
        assert invocation is benchmark.invocation and environment is benchmark.environment
        assert kwargs == dict(
            backend=benchmark.backend, inventory=benchmark.inventory, host=benchmark.host
        )
        state.rechecks += 1
        if state.fault == "initial_frame" or (state.fault == "late_frame" and state.rechecks == 2):
            return replace(ready, pid=ready.pid + 1)
        return ready

    def reserve(root, unit, invocation, phase):
        assert root == owner._ROOT and unit == benchmark.unit_name
        assert invocation == ready.unit.invocation_id and phase == "ack"
        directory = tmp_path / phase
        directory.mkdir(mode=0o700)
        state.directory = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        return state.directory

    def effect(arguments, **kwargs):
        assert arguments == (
            "/usr/bin/systemctl",
            "--no-ask-password",
            "kill",
            "--kill-whom=main",
            "--signal=SIGUSR1",
            benchmark.unit_name,
        )
        assert kwargs == dict(
            capture_output=True,
            check=False,
            timeout=10,
            env={"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"},
        )
        assert state.rechecks >= 2
        intent = tmp_path / "ack/intent.json"
        assert intent.is_file() and not (tmp_path / "ack/result.json").exists()
        data = json.loads(intent.read_bytes())
        assert data["event"] == "BENCHMARK_CUDA_ACK_INTENT" and data["admission_granted"] is False
        state.calls.append(arguments)
        if state.fault == "oserror":
            raise OSError("synthetic uncertain send")
        if state.fault == "timeout":
            raise subprocess.TimeoutExpired(arguments, 10)
        return SimpleNamespace(
            returncode=1 if state.fault == "exit" else 0,
            stdout=b"x" * 16385 if state.fault == "output" else b"",
            stderr=b"",
        )

    monkeypatch.setattr(owner, "observe_benchmark_cuda_ready", recheck)
    monkeypatch.setattr(owner, "reserve_unit_effect_phase", reserve)
    monkeypatch.setattr(
        owner, "subprocess", SimpleNamespace(run=effect, TimeoutExpired=subprocess.TimeoutExpired)
    )
    state.root = tmp_path
    return state


def acknowledge(state):
    source = state.source
    return owner.acknowledge_benchmark_cuda_ready(
        state.ready,
        source.invocation,
        source.environment,
        backend=source.backend,
        inventory=source.inventory,
        host=source.host,
    )


def test_intent_precedes_one_exact_original_main_ack_and_result_is_not_model_admission(lifetime):
    state = lifetime
    result = acknowledge(state)
    assert result.ready == state.ready and result.acknowledged_at_utc.endswith("Z")
    assert state.rechecks == 2 and len(state.calls) == 1
    for name in ("intent.json", "result.json"):
        raw = (state.root / "ack" / name).read_bytes()
        record = json.loads(raw)
        assert canonical_json_bytes(record) == raw and record["admission_granted"] is False
        adapter = TypeAdapter(type(state.ready) if name == "intent.json" else type(result))
        Draft202012Validator(adapter.json_schema()).validate(record["observation"])
    with pytest.raises(OSError):
        os.fstat(state.directory)
    with pytest.raises(ValueError, match="ALREADY_RESERVED"):
        acknowledge(state)
    assert len(state.calls) == 1


@pytest.mark.parametrize(
    "fault", ("initial_frame", "late_frame", "oserror", "timeout", "exit", "output")
)
def test_uncertain_or_changed_frame_keeps_intent_and_never_replays_signal(lifetime, fault):
    state = lifetime
    state.fault = fault
    with pytest.raises(ValueError):
        acknowledge(state)
    assert len(state.calls) == (0 if fault in {"initial_frame", "late_frame"} else 1)
    assert (state.root / "ack/intent.json").exists() == (fault != "initial_frame")
    assert not (state.root / "ack/result.json").exists()
    if state.directory is not None:
        with pytest.raises(OSError):
            os.fstat(state.directory)
    if fault != "initial_frame":
        state.fault = None
        before = tuple(state.calls)
        with pytest.raises(ValueError, match="ALREADY_RESERVED"):
            acknowledge(state)
        assert tuple(state.calls) == before


@pytest.mark.parametrize("name", ("intent.json", "result.json"))
def test_record_failure_preserves_partial_bytes_and_prevents_repeat(lifetime, monkeypatch, name):
    state = lifetime

    def uncertain(directory, member, raw):
        if member == name:
            write_unit_effect_record(directory, member, raw[:5])
            raise OSError("synthetic partial record outcome")
        return write_unit_effect_record(directory, member, raw)

    monkeypatch.setattr(owner, "write_unit_effect_record", uncertain)
    with pytest.raises(ValueError, match="RECORD_UNCERTAIN"):
        acknowledge(state)
    assert len(state.calls) == (0 if name == "intent.json" else 1)
    partial = (state.root / "ack" / name).read_bytes()
    assert len(partial) == 5
    with pytest.raises(ValueError, match="ALREADY_RESERVED"):
        acknowledge(state)
    assert (state.root / "ack" / name).read_bytes() == partial


@pytest.mark.parametrize("fault", ("root", "execution", "invocation", "cgroup"))
def test_invalid_identity_rejected_before_records_and_commands(lifetime, monkeypatch, fault):
    state = lifetime
    if fault == "root":
        monkeypatch.setattr(owner.os, "getresuid", lambda: (1000,) * 3)
    elif fault == "execution":
        state.ready = replace(state.ready, execution_id="../wrong")
    elif fault == "invocation":
        state.ready = replace(state.ready, unit=replace(state.ready.unit, invocation_id="latest"))
    else:
        state.ready = replace(state.ready, cgroup="/system.slice/another.service")
    with pytest.raises(ValueError):
        acknowledge(state)
    assert not state.calls and not tuple(state.root.iterdir())


def test_concurrent_original_ack_has_one_effect_winner(lifetime):
    state = lifetime

    def attempt():
        try:
            return acknowledge(state)
        except ValueError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _n: attempt(), range(2)))
    assert sum(isinstance(value, owner.BenchmarkCudaAcknowledgement) for value in results) == 1
    assert sum(isinstance(value, str) and "ALREADY_RESERVED" in value for value in results) == 1
    assert len(state.calls) == 1
