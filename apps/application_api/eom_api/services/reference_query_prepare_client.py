"""Authenticated request capture → fixed native owner; no engine/model/NAS or re-login."""

from __future__ import annotations

import grp
import pwd
import socket
from pathlib import Path
from time import monotonic

from eom_catalog_contracts.reference_query_prepare import (
    MAX_REFERENCE_QUERY_PREPARE_REPLY_BYTES,
    MAX_REFERENCE_QUERY_PREPARE_REQUEST_BYTES,
    REFERENCE_QUERY_PREPARE_SOCKET,
    SupportedReferenceQueryPrepareReply,
    SupportedReferenceQueryPrepareRequest,
    parse_supported_reference_query_prepare_reply,
    parse_supported_reference_query_prepare_request,
    validate_supported_reference_query_prepare_reply,
)
from eom_identifiers import canonical_json_bytes
from eom_identity_service.owner_session_transport import (
    OWNER_SESSION_TRANSPORT_SECONDS,
    export_owner_session_capture,
)
from eom_operator_identity import ActorType, PermissionKey
from eom_operator_identity.owner_session_capture import (
    MAX_OWNER_SESSION_CAPTURE_REQUEST_BYTES,
    MAX_OWNER_SESSION_CAPTURE_RESPONSE_BYTES,
)
from eom_operator_identity.owner_session_capture_v11 import (
    OwnerSessionCaptureRequestV11,
    parse_supported_owner_session_capture_request,
)
from eom_orchestrator.general_chat_socket import (
    ChatSocketEndpoint,
    chat_peer_uid,
    decode_chat_frame,
    receive_chat_stream_payload,
    send_chat_stream,
)

from eom_api.request_context import RequestContext


class ReferenceQueryPrepareClientError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class NativeReferenceQueryPrepareClient:
    """One current HTTP context/connection, never a captured Actor or transport retry."""

    def __init__(self, endpoint: ChatSocketEndpoint | None = None) -> None:
        self.endpoint = endpoint

    def prepare(
        self,
        context: RequestContext,
        request: SupportedReferenceQueryPrepareRequest,
    ) -> SupportedReferenceQueryPrepareReply:
        try:
            request = parse_supported_reference_query_prepare_request(request)
            if type(context) is not RequestContext:
                raise ValueError("current request required")
            capture, actor = context.owner_capture(), context.actor()
            if (
                actor.actor_type is not ActorType.OPERATOR
                or PermissionKey.WORKFLOW_START not in actor.permissions
                or capture.operator_id != actor.actor_id
            ):
                raise ValueError("current action unavailable")
            endpoint = self.endpoint or ChatSocketEndpoint(
                Path(REFERENCE_QUERY_PREPARE_SOCKET),
                pwd.getpwnam("eom-workflow-runner").pw_uid,
                grp.getgrnam("eom-api").gr_gid,
                parent_mode=0o2750,
            )
            endpoint.require_socket()
            deadline = monotonic() + 30.0
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(max(0.001, deadline - monotonic()))
                connection.connect(str(endpoint.path))
                if chat_peer_uid(connection) != endpoint.owner_uid:
                    raise ValueError("native owner differs")
                send_chat_stream(
                    connection,
                    request.model_dump(mode="json"),
                    deadline=deadline,
                    limit=MAX_REFERENCE_QUERY_PREPARE_REQUEST_BYTES,
                )
                capture_deadline = min(deadline, monotonic() + OWNER_SESSION_TRANSPORT_SECONDS)
                raw = receive_chat_stream_payload(
                    connection,
                    deadline=capture_deadline,
                    limit=MAX_OWNER_SESSION_CAPTURE_REQUEST_BYTES,
                )
                challenge = parse_supported_owner_session_capture_request(raw)
                if (
                    type(challenge) is not OwnerSessionCaptureRequestV11
                    or challenge.purpose != "REFERENCE_QUERY"
                ):
                    raise ValueError("native capture purpose differs")
                response = export_owner_session_capture(challenge, capture)
                send_chat_stream(
                    connection,
                    response.model_dump(mode="json"),
                    deadline=capture_deadline,
                    limit=MAX_OWNER_SESSION_CAPTURE_RESPONSE_BYTES,
                )
                del response, capture
                raw = receive_chat_stream_payload(
                    connection,
                    deadline=deadline,
                    limit=MAX_REFERENCE_QUERY_PREPARE_REPLY_BYTES,
                )
                reply = parse_supported_reference_query_prepare_reply(decode_chat_frame(raw))
                if canonical_json_bytes(reply.model_dump(mode="json")) != raw:
                    raise ValueError("noncanonical reply")
                validate_supported_reference_query_prepare_reply(request, reply)
                return reply
        except Exception:
            # The owner may already have committed the original QUERY. Do not
            # re-login, retain credentials, reconnect or select another key here.
            raise ReferenceQueryPrepareClientError("REFERENCE_QUERY_PREPARE_UNAVAILABLE") from None
