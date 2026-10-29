"""Public recipe2 QUERY values over unchanged numerical encoding/shard identities."""

from typing import Literal, Self

from eom_identifiers import canonical_json_bytes, content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.models import JobId
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import (
    MAX_REFERENCE_QUERY_BYTES,
    ReferenceQuerySpaces,
    ReferenceQueryTextInput,
    ReferenceQueryViewRow,
    raw_similarity_contract_value,
    similarity_contract_document,
)
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingVectorShardManifest,
    embedding_input_set_sha256,
    parse_embedding_shard,
)
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingRecipe

PUBLIC_SOLUTION_QUERY_SCHEMA = "public-solution-query-v2"
PUBLIC_SOLUTION_QUERY_INPUT_REF = "eom://schemas/knowledge/embedding-reference-query-input/2.0"
PUBLIC_SOLUTION_QUERY_RESULT_REF = "eom://schemas/knowledge/embedding-reference-query-result/2.0"


class _PublicQueryValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def raw_values(cls, value: object) -> object:
        return raw_similarity_contract_value(value)


def _require_hash(value: FrozenModel, field: str) -> None:
    document = value.model_dump(mode="json")
    if len(canonical_json_bytes(document)) > MAX_REFERENCE_QUERY_BYTES or getattr(
        value, field
    ) != content_sha256({key: item for key, item in document.items() if key != field}):
        raise ValueError("PUBLIC_SOLUTION_QUERY_HASH_INVALID")


class PublicSolutionQueryInput(_PublicQueryValue):
    schema_version: Literal["embedding-reference-query-input/2.0"] = (
        "embedding-reference-query-input/2.0"
    )
    job_id: JobId
    query_request_id: str = Field(pattern=r"^embeddingquery_[0-9a-f]{32}$")
    context_request_sha256: Sha256
    spaces: ReferenceQuerySpaces
    recipe: PublicSolutionEmbeddingRecipe
    rows: tuple[ReferenceQueryTextInput, ...] = Field(min_length=1, max_length=1)
    batch_size: int = Field(ge=1, le=16, strict=True)
    threads: int = Field(ge=1, le=16, strict=True)
    input_set_sha256: Sha256
    request_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, PUBLIC_SOLUTION_QUERY_SCHEMA, MAX_REFERENCE_QUERY_BYTES
        )

    @model_validator(mode="after")
    def exact_public_input(self) -> Self:
        ReferenceQuerySpaces.model_validate(raw_similarity_contract_value(self.spaces))
        PublicSolutionEmbeddingRecipe.model_validate(raw_similarity_contract_value(self.recipe))
        row = self.rows[0]
        if (
            row.view != "CONCRETE_FACETS"
            or row.encoding.space_sha256 != self.spaces.query.space_sha256
            or len(row.text.encode("utf-8")) > self.recipe.maximum_text_bytes
            or self.input_set_sha256 != embedding_input_set_sha256((row.encoding,))
        ):
            raise ValueError("PUBLIC_SOLUTION_QUERY_INPUT_INVALID")
        _require_hash(self, "request_sha256")
        return self


class PublicSolutionQueryResult(_PublicQueryValue):
    schema_version: Literal["embedding-reference-query-result/2.0"] = (
        "embedding-reference-query-result/2.0"
    )
    job_id: JobId
    query_request_id: str = Field(pattern=r"^embeddingquery_[0-9a-f]{32}$")
    context_request_sha256: Sha256
    request_sha256: Sha256
    spaces: ReferenceQuerySpaces
    recipe: PublicSolutionEmbeddingRecipe
    input_set_sha256: Sha256
    shard: EmbeddingVectorShardManifest
    view_rows: tuple[ReferenceQueryViewRow, ...] = Field(min_length=1, max_length=1)
    result_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, PUBLIC_SOLUTION_QUERY_SCHEMA, MAX_REFERENCE_QUERY_BYTES
        )

    @model_validator(mode="after")
    def exact_public_result(self) -> Self:
        ReferenceQuerySpaces.model_validate(raw_similarity_contract_value(self.spaces))
        PublicSolutionEmbeddingRecipe.model_validate(raw_similarity_contract_value(self.recipe))
        shard = parse_embedding_shard(raw_similarity_contract_value(self.shard))
        row = self.view_rows[0]
        if (
            shard.space != self.spaces.query
            or shard.input_set_sha256 != self.input_set_sha256
            or shard.row_count != 1
            or row.view != "CONCRETE_FACETS"
            or row.row_index != 0
            or row.encoding_sha256 != shard.rows[0].encoding_sha256
        ):
            raise ValueError("PUBLIC_SOLUTION_QUERY_RESULT_INVALID")
        _require_hash(self, "result_sha256")
        return self


class PublicSolutionQueryExecutionPointer(_PublicQueryValue):
    job_id: JobId
    query_request_id: str = Field(pattern=r"^embeddingquery_[0-9a-f]{32}$")
    request_sha256: Sha256
    input_set_sha256: Sha256
    result_member: ArtifactMemberPointer
    result_sha256: Sha256

    @model_validator(mode="after")
    def exact_result_member(self) -> Self:
        if (
            self.result_member.member_path != "result.json"
            or self.result_member.schema_ref != PUBLIC_SOLUTION_QUERY_RESULT_REF
            or self.result_member.media_type != "application/json"
        ):
            raise ValueError("PUBLIC_SOLUTION_QUERY_RESULT_POINTER_INVALID")
        return self


def validate_public_solution_query_result(
    request: PublicSolutionQueryInput, result: PublicSolutionQueryResult
) -> None:
    """Supplied-value closure only. IAM, runtime and committed bytes stay with owners."""
    request = PublicSolutionQueryInput.model_validate(raw_similarity_contract_value(request))
    result = PublicSolutionQueryResult.model_validate(raw_similarity_contract_value(result))
    if (
        any(
            getattr(request, key) != getattr(result, key)
            for key in (
                "job_id",
                "query_request_id",
                "context_request_sha256",
                "request_sha256",
                "spaces",
                "recipe",
                "input_set_sha256",
            )
        )
        or result.shard.rows != tuple(row.encoding for row in request.rows)
        or tuple(row.view for row in result.view_rows) != tuple(row.view for row in request.rows)
    ):
        raise ValueError("PUBLIC_SOLUTION_QUERY_CONTEXT_INVALID")
