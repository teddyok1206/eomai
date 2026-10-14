"""Synthetic unit/cgroup observations; prove failure classification, never runtime acceptance."""

from dataclasses import replace

import pytest
from eom_orchestrator import native_embedding_cpu_execution as cpu

from tests.unit.test_inference_transfer_cpu_systemd import observation
from tests.unit.test_native_embedding_index_handoff import prepared as index_prepared
from tests.unit.test_native_embedding_index_systemd import setup_launcher as index_setup
from tests.unit.test_native_embedding_query_handoff import prepared as query_prepared
from tests.unit.test_native_embedding_query_systemd import setup_launcher as query_setup


@pytest.mark.parametrize("purpose", ("INDEX", "QUERY"))
@pytest.mark.parametrize("phase", ("before", "after"))
@pytest.mark.parametrize("fault", (None, "child", "changed", "timeout", "prepare_failed"))
def test_only_quiescent_stable_failure_is_terminal_and_never_a_restart(
    tmp_path,
    monkeypatch,
    purpose,
    phase,
    fault,
):
    setup, prepared = (
        (index_setup, index_prepared) if purpose == "INDEX" else (query_setup, query_prepared)
    )
    adapter, calls = setup(tmp_path, monkeypatch, [])
    pair = (
        (observation("failed"), observation("fresh", main=True))
        if fault == "prepare_failed"
        else (
            observation("success"),
            observation("timeout" if fault == "timeout" else "failed", main=True),
        )
    )
    final = (pair[0], replace(pair[1], invocation_id="b" * 32)) if fault == "changed" else pair
    states = [pair, final]
    if phase == "after":
        states.insert(0, (observation("fresh"), observation("fresh", main=True)))
    reads = iter(states)
    monkeypatch.setattr(type(adapter), "_observe", lambda *_: next(reads))
    if fault == "child":

        def surviving(_):
            raise cpu.NativeCpuExecutionError("NATIVE_CPU_UNCERTAIN")

        monkeypatch.setattr(cpu, "require_empty_native_cpu_cgroup", surviving)
    code = "KNOWN_FAILED" if fault in {None, "prepare_failed"} else "UNCERTAIN"
    with pytest.raises(ValueError, match=code):
        adapter.run(prepared())
    assert len(calls) == (1 if phase == "after" else 0)
