"""One fixed API peer exchange; no session cache, SQL, native execution or listener default."""

from __future__ import annotations

import secrets
import socket
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from time import monotonic

from eom_catalog_contracts.reference_query_prepare import (
    MAX_REFERENCE_QUERY_PREPARE_REPLY_BYTES,
    MAX_REFERENCE_QUERY_PREPARE_REQUEST_BYTES,
    ReferenceQueryPrepareReply,
    ReferenceQueryPrepareRequest,
    validate_reference_query_prepare_reply,
)
from eom_identifiers import canonical_json_bytes
from eom_identity_service import AuthenticatedOperatorSession
from eom_identity_service.installed_owner_session_provider import (
    ProtectedInstalledIdentityProviderAdmission,
)
from eom_identity_service.owner_session_transport import OWNER_SESSION_TRANSPORT_SECONDS
from eom_operator_identity.owner_session_capture import (
    MAX_OWNER_SESSION_CAPTURE_REQUEST_BYTES,
    MAX_OWNER_SESSION_CAPTURE_RESPONSE_BYTES,
)
from eom_operator_identity.owner_session_capture_v11 import OwnerSessionCaptureRequestV11

from eom_orchestrator.general_chat_socket import (
    chat_peer_uid,
    decode_chat_frame,
    receive_chat_stream_payload,
    send_chat_stream,
)
from eom_orchestrator.reference_query_prepare_ports import ReferenceQueryPreparationPort


def handle_reference_query_prepare_connection(
    connection: socket.socket,
    *,
    admission: ProtectedInstalledIdentityProviderAdmission,
    api_uid: int,
    application: Callable[[AuthenticatedOperatorSession], ReferenceQueryPreparationPort],
) -> None:
    """Caller owns connection/finite accept capacity; actual installed import precedes SQL.

    No authentication material is returned, persisted, logged or passed to a worker.
    An error after application entry is an unknown outcome, never a retry grant.
    """
    request: ReferenceQueryPrepareRequest | None = None
    deadline = monotonic() + 30.0
    try:
        if type(admission) is not ProtectedInstalledIdentityProviderAdmission:
            raise ValueError("current installed provider required")
        if chat_peer_uid(connection) != api_uid:
            return
        pin = admission.observation.pin
        admission.assert_current(
            source_commit=pin.source_commit,
            wheel_sha256=pin.wheel_sha256,
            configuration_sha256=pin.configuration_sha256,
        )
        raw = receive_chat_stream_payload(
            connection,
            deadline=deadline,
            limit=MAX_REFERENCE_QUERY_PREPARE_REQUEST_BYTES,
        )
        parsed = ReferenceQueryPrepareRequest.model_validate(decode_chat_frame(raw))
        if canonical_json_bytes(parsed.model_dump(mode="json")) != raw:
            raise ValueError("noncanonical request")
        request = parsed
        challenge = OwnerSessionCaptureRequestV11(
            schema_version="operator-owner-session-capture-request/1.1",
            request_id="ownercapture_" + secrets.token_hex(16),
            nonce=secrets.token_hex(32),
            purpose="REFERENCE_QUERY",
        )
        started_at = datetime.now(UTC)
        capture_deadline = min(deadline, monotonic() + OWNER_SESSION_TRANSPORT_SECONDS)
        send_chat_stream(
            connection,
            challenge.model_dump(mode="json"),
            deadline=capture_deadline,
            limit=MAX_OWNER_SESSION_CAPTURE_REQUEST_BYTES,
        )
        response_raw = receive_chat_stream_payload(
            connection,
            deadline=capture_deadline,
            limit=MAX_OWNER_SESSION_CAPTURE_RESPONSE_BYTES,
        )
        capture = admission.capture_catalog_request(
            request=challenge,
            response_raw=response_raw,
            connection=connection,
            started_at=started_at,
            deadline=capture_deadline,
        )
        del response_raw
        # The returned application must bind this genuine capture itself. A peer
        # UID or syntactically valid response is never passed as authority.
        reply = application(capture).prepare(request)
        del capture
        validate_reference_query_prepare_reply(request, reply)
    except Exception:
        # No response/capture/traceback contents leave this adapter. In particular,
        # database admission may already have committed before a disconnect.
        reply = ReferenceQueryPrepareReply(
            schema_version="system-rag-reference-query-prepare-reply/1.0",
            operation="PREPARE_REFERENCE_QUERY",
            operation_id=None if request is None else request.operation_id,
            request_sha256=None if request is None else request.request_sha256,
            status="FAILED",
            workflow_id=None,
            selection=None,
            error_code="REFERENCE_QUERY_PREPARE_REQUEST_INVALID"
            if request is None
            else "REFERENCE_QUERY_PREPARE_UNAVAILABLE",
        )
    # Exactly one final send. A partial/timeout final write must not append a
    # second reply and cannot justify another application invocation.
    with suppress(Exception):
        send_chat_stream(
            connection,
            reply.model_dump(mode="json"),
            deadline=deadline,
            limit=MAX_REFERENCE_QUERY_PREPARE_REPLY_BYTES,
        )
