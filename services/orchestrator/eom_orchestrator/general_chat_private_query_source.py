"""Chat-owned source read use case; no model work, SQL/NAS bypass or public retrieval grant."""

from __future__ import annotations

from typing import Protocol

from eom_catalog_contracts.private_chat_query_read import (
    ChatPrivateQueryReadReply,
    ChatPrivateQueryReadRequest,
    MaterializeLiveChatQuery,
    PrivateChatQueryReadErrorCode,
    parse_private_chat_query_read_reply,
    parse_private_chat_query_read_request,
)
from eom_identifiers import content_sha256
from pydantic import TypeAdapter

from eom_orchestrator.general_chat_execution import GeneralChatExecutionService
from eom_orchestrator.general_chat_state import ChatError


class ChatPrivateQueryReadPort(Protocol):
    def read(self, request: ChatPrivateQueryReadRequest) -> ChatPrivateQueryReadReply: ...


def failed_private_chat_query_read(
    request: ChatPrivateQueryReadRequest, code: str
) -> ChatPrivateQueryReadReply:
    request = parse_private_chat_query_read_request(request)
    try:
        error: PrivateChatQueryReadErrorCode = TypeAdapter(
            PrivateChatQueryReadErrorCode
        ).validate_python(code, strict=True)
    except ValueError:
        error = "GENERAL_CHAT_APPLICATION_UNAVAILABLE"
    return ChatPrivateQueryReadReply(
        schema_version="general-chat-private-query-read-reply/1.0",
        request_id=request.request_id,
        request_sha256=content_sha256(request),
        action=request.command.action,
        status="FAILED",
        value=None,
        error_code=error,
    )


class GeneralChatPrivateQuerySource:
    def __init__(self, execution: GeneralChatExecutionService) -> None:
        self.execution = execution

    def read(self, request: ChatPrivateQueryReadRequest) -> ChatPrivateQueryReadReply:
        request = parse_private_chat_query_read_request(request)
        try:
            command = request.command
            value = (
                self.execution.materialize_live_private_query(command.ticket)
                if isinstance(command, MaterializeLiveChatQuery)
                else self.execution.authorize_live_private_query(command.origin)
            )
            reply = ChatPrivateQueryReadReply(
                schema_version="general-chat-private-query-read-reply/1.0",
                request_id=request.request_id,
                request_sha256=content_sha256(request),
                action=command.action,
                status="SUCCEEDED",
                value=value,
                error_code=None,
            )
            return parse_private_chat_query_read_reply(reply, request=request)
        except ChatError as error:
            return failed_private_chat_query_read(request, error.code)
        except Exception:
            return failed_private_chat_query_read(request, "GENERAL_CHAT_APPLICATION_UNAVAILABLE")
