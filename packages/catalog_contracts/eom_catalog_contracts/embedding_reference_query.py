"""Approved-reference QUERY values only; validation is never compute or source admission."""

from __future__ import annotations

from typing import Any, Literal

from eom_identifiers import canonical_json_bytes, content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.models import JobId
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_contract_values import (
    raw_similarity_contract_value as raw_similarity_contract_value,
)
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingSpace,
    EmbeddingTextInput,
    EmbeddingVectorShardManifest,
    embedding_input_set_sha256,
    parse_embedding_shard,
)
from eom_catalog_contracts.inference_transfer_experiment import ExperimentView, ExperimentViewRecipe
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.validation import validate_contract

REFERENCE_QUERY_SCHEMA = "embedding-reference-query"
REFERENCE_QUERY_INPUT_REF = "eom://schemas/knowledge/embedding-reference-query-input/1.0"
REFERENCE_QUERY_RESULT_REF = "eom://schemas/knowledge/embedding-reference-query-result/1.0"
MAX_REFERENCE_QUERY_BYTES = 1024 * 1024


def similarity_contract_document(value: object, schema: str, maximum: int) -> dict[str, Any]:
    document = raw_similarity_contract_value(value)
    if not isinstance(document, dict):
        raise ValueError("contract must be an object")
    try:
        encoded = canonical_json_bytes(document)
    except TypeError as exc:
        raise ValueError("contract cannot contain floats or non-JSON scalar values") from exc
    if len(encoded) > maximum:
        raise ValueError("contract exceeds its canonical byte budget")
    validate_contract(schema, document)
    return document


def _exact_hash(value: FrozenModel, field: str, maximum: int) -> None:
    document = value.model_dump(mode="json")
    if len(canonical_json_bytes(document)) > maximum or getattr(value, field) != content_sha256(
        value.model_dump(mode="json", exclude={field})
    ):
        raise ValueError("contract byte bound or canonical hash differs")


class _QueryContract(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def raw_values(cls, value: object) -> object:
        return raw_similarity_contract_value(value)


class ReferenceQuerySpaces(_QueryContract):
    query: EmbeddingSpace
    document: EmbeddingSpace

    @model_validator(mode="after")
    def complementary_purposes(self) -> ReferenceQuerySpaces:
        query = EmbeddingSpace.model_validate(raw_similarity_contract_value(self.query))
        document = EmbeddingSpace.model_validate(raw_similarity_contract_value(self.document))
        if (
            query.purpose != "QUERY"
            or document.purpose != "DOCUMENT"
            or query.space_sha256 == document.space_sha256
            or query.model_spec != document.model_spec
            or query.runtime != document.runtime
        ):
            raise ValueError("QUERY/DOCUMENT require distinct purposes and identical model/runtime")
        return self


class ReferenceQueryTextInput(EmbeddingTextInput):
    model_config = ConfigDict(revalidate_instances="always")
    view: ExperimentView

    @model_validator(mode="before")
    @classmethod
    def raw_values(cls, value: object) -> object:
        return raw_similarity_contract_value(value)


class ReferenceQueryViewRow(_QueryContract):
    view: ExperimentView
    row_index: int = Field(ge=0, le=2, strict=True)
    encoding_sha256: Sha256


class ReferenceQueryExecutionPointer(_QueryContract):
    job_id: JobId
    query_request_id: str = Field(pattern=r"^embeddingquery_[0-9a-f]{32}$")
    request_sha256: Sha256
    input_set_sha256: Sha256
    result_member: ArtifactMemberPointer
    result_sha256: Sha256

    @model_validator(mode="after")
    def exact_member(self) -> ReferenceQueryExecutionPointer:
        if (
            self.result_member.member_path != "result.json"
            or self.result_member.schema_ref != REFERENCE_QUERY_RESULT_REF
            or self.result_member.media_type != "application/json"
        ):
            raise ValueError("reference QUERY result member differs")
        return self


class EmbeddingReferenceQueryInput(_QueryContract):
    schema_version: Literal["embedding-reference-query-input/1.0"] = (
        "embedding-reference-query-input/1.0"
    )
    job_id: JobId
    query_request_id: str = Field(pattern=r"^embeddingquery_[0-9a-f]{32}$")
    context_request_sha256: Sha256
    spaces: ReferenceQuerySpaces
    recipe: ExperimentViewRecipe
    rows: tuple[ReferenceQueryTextInput, ...] = Field(min_length=1, max_length=3)
    batch_size: int = Field(ge=1, le=3, strict=True)
    threads: int = Field(ge=1, le=16, strict=True)
    input_set_sha256: Sha256
    request_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, REFERENCE_QUERY_SCHEMA, MAX_REFERENCE_QUERY_BYTES
        )

    @model_validator(mode="after")
    def exact_query_rows(self) -> EmbeddingReferenceQueryInput:
        ExperimentViewRecipe.model_validate(raw_similarity_contract_value(self.recipe))
        keys = tuple(row.encoding.encoding_sha256 for row in self.rows)
        if (
            keys != tuple(sorted(set(keys)))
            or len({row.view for row in self.rows}) != len(self.rows)
            or len({row.encoding.storage_partition for row in self.rows}) != 1
            or any(row.encoding.space_sha256 != self.spaces.query.space_sha256 for row in self.rows)
            or self.input_set_sha256
            != embedding_input_set_sha256(tuple(row.encoding for row in self.rows))
        ):
            raise ValueError("reference QUERY ordered rows, view, partition or input hash differs")
        _exact_hash(self, "request_sha256", MAX_REFERENCE_QUERY_BYTES)
        return self


class EmbeddingReferenceQueryResult(_QueryContract):
    schema_version: Literal["embedding-reference-query-result/1.0"] = (
        "embedding-reference-query-result/1.0"
    )
    job_id: JobId
    query_request_id: str = Field(pattern=r"^embeddingquery_[0-9a-f]{32}$")
    context_request_sha256: Sha256
    request_sha256: Sha256
    spaces: ReferenceQuerySpaces
    recipe: ExperimentViewRecipe
    input_set_sha256: Sha256
    shard: EmbeddingVectorShardManifest
    view_rows: tuple[ReferenceQueryViewRow, ...] = Field(min_length=1, max_length=3)
    result_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, REFERENCE_QUERY_SCHEMA, MAX_REFERENCE_QUERY_BYTES
        )

    @model_validator(mode="after")
    def exact_query_shard(self) -> EmbeddingReferenceQueryResult:
        shard = parse_embedding_shard(raw_similarity_contract_value(self.shard))
        ExperimentViewRecipe.model_validate(raw_similarity_contract_value(self.recipe))
        if (
            shard.space != self.spaces.query
            or shard.input_set_sha256 != self.input_set_sha256
            or shard.row_count != len(self.view_rows)
            or len({row.view for row in self.view_rows}) != len(self.view_rows)
            or tuple(row.row_index for row in self.view_rows) != tuple(range(shard.row_count))
            or any(
                row.encoding_sha256 != shard.rows[row.row_index].encoding_sha256
                for row in self.view_rows
            )
        ):
            raise ValueError("reference QUERY result view/row/space closure differs")
        _exact_hash(self, "result_sha256", MAX_REFERENCE_QUERY_BYTES)
        return self


def parse_embedding_reference_query_input(value: object) -> EmbeddingReferenceQueryInput:
    return EmbeddingReferenceQueryInput.model_validate(value)


def parse_embedding_reference_query_result(value: object) -> EmbeddingReferenceQueryResult:
    return EmbeddingReferenceQueryResult.model_validate(value)


def validate_reference_query_result(
    request: EmbeddingReferenceQueryInput, result: EmbeddingReferenceQueryResult
) -> None:
    """Pure supplied-value closure; no byte resolution, source permission or launch occurs."""
    request = parse_embedding_reference_query_input(request)
    result = parse_embedding_reference_query_result(result)
    if (
        result.job_id != request.job_id
        or result.query_request_id != request.query_request_id
        or result.context_request_sha256 != request.context_request_sha256
        or result.request_sha256 != request.request_sha256
        or result.spaces != request.spaces
        or result.recipe != request.recipe
        or result.input_set_sha256 != request.input_set_sha256
        or result.shard.rows != tuple(row.encoding for row in request.rows)
        or tuple(row.view for row in result.view_rows) != tuple(row.view for row in request.rows)
    ):
        raise ValueError("reference QUERY result differs from its exact pinned request")
