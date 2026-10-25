"""INDEX-only bulk metadata successor; native control and planning event frames stay 1.0."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any, ClassVar, Literal

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.models import Sha256
from eom_identifiers import canonical_json_bytes, sha256_bytes
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import Field, model_validator
from referencing import Resource

from eom_workflow.embedding_batch_plan import (
    BATCH_PLAN_SCHEMA_REF,
    MAX_BATCH_PLAN_BYTES,
    embedding_batch_plan_schema,
)
from eom_workflow.embedding_batch_plan_values import (
    EmbeddingBatchPlanRequestValues,
    EmbeddingBatchPlanValue,
    EmbeddingBatchSelectionValues,
)
from eom_workflow.embedding_device_routing import (
    EMBEDDING_DEVICE_ROUTING_SCHEMA_REF,
    embedding_device_routing_schema,
)
from eom_workflow.native_embedding_backend_selection import (
    NATIVE_EMBEDDING_BACKEND_SELECTION_SCHEMA_REF,
    native_embedding_backend_selection_schema,
)
from eom_workflow.schemas import local_embedding_admission_schema_registry

BATCH_PLAN_V11_PROTOCOL = "embedding-batch-plan/1.1"
BATCH_PLAN_V11_SCHEMA_REF = "eom://schemas/workflow/embedding-batch-plan/1.1"
BATCH_PLAN_V11_SCHEMA_SHA256 = (
    "sha256:deb40e0b3ebbcaed1d956bf5d9cbc09937a5f4a568bd397c819396387e0dd6c3"
)
BATCH_SELECTION_V11_SCHEMA_REF = BATCH_PLAN_V11_SCHEMA_REF + "#/$defs/selection"
MAX_BULK_BATCH_SELECTION_BYTES = 4 * 1024**2


@lru_cache(maxsize=1)
def _schema_raw() -> bytes:
    with (
        files("eom_workflow")
        .joinpath("resources/embedding-batch-plan-v1.1.schema.json")
        .open("rb") as stream
    ):
        raw = stream.read(MAX_BATCH_PLAN_BYTES + 1)
    if (
        not 0 < len(raw) <= MAX_BATCH_PLAN_BYTES
        or sha256_bytes(raw) != BATCH_PLAN_V11_SCHEMA_SHA256
    ):
        raise ValueError("EMBEDDING_BATCH_PLAN_SCHEMA_INVALID")
    return raw


def embedding_batch_plan_v11_schema() -> dict[str, Any]:
    value: dict[str, Any] = json.loads(_schema_raw())
    return value


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = embedding_batch_plan_v11_schema()
    Draft202012Validator.check_schema(schema)
    registry = local_embedding_admission_schema_registry().with_resources(
        (
            (BATCH_PLAN_SCHEMA_REF, Resource.from_contents(embedding_batch_plan_schema())),
            (
                EMBEDDING_DEVICE_ROUTING_SCHEMA_REF,
                Resource.from_contents(embedding_device_routing_schema()),
            ),
            (
                NATIVE_EMBEDDING_BACKEND_SELECTION_SCHEMA_REF,
                Resource.from_contents(native_embedding_backend_selection_schema()),
            ),
        )
    )
    return Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())


class _BulkPlanMessage(EmbeddingBatchPlanValue):
    schema_version: Literal["embedding-batch-plan/1.1"]

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> Any:
        try:
            document = raw_similarity_contract_value(value)
            maximum = (
                MAX_BULK_BATCH_SELECTION_BYTES
                if document.get("message_type") == "SELECTION"
                else MAX_BATCH_PLAN_BYTES
            )
            if len(canonical_json_bytes(document)) > maximum:
                raise ValueError("oversized metadata")
            _validator().validate(document)
            return document
        except Exception:
            raise ValueError("EMBEDDING_BATCH_PLAN_INVALID") from None


class EmbeddingBatchSelectionV11(EmbeddingBatchSelectionValues, _BulkPlanMessage):
    """Only schema-validated INDEX is executable; QUERY1.1 is deliberately unsupported."""


class EmbeddingBatchPlanRequestV11(EmbeddingBatchPlanRequestValues, _BulkPlanMessage):
    selection_schema_ref: ClassVar[str] = BATCH_SELECTION_V11_SCHEMA_REF
    child_selection_sha256s: tuple[Sha256, ...] = Field(min_length=1, max_length=3)
