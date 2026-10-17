"""CUDA executable ordering with explicit doubles; no model, real Job or root ACK."""

import os
import signal
import subprocess
import sys
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_service import embedding_benchmark_cuda as cuda
from eom_catalog_service import embedding_benchmark_launch as launch

from tests.unit.embedding_benchmark_cuda_ready_fixtures import benchmark_cuda_ready
from tests.unit.test_embedding_benchmark_cpu import arguments


@pytest.mark.parametrize(
    "fault",
    (
        None,
        "unreserved",
        "pending",
        "expired",
        "timeout",
        "uid",
        "bool_uid",
        "pid",
        "signo",
        "late",
    ),
)
def test_ack_is_root_only_bounded_and_preserves_observable_signal_reservation(monkeypatch, fault):
    clock = [100]
    waits = []
    deadline = 200
    monkeypatch.setattr(cuda.time, "monotonic_ns", lambda: clock[0])
    monkeypatch.setattr(
        cuda.signal,
        "pthread_sigmask",
        lambda *_a: set() if fault == "unreserved" else {signal.SIGUSR1},
    )
    monkeypatch.setattr(
        cuda.signal, "sigpending", lambda: {signal.SIGUSR1} if fault == "pending" else set()
    )
    monkeypatch.setattr(cuda.time, "sleep", lambda _s: clock.__setitem__(0, deadline))

    def receive(signals, timeout):
        waits.append(timeout)
        assert signals == {signal.SIGUSR1} and timeout == 0
        if fault == "timeout":
            return None
        if fault == "late":
            clock[0] = deadline
        return SimpleNamespace(
            si_uid=1 if fault == "uid" else False if fault == "bool_uid" else 0,
            si_pid=0 if fault == "pid" else 100,
            si_signo=signal.SIGUSR2 if fault == "signo" else signal.SIGUSR1,
        )

    monkeypatch.setattr(cuda.signal, "sigtimedwait", receive)
    if fault in {None, "pending"}:
        cuda._wait_root_ack(deadline)
        assert waits == [0]
    else:
        with pytest.raises(ValueError, match="BENCHMARK_CUDA_"):
            cuda._wait_root_ack(100 if fault == "expired" else deadline)
        if fault in {"expired", "unreserved"}:
            assert not waits


@pytest.mark.parametrize("fault", (None, "identity", "execute"))
def test_main_reserves_signal_before_identity_and_optional_imports(monkeypatch, fault):
    events = []
    monkeypatch.setattr(sys, "argv", ["fixed-unit", *arguments()])
    monkeypatch.setattr(cuda, "discard_native_embedding_diagnostics", lambda: nullcontext())

    def event(value):
        events.append(value)
        if fault == value:
            raise ValueError("synthetic " + value)

    def reserve(how, signals):
        assert how == signal.SIG_BLOCK and signals == {signal.SIGUSR1}
        event("reserve")

    def identity(profile):
        assert profile == "CUDA_INDEX_FP32"
        event("identity")

    def execute(pins, started):
        assert pins.owner_pid == os.getpid() and started > 0
        event("execute")
        return 0

    monkeypatch.setattr(cuda.signal, "pthread_sigmask", reserve)
    monkeypatch.setattr(cuda.signal, "sigpending", lambda: set())
    monkeypatch.setattr(cuda, "require_native_embedding_identity", identity)
    monkeypatch.setattr(cuda, "_execute", execute)
    assert cuda.main() == (0 if fault is None else 1)
    assert events == (
        ["reserve", "identity"] if fault == "identity" else ["reserve", "identity", "execute"]
    )


@pytest.mark.parametrize(
    "fault",
    (
        None,
        "files",
        "proof",
        "lease",
        "resources",
        "retention",
        "ready",
        "ack",
        "device",
        "channel",
        "backend",
        "body",
        "backend-close",
        "channel-close",
        "device-close",
        "resources-close",
        "lease-close",
        "failed-result",
    ),
)
def test_retention_ready_root_ack_device_peer_then_model_and_reverse_cleanup(monkeypatch, fault):
    import eom_gpu_lease
    from eom_catalog_service import embedding_benchmark_activation as activation
    from eom_catalog_service import embedding_benchmark_entrypoint as leaf
    from eom_catalog_service import embedding_cuda_probe_resource_files as resource_files
    from eom_catalog_service import embedding_device_benchmark_files as local_files
    from eom_catalog_service import embedding_native_cuda_backend as backend_module

    invocation, ready = benchmark_cuda_ready()
    device = ready.expected_device_capture
    raw = list(arguments())
    raw[0], raw[1] = invocation.execution_id, ready.invocation_raw_sha256
    pins = launch.parse_benchmark_launch_pins(tuple(raw))
    events = []

    def event(value):
        events.append(value)
        if fault == value:
            raise ValueError("synthetic " + value)

    class Files:
        def __init__(self, fd, **kwargs):
            assert fd == 0
            assert kwargs == dict(
                profile="CUDA_INDEX_FP32",
                execution_id=invocation.execution_id,
                invocation_raw_sha256=ready.invocation_raw_sha256,
            )

        def __enter__(self):
            event("files")
            return self

        def __exit__(self, *_a):
            event("files-close")

        def read_invocation(self):
            return invocation

        def write_cuda_ready(self, observed):
            assert observed.job_id == ready.job_id
            assert observed.resource_fds == ready.resource_fds
            assert observed.expected_device_capture == device
            assert observed.pid == os.getpid()
            event("ready")

        def assert_current(self):
            event("files-current")

    class Lease:
        def close(self):
            event("lease-close")

    class Resources:
        shared_gpu_lease = SimpleNamespace(holder_pid=os.getpid(), holder_start_time_ticks=999)
        resource_descriptors = ready.resource_fds

        def assert_current(self):
            event("resources-current")

    class Ownership:
        def assert_owned(self):
            event("ownership-current")

    class Channel:
        def close(self):
            event("channel-close")

    lease, resources, ownership, channel = Lease(), Resources(), Ownership(), Channel()

    def expected_device(observed):
        assert observed is invocation
        event("proof")
        return device

    def acquire():
        event("lease")
        return lease

    def retain(observed):
        assert observed is lease
        event("retention")

    @contextmanager
    def capture(observed_device, observed_lease):
        assert observed_device is device and observed_lease is lease
        event("resources")
        try:
            yield resources
        finally:
            event("resources-close")

    @contextmanager
    def opened(observed):
        assert observed is resources
        event("device")
        try:
            yield ownership
        finally:
            event("device-close")

    def channel_factory(observed, **kwargs):
        assert observed is invocation and kwargs["activation_fd"] == 3
        assert kwargs["expires_ns"] == pins.expires_ns
        peer = kwargs["expected_peer"]
        assert (peer.pid, peer.uid, peer.gid) == (os.getpid(), 990, 990)
        kwargs["peer_fence"](peer)
        event("channel")
        return channel

    @contextmanager
    def backend(configuration, **kwargs):
        assert configuration == ready.configuration
        assert kwargs == dict(receipt_raw_sha256=ready.receipt_raw_sha256, ownership=ownership)
        event("backend")
        try:
            yield "synthetic-backend"
        finally:
            event("backend-close")

    def run(files, factory, observed_channel, **kwargs):
        assert type(files) is Files and observed_channel is channel
        assert kwargs == dict(
            profile="CUDA_INDEX_FP32", entry_started_ns=123, expires_ns=pins.expires_ns
        )
        with factory() as observed:
            assert observed == "synthetic-backend"
            event("body")
        return SimpleNamespace(status="FAILED" if fault == "failed-result" else "COMPLETED")

    monkeypatch.setattr(cuda.pwd, "getpwnam", lambda _n: SimpleNamespace(pw_uid=990, pw_gid=990))
    monkeypatch.setattr(cuda.os, "getgroups", lambda: [os.getgid(), 2468])
    monkeypatch.setattr(cuda, "_expected_device", expected_device)
    monkeypatch.setattr(cuda, "_wait_root_ack", lambda _n: event("ack"))
    monkeypatch.setattr(local_files, "BenchmarkWorkerLocalFiles", Files)
    monkeypatch.setattr(eom_gpu_lease, "acquire_shared_gpu_lease", acquire)
    monkeypatch.setattr(eom_gpu_lease, "request_unit_gpu_lease_retention", retain)
    monkeypatch.setattr(resource_files, "capture_cuda_probe_resource_files", capture)
    monkeypatch.setattr(resource_files, "open_cuda_probe_device_access", opened)
    monkeypatch.setattr(activation, "capture_benchmark_worker_channel", channel_factory)
    monkeypatch.setattr(backend_module, "native_cuda_backend_scope", backend)
    monkeypatch.setattr(leaf, "run_native_embedding_benchmark", run)
    if fault in {None, "failed-result"}:
        assert cuda._run(pins, 123) == (1 if fault else 0)
    else:
        with pytest.raises(ValueError, match="synthetic"):
            cuda._run(pins, 123)
        assert fault in events
    ordered = ["retention", "ready", "ack", "device", "channel", "backend", "body"]
    actual = [value for value in events if value in ordered]
    assert actual == ordered[: len(actual)]
    if "lease" in events and fault != "lease":
        assert "lease-close" in events
    if "channel" in events and fault != "channel":
        assert "channel-close" in events
    if "device" in events and fault != "device":
        assert events.index("device-close") < events.index("lease-close")
    if "backend" in events and fault != "backend":
        assert events.index("backend-close") < events.index("device-close")


def test_fresh_import_and_bad_cli_are_quiet_without_optional_runtime():
    code = (
        "import sys;import eom_catalog_service.embedding_benchmark_cuda;"
        "assert not {'pydantic','torch','numpy','transformers','sqlalchemy',"
        "'eom_gpu_lease','eom_orchestrator'}.intersection(sys.modules)"
    )
    imported = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, timeout=20)
    assert imported.returncode == 0 and not imported.stdout and not imported.stderr
    rejected = subprocess.run(
        [sys.executable, "-B", "-m", "eom_catalog_service.embedding_benchmark_cuda"],
        capture_output=True,
        timeout=20,
    )
    assert rejected.returncode == 1 and not rejected.stdout and not rejected.stderr

    wrong_identity = (
        "import sys;import eom_catalog_service.embedding_benchmark_cuda as c;"
        f"sys.argv=['fixed-unit',*{arguments()!r}];"
        "assert c.main()==1;"
        "assert not {'pydantic','torch','transformers','numpy','sqlalchemy',"
        "'eom_gpu_lease'}.intersection(sys.modules)"
    )
    guarded = subprocess.run(
        [sys.executable, "-B", "-c", wrong_identity], capture_output=True, timeout=20
    )
    assert guarded.returncode == 0 and not guarded.stdout and not guarded.stderr


def test_preexisting_signal_is_refused_before_input_or_optional_import(monkeypatch):
    monkeypatch.setattr(cuda.signal, "pthread_sigmask", lambda *_a: {signal.SIGUSR1})
    monkeypatch.setattr(cuda.signal, "sigpending", lambda: {signal.SIGUSR1})
    monkeypatch.setattr(cuda, "_execute", lambda *_a: pytest.fail("execution entered"))
    monkeypatch.setattr(
        cuda, "require_native_embedding_identity", lambda *_a: pytest.fail("identity entered")
    )
    assert cuda.main() == 1


def test_cuda_source_units_keep_fixed_activation_and_numerical_namespace():
    root = Path(__file__).resolve().parents[2]
    service = (root / "infra/systemd/eom-embedding-benchmark-cuda@.service").read_text()
    listener = (root / "infra/systemd/eom-embedding-benchmark-cuda@.socket").read_text()
    assert service.count("EnvironmentFile=") == 1
    for expected in (
        "User=eom-embedding-cuda",
        "SupplementaryGroups=eom-gpu-lease",
        "Slice=system.slice",
        "FileDescriptorStoreMax=1",
        "FileDescriptorStorePreserve=yes",
        "NotifyAccess=main",
        "DevicePolicy=closed",
        "DeviceAllow=/dev/nvidia0 rw",
        "DeviceAllow=/dev/nvidiactl rw",
        "DeviceAllow=/dev/nvidia-uvm rw",
        "DeviceAllow=/dev/nvidia-uvm-tools rw",
        "Environment=CUDA_VISIBLE_DEVICES=0",
        "Environment=CUBLAS_WORKSPACE_CONFIG=:4096:8",
        "-I -B -m eom_catalog_service.embedding_benchmark_cuda",
        "MemoryMax=6G",
        "CPUQuota=400%",
        "TasksMax=64",
        "TimeoutStartSec=180",
        "Restart=no",
        "ReadWritePaths=/run/eom-incremental-embeddings/benchmark/%i/cuda-ready.json",
        "TemporaryFileSystem=/run/eom-incremental-embeddings/benchmark:ro,mode=0711",
        "BindPaths=/run/eom-incremental-embeddings/benchmark/%i",
    ):
        assert expected in service
    assert "eom-gpu0-lease" not in listener
    assert "FileDescriptorName=benchmark-control" in listener
    assert (
        "ConditionPathExists=/run/eom-incremental-embeddings/benchmark/%i/cuda-ready.json"
        in listener
    )


@pytest.mark.parametrize("fault", (None, "hash", "changed", "missing", "malformed"))
def test_expected_device_resolves_exact_pinned_proof_metadata(monkeypatch, fault):
    from eom_catalog_contracts.embedding_installed_runtime_proof import (
        EmbeddingInstalledRuntimeProof,
        installed_runtime_proof_bytes,
    )
    from eom_catalog_service import embedding_runtime_files as runtime_files
    from jsonschema import ValidationError as SchemaValidationError

    from tests.unit.embedding_installed_runtime_fixtures import runtime_proof
    from tests.unit.inference_transfer_embedding_fixtures import seal

    invocation, ready = benchmark_cuda_ready()
    pointer = invocation.runtime.installed_proof
    body = runtime_proof("CUDA_INDEX_FP32").model_dump(mode="json")
    body.update(proof_id=pointer.proof_id, proof_revision_id=pointer.proof_revision_id)
    proof = EmbeddingInstalledRuntimeProof.model_validate(seal(body, "proof_sha256"))
    raw = installed_runtime_proof_bytes(proof)
    events = []

    class Files:
        def __init__(self, uid):
            assert uid == 0

        def read(self, path, *, sha256, maximum):
            assert (
                path
                == Path("/opt/eom/embedding-runtime-proofs")
                / pointer.proof_id
                / pointer.proof_revision_id
                / "proof.json"
            )
            assert sha256 == pointer.proof_raw_sha256 and maximum == 128 * 1024
            events.append("read")
            if fault == "missing":
                raise ValueError("synthetic missing protected proof")
            return b"{}" if fault == "malformed" else raw + b" " if fault == "hash" else raw

        def assert_unchanged(self):
            events.append("unchanged")
            if fault == "changed":
                raise ValueError("synthetic replaced proof")

    monkeypatch.setattr(runtime_files, "NumericalRuntimeFileSnapshots", Files)
    if fault is None:
        assert cuda._expected_device(invocation) == ready.expected_device_capture
        assert events == ["read", "unchanged"]
    else:
        with pytest.raises(SchemaValidationError if fault == "malformed" else ValueError):
            cuda._expected_device(invocation)


@pytest.mark.parametrize("fault", ("pid", "fds", "name", "expired", "too_long", None, "body"))
def test_shared_activation_validates_before_taking_fd_and_closes_only_owned_fd(monkeypatch, fault):
    pins = launch.parse_benchmark_launch_pins(arguments())
    now = pins.expires_ns - 10**9
    monkeypatch.setattr(launch.time, "monotonic_ns", lambda: now)
    monkeypatch.setenv("LISTEN_PID", str(os.getpid() + (1 if fault == "pid" else 0)))
    monkeypatch.setenv("LISTEN_FDS", "2" if fault == "fds" else "1")
    monkeypatch.setenv("LISTEN_FDNAMES", "other" if fault == "name" else "benchmark-control")
    if fault in {"expired", "too_long"}:
        from dataclasses import replace

        pins = replace(pins, expires_ns=now if fault == "expired" else now + 180 * 10**9 + 1)
    closed = []
    monkeypatch.setattr(launch.os, "close", lambda fd: closed.append(fd))

    def execute():
        with launch.benchmark_socket_activation(pins):
            if fault == "body":
                raise ValueError("synthetic failure")

    if fault is None:
        execute()
    else:
        with pytest.raises(ValueError):
            execute()
    assert closed == ([3] if fault in {None, "body"} else [])


def test_actual_child_keeps_sigblk_observable_and_rejects_nonroot_ack():
    if os.getuid() == 0:
        pytest.skip("This negative case needs the ordinary unprivileged test identity")
    code = (
        "import signal,time;"
        "from eom_catalog_service.embedding_benchmark_cuda import _wait_root_ack;"
        "signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGUSR1});print('READY',flush=True)\n"
        "try:_wait_root_ack(time.monotonic_ns()+5*10**9)\n"
        "except ValueError as e:\n"
        " assert str(e)=='BENCHMARK_CUDA_ROOT_ACK_REQUIRED';print('REJECTED',flush=True)\n"
        "else:raise AssertionError('nonroot sender admitted')\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-B", "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        assert process.stdout is not None and process.stdout.readline() == b"READY\n"
        for _ in range(5):
            status = (Path("/proc") / str(process.pid) / "status").read_text()
            blocked = next(
                line.split()[1] for line in status.splitlines() if line.startswith("SigBlk:")
            )
            assert int(blocked, 16) & (1 << (signal.SIGUSR1 - 1))
            time.sleep(0.02)
        os.kill(process.pid, signal.SIGUSR1)
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0 and stdout == b"REJECTED\n" and not stderr
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)
