"""Pinned semantic Graph scope to an exact raw manifest pointer; never source authority."""

from __future__ import annotations

from typing import ClassVar, Literal

from eom_identifiers import content_sha256
from eom_protocol.general_chat_rag_knowledge import ChatRagScope
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import (
    raw_similarity_contract_value,
    similarity_contract_document,
)
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.models import FrozenModel, Sha256

CHAT_PRIVATE_SCOPE_REQUEST_BYTES = 4096
CHAT_PRIVATE_SCOPE_REPLY_BYTES = 16 * 1024
type ChatPrivateQueryScopeErrorCode = Literal[
    "CHAT_KNOWLEDGE_FORBIDDEN", "CHAT_KNOWLEDGE_POINTER_INVALID", "CHAT_KNOWLEDGE_UNAVAILABLE"
]


class ChatPrivateQueryScopeContractError(ValueError):
    def __init__(self) -> None:
        super().__init__("CHAT_PRIVATE_QUERY_SCOPE_INVALID")


class _ScopeValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)
    maximum_bytes: ClassVar[int] = CHAT_PRIVATE_SCOPE_REPLY_BYTES - 1

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(value, "chat-private-query-scope", cls.maximum_bytes)


class ChatPrivateQueryScopeRequest(_ScopeValue):
    maximum_bytes = CHAT_PRIVATE_SCOPE_REQUEST_BYTES - 1
    schema_version: Literal["chat-private-query-scope-request/1.0"]
    operation: Literal["RESOLVE_CHAT_PRIVATE_QUERY_SCOPE"]
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    scope: ChatRagScope
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_request(self) -> ChatPrivateQueryScopeRequest:
        if self.request_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"request_sha256"})
        ):
            raise ChatPrivateQueryScopeContractError()
        return self


class ChatPrivateQueryScopeReply(_ScopeValue):
    schema_version: Literal["chat-private-query-scope-reply/1.0"]
    request_sha256: Sha256
    status: Literal["SUCCEEDED", "FAILED"]
    scope: ChatRagScope | None
    graph_snapshot: KnowledgeGraphSnapshotPointer | None
    error_code: ChatPrivateQueryScopeErrorCode | None

    @model_validator(mode="after")
    def separate_graph_identities(self) -> ChatPrivateQueryScopeReply:
        if self.graph_snapshot is not None:
            pointer = self.graph_snapshot
            member = pointer.manifest_artifact
            if (
                self.scope is None
                or pointer.graph_snapshot_revision_id
                != self.scope.snapshot.graph_snapshot_revision_id
                or pointer.manifest_sha256 != member.sha256
                or member.member_path != "projections/manifest.json"
                or member.media_type != "application/json"
                or member.schema_ref
                not in {
                    f"eom://schemas/knowledge/knowledge-graph-snapshot-manifest/{version}.0"
                    for version in range(2, 10)
                }
            ):
                raise ChatPrivateQueryScopeContractError()
            # scope.snapshot.sha256 is semantic; it is not pointer.manifest_sha256.
        return self


def parse_chat_private_query_scope_request(value: object) -> ChatPrivateQueryScopeRequest:
    try:
        return ChatPrivateQueryScopeRequest.model_validate(raw_similarity_contract_value(value))
    except (ValueError, TypeError, SchemaError):
        raise ChatPrivateQueryScopeContractError() from None


def build_chat_private_query_scope_request(
    actor_id: str, scope: ChatRagScope
) -> ChatPrivateQueryScopeRequest:
    body = {
        "schema_version": "chat-private-query-scope-request/1.0",
        "operation": "RESOLVE_CHAT_PRIVATE_QUERY_SCOPE",
        "actor_id": actor_id,
        "scope": raw_similarity_contract_value(scope),
    }
    return parse_chat_private_query_scope_request(body | {"request_sha256": content_sha256(body)})


def validate_chat_private_query_scope_reply(
    request: ChatPrivateQueryScopeRequest, value: object
) -> ChatPrivateQueryScopeReply:
    try:
        request = parse_chat_private_query_scope_request(request)
        reply = ChatPrivateQueryScopeReply.model_validate(raw_similarity_contract_value(value))
        if reply.request_sha256 != request.request_sha256 or (
            reply.status == "SUCCEEDED" and reply.scope != request.scope
        ):
            raise ChatPrivateQueryScopeContractError()
        return reply
    except (ValueError, TypeError, SchemaError):
        raise ChatPrivateQueryScopeContractError() from None


def failed_chat_private_query_scope_reply(
    request: ChatPrivateQueryScopeRequest, code: ChatPrivateQueryScopeErrorCode
) -> ChatPrivateQueryScopeReply:
    return validate_chat_private_query_scope_reply(
        request,
        dict(
            schema_version="chat-private-query-scope-reply/1.0",
            request_sha256=request.request_sha256,
            status="FAILED",
            scope=None,
            graph_snapshot=None,
            error_code=code,
        ),
    )
