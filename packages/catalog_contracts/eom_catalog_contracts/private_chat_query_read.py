"""Closed live Chat source reads; metadata is not source/runtime execution authority."""

from __future__ import annotations

from typing import Annotated, Literal

from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.general_chat_rag_turn import RAG_INPUT_SCHEMA
from eom_protocol.general_chat_worker_messages import ChatWorkerTicket
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import (
    raw_similarity_contract_value,
    similarity_contract_document,
)
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.private_chat_query_basis import (
    PrivateChatQueryBasis,
    private_chat_query_text_sha256,
)

PRIVATE_CHAT_SOURCE_REQUEST_BYTES = 32 * 1024
PRIVATE_CHAT_SOURCE_REPLY_BYTES = 128 * 1024
type PrivateChatQueryReadAction = Literal[
    "MATERIALIZE_LIVE_CHAT_QUERY", "AUTHORIZE_LIVE_CHAT_QUERY"
]
type PrivateChatQueryReadErrorCode = Literal[
    "GENERAL_CHAT_FORBIDDEN",
    "GENERAL_CHAT_NOT_FOUND",
    "GENERAL_CHAT_POINTER_INVALID",
    "GENERAL_CHAT_CLAIM_MISMATCH",
    "GENERAL_CHAT_RECONCILIATION_REQUIRED",
    "GENERAL_CHAT_PROTOCOL_INVALID",
    "GENERAL_CHAT_APPLICATION_UNAVAILABLE",
]


class _SourceReadValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, "general-chat-private-query-read", PRIVATE_CHAT_SOURCE_REPLY_BYTES
        )


class ChatPrivateQueryOrigin(_SourceReadValue):
    schema_version: Literal["general-chat-private-query-origin/1.0"]
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    runtime_id: str = Field(pattern=r"^chatrt_[0-9a-f]{32}$")
    ticket: ChatWorkerTicket
    request_member: ArtifactMemberPointer
    dispatch_member: ArtifactMemberPointer
    basis: PrivateChatQueryBasis
    origin_sha256: Sha256

    @model_validator(mode="after")
    def exact_origin(self) -> ChatPrivateQueryOrigin:
        if (
            (self.basis.conversation_id, self.basis.turn_id)
            != (self.ticket.conversation_id, self.ticket.turn_id)
            or self.request_member.schema_ref != RAG_INPUT_SCHEMA
            or self.request_member.sha256 != self.ticket.request_sha256
            or self.origin_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"origin_sha256"}))
        ):
            raise ValueError("private Chat source origin differs")
        return self


class LiveChatQueryProjection(_SourceReadValue):
    schema_version: Literal["general-chat-private-query-projection/1.0"]
    origin: ChatPrivateQueryOrigin
    text: str = Field(min_length=1, max_length=16000)

    @model_validator(mode="after")
    def exact_text(self) -> LiveChatQueryProjection:
        if private_chat_query_text_sha256(self.text) != self.origin.basis.query_text_sha256:
            raise ValueError("private Chat source projection differs")
        return self


class MaterializeLiveChatQuery(_SourceReadValue):
    action: Literal["MATERIALIZE_LIVE_CHAT_QUERY"]
    ticket: ChatWorkerTicket


class AuthorizeLiveChatQuery(_SourceReadValue):
    action: Literal["AUTHORIZE_LIVE_CHAT_QUERY"]
    origin: ChatPrivateQueryOrigin


class ChatPrivateQueryReadRequest(_SourceReadValue):
    schema_version: Literal["general-chat-private-query-read-request/1.0"]
    request_id: str = Field(pattern=r"^chatqueryrpc_[0-9a-f]{32}$")
    command: Annotated[
        MaterializeLiveChatQuery | AuthorizeLiveChatQuery, Field(discriminator="action")
    ]

    @model_validator(mode="before")
    @classmethod
    def bounded_request(cls, value: object) -> object:
        return similarity_contract_document(
            value, "general-chat-private-query-read", PRIVATE_CHAT_SOURCE_REQUEST_BYTES
        )


class ChatPrivateQueryReadReply(_SourceReadValue):
    schema_version: Literal["general-chat-private-query-read-reply/1.0"]
    request_id: str = Field(pattern=r"^chatqueryrpc_[0-9a-f]{32}$")
    request_sha256: Sha256
    action: PrivateChatQueryReadAction
    status: Literal["SUCCEEDED", "FAILED"]
    value: LiveChatQueryProjection | ChatPrivateQueryOrigin | None
    error_code: PrivateChatQueryReadErrorCode | None


class PrivateChatQueryReadProtocolError(ValueError):
    """Never stringify schema/Pydantic errors that could include a private question."""


def parse_private_chat_query_read_request(value: object) -> ChatPrivateQueryReadRequest:
    try:
        return ChatPrivateQueryReadRequest.model_validate(raw_similarity_contract_value(value))
    except (ValueError, TypeError, SchemaError):
        raise PrivateChatQueryReadProtocolError("PRIVATE_CHAT_QUERY_SOURCE_INVALID") from None


def parse_private_chat_query_read_reply(
    value: object, *, request: ChatPrivateQueryReadRequest
) -> ChatPrivateQueryReadReply:
    try:
        request = parse_private_chat_query_read_request(request)
        reply = ChatPrivateQueryReadReply.model_validate(raw_similarity_contract_value(value))
        if (reply.request_id, reply.request_sha256, reply.action) != (
            request.request_id,
            content_sha256(request),
            request.command.action,
        ):
            raise ValueError("source read reply differs")
        if reply.status == "SUCCEEDED":
            origin = (
                reply.value.origin
                if isinstance(reply.value, LiveChatQueryProjection)
                else reply.value
            )
            assert origin is not None
            if isinstance(request.command, MaterializeLiveChatQuery):
                if origin.ticket != request.command.ticket:
                    raise ValueError("source read ticket differs")
            elif origin != request.command.origin:
                raise ValueError("source read origin differs")
        return reply
    except (ValueError, TypeError, SchemaError):
        raise PrivateChatQueryReadProtocolError("PRIVATE_CHAT_QUERY_SOURCE_INVALID") from None
