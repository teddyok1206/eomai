"""Distinct private-question numeric messages; parsing never admits an execution."""

from __future__ import annotations

from typing import Literal

from eom_identifiers import content_sha256
from eom_protocol.models import JobId
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import (
    ReferenceQuerySpaces,
    ReferenceQueryTextInput,
    raw_similarity_contract_value,
    similarity_contract_document,
)
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingVectorShardManifest,
    embedding_input_set_sha256,
    parse_embedding_shard,
)
from eom_catalog_contracts.inference_transfer_experiment import ExperimentViewRecipe
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.private_chat_query_basis import (
    PrivateChatQueryBasis,
    private_chat_query_text_sha256,
)

MAX_PRIVATE_CHAT_QUERY_BYTES = 128 * 1024
PRIVATE_CHAT_QUERY_RESULT_REF = "eom://schemas/knowledge/embedding-private-chat-query-result/1.0"


class _PrivateQueryValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, "embedding-private-chat-query", MAX_PRIVATE_CHAT_QUERY_BYTES
        )


class EmbeddingPrivateChatQueryInput(_PrivateQueryValue):
    schema_version: Literal["embedding-private-chat-query-input/1.0"]
    job_id: JobId
    query_request_id: str = Field(pattern=r"^embeddingquery_[0-9a-f]{32}$")
    context_request_sha256: Sha256
    basis: PrivateChatQueryBasis
    spaces: ReferenceQuerySpaces
    document_recipe: ExperimentViewRecipe
    row: ReferenceQueryTextInput
    batch_size: int = Field(ge=1, le=16, strict=True)
    threads: int = Field(ge=1, le=16, strict=True)
    input_set_sha256: Sha256
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_question_row(self) -> EmbeddingPrivateChatQueryInput:
        if (
            self.row.view != "CONTENT_ONLY"
            or self.row.encoding.space_sha256 != self.spaces.query.space_sha256
            or self.basis.query_text_sha256 != private_chat_query_text_sha256(self.row.text)
            or self.input_set_sha256 != embedding_input_set_sha256((self.row.encoding,))
            or self.request_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"request_sha256"}))
        ):
            raise ValueError("private Chat numeric input identity/hash differs")
        return self


class EmbeddingPrivateChatQueryResult(_PrivateQueryValue):
    schema_version: Literal["embedding-private-chat-query-result/1.0"]
    job_id: JobId
    query_request_id: str = Field(pattern=r"^embeddingquery_[0-9a-f]{32}$")
    context_request_sha256: Sha256
    basis_sha256: Sha256
    request_sha256: Sha256
    spaces: ReferenceQuerySpaces
    document_recipe: ExperimentViewRecipe
    input_set_sha256: Sha256
    shard: EmbeddingVectorShardManifest
    result_sha256: Sha256

    @model_validator(mode="after")
    def exact_query_shard(self) -> EmbeddingPrivateChatQueryResult:
        shard = parse_embedding_shard(raw_similarity_contract_value(self.shard))
        if (
            shard.space != self.spaces.query
            or shard.row_count != 1
            or self.input_set_sha256 != shard.input_set_sha256
            or self.result_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        ):
            raise ValueError("private Chat numeric result identity/hash differs")
        return self


def validate_private_chat_query_result(
    request: EmbeddingPrivateChatQueryInput, result: EmbeddingPrivateChatQueryResult
) -> None:
    """Check exact typed result association, never source/session/installed admission."""
    request = EmbeddingPrivateChatQueryInput.model_validate(raw_similarity_contract_value(request))
    result = EmbeddingPrivateChatQueryResult.model_validate(raw_similarity_contract_value(result))
    if any(
        getattr(result, field) != getattr(request, field)
        for field in (
            "job_id",
            "query_request_id",
            "context_request_sha256",
            "request_sha256",
            "spaces",
            "document_recipe",
            "input_set_sha256",
        )
    ) or (
        result.basis_sha256 != request.basis.basis_sha256
        or result.shard.rows != (request.row.encoding,)
    ):
        raise ValueError("private Chat result differs from its exact request")
