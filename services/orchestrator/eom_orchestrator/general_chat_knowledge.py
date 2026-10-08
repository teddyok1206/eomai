"""Trusted owner read port to Catalog; never installed as a worker capability."""

from __future__ import annotations

import grp
import pwd
from pathlib import Path
from typing import Protocol

from eom_catalog_contracts import CATALOG_APPLICATION_SOCKET_PATH
from eom_protocol.general_chat_grounding import (
    ChatKnowledgeCatalogReply,
    ChatKnowledgeCatalogRequest,
    ChatKnowledgeSelection,
    read_grounding,
)

from eom_orchestrator.general_chat_socket import ChatSocketEndpoint, exchange_chat_frame
from eom_orchestrator.general_chat_state import ChatError


class ChatKnowledgePort(Protocol):
    def resolve(
        self, *, actor_id: str, selection: ChatKnowledgeSelection | None, purpose: str
    ) -> ChatKnowledgeCatalogReply: ...


class CatalogChatKnowledgeClient:
    def resolve(
        self, *, actor_id: str, selection: ChatKnowledgeSelection | None, purpose: str
    ) -> ChatKnowledgeCatalogReply:
        request = ChatKnowledgeCatalogRequest.model_validate(
            {"actor_id": actor_id, "selection": selection, "purpose": purpose}
        )
        document = request.model_dump(mode="json")
        read_grounding("CatalogRequest", document, ChatKnowledgeCatalogRequest)
        try:
            value = exchange_chat_frame(
                ChatSocketEndpoint(
                    Path(CATALOG_APPLICATION_SOCKET_PATH),
                    pwd.getpwnam("eom-catalog-manager").pw_uid,
                    grp.getgrnam("eom-api").gr_gid,
                ),
                document,
                request_limit=32000,
                reply_limit=512000,
                timeout=20,
            )
            reply = read_grounding("CatalogReply", value, ChatKnowledgeCatalogReply)
        except Exception:
            raise ChatError("GENERAL_CHAT_APPLICATION_UNAVAILABLE") from None
        if reply.status != "SUCCEEDED":
            raise ChatError(
                "GENERAL_CHAT_FORBIDDEN"
                if reply.error_code == "CHAT_KNOWLEDGE_FORBIDDEN"
                else "GENERAL_CHAT_POINTER_INVALID"
            )
        if (
            purpose == "MATERIALIZE"
            and selection is not None
            and (reply.context is None or reply.context.selection != selection)
        ):
            raise ChatError("GENERAL_CHAT_POINTER_INVALID")
        return reply
