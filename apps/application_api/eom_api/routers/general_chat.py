"""Owner-scoped general chat; no caller-supplied operator or native Codex thread ID."""

from __future__ import annotations

from typing import Annotated

from eom_api_contracts.chat_knowledge import ChatKnowledgeRequest, ChatKnowledgeSelection
from eom_api_contracts.general_chat import (
    GeneralChatConversation,
    GeneralChatCreate,
    GeneralChatList,
    GeneralChatSlot,
    GeneralChatSubmission,
)
from eom_operator_identity import PermissionKey
from eom_protocol.general_chat_grounding import (
    ChatGroundingSubmission,
    ChatGroundingViews,
    GroundedChatSubmission,
    read_grounding,
)
from fastapi import APIRouter, Depends, Path, Query, Request

from eom_api.dependencies import Auth, IdempotencyKey, get_services, require_permission

router = APIRouter(prefix="/general-chat", tags=["general-chat"])


@router.post(
    "/conversations/{conversation_id}/grounded-turns",
    operation_id="general_chat_grounded_submit",
    status_code=202,
    response_model=GeneralChatConversation,
    dependencies=[Depends(require_permission(PermissionKey.GENERAL_CHAT_WRITE))],
)
def grounded_submit(
    request: Request,
    conversation_id: Annotated[str, Path(pattern=r"^chat_[0-9a-f]{32}$")],
    body: GroundedChatSubmission,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> GeneralChatConversation:
    read_grounding("Submission", body.model_dump(mode="json"), GroundedChatSubmission)
    return (
        get_services(request)
        .general_chat.require_owner()
        .submit(
            actor_id=authentication.operator.operator_id,
            conversation_id=conversation_id,
            request=body,
            idempotency_key=idempotency_key,
        )
    )


@router.post(
    "/conversations/{conversation_id}/grounding",
    operation_id="general_chat_grounding_read",
    response_model=ChatGroundingViews,
    dependencies=[Depends(require_permission(PermissionKey.GENERAL_CHAT_READ))],
    openapi_extra={"x-eom-read-only": True},
)
def grounding_read(
    request: Request,
    conversation_id: Annotated[str, Path(pattern=r"^chat_[0-9a-f]{32}$")],
    body: ChatGroundingSubmission,
    authentication: Auth,
) -> ChatGroundingViews:
    read_grounding("ViewSubmission", body.model_dump(mode="json"), ChatGroundingSubmission)
    return (
        get_services(request)
        .general_chat.require_owner()
        .grounding(
            actor_id=authentication.operator.operator_id,
            conversation_id=conversation_id,
            turn_ids=body.turn_ids,
        )
    )


@router.post(
    "/knowledge/search",
    operation_id="general_chat_knowledge_search",
    response_model=ChatKnowledgeSelection,
    dependencies=[Depends(require_permission(PermissionKey.GENERAL_CHAT_READ))],
    openapi_extra={
        "x-eom-additional-permissions": [PermissionKey.ITEM_READ.value],
        "x-eom-read-only": True,
    },
)
def knowledge_search(
    request: Request, body: ChatKnowledgeRequest, authentication: Auth
) -> ChatKnowledgeSelection:
    return get_services(request).chat_knowledge.search(body, authentication.permissions)


@router.get(
    "/slot",
    operation_id="general_chat_slot",
    response_model=GeneralChatSlot,
    dependencies=[Depends(require_permission(PermissionKey.GENERAL_CHAT_READ))],
)
def slot(request: Request, authentication: Auth) -> GeneralChatSlot:
    del authentication
    return get_services(request).general_chat.slot()


@router.get(
    "/conversations",
    operation_id="general_chat_list",
    response_model=GeneralChatList,
    dependencies=[Depends(require_permission(PermissionKey.GENERAL_CHAT_READ))],
)
def conversations(
    request: Request,
    authentication: Auth,
    cursor: str | None = Query(default=None, min_length=1, max_length=1024),
) -> GeneralChatList:
    owner = get_services(request).general_chat.require_owner()
    return owner.conversations(actor_id=authentication.operator.operator_id, cursor=cursor)


@router.post(
    "/conversations",
    operation_id="general_chat_create",
    status_code=201,
    response_model=GeneralChatConversation,
    dependencies=[Depends(require_permission(PermissionKey.GENERAL_CHAT_WRITE))],
)
def create(
    request: Request, body: GeneralChatCreate, authentication: Auth, idempotency_key: IdempotencyKey
) -> GeneralChatConversation:
    return (
        get_services(request)
        .general_chat.require_owner()
        .create(
            actor_id=authentication.operator.operator_id,
            request=body,
            idempotency_key=idempotency_key,
        )
    )


@router.get(
    "/conversations/{conversation_id}",
    operation_id="general_chat_get",
    response_model=GeneralChatConversation,
    dependencies=[Depends(require_permission(PermissionKey.GENERAL_CHAT_READ))],
)
def conversation(
    request: Request,
    conversation_id: Annotated[str, Path(pattern=r"^chat_[0-9a-f]{32}$")],
    authentication: Auth,
    cursor: str | None = Query(default=None, min_length=1, max_length=1024),
) -> GeneralChatConversation:
    return (
        get_services(request)
        .general_chat.require_owner()
        .conversation(
            actor_id=authentication.operator.operator_id,
            conversation_id=conversation_id,
            cursor=cursor,
        )
    )


@router.post(
    "/conversations/{conversation_id}/turns",
    operation_id="general_chat_submit",
    status_code=202,
    response_model=GeneralChatConversation,
    dependencies=[Depends(require_permission(PermissionKey.GENERAL_CHAT_WRITE))],
)
def submit(
    request: Request,
    conversation_id: Annotated[str, Path(pattern=r"^chat_[0-9a-f]{32}$")],
    body: GeneralChatSubmission,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> GeneralChatConversation:
    return (
        get_services(request)
        .general_chat.require_owner()
        .submit(
            actor_id=authentication.operator.operator_id,
            conversation_id=conversation_id,
            request=body,
            idempotency_key=idempotency_key,
        )
    )
