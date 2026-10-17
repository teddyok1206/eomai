"""One-shot fixed-peer source reads for the QUERY controller; never a worker tool."""

from __future__ import annotations

import grp
import pwd
from pathlib import Path
from uuid import uuid4

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.private_chat_query_read import (
    PRIVATE_CHAT_SOURCE_REPLY_BYTES,
    PRIVATE_CHAT_SOURCE_REQUEST_BYTES,
    ChatPrivateQueryOrigin,
    ChatPrivateQueryReadReply,
    LiveChatQueryProjection,
    parse_private_chat_query_read_reply,
    parse_private_chat_query_read_request,
)
from eom_protocol.general_chat_worker_messages import ChatWorkerTicket

from eom_orchestrator.general_chat_socket import (
    ChatSocketEndpoint,
    ChatTransportError,
    exchange_chat_frame,
)
from eom_orchestrator.general_chat_state import ChatError

PRIVATE_CHAT_QUERY_SOURCE_SOCKET = Path("/run/eom-general-chat-query-read/source.sock")


class GeneralChatPrivateQueryClient:
    def __init__(self, endpoint: ChatSocketEndpoint | None = None) -> None:
        self.endpoint = endpoint

    def _read(self, command: dict[str, object]) -> ChatPrivateQueryReadReply:
        try:
            request = parse_private_chat_query_read_request(
                {
                    "schema_version": "general-chat-private-query-read-request/1.0",
                    "request_id": "chatqueryrpc_" + uuid4().hex,
                    "command": command,
                }
            )
            endpoint = self.endpoint or ChatSocketEndpoint(
                PRIVATE_CHAT_QUERY_SOURCE_SOCKET,
                pwd.getpwnam("eom-general-chat").pw_uid,
                grp.getgrnam("eom").gr_gid,
            )
            value = exchange_chat_frame(
                endpoint,
                request.model_dump(mode="json"),
                request_limit=PRIVATE_CHAT_SOURCE_REQUEST_BYTES,
                reply_limit=PRIVATE_CHAT_SOURCE_REPLY_BYTES,
                timeout=20,
            )
            reply = parse_private_chat_query_read_reply(value, request=request)
        except ChatTransportError as error:
            raise ChatError(
                "GENERAL_CHAT_POINTER_INVALID"
                if error.kind == "INVALID"
                else "GENERAL_CHAT_APPLICATION_UNAVAILABLE"
            ) from None
        except (KeyError, OSError):
            raise ChatError("GENERAL_CHAT_APPLICATION_UNAVAILABLE") from None
        except Exception:
            raise ChatError("GENERAL_CHAT_POINTER_INVALID") from None
        if reply.status != "SUCCEEDED":
            assert reply.error_code is not None
            raise ChatError(reply.error_code)
        return reply

    def materialize(self, ticket: ChatWorkerTicket) -> LiveChatQueryProjection:
        reply = self._read(
            {
                "action": "MATERIALIZE_LIVE_CHAT_QUERY",
                "ticket": raw_similarity_contract_value(ticket),
            }
        )
        if not isinstance(reply.value, LiveChatQueryProjection):
            raise ChatError("GENERAL_CHAT_POINTER_INVALID")
        return reply.value

    def authorize(self, origin: ChatPrivateQueryOrigin) -> ChatPrivateQueryOrigin:
        reply = self._read(
            {
                "action": "AUTHORIZE_LIVE_CHAT_QUERY",
                "origin": raw_similarity_contract_value(origin),
            }
        )
        if not isinstance(reply.value, ChatPrivateQueryOrigin):
            raise ChatError("GENERAL_CHAT_POINTER_INVALID")
        return reply.value
