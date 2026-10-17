"""Synthetic root kernel/systemd ports; no real PID1/GPU/lock or privileged operation."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_service import embedding_cuda_probe_resource_observation as owner

from tests.unit.embedding_benchmark_cuda_ready_fixtures import benchmark_cuda_ready
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_cuda_probe_resource_files import FakeKernel, metadata
from tests.unit.test_embedding_native_cuda_probe import case as case
from tests.unit.test_embedding_native_cuda_probe_ready import ready_case as ready_case
from tests.unit.test_embedding_runtime_process_identity import fdinfo


@pytest.fixture
def kernel(monkeypatch, ready_case):
    report = ready_case[2]
    k = FakeKernel()
    state = {
        "store": None,
        "pid1": ["80"],
        "unheld_pid1": False,
        "unheld_worker": False,
        "worker_fds": ["14"],
        "worker_lock_fds": {14},
        "expected_unit": "eom-embedding-native-cuda-probe@" + report.execution_id + ".service",
    }
    store = [
        {
            "fdname": "eom-gpu0-lease",
            "type": k.values[99].st_mode,
            "devno": [0, 2],
            "inode": 99,
            "rdevno": None,
            "path": "/mount-relative/gpu0.lock",
            "flags": "ro",
        }
    ]
    state["store"] = json.dumps(store).encode()
    real_lstat, real_stat = Path.lstat, Path.stat

    def lstat(path, *args, **kwargs):
        name = str(path)
        if name == "/run/eom-gpu-lease":
            return k.named[11]
        if name == "/run/eom-gpu-lease/gpu0.lock":
            return k.named[99]
        if name.startswith("/dev/nvidia"):
            return k.named[k.names[path.name]]
        return real_lstat(path, *args, **kwargs)

    def procstat(path, *args, **kwargs):
        if str(path).startswith("/proc/123/fd/"):
            n = int(path.name)
            return k.values[99 if n in state["worker_lock_fds"] else n + 10]
        if str(path).startswith("/proc/1/fd/"):
            return k.values[99]
        return real_stat(path, *args, **kwargs)

    def read(path, *, maximum, owner_uid):
        if str(path) == "/proc/456/mountinfo":
            assert owner_uid == 0 and maximum == 1024**2
            return b"24 1 0:2 / /run rw - tmpfs tmpfs rw\n"
        assert path.parent.name == "fdinfo" and maximum == 16384
        pid, number = int(path.parts[2]), int(path.name)
        assert owner_uid == (0 if pid == 1 else report.worker_uid)
        if pid == 1 or number in state["worker_lock_fds"]:
            raw = fdinfo(report.pid, 2, 99, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
            no_lock = state["unheld_pid1" if pid == 1 else "unheld_worker"]
            return raw.split(b"lock:")[0] if no_lock else raw
        value = k.values[number + 10]
        return fdinfo(report.pid, value.st_dev, value.st_ino, os.O_PATH | os.O_CLOEXEC).split(
            b"lock:"
        )[0]

    @contextmanager
    def scan(path):
        assert str(path) in {"/proc/1/fd", "/proc/123/fd"}
        names = state["pid1"] if str(path) == "/proc/1/fd" else state["worker_fds"]
        yield iter(SimpleNamespace(name=name) for name in names)

    def command(args, **kwargs):
        assert args[:4] == ("/usr/bin/systemd-analyze", "--no-pager", "--json=short", "fdstore")
        assert args[-1] == state["expected_unit"]
        assert kwargs["timeout"] == 10
        return SimpleNamespace(returncode=0, stdout=state["store"], stderr=b"")

    monkeypatch.setattr(Path, "lstat", lstat)
    monkeypatch.setattr(Path, "stat", procstat)
    monkeypatch.setattr(
        owner,
        "os",
        SimpleNamespace(
            getresuid=lambda: (0, 0, 0),
            getpid=lambda: 456,
            scandir=scan,
            stat=lambda path: procstat(Path(path)),
            major=os.major,
            minor=os.minor,
            O_RDONLY=os.O_RDONLY,
            O_ACCMODE=os.O_ACCMODE,
            O_PATH=os.O_PATH,
            O_CLOEXEC=os.O_CLOEXEC,
        ),
    )
    monkeypatch.setattr(owner, "read_live_runtime_os_file", read)
    monkeypatch.setattr(owner.subprocess, "run", command)
    return report, k, state, store


def observe(kernel):
    report, *_ = kernel
    return owner.observe_cuda_probe_resources(
        report,
        unit="eom-embedding-native-cuda-probe@" + report.execution_id + ".service",
        lease_gid=2468,
    )


def test_worker_and_pid1_real_lock_records_are_both_required_not_display_path(kernel):
    result = observe(kernel)
    assert result.pid1_descriptor == 80
    assert result.shared_gpu_lease.holder_pid == 123
    assert result.shared_gpu_lease.lock_epoch[1] == 99
    assert tuple(n.role for n in result.device_nodes) == tuple(owner.CUDA_DEVICE_NODE_SPECS)
    assert not hasattr(result, "assert_owned")


def benchmark_report(kernel):
    from eom_catalog_contracts.embedding_benchmark_cuda_ready import BenchmarkCudaReady

    prototype, _files, state, _store = kernel
    _, ready = benchmark_cuda_ready()
    body = ready.model_dump(mode="json")
    for name in (
        "execution_id",
        "pid",
        "start_time_ticks",
        "worker_uid",
        "worker_gid",
        "supplementary_gids",
        "resource_fds",
        "expected_device_capture",
    ):
        body[name] = prototype.model_dump(mode="json")[name]
    report = BenchmarkCudaReady.model_validate(seal(body, "ready_sha256"))
    state["expected_unit"] = f"eom-embedding-benchmark-cuda@{report.execution_id}.service"
    return report


def test_existing_probe_and_image_imports_do_not_eagerly_load_new_ready_contract():
    paths = os.environ["PYTHONPATH"].split(os.pathsep)
    code = """
import sys
sys.path[:0]=sys.argv[1:]
import eom_catalog_service.embedding_cuda_probe_resource_observation
assert 'eom_catalog_contracts.embedding_benchmark_cuda_ready' not in sys.modules
# Existing public package exports already load the old benchmark1.0 contract.
# This extension must not add an eager import of the new readiness branch.
assert not {'torch','numpy','transformers','tokenizers'}.intersection(sys.modules)
"""
    result = subprocess.run(
        (sys.executable, "-I", "-B", "-c", code, *paths), capture_output=True, timeout=10
    )
    assert result.returncode == 0, result.stderr.decode()


def test_benchmark_uses_its_own_message_and_exact_unit_with_the_same_kernel_fd_rules(kernel):
    report = benchmark_report(kernel)
    result = owner.observe_benchmark_cuda_ready_resources(
        report, unit=kernel[2]["expected_unit"], lease_gid=2468
    )
    assert result.pid1_descriptor == 80 and result.shared_gpu_lease.holder_pid == report.pid
    assert result.shared_gpu_lease.lock_epoch[1] == 99
    assert not hasattr(result, "assert_owned")


@pytest.mark.parametrize(
    "fault", ("probe_report", "probe_unit", "other_execution", "group", "pid1", "worker", "store")
)
def test_benchmark_cannot_borrow_another_purpose_or_skip_either_physical_lock(kernel, fault):
    report = benchmark_report(kernel)
    unit = kernel[2]["expected_unit"]
    group = 2468
    if fault == "probe_report":
        report = kernel[0]
    elif fault == "probe_unit":
        unit = "eom-embedding-native-cuda-probe@" + report.execution_id + ".service"
    elif fault == "other_execution":
        unit = "eom-embedding-benchmark-cuda@" + "0" * 32 + ".service"
    elif fault == "group":
        group = 1
    elif fault == "pid1":
        kernel[2]["unheld_pid1"] = True
    elif fault == "worker":
        kernel[2]["unheld_worker"] = True
    else:
        kernel[2]["store"] = b"[]"
    with pytest.raises(ValueError, match="BENCHMARK_CUDA_RESOURCE_OBSERVATION_INVALID"):
        owner.observe_benchmark_cuda_ready_resources(report, unit=unit, lease_gid=group)


@pytest.mark.parametrize(
    "field,value",
    [
        ("fdname", "other"),
        ("type", True),
        ("type", 0),
        ("inode", True),
        ("inode", 100),
        ("devno", [0, 3]),
        ("devno", [False, 2]),
        ("flags", "rw"),
        ("rdevno", [0, 0]),
        ("path", "relative"),
        ("path", "/bad\npath"),
    ],
)
def test_store_metadata_must_match_exact_regular_readonly_inode(kernel, field, value):
    result = observe(kernel)
    rows = copy.deepcopy(kernel[3])
    rows[0][field] = value
    with pytest.raises(ValueError):
        owner.validate_cuda_probe_fdstore(json.dumps(rows).encode(), result.shared_gpu_lease)


@pytest.mark.parametrize(
    "raw",
    [
        b"[]",
        b"[{},{}]",
        b"{}",
        b"null",
        b"NaN",
        b"[" * 17 + b"]" * 17,
        b'[ {"inode":99,"inode":99} ]',
        b"x" * 16385,
    ],
)
def test_store_external_json_is_bounded_unique_and_exact(kernel, raw):
    result = observe(kernel)
    with pytest.raises(ValueError):
        owner.validate_cuda_probe_fdstore(raw, result.shared_gpu_lease)


@pytest.mark.parametrize(
    "fault",
    [
        "unheld_worker",
        "unheld_pid1",
        "missing_pid1",
        "duplicate_pid1",
        "invalid_pid1",
        "too_many_pid1",
        "named_lock_changed",
        "device_changed",
    ],
)
def test_resource_drift_or_unheld_same_inode_never_passes(kernel, monkeypatch, fault):
    _, k, state, _ = kernel
    if fault.startswith("unheld"):
        state[fault] = True
    elif fault == "missing_pid1":
        state["pid1"] = []
    elif fault == "duplicate_pid1":
        state["pid1"] = ["80", "81"]
    elif fault == "invalid_pid1":
        state["pid1"] = ["../80"]
    elif fault == "too_many_pid1":
        monkeypatch.setattr(owner, "_MAX_PID1_FDS", 1)
        state["pid1"] = ["80", "81"]
    elif fault == "named_lock_changed":
        k.named[99] = metadata(k.values[99].st_mode, 100, device=2, gid=2468)
    else:
        k.named[20] = metadata(k.values[20].st_mode, 500, rdev=k.values[20].st_rdev)
    with pytest.raises(ValueError):
        observe(kernel)


def test_nonroot_and_unrelated_unit_have_no_resource_observation(kernel, monkeypatch):
    monkeypatch.setattr(owner.os, "getresuid", lambda: (1000, 1000, 1000))
    with pytest.raises(ValueError):
        observe(kernel)


def test_retained_phase_needs_no_worker_fd_and_does_not_release_the_guard(kernel):
    report, _, state, _ = kernel
    observed = observe(kernel)
    state["unheld_worker"] = True
    assert (
        owner.observe_cuda_probe_retained_resources(
            observed, unit="eom-embedding-native-cuda-probe@" + report.execution_id + ".service"
        )
        == observed
    )


@pytest.mark.parametrize("fault", ("lost_lock", "descriptor_changed", "device_changed"))
def test_retained_phase_rejects_lost_or_changed_physical_fence(kernel, fault):
    report, k, state, _ = kernel
    observed = observe(kernel)
    if fault == "lost_lock":
        state["unheld_pid1"] = True
    elif fault == "descriptor_changed":
        state["pid1"] = ["81"]
    else:
        k.named[20] = metadata(k.values[20].st_mode, 500, rdev=k.values[20].st_rdev)
    with pytest.raises(ValueError):
        owner.observe_cuda_probe_retained_resources(
            observed, unit="eom-embedding-native-cuda-probe@" + report.execution_id + ".service"
        )


@pytest.fixture
def released(kernel, monkeypatch):
    observed = observe(kernel)
    _, k, state, _ = kernel
    events = []

    def opened(path, flags):
        assert path == owner._LOCK
        assert flags == os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
        events.append("open")
        return 700

    def flock(descriptor, flags):
        assert descriptor == 700 and flags == owner.fcntl.LOCK_EX | owner.fcntl.LOCK_NB
        events.append("flock")
        if state.get("still_retained"):
            raise BlockingIOError("synthetic retained open description")

    monkeypatch.setattr(owner.os, "open", opened, raising=False)
    monkeypatch.setattr(owner.os, "fstat", lambda fd: k.values[99], raising=False)
    monkeypatch.setattr(owner.os, "close", lambda fd: events.append("close"), raising=False)
    for name in ("O_NOFOLLOW", "O_NONBLOCK"):
        monkeypatch.setattr(owner.os, name, getattr(os, name), raising=False)
    monkeypatch.setattr(owner.fcntl, "flock", flock)
    return observed, k, state, events


def test_released_lock_holds_new_description_through_post_checks_and_only_closes_it(released):
    observed, _, _, events = released
    with owner.hold_released_cuda_probe_resources(observed):
        assert events == ["open", "flock"]
        events.append("post-checks")
    assert events == ["open", "flock", "post-checks", "close"]


def test_retained_lock_prevents_release_proof_without_unlock_or_reset(released):
    observed, _, state, events = released
    state["still_retained"] = True
    with (
        pytest.raises(ValueError, match="RELEASE_UNCERTAIN"),
        owner.hold_released_cuda_probe_resources(observed),
    ):
        pytest.fail("retained flock cannot authorize post-retirement success")
    assert events == ["open", "flock", "close"]


def test_released_lock_drift_and_body_failure_still_close_only_new_description(released):
    observed, k, _, events = released
    with (
        pytest.raises(ValueError, match="RESOURCE_OBSERVATION_INVALID"),
        owner.hold_released_cuda_probe_resources(observed),
    ):
        k.named[99] = metadata(k.values[99].st_mode, 100, device=2, gid=2468)
    assert events[-1] == "close"
