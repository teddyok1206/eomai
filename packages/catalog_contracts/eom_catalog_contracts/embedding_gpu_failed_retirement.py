"""Small protected failed-unit result; neither source admission nor numerical success."""

from __future__ import annotations

from typing import Literal

from jsonschema import ValidationError as JsonSchemaError
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import similarity_contract_document
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime


class FailedEmbeddingGpuRetirement(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")

    schema_version: Literal["embedding-gpu-failed-retirement/1.0"]
    event: Literal["EMBEDDING_GPU_BATCH_FAILED_RETIRED_NOT_PUBLISHED"]
    allocation_attempt_id: str = Field(pattern=r"^embeddingallocation_[0-9a-f]{32}$")
    allocation_raw_sha256: Sha256
    allocation_request_sha256: Sha256
    invocation_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    intent_sha256: Sha256
    original_outcome: Literal["FAILED"]
    stored_descriptors: Literal[0]
    observed_at: UtcDatetime

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        try:
            return similarity_contract_document(value, "embedding-gpu-failed-retirement", 16384)
        except (JsonSchemaError, TypeError, ValueError):
            raise ValueError("EMBEDDING_GPU_FAILED_RETIREMENT_INVALID") from None
