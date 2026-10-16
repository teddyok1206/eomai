"""Synthetic notification sink over real file descriptions; not PID1/GPU admission."""

from __future__ import annotations

import array
import fcntl
import os
import socket
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_gpu_lease import lease as adapter

from tests.unit.test_shared_gpu_lease import policy as policy


class NotifySink:
    def __init__(self):
        self.messages = []
        self.retained = []
        self.channels_closed = 0
        self.short = None
        self.connect_failure = False

    def channel(self, family, kind):
        assert family == socket.AF_UNIX and kind == socket.SOCK_DGRAM | socket.SOCK_CLOEXEC
        sink = self

        class Channel:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                sink.channels_closed += 1

            def settimeout(self, value):
                assert value == 2.0

            def connect(self, path):
                assert path == "/run/systemd/notify"
                if sink.connect_failure:
                    raise OSError("synthetic connection failure")

            def sendmsg(self, buffers, rights):
                message = b"".join(buffers)
                level, kind, values = rights[0]
                assert level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS
                assert (
                    isinstance(values, array.array) and values.typecode == "i" and len(values) == 1
                )
                descriptor = os.dup(values[0])
                sink.messages.append(message)
                if message.startswith(b"FDSTORE=1"):
                    sink.retained.append(descriptor)
                else:
                    assert message == b"BARRIER=1"
                    os.close(descriptor)  # Fake processing completes before the barrier returns.
                return len(message) if sink.short != message else len(message) - 1

        return Channel()

    def close(self):
        for descriptor in self.retained:
            os.close(descriptor)
        self.retained.clear()


@pytest.fixture
def retained(policy, monkeypatch):
    lease = adapter._claim(policy)
    sink = NotifySink()
    monkeypatch.setenv("NOTIFY_SOCKET", "/run/systemd/notify")
    monkeypatch.setenv("FDSTORE", "1")
    monkeypatch.setattr(adapter, "_notification_epochs", lambda: ())
    monkeypatch.setattr(
        adapter,
        "socket",
        SimpleNamespace(
            AF_UNIX=socket.AF_UNIX,
            SOCK_DGRAM=socket.SOCK_DGRAM,
            SOCK_CLOEXEC=socket.SOCK_CLOEXEC,
            SOL_SOCKET=socket.SOL_SOCKET,
            SCM_RIGHTS=socket.SCM_RIGHTS,
            socket=sink.channel,
        ),
    )
    try:
        yield policy, lease, sink
    finally:
        lease.close()
        sink.close()


def test_retention_request_does_not_admit_or_release_original_and_copy_keeps_mutex(retained):
    policy, lease, sink = retained
    assert adapter.request_unit_gpu_lease_retention(lease) is None
    assert sink.messages == [b"FDSTORE=1\nFDNAME=eom-gpu0-lease\nFDPOLL=0", b"BARRIER=1"]
    lease.assert_valid()
    descriptor = lease.fileno()
    lease.close()
    with pytest.raises(OSError):
        os.fstat(descriptor)
    other = os.open(policy.path, os.O_RDONLY | os.O_CLOEXEC)
    try:
        with pytest.raises(BlockingIOError):
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        sink.close()
        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(other)


@pytest.mark.parametrize("fault", ("absent", "abstract", "other", "max0", "max2", "duck"))
def test_no_arbitrary_endpoint_capacity_or_duck_authority(retained, monkeypatch, fault):
    _, lease, sink = retained
    if fault == "absent":
        monkeypatch.delenv("NOTIFY_SOCKET")
    elif fault == "abstract":
        monkeypatch.setenv("NOTIFY_SOCKET", "@other")
    elif fault == "other":
        monkeypatch.setenv("NOTIFY_SOCKET", "/tmp/other.socket")
    elif fault.startswith("max"):
        monkeypatch.setenv("FDSTORE", fault[-1])
    else:
        lease = SimpleNamespace(assert_valid=lambda: None, fileno=lambda: 1)
    with pytest.raises(adapter.SharedGpuLeaseError, match="INVALID"):
        adapter.request_unit_gpu_lease_retention(lease)
    assert sink.messages == []


@pytest.mark.parametrize("fault", ("connect", "store_short", "barrier_short", "timeout", "epoch"))
def test_unknown_outcome_never_removes_store_or_closes_borrowed_lease(retained, monkeypatch, fault):
    _, lease, sink = retained
    if fault == "connect":
        sink.connect_failure = True
    elif fault == "store_short":
        sink.short = adapter._STORE_MESSAGE
    elif fault == "barrier_short":
        sink.short = adapter._BARRIER_MESSAGE
    elif fault == "timeout":
        monkeypatch.setattr(
            adapter.select,
            "poll",
            lambda: SimpleNamespace(register=lambda *_: None, poll=lambda _: []),
        )
    else:
        calls = iter(((), (), ((1,),)))
        monkeypatch.setattr(adapter, "_notification_epochs", lambda: next(calls))
    with pytest.raises(adapter.SharedGpuLeaseError, match="INVALID"):
        adapter.request_unit_gpu_lease_retention(lease)
    lease.assert_valid()
    assert not any(b"REMOVE" in message for message in sink.messages)
    assert sink.channels_closed == 1


def test_barrier_has_no_fd_leak(retained):
    _, lease, sink = retained
    before = set(os.listdir("/proc/self/fd"))
    adapter.request_unit_gpu_lease_retention(lease)
    sink.close()
    assert set(os.listdir("/proc/self/fd")) == before


@pytest.mark.parametrize(
    "fault",
    ("none", "parent_uid", "parent_write", "symlink", "socket_uid", "socket_alias", "regular"),
)
def test_fixed_notification_endpoint_has_protected_parents_and_one_root_socket(monkeypatch, fault):
    def metadata(path):
        mode = stat.S_IFSOCK | 0o777 if path.name == "notify" else stat.S_IFDIR | 0o755
        uid, links = 0, 1
        if path.name == "systemd":
            if fault == "parent_uid":
                uid = 1000
            elif fault == "parent_write":
                mode |= 0o020
            elif fault == "symlink":
                mode = stat.S_IFLNK | 0o777
        if path.name == "notify":
            if fault == "socket_uid":
                uid = 1000
            elif fault == "socket_alias":
                links = 2
            elif fault == "regular":
                mode = stat.S_IFREG | 0o777
        return SimpleNamespace(
            st_dev=1,
            st_ino=10,
            st_uid=uid,
            st_gid=0,
            st_mode=mode,
            st_nlink=links,
            st_size=0,
            st_mtime_ns=1,
            st_ctime_ns=1,
        )

    monkeypatch.setattr(Path, "lstat", metadata)
    if fault == "none":
        assert len(adapter._notification_epochs()) == 4
    else:
        with pytest.raises(adapter.SharedGpuLeaseError, match="INVALID"):
            adapter._notification_epochs()
