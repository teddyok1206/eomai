"""Synthetic fixed INDEX leaf seams; no CUDA, model, root ACK or production IO."""

from __future__ import annotations

import ast
import fcntl
import json
import os
import signal
import stat
import subprocess
import sys
import time
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.embedding_native_cuda_index_ready import (
    NativeCudaIndexReady,
    validate_native_cuda_index_ready,
)
from eom_catalog_service import embedding_native_cuda_index_entry as entry
from eom_identifiers import canonical_json_bytes, sha256_bytes

from tests.unit.embedding_installed_runtime_fixtures import runtime_proof
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.local_embedding_admission_fixtures import native_fixture

ROOT = Path(__file__).resolve().parents[2]


def arguments(request=None):
    request = native_fixture(device="CUDA").native_input if request is None else request
    return (
        "INDEX",
        "a" * 32,
        request.job_id,
        "sha256:" + "b" * 64,
        sha256_bytes(canonical_json_bytes(request.model_dump(mode="json"))),
        str(time.monotonic_ns() + 60 * 10**9),
        "embeddingnativeconfig_" + "c" * 32,
        "embeddingnativeconfigrev_" + "d" * 32,
        "sha256:" + "e" * 64,
        "sha256:" + "f" * 64,
        "sha256:" + "1" * 64,
    )


def metadata(ino=1, size=0, *, mode=0o640, uid=0, links=1):
    return SimpleNamespace(
        st_dev=1,
        st_ino=ino,
        st_uid=uid,
        st_gid=2345,
        st_mode=stat.S_IFREG | mode,
        st_nlink=links,
        st_size=size,
        st_mtime_ns=2,
        st_ctime_ns=3,
    )


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "purpose",
        "flag",
        "hash",
        "job",
        "config",
        "revision",
        "expiry",
        "overflow",
        "bool",
        "extra",
        "list",
    ],
)
def test_closed_index_argv_has_no_backend_path_authority_or_inferred_purpose(fault):
    values = list(arguments())
    changes = {
        "purpose": (0, "PRIVATE_CHAT_QUERY"),
        "flag": (0, "--cuda"),
        "hash": (3, "b" * 64),
        "job": (2, "job_latest"),
        "config": (6, "/tmp/config.json"),
        "revision": (7, "latest"),
        "expiry": (5, "1.5"),
        "overflow": (5, str(2**63)),
        "bool": (5, True),
    }
    if fault in changes:
        index, value = changes[fault]
        values[index] = value
    if fault == "extra":
        values.append("--ready-path=/tmp/foreign")
    if fault is None:
        pins = entry.parse_native_cuda_index_launch_pins(tuple(values))
        assert (
            pins.execution_id == "a" * 32
            and pins.configuration_sha256 != pins.configuration_raw_sha256
        )
    else:
        with pytest.raises(ValueError, match="NATIVE_CUDA_INDEX_ENTRY_INVALID"):
            entry.parse_native_cuda_index_launch_pins(values if fault == "list" else tuple(values))


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "pid1",
        "unreserved",
        "expired",
        "timeout",
        "uid",
        "bool_uid",
        "pid",
        "bool_pid",
        "signal",
        "late",
    ],
)
def test_one_root_ack_requires_reserved_mask_and_zero_time_bounded_poll(monkeypatch, fault):
    clock = [100]
    waits = []
    monkeypatch.setattr(entry.time, "monotonic_ns", lambda: clock[0])
    monkeypatch.setattr(entry.time, "sleep", lambda _s: clock.__setitem__(0, 200))
    monkeypatch.setattr(
        entry.signal,
        "pthread_sigmask",
        lambda *_a: set() if fault == "unreserved" else {signal.SIGUSR1},
    )

    def receive(signals, timeout):
        waits.append(timeout)
        assert signals == {signal.SIGUSR1} and timeout == 0
        if fault == "timeout":
            return None
        if fault == "late":
            clock[0] = 200
        return SimpleNamespace(
            si_uid=12 if fault == "uid" else False if fault == "bool_uid" else 0,
            si_pid=0
            if fault == "pid"
            else False
            if fault == "bool_pid"
            else 1
            if fault == "pid1"
            else 99,
            si_signo=signal.SIGUSR2 if fault == "signal" else signal.SIGUSR1,
        )

    monkeypatch.setattr(entry.signal, "sigtimedwait", receive)
    if fault in {None, "pid1"}:
        entry._wait_root_ack(200)
        assert waits == [0]
    else:
        with pytest.raises(ValueError, match="NATIVE_CUDA_INDEX_ENTRY_INVALID"):
            entry._wait_root_ack(100 if fault == "expired" else 200)
        if fault in {"expired", "unreserved"}:
            assert not waits


@pytest.mark.parametrize("delta", [-1, 0, 180 * 10**9 + 1])
def test_original_deadline_cannot_be_expired_or_unbounded(monkeypatch, delta):
    pins = entry.parse_native_cuda_index_launch_pins(arguments())
    monkeypatch.setattr(entry.time, "monotonic_ns", lambda: 100)
    with pytest.raises(ValueError):
        entry._before_deadline(replace(pins, expires_ns=100 + delta))


@pytest.mark.parametrize(
    "fault",
    [None, "hash", "job", "cpu", "recipe", "noncanonical", "changed", "mode", "flags", "oversized"],
)
def test_exact_canonical_regular_stdin_is_hashed_and_rewound_before_standard_api(
    monkeypatch, fault
):
    request = native_fixture(device="CPU" if fault == "cpu" else "CUDA").native_input
    if fault == "recipe":
        body = request.model_dump(mode="json") | {"threads": 2}
        request = type(request).model_validate(seal(body, "request_sha256"))
    raw = canonical_json_bytes(request.model_dump(mode="json")) + (
        b"\n" if fault == "noncanonical" else b""
    )
    pins = entry.parse_native_cuda_index_launch_pins(arguments(request))
    pins = replace(pins, input_raw_sha256=sha256_bytes(raw))
    if fault == "hash":
        pins = replace(pins, input_raw_sha256="sha256:" + "0" * 64)
    if fault == "job":
        pins = replace(pins, job_id="job_" + "0" * 32)
    value = metadata(
        size=64 * 1024**2 + 1 if fault == "oversized" else len(raw),
        mode=0o640 if fault == "mode" else 0o600,
    )
    offset = [0]

    def read(fd, maximum):
        assert fd == 0
        chunk = raw[offset[0] : offset[0] + maximum]
        offset[0] += len(chunk)
        return chunk

    def seek(fd, position, origin):
        assert fd == 0
        if origin == os.SEEK_SET:
            offset[0] = position
        return offset[0]

    def observed(fd):
        assert fd == 0
        return (
            metadata(size=len(raw) + 1, mode=0o600) if fault == "changed" and offset[0] else value
        )

    monkeypatch.setattr(
        entry,
        "os",
        SimpleNamespace(
            fstat=observed,
            read=read,
            lseek=seek,
            O_RDONLY=os.O_RDONLY,
            O_ACCMODE=os.O_ACCMODE,
            O_APPEND=os.O_APPEND,
            SEEK_CUR=os.SEEK_CUR,
            SEEK_SET=os.SEEK_SET,
        ),
    )
    monkeypatch.setattr(
        entry,
        "fcntl",
        SimpleNamespace(
            F_GETFL=1, fcntl=lambda *_a: os.O_RDWR if fault == "flags" else os.O_RDONLY
        ),
    )
    if fault is None:
        actual, epoch = entry._read_input(pins)
        assert actual == request and offset[0] == 0
        entry._assert_input_current(epoch)
    else:
        with pytest.raises(ValueError):
            entry._read_input(pins)


@pytest.mark.parametrize(
    "fault", [None, "pid", "count", "name", "mode", "owner", "link", "nonempty", "access", "append"]
)
def test_ready_is_only_exact_named_root_regular_openfile_fd3_rdwr(monkeypatch, fault):
    environment = {"LISTEN_PID": "123", "LISTEN_FDS": "1", "LISTEN_FDNAMES": "cuda-index-ready"}
    if fault in {"pid", "count", "name"}:
        environment[
            {"pid": "LISTEN_PID", "count": "LISTEN_FDS", "name": "LISTEN_FDNAMES"}[fault]
        ] = "wrong"
    initial = metadata(
        mode=0o600 if fault == "mode" else 0o640,
        uid=1 if fault == "owner" else 0,
        links=2 if fault == "link" else 1,
        size=1 if fault == "nonempty" else 0,
    )
    inherited = []
    monkeypatch.setattr(
        entry,
        "os",
        SimpleNamespace(
            environ=environment,
            getpid=lambda: 123,
            fstat=lambda fd: initial,
            lseek=lambda *_a: 0,
            set_inheritable=lambda fd, value: inherited.append((fd, value)),
            O_RDWR=os.O_RDWR,
            O_ACCMODE=os.O_ACCMODE,
            O_APPEND=os.O_APPEND,
            SEEK_CUR=os.SEEK_CUR,
        ),
    )
    flags = (
        os.O_WRONLY if fault == "access" else os.O_RDWR | (os.O_APPEND if fault == "append" else 0)
    )
    monkeypatch.setattr(entry, "fcntl", SimpleNamespace(F_GETFL=1, fcntl=lambda *_a: flags))
    if fault is None:
        assert entry._ready_descriptor() is initial
        assert inherited == [(3, False)]
    else:
        with pytest.raises(ValueError):
            entry._ready_descriptor()
        assert not inherited


@pytest.mark.parametrize(
    "fault",
    [None, "write_zero", "oversized", "changed", "partial", "fsync", "contended", "unlock"],
)
def test_ready_partial_writes_are_bounded_fsynced_and_epoch_checked_on_fd3(monkeypatch, fault):
    payload = b'{"ready":true}' if fault != "oversized" else b"x" * (8 * 1024 + 1)
    data = bytearray()
    synced = []
    events = []
    locked = [False]

    def ready_flock(fd, operation):
        assert fd == 3
        if operation == fcntl.LOCK_EX | fcntl.LOCK_NB:
            assert not locked[0]
            events.append("lock")
            if fault == "contended":
                raise BlockingIOError("synthetic READY reader contention")
            locked[0] = True
        else:
            assert operation == fcntl.LOCK_UN and locked[0]
            events.append("unlock")
            locked[0] = False
            if fault == "unlock":
                raise OSError("synthetic READY unlock failure")

    def observed(fd):
        assert fd == 3
        events.append("stat")
        return metadata(3, len(data), links=2 if fault == "changed" and data else 1)

    def write(fd, remaining):
        assert fd == 3 and locked[0]
        events.append("write")
        if fault == "partial" and data:
            raise OSError("synthetic partial READY failure")
        if fault == "write_zero":
            return 0
        count = min(7, len(remaining))
        data.extend(remaining[:count])
        return count

    def sync(fd):
        assert fd == 3 and locked[0]
        events.append("fsync")
        if fault == "fsync":
            raise OSError("synthetic READY fsync failure")
        synced.append(fd)

    monkeypatch.setattr(
        entry,
        "os",
        SimpleNamespace(
            fstat=observed,
            write=write,
            fsync=sync,
            lseek=lambda *_a: len(data),
            get_inheritable=lambda _fd: False,
            O_RDWR=os.O_RDWR,
            O_ACCMODE=os.O_ACCMODE,
            O_APPEND=os.O_APPEND,
            SEEK_CUR=os.SEEK_CUR,
        ),
    )
    monkeypatch.setattr(
        entry,
        "fcntl",
        SimpleNamespace(
            F_GETFL=1,
            fcntl=lambda *_a: os.O_RDWR,
            flock=ready_flock,
            LOCK_EX=fcntl.LOCK_EX,
            LOCK_NB=fcntl.LOCK_NB,
            LOCK_UN=fcntl.LOCK_UN,
        ),
    )
    initial = observed(3)
    events.clear()
    if fault is None:
        epoch = entry._write_ready(payload, initial)
        assert bytes(data) == payload and synced == [3]
        assert events[0] == "lock" and events[-1] == "unlock"
        assert events.index("lock") < events.index("stat") < events.index("write")
        assert events.index("write") < events.index("fsync") < len(events) - 1
        assert events[-2] == "stat"  # Post-write/epoch validation is still locked.
        entry._assert_ready_current(epoch)
    else:
        with pytest.raises((ValueError, OSError)):
            entry._write_ready(payload, initial)
        if fault in {"write_zero", "oversized"}:
            assert not data and not synced
        if fault == "oversized":
            assert not events
        elif fault == "contended":
            assert events == ["lock"] and not data and not synced
        else:
            assert events[0] == "lock" and events[-1] == "unlock"
        if fault == "partial":
            assert 0 < len(data) < len(payload) and not synced
        elif fault == "fsync":
            assert bytes(data) == payload and not synced
    assert not locked[0]


@pytest.mark.parametrize("fault", [None, "identity", "pending", "argv", "execute", "silencer"])
def test_main_reserves_before_identity_and_cannot_execute_after_early_failure(monkeypatch, fault):
    events = []
    monkeypatch.setattr(entry.signal, "pthread_sigmask", lambda *_a: events.append("reserved"))
    monkeypatch.setattr(
        entry.signal, "sigpending", lambda: {signal.SIGUSR1} if fault == "pending" else set()
    )
    monkeypatch.setattr(entry, "_result_channels", lambda: nullcontext((90, 91)))

    def silence():
        if fault == "silencer":
            raise ValueError("NATIVE_CUDA_INDEX_DIAGNOSTIC_SINK_INVALID")

    monkeypatch.setattr(entry, "_silence_diagnostics", silence)

    def identity():
        events.append("identity")
        if fault == "identity":
            raise ValueError("sensitive identity")

    def execute(pins, outputs):
        events.append("execute")
        assert outputs == (90, 91) and pins.job_id.startswith("job_")
        if fault == "execute":
            raise ValueError("sensitive execute")
        return 0

    monkeypatch.setattr(entry, "_require_identity", identity)
    monkeypatch.setattr(entry, "_run", execute)
    monkeypatch.setattr(
        sys, "argv", ["external-entry", *(arguments() if fault != "argv" else ("QUERY",))]
    )
    assert entry.main() == (0 if fault is None else 1)
    assert events[0] == "reserved"
    if fault in {"identity", "pending", "argv", "silencer"}:
        assert "execute" not in events


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "runtime",
        "retention",
        "ready",
        "ack",
        "input_changed",
        "ready_changed",
        "device",
        "model",
        "resources-close",
        "lease-close",
    ],
)
def test_only_retained_ready_root_ack_allows_devices_and_native_model_scope(monkeypatch, fault):
    import eom_gpu_lease
    from eom_catalog_service import embedding_cuda_probe_resource_files as resource_files
    from eom_catalog_service import embedding_native_cuda_backend as backend_module
    from eom_catalog_service import embedding_native_entrypoint as numerical_api
    from eom_catalog_service import embedding_native_installation_admission as admission
    from eom_catalog_service import embedding_runtime_files as runtime_files

    request = native_fixture(device="CUDA").native_input
    pins = entry.parse_native_cuda_index_launch_pins(arguments(request))
    device = runtime_proof("CUDA_INDEX_FP32").device_capture
    events = []
    emitted = []

    def event(value):
        events.append(value)
        if value == fault:
            raise ValueError("synthetic " + value)

    class Lease:
        def close(self):
            event("lease-close")

    class Files:
        def __init__(self, uid):
            assert uid == 0

        def assert_unchanged(self):
            event("files-current")

    class Resources:
        shared_gpu_lease = SimpleNamespace(holder_pid=123, holder_start_time_ticks=999)
        resource_descriptors = SimpleNamespace(
            model_dump=lambda **_k: {
                "nvidia0_fd": 10,
                "nvidiactl_fd": 11,
                "nvidia_uvm_fd": 12,
                "nvidia_uvm_tools_fd": 13,
                "lease_fd": 14,
            }
        )

        def assert_current(self):
            event("resources-current")

        def __enter__(self):
            event("resources")
            return self

        def __exit__(self, *_a):
            event("resources-close")

    lease, resources = Lease(), Resources()
    monkeypatch.setattr(
        eom_gpu_lease, "acquire_shared_gpu_lease", lambda: (event("lease"), lease)[1]
    )
    monkeypatch.setattr(
        eom_gpu_lease,
        "request_unit_gpu_lease_retention",
        lambda actual: event("retention") if actual is lease else pytest.fail("foreign lease"),
    )
    monkeypatch.setattr(runtime_files, "NumericalRuntimeFileSnapshots", Files)
    monkeypatch.setattr(
        admission,
        "read_pinned_cuda_admission_receipt",
        lambda *_a, **_k: (
            SimpleNamespace(
                device_capture=device,
                runtime_sha256="sha256:" + "0" * 64
                if fault == "runtime"
                else request.space.runtime.execution_runtime_sha256,
            ),
            b"receipt",
        ),
    )
    monkeypatch.setattr(
        resource_files,
        "capture_cuda_probe_resource_files",
        lambda expected, actual: (
            resources
            if expected is device and actual is lease
            else pytest.fail("foreign resources")
        ),
    )

    @contextmanager
    def opened(actual):
        assert actual is resources
        event("device")
        try:
            yield "ownership"
        finally:
            event("device-close")

    @contextmanager
    def backend(configuration, **kwargs):
        assert kwargs == {"receipt_raw_sha256": pins.receipt_raw_sha256, "ownership": "ownership"}
        event("backend")
        try:
            yield "native-backend"
        finally:
            event("backend-close")

    def numerical(**kwargs):
        assert kwargs["profile"] == "CUDA_INDEX_FP32"
        event("native-api")
        with kwargs["backend_scope"]() as actual:
            assert actual == "native-backend"
            event("model")

    monkeypatch.setattr(resource_files, "open_cuda_probe_device_access", opened)
    monkeypatch.setattr(backend_module, "native_cuda_backend_scope", backend)
    monkeypatch.setattr(numerical_api, "run_native_embedding_index", numerical)
    monkeypatch.setattr(entry, "_ready_descriptor", lambda: metadata(3))
    monkeypatch.setattr(entry, "_read_input", lambda _pins: (request, (1,)))
    monkeypatch.setattr(
        entry,
        "_assert_input_current",
        lambda _epoch: (
            event("input_changed") if fault == "input_changed" else event("input-current")
        ),
    )
    monkeypatch.setattr(
        entry,
        "_assert_ready_current",
        lambda _epoch: (
            event("ready_changed") if fault == "ready_changed" else event("ready-current")
        ),
    )
    monkeypatch.setattr(entry, "_wait_root_ack", lambda expiry: event("ack"))
    monkeypatch.setattr(entry, "_silence_diagnostics", lambda: None)
    monkeypatch.setattr(
        entry,
        "os",
        SimpleNamespace(
            fstat=lambda fd: metadata(fd + 10),
            geteuid=lambda: 1234,
            getegid=lambda: 1234,
            getgroups=lambda: [1234, 2468],
            dup2=lambda source, target: event("restore-" + str(target)),
        ),
    )

    def write(raw, _initial):
        event("ready")
        ready = NativeCudaIndexReady.model_validate(json.loads(raw))
        validate_native_cuda_index_ready(
            request,
            ready,
            execution_id=pins.execution_id,
            native_launch_job_id=pins.job_id,
            launch_association_sha256=pins.association_sha256,
            input_raw_sha256=pins.input_raw_sha256,
            configuration=ready.configuration,
            receipt_raw_sha256=pins.receipt_raw_sha256,
            expected_device=device,
        )
        emitted.append(raw)
        return (3,)

    monkeypatch.setattr(entry, "_write_ready", write)
    if fault is None:
        assert entry._run(pins, (90, 91)) == 0
        assert (
            events.index("retention")
            < events.index("ready")
            < events.index("ack")
            < events.index("device")
            < events.index("model")
        )
        assert (
            events.index("backend-close")
            < events.index("device-close")
            < events.index("resources-close")
            < events.index("lease-close")
        )
        assert len(emitted) == 1
    else:
        with pytest.raises(ValueError):
            entry._run(pins, (90, 91))
        if fault in {
            "runtime",
            "retention",
            "ready",
            "ack",
            "input_changed",
            "ready_changed",
            "device",
        }:
            assert "model" not in events
        if fault in {"runtime", "retention", "ready", "ack", "input_changed", "ready_changed"}:
            assert "device" not in events
        if fault != "runtime":
            assert "lease-close" in events


@pytest.mark.parametrize(
    "fault",
    [
        "identity",
        "argv",
        "execute",
        "keyboard",
        "systemexit",
        "before_quiet",
        "import",
        "preflight",
        "silencer",
    ],
)
def test_actual_child_failure_emits_zero_diagnostics_to_result_and_vector_channels(fault):
    paths = [path for path in sys.path if path.startswith(str(ROOT))]
    code = (
        "import sys;sys.path[:0]=" + repr(paths) + ";"
        "from contextlib import nullcontext;"
        "from eom_catalog_service import embedding_native_cuda_index_entry as e;"
        "original_channels=e._result_channels;original_identity=e._require_identity;"
        "e._result_channels=lambda:nullcontext((90,91));"
        "e._require_identity=lambda:None;"
        "sys.argv=['entry',*" + repr(arguments()) + "];"
        "defect=" + repr(fault) + ";"
        "\nerror_type=(KeyboardInterrupt if defect in ('keyboard','before_quiet') "
        "else SystemExit if defect=='systemexit' else ValueError)\n"
        "def fail(*_a): raise error_type('sensitive source diagnostic')\n"
        "if defect=='identity':e._require_identity=fail\n"
        "if defect=='argv':sys.argv=['entry','QUERY']\n"
        "if defect=='before_quiet':e._result_channels=fail\n"
        "if defect=='preflight':e._result_channels=original_channels\n"
        "if defect=='silencer':e.os.open=fail\n"
        "if defect=='import':\n"
        " import builtins\n"
        " original_import=builtins.__import__\n"
        " def guarded(name,*args,**kwargs):\n"
        "  if name=='eom_catalog_service.embedding_native_entrypoint':fail()\n"
        "  return original_import(name,*args,**kwargs)\n"
        " builtins.__import__=guarded\n"
        " e._require_identity=original_identity\n"
        "e._run=fail\nraise SystemExit(e.main())\n"
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-B", "-c", code], capture_output=True, timeout=20, check=False
    )
    assert completed.returncode == 1
    assert completed.stdout == completed.stderr == b""


def test_external_script_imports_only_existing_absolute_sealed_prefix_boundaries():
    source = (
        ROOT / "services/catalog_service/eom_catalog_service/embedding_native_cuda_index_entry.py"
    )
    tree = ast.parse(source.read_text())
    modules = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert all(node.level == 0 for node in ast.walk(tree) if isinstance(node, ast.ImportFrom))
    assert not any(
        "benchmark" in name or "embedding_native_cuda_index_ready" in name for name in modules
    )
    assert not any(
        name.startswith(
            ("eom_workflow", "eom_orchestrator", "sqlalchemy", "torch", "transformers", "httpx")
        )
        for name in modules
    )
    text = source.read_text()
    assert "FDSTOREREMOVE" not in text
    ready_writer = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_write_ready"
    )
    flock_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "fcntl"
        and node.func.attr == "flock"
    ]
    assert len(flock_calls) == 2
    assert all(node in tuple(ast.walk(ready_writer)) for node in flock_calls)
    assert all(ast.unparse(node.args[0]) == "_READY_FD" for node in flock_calls)
    assert {ast.unparse(node.args[1]) for node in flock_calls} == {
        "fcntl.LOCK_EX | fcntl.LOCK_NB",
        "fcntl.LOCK_UN",
    }
    assert not any(
        (node.module or "").startswith("eom_")
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
    )
    opened = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "os"
        and node.func.attr == "open"
    ]
    assert len(opened) == 1 and opened[0].args[0].value == "/dev/null"
