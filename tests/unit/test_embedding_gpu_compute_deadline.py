"""Actual child-process deadline; not GPU, worker identity or privilege acceptance."""

from __future__ import annotations

import signal
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from eom_catalog_service import embedding_gpu_batch_worker as worker


def child(body: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", "-c", body], capture_output=True, text=True, timeout=12, check=False
    )


def test_kernel_default_deadline_terminates_a_dedicated_child_in_a_native_call():
    result = child("""
import ctypes
from eom_catalog_service.embedding_gpu_batch_worker import _hard_compute_deadline
native = ctypes.PyDLL(None)
native.sleep.argtypes = [ctypes.c_uint]
native.sleep.restype = ctypes.c_uint
with _hard_compute_deadline(1):
    print('ARMED', flush=True)
    native.sleep(5)
print('UNREACHABLE', flush=True)
""")
    assert result.stdout == "ARMED\n"
    assert result.returncode == -signal.SIGALRM


def test_success_cancels_only_its_own_timer_before_later_process_work():
    result = child("""
import signal
import time
from eom_catalog_service.embedding_gpu_batch_worker import _hard_compute_deadline
with _hard_compute_deadline(1):
    assert signal.getitimer(signal.ITIMER_REAL)[0] > 0
assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
time.sleep(1.2)
print('DISARMED', flush=True)
""")
    assert result.returncode == 0 and result.stdout == "DISARMED\n"


@pytest.fixture
def signals(monkeypatch):
    calls = []
    state = {"handler": signal.SIG_DFL, "timer": (0.0, 0.0), "mask": set()}
    monkeypatch.setattr(
        worker,
        "signal",
        SimpleNamespace(
            SIGALRM=signal.SIGALRM,
            SIG_DFL=signal.SIG_DFL,
            SIG_BLOCK=signal.SIG_BLOCK,
            ITIMER_REAL=signal.ITIMER_REAL,
            getsignal=lambda _signal: state["handler"],
            getitimer=lambda _timer: state["timer"],
            pthread_sigmask=lambda _how, _mask: state["mask"],
            setitimer=lambda timer, seconds: calls.append((timer, seconds)),
        ),
    )
    return calls, state


@pytest.mark.parametrize("seconds", (0, -1, 181, True, 180.0, "180"))
def test_invalid_compute_limit_cannot_arm_a_process_timer(signals, seconds):
    calls, _state = signals
    with pytest.raises(ValueError), worker._hard_compute_deadline(seconds):
        pytest.fail("invalid budget entered")
    assert not calls


@pytest.mark.parametrize("fault", ("handler", "timer", "blocked"))
def test_existing_signal_owner_or_blocked_deadline_is_not_overwritten(signals, fault):
    calls, state = signals
    if fault == "handler":
        state["handler"] = signal.SIG_IGN
    elif fault == "timer":
        state["timer"] = (10.0, 0.0)
    else:
        state["mask"] = {signal.SIGALRM}
    with pytest.raises(ValueError), worker._hard_compute_deadline(180):
        pytest.fail("foreign/blocked timer admitted")
    assert not calls


def test_worker_guard_cannot_be_used_in_a_shared_service_thread(signals):
    calls, _state = signals

    def shared_thread():
        with worker._hard_compute_deadline(180):
            pytest.fail("shared service thread armed process timer")

    with ThreadPoolExecutor(max_workers=1) as pool, pytest.raises(ValueError):
        pool.submit(shared_thread).result(timeout=5)
    assert not calls


def test_exception_disarms_owned_timer_and_preserves_original_exception(signals):
    calls, _state = signals
    with pytest.raises(RuntimeError, match="original failure"), worker._hard_compute_deadline(180):
        raise RuntimeError("original failure")
    assert calls == [(signal.ITIMER_REAL, 180.0), (signal.ITIMER_REAL, 0.0)]
