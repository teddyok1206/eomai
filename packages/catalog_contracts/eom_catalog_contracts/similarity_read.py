"""Exact completed QUERY read values, never execution or source permission."""

from __future__ import annotations

from typing import Literal

from eom_identifiers import content_sha256
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import similarity_contract_document
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.similarity_context import SimilarityContext, SimilarityFailureCode

MAX_SIMILARITY_READ_FRAME_BYTES = 1024 * 1024
type SimilarityReadErrorCode = (
    SimilarityFailureCode
    | Literal[
        "SIMILARITY_CONTEXT_REQUEST_INVALID",
        "SIMILARITY_CONTEXT_UNAVAILABLE",
        "SIMILARITY_CONTEXT_BUDGET_EXCEEDED",
    ]
)


class _ReadValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        # Reserve the terminal newline within the actual transport bound.
        return similarity_contract_document(
            value, "system-rag-similarity-read", MAX_SIMILARITY_READ_FRAME_BYTES - 1
        )


class CompletedSimilarityQuerySelection(_ReadValue):
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    workflow_request_sha256: Sha256
    context_request_sha256: Sha256


class SimilarityContextReadRequest(_ReadValue):
    """Only the authenticated API composition supplies actor_id, not a public body."""

    schema_version: Literal["system-rag-similarity-read-request/1.0"] = (
        "system-rag-similarity-read-request/1.0"
    )
    operation: Literal["READ_SIMILARITY_CONTEXT"] = "READ_SIMILARITY_CONTEXT"
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    selection: CompletedSimilarityQuerySelection


class SimilarityContextReadReply(_ReadValue):
    schema_version: Literal["system-rag-similarity-read-reply/1.0"] = (
        "system-rag-similarity-read-reply/1.0"
    )
    operation: Literal["READ_SIMILARITY_CONTEXT"] = "READ_SIMILARITY_CONTEXT"
    status: Literal["SUCCESS", "FAILED"]
    actor_id: str | None = Field(pattern=r"^operator_[0-9a-f]{32}$")
    request_sha256: Sha256 | None
    result: SimilarityContext | None
    error_code: SimilarityReadErrorCode | None


def validate_similarity_read_reply(
    request: SimilarityContextReadRequest, reply: SimilarityContextReadReply
) -> None:
    request = SimilarityContextReadRequest.model_validate(request)
    reply = SimilarityContextReadReply.model_validate(reply)
    if (
        reply.actor_id != request.actor_id
        or reply.request_sha256 != content_sha256(request.model_dump(mode="json"))
        or (
            reply.result is not None
            and reply.result.request.request_sha256 != request.selection.context_request_sha256
        )
    ):
        raise ValueError("similarity read reply differs from exact actor/request/selection")
