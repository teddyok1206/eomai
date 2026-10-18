"""Text-free original private submission pins; validation is never an authority grant."""

from __future__ import annotations

from typing import Literal

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.models import Sha256
from eom_catalog_contracts.private_chat_query_read import ChatPrivateQueryOrigin
from eom_identifiers import content_sha256
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import model_validator

from eom_workflow.private_chat_query_execution import PrivateChatQueryWorkflowRequest
from eom_workflow.schemas import NativeEmbeddingContract, validate_local_embedding_admission_message


class PrivateChatQuerySubmissionContextError(ValueError):
    """Stable private metadata error; never stringify rejected authority/text extras."""


class PrivateChatQuerySubmissionContext(NativeEmbeddingContract):
    schema_version: Literal["private-chat-query-submission-context/1.0"]
    purpose: Literal["PRIVATE_CHAT_QUERY"]
    workflow_request_sha256: Sha256
    origin: ChatPrivateQueryOrigin
    artifact_pointers: tuple[()]
    context_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        document = raw_similarity_contract_value(value)
        validate_local_embedding_admission_message("private-chat-submission", document)
        return document

    @model_validator(mode="after")
    def exact_context(self) -> PrivateChatQuerySubmissionContext:
        if self.context_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"context_sha256"})
        ):
            raise ValueError("private submission context hash differs")
        return self


def parse_private_chat_query_submission_context(value: object) -> PrivateChatQuerySubmissionContext:
    try:
        return PrivateChatQuerySubmissionContext.model_validate(
            raw_similarity_contract_value(value)
        )
    except (ValueError, TypeError, SchemaError):
        raise PrivateChatQuerySubmissionContextError(
            "PRIVATE_CHAT_QUERY_SUBMISSION_CONTEXT_INVALID"
        ) from None


def validate_private_chat_query_submission_context(
    request: PrivateChatQueryWorkflowRequest,
    context: PrivateChatQuerySubmissionContext,
) -> PrivateChatQuerySubmissionContext:
    """Exact supplied parent/actor/basis only; actual source and claim stay with owners."""
    try:
        request = PrivateChatQueryWorkflowRequest.model_validate(
            raw_similarity_contract_value(request)
        )
        context = parse_private_chat_query_submission_context(context)
        if (
            context.workflow_request_sha256 != request.request_sha256
            or context.origin.actor_id != request.operator_audit.operator_id
            or context.origin.basis != request.context_request.query_basis
        ):
            raise ValueError()
        return context
    except (ValueError, TypeError, SchemaError):
        raise PrivateChatQuerySubmissionContextError(
            "PRIVATE_CHAT_QUERY_SUBMISSION_CONTEXT_INVALID"
        ) from None


def build_private_chat_query_submission_context(
    request: PrivateChatQueryWorkflowRequest, origin: ChatPrivateQueryOrigin
) -> PrivateChatQuerySubmissionContext:
    try:
        request = PrivateChatQueryWorkflowRequest.model_validate(
            raw_similarity_contract_value(request)
        )
        origin = ChatPrivateQueryOrigin.model_validate(raw_similarity_contract_value(origin))
        body = {
            "schema_version": "private-chat-query-submission-context/1.0",
            "purpose": "PRIVATE_CHAT_QUERY",
            "workflow_request_sha256": request.request_sha256,
            "origin": origin.model_dump(mode="json"),
            "artifact_pointers": [],
        }
        context = parse_private_chat_query_submission_context(
            body | {"context_sha256": content_sha256(body)}
        )
        return validate_private_chat_query_submission_context(request, context)
    except (ValueError, TypeError, SchemaError):
        raise PrivateChatQuerySubmissionContextError(
            "PRIVATE_CHAT_QUERY_SUBMISSION_CONTEXT_INVALID"
        ) from None


def private_chat_query_turn_identity(
    context: PrivateChatQuerySubmissionContext,
) -> tuple[str, str, str]:
    context = parse_private_chat_query_submission_context(context)
    return (
        context.origin.actor_id,
        context.origin.basis.conversation_id,
        context.origin.basis.turn_id,
    )


def private_chat_query_submission_key(context: PrivateChatQuerySubmissionContext) -> str:
    """One trusted original key per turn; changing claim/pins cannot invent another key."""
    context = parse_private_chat_query_submission_context(context)
    return private_chat_query_origin_key(context.origin)


def private_chat_query_origin_key(origin: ChatPrivateQueryOrigin) -> str:
    """The same key before request construction; parsing does not grant ownership."""
    try:
        origin = ChatPrivateQueryOrigin.model_validate(raw_similarity_contract_value(origin))
    except (ValueError, TypeError, SchemaError):
        raise PrivateChatQuerySubmissionContextError(
            "PRIVATE_CHAT_QUERY_SUBMISSION_CONTEXT_INVALID"
        ) from None
    return f"private-chat-query:{origin.actor_id}:{origin.basis.turn_id}"


def private_chat_query_submission_fingerprint(
    request: PrivateChatQueryWorkflowRequest,
    context: PrivateChatQuerySubmissionContext,
    *,
    definition_sha256: str,
    actor_type: str,
    actor_id: str,
) -> str:
    try:
        request = PrivateChatQueryWorkflowRequest.model_validate(
            raw_similarity_contract_value(request)
        )
    except (ValueError, TypeError, SchemaError):
        raise PrivateChatQuerySubmissionContextError(
            "PRIVATE_CHAT_QUERY_SUBMISSION_CONTEXT_INVALID"
        ) from None
    context = validate_private_chat_query_submission_context(request, context)
    if (
        definition_sha256 != request.workflow_definition_sha256
        or actor_type != "human"
        or actor_id != context.origin.actor_id
    ):
        raise PrivateChatQuerySubmissionContextError(
            "PRIVATE_CHAT_QUERY_SUBMISSION_CONTEXT_INVALID"
        )
    return content_sha256(
        {
            "purpose": "PRIVATE_CHAT_QUERY",
            "workflow_definition_sha256": definition_sha256,
            "workflow_request_sha256": context.workflow_request_sha256,
            "submission_context_sha256": context.context_sha256,
            "actor_type": actor_type,
            "actor_id": actor_id,
        }
    )
