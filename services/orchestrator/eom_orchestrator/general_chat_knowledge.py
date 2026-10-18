"""Trusted owner read port to Catalog; never installed as a worker capability."""

from __future__ import annotations

import grp
import pwd
from pathlib import Path
from typing import Protocol

from eom_catalog_contracts import CATALOG_APPLICATION_SOCKET_PATH
from eom_catalog_contracts.chat_private_query_scope import (
    CHAT_PRIVATE_SCOPE_REPLY_BYTES,
    CHAT_PRIVATE_SCOPE_REQUEST_BYTES,
    ChatPrivateQueryScopeReply,
    build_chat_private_query_scope_request,
    validate_chat_private_query_scope_reply,
)
from eom_protocol.general_chat_grounding import (
    ChatKnowledgeCatalogReply,
    ChatKnowledgeCatalogRequest,
    ChatKnowledgeSelection,
    ChatKnowledgeSnapshot,
    read_agent,
    read_grounding,
)
from eom_protocol.general_chat_rag_knowledge import (
    ChatRagCatalogReply,
    ChatRagCatalogRequest,
    ChatRagScope,
    read_rag,
    read_rag_catalog_reply,
)
from eom_protocol.general_chat_tools import (
    ChatSearchArguments,
    ChatSearchCatalogReply,
    ChatSearchCatalogRequest,
    ChatToolOutcome,
)
from jsonschema import ValidationError as SchemaError

from eom_orchestrator.general_chat_socket import (
    ChatSocketEndpoint,
    ChatTransportError,
    exchange_chat_frame,
)
from eom_orchestrator.general_chat_state import ChatError


class ChatKnowledgePort(Protocol):
    def search(
        self,
        *,
        actor_id: str,
        arguments: ChatSearchArguments,
        snapshot: ChatKnowledgeSnapshot | None,
    ) -> ChatToolOutcome: ...
    def resolve(
        self, *, actor_id: str, selection: ChatKnowledgeSelection | None, purpose: str
    ) -> ChatKnowledgeCatalogReply: ...


class ChatRagKnowledgePort(Protocol):
    def rag(self, request: ChatRagCatalogRequest) -> ChatRagCatalogReply: ...


class CatalogChatKnowledgeClient:
    def resolve_private_query_scope(
        self, *, actor_id: str, scope: ChatRagScope
    ) -> ChatPrivateQueryScopeReply:
        """One exact semantic→manifest read; never invent a hash/pin or retry transport."""
        request = build_chat_private_query_scope_request(actor_id, scope)
        try:
            value = exchange_chat_frame(
                ChatSocketEndpoint(
                    Path(CATALOG_APPLICATION_SOCKET_PATH),
                    pwd.getpwnam("eom-catalog-manager").pw_uid,
                    grp.getgrnam("eom-api").gr_gid,
                ),
                request.model_dump(mode="json"),
                request_limit=CHAT_PRIVATE_SCOPE_REQUEST_BYTES,
                reply_limit=CHAT_PRIVATE_SCOPE_REPLY_BYTES,
                timeout=20,
            )
            return validate_chat_private_query_scope_reply(request, value)
        except ChatTransportError as error:
            raise ChatError(
                "GENERAL_CHAT_POINTER_INVALID"
                if error.kind == "INVALID"
                else "GENERAL_CHAT_APPLICATION_UNAVAILABLE"
            ) from None
        except (ValueError, SchemaError):
            raise ChatError("GENERAL_CHAT_POINTER_INVALID") from None
        except (KeyError, OSError):
            raise ChatError("GENERAL_CHAT_APPLICATION_UNAVAILABLE") from None

    def rag(self, request: ChatRagCatalogRequest) -> ChatRagCatalogReply:
        document = request.model_dump(mode="json")
        read_rag("CatalogRequest", document, ChatRagCatalogRequest)
        try:
            value = exchange_chat_frame(
                ChatSocketEndpoint(
                    Path(CATALOG_APPLICATION_SOCKET_PATH),
                    pwd.getpwnam("eom-catalog-manager").pw_uid,
                    grp.getgrnam("eom-api").gr_gid,
                ),
                document,
                request_limit=64000,
                reply_limit=64000,
                timeout=20,
            )
        except ChatTransportError as exc:
            raise ChatError(
                "GENERAL_CHAT_POINTER_INVALID"
                if exc.kind == "INVALID"
                else "GENERAL_CHAT_APPLICATION_UNAVAILABLE"
            ) from None
        except Exception:
            raise ChatError("GENERAL_CHAT_APPLICATION_UNAVAILABLE") from None
        try:
            return read_rag_catalog_reply(value, request=request)
        except (ValueError, SchemaError):
            raise ChatError("GENERAL_CHAT_POINTER_INVALID") from None

    def search(
        self,
        *,
        actor_id: str,
        arguments: ChatSearchArguments,
        snapshot: ChatKnowledgeSnapshot | None,
    ) -> ChatToolOutcome:
        request = ChatSearchCatalogRequest(
            actor_id=actor_id, arguments=arguments, snapshot=snapshot
        )
        document = request.model_dump(mode="json")
        read_agent("CatalogRequest", document, ChatSearchCatalogRequest)
        try:
            value = exchange_chat_frame(
                ChatSocketEndpoint(
                    Path(CATALOG_APPLICATION_SOCKET_PATH),
                    pwd.getpwnam("eom-catalog-manager").pw_uid,
                    grp.getgrnam("eom-api").gr_gid,
                ),
                document,
                request_limit=32000,
                reply_limit=64000,
                timeout=20,
            )
            return read_agent("CatalogReply", value, ChatSearchCatalogReply).outcome
        except Exception:
            raise ChatError("GENERAL_CHAT_APPLICATION_UNAVAILABLE") from None

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
