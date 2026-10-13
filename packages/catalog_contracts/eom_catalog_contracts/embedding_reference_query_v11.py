"""Input-only reference QUERY successor; configured batch is not partial row count."""

from __future__ import annotations

from typing import Literal

from eom_identifiers import content_sha256
from eom_protocol.models import JobId
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import (
    MAX_REFERENCE_QUERY_BYTES,
    EmbeddingReferenceQueryResult,
    ReferenceQuerySpaces,
    ReferenceQueryTextInput,
    parse_embedding_reference_query_result,
    raw_similarity_contract_value,
    similarity_contract_document,
)
from eom_catalog_contracts.inference_transfer_embedding import embedding_input_set_sha256
from eom_catalog_contracts.inference_transfer_experiment import ExperimentViewRecipe
from eom_catalog_contracts.models import FrozenModel, Sha256

REFERENCE_QUERY_INPUT_V11_SCHEMA = "embedding-reference-query-input-v1.1"
REFERENCE_QUERY_INPUT_V11_REF = "eom://schemas/knowledge/embedding-reference-query-input/1.1"


class EmbeddingReferenceQueryInputV11(FrozenModel):
    """One to three genuine rows; recipe equality still requires the actual backend owner."""

    model_config = ConfigDict(revalidate_instances="always")

    schema_version: Literal["embedding-reference-query-input/1.1"] = (
        "embedding-reference-query-input/1.1"
    )
    job_id: JobId
    query_request_id: str = Field(pattern=r"^embeddingquery_[0-9a-f]{32}$")
    context_request_sha256: Sha256
    spaces: ReferenceQuerySpaces
    recipe: ExperimentViewRecipe
    rows: tuple[ReferenceQueryTextInput, ...] = Field(min_length=1, max_length=3)
    batch_size: int = Field(ge=1, le=16, strict=True)
    threads: int = Field(ge=1, le=16, strict=True)
    input_set_sha256: Sha256
    request_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, REFERENCE_QUERY_INPUT_V11_SCHEMA, MAX_REFERENCE_QUERY_BYTES
        )

    @model_validator(mode="after")
    def exact_query_rows(self) -> EmbeddingReferenceQueryInputV11:
        ReferenceQuerySpaces.model_validate(raw_similarity_contract_value(self.spaces))
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
        if self.request_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"request_sha256"})
        ):
            raise ValueError("reference QUERY canonical request hash differs")
        return self


def parse_embedding_reference_query_input_v11(value: object) -> EmbeddingReferenceQueryInputV11:
    """Parse only literal input 1.1, without widening the released 1.0 parser."""
    return EmbeddingReferenceQueryInputV11.model_validate(value)


def validate_reference_query_result_v11(
    request: EmbeddingReferenceQueryInputV11, result: EmbeddingReferenceQueryResult
) -> None:
    """Pure 1.1-input/1.0-result closure, never source or native execution admission."""
    request = parse_embedding_reference_query_input_v11(request)
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
