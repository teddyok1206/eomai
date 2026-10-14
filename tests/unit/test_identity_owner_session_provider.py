"""Fixed provider forward path with fake API/kernel/installed admission, not activation."""

from __future__ import annotations

import http.client
import os
import time
from typing import Any

import pytest
from eom_identity_service.owner_session_transport import (
    OwnerSessionTransportError,
    export_owner_session_capture,
)
from eom_operator_identity.owner_session_capture import (
    OwnerSessionCaptureRequest,
)
from eom_operator_identity.owner_session_capture_v11 import (
    OwnerSessionCaptureRequestV11,
)
from eom_operator_identity.owner_session_capture_v11 import (
    parse_supported_owner_session_capture_request as parse_owner_session_capture_request,
)
from eom_operator_identity.owner_session_capture_v11 import (
    supported_owner_session_capture_bytes as owner_session_capture_bytes,
)
from eom_orchestrator import identity_owner_session_provider as provider

from tests.unit.test_authenticated_session_fence import SyntheticSession, verified_capture
from tests.unit.test_owner_session_transport import PIN, SyntheticAdmission, SyntheticSocket


def token_fd(token: str) -> int:
    reader, writer = os.pipe()
    os.write(writer, token.encode())
    os.close(writer)
    return reader


def forward(
    monkeypatch: pytest.MonkeyPatch, fault: str = ""
) -> tuple[str, list[str], list[SyntheticSocket], SyntheticAdmission, dict[str, Any]]:
    source, capture = verified_capture(monkeypatch, SyntheticSession())
    events: list[str] = []
    sockets: list[SyntheticSocket] = []
    admission = SyntheticAdmission()
    captured: dict[str, Any] = {}
    clock = [time.monotonic()]

    def owner() -> None:
        events.append("owner")
        if fault == "owner":
            raise RuntimeError(source.raw_token)

    def peer(_socket: object) -> None:
        events.append("peer")
        if fault == "peer":
            raise RuntimeError(source.raw_token)

    class Reply:
        status = 401 if fault == "denied" else 302 if fault == "redirect" else 200

        def getheader(self, name: str, default: str | None = None) -> str | None:
            if name == "Content-Type":
                return "text/plain" if fault == "media" else "application/json"
            if name == "Content-Length":
                return "9000" if fault == "oversize" else str(len(captured["raw"]))
            if name == "Connection" and fault == "server_close":
                return "close"
            return default

        def read(self, maximum: int) -> bytes:
            events.append("read")
            assert maximum == 8193
            if fault == "deadline":
                clock[0] += 11
            if fault == "read":
                raise TimeoutError(source.raw_token + " private digest")
            raw = captured["raw"]
            assert isinstance(raw, bytes)
            if fault == "length":
                return raw + b"extra"
            return raw

    class Connection:
        def __init__(self, host: str, port: int, *, timeout: float) -> None:
            assert (host, port, timeout) == ("127.0.0.1", 8765, 10)
            self.sock: SyntheticSocket | None = None
            events.append("construct")

        def connect(self) -> None:
            events.append("connect")
            if fault == "connect":
                raise TimeoutError(source.raw_token)
            self.sock = SyntheticSocket()
            sockets.append(self.sock)

        def request(self, method: str, path: str, *, body: bytes, headers: dict[str, str]) -> None:
            events.append("send")
            assert events.index("peer") < events.index("send")
            assert (method, path) == ("POST", "/api/v1/auth/owner-session-capture")
            assert headers["Authorization"] == "Bearer " + source.raw_token
            assert headers["Connection"] == "keep-alive"
            request = parse_owner_session_capture_request(body)
            captured["request"] = request
            raw = owner_session_capture_bytes(export_owner_session_capture(request, capture))
            if fault == "wrong_purpose":
                reply = export_owner_session_capture(request, capture).model_copy(
                    update={"purpose": "LOCAL_EMBEDDING_DEVICE_BENCHMARK"}
                )
                raw = owner_session_capture_bytes(reply)
            if fault == "legacy_response":
                legacy = OwnerSessionCaptureRequest(
                    schema_version="operator-owner-session-capture-request/1.0",
                    purpose="LOCAL_EMBEDDING_OPERATOR_SEED",
                    request_id=request.request_id,
                    nonce=request.nonce,
                )
                raw = owner_session_capture_bytes(export_owner_session_capture(legacy, capture))
            if fault == "canonical":
                raw = b" " + raw
            if fault == "hash":
                raw = raw.replace(request.nonce[:16].encode(), b"z" * 16)
                reply = export_owner_session_capture(request, capture).model_copy(
                    update={"request_sha256": "sha256:" + "f" * 64}
                )
                raw = owner_session_capture_bytes(reply)
            captured["raw"] = raw

        def getresponse(self) -> Reply:
            if fault == "admission_late":
                admission.fail = True
            if fault == "socket_close" and self.sock is not None:
                self.sock.close()
            return Reply()

        def close(self) -> None:
            events.append("close")
            if self.sock is not None:
                self.sock.close()
            if fault == "cleanup":
                raise RuntimeError(source.raw_token + " private digest")

    monkeypatch.setattr(provider, "require_inference_transfer_control_owner", owner)
    monkeypatch.setattr(provider, "require_fixed_api_peer_socket", peer)
    monkeypatch.setattr(http.client, "HTTPConnection", Connection)
    if fault == "deadline":
        monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    return source.raw_token, events, sockets, admission, captured


def test_fixed_forward_fd_peer_before_bearer_exact_pins_genuine_import_and_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token, events, sockets, admission, captured = forward(monkeypatch)
    fd = token_fd(token)
    value = provider.FixedIdentityOwnerSessionProvider(PIN, admission).capture_access_from_fd(fd)
    assert value.operator_id == "operator_" + "a" * 32
    assert events.count("connect") == events.count("send") == events.count("read") == 1
    assert events[0] == "owner" and events[-1] == "close"
    assert all(socket.fileno() == -1 for socket in sockets)
    with pytest.raises(OSError):
        os.fstat(fd)
    assert captured["request"].nonce and token not in repr(value)
    assert len(admission.calls) >= 3


@pytest.mark.parametrize(
    "method,purpose",
    (
        ("capture_reference_query_access_from_fd", "REFERENCE_QUERY"),
        ("capture_device_benchmark_access_from_fd", "LOCAL_EMBEDDING_DEVICE_BENCHMARK"),
    ),
)
def test_explicit_purpose_provider_uses_new_exchange_without_seed_fallback(
    monkeypatch, method, purpose
):
    token, events, sockets, admission, captured = forward(monkeypatch)
    fd = token_fd(token)
    client = provider.FixedIdentityOwnerSessionProvider(PIN, admission)
    value = getattr(client, method)(fd)
    assert value.operator_id == "operator_" + "a" * 32
    request = captured["request"]
    assert isinstance(request, OwnerSessionCaptureRequestV11)
    assert request.purpose == purpose
    assert events.count("connect") == events.count("send") == events.count("read") == 1
    assert all(sock.fileno() == -1 for sock in sockets)
    with pytest.raises(OSError):
        os.fstat(fd)


@pytest.mark.parametrize(
    "fault", ("wrong_purpose", "legacy_response", "hash", "canonical", "cleanup", "denied")
)
def test_query_provider_denies_other_purpose_version_and_failed_transport_without_retry(
    monkeypatch, fault
):
    token, events, sockets, admission, _captured = forward(monkeypatch, fault)
    fd = token_fd(token)
    with pytest.raises(OwnerSessionTransportError) as failure:
        provider.FixedIdentityOwnerSessionProvider(
            PIN, admission
        ).capture_reference_query_access_from_fd(fd)
    assert token not in str(failure.value)
    assert events.count("connect") == events.count("send") == 1
    assert all(sock.fileno() == -1 for sock in sockets)
    with pytest.raises(OSError):
        os.fstat(fd)


@pytest.mark.parametrize(
    "fault",
    [
        "owner",
        "peer",
        "connect",
        "denied",
        "redirect",
        "media",
        "oversize",
        "server_close",
        "socket_close",
        "read",
        "length",
        "deadline",
        "canonical",
        "hash",
        "admission_late",
        "cleanup",
    ],
)
def test_failure_sanitized_no_retry_closed_fds_and_no_capture(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    token, events, sockets, admission, _captured = forward(monkeypatch, fault)
    fd = token_fd(token)
    with pytest.raises(OwnerSessionTransportError) as caught:
        provider.FixedIdentityOwnerSessionProvider(PIN, admission).capture_access_from_fd(fd)
    assert token not in str(caught.value) and "private digest" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert events.count("connect") <= 1 and events.count("send") <= 1
    assert all(socket.fileno() == -1 for socket in sockets)
    with pytest.raises(OSError):
        os.fstat(fd)
    if fault == "oversize":
        assert "read" not in events


def test_every_new_exchange_has_fresh_request_no_provider_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token, _events, _sockets, admission, captured = forward(monkeypatch)
    client = provider.FixedIdentityOwnerSessionProvider(PIN, admission)
    client.capture_access_from_fd(token_fd(token))
    first = captured["request"]
    client.capture_access_from_fd(token_fd(token))
    second = captured["request"]
    assert first.nonce != second.nonce and first.request_id != second.request_id


def test_actual_admission_missing_or_failure_denies_before_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token, events, _sockets, admission, _captured = forward(monkeypatch)
    admission.fail = True
    fd = token_fd(token)
    with pytest.raises(OwnerSessionTransportError, match=r"^OWNER_SESSION_PROVIDER_UNAVAILABLE$"):
        provider.FixedIdentityOwnerSessionProvider(PIN, admission).capture_access_from_fd(fd)
    assert events == ["owner"]
    with pytest.raises(OSError):
        os.fstat(fd)
