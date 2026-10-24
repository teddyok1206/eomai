"""Fixed lifecycle composition with synthetic root/unit/GPU ports; no live GPU acceptance."""

import os
import socket
import subprocess
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
from eom_catalog_service import embedding_benchmark_cuda_driver as driver
from eom_catalog_service import embedding_benchmark_unit_control as control
from eom_catalog_service.embedding_benchmark_handoff import PreparedBenchmarkEnvironment
from eom_catalog_service.embedding_benchmark_unit_control import CUDA_BENCHMARK_SOCKET
from eom_orchestrator.inference_transfer_cpu_systemd import CpuUnitObservation
from eom_orchestrator.worker_systemd import FixedUnitStatus

from tests.unit.embedding_device_benchmark_fixtures import resources, worker_invocation


@pytest.fixture
def lifecycle(monkeypatch, tmp_path):
    invocation = worker_invocation(2)
    connection, other = socket.socketpair()
    now = time.monotonic_ns()
    environment = PreparedBenchmarkEnvironment(
        invocation.execution_id,
        invocation.job_id,
        "sha256:" + "a" * 64,
        os.getpid(),
        7,
        now + 10**9,
    )
    calls = []
    fresh = CpuUnitObservation(
        FixedUnitStatus("loaded", "inactive", "dead", "success", 0, 0, 0, False),
        0,
        0,
        "",
        "/etc/systemd/system/" + driver.CUDA_BENCHMARK_TEMPLATE,
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
    ready = SimpleNamespace(unit=running)
    retirement = SimpleNamespace(original_terminal=SimpleNamespace(original_outcome="SUCCEEDED"))
    state = SimpleNamespace(
        invocation=invocation,
        environment=environment,
        connection=connection,
        other=other,
        calls=calls,
        fresh=fresh,
        running=running,
        terminal=terminal,
        ready=ready,
        retirement=retirement,
        observations=[fresh, running, terminal],
        now=now,
        sleeps=0,
        socket_live=False,
        fault=None,
    )

    def record(name):
        calls.append(name)
        if state.fault == name:
            raise ValueError("synthetic " + name + " failure")

    def inspect(unit, *, template):
        assert unit == driver.CUDA_BENCHMARK_TEMPLATE.replace(
            "@.service", f"@{invocation.execution_id}.service"
        )
        assert template == driver.CUDA_BENCHMARK_TEMPLATE
        record("inspect")
        return state.observations.pop(0)

    def command(arguments, **kwargs):
        assert arguments[0] == "/usr/bin/systemctl"
        assert kwargs == dict(capture_output=True, check=False, timeout=10, env=control._ENV)
        args = arguments[1:]
        record(tuple(args))
        if args[0] == "show":
            fields = dict(
                LoadState="loaded",
                ActiveState="active" if state.socket_live else "inactive",
                SubState="listening" if state.socket_live else "dead",
                NeedDaemonReload="no",
                FragmentPath="/etc/systemd/system/" + CUDA_BENCHMARK_SOCKET,
                DropInPaths="",
                Job="0",
            )
            if state.fault == "socket_reload":
                fields["NeedDaemonReload"] = "yes"
            if state.fault == "socket_auto_activation" and state.socket_live:
                fields["SubState"] = "running"
            return SimpleNamespace(
                returncode=0,
                stdout="".join(f"{k}={v}\n" for k, v in fields.items()).encode(),
                stderr=b"",
            )
        if args[0] == "start":
            assert args[1].endswith(".socket")
            state.socket_live = True
        elif args[0] == "stop":
            assert args[1].endswith(".socket")
            state.socket_live = False
        else:
            assert args[:2] == ("--no-block", "start") and args[2].endswith(".service")
        if state.fault == "start_timeout":
            raise subprocess.TimeoutExpired(arguments, 10)
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    def capture(*args, **kwargs):
        record("capture")
        assert args == (invocation, environment)
        return SimpleNamespace(assert_current=lambda: record("capture_current"))

    def observe(*args, **kwargs):
        record("ready")
        assert args == (invocation, environment)
        if state.fault == "pending":
            raise ValueError("BENCHMARK_CUDA_OBSERVATION_NOT_READY")
        return ready

    def ack(*args, **kwargs):
        record("ack")
        assert args == (ready, invocation, environment)

    class Relay:
        def __init__(self, peer, inv, env, **kwargs):
            record("relay_baseline")
            assert peer is connection and inv == invocation and env == environment

        def sample(self):
            record("sample")

        def serve(self):
            record("resources")
            connection.close()  # Same ownership as actual resource relay.
            if state.fault == "late_terminal":
                state.now = environment.expires_ns + 1
            return resources(2)

        def close(self):
            calls.append("relay_close")
            connection.close()

    def verify(*args, **kwargs):
        record("verify_terminal")
        assert args == (ready, invocation, environment)
        return "synthetic verified terminal"

    def retire(*args, **kwargs):
        record("retire")
        assert args == ("synthetic verified terminal", invocation, environment)
        return state.retirement

    def sleep(seconds):
        assert 0 <= seconds <= 0.1
        state.sleeps += 1
        state.now += 100_000_000

    monkeypatch.setattr(driver.os, "getresuid", lambda: (0, 0, 0))
    monkeypatch.setattr(driver.os, "getresgid", lambda: (0, 0, 0))
    monkeypatch.setattr(
        driver.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
    )
    monkeypatch.setattr(driver, "benchmark_owner_start_ticks", lambda *args, **kwargs: 7)
    monkeypatch.setattr(driver, "BENCHMARK_HANDOFF_ROOT", tmp_path)
    monkeypatch.setattr(
        driver, "time", SimpleNamespace(monotonic_ns=lambda: state.now, sleep=sleep)
    )
    monkeypatch.setattr(
        control,
        "subprocess",
        SimpleNamespace(run=command, TimeoutExpired=subprocess.TimeoutExpired),
    )
    monkeypatch.setattr(driver, "inspect_cpu_unit", inspect)
    monkeypatch.setattr(driver, "capture_benchmark_cuda_launch_files", capture)
    monkeypatch.setattr(driver, "observe_benchmark_cuda_ready", observe)
    monkeypatch.setattr(driver, "acknowledge_benchmark_cuda_ready", ack)
    monkeypatch.setattr(driver, "RootBenchmarkGpuResourceRelay", Relay)
    monkeypatch.setattr(driver, "verify_benchmark_cuda_terminal", verify)
    monkeypatch.setattr(driver, "retire_benchmark_cuda_unit", retire)
    monkeypatch.setattr(driver, "require_empty_benchmark_cuda_cgroup", lambda _: record("empty"))
    state.backend = SimpleNamespace()
    state.inventory = SimpleNamespace(assert_unchanged=lambda: record("inventory"))
    state.host = SimpleNamespace(assert_current=lambda: record("host"))
    yield state
    connection.close()
    other.close()


def make(state):
    return driver.FixedRootBenchmarkCudaDriver(
        state.connection,
        state.invocation,
        state.environment,
        backend=state.backend,
        inventory=state.inventory,
        host=state.host,
    )


def effects(state):
    return [row for row in state.calls if isinstance(row, tuple) and row[0] != "show"]


def test_lifecycle_composes_one_start_baseline_ack_observation_retirement_and_socket_stop(
    lifecycle,
):
    state = lifecycle
    runtime = make(state)
    result = runtime.run()
    assert result.outcome == "SUCCEEDED" and result.execution_id == state.invocation.execution_id
    assert result.resources == resources(2) and result.retirement is state.retirement
    assert [row[0] for row in effects(state)] == ["start", "--no-block", "stop"]
    assert (
        state.calls.index("relay_baseline")
        < state.calls.index("ack")
        < state.calls.index("resources")
    )
    assert state.calls.count("sample") == 2 and state.calls.count("retire") == 1
    assert state.calls.index("verify_terminal") < state.calls.index("retire")
    assert state.connection.fileno() == -1
    before = list(state.calls)
    with pytest.raises(ValueError, match="ALREADY_USED"):
        runtime.run()
    assert state.calls == before


@pytest.mark.parametrize("fault", ("capture", "host", "inventory", "socket_reload"))
def test_failed_preflight_has_no_start_and_cannot_be_retried(lifecycle, fault):
    state = lifecycle
    runtime = make(state)
    state.fault = fault
    with pytest.raises(ValueError):
        runtime.run()
    assert not effects(state) and state.connection.fileno() == -1
    with pytest.raises(ValueError, match="ALREADY_USED"):
        runtime.run()


@pytest.mark.parametrize(
    "fault", ("start_timeout", "ack", "sample", "resources", "verify_terminal", "retire")
)
def test_effect_failure_never_restarts_or_speculatively_stops_a_unit(lifecycle, fault):
    state = lifecycle
    runtime = make(state)
    state.fault = fault
    with pytest.raises(ValueError):
        runtime.run()
    # Requires=socket means even a socket-only stop can kill a live GPU service.
    assert all(row[0] != "stop" for row in effects(state))
    assert len([row for row in effects(state) if row[0] == "start"]) == 1
    assert state.calls.count("ack") <= 1 and state.calls.count("retire") <= 1
    assert state.connection.fileno() == -1
    with pytest.raises(ValueError, match="ALREADY_USED"):
        runtime.run()


def test_failed_original_outcome_survives_confirmed_retirement(lifecycle):
    state = lifecycle
    state.terminal = replace(
        state.terminal,
        status=replace(
            state.terminal.status,
            active_state="failed",
            sub_state="failed",
            result="timeout",
            exec_main_status=9,
        ),
    )
    state.observations[-1] = state.terminal
    state.retirement.original_terminal.original_outcome = "FAILED"
    assert make(state).run().outcome == "FAILED"
    assert state.calls.count("retire") == 1


def test_owner_connection_can_activate_original_socket_before_explicit_service_start(lifecycle):
    state = lifecycle
    state.fault = "socket_auto_activation"
    assert make(state).run().outcome == "SUCCEEDED"
    assert [row[0] for row in effects(state)] == ["start", "--no-block", "stop"]


def test_timeout_terminal_cleanup_is_allowed_after_compute_expiry_without_another_ack(lifecycle):
    state = lifecycle
    state.fault = "late_terminal"
    assert make(state).run().outcome == "SUCCEEDED"
    assert state.now > state.environment.expires_ns
    assert state.calls.count("ack") == 1 and state.calls.count("retire") == 1


def test_live_not_ready_wait_keeps_original_handle_and_absolute_deadline(lifecycle):
    state = lifecycle
    state.fault = "pending"
    state.observations = [state.fresh] + [state.running] * 20
    with pytest.raises(ValueError, match="EXPIRED"):
        make(state).run()
    assert state.sleeps == 10 and len(effects(state)) == 2
    assert "ack" not in state.calls and "retire" not in state.calls


def test_unit_replacement_while_waiting_never_gets_a_compute_ack(lifecycle):
    state = lifecycle
    state.fault = "pending"
    state.observations = [
        state.fresh,
        state.running,
        replace(state.running, invocation_id="b" * 32),
    ]
    with pytest.raises(ValueError, match="UNIT_CHANGED"):
        make(state).run()
    assert "ack" not in state.calls and "retire" not in state.calls


def test_terminal_before_ready_preserves_history_for_unacknowledged_reconciliation(lifecycle):
    state = lifecycle
    state.observations = [state.fresh, state.terminal]
    with pytest.raises(ValueError, match="TERMINAL_BEFORE_READY"):
        make(state).run()
    assert (
        "relay_baseline" not in state.calls
        and "ack" not in state.calls
        and "retire" not in state.calls
    )
    assert len(effects(state)) == 2


def test_existing_execution_is_refused_before_any_start(lifecycle):
    state = lifecycle
    state.observations = [state.running]
    with pytest.raises(ValueError, match="UNIT_NOT_FRESH"):
        make(state).run()
    assert not effects(state)


@pytest.mark.parametrize("fault", ("root_group", "expired", "distant_expiry", "foreign_job"))
def test_constructor_identity_failures_close_socket_before_preflight(lifecycle, monkeypatch, fault):
    state = lifecycle
    if fault == "root_group":
        monkeypatch.setattr(driver.os, "getresgid", lambda: (1, 1, 1))
    elif fault == "expired":
        state.environment = replace(state.environment, expires_ns=state.now)
    elif fault == "distant_expiry":
        state.environment = replace(state.environment, expires_ns=state.now + 181 * 10**9)
    else:
        state.environment = replace(state.environment, job_id="job_" + "b" * 32)
    with pytest.raises(ValueError):
        make(state)
    assert not state.calls and state.connection.fileno() == -1


def test_dead_owner_before_start_never_launches(lifecycle, monkeypatch):
    state = lifecycle
    runtime = make(state)
    monkeypatch.setattr(driver, "benchmark_owner_start_ticks", lambda *args, **kwargs: 8)
    with pytest.raises(ValueError, match="OWNER_CHANGED"):
        runtime.run()
    assert not effects(state)


def test_replaced_unit_after_finalization_is_not_retired(lifecycle):
    state = lifecycle
    state.observations[-1] = replace(state.terminal, invocation_id="b" * 32)
    with pytest.raises(ValueError, match="UNIT_CHANGED"):
        make(state).run()
    assert "retire" not in state.calls and all(row[0] != "stop" for row in effects(state))


def test_timeout_terminal_is_still_failure_when_cleanup_runs_after_admission_expires(lifecycle):
    state = lifecycle
    state.fault = "late_terminal"
    state.observations[-1] = replace(
        state.terminal,
        status=replace(
            state.terminal.status,
            active_state="failed",
            sub_state="failed",
            result="timeout",
            exec_main_status=9,
        ),
    )
    state.retirement.original_terminal.original_outcome = "FAILED"
    assert make(state).run().outcome == "FAILED"
    assert state.now > state.environment.expires_ns
    assert state.calls.count("ack") == 1 and state.calls.count("retire") == 1


def test_peer_changed_before_start_is_refused_by_real_socket_credentials(lifecycle):
    state = lifecycle
    runtime = make(state)
    runtime._owner = (os.getpid() + 1, os.getuid(), os.getgid())
    with pytest.raises(ValueError, match="PEER_CHANGED"):
        runtime.run()
    assert not state.calls and state.connection.fileno() == -1


def test_actual_nonroot_is_denied_before_parsing_or_os_effects():
    if os.geteuid() == 0:
        pytest.skip("requires actual nonroot process")
    connection, other = socket.socketpair()
    try:
        with pytest.raises(ValueError, match="ROOT_REQUIRED"):
            driver.FixedRootBenchmarkCudaDriver(
                connection, None, None, backend=None, inventory=None, host=None
            )
        assert connection.fileno() == -1
    finally:
        connection.close()
        other.close()
