"""CPU executable/source-unit composition, not model, authority or installed acceptance."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import time
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_catalog_contracts.embedding_device_benchmark import embedding_device_benchmark_bytes
from eom_catalog_service import embedding_benchmark_activation as activation
from eom_catalog_service import embedding_benchmark_cpu as cpu
from eom_catalog_service import embedding_benchmark_entrypoint as leaf
from eom_catalog_service import embedding_device_benchmark_files as local_files
from eom_identifiers import sha256_bytes

from tests.unit.embedding_device_benchmark_fixtures import worker_invocation

ROOT = Path(__file__).resolve().parents[2]
BACKEND_PINS = (
    "embeddingnativeconfig_" + "a" * 32,
    "embeddingnativeconfigrev_" + "b" * 32,
    "sha256:" + "c" * 64,
    "sha256:" + "d" * 64,
    "sha256:" + "e" * 64,
)


def arguments() -> tuple[str, ...]:
    return (
        "1" * 32,
        "sha256:" + "f" * 64,
        str(os.getpid()),
        str(time.monotonic_ns() + 10**9),
        *BACKEND_PINS,
    )


@pytest.mark.parametrize("index", range(9))
@pytest.mark.parametrize("bad", ("", "latest", "../path", " 1", "+1", "1.0"))
def test_all_pins_are_exact_and_no_default_is_selected(index: int, bad: str) -> None:
    raw = list(arguments())
    raw[index] = bad
    with pytest.raises(ValueError):
        cpu._arguments(tuple(raw))


def test_each_independent_pin_and_exact_argument_count() -> None:
    raw = arguments()
    pins = cpu._arguments(raw)
    assert pins.execution_id == raw[0] and pins.invocation_raw_sha256 == raw[1]
    assert pins.owner_pid == os.getpid() and pins.expires_ns == int(raw[3])
    assert pins.backend.configuration_raw_sha256 == BACKEND_PINS[3]
    assert pins.backend.configuration_sha256 != pins.backend.configuration_raw_sha256
    for malformed in ((), raw[:-1], (*raw, "extra")):
        with pytest.raises(ValueError):
            cpu._arguments(malformed)


@pytest.mark.parametrize("failure", (None, "guard", "execute"))
def test_main_identity_precedes_capture_and_quiet_boundary_always_closes(
    monkeypatch: pytest.MonkeyPatch,
    failure: str | None,
) -> None:
    events: list[str] = []
    monkeypatch.setattr(sys, "argv", ["fixed-unit", *arguments()])
    monkeypatch.setattr(cpu, "discard_native_embedding_diagnostics", lambda: nullcontext())

    def identity(profile: str) -> None:
        events.append("identity")
        assert profile == "CPU_INDEX_FP32"
        if failure == "guard":
            raise ValueError("synthetic identity failure")

    def execute(pins: Any, started: int) -> int:
        events.append("capture")
        assert started > 0 and pins.owner_pid == os.getpid()
        if failure == "execute":
            raise ValueError("synthetic capture failure")
        return 0

    monkeypatch.setattr(cpu, "require_native_embedding_identity", identity)
    monkeypatch.setattr(cpu, "_execute", execute)
    assert cpu.main() == (0 if failure is None else 1)
    assert events == (["identity"] if failure == "guard" else ["identity", "capture"])


@pytest.mark.parametrize("failure", (False, True))
def test_activation_fd_closes_even_on_input_capture_failure(
    monkeypatch: pytest.MonkeyPatch,
    failure: bool,
) -> None:
    pins = cpu._arguments(arguments())
    monkeypatch.setenv("LISTEN_PID", str(os.getpid()))
    monkeypatch.setenv("LISTEN_FDS", "1")
    monkeypatch.setenv("LISTEN_FDNAMES", "benchmark-control")
    closed = []
    monkeypatch.setattr(cpu.os, "close", lambda descriptor: closed.append(descriptor))

    def run(pins: Any, started: int) -> int:
        if failure:
            raise ValueError("synthetic bad invocation")
        return 0

    monkeypatch.setattr(cpu, "_run", run)
    if failure:
        with pytest.raises(ValueError, match="synthetic bad"):
            cpu._execute(pins, 1)
    else:
        assert cpu._execute(pins, 1) == 0
    assert closed == [3]


def test_fresh_import_has_no_optional_runtime_and_bad_cli_is_quiet() -> None:
    code = (
        "import sys;import eom_catalog_service.embedding_benchmark_cpu;"
        "assert not {'pydantic','torch','numpy','transformers','sqlalchemy',"
        "'eom_orchestrator'}.intersection(sys.modules)"
    )
    result = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, timeout=20)
    assert result.returncode == 0 and not result.stdout and not result.stderr
    result = subprocess.run(
        [sys.executable, "-B", "-m", "eom_catalog_service.embedding_benchmark_cpu"],
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 1 and not result.stdout and not result.stderr


def test_source_units_pin_stdin_one_socket_resources_and_no_mutable_latest() -> None:
    service = (ROOT / "infra/systemd/eom-embedding-benchmark-cpu@.service").read_text()
    listener = (ROOT / "infra/systemd/eom-embedding-benchmark-cpu@.socket").read_text()
    assert service.count("EnvironmentFile=") == 1
    for value in (
        "NonBlocking=yes",
        "MemoryMax=6G",
        "CPUQuota=400%",
        "TasksMax=64",
        "TimeoutStartSec=180",
        "LimitFSIZE=16M",
        "PrivateDevices=yes",
        "PrivateNetwork=yes",
        "ProtectProc=invisible",
        "Slice=system.slice",
        "-I -B -m eom_catalog_service.embedding_benchmark_cpu",
        "StandardInput=file:/run/eom-incremental-embeddings/benchmark/%i/invocation.json",
        "ReadWritePaths=/run/eom-incremental-embeddings/benchmark/%i/outputs",
        "TemporaryFileSystem=/run/eom-incremental-embeddings/benchmark:ro,mode=0711",
        "BindPaths=/run/eom-incremental-embeddings/benchmark/%i",
    ):
        assert value in service
    assert "DeviceAllow=" not in service and "Restart=no" in service
    for value in (
        "Accept=no",
        "SocketMode=0600",
        "FileDescriptorName=benchmark-control",
        "SocketUser=eom-workflow-runner",
        "RemoveOnStop=yes",
    ):
        assert value in listener
    assert "ConditionPathIsDirectory=" in listener


@pytest.mark.parametrize(
    "fault", (None, "uid", "gid", "mode", "links", "size", "flags", "offset", "hash", "cuda")
)
def test_bounded_stdin_header_requires_exact_root_file_and_cpu_invocation(
    monkeypatch: pytest.MonkeyPatch,
    fault: str | None,
) -> None:
    # Explicit metadata surrogates, not a claim of real root descriptor admission.
    invocation = worker_invocation(2 if fault == "cuda" else 1)
    raw = embedding_device_benchmark_bytes(invocation)
    values = list(arguments())
    values[0] = invocation.execution_id
    values[1] = sha256_bytes(raw) if fault != "hash" else "sha256:" + "0" * 64
    pins = cpu._arguments(tuple(values))
    metadata = dict(st_uid=0, st_gid=0, st_mode=stat.S_IFREG | 0o600, st_nlink=1, st_size=len(raw))
    for name, changed in {
        "uid": ("st_uid", 1),
        "gid": ("st_gid", 1),
        "mode": ("st_mode", stat.S_IFREG | 0o640),
        "links": ("st_nlink", 2),
        "size": ("st_size", 65537),
    }.items():
        if fault == name:
            metadata[changed[0]] = changed[1]
    reads = []

    def pread(descriptor: int, count: int, offset: int) -> bytes:
        reads.append((descriptor, count, offset))
        return raw

    monkeypatch.setattr(
        cpu,
        "os",
        SimpleNamespace(
            fstat=lambda fd: SimpleNamespace(**metadata),
            pread=pread,
            lseek=lambda *args: 1 if fault == "offset" else 0,
            O_ACCMODE=os.O_ACCMODE,
            O_RDONLY=os.O_RDONLY,
            SEEK_CUR=os.SEEK_CUR,
        ),
    )
    monkeypatch.setattr(
        cpu,
        "fcntl",
        SimpleNamespace(
            fcntl=lambda *args: os.O_RDWR if fault == "flags" else os.O_RDONLY,
            F_GETFL=1,
        ),
    )
    if fault is None:
        assert cpu._invocation(pins) == invocation
        assert reads == [(0, 65537, 0)]
    else:
        with pytest.raises(ValueError):
            cpu._invocation(pins)


@pytest.mark.parametrize("failure", (None, "capture", "leaf", "worker_failed", "close"))
def test_real_executable_composition_keeps_backend_lazy_and_closes_owned_resources(
    monkeypatch: pytest.MonkeyPatch,
    failure: str | None,
) -> None:
    events = []
    pins = cpu._arguments(arguments())
    invocation = worker_invocation()
    monkeypatch.setattr(
        cpu,
        "pwd",
        SimpleNamespace(
            getpwnam=lambda _: SimpleNamespace(pw_uid=990, pw_gid=990),
        ),
    )
    monkeypatch.setattr(cpu, "_invocation", lambda _: invocation)

    class Files:
        def __init__(self, descriptor: int, **kwargs: Any) -> None:
            assert descriptor == 0 and kwargs["profile"] == "CPU_INDEX_FP32"
            assert kwargs["invocation_raw_sha256"] == pins.invocation_raw_sha256
            events.append("files")

        def close(self) -> None:
            events.append("files-close")

    class Channel:
        def close(self) -> None:
            events.append("channel-close")
            if failure == "close":
                raise ValueError("synthetic close uncertainty")

    def capture(value: Any, **kwargs: Any) -> Channel:
        events.append("capture")
        assert value == invocation and kwargs["activation_fd"] == 3
        assert kwargs["expected_peer"].pid == pins.owner_pid
        assert kwargs["expected_peer"].uid == 990
        if failure == "capture":
            raise ValueError("synthetic capture failure")
        return Channel()

    def backend(value: Any) -> Any:
        events.append("backend")
        assert value == pins.backend
        return nullcontext("synthetic-admitted-backend")

    def execute(files: Any, scope: Any, channel: Any, **kwargs: Any) -> Any:
        events.append("leaf")
        assert kwargs["profile"] == "CPU_INDEX_FP32" and kwargs["expires_ns"] == pins.expires_ns
        if failure == "leaf":
            raise ValueError("synthetic leaf failure")
        with scope() as actual:
            assert actual == "synthetic-admitted-backend"
        return SimpleNamespace(status="FAILED" if failure == "worker_failed" else "COMPLETED")

    monkeypatch.setattr(local_files, "BenchmarkWorkerLocalFiles", Files)
    monkeypatch.setattr(activation, "capture_benchmark_worker_channel", capture)
    monkeypatch.setattr(leaf, "run_native_embedding_benchmark", execute)
    monkeypatch.setattr(cpu, "native_cpu_backend_scope", backend)
    if failure in {"capture", "leaf", "close"}:
        with pytest.raises(ValueError):
            cpu._run(pins, 1)
    else:
        assert cpu._run(pins, 1) == (1 if failure == "worker_failed" else 0)
    assert events[:2] == ["files", "capture"]
    if failure == "capture":
        assert events == ["files", "capture", "files-close"]
    else:
        assert events[-2:] == ["files-close", "channel-close"]
        assert events[2] == "leaf"
        assert ("backend" in events) == (failure != "leaf")
