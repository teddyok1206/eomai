"""Fixed Chat-owner peer, bounded one-shot exchange; never a native worker tool."""

from __future__ import annotations

import socket
from contextlib import suppress
from time import monotonic
from typing import Protocol

from eom_catalog_contracts.private_chat_query_prepare import (
    PRIVATE_CHAT_PREPARE_REPLY_BYTES,
    PRIVATE_CHAT_PREPARE_REQUEST_BYTES,
    PrivateChatQueryPrepareReply,
    PrivateChatQueryPrepareRequest,
    parse_private_chat_query_prepare_request,
    validate_private_chat_query_prepare_reply,
)
from eom_identifiers import canonical_json_bytes

from eom_orchestrator.general_chat_socket import (
    chat_peer_uid,
    decode_chat_frame,
    receive_chat_frame,
    send_chat_frame,
)


class PrivateChatQueryPreparationPort(Protocol):
    def execute(self, request: PrivateChatQueryPrepareRequest) -> PrivateChatQueryPrepareReply: ...


def handle_private_chat_query_prepare_connection(
    connection: socket.socket,
    *,
    chat_uid: int,
    application: PrivateChatQueryPreparationPort,
) -> None:
    """The host owns finite accept capacity; this function never retries a request."""
    request = None
    deadline = monotonic() + 20.0
    try:
        if type(chat_uid) is not int or chat_uid <= 0 or chat_peer_uid(connection) != chat_uid:
            return
        raw = receive_chat_frame(
            connection, deadline=deadline, limit=PRIVATE_CHAT_PREPARE_REQUEST_BYTES
        )
        parsed = parse_private_chat_query_prepare_request(decode_chat_frame(raw))
        if canonical_json_bytes(parsed.model_dump(mode="json")) != raw:
            return
        request = parsed
        reply = validate_private_chat_query_prepare_reply(request, application.execute(request))
    except Exception:
        # The application may already have committed. Never turn unknown outcome
        # into NOT_PREPARED or send an additional request with another identity.
        if request is None:
            return
        reply = PrivateChatQueryPrepareReply(
            schema_version="system-rag-private-chat-query-prepare-reply/1.0",
            action=request.action,
            request_id=request.request_id,
            request_sha256=request.request_sha256,
            status="FAILED",
            workflow_id=None,
            context=None,
            error_code="PRIVATE_CHAT_QUERY_UNAVAILABLE",
        )
    with suppress(Exception):
        send_chat_frame(
            connection,
            canonical_json_bytes(reply.model_dump(mode="json")),
            deadline=deadline,
            limit=PRIVATE_CHAT_PREPARE_REPLY_BYTES,
        )
