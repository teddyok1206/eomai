"""Actual-actor authorization of pinned conversation evidence; no worker authority."""

from __future__ import annotations

from eom_protocol.general_chat_grounding import ChatKnowledgeSnapshot
from eom_protocol.general_chat_rag_knowledge import (
    ChatRagAuthorizeCommand,
    ChatRagCatalogReply,
    ChatRagCatalogRequest,
    ChatRagContext,
    ChatRagPolicy,
    ChatRagPrepareCommand,
    ChatRagScope,
    read_rag_catalog_reply,
)
from jsonschema import ValidationError as SchemaError

from eom_orchestrator.general_chat_knowledge import ChatRagKnowledgePort
from eom_orchestrator.general_chat_state import ChatError


def _resolve(port: ChatRagKnowledgePort, request: ChatRagCatalogRequest) -> ChatRagCatalogReply:
    try:
        return read_rag_catalog_reply(port.rag(request).model_dump(mode="json"), request=request)
    except (ValueError, SchemaError):
        raise ChatError("GENERAL_CHAT_POINTER_INVALID") from None


def authorize_rag_context(
    port: ChatRagKnowledgePort | None, *, actor_id: str | None, context: ChatRagContext
) -> None:
    if port is None or actor_id is None:
        raise ChatError("GENERAL_CHAT_FORBIDDEN")
    reply = _resolve(
        port,
        ChatRagCatalogRequest(actor_id=actor_id, command=ChatRagAuthorizeCommand(context=context)),
    )
    if reply.status != "SUCCEEDED":
        raise ChatError(
            "GENERAL_CHAT_FORBIDDEN"
            if reply.error_code == "CHAT_KNOWLEDGE_FORBIDDEN"
            else "GENERAL_CHAT_APPLICATION_UNAVAILABLE"
            if reply.error_code == "CHAT_KNOWLEDGE_UNAVAILABLE"
            else "GENERAL_CHAT_POINTER_INVALID"
        )


def prepare_rag_scope(
    port: ChatRagKnowledgePort,
    *,
    actor_id: str,
    policy: ChatRagPolicy,
    snapshot: ChatKnowledgeSnapshot | None,
) -> ChatRagScope | None:
    try:
        reply = _resolve(
            port,
            ChatRagCatalogRequest(
                actor_id=actor_id,
                command=ChatRagPrepareCommand(snapshot=snapshot, policy=policy),
            ),
        )
    except ChatError as exc:
        if exc.code in {"GENERAL_CHAT_FORBIDDEN", "GENERAL_CHAT_APPLICATION_UNAVAILABLE"}:
            return None
        raise
    if reply.status == "SUCCEEDED":
        return reply.scope
    # No source is exposed on an initially unavailable RAG boundary. An invalid
    # explicit pin is not permission to retarget it or try a newer Graph/policy.
    if reply.error_code in {"CHAT_KNOWLEDGE_FORBIDDEN", "CHAT_KNOWLEDGE_UNAVAILABLE"}:
        return None
    raise ChatError("GENERAL_CHAT_POINTER_INVALID")
