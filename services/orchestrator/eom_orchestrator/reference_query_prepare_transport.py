"""One fixed API peer exchange; no session cache, SQL, native execution or listener default."""

from __future__ import annotations

import logging
import re
import secrets
import socket
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from time import monotonic

from eom_catalog_contracts.reference_query_prepare import (
    MAX_ROUTED_QUERY_PREPARE_REPLY_BYTES,
    MAX_ROUTED_QUERY_PREPARE_REQUEST_BYTES,
    REFERENCE_QUERY_PREPARE_RESPONSE_SECONDS,
    ReferenceQueryPrepareReply,
    ReferenceQueryPrepareReplyV2,
    ReferenceQueryPrepareRequestV2,
    ReferenceQueryPrepareRequestV3,
    ReferenceQueryPrepareRequestV4,
    SupportedReferenceQueryPrepareRequest,
    parse_supported_reference_query_prepare_request,
    routed_reference_query_error_reply,
    validate_supported_reference_query_prepare_reply,
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

_LOGGER = logging.getLogger(__name__)


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
    request: SupportedReferenceQueryPrepareRequest | None = None
    started = monotonic()
    deadline = started + REFERENCE_QUERY_PREPARE_RESPONSE_SECONDS
    stage = "ADMIT_PROVIDER"
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
        stage = "READ_REQUEST"
        raw = receive_chat_stream_payload(
            connection,
            deadline=deadline,
            limit=MAX_ROUTED_QUERY_PREPARE_REQUEST_BYTES,
        )
        parsed = parse_supported_reference_query_prepare_request(decode_chat_frame(raw))
        if canonical_json_bytes(parsed.model_dump(mode="json")) != raw:
            raise ValueError("noncanonical request")
        request = parsed
        stage = "CAPTURE_CURRENT_OPERATOR"
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
        stage = "PREPARE_APPLICATION"
        reply = application(capture).prepare(request)
        del capture
        stage = "VALIDATE_REPLY"
        validate_supported_reference_query_prepare_reply(request, reply)
    except Exception as error:
        # Never log exception prose, traceback, request, capture or credentials.
        # A closed metadata record distinguishes admission failure from slow IO.
        with suppress(Exception):
            code = getattr(error, "code", None)
            if code is None and isinstance(error, ValueError) and len(error.args) == 1:
                code = error.args[0]
            safe_code = (
                code
                if isinstance(code, str)
                and re.fullmatch(
                    r"(?:REFERENCE|EMBEDDING|INFERENCE|PUBLIC|OWNER|SOURCE|INDEX|AUTHORITY)_[A-Z0-9_]{1,85}",
                    code,
                )
                else "REFERENCE_QUERY_PREPARE_UNAVAILABLE"
            )
            _LOGGER.warning(
                "REFERENCE_QUERY_PREPARATION_FAILED stage=%s code=%s elapsed_ms=%d",
                stage,
                safe_code,
                max(0, int((monotonic() - started) * 1000)),
            )
        # No response/capture/traceback contents leave this adapter. In particular,
        # database admission may already have committed before a disconnect.
        if isinstance(request, ReferenceQueryPrepareRequestV3 | ReferenceQueryPrepareRequestV4):
            reply = routed_reference_query_error_reply(request)
        else:
            reply = _legacy_failure_reply(request)
    # Exactly one final send. A partial/timeout final write must not append a
    # second reply and cannot justify another application invocation.
    with suppress(Exception):
        send_chat_stream(
            connection,
            reply.model_dump(mode="json"),
            deadline=deadline,
            limit=MAX_ROUTED_QUERY_PREPARE_REPLY_BYTES,
        )


def _legacy_failure_reply(
    request: SupportedReferenceQueryPrepareRequest | None,
) -> ReferenceQueryPrepareReply | ReferenceQueryPrepareReplyV2:
    family = "2.0" if isinstance(request, ReferenceQueryPrepareRequestV2) else "1.0"
    reply_type = ReferenceQueryPrepareReplyV2 if family == "2.0" else ReferenceQueryPrepareReply
    return reply_type.model_validate(
        dict(
            schema_version=f"system-rag-reference-query-prepare-reply/{family}",
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
    )
