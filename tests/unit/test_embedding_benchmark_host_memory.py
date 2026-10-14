"""Synthetic kernel records and temporary files; no live cgroup, model or runtime mutation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_service import embedding_benchmark_host_memory as host
from eom_catalog_service.embedding_execution_ports import BenchmarkHostObservationError
from eom_catalog_service.embedding_runtime_files import read_live_runtime_os_file

EXECUTION_ID = "a" * 32


def counters(**changes: int) -> bytes:
    values = {"low": 0, "high": 0, "max": 0, "oom": 0, "oom_kill": 0, "oom_group_kill": 0}
    return b"".join(f"{key} {value}\n".encode() for key, value in (values | changes).items())


@pytest.fixture
def kernel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> dict[str, Any]:
    root = tmp_path / "cgroup"
    device_kind = getattr(request, "param", "CPU")
    unit = f"eom-embedding-benchmark-{device_kind.lower()}@{EXECUTION_ID}.service"
    directory = root / "system.slice" / unit
    directory.mkdir(parents=True)
    for path in (root, directory.parent, directory):
        path.chmod(0o700)
    events = directory / "memory.events"
    events.write_bytes(counters())
    events.chmod(0o444)
    device = root.stat().st_dev
    mount = f"41 23 {os.major(device)}:{os.minor(device)} / {root} ro - cgroup2 cgroup rw\n"
    state: dict[str, Any] = {
        "root": root,
        "device": device_kind,
        "directory": directory,
        "events": events,
        "mountinfo": mount.encode(),
        "cgroup": f"0::/system.slice/{unit}\n".encode(),
        "read_count": 0,
        "on_read": lambda: None,
    }
    monkeypatch.setattr(host, "_CGROUP_ROOT", root)

    def read(path: Path, *, maximum: int, owner_uid: int = 0) -> bytes:
        assert maximum in (4096, 1024**2)
        if path.parent == Path("/proc") / str(os.getpid()):
            assert owner_uid == os.geteuid()
            return bytes(state[path.name])
        assert path == events and maximum == 4096 and owner_uid == 0
        state["read_count"] += 1
        state["on_read"]()
        # Explicit synthetic file owner; production read always requires root protection.
        return read_live_runtime_os_file(path, maximum=maximum, owner_uid=os.geteuid())

    monkeypatch.setattr(host, "read_live_runtime_os_file", read)
    return state


def overwrite(path: Path, raw: bytes) -> None:
    path.chmod(0o600)
    path.write_bytes(raw)
    path.chmod(0o444)


def test_original_baseline_and_live_monotonic_oom_delta_without_rebasing(
    kernel: dict[str, Any],
) -> None:
    overwrite(kernel["events"], counters(oom=4, oom_kill=2))
    observer = host.OwnBenchmarkHostOomObserver(device="CPU", execution_id=EXECUTION_ID)
    assert observer.observe_delta() == 0
    overwrite(kernel["events"], counters(oom=6, oom_kill=2))
    assert observer.observe_delta() == 2
    overwrite(kernel["events"], counters(oom=7, oom_kill=2, high=8))
    assert observer.observe_delta() == 3
    assert kernel["read_count"] == 4


@pytest.mark.parametrize("key", ("oom_kill", "oom_group_kill"))
def test_global_or_group_kill_is_not_hidden_by_zero_local_oom_or_double_counted(
    kernel: dict[str, Any], key: str
) -> None:
    observer = host.OwnBenchmarkHostOomObserver(device="CPU", execution_id=EXECUTION_ID)
    overwrite(kernel["events"], counters(**{key: 1}))
    with pytest.raises(BenchmarkHostObservationError, match="HOST_OOM_KILL_DETECTED"):
        observer.observe_delta()
    overwrite(kernel["events"], counters())
    with pytest.raises(BenchmarkHostObservationError, match="OBSERVER_POISONED"):
        observer.observe_delta()


@pytest.mark.parametrize("key", ("oom", "low", "high", "max", "oom_kill"))
def test_any_counter_reset_poisoned_without_rebasing(kernel: dict[str, Any], key: str) -> None:
    overwrite(kernel["events"], counters(**{key: 3}))
    observer = host.OwnBenchmarkHostOomObserver(device="CPU", execution_id=EXECUTION_ID)
    overwrite(kernel["events"], counters(**{key: 2}))
    with pytest.raises(BenchmarkHostObservationError, match="COUNTER_RESET"):
        observer.observe_delta()


@pytest.mark.parametrize("when", ("observe", "during_read"))
@pytest.mark.parametrize("fault", ("membership", "mount", "file_inode", "directory", "symlink"))
def test_replacement_or_membership_drift_cannot_produce_an_observation(
    kernel: dict[str, Any], when: str, fault: str
) -> None:
    def change() -> None:
        if fault == "membership":
            kernel["cgroup"] = b"0::/unrelated.service\n"
        elif fault == "mount":
            kernel["mountinfo"] = kernel["mountinfo"].replace(b"41 23 ", b"42 23 ")
        elif fault == "directory":
            kernel["directory"].chmod(0o750)
        else:
            replacement = kernel["events"].with_name("original-events")
            kernel["events"].rename(replacement)
            if fault == "symlink":
                kernel["events"].symlink_to(replacement)
            else:
                kernel["events"].write_bytes(counters())
                kernel["events"].chmod(0o444)

    observer = host.OwnBenchmarkHostOomObserver(device="CPU", execution_id=EXECUTION_ID)
    if when == "during_read":
        kernel["on_read"] = change
    else:
        change()
    with pytest.raises(BenchmarkHostObservationError):
        observer.observe_delta()
    kernel["on_read"] = lambda: None
    with pytest.raises(BenchmarkHostObservationError, match="POISONED"):
        observer.observe_delta()


@pytest.mark.parametrize("fault", ("membership", "mount", "missing_file", "symlink", "writable"))
def test_invalid_initial_capture_never_invents_a_zero(kernel: dict[str, Any], fault: str) -> None:
    if fault == "membership":
        kernel["cgroup"] = b"0::/foreign.service\n"
    elif fault == "mount":
        kernel["mountinfo"] = kernel["mountinfo"].replace(b"cgroup2", b"tmpfs")
    elif fault == "missing_file":
        kernel["events"].unlink()
    elif fault == "writable":
        kernel["events"].chmod(0o666)
    else:
        original = kernel["events"].with_name("original-events")
        kernel["events"].rename(original)
        kernel["events"].symlink_to(original)
    with pytest.raises(BenchmarkHostObservationError, match="CAPTURE_INVALID"):
        host.OwnBenchmarkHostOomObserver(device="CPU", execution_id=EXECUTION_ID)


@pytest.mark.parametrize(
    "raw",
    (
        b"",
        b"x" * 4097,
        counters().rstrip(b"\n"),
        counters() + b"oom 0\n",
        counters().replace(b"oom 0\n", b"oom -1\n"),
        counters().replace(b"oom 0\n", b"oom 01\n"),
        counters().replace(b"oom 0\n", b"oom 18446744073709551616\n"),
        counters().replace(b"oom 0\n", b"oom 1.0\n"),
        counters().replace(b"oom 0\n", b"oom  0\n"),
        counters().replace(b"oom 0\n", b"oom\t0\n"),
        counters().replace(b"oom 0\n", b""),
        counters() + b"bad-key 0\n",
        counters() + b"\xff 0\n",
    ),
)
def test_invalid_counter_records_do_not_coerce_or_default(raw: bytes) -> None:
    with pytest.raises(BenchmarkHostObservationError):
        host._counters(raw)


@pytest.mark.parametrize(
    "fault", ("duplicate_mount", "wrong_type", "subtree", "local_only", "device", "missing")
)
def test_initial_mount_must_match_actual_fixed_cgroup2_scope(
    kernel: dict[str, Any], fault: str
) -> None:
    raw = kernel["mountinfo"]
    if fault == "duplicate_mount":
        raw *= 2
    elif fault == "wrong_type":
        raw = raw.replace(b"cgroup2", b"tmpfs")
    elif fault == "subtree":
        raw = raw.replace(b" / ", b" /foreign ")
    elif fault == "local_only":
        raw = raw.replace(b"cgroup rw", b"cgroup rw,memory_localevents")
    elif fault == "device":
        raw = raw.replace(raw.split()[2], b"1:999")
    else:
        raw = b"41 23 1:999 / /unrelated rw - tmpfs tmpfs rw\n"
    kernel["mountinfo"] = raw
    with pytest.raises(BenchmarkHostObservationError, match="CAPTURE_INVALID"):
        host.OwnBenchmarkHostOomObserver(device="CPU", execution_id=EXECUTION_ID)


@pytest.mark.parametrize(
    ("device", "execution"),
    (("CPU", "../escape"), ("CUDA", "A" * 32), ("OTHER", EXECUTION_ID), (True, EXECUTION_ID)),
)
def test_untrusted_device_or_execution_is_not_a_filesystem_path(
    device: Any, execution: Any
) -> None:
    with pytest.raises(BenchmarkHostObservationError, match="CAPTURE_INVALID"):
        host.OwnBenchmarkHostOomObserver(device=device, execution_id=execution)


def test_new_counter_is_supported_but_counter_set_cannot_drift(kernel: dict[str, Any]) -> None:
    overwrite(kernel["events"], counters() + b"sock_throttled 0\n")
    observer = host.OwnBenchmarkHostOomObserver(device="CPU", execution_id=EXECUTION_ID)
    assert observer.observe_delta() == 0
    overwrite(kernel["events"], counters())
    with pytest.raises(BenchmarkHostObservationError, match="COUNTER_RESET"):
        observer.observe_delta()


@pytest.mark.parametrize("kernel", ("CUDA",), indirect=True)
def test_cuda_uses_only_its_exact_benchmark_unit_without_gpu_calls(kernel: dict[str, Any]) -> None:
    observer = host.OwnBenchmarkHostOomObserver(device="CUDA", execution_id=EXECUTION_ID)
    assert observer.observe_delta() == 0
    with pytest.raises(BenchmarkHostObservationError, match="CAPTURE_INVALID"):
        host.OwnBenchmarkHostOomObserver(device="CPU", execution_id=EXECUTION_ID)


def test_captured_process_cannot_be_reused_after_fork(
    kernel: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    observer = host.OwnBenchmarkHostOomObserver(device="CPU", execution_id=EXECUTION_ID)
    original_pid = os.getpid()
    with monkeypatch.context() as patch:
        patch.setattr(host.os, "getpid", lambda: original_pid + 1)
        with pytest.raises(BenchmarkHostObservationError):
            observer.observe_delta()
    with pytest.raises(BenchmarkHostObservationError, match="POISONED"):
        observer.observe_delta()


def test_unchanged_zero_is_live_observation_not_a_cached_default(kernel: dict[str, Any]) -> None:
    observer = host.OwnBenchmarkHostOomObserver(device="CPU", execution_id=EXECUTION_ID)
    assert observer.observe_delta() == 0
    kernel["events"].chmod(0o666)
    with pytest.raises(BenchmarkHostObservationError):
        observer.observe_delta()
