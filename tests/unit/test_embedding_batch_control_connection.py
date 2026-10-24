"""Actual local sockets/markers; unit/process/root identity seams are explicitly synthetic."""

from __future__ import annotations

import os
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_service import embedding_batch_control_connection as connection
from eom_catalog_service import embedding_batch_control_workspace as workspace
from eom_catalog_service.embedding_benchmark_channel import BenchmarkUnixPeer
from eom_orchestrator.inference_transfer_cpu_handoff import CpuHandoffIdentity

from tests.unit.test_embedding_batch_control_workspace import control_local as control_local


@pytest.fixture
def local(control_local, monkeypatch):
    monkeypatch.setattr(
        connection, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.getuid(), os.getgid())
    )
    monkeypatch.setattr(connection, "require_fixed_cpu_unit_template", Mock())
    status = SimpleNamespace(
        process_started=False, active_state="inactive", need_daemon_reload=False
    )
    unit = SimpleNamespace(
        fresh=True,
        status=status,
        main_pid=0,
        invocation_id="",
        fragment_path="/etc/systemd/system/" + workspace.BATCH_CONTROL_TEMPLATE,
        drop_in_paths="",
    )
    monkeypatch.setattr(connection, "inspect_cpu_unit", Mock(return_value=unit))
    return workspace.stage_embedding_batch_control(control_local), unit


def test_listener_keeps_one_socket_and_removes_only_its_own_inode(local):
    staged, _ = local
    with connection.owner_embedding_batch_listener(staged) as listener:
        listener.assert_current()
        assert (staged.path / "control.sock").stat().st_mode & 0o777 == 0o660
        assert staged.request == listener.staged.request
    assert not (staged.path / "control.sock").exists()
    assert (staged.path / "allocation.json").exists()


@pytest.mark.parametrize("failure", (None, "timeout", "returncode"))
def test_dispatch_marks_original_once_even_when_start_outcome_is_unknown(
    local, monkeypatch, failure
):
    staged, _ = local
    run = Mock(
        return_value=SimpleNamespace(
            returncode=0 if failure != "returncode" else 1, stdout=b"", stderr=b""
        )
    )
    if failure == "timeout":
        run.side_effect = subprocess.TimeoutExpired("systemctl", 10)
    monkeypatch.setattr(connection.subprocess, "run", run)
    with connection.owner_embedding_batch_listener(staged) as listener:
        if failure:
            with pytest.raises((ValueError, subprocess.TimeoutExpired)):
                connection.dispatch_embedding_batch_control(listener)
        else:
            connection.dispatch_embedding_batch_control(listener)
        assert (staged.path / ".dispatch-attempted").read_text() == staged.request.message_sha256
        with pytest.raises(RuntimeError, match="ALREADY_ATTEMPTED"):
            connection.dispatch_embedding_batch_control(listener)
    assert run.call_count == 1
    assert run.call_args.args[0] == (
        "/usr/bin/systemctl",
        "--no-ask-password",
        "--no-block",
        "start",
        workspace.embedding_batch_control_unit(staged.attempt_hex),
    )
    assert set(run.call_args.kwargs["env"]) == {"PATH", "TZ", "LANG"}


@pytest.mark.parametrize("fault", ("not_fresh", "dropin", "reload", "fragment", "no_listener"))
def test_unavailable_or_changed_boundary_never_consumes_dispatch(local, monkeypatch, fault):
    staged, unit = local
    if fault == "not_fresh":
        unit.fresh = False
    elif fault == "dropin":
        unit.drop_in_paths = "/etc/systemd/system/other.conf"
    elif fault == "reload":
        unit.status.need_daemon_reload = True
    elif fault == "fragment":
        unit.fragment_path = "/tmp/other.service"
    run = Mock()
    monkeypatch.setattr(connection.subprocess, "run", run)
    with connection.owner_embedding_batch_listener(staged) as listener:
        if fault == "no_listener":
            listener.socket.close()
        with pytest.raises(ValueError):
            connection.dispatch_embedding_batch_control(listener)
    run.assert_not_called()
    assert not (staged.path / ".dispatch-attempted").exists()


@pytest.mark.parametrize(
    "fault", (None, "pid", "invocation", "dropin", "reload", "fragment", "changed")
)
def test_accept_requires_actual_original_root_unit_identity_before_channel_binding(
    local, monkeypatch, fault
):
    staged, unit = local
    unit.main_pid = os.getpid() + (1 if fault == "pid" else 0)
    unit.status.process_started, unit.status.active_state = True, "activating"
    unit.invocation_id = "1" * 32 if fault != "invocation" else ""
    if fault == "dropin":
        unit.drop_in_paths = "extra.conf"
    elif fault == "reload":
        unit.status.need_daemon_reload = True
    elif fault == "fragment":
        unit.fragment_path = "/tmp/not-fixed.service"
    monkeypatch.setattr(connection, "_peer", lambda _: BenchmarkUnixPeer(os.getpid(), 0, 0))
    monkeypatch.setattr(connection, "embedding_batch_owner_start_ticks", lambda *_a, **_kw: 123)
    factory = Mock(return_value=Mock())
    monkeypatch.setattr(connection, "bind_original_embedding_batch_owner_channel", factory)
    if fault == "changed":
        changed = SimpleNamespace(**(vars(unit) | {"invocation_id": "2" * 32}))
        connection.inspect_cpu_unit.side_effect = [unit, changed]
    with (
        connection.owner_embedding_batch_listener(staged) as listener,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        pending = pool.submit(listener.accept_root, controller_release="a" * 40)
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            client.connect(str(staged.path / "control.sock"))
            if fault:
                with pytest.raises(ValueError):
                    pending.result(timeout=5)
                if fault == "changed":
                    factory.return_value.close.assert_called_once()
                else:
                    factory.assert_not_called()
            else:
                assert pending.result(timeout=5) is factory.return_value
        finally:
            client.close()


def test_replaced_socket_is_preserved_instead_of_unlinked_as_our_own(local):
    staged, _ = local
    replacement = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        with (
            pytest.raises(ValueError),
            connection.owner_embedding_batch_listener(staged) as listener,
        ):
            listener.socket.close()
            (staged.path / "control.sock").unlink()
            replacement.bind(str(staged.path / "control.sock"))
            with pytest.raises(ValueError):
                listener.assert_current()
        assert (staged.path / "control.sock").exists()
        assert (staged.path / "allocation.json").exists()
    finally:
        replacement.close()


def test_nonroot_cannot_connect_as_root_source_proxy(local):
    staged, _ = local
    with pytest.raises(ValueError):
        connection.connect_embedding_batch_source_owner(staged, controller_release="a" * 40)
