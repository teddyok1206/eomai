"""Actual private socket/inode cleanup; root UID and protected-directory fixture are synthetic."""

import os
import socket
import tempfile
from contextlib import contextmanager
from pathlib import Path

import pytest
from eom_catalog_service import embedding_benchmark_root_socket as module
from eom_orchestrator.inference_transfer_cpu_handoff import CpuHandoffIdentity


@pytest.fixture
def private_listener(monkeypatch):
    monkeypatch.setattr(module, "require_root_benchmark_control", lambda: None)
    monkeypatch.setattr(
        module, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.getuid(), os.getgid())
    )
    monkeypatch.setattr(module.os, "chown", lambda *args, **kwargs: None)

    @contextmanager
    def directory(path, **kwargs):
        descriptor = os.open(path, os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            yield descriptor
        finally:
            os.close(descriptor)

    monkeypatch.setattr(module, "protected_cpu_handoff_directory", directory)
    with tempfile.TemporaryDirectory(prefix="eom-root-socket-") as temporary:
        root = Path(temporary)
        monkeypatch.setattr(module, "BENCHMARK_CONTROL_ROOT", root)
        yield root


def test_owned_listener_has_fixed_mode_and_removes_only_its_own_socket(private_listener):
    name = "series-" + "a" * 32 + ".sock"
    path = private_listener / name
    with module.root_benchmark_listener(name) as listener:
        assert not listener.get_inheritable() and not listener.getblocking()
        assert path.stat().st_mode & 0o777 == 0o660
        assert listener.getsockname() == str(path)
    assert not path.exists()


def test_existing_listener_is_not_unlinked_or_replaced(private_listener):
    name = "b" * 32 + ".sock"
    path = private_listener / name
    original = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    original.bind(str(path))
    inode = path.stat().st_ino
    try:
        with pytest.raises(OSError), module.root_benchmark_listener(name):
            pytest.fail("existing socket must not be replaced")
        assert path.stat().st_ino == inode
    finally:
        original.close()


def test_replaced_named_inode_is_preserved_and_reported_as_uncertain(private_listener):
    name = "c" * 32 + ".sock"
    path = private_listener / name
    replacement = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        with (
            pytest.raises(ValueError, match="SOCKET_CHANGED"),
            module.root_benchmark_listener(name),
        ):
            original_inode = path.stat().st_ino
            path.unlink()
            replacement.bind(str(path))
            assert path.stat().st_ino != original_inode
        assert path.exists()
    finally:
        replacement.close()


@pytest.mark.parametrize("name", ["../escape.sock", "series-x.sock", "a" * 64 + ".sock", True])
def test_only_fixed_execution_or_series_names_are_accepted(private_listener, name):
    with (
        pytest.raises(ValueError, match="CONTROL_NAME_INVALID"),
        module.root_benchmark_listener(name),
    ):
        pytest.fail("untrusted socket name accepted")
    assert not tuple(private_listener.iterdir())
