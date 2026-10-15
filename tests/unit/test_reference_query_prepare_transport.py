"""Real local socket framing and HMAC capture; PID/UID/unit/source/application are synthetic."""

import os
import socket
import struct
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_api.request_context import RequestContext
from eom_api.services import reference_query_prepare_client as client_module
from eom_api.services.reference_query_prepare_client import (
    NativeReferenceQueryPrepareClient,
    ReferenceQueryPrepareClientError,
)
from eom_catalog_contracts.reference_query_prepare import (
    ReferenceQueryPrepareReply,
    ReferenceQueryPrepareRequest,
)
from eom_identifiers import canonical_json_bytes
from eom_identity_service.installed_owner_session_provider import (
    ProtectedInstalledIdentityProviderAdmission,
)
from eom_identity_service.tokens import SessionTokenService
from eom_orchestrator import general_chat_socket as carrier
from eom_orchestrator import reference_query_prepare_transport as transport_module
from eom_orchestrator.reference_query_prepare_transport import (
    handle_reference_query_prepare_connection,
)

from tests.unit.test_authenticated_session_fence import assert_current, verified_capture
from tests.unit.test_catalog_owner_capture_peer import SyntheticApiPeer
from tests.unit.test_installed_identity_provider_observation import observation as observation
from tests.unit.test_reference_query_prepare_contracts import reply_body, request_body


def api_context(monkeypatch):
    source, _capture = verified_capture(monkeypatch)
    pair = SessionTokenService(source.codec).authenticate_and_capture_access(
        source, source.raw_token
    )
    context = RequestContext(
        "synthetic-request",
        datetime.now(UTC),
        "/api/v1/workflows",
        "POST",
        None,
        None,
        None,
        authentication=pair.authentication,
        authenticated_access=pair,
    )
    return source, context


def exchange(observation, monkeypatch, *, fault="", through_http=False):
    source, context = api_context(monkeypatch)
    request = ReferenceQueryPrepareRequest.model_validate(request_body())
    application_calls = []
    final_sends = []
    preparation_sends = []

    original_export = client_module.export_owner_session_capture
    original_send = carrier.send_chat_stream

    def export(challenge, capture):
        response = original_export(challenge, capture)
        if fault == "capture_hash":
            return response.model_copy(update={"request_sha256": "sha256:" + "0" * 64})
        if fault == "capture_purpose":
            return response.model_copy(update={"purpose": "LOCAL_EMBEDDING_DEVICE_BENCHMARK"})
        return response

    def client_send(connection, document, *, deadline, limit):
        if document["schema_version"] == "system-rag-reference-query-prepare-request/1.0":
            preparation_sends.append(document["operation_id"])
            if fault == "noncanonical_request":
                raw = b" " + canonical_json_bytes(document)
                connection.sendall(carrier.STREAM_MAGIC + struct.pack("!I", len(raw)) + raw)
                return
        original_send(connection, document, deadline=deadline, limit=limit)

    def server_send(connection, document, *, deadline, limit):
        if document["schema_version"] == "system-rag-reference-query-prepare-reply/1.0":
            final_sends.append(document)
            if fault == "partial_final_write":
                connection.sendall(carrier.STREAM_MAGIC)
                raise ConnectionError("synthetic partial write, not a retry grant")
            if fault == "wrong_reply":
                document = {**document, "request_sha256": "sha256:" + "0" * 64}
        elif fault == "challenge_purpose":
            document = {**document, "purpose": "LOCAL_EMBEDDING_DEVICE_BENCHMARK"}
        original_send(connection, document, deadline=deadline, limit=limit)

    monkeypatch.setattr(client_module, "export_owner_session_capture", export)
    monkeypatch.setattr(client_module, "send_chat_stream", client_send)
    monkeypatch.setattr(transport_module, "send_chat_stream", server_send)

    def factory(capture):
        assert_current(source, capture)
        application_calls.append(capture.operator_id)
        if fault == "application":
            raise RuntimeError("synthetic private details must not leave the owner")
        return SimpleNamespace(
            prepare=lambda actual: ReferenceQueryPrepareReply.model_validate(reply_body(actual))
        )

    with tempfile.TemporaryDirectory(prefix="eom-query-wire-") as directory:
        parent = Path(directory)
        parent.chmod(0o2750)
        endpoint = carrier.ChatSocketEndpoint(
            parent / "owner.sock", os.geteuid(), os.getegid(), parent_mode=0o2750
        )
        listener = carrier.bind_chat_listener(endpoint, backlog=1)
        # A real server retries its 250ms idle accept. This one-exchange harness
        # must also allow cold HTTP application startup before the first connect;
        # capture and transport deadlines below remain unchanged.
        listener.settimeout(10)
        try:
            installed = ProtectedInstalledIdentityProviderAdmission(observation[0])

            def serve():
                accepted, _address = listener.accept()
                with SyntheticApiPeer(accepted.detach()) as peer:
                    if fault == "pid":
                        peer.peer_credentials = (12346, 1000, 1000)
                    elif fault == "uid":
                        peer.peer_credentials = (12345, 1001, 1000)
                    handle_reference_query_prepare_connection(
                        peer,
                        admission=installed,
                        api_uid=1000,
                        application=factory,
                    )

            # Setup HMAC is complete. The client may export the actual current
            # request capture, but must never authenticate/re-login on this path.
            monkeypatch.setattr(
                SessionTokenService,
                "authenticate_and_capture_access",
                Mock(side_effect=AssertionError("reauthentication")),
            )
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(serve)
                try:
                    native = NativeReferenceQueryPrepareClient(endpoint)
                    if through_http:
                        from eom_api.app import create_app
                        from eom_api.services.reference_query_preparation import (
                            ReferenceQueryPreparationApplicationService,
                        )
                        from fastapi.testclient import TestClient

                        from tests.api.helpers import disconnected_services
                        from tests.api.test_hwpx_endpoints import FakeAudit

                        services = disconnected_services()
                        services.audit = FakeAudit()
                        services.auth = Mock()
                        services.auth.authenticate_and_capture_access.return_value = (
                            context.authenticated_access
                        )
                        services.auth.authenticate_access.side_effect = AssertionError(
                            "HTTP must use current capture"
                        )
                        services.reference_query_preparation = (
                            ReferenceQueryPreparationApplicationService(native)
                        )
                        try:
                            with TestClient(
                                create_app(services), base_url="http://localhost"
                            ) as http:
                                response = http.post(
                                    "/api/v1/knowledge/reference-queries/preparation",
                                    json=request.model_dump(mode="json"),
                                    headers={
                                        "Authorization": "Bearer synthetic-HTTP-only-token",
                                        "Idempotency-Key": request.idempotency_key,
                                    },
                                )
                            future.result(timeout=10)
                            assert response.status_code == 202, {
                                "preparation_sends": len(preparation_sends),
                                "final_statuses": [value["status"] for value in final_sends],
                                "application_calls": len(application_calls),
                            }
                            assert response.headers["Cache-Control"] == "no-store"
                            reply = ReferenceQueryPrepareReply.model_validate(
                                response.json()["data"]
                            )
                            services.auth.authenticate_and_capture_access.assert_called_once()
                        finally:
                            services.engine.dispose()
                    else:
                        reply = native.prepare(context, request)
                except ReferenceQueryPrepareClientError:
                    reply = None
                future.result(timeout=10)
            assert preparation_sends == [request.operation_id]
            assert len(final_sends) <= 1
            if reply is not None:
                assert "synthetic private details" not in repr(reply)
            return source, reply, application_calls
        finally:
            listener.close()


def test_real_handshake_imports_same_current_capture_before_application(observation, monkeypatch):
    source, reply, calls = exchange(observation, monkeypatch)
    assert reply is not None and reply.status == "PENDING" and reply.selection is None
    assert calls == [source.operator.operator_id]
    assert source.raw_token not in repr(reply) and source.token.verifier_hash not in repr(reply)


def test_http_to_real_unix_handshake_preserves_actual_current_capture(observation, monkeypatch):
    source, reply, calls = exchange(observation, monkeypatch, through_http=True)
    assert reply.status == "PENDING" and calls == [source.operator.operator_id]


@pytest.mark.parametrize("fault", ("pid", "uid"))
def test_wrong_real_peer_never_reaches_application(observation, monkeypatch, fault):
    _source, reply, calls = exchange(observation, monkeypatch, fault=fault)
    assert calls == [] and (reply is None or reply.status == "FAILED")


@pytest.mark.parametrize(
    "fault", ("capture_hash", "capture_purpose", "challenge_purpose", "noncanonical_request")
)
def test_invalid_capture_or_noncanonical_request_never_calls_application(
    observation, monkeypatch, fault
):
    _source, reply, calls = exchange(observation, monkeypatch, fault=fault)
    assert calls == [] and (reply is None or reply.status == "FAILED")


@pytest.mark.parametrize("fault", ("application", "partial_final_write", "wrong_reply"))
def test_unknown_outcome_never_reinvokes_application_or_resends_a_final_reply(
    observation, monkeypatch, fault
):
    source, reply, calls = exchange(observation, monkeypatch, fault=fault)
    assert calls == [source.operator.operator_id]
    assert reply is None or reply.status == "FAILED"


def test_actor_only_or_missing_current_pair_fails_before_socket_io(monkeypatch):
    _source, context = api_context(monkeypatch)
    context.authenticated_access = None
    connect = Mock(side_effect=AssertionError("network before current capture"))
    monkeypatch.setattr(socket, "socket", connect)
    with pytest.raises(ReferenceQueryPrepareClientError) as raised:
        NativeReferenceQueryPrepareClient().prepare(
            context, ReferenceQueryPrepareRequest.model_validate(request_body())
        )
    assert raised.value.code == "REFERENCE_QUERY_PREPARE_UNAVAILABLE"
    connect.assert_not_called()


@pytest.mark.parametrize("mode", (0o750, 0o2750))
def test_opt_in_parent_profile_preserves_default_and_does_not_need_group_chown(
    tmp_path, monkeypatch, mode
):
    tmp_path.chmod(mode)
    endpoint = carrier.ChatSocketEndpoint(
        tmp_path / "s", os.geteuid(), os.getegid(), parent_mode=mode
    )
    chown = Mock(side_effect=AssertionError("unnecessary group change"))
    monkeypatch.setattr(carrier.os, "chown", chown)
    listener = carrier.bind_chat_listener(endpoint, backlog=1)
    try:
        endpoint.require_socket()
        assert endpoint.path.lstat().st_gid == os.getegid()
        chown.assert_not_called()
    finally:
        listener.close()


def test_sgid_profile_never_implicitly_weakens_an_existing_endpoint(tmp_path):
    tmp_path.chmod(0o2750)
    with pytest.raises(carrier.ChatTransportError):
        carrier.ChatSocketEndpoint(tmp_path / "s", os.geteuid(), os.getegid()).require_parent()
    with pytest.raises(carrier.ChatTransportError):
        carrier.ChatSocketEndpoint(tmp_path / "s", os.geteuid(), os.getegid(), parent_mode=0o2770)


def test_stream_rejects_oversized_length_before_body_and_keeps_literal_bytes():
    left, right = socket.socketpair()
    with left, right:
        left.sendall(carrier.STREAM_MAGIC + struct.pack("!I", 9))
        with pytest.raises(carrier.ChatTransportError):
            carrier.receive_chat_stream_payload(right, deadline=monotonic() + 1, limit=8)
    raw = b' {"literal":true}'
    left, right = socket.socketpair()
    with left, right:
        left.sendall(carrier.STREAM_MAGIC + struct.pack("!I", len(raw)) + raw)
        assert carrier.receive_chat_stream_payload(right, deadline=monotonic() + 1, limit=32) == raw


@pytest.mark.parametrize("bound", (True, 0, 256001))
def test_bad_stream_budget_never_reads_or_writes(bound):
    left, right = socket.socketpair()
    with left, right:
        with pytest.raises(carrier.ChatTransportError):
            carrier.receive_chat_stream_payload(right, deadline=monotonic() + 1, limit=bound)
        with pytest.raises(carrier.ChatTransportError):
            carrier.send_chat_stream(left, {"x": True}, deadline=monotonic() + 1, limit=bound)
