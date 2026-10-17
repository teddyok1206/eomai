"""Real temporary phase files; positive root/systemd/source/clock ports are synthetic."""

import json
import os
import subprocess
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
from eom_catalog_service import embedding_benchmark_cpu_driver as driver
from eom_catalog_service import embedding_benchmark_unit_control as control
from eom_catalog_service.embedding_benchmark_handoff import PreparedBenchmarkEnvironment
from eom_catalog_service.gpu_unit_terminal_observation import StoppedGpuUnit
from eom_orchestrator.inference_transfer_cpu_systemd import CpuUnitObservation
from eom_orchestrator.worker_systemd import FixedUnitStatus

from tests.unit.embedding_device_benchmark_fixtures import worker_invocation


@pytest.fixture
def lifecycle(tmp_path, monkeypatch):
    invocation = worker_invocation(1)
    now = time.monotonic_ns()
    environment = PreparedBenchmarkEnvironment(
        invocation.execution_id,
        invocation.job_id,
        "sha256:" + "a" * 64,
        os.getpid(),
        7,
        now + 10**9,
    )
    fresh = CpuUnitObservation(
        FixedUnitStatus("loaded", "inactive", "dead", "success", 0, 0, 0, False),
        0,
        0,
        "",
        "/etc/systemd/system/" + control.CPU_BENCHMARK_TEMPLATE,
        "",
    )
    running = replace(
        fresh,
        main_pid=123,
        invocation_id="a" * 32,
        status=replace(
            fresh.status,
            active_state="activating",
            sub_state="start",
            exec_main_started_monotonic=100,
        ),
    )
    terminal = replace(
        running,
        main_pid=0,
        exited_monotonic=200,
        status=replace(running.status, active_state="active", sub_state="exited", exec_main_code=1),
    )
    state = SimpleNamespace(
        invocation=invocation,
        environment=environment,
        backend=SimpleNamespace(),
        now=now,
        calls=[],
        observations=[fresh, running, terminal, terminal, terminal],
        fresh=fresh,
        running=running,
        terminal=terminal,
        fault=None,
        socket_live=False,
        stopped=StoppedGpuUnit("loaded", "a" * 32, 0),
        root=tmp_path,
    )

    def record(name):
        state.calls.append(name)
        if state.fault == name:
            raise ValueError("synthetic " + str(name))

    def snapshot(*args, **kwargs):
        record("capture")
        return SimpleNamespace(assert_unchanged=lambda: record("file_fence"))

    def inspect(*args, **kwargs):
        record("inspect")
        return state.observations.pop(0)

    def command(args, **kwargs):
        assert kwargs == dict(capture_output=True, check=False, timeout=10, env=control._ENV)
        action = args[1]
        record((action, args[-1]))
        if action == "show":
            fields = dict(
                LoadState="loaded",
                ActiveState="active" if state.socket_live else "inactive",
                SubState="running" if state.socket_live else "dead",
                NeedDaemonReload="no",
                FragmentPath="/etc/systemd/system/" + control.CPU_BENCHMARK_SOCKET,
                DropInPaths="",
                Job="0",
            )
            return SimpleNamespace(
                returncode=0,
                stdout="".join(f"{k}={v}\n" for k, v in fields.items()).encode(),
                stderr=b"",
            )
        if action == "start":
            state.socket_live = True
        if action == "stop" and args[-1].endswith(".socket"):
            state.socket_live = False
        if state.fault == "timeout" and action == "--no-block":
            raise subprocess.TimeoutExpired(args, 10)
        if action in {"stop", "reset-failed"} and args[-1].endswith(".service"):
            assert (tmp_path / "retirement/intent.json").is_file()
            assert not (tmp_path / "retirement/result.json").exists()
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    def reserve(root, unit, unit_invocation, phase):
        record("reserve")
        assert (
            root == driver.BENCHMARK_LIFETIME_ROOT
            and unit
            == control.CPU_BENCHMARK_TEMPLATE.replace(
                "@.service", f"@{invocation.execution_id}.service"
            )
        )
        assert unit_invocation == "a" * 32 and phase == "retirement"
        (tmp_path / phase).mkdir(mode=0o700)
        return os.open(tmp_path / phase, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)

    def stopped(*args, **kwargs):
        record("stopped")
        return state.stopped

    def sleep(seconds):
        assert 0 <= seconds <= 0.1
        state.now += 100_000_000

    monkeypatch.setattr(control.os, "getresuid", lambda: (0, 0, 0))
    monkeypatch.setattr(control.os, "getresgid", lambda: (0, 0, 0))
    monkeypatch.setattr(driver.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=990, pw_gid=990))
    monkeypatch.setattr(driver, "benchmark_owner_start_ticks", lambda *args, **kwargs: 7)
    monkeypatch.setattr(driver, "capture_prepared_benchmark_environment", snapshot)
    monkeypatch.setattr(control.FixedRootBenchmarkUnits, "capture_installed", snapshot)
    monkeypatch.setattr(control, "inspect_cpu_unit", inspect)
    monkeypatch.setattr(
        control,
        "subprocess",
        SimpleNamespace(run=command, TimeoutExpired=subprocess.TimeoutExpired),
    )
    monkeypatch.setattr(driver, "observe_stopped_gpu_unit", stopped)
    monkeypatch.setattr(driver, "require_empty_native_cpu_cgroup", lambda _: record("empty"))
    monkeypatch.setattr(driver, "reserve_unit_effect_phase", reserve)
    monkeypatch.setattr(driver, "BENCHMARK_HANDOFF_ROOT", tmp_path)
    monkeypatch.setattr(
        driver, "time", SimpleNamespace(monotonic_ns=lambda: state.now, sleep=sleep)
    )
    return state


def make(state):
    return driver.FixedRootBenchmarkCpuDriver(
        state.invocation, state.environment, backend=state.backend
    )


def effects(state):
    return [v for v in state.calls if isinstance(v, tuple) and v[0] != "show"]


def test_actual_phase_bytes_surround_one_original_cpu_lifecycle(lifecycle):
    state = lifecycle
    runtime = make(state)
    result = runtime.run()
    assert result.outcome == "SUCCEEDED" and result.job_id == state.invocation.job_id
    assert [v[0] for v in effects(state)] == ["start", "--no-block", "stop", "stop"]
    intent = json.loads((state.root / "retirement/intent.json").read_bytes())
    final = json.loads((state.root / "retirement/result.json").read_bytes())
    assert (
        intent["event"] == "BENCHMARK_CPU_RETIREMENT_INTENT"
        and intent["admission_granted"] is False
    )
    assert (
        final["event"] == "BENCHMARK_CPU_RETIRED_NOT_ADMITTED"
        and final["admission_granted"] is False
    )
    assert final["invocation_sha256"] == state.invocation.invocation_sha256
    assert final["observation"]["observed_at_utc"].endswith("Z")
    before = list(state.calls)
    with pytest.raises(ValueError, match="ALREADY_USED"):
        runtime.run()
    assert state.calls == before


def test_timeout_failure_is_preserved_and_reset_not_retried(lifecycle):
    state = lifecycle
    terminal = replace(
        state.terminal,
        status=replace(
            state.terminal.status,
            active_state="failed",
            sub_state="failed",
            result="timeout",
            exec_main_status=9,
        ),
    )
    state.observations[2:] = [terminal] * 3
    result = make(state).run()
    assert (
        result.outcome == "FAILED"
        and result.retirement.original_terminal.status.result == "timeout"
    )
    assert [v[0] for v in effects(state)] == ["start", "--no-block", "reset-failed", "stop"]


@pytest.mark.parametrize("fault", ("capture", "file_fence", "timeout"))
def test_failures_never_restart_or_invent_retirement(lifecycle, fault):
    state = lifecycle
    runtime = make(state)
    state.fault = fault
    with pytest.raises(ValueError):
        runtime.run()
    assert len([v for v in effects(state) if v[0] == "--no-block"]) <= 1
    assert not (state.root / "retirement").exists()
    with pytest.raises(ValueError, match="ALREADY_USED"):
        runtime.run()


def test_existing_unit_never_starts(lifecycle):
    state = lifecycle
    state.observations = [state.running]
    with pytest.raises(ValueError, match="UNIT_NOT_FRESH"):
        make(state).run()
    assert not effects(state)


def test_replaced_unit_after_start_is_not_acked_or_retired(lifecycle):
    state = lifecycle
    state.observations[2] = replace(state.terminal, invocation_id="b" * 32)
    with pytest.raises(ValueError, match="UNIT_CHANGED"):
        make(state).run()
    assert "reserve" not in state.calls and len(effects(state)) == 2


def test_partial_existing_retirement_intent_never_repeats_a_machine_effect(lifecycle):
    state = lifecycle
    (state.root / "retirement").mkdir()
    (state.root / "retirement/intent.json").write_bytes(b"partial")
    with pytest.raises(FileExistsError):
        make(state).run()
    assert len(effects(state)) == 2
    assert (state.root / "retirement/intent.json").read_bytes() == b"partial"


def test_unknown_stored_descriptor_is_not_cleaned_or_called_a_completed_retirement(lifecycle):
    state = lifecycle
    state.stopped = replace(state.stopped, stored_descriptors=1)
    with pytest.raises(ValueError, match="STORED_DESCRIPTORS_UNCERTAIN"):
        make(state).run()
    assert (state.root / "retirement/intent.json").exists()
    assert not (state.root / "retirement/result.json").exists()
    assert [v[0] for v in effects(state)] == ["start", "--no-block", "stop"]


def test_actual_nonroot_cannot_parse_or_start():
    if os.getuid() == 0:
        pytest.skip("requires actual nonroot")
    with pytest.raises(ValueError, match="ROOT_REQUIRED"):
        driver.FixedRootBenchmarkCpuDriver(None, None, backend=None)


@pytest.mark.parametrize("member", ("intent.json", "result.json"))
def test_partial_retirement_write_is_preserved_and_not_success(lifecycle, monkeypatch, member):
    state = lifecycle
    original = driver.write_unit_effect_record

    def uncertain(directory, name, raw):
        if name == member:
            original(directory, name, raw[:5])
            raise OSError("synthetic partial record")
        return original(directory, name, raw)

    monkeypatch.setattr(driver, "write_unit_effect_record", uncertain)
    runtime = make(state)
    with pytest.raises(OSError):
        runtime.run()
    assert (state.root / "retirement" / member).read_bytes() == b'{"adm'
    assert len(effects(state)) == (2 if member == "intent.json" else 3)
    with pytest.raises(ValueError, match="ALREADY_USED"):
        runtime.run()


def test_dead_original_owner_never_starts_a_cpu_unit(lifecycle, monkeypatch):
    state = lifecycle
    runtime = make(state)
    monkeypatch.setattr(driver, "benchmark_owner_start_ticks", lambda *args, **kwargs: 8)
    with pytest.raises(ValueError, match="OWNER_CHANGED"):
        runtime.run()
    assert not effects(state)


def test_terminal_after_compute_expiry_can_be_retired_without_extending_compute(
    lifecycle, monkeypatch
):
    state = lifecycle
    original = control.FixedRootBenchmarkUnits.start_service

    def start(units):
        original(units)
        state.now = state.environment.expires_ns + 1

    monkeypatch.setattr(control.FixedRootBenchmarkUnits, "start_service", start)
    terminal = replace(
        state.terminal,
        status=replace(
            state.terminal.status,
            active_state="failed",
            sub_state="failed",
            result="timeout",
            exec_main_status=9,
        ),
    )
    state.observations[2:] = [terminal] * 3
    result = make(state).run()
    assert result.outcome == "FAILED" and state.now > state.environment.expires_ns
    assert [v[0] for v in effects(state)].count("--no-block") == 1
