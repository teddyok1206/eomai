"""Synthetic root kernel/systemd ports; no real PID1/GPU/lock or privileged operation."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import replace
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


def index_report(kernel):
    from eom_catalog_contracts.embedding_native_cuda_index_ready import NativeCudaIndexReady

    prototype, _files, state, _store = kernel
    body = {
        "schema_version": "embedding-native-cuda-index-ready/1.0",
        "purpose": "INDEX",
        "evidence_state": "RETENTION_REQUESTED_NOT_COMPUTE_ADMITTED",
        "job_id": "job_" + "b" * 32,
        "launch_association_sha256": "sha256:" + "c" * 64,
        "input_raw_sha256": "sha256:" + "d" * 64,
        "request_sha256": "sha256:" + "e" * 64,
        "input_set_sha256": "sha256:" + "f" * 64,
        "receipt_raw_sha256": "sha256:" + "a" * 64,
        **{
            name: value
            for name, value in prototype.model_dump(mode="json").items()
            if name
            in {
                "execution_id",
                "configuration",
                "fdstore_name",
                "pid",
                "start_time_ticks",
                "worker_uid",
                "worker_gid",
                "supplementary_gids",
                "resource_fds",
                "expected_device_capture",
                "cuda_initialization_calls",
                "cuda_synchronize_calls",
                "model_constructor_calls",
                "tokenizer_constructor_calls",
                "forward_calls",
            }
        },
    }
    report = NativeCudaIndexReady.model_validate(seal(body, "ready_sha256"))
    state["expected_unit"] = f"eom-embedding-native-cuda-index@{report.execution_id}.service"
    return report


def test_existing_probe_and_image_imports_do_not_eagerly_load_new_ready_contract():
    paths = os.environ["PYTHONPATH"].split(os.pathsep)
    code = """
import sys
sys.path[:0]=sys.argv[1:]
import eom_catalog_service.embedding_cuda_probe_resource_observation
assert 'eom_catalog_contracts.embedding_benchmark_cuda_ready' not in sys.modules
assert 'eom_catalog_contracts.embedding_native_cuda_index_ready' not in sys.modules
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


def test_benchmark_retained_phase_uses_its_own_closed_unit_family_without_dead_worker_fds(kernel):
    report = benchmark_report(kernel)
    unit = kernel[2]["expected_unit"]
    observed = owner.observe_benchmark_cuda_ready_resources(report, unit=unit, lease_gid=2468)
    kernel[2]["unheld_worker"] = True
    assert owner.observe_benchmark_cuda_retained_resources(observed, unit=unit) is observed
    with pytest.raises(ValueError):
        owner.observe_cuda_probe_retained_resources(observed, unit=unit)


@pytest.mark.parametrize(
    "fault",
    ("probe_unit", "pid1", "store", "device", "root", "unit_type", "resource_type", "descriptor"),
)
def test_benchmark_retained_phase_still_checks_actual_physical_fencing(kernel, monkeypatch, fault):
    report = benchmark_report(kernel)
    unit = kernel[2]["expected_unit"]
    observed = owner.observe_benchmark_cuda_ready_resources(report, unit=unit, lease_gid=2468)
    if fault == "probe_unit":
        unit = f"eom-embedding-native-cuda-probe@{report.execution_id}.service"
    elif fault == "pid1":
        kernel[2]["unheld_pid1"] = True
    elif fault == "store":
        kernel[2]["store"] = b"[]"
    elif fault == "device":
        kernel[1].named[20] = metadata(
            kernel[1].values[20].st_mode, 500, rdev=kernel[1].values[20].st_rdev
        )
    elif fault == "root":
        monkeypatch.setattr(owner.os, "getresuid", lambda: (1000,) * 3)
    elif fault == "unit_type":
        unit = None
    elif fault == "resource_type":
        observed = None
    else:
        observed = replace(observed, pid1_descriptor=observed.pid1_descriptor + 1)
    with pytest.raises(ValueError, match="BENCHMARK_CUDA_RESOURCE_OBSERVATION_INVALID"):
        owner.observe_benchmark_cuda_retained_resources(observed, unit=unit)


def test_benchmark_retained_metadata_timeout_is_uncertain_not_cleanup_permission(
    kernel, monkeypatch
):
    report = benchmark_report(kernel)
    unit = kernel[2]["expected_unit"]
    observed = owner.observe_benchmark_cuda_ready_resources(report, unit=unit, lease_gid=2468)

    def timeout(*_a, **_kw):
        raise subprocess.TimeoutExpired("synthetic fdstore read", 10)

    monkeypatch.setattr(owner.subprocess, "run", timeout)
    with pytest.raises(ValueError, match="BENCHMARK_CUDA_RESOURCE_OBSERVATION_INVALID"):
        owner.observe_benchmark_cuda_retained_resources(observed, unit=unit)


def test_pre_ready_terminal_resources_have_no_invented_birth_or_worker_fd_read(kernel):
    report = benchmark_report(kernel)
    kernel[2]["unheld_worker"] = True
    observed = owner.observe_unacknowledged_benchmark_gpu_resources(
        unit=kernel[2]["expected_unit"], terminal_pid=report.pid, lease_gid=2468
    )
    assert observed.pid1_descriptor == 80 and observed.shared_gpu_lease.holder_pid == report.pid
    assert not hasattr(observed.shared_gpu_lease, "holder_start_time_ticks")
    assert not hasattr(observed, "assert_owned")


def test_index_unacknowledged_resources_use_actual_terminal_pid_without_worker_or_ready(kernel):
    report = index_report(kernel)
    kernel[2]["unheld_worker"] = True
    observed = owner.observe_unacknowledged_native_cuda_index_gpu_resources(
        unit=kernel[2]["expected_unit"], terminal_pid=report.pid, lease_gid=2468
    )
    assert type(observed) is owner.UnacknowledgedNativeCudaIndexGpuResources
    assert observed.pid1_descriptor == 80 and observed.shared_gpu_lease.holder_pid == report.pid
    assert not hasattr(observed.shared_gpu_lease, "holder_start_time_ticks")
    assert not hasattr(observed, "ready") and not hasattr(observed, "assert_owned")


@pytest.mark.parametrize("fault", ("pid", "group", "benchmark", "pid1", "store", "root"))
def test_index_unacknowledged_resources_never_borrow_other_unit_or_authority(
    kernel, monkeypatch, fault
):
    report = index_report(kernel)
    unit, pid, gid = kernel[2]["expected_unit"], report.pid, 2468
    if fault == "pid":
        pid += 1
    elif fault == "group":
        gid += 1
    elif fault == "benchmark":
        unit = "eom-embedding-benchmark-cuda@" + report.execution_id + ".service"
    elif fault == "pid1":
        kernel[2]["unheld_pid1"] = True
    elif fault == "store":
        kernel[2]["store"] = b"[]"
    else:
        monkeypatch.setattr(owner.os, "getresuid", lambda: (1000,) * 3)
    with pytest.raises(ValueError, match="NATIVE_CUDA_INDEX_RESOURCE_OBSERVATION_INVALID"):
        owner.observe_unacknowledged_native_cuda_index_gpu_resources(
            unit=unit, terminal_pid=pid, lease_gid=gid
        )


@pytest.mark.parametrize("fault", ("pid", "group", "probe", "pid1", "store", "root"))
def test_pre_ready_terminal_resources_require_exact_unit_physical_identity(
    kernel, monkeypatch, fault
):
    report = benchmark_report(kernel)
    unit, pid, gid = kernel[2]["expected_unit"], report.pid, 2468
    if fault == "pid":
        pid += 1
    elif fault == "group":
        gid += 1
    elif fault == "probe":
        unit = f"eom-embedding-native-cuda-probe@{report.execution_id}.service"
    elif fault == "pid1":
        kernel[2]["unheld_pid1"] = True
    elif fault == "store":
        kernel[2]["store"] = b"[]"
    else:
        monkeypatch.setattr(owner.os, "getresuid", lambda: (1000,) * 3)
    with pytest.raises(ValueError, match="BENCHMARK_CUDA_RESOURCE_OBSERVATION_INVALID"):
        owner.observe_unacknowledged_benchmark_gpu_resources(
            unit=unit, terminal_pid=pid, lease_gid=gid
        )


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


def test_index_uses_its_exact_ready_and_unit_with_the_existing_kernel_checks(kernel):
    report = index_report(kernel)
    result = owner.observe_native_cuda_index_ready_resources(
        report, unit=kernel[2]["expected_unit"], lease_gid=2468
    )
    assert type(result) is owner.CudaProbeResourceObservation
    assert result.pid1_descriptor == 80 and result.shared_gpu_lease.holder_pid == report.pid
    assert result.shared_gpu_lease.holder_start_time_ticks == report.start_time_ticks
    assert result.shared_gpu_lease.lock_epoch[1] == 99
    assert not hasattr(result, "assert_owned") and not hasattr(result, "root_ack")
    with pytest.raises(ValueError):
        owner.observe_cuda_probe_resources(report, unit=kernel[2]["expected_unit"], lease_gid=2468)
    with pytest.raises(ValueError):
        owner.observe_benchmark_cuda_ready_resources(
            report, unit=kernel[2]["expected_unit"], lease_gid=2468
        )


@pytest.mark.parametrize(
    "fault",
    (
        "probe_report",
        "benchmark_report",
        "dict",
        "probe_unit",
        "benchmark_unit",
        "other_execution",
        "unit_type",
        "root",
        "partial_root",
        "purpose",
        "hash",
        "alias",
        "group",
        "worker",
        "pid1",
        "store",
        "store_inode",
        "device",
    ),
)
def test_index_ready_cannot_borrow_authority_or_skip_either_physical_lock(
    kernel, monkeypatch, fault
):
    report = index_report(kernel)
    unit, group = kernel[2]["expected_unit"], 2468
    if fault == "probe_report":
        report = kernel[0]
    elif fault == "benchmark_report":
        report = benchmark_report(kernel)
    elif fault == "dict":
        report = report.model_dump(mode="json")
    elif fault == "probe_unit":
        unit = f"eom-embedding-native-cuda-probe@{report.execution_id}.service"
    elif fault == "benchmark_unit":
        unit = f"eom-embedding-benchmark-cuda@{report.execution_id}.service"
    elif fault == "other_execution":
        unit = "eom-embedding-native-cuda-index@" + "0" * 32 + ".service"
    elif fault == "unit_type":
        unit = None
    elif fault in {"root", "partial_root"}:
        identity = (1000,) * 3 if fault == "root" else (0, 1000, 0)
        monkeypatch.setattr(owner.os, "getresuid", lambda: identity)
    elif fault == "purpose":
        report = report.model_copy(update={"purpose": "BENCHMARK"})
    elif fault == "hash":
        report = report.model_copy(update={"ready_sha256": "sha256:" + "0" * 64})
    elif fault == "alias":
        report = report.model_copy(
            update={
                "resource_fds": report.resource_fds.model_copy(
                    update={"lease_fd": report.resource_fds.nvidia0_fd}
                )
            }
        )
    elif fault == "group":
        group = 1
    elif fault in {"worker", "pid1"}:
        kernel[2]["unheld_" + fault] = True
    elif fault == "store":
        kernel[2]["store"] = b"[]"
    elif fault == "store_inode":
        rows = copy.deepcopy(kernel[3])
        rows[0]["inode"] += 1
        kernel[2]["store"] = json.dumps(rows).encode()
    else:
        kernel[1].named[20] = metadata(
            kernel[1].values[20].st_mode, 500, rdev=kernel[1].values[20].st_rdev
        )
    with pytest.raises(ValueError, match="NATIVE_CUDA_INDEX_RESOURCE_OBSERVATION_INVALID"):
        owner.observe_native_cuda_index_ready_resources(report, unit=unit, lease_gid=group)


def test_index_retained_checks_only_same_original_physical_fence_not_dead_worker_fds(kernel):
    report = index_report(kernel)
    unit = kernel[2]["expected_unit"]
    observed = owner.observe_native_cuda_index_ready_resources(report, unit=unit, lease_gid=2468)
    kernel[2]["unheld_worker"] = True
    assert owner.observe_native_cuda_index_retained_resources(observed, unit=unit) is observed
    with pytest.raises(ValueError):
        owner.observe_cuda_probe_retained_resources(observed, unit=unit)
    with pytest.raises(ValueError):
        owner.observe_benchmark_cuda_retained_resources(observed, unit=unit)


@pytest.mark.parametrize(
    "fault",
    ("probe", "benchmark", "unit_type", "root", "type", "descriptor", "pid1", "store"),
)
def test_index_retained_never_uses_another_family_or_lost_store(kernel, monkeypatch, fault):
    report = index_report(kernel)
    unit = kernel[2]["expected_unit"]
    observed = owner.observe_native_cuda_index_ready_resources(report, unit=unit, lease_gid=2468)
    if fault in {"probe", "benchmark"}:
        prefix = (
            "eom-embedding-native-cuda-probe"
            if fault == "probe"
            else "eom-embedding-benchmark-cuda"
        )
        unit = f"{prefix}@{report.execution_id}.service"
    elif fault == "unit_type":
        unit = None
    elif fault == "root":
        monkeypatch.setattr(owner.os, "getresuid", lambda: (1000,) * 3)
    elif fault == "type":
        observed = None
    elif fault == "descriptor":
        observed = replace(observed, pid1_descriptor=81)
    elif fault == "pid1":
        kernel[2]["unheld_pid1"] = True
    else:
        kernel[2]["store"] = b"[]"
    with pytest.raises(ValueError, match="NATIVE_CUDA_INDEX_RESOURCE_OBSERVATION_INVALID"):
        owner.observe_native_cuda_index_retained_resources(observed, unit=unit)


@pytest.mark.parametrize("phase", ("ready", "retained"))
def test_index_fdstore_timeout_is_uncertain_not_ack_or_cleanup(kernel, monkeypatch, phase):
    report = index_report(kernel)
    unit = kernel[2]["expected_unit"]
    observed = owner.observe_native_cuda_index_ready_resources(report, unit=unit, lease_gid=2468)

    def timeout(*_a, **_kw):
        raise subprocess.TimeoutExpired("synthetic fdstore read", 10)

    monkeypatch.setattr(owner.subprocess, "run", timeout)
    with pytest.raises(ValueError, match="NATIVE_CUDA_INDEX_RESOURCE_OBSERVATION_INVALID"):
        if phase == "ready":
            owner.observe_native_cuda_index_ready_resources(report, unit=unit, lease_gid=2468)
        else:
            owner.observe_native_cuda_index_retained_resources(observed, unit=unit)


@pytest.fixture
def index_released(kernel, released):
    report = index_report(kernel)
    unit = kernel[2]["expected_unit"]
    observed = owner.observe_native_cuda_index_ready_resources(report, unit=unit, lease_gid=2468)
    return observed, *released[1:], unit


def test_index_released_scope_holds_only_its_new_description(index_released):
    observed, _, _, events, unit = index_released
    with owner.hold_released_native_cuda_index_resources(observed, unit=unit):
        assert events == ["open", "flock"]
        events.append("post-checks")
    assert events == ["open", "flock", "post-checks", "close"]


def unacknowledged_index_resources(original):
    lease = original.shared_gpu_lease
    return owner.UnacknowledgedNativeCudaIndexGpuResources(
        original.device_nodes,
        owner.TerminalCudaLeaseIdentity(
            lease.lease_gid, lease.parent_epoch, lease.lock_epoch, lease.holder_pid
        ),
        original.pid1_descriptor,
    )


def test_unacknowledged_index_release_holds_same_inode_without_fabricated_birth(index_released):
    original, _, _, events, unit = index_released
    resources = unacknowledged_index_resources(original)
    with owner.hold_released_unacknowledged_native_cuda_index_resources(resources, unit=unit):
        assert events == ["open", "flock"]
        events.append("post-checks")
    assert events == ["open", "flock", "post-checks", "close"]


def test_unacknowledged_index_release_cannot_unlock_still_retained_description(index_released):
    original, _, state, events, unit = index_released
    state["still_retained"] = True
    with (
        pytest.raises(ValueError, match="RELEASE_UNCERTAIN"),
        owner.hold_released_unacknowledged_native_cuda_index_resources(
            unacknowledged_index_resources(original), unit=unit
        ),
    ):
        pytest.fail("old retained description is not released")
    assert events == ["open", "flock", "close"]


@pytest.mark.parametrize("fault", ("root", "benchmark", "type"))
def test_unacknowledged_index_release_rejects_other_family_before_open(
    index_released, monkeypatch, fault
):
    original, _, _, events, unit = index_released
    resources = unacknowledged_index_resources(original)
    if fault == "root":
        monkeypatch.setattr(owner.os, "getresuid", lambda: (1000,) * 3)
    elif fault == "benchmark":
        unit = unit.replace("native-cuda-index", "benchmark-cuda")
    else:
        resources = owner.UnacknowledgedBenchmarkGpuResources(
            resources.device_nodes, resources.shared_gpu_lease, resources.pid1_descriptor
        )
    with (
        pytest.raises(ValueError),
        owner.hold_released_unacknowledged_native_cuda_index_resources(resources, unit=unit),
    ):
        pytest.fail("wrong family cannot obtain an INDEX scope")
    assert events == []


@pytest.mark.parametrize("fault", ("root", "probe", "benchmark", "unit_type", "type"))
def test_index_released_scope_rejects_bad_owner_or_family_before_opening(
    index_released, monkeypatch, fault
):
    observed, _, _, events, unit = index_released
    if fault == "root":
        monkeypatch.setattr(owner.os, "getresuid", lambda: (1000,) * 3)
    elif fault == "probe":
        unit = unit.replace("cuda-index", "cuda-probe")
    elif fault == "benchmark":
        unit = unit.replace("native-cuda-index", "benchmark-cuda")
    elif fault == "unit_type":
        unit = None
    else:
        observed = None
    with (
        pytest.raises(ValueError, match="NATIVE_CUDA_INDEX_RESOURCE_OBSERVATION_INVALID"),
        owner.hold_released_native_cuda_index_resources(observed, unit=unit),
    ):
        pytest.fail("invalid INDEX owner cannot obtain a released-lock scope")
    assert events == []


def test_index_release_rejects_still_retained_lock_without_unlock_or_store_removal(index_released):
    observed, _, state, events, unit = index_released
    state["still_retained"] = True
    with (
        pytest.raises(ValueError, match="RELEASE_UNCERTAIN"),
        owner.hold_released_native_cuda_index_resources(observed, unit=unit),
    ):
        pytest.fail("retained old flock is not released INDEX evidence")
    assert events == ["open", "flock", "close"]


def test_index_release_detects_post_check_inode_drift_and_closes_only_new_fd(index_released):
    observed, k, _, events, unit = index_released
    with (
        pytest.raises(ValueError, match="RESOURCE_OBSERVATION_INVALID"),
        owner.hold_released_native_cuda_index_resources(observed, unit=unit),
    ):
        k.named[99] = metadata(k.values[99].st_mode, 100, device=2, gid=2468)
    assert events == ["open", "flock", "close"]


def test_index_release_does_not_relabel_caller_failure_as_retirement(index_released):
    observed, _, _, events, unit = index_released
    failure = RuntimeError("synthetic original caller failure")
    with (
        pytest.raises(RuntimeError) as error,
        owner.hold_released_native_cuda_index_resources(observed, unit=unit),
    ):
        raise failure
    assert error.value is failure
    assert events == ["open", "flock", "close"]


def allocation_report(kernel):
    from eom_catalog_contracts.embedding_gpu_control import parse_embedding_gpu_control

    from tests.unit.test_embedding_gpu_control import control_case

    prototype, _, state, _ = kernel
    body = control_case()[1].model_dump(mode="json")
    for field in (
        "pid",
        "start_time_ticks",
        "worker_uid",
        "worker_gid",
        "supplementary_gids",
        "resource_fds",
        "expected_device_capture",
    ):
        body[field] = prototype.model_dump(mode="json")[field]
    report = parse_embedding_gpu_control(seal(body, "message_sha256"))
    instance = report.allocation_attempt_id.removeprefix("embeddingallocation_")
    state["expected_unit"] = f"eom-embedding-native-gpu-batch@{instance}.service"
    return report


def test_allocation_uses_its_own_ready_and_unit_for_both_kernel_locks(kernel):
    report = allocation_report(kernel)
    observed = owner.observe_embedding_gpu_allocation_resources(
        report, unit=kernel[2]["expected_unit"], lease_gid=2468
    )
    assert observed.pid1_descriptor == 80
    assert observed.shared_gpu_lease.holder_pid == report.pid
    assert observed.shared_gpu_lease.holder_start_time_ticks == report.start_time_ticks
    with pytest.raises(ValueError):
        owner.observe_native_cuda_index_ready_resources(
            report, unit=kernel[2]["expected_unit"], lease_gid=2468
        )
    kernel[2]["unheld_worker"] = True
    assert (
        owner.observe_embedding_gpu_batch_retained_resources(
            observed, unit=kernel[2]["expected_unit"]
        )
        is observed
    )  # terminal phase uses PID1; no dead-worker FD is invented


@pytest.mark.parametrize(
    "fault",
    [
        "dict",
        "probe_report",
        "unit",
        "other_attempt",
        "uid",
        "group",
        "worker",
        "pid1",
        "store",
        "hash",
        "extra",
        "timeout",
    ],
)
def test_allocation_does_not_borrow_other_authority_or_ignore_physical_fences(
    kernel, monkeypatch, fault
):
    report = allocation_report(kernel)
    unit, group = kernel[2]["expected_unit"], 2468
    if fault == "dict":
        report = report.model_dump(mode="json")
    elif fault == "probe_report":
        report = kernel[0]
    elif fault == "unit":
        unit = "eom-embedding-native-cuda-index@" + "a" * 32 + ".service"
    elif fault == "other_attempt":
        unit = "eom-embedding-native-gpu-batch@" + "b" * 32 + ".service"
    elif fault == "uid":
        monkeypatch.setattr(owner.os, "getresuid", lambda: (0, 1234, 0))
    elif fault == "group":
        group = 1234
    elif fault in ("worker", "pid1"):
        kernel[2]["unheld_" + fault] = True
    elif fault == "store":
        kernel[2]["store"] = b"[]"
    elif fault == "hash":
        report = report.model_copy(update={"message_sha256": "sha256:" + "0" * 64})
    elif fault == "extra":
        report = report.model_copy(update={"authority": "ROOT"})
    else:

        def timed_out(*args, **kwargs):
            raise subprocess.TimeoutExpired(args[0], 10)

        monkeypatch.setattr(owner.subprocess, "run", timed_out)
    with pytest.raises(ValueError, match="EMBEDDING_GPU_ALLOCATION_RESOURCE_OBSERVATION_INVALID"):
        owner.observe_embedding_gpu_allocation_resources(report, unit=unit, lease_gid=group)


def test_gpu_batch_release_retains_same_inode_and_never_unlocks_old_description(index_released):
    observed, _, _, events, _ = index_released
    unit = "eom-embedding-native-gpu-batch@" + "a" * 32 + ".service"
    with owner.hold_released_embedding_gpu_batch_resources(observed, unit=unit):
        assert events == ["open", "flock"]
    assert events == ["open", "flock", "close"]
