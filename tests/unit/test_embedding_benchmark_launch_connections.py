"""Actual Unix negative and owner-lifetime tests; positive unit/root identity is not faked."""

import os
import socket
import tempfile
import time
from pathlib import Path

import pytest
from eom_catalog_service import embedding_benchmark_native_connection as native
from eom_catalog_service import embedding_benchmark_root_connection as owner
from eom_catalog_service import embedding_benchmark_root_socket as root
from eom_orchestrator.embedding_device_benchmark_owner import BenchmarkLaunchAuthorization
from eom_orchestrator.inference_transfer_cpu_handoff import (
    CpuHandoffIdentity,
    protected_cpu_handoff_directory,
)

from tests.unit.embedding_device_benchmark_fixtures import worker_invocation


def test_nonroot_root_listener_is_rejected_before_parsing_or_reading_owner_stage():
    if os.geteuid() == 0:
        pytest.skip("requires actual nonroot")
    with pytest.raises(ValueError, match="ROOT_REQUIRED"):
        root.serve_root_benchmark_workspace(
            "not-an-execution",
            selected_request_sha256="not-a-hash",
            backend=None,
            controller_release="not-a-release",
        )


def test_nonowner_cannot_connect_to_privileged_control_or_native_listener():
    from eom_orchestrator.inference_transfer_cpu_handoff import fixed_owner_identity

    if os.geteuid() == fixed_owner_identity().owner_uid:
        pytest.skip("requires actual nonowner")
    with pytest.raises(ValueError, match="OWNER_REQUIRED"):
        owner.connect_benchmark_root(None, authorization=None, controller_release="a" * 40)
    with pytest.raises(ValueError, match="OWNER_REQUIRED"):
        owner.connect_benchmark_series_root(
            None, None, authorization=None, controller_release="a" * 40
        )
    with pytest.raises(ValueError, match="OWNER_REQUIRED"):
        owner.require_benchmark_series_listener(None)
    with pytest.raises(ValueError, match="OWNER_REQUIRED"):
        native.CapturedBenchmarkNativeConnection.connect(None, authorization=None, expires_ns=1)


@pytest.fixture
def short_socket_root():
    with tempfile.TemporaryDirectory(prefix="eom-bm-") as directory:
        yield Path(directory)


def test_real_same_uid_listener_cannot_impersonate_pid1(short_socket_root, monkeypatch):
    invocation = worker_invocation(4)
    identity = CpuHandoffIdentity(os.getuid(), os.getgid())
    monkeypatch.setattr(native, "fixed_owner_identity", lambda: identity)
    monkeypatch.setattr(native, "BENCHMARK_HANDOFF_ROOT", short_socket_root)
    parent = short_socket_root / invocation.execution_id
    parent.mkdir(mode=0o750)
    parent.chmod(0o750)
    authorization = object.__new__(BenchmarkLaunchAuthorization)
    monkeypatch.setattr(BenchmarkLaunchAuthorization, "assert_invocation", lambda *args: None)

    def synthetic_directory(path, **kwargs):
        kwargs["uid"] = os.getuid()
        return protected_cpu_handoff_directory(path, **kwargs)

    monkeypatch.setattr(native, "protected_cpu_handoff_directory", synthetic_directory)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(parent / "control.sock"))
    (parent / "control.sock").chmod(0o600)
    listener.listen(1)
    try:
        with pytest.raises(ValueError, match="LISTENER_INVALID"):
            native.CapturedBenchmarkNativeConnection.connect(
                invocation,
                authorization=authorization,
                expires_ns=time.monotonic_ns() + 10**9,
            )
        accepted, _ = listener.accept()
        try:
            assert accepted.recv(1) == b""  # Failed connection was actually closed.
        finally:
            accepted.close()
    finally:
        listener.close()


@pytest.mark.parametrize("missing", ["directory", "socket"])
def test_absent_series_controller_is_explicit_before_a_connect_or_job(missing, monkeypatch):
    from contextlib import contextmanager
    from unittest.mock import Mock

    from eom_orchestrator.inference_transfer_cpu_handoff import CpuHandoffError

    from tests.unit.embedding_device_benchmark_fixtures import owner_request

    monkeypatch.setattr(
        owner, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.getuid(), os.getgid())
    )

    @contextmanager
    def synthetic_directory(*args, **kwargs):
        if missing == "directory":
            raise CpuHandoffError("INFERENCE_CPU_DIRECTORY_INVALID")
        yield 123

    def absent(*args):
        raise FileNotFoundError("synthetic missing socket")

    monkeypatch.setattr(owner, "protected_cpu_handoff_directory", synthetic_directory)
    monkeypatch.setattr(owner, "_socket_metadata", absent)
    connect = Mock(side_effect=AssertionError("preflight must not create a connection"))
    monkeypatch.setattr(owner.socket, "socket", connect)
    with pytest.raises(ValueError, match="BENCHMARK_SERIES_CONTROLLER_UNAVAILABLE"):
        owner.require_benchmark_series_listener(owner_request())
    connect.assert_not_called()
