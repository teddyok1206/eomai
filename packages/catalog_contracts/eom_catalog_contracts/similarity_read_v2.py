"""Mixed completed-query read frames; legacy read1 remains independently exact."""

from __future__ import annotations

from typing import Literal

from eom_identifiers import content_sha256
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import similarity_contract_document
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.similarity_context_v2 import SimilarityContextV2
from eom_catalog_contracts.similarity_read import (
    MAX_SIMILARITY_READ_FRAME_BYTES,
    CompletedSimilarityQuerySelection,
    SimilarityReadErrorCode,
)


class _MixedReadValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, "system-rag-similarity-read-v2", MAX_SIMILARITY_READ_FRAME_BYTES - 1
        )


class SimilarityContextReadRequestV2(_MixedReadValue):
    schema_version: Literal["system-rag-similarity-read-request/2.0"] = (
        "system-rag-similarity-read-request/2.0"
    )
    operation: Literal["READ_SIMILARITY_CONTEXT"] = "READ_SIMILARITY_CONTEXT"
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    selection: CompletedSimilarityQuerySelection


class SimilarityContextReadReplyV2(_MixedReadValue):
    schema_version: Literal["system-rag-similarity-read-reply/2.0"] = (
        "system-rag-similarity-read-reply/2.0"
    )
    operation: Literal["READ_SIMILARITY_CONTEXT"] = "READ_SIMILARITY_CONTEXT"
    status: Literal["SUCCESS", "FAILED"]
    actor_id: str | None = Field(pattern=r"^operator_[0-9a-f]{32}$")
    request_sha256: Sha256 | None
    result: SimilarityContextV2 | None
    error_code: SimilarityReadErrorCode | None


def validate_similarity_read_reply_v2(
    request: SimilarityContextReadRequestV2, reply: SimilarityContextReadReplyV2
) -> None:
    request = SimilarityContextReadRequestV2.model_validate(request)
    reply = SimilarityContextReadReplyV2.model_validate(reply)
    if (
        reply.actor_id != request.actor_id
        or reply.request_sha256 != content_sha256(request.model_dump(mode="json"))
        or (
            reply.result is not None
            and reply.result.request.request_sha256 != request.selection.context_request_sha256
        )
    ):
        raise ValueError("SIMILARITY_READ_V2_REPLY_MISMATCH")
