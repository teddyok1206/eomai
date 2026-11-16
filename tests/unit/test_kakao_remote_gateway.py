"""Gateway source checks: synthetic grants and real isolated local child streams only."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_kakao_archive_contracts.kakao_remote import GatewayLeaseGrant, GatewayRevocation
from eom_kakao_archive_gateway import supervisor
from eom_kakao_archive_gateway.grant_file import (
    GatewayRuntimeError,
    read_owner_grant,
    read_protected,
)
from eom_kakao_archive_gateway.process import GatewayChild

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 16, 12, tzinfo=UTC)


def grant(**updates):
    return GatewayLeaseGrant.model_validate(
        {
            "schema_version": "kakao-remote-gateway-grant/1.0",
            "lease_id": "kakaoremotelease_" + "1" * 32,
            "source_binding_id": "kakaobinding_" + "2" * 32,
            "profile_id": "kakaoprofile_" + "3" * 32,
            "fence_epoch": 4,
            "gateway_epoch": 5,
            "grant_revision": 1,
            "issued_at": NOW,
            "authorized_at": NOW,
            "expires_at": NOW + timedelta(seconds=30),
            "absolute_expires_at": NOW + timedelta(minutes=20),
            **updates,
        }
    )


def revoked():
    original = grant()
    return GatewayRevocation(
        schema_version="kakao-remote-gateway-revocation/1.0",
        lease_id=original.lease_id,
        fence_epoch=original.fence_epoch,
        gateway_epoch=original.gateway_epoch,
        grant_revision=1,
        reason="LOGOUT",
    )


@pytest.fixture
def secure_tmp():
    # /tmp is intentionally rejected by the production no-world-writable-parent rule.
    with tempfile.TemporaryDirectory(prefix="gateway-test-", dir=ROOT / "staging") as directory:
        yield Path(directory)


def write_grant(directory, value=None):
    path = directory / "grant.json"
    path.write_text((value or grant()).model_dump_json(), encoding="utf-8")
    path.chmod(0o640)
    return path


def test_bounded_owner_reader_grant_then_revocation_atomic_replace(secure_tmp):
    path = write_grant(secure_tmp)
    assert read_owner_grant(path, owner_uid=os.getuid()) == grant()
    replacement = secure_tmp / "next.json"
    replacement.write_text(revoked().model_dump_json(), encoding="utf-8")
    replacement.chmod(0o440)
    replacement.replace(path)
    assert read_owner_grant(path, owner_uid=os.getuid()) == revoked()


@pytest.mark.parametrize("mode", [0o600, 0o644, 0o660, 0o666, 0o777])
def test_grant_reader_requires_private_read_only_group_mode(secure_tmp, mode):
    path = write_grant(secure_tmp)
    path.chmod(mode)
    with pytest.raises(GatewayRuntimeError, match="MEMBER_UNSAFE"):
        read_owner_grant(path, owner_uid=os.getuid())


def test_grant_reader_rejects_wrong_owner(secure_tmp):
    path = write_grant(secure_tmp)
    with pytest.raises(GatewayRuntimeError):
        read_owner_grant(path, owner_uid=os.getuid() + 1)


def test_pinned_empty_static_asset_does_not_relax_grants_or_executables(secure_tmp):
    path = secure_tmp / ".gitmodules"
    path.write_bytes(b"")
    path.chmod(0o640)
    arguments = dict(uid=os.getuid(), limit=1024, allowed_uids=frozenset({0, os.getuid()}))
    assert read_protected(path, minimum_size=0, **arguments) == b""
    with pytest.raises(GatewayRuntimeError, match="MEMBER_UNSAFE"):
        read_protected(path, **arguments)
    with pytest.raises(GatewayRuntimeError, match="MEMBER_UNSAFE"):
        read_owner_grant(path, owner_uid=os.getuid())
    with pytest.raises(GatewayRuntimeError, match="READ_LIMIT_INVALID"):
        read_protected(path, minimum_size=-1, **arguments)


@pytest.mark.parametrize(
    "kind",
    [
        "link",
        "hardlink",
        "fifo",
        "large",
        "empty",
        "duplicate",
        "invalid",
        "parent_link",
        "parent_writable",
    ],
)
def test_unsafe_grant_input_does_not_authorize(secure_tmp, kind):
    inner = secure_tmp / "inner"
    inner.mkdir(mode=0o750)
    path = write_grant(inner)
    if kind == "link":
        alias = inner / "alias.json"
        alias.symlink_to(path)
        path = alias
    elif kind == "hardlink":
        os.link(path, inner / "alias.json")
    elif kind == "fifo":
        path.unlink()
        os.mkfifo(path, 0o640)
    elif kind == "large":
        path.write_bytes(b" " * 4097)
    elif kind == "empty":
        path.write_bytes(b"")
    elif kind == "duplicate":
        path.write_bytes(b'{"schema_version":"a","schema_version":"b"}')
    elif kind == "invalid":
        path.write_bytes(b'{"bearer":"never accepted"}')
    elif kind == "parent_link":
        (secure_tmp / "alias").symlink_to(inner, target_is_directory=True)
        path = secure_tmp / "alias" / path.name
    elif kind == "parent_writable":
        inner.chmod(0o770)
    with pytest.raises((OSError, GatewayRuntimeError)):
        read_owner_grant(path, owner_uid=os.getuid())


CHILD = """
import os, signal, socket, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.bind(sys.argv[1]); s.listen(1)
c, _ = s.accept()
pid = os.fork()
if pid == 0:
    s.close()
    c.sendall(b'accepted')
    while True: time.sleep(0.02)
c.close()
if sys.argv[2] == 'exit': os._exit(0)
while True: time.sleep(0.02)
"""


def launch(path, *, exit_leader=False):
    return subprocess.Popen(
        [sys.executable, "-I", "-B", "-c", CHILD, str(path), "exit" if exit_leader else "stay"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def connect(path):
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(3)
    deadline = time.monotonic() + 3
    while True:
        try:
            connection.connect(str(path))
            break
        except (FileNotFoundError, ConnectionRefusedError):
            if time.monotonic() >= deadline:
                connection.close()
                raise
            time.sleep(0.01)
    assert connection.recv(8) == b"accepted"
    return connection


@pytest.mark.parametrize("exit_leader", [False, True])
def test_group_stop_closes_existing_stream_even_after_leader_exit(tmp_path, exit_leader):
    path = tmp_path / "s.sock"
    child = GatewayChild(launch(path, exit_leader=exit_leader))
    try:
        with connect(path) as connection:
            if exit_leader:
                deadline = time.monotonic() + 3
                while not child.exited() and time.monotonic() < deadline:
                    time.sleep(0.01)
                assert child.exited()
            child.close()
            assert connection.recv(1) == b""
            assert child.closed
            child.close()  # Never kill a possibly reused PGID after reaping.
    finally:
        child.close()


@pytest.mark.parametrize(
    "ending",
    [
        "revoked",
        "missing",
        "invalid",
        "stale",
        "wrong_epoch",
        "expired",
        "clock",
        "owner_stop",
        "late_renewal",
    ],
)
def test_watchdog_closes_already_connected_child_on_all_endings(tmp_path, ending):
    path = tmp_path / "s.sock"
    state = {"value": grant(), "utc": NOW, "mono": 100.0}
    stopping = threading.Event()

    def read():
        if isinstance(state["value"], Exception):
            raise state["value"]
        return state["value"]

    def run():
        supervisor.supervise(
            read,
            lambda: launch(path),
            stopping=stopping,
            listener_ready=lambda: True,
            notify_ready=lambda _: None,
            utc_now=lambda: state["utc"],
            monotonic_now=lambda: state["mono"],
        )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(run)
        try:
            with connect(path) as connection:
                if ending == "revoked":
                    state["value"] = revoked()
                elif ending == "missing":
                    state["value"] = FileNotFoundError()
                elif ending == "invalid":
                    state["value"] = GatewayRuntimeError("KAKAO_GATEWAY_GRANT_INVALID")
                elif ending == "stale":
                    state["value"] = grant(grant_revision=2)
                    time.sleep(0.2)
                    state["value"] = grant()
                elif ending == "wrong_epoch":
                    state["value"] = grant(gateway_epoch=6)
                elif ending == "expired":
                    state["utc"] = NOW + timedelta(seconds=30)
                elif ending == "clock":
                    state["mono"] = 99.0
                elif ending == "owner_stop":
                    stopping.set()
                elif ending == "late_renewal":
                    state["value"] = grant(
                        grant_revision=2,
                        authorized_at=NOW + timedelta(seconds=29),
                        expires_at=NOW + timedelta(seconds=59),
                    )
                    state["utc"] = NOW + timedelta(seconds=31)
                    state["mono"] = 131.0
                assert connection.recv(1) == b""
            if ending in {"revoked", "expired", "owner_stop", "late_renewal"}:
                future.result(timeout=3)
            else:
                with pytest.raises((ValueError, OSError)):
                    future.result(timeout=3)
        finally:
            stopping.set()


def test_missing_or_expired_initial_grant_never_launches():
    calls = []

    def no_launch():
        calls.append(True)
        raise AssertionError("must not launch")

    for initial in (revoked(), grant()):
        with pytest.raises(ValueError):
            supervisor.supervise(
                lambda initial=initial: initial,
                no_launch,
                stopping=threading.Event(),
                listener_ready=lambda: True,
                notify_ready=lambda _: None,
                utc_now=lambda: NOW + timedelta(seconds=30),
                monotonic_now=lambda: 100.0,
            )
    assert calls == []


def test_actual_owner_file_revocation_closes_existing_connection(secure_tmp, tmp_path):
    path = write_grant(secure_tmp)
    socket_path = tmp_path / "s.sock"
    stopping = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            supervisor.supervise,
            lambda: read_owner_grant(path, owner_uid=os.getuid()),
            lambda: launch(socket_path),
            stopping=stopping,
            listener_ready=lambda: True,
            notify_ready=lambda _: None,
            utc_now=lambda: NOW,
            monotonic_now=lambda: 100.0,
        )
        try:
            with connect(socket_path) as connection:
                replacement = secure_tmp / "replacement.json"
                replacement.write_text(revoked().model_dump_json(), encoding="utf-8")
                replacement.chmod(0o440)
                replacement.replace(path)
                assert connection.recv(1) == b""
            future.result(timeout=3)
        finally:
            stopping.set()


@pytest.mark.parametrize("case", ["timeout", "notify_failure", "expires_during_ready_probe"])
def test_startup_never_reports_ready_past_deadline_and_closes_children(tmp_path, case):
    path = tmp_path / "s.sock"
    state = {"mono": 100.0, "probe": False}
    stopping = threading.Event()
    notify = Mock(side_effect=ValueError("notify failed") if case == "notify_failure" else None)

    def ready():
        if state["probe"] and case == "expires_during_ready_probe":
            state["mono"] = 130.0
        return state["probe"]

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            supervisor.supervise,
            grant,
            lambda: launch(path),
            stopping=stopping,
            listener_ready=ready,
            notify_ready=notify,
            utc_now=lambda: NOW,
            monotonic_now=lambda: state["mono"],
        )
        try:
            with connect(path) as connection:
                if case == "timeout":
                    state["mono"] = 110.0
                else:
                    state["probe"] = True
                assert connection.recv(1) == b""
            if case == "expires_during_ready_probe":
                future.result(timeout=3)
            else:
                with pytest.raises(ValueError):
                    future.result(timeout=3)
            assert notify.call_count == (1 if case == "notify_failure" else 0)
        finally:
            stopping.set()


def test_listener_ready_rejects_stale_inode_until_actually_listening(secure_tmp, monkeypatch):
    path = secure_tmp / "gateway.sock"
    monkeypatch.setattr(supervisor, "LISTENER", path)
    monkeypatch.setattr(supervisor.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=os.getuid()))
    monkeypatch.setattr(supervisor.grp, "getgrnam", lambda _: SimpleNamespace(gr_gid=os.getgid()))
    assert supervisor._listener_ready() is False
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(path))
        path.chmod(0o660)
        assert supervisor._listener_ready() is False
        listener.listen(1)
        assert supervisor._listener_ready() is True
    assert supervisor._listener_ready() is False


def test_notify_contains_only_fixed_immutable_identity(monkeypatch):
    value = grant()
    connection = Mock()
    channel = Mock()
    channel.__enter__ = Mock(return_value=connection)
    channel.__exit__ = Mock(return_value=False)
    factory = Mock(return_value=channel)
    monkeypatch.setattr(supervisor.socket, "socket", factory)
    monkeypatch.setenv("NOTIFY_SOCKET", "/run/systemd/notify")
    supervisor._notify_ready(value)
    connection.connect.assert_called_once_with("/run/systemd/notify")
    connection.sendall.assert_called_once_with(
        (
            "READY=1\nSTATUS=KAKAO_GATEWAY_STARTED:" + supervisor.gateway_execution_digest(value)
        ).encode()
    )
    monkeypatch.setenv("NOTIFY_SOCKET", "/tmp/untrusted")
    with pytest.raises(GatewayRuntimeError, match="NOTIFY_INVALID"):
        supervisor._notify_ready(value)
    assert factory.call_count == 1


def test_gateway_uid_checks_actual_vnc_peer_and_fixed_membership(secure_tmp, monkeypatch):
    path = secure_tmp / "vnc.sock"
    group = secure_tmp / "browser-cgroup"
    group.mkdir(mode=0o750)
    members = group / "cgroup.procs"
    members.write_text(str(os.getpid()) + "\n", encoding="ascii")
    monkeypatch.setattr(supervisor, "TARGET", path)
    monkeypatch.setattr(supervisor, "VNC_CGROUP", group)
    monkeypatch.setattr(supervisor.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=os.getuid()))
    monkeypatch.setattr(supervisor.grp, "getgrnam", lambda _: SimpleNamespace(gr_gid=os.getgid()))
    protected = supervisor.protected_directory
    monkeypatch.setattr(
        supervisor,
        "protected_directory",
        lambda target, **kwargs: (
            protected(target, allowed_uids=frozenset({0, os.getuid()}))
            if target == group
            else protected(target, **kwargs)
        ),
    )
    assert supervisor._target_ready() is False
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(path))
        path.chmod(0o660)
        listener.listen(3)
        assert supervisor._target_ready() is True
        members.write_text("2147483647\n", encoding="ascii")
        with pytest.raises(GatewayRuntimeError, match="TARGET_PEER_INVALID"):
            supervisor._target_ready()
        members.write_text("not a pid\n", encoding="ascii")
        with pytest.raises(GatewayRuntimeError, match="TARGET_PEER_INVALID"):
            supervisor._target_ready()
    assert supervisor._target_ready() is False


def test_fixed_argv_has_only_uds_and_installed_assets():
    argv = supervisor.gateway_argv()
    assert argv == (
        str(supervisor.PYTHON),
        "-I",
        "-B",
        "-m",
        "websockify",
        "--unix-listen",
        str(supervisor.LISTENER),
        "--unix-listen-mode",
        "0660",
        "--unix-target",
        str(supervisor.TARGET),
        "--web",
        str(supervisor.ASSETS),
        "--file-only",
    )
    assert not {
        "--libserver",
        "--daemon",
        "--record",
        "--traffic",
        "--token-source",
        "--run-once",
    }.intersection(argv)


def test_unit_isolated_identity_lifetime_and_no_autorestart():
    text = (ROOT / "infra/systemd/eom-kakao-remote.service").read_text()
    for required in (
        "User=eom-kakao-remote",
        "Group=eom-kakao-proxy",
        "RuntimeDirectoryPreserve=yes",
        "SupplementaryGroups=eom-kakao-vnc eom-kakao-grant",
        "KillMode=control-group",
        "SendSIGKILL=yes",
        "Restart=no",
        "TimeoutStopSec=3",
        "RestrictAddressFamilies=AF_UNIX",
        "PrivateNetwork=yes",
        "NoNewPrivileges=yes",
        "-/var/lib/eom-kakao -/run/eom-kakao-private",
        "/mnt/nas",
        "-I -B -m eom_kakao_archive_gateway.supervisor",
        "ExecStopPost=/opt/eom/conda/envs/eom-kakao-remote/bin/python "
        "-I -B -m eom_kakao_archive_gateway.endpoint_cleanup",
    ):
        assert required in text
    assert "EnvironmentFile=" not in text and "ExecStartPre=" not in text


def test_cli_rejects_all_arguments_without_reading_grant():
    result = subprocess.run(
        [sys.executable, "-B", "-m", "eom_kakao_archive_gateway.supervisor", "--help"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 2
    assert result.stderr.strip() == "KAKAO_GATEWAY_ARGUMENTS_FORBIDDEN"


def test_package_has_no_pdf_browser_database_dependency():
    import tomllib

    package = tomllib.loads((ROOT / "services/kakao_archive_gateway/pyproject.toml").read_text())
    assert package["project"]["dependencies"] == ["eom-kakao-archive-contracts==0.1.0"]
    assert package["project"]["optional-dependencies"]["remote"] == ["websockify==0.13.0"]
    assert not (
        ROOT / "services/kakao_archive_worker/eom_kakao_archive_worker/remote_gateway_lifetime.py"
    ).exists()
