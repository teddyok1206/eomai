"""Synthetic kernel/HTTP/FD boundaries only; no actual authentication or control."""

from __future__ import annotations

import http.client
import json
import os
import pwd
import socket
import time
from types import SimpleNamespace
from typing import Any

import pytest
from eom_orchestrator import inference_transfer_control_auth as auth
from eom_orchestrator.control_service import ControlPlaneError
from pydantic import SecretStr

_TOKEN = "eom_at_" + "synthetic" * 8
_LOCAL = "0100007F:A123"
_REMOTE = "0100007F:223D"
_HEADER = (
    "  sl  local_address rem_address   st tx_queue rx_queue "
    "tr tm->when retrnsmt uid timeout inode\n"
)


def _table(
    *,
    uid: int = 991,
    local: str = _REMOTE,
    remote: str = _LOCAL,
    state: str = "01",
    inode: int = 42,
) -> bytes:
    return (_HEADER + f" 0: {local} {remote} {state} 0:0 0:0 0 {uid} 0 {inode}\n").encode()


def _reply() -> dict[str, Any]:
    return {
        "data": {
            "operator_id": "operator_" + "a" * 32,
            "username": "synthetic-admin",
            "display_name": "합성 관리자",
            "roles": ["ADMIN"],
            "effective_permissions": ["execution_preset:manage"],
            "session_id": "apisession_" + "b" * 32,
            "authenticated_at": "2026-10-10T09:00:00Z",
            "access_expires_at": "2026-10-10T09:15:00Z",
            "password_change_required": False,
        },
        "meta": {"request_id": "test_request", "api_version": "1"},
    }


@pytest.mark.parametrize("uid", [0, 991, 1234])
def test_exact_reverse_connected_tuple_returns_kernel_uid(uid: int) -> None:
    assert auth._reverse_tcp_uid(_table(uid=uid), local=_LOCAL, remote=_REMOTE) == uid


@pytest.mark.parametrize(
    "changes",
    [
        {"state": "0A"},
        {"local": "0100007F:FFFF"},
        {"remote": "0100007F:FFFF"},
        {"local": _LOCAL, "remote": _REMOTE},
    ],
)
def test_listener_other_connection_or_forward_tuple_is_not_peer_identity(
    changes: dict[str, Any],
) -> None:
    assert auth._reverse_tcp_uid(_table(**changes), local=_LOCAL, remote=_REMOTE) is None


@pytest.mark.parametrize(
    "raw",
    [
        b"garbage",
        _HEADER.encode() + b"short\n",
        _table(inode=0),
        _table() + _table().split(b"\n", 1)[1],
    ],
)
def test_missing_malformed_or_ambiguous_kernel_identity_fails(raw: bytes) -> None:
    with pytest.raises(ValueError):
        auth._reverse_tcp_uid(raw, local=_LOCAL, remote=_REMOTE)


def test_kernel_table_both_byte_and_row_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "_TCP_TABLE_BYTES", 64)
    with pytest.raises(ValueError):
        auth._reverse_tcp_uid(_table(), local=_LOCAL, remote=_REMOTE)
    monkeypatch.setattr(auth, "_TCP_TABLE_BYTES", 4096)
    monkeypatch.setattr(auth, "_TCP_TABLE_ROWS", 1)
    with pytest.raises(ValueError):
        auth._reverse_tcp_uid(_table() + _table().split(b"\n", 1)[1], local=_LOCAL, remote=_REMOTE)


def _pipe(payload: bytes) -> int:
    reader, writer = os.pipe()
    os.write(writer, payload)
    os.close(writer)
    return reader


def test_bearer_is_consumed_from_fd_closed_and_secret_repr() -> None:
    descriptor = _pipe((_TOKEN + "\n").encode())
    secret = auth.read_control_bearer_fd(descriptor)
    assert secret.get_secret_value() == _TOKEN
    assert _TOKEN not in repr(secret)
    with pytest.raises(OSError):
        os.fstat(descriptor)


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"not-a-token",
        (_TOKEN + "\r\nInjected: yes").encode(),
        (_TOKEN + "\n\n").encode(),
        b"eom_at_" + b"x" * 600,
        b"eom_at_\xff",
    ],
)
def test_invalid_fd_data_is_sanitized_and_closed(payload: bytes) -> None:
    descriptor = _pipe(payload)
    with pytest.raises(ControlPlaneError) as caught:
        auth.read_control_bearer_fd(descriptor)
    assert caught.value.code == "CONTROL_AUTHORIZATION_REQUIRED"
    assert _TOKEN not in str(caught.value)
    with pytest.raises(OSError):
        os.fstat(descriptor)


def test_stalled_fd_writer_fails_without_waiting() -> None:
    reader, writer = os.pipe()
    try:
        with pytest.raises(ControlPlaneError):
            auth.read_control_bearer_fd(reader)
    finally:
        os.close(writer)


class _Socket:
    family = socket.AF_INET
    type = socket.SOCK_STREAM

    def getsockname(self) -> tuple[str, int]:
        return ("127.0.0.1", 0xA123)

    def getpeername(self) -> tuple[str, int]:
        return ("127.0.0.1", 8765)


def test_peer_uid_check_rejects_before_sending_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=991))
    monkeypatch.setattr(os, "open", lambda *args: 10)
    monkeypatch.setattr(os, "close", lambda fd: None)
    values = iter([_table(uid=1234), b""])
    monkeypatch.setattr(os, "read", lambda *args: next(values))
    with pytest.raises(ControlPlaneError) as caught:
        auth._require_api_peer_socket(_Socket())  # type: ignore[arg-type]
    assert caught.value.code == "CONTROL_AUTH_SERVICE_UNAVAILABLE"


def test_verified_reverse_kernel_uid_allows_connected_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=991))
    monkeypatch.setattr(os, "open", lambda *args: 10)
    monkeypatch.setattr(os, "close", lambda fd: None)
    values = iter([_table(), b""])
    monkeypatch.setattr(os, "read", lambda *args: next(values))
    auth._require_api_peer_socket(_Socket())  # type: ignore[arg-type]


def test_peer_acceptance_wait_is_bounded_and_never_substitutes_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=991))
    monkeypatch.setattr(os, "open", lambda *args: 10)
    monkeypatch.setattr(os, "close", lambda fd: None)
    values = iter([member for _ in range(5) for member in (_table(state="0A"), b"")])
    monkeypatch.setattr(os, "read", lambda *args: next(values))
    waits: list[float] = []
    monkeypatch.setattr(time, "sleep", waits.append)
    with pytest.raises(ControlPlaneError):
        auth._require_api_peer_socket(_Socket())  # type: ignore[arg-type]
    assert waits == [0.01] * 4


def test_api_uid_missing_fails_closed_without_kernel_or_header_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pwd, "getpwnam", lambda name: (_ for _ in ()).throw(KeyError(name)))
    monkeypatch.setattr(os, "open", lambda *args: pytest.fail())
    with pytest.raises(ControlPlaneError):
        auth._require_api_peer_socket(_Socket())  # type: ignore[arg-type]


def test_regular_credential_fd_requires_private_owner_single_link_and_byte_bound(
    tmp_path: Any,
) -> None:
    path = tmp_path / "private-token"
    path.write_bytes(_TOKEN.encode())
    path.chmod(0o600)
    assert auth.read_control_bearer_fd(os.open(path, os.O_RDONLY)).get_secret_value() == _TOKEN
    path.chmod(0o644)
    with pytest.raises(ControlPlaneError):
        auth.read_control_bearer_fd(os.open(path, os.O_RDONLY))
    path.chmod(0o600)
    os.link(path, tmp_path / "other")
    with pytest.raises(ControlPlaneError):
        auth.read_control_bearer_fd(os.open(path, os.O_RDONLY))


def test_direct_reader_does_not_bypass_token_byte_bound() -> None:
    with pytest.raises(ControlPlaneError):
        auth.FixedApiControlPrincipalReader(SecretStr("eom_at_" + "a" * 600))


class _Response:
    def __init__(
        self, payload: bytes, status: int = 200, content_type: str = "application/json"
    ) -> None:
        self.payload, self.status, self.content_type = payload, status, content_type

    def getheader(self, _name: str, _default: str) -> str:
        return self.content_type

    def read(self, amount: int) -> bytes:
        return self.payload[:amount]


class _Connection:
    def __init__(self, events: list[str], response: _Response) -> None:
        self.events, self.response = events, response
        self.sock = _Socket()

    def connect(self) -> None:
        self.events.append("CONNECT")

    def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
        assert method == "GET" and path == "/api/v1/auth/me"
        assert headers["Authorization"] == "Bearer " + _TOKEN
        self.events.append("SEND")

    def getresponse(self) -> _Response:
        return self.response

    def close(self) -> None:
        self.events.append("CLOSE")


def _http(
    monkeypatch: pytest.MonkeyPatch, response: _Response, *, peer_ok: bool = True
) -> list[str]:
    events: list[str] = []

    def factory(host: str, port: int, *, timeout: float) -> _Connection:
        assert (host, port, timeout) == ("127.0.0.1", 8765, 10.0)
        return _Connection(events, response)

    def peer(_socket: Any) -> None:
        events.append("PEER")
        if not peer_ok:
            raise ControlPlaneError("CONTROL_AUTH_SERVICE_UNAVAILABLE", "peer unavailable")

    monkeypatch.setattr(http.client, "HTTPConnection", factory)
    monkeypatch.setattr(auth, "_require_api_peer_socket", peer)
    return events


def test_fixed_http_checks_uid_before_header_and_ignores_env_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://untrusted.invalid:8765")
    events = _http(monkeypatch, _Response(json.dumps(_reply()).encode()))
    result = auth.FixedApiControlPrincipalReader(SecretStr(_TOKEN)).read()
    assert result.operator_id == "operator_" + "a" * 32
    assert events == ["CONNECT", "PEER", "SEND", "CLOSE"]


def test_unverified_peer_never_receives_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    events = _http(monkeypatch, _Response(b""), peer_ok=False)
    with pytest.raises(ControlPlaneError):
        auth.FixedApiControlPrincipalReader(SecretStr(_TOKEN)).read()
    assert events == ["CONNECT", "PEER", "CLOSE"]


@pytest.mark.parametrize(
    "response",
    [
        _Response(b"", status=302),
        _Response(b"", status=401),
        _Response(b"", status=403),
        _Response(b"", status=503),
        _Response(b"{}", content_type="text/html"),
        _Response(b"{}"),
        _Response(b'{"data":{},"data":{}}'),
        _Response(b"NaN"),
        _Response(b"x" * (64 * 1024 + 1)),
    ],
)
def test_http_no_redirect_retry_or_unvalidated_reply(
    monkeypatch: pytest.MonkeyPatch, response: _Response
) -> None:
    events = _http(monkeypatch, response)
    with pytest.raises(ControlPlaneError) as caught:
        auth.FixedApiControlPrincipalReader(SecretStr(_TOKEN)).read()
    assert caught.value.code in {
        "CONTROL_AUTH_SERVICE_UNAVAILABLE",
        "CONTROL_AUTHORIZATION_REQUIRED",
    }
    assert events == ["CONNECT", "PEER", "SEND", "CLOSE"]
    assert _TOKEN not in str(caught.value)


def test_reply_extra_authority_is_not_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _reply()
    raw["data"]["is_admin"] = True
    _http(monkeypatch, _Response(json.dumps(raw).encode()))
    with pytest.raises(ControlPlaneError):
        auth.FixedApiControlPrincipalReader(SecretStr(_TOKEN)).read()
