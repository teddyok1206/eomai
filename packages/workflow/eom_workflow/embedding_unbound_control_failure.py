"""Immutable original controller-failure metadata, never authority or a retry grant."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any, Literal, Self

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.models import Sha256, UtcDatetime
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import Field, model_validator

from eom_workflow.models import JobId
from eom_workflow.schemas import NativeEmbeddingContract

UNBOUND_CONTROL_FAILURE_SCHEMA = "eom://schemas/workflow/embedding-unbound-control-failure/1.0"
UNBOUND_CONTROL_FAILURE_SCHEMA_SHA256 = (
    "sha256:aef6b1cadff03eb5b6331b1ca08de4b7c261a178a2b0c9de075c7fa430a5c369"
)
UNBOUND_CONTROL_FAILURE_CODE = "EMBEDDING_GPU_CONTROLLER_FAILED_UNBOUND"


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    raw = (
        files("eom_workflow")
        .joinpath("resources/embedding-unbound-control-failure-v1.schema.json")
        .read_bytes()
    )
    if len(raw) > 16384 or sha256_bytes(raw) != UNBOUND_CONTROL_FAILURE_SCHEMA_SHA256:
        raise ValueError("EMBEDDING_UNBOUND_CONTROL_SCHEMA_INVALID")
    schema = json.loads(raw)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


class UnboundEmbeddingControlFailure(NativeEmbeddingContract):
    schema_version: Literal["embedding-unbound-control-failure/1.0"]
    parent_plan_job_id: JobId
    parent_request_sha256: Sha256
    allocation_attempt_id: str = Field(pattern=r"^embeddingallocation_[0-9a-f]{32}$")
    allocation_request_sha256: Sha256
    controller_invocation_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    controller_pid: int = Field(strict=True, ge=1, le=2147483647)
    boot_id: str
    allocation_raw_sha256: Sha256
    launch_raw_sha256: Sha256
    descriptor_raw_sha256: Sha256
    controller_outcome: Literal["FAILED"]
    compute_state: Literal["NOT_GRANTED"]
    observed_at: UtcDatetime
    evidence_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> Any:
        try:
            document = raw_similarity_contract_value(value)
            if len(canonical_json_bytes(document)) > 8192:
                raise ValueError("EMBEDDING_UNBOUND_CONTROL_EVIDENCE_INVALID")
            _validator().validate(document)
            return document
        except (ValueError, SchemaValidationError):
            raise ValueError("EMBEDDING_UNBOUND_CONTROL_EVIDENCE_INVALID") from None

    @model_validator(mode="after")
    def exact_hash(self) -> Self:
        if self.evidence_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"evidence_sha256"})
        ):
            raise ValueError("EMBEDDING_UNBOUND_CONTROL_EVIDENCE_INVALID")
        return self
