"""Execute only stdlib bootstrap with a fake runpy entry; zero model/CUDA imports."""

import runpy
import shlex
import signal
import sys
import time
from pathlib import Path

import pytest
from eom_catalog_service.embedding_benchmark_launch import (
    benchmark_launch_arguments,
    benchmark_launch_environment_bytes,
    parse_benchmark_launch_pins,
)
from eom_catalog_service.embedding_benchmark_unit_policy import benchmark_unit_family

from tests.unit.test_embedding_benchmark_budget_runtime import pins
from tests.unit.test_embedding_device_benchmark_budget import successor_policy_v12


@pytest.mark.parametrize("device", ("CPU", "CUDA"))
def test_actual_unit_and_root_observer_share_one_exact_argv(device):
    family = benchmark_unit_family(device, successor_policy_v12())
    path = Path(__file__).resolve().parents[2] / "infra/systemd" / family.service_template
    line = next(
        line.removeprefix("ExecStart=")
        for line in path.read_text().splitlines()
        if line.startswith("ExecStart=")
    )
    argv = shlex.split(line)
    assert tuple(argv[1:5]) == family.interpreter_arguments


@pytest.mark.parametrize("device", ("CPU", "CUDA"))
@pytest.mark.parametrize("seconds", (180, 600, 1200))
def test_complete_expanded_unit_argv_matches_actual_native_parser(device, seconds):
    from tests.unit.test_embedding_device_benchmark_budget import successor_policy

    policy = {180: None, 600: successor_policy(), 1200: successor_policy_v12()}[seconds]
    family = benchmark_unit_family(device, policy)
    path = Path(__file__).resolve().parents[2] / "infra/systemd" / family.service_template
    command = next(
        line.removeprefix("ExecStart=")
        for line in path.read_text().splitlines()
        if line.startswith("ExecStart=")
    )
    selected = pins(time.monotonic_ns() + 1200 * 10**9)
    environment = dict(
        line.split("=", 1)
        for line in benchmark_launch_environment_bytes(selected).decode().splitlines()
    )
    argv = shlex.split(command)
    tail = argv[1 + len(family.interpreter_arguments) :]
    expanded = tuple(
        selected.execution_id if word == "%i" else environment[word[2:-1]] for word in tail
    )
    assert expanded == benchmark_launch_arguments(selected)
    assert parse_benchmark_launch_pins(expanded) == selected


@pytest.mark.parametrize("pending", (False, True))
def test_cuda_blocks_ack_before_any_entrypoint_and_rejects_stale_signal(monkeypatch, pending):
    family = benchmark_unit_family("CUDA", successor_policy_v12())
    original_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())
    original_path = sys.path[:]
    calls = []

    def entry(module, *, run_name):
        assert signal.SIGUSR1 in signal.pthread_sigmask(signal.SIG_BLOCK, set())
        calls.append((module, run_name))

    monkeypatch.setattr(runpy, "run_module", entry)
    monkeypatch.setattr(signal, "sigpending", lambda: {signal.SIGUSR1} if pending else set())
    try:
        if pending:
            with pytest.raises(SystemExit) as error:
                exec(family.bootstrap_program, {})
            assert error.value.code == 1 and calls == []
        else:
            exec(family.bootstrap_program, {})
            assert calls == [(family.entrypoint_module, "__main__")]
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, original_mask)
        sys.path[:] = original_path
