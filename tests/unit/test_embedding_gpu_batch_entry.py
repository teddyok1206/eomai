"""Fixed bootstrap/metadata with synthetic UID ports; no native identity or GPU execution."""

from __future__ import annotations

import ast
import os
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.embedding_gpu_control import embedding_gpu_control_bytes
from eom_catalog_service import embedding_gpu_batch_entry as entry
from eom_identifiers import sha256_bytes

from tests.unit.test_embedding_gpu_batch_launch import launch_pins
from tests.unit.test_embedding_gpu_control import control_case


@pytest.fixture
def allocation(tmp_path, monkeypatch):
    monkeypatch.setattr(entry, "_ROOT_UID", os.geteuid())
    request = control_case(expires_ns=time.monotonic_ns() + 30 * 10**9)[0]
    raw = embedding_gpu_control_bytes(request)
    path = tmp_path / "allocation.json"
    path.write_bytes(raw)
    path.chmod(0o600)
    descriptor = os.open(path, os.O_RDONLY)
    try:
        yield (
            descriptor,
            path,
            request,
            raw,
            replace(launch_pins(), allocation_raw_sha256=sha256_bytes(raw)),
        )
    finally:
        os.close(descriptor)


def test_allocation_is_exact_canonical_bounded_root_metadata_not_numerical_input(allocation):
    descriptor, _, request, raw, pins = allocation
    assert entry._read_allocation(descriptor, pins) == request
    assert os.lseek(descriptor, 0, os.SEEK_CUR) == len(raw)


@pytest.mark.parametrize(
    "fault",
    [
        "mode",
        "uid",
        "hash",
        "attempt",
        "noncanonical",
        "oversize",
        "offset",
        "links",
        "busy",
        "epoch",
    ],
)
def test_invalid_or_drifted_original_metadata_is_not_an_allocation_or_grant(
    allocation, monkeypatch, fault
):
    descriptor, path, _, raw, pins = allocation
    if fault == "mode":
        path.chmod(0o640)
    elif fault == "uid":
        monkeypatch.setattr(entry, "_ROOT_UID", os.geteuid() + 1)
    elif fault == "hash":
        pins = replace(pins, allocation_raw_sha256="sha256:" + "b" * 64)
    elif fault == "attempt":
        pins = replace(pins, attempt_hex="b" * 32)
    elif fault == "noncanonical":
        path.write_bytes(raw + b"\n")
        pins = replace(pins, allocation_raw_sha256=sha256_bytes(raw + b"\n"))
    elif fault == "oversize":
        path.write_bytes(b"x" * (32 * 1024 + 1))
    elif fault == "offset":
        os.lseek(descriptor, 1, os.SEEK_SET)
    elif fault == "links":
        os.link(path, path.parent / "duplicate.json")
    elif fault == "busy":
        raw = embedding_gpu_control_bytes(control_case()[2])
        path.write_bytes(raw)
        pins = replace(pins, allocation_raw_sha256=sha256_bytes(raw))
    else:
        count = [0]
        fstat = os.fstat

        def changed(fd):
            count[0] += 1
            current = fstat(fd)
            if count[0] == 1:
                return current
            values = {
                name: getattr(current, name)
                for name in (
                    "st_dev",
                    "st_ino",
                    "st_uid",
                    "st_gid",
                    "st_mode",
                    "st_nlink",
                    "st_size",
                    "st_mtime_ns",
                    "st_ctime_ns",
                )
            }
            return SimpleNamespace(**(values | {"st_ctime_ns": current.st_ctime_ns + 1}))

        monkeypatch.setattr(
            entry,
            "os",
            SimpleNamespace(
                fstat=changed,
                read=os.read,
                lseek=os.lseek,
                SEEK_CUR=os.SEEK_CUR,
                O_RDONLY=os.O_RDONLY,
                O_ACCMODE=os.O_ACCMODE,
                O_APPEND=os.O_APPEND,
            ),
        )
    with pytest.raises(ValueError):
        entry._read_allocation(descriptor, pins)


@pytest.mark.parametrize(
    "names", ["gpu-batch-control:gpu-batch-allocation", "gpu-batch-allocation:gpu-batch-control"]
)
def test_pid1_descriptor_names_not_order_define_metadata_and_control(monkeypatch, names):
    marks = []
    monkeypatch.setattr(
        entry,
        "os",
        SimpleNamespace(
            environ={"LISTEN_PID": "123", "LISTEN_FDS": "2", "LISTEN_FDNAMES": names},
            getpid=lambda: 123,
            set_inheritable=lambda fd, value: marks.append((fd, value)),
        ),
    )
    observed = entry._activation_descriptors()
    assert set(observed.values()) == {3, 4}
    assert list(observed) == names.split(":")
    assert marks == [(3, False), (4, False)]


@pytest.mark.parametrize(
    "key,value",
    [
        ("LISTEN_PID", "456"),
        ("LISTEN_FDS", "1"),
        ("LISTEN_FDS", "3"),
        ("LISTEN_FDNAMES", "gpu-batch-control:gpu-batch-control"),
        ("LISTEN_FDNAMES", "benchmark-control:gpu-batch-allocation"),
        ("LISTEN_FDNAMES", "gpu-batch-control:gpu-batch-allocation:extra"),
    ],
)
def test_arbitrary_activation_metadata_cannot_select_fds(monkeypatch, key, value):
    env = {
        "LISTEN_PID": "123",
        "LISTEN_FDS": "2",
        "LISTEN_FDNAMES": "gpu-batch-control:gpu-batch-allocation",
    }
    env[key] = value
    monkeypatch.setattr(
        entry,
        "os",
        SimpleNamespace(
            environ=env,
            getpid=lambda: 123,
            set_inheritable=lambda *_: pytest.fail("invalid activation changed FDs"),
        ),
    )
    with pytest.raises(ValueError):
        entry._activation_descriptors()


@pytest.mark.parametrize(
    "fault", [None, "dup_first", "dup_second", "silence", "run", "interrupt", "close"]
)
def test_bootstrap_quiets_before_libraries_and_never_returns_success_after_failed_cleanup(
    monkeypatch, fault
):
    events, owned = [], []

    def duplicate(fd, operation, minimum):
        assert minimum == 3
        events.append(("duplicate", fd))
        if (fd == 1 and fault == "dup_first") or (fd == 2 and fault == "dup_second"):
            raise OSError("synthetic duplication failure")
        owned.append(fd + 4)
        return fd + 4

    def silence():
        events.append("silence")
        if fault == "silence":
            raise OSError("sink unavailable")

    def run(args, outputs):
        assert events[-1] == "silence" and outputs == (5, 6) and args == ("pinned",)
        events.append("run")
        if fault == "run":
            raise ValueError("private error must not reach binary descriptors")
        if fault == "interrupt":
            raise KeyboardInterrupt
        return 0

    def close(fd):
        events.append(("close", fd))
        if fault == "close":
            raise OSError("close uncertain")

    monkeypatch.setattr(entry, "fcntl", SimpleNamespace(fcntl=duplicate, F_DUPFD_CLOEXEC=1))
    monkeypatch.setattr(entry, "os", SimpleNamespace(close=close))
    monkeypatch.setattr(entry, "sys", SimpleNamespace(argv=["entry", "pinned"]))
    monkeypatch.setattr(entry, "_silence", silence)
    monkeypatch.setattr(entry, "_run", run)
    assert entry.main() == (0 if fault is None else 1)
    assert [("close", fd) for fd in owned] == [
        event for event in events if isinstance(event, tuple) and event[0] == "close"
    ]


def test_bootstrap_top_level_is_stdlib_only_and_identity_precedes_runtime_imports():
    path = Path(entry.__file__)
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.Import):
            assert all(
                alias.name in {"fcntl", "hashlib", "os", "stat", "sys"} for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            assert node.module in {"__future__", "contextlib", "typing"}
    run = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_run"
    )
    assert isinstance(run.body[0], ast.ImportFrom) and run.body[0].module.endswith(
        "embedding_native_entrypoint"
    )
    assert isinstance(run.body[1], ast.Expr) and isinstance(run.body[1].value, ast.Call)
    assert run.body[1].value.func.id == "require_native_embedding_identity"
