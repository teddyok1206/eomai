"""Small immutable CUDA execution metadata; not child publication or a source grant."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any, Literal, Self

from eom_catalog_contracts.embedding_gpu_control import EmbeddingGpuAllocationRequest
from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.embedding_work_batch import EmbeddingWorkBatchScope
from eom_catalog_contracts.models import Sha256
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, ConfigDict, Field, model_validator
from referencing import Resource

from eom_workflow.embedding_batch_owner_control import (
    BATCH_OWNER_CONTROL_SCHEMA_REF,
    EmbeddingBatchOwnerBound,
    EmbeddingBatchRootCompleted,
    EmbeddingBatchRootReady,
    embedding_batch_owner_control_schema,
    validate_embedding_batch_owner_completion,
)
from eom_workflow.embedding_batch_plan import BATCH_PLAN_SCHEMA_REF, embedding_batch_plan_schema
from eom_workflow.schemas import local_embedding_admission_schema_registry

BATCH_EXECUTION_RECEIPT_SCHEMA_REF = "eom://schemas/workflow/embedding-batch-execution-receipt/1.0"
BATCH_EXECUTION_RECEIPT_SCHEMA_SHA256 = (
    "sha256:6858a52c0dff379c7db3dd79325a2ea82f168e2b847f22a57f55e3baf3bcc7f7"
)
MAX_BATCH_EXECUTION_RECEIPT_BYTES = 512 * 1024


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("EMBEDDING_BATCH_EXECUTION_RECEIPT_INVALID")


@lru_cache(maxsize=1)
def _schema_raw() -> bytes:
    with (
        files("eom_workflow")
        .joinpath("resources/embedding-batch-execution-receipt-v1.schema.json")
        .open("rb") as stream
    ):
        raw = stream.read(MAX_BATCH_EXECUTION_RECEIPT_BYTES + 1)
    _require(
        0 < len(raw) <= MAX_BATCH_EXECUTION_RECEIPT_BYTES
        and sha256_bytes(raw) == BATCH_EXECUTION_RECEIPT_SCHEMA_SHA256
    )
    return raw


def embedding_batch_execution_receipt_schema() -> dict[str, Any]:
    value: dict[str, Any] = json.loads(_schema_raw())
    return value


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = embedding_batch_execution_receipt_schema()
    Draft202012Validator.check_schema(schema)
    registry = local_embedding_admission_schema_registry().with_resources(
        (
            (BATCH_PLAN_SCHEMA_REF, Resource.from_contents(embedding_batch_plan_schema())),
            (
                BATCH_OWNER_CONTROL_SCHEMA_REF,
                Resource.from_contents(embedding_batch_owner_control_schema()),
            ),
        )
    )
    return Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())


class EmbeddingBatchExecutedChild(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="forbid", revalidate_instances="always", hide_input_in_errors=True
    )

    ordinal: int = Field(ge=0, le=31, strict=True)
    native_job_id: str = Field(pattern=r"^job_[0-9a-f]{32}$", strict=True)
    input_sha256: Sha256
    result_sha256: Sha256
    shard_sha256: Sha256
    binary_sha256: Sha256
    vector_offset: int = Field(ge=0, le=16 * 1024**2 - 4, strict=True)
    vector_byte_count: int = Field(ge=4, le=16 * 1024**2, strict=True)
    row_count: int = Field(ge=1, le=1024, strict=True)
    dimension: int = Field(ge=1, le=65536, strict=True)

    @model_validator(mode="before")
    @classmethod
    def raw_values(cls, value: object) -> Any:
        return raw_similarity_contract_value(value)

    @model_validator(mode="after")
    def exact_range(self) -> Self:
        _require(
            self.vector_offset % 4 == 0
            and self.vector_byte_count == 4 * self.row_count * self.dimension
        )
        return self


class EmbeddingBatchExecutionReceipt(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="forbid", revalidate_instances="always", hide_input_in_errors=True
    )

    schema_version: Literal["embedding-batch-execution-receipt/1.0"]
    purpose: Literal["INDEX", "REFERENCE_QUERY"]
    device: Literal["CUDA"]
    parent_plan_job_id: str = Field(pattern=r"^job_[0-9a-f]{32}$", strict=True)
    scope: EmbeddingWorkBatchScope
    allocation: EmbeddingGpuAllocationRequest
    ready: EmbeddingBatchRootReady
    bound: EmbeddingBatchOwnerBound
    completed: EmbeddingBatchRootCompleted
    children: tuple[EmbeddingBatchExecutedChild, ...] = Field(min_length=1, max_length=32)
    receipt_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> Any:
        try:
            document = raw_similarity_contract_value(value)
            _require(len(canonical_json_bytes(document)) <= MAX_BATCH_EXECUTION_RECEIPT_BYTES)
            _validator().validate(document)
            return document
        except Exception:
            raise ValueError("EMBEDDING_BATCH_EXECUTION_RECEIPT_INVALID") from None

    @model_validator(mode="after")
    def exact_closure(self) -> Self:
        validate_embedding_batch_owner_completion(
            self.allocation, self.ready, self.bound, self.completed
        )
        _require(
            self.purpose == self.allocation.purpose
            and self.allocation.child_set_sha256
            == content_sha256([child.selection_sha256 for child in self.bound.binding.children])
            and len(self.children) == len(self.bound.binding.children)
            and self.receipt_sha256
            == content_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        )
        position = rows = 0
        for ordinal, (child, binding) in enumerate(
            zip(self.children, self.bound.binding.children, strict=True)
        ):
            _require(
                child.ordinal == ordinal
                and child.native_job_id == binding.native_job_id
                and child.input_sha256 == binding.native_input_sha256
                and child.vector_offset == position
                and child.dimension == self.children[0].dimension
            )
            position += child.vector_byte_count
            rows += child.row_count
        _require(position == self.completed.vectors_byte_count and rows <= 1024)
        return self
