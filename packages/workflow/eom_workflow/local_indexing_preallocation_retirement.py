"""Exact deployment-owner retirement metadata; not worker input or a service grant."""

from __future__ import annotations

import json
from functools import cache
from importlib.resources import files
from typing import Literal, Self

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.models import Sha256
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_operator_identity import LocalIndexingServiceReference
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import Field, model_validator

from eom_workflow.control_plane import UtcDatetime
from eom_workflow.schemas import NativeEmbeddingContract

LOCAL_INDEXING_RETIREMENT_SCHEMA_RESOURCE = (
    "local-indexing-preallocation-retirement-v1.schema.json",
    "eom://schemas/workflow/local-indexing-preallocation-retirement/1.0",
    "sha256:2af388752b7df14de92d27b5f0f8f8be1b4a1423a251ac4da0d86cdd0652be2c",
)
LOCAL_INDEXING_RETIREMENT_V11_SCHEMA_RESOURCE = (
    "local-indexing-preallocation-retirement-v11.schema.json",
    "eom://schemas/workflow/local-indexing-preallocation-retirement/1.1",
    "sha256:1fe87fe04d930087236b4036f3ad5a4965062abb4b896214b692e214ab7abf77",
)


@cache
def _validator() -> Draft202012Validator:
    # Removing this owner-maintenance leaf must not change any runtime schema
    # family/registry/hash or make unrelated admission load its resource.
    return _schema_validator(LOCAL_INDEXING_RETIREMENT_SCHEMA_RESOURCE)


@cache
def _v11_validator() -> Draft202012Validator:
    return _schema_validator(LOCAL_INDEXING_RETIREMENT_V11_SCHEMA_RESOURCE)


def _schema_validator(resource: tuple[str, str, str]) -> Draft202012Validator:
    filename, schema_id, expected = resource
    with files("eom_workflow").joinpath("resources", filename).open("rb") as stream:
        raw = stream.read(16 * 1024 + 1)
    if not 0 < len(raw) <= 16 * 1024 or sha256_bytes(raw) != expected:
        raise ValueError("LOCAL_INDEXING_RETIREMENT_SCHEMA_UNAVAILABLE")
    schema = json.loads(raw)
    if not isinstance(schema, dict) or schema.get("$id") != schema_id:
        raise ValueError("LOCAL_INDEXING_RETIREMENT_SCHEMA_UNAVAILABLE")
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


class LocalIndexingPreallocationRetirementCommand(NativeEmbeddingContract):
    schema_version: Literal["local-indexing-preallocation-retirement/1.0"] = (
        "local-indexing-preallocation-retirement/1.0"
    )
    record_type: Literal["COMMAND"] = "COMMAND"
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    workflow_request_sha256: Sha256
    command_id: str = Field(pattern=r"^wfcmd_[0-9a-f]{32}$")
    lease_generation: int = Field(strict=True, ge=1, le=2147483647)
    service: LocalIndexingServiceReference
    successor_source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    reason: Literal["EMBEDDING_ENCODING_PROTOCOL_UNAVAILABLE"] = (
        "EMBEDDING_ENCODING_PROTOCOL_UNAVAILABLE"
    )
    command_sha256: Sha256

    @model_validator(mode="after")
    def exact_hash(self) -> Self:
        if self.command_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"command_sha256"})
        ):
            raise ValueError("LOCAL_INDEXING_RETIREMENT_COMMAND_HASH_INVALID")
        return self


class LocalIndexingPreallocationRetirementReceipt(NativeEmbeddingContract):
    schema_version: Literal["local-indexing-preallocation-retirement/1.0"] = (
        "local-indexing-preallocation-retirement/1.0"
    )
    record_type: Literal["RECEIPT"] = "RECEIPT"
    command: LocalIndexingPreallocationRetirementCommand
    step_run_id: str = Field(pattern=r"^steprun_[0-9a-f]{32}$")
    performed_by: str = Field(min_length=1, max_length=63, pattern=r"^[a-z_][a-z0-9_]*$")
    performed_at: UtcDatetime
    prior_command_state: Literal["PROCESSING"] = "PROCESSING"
    new_workflow_state: Literal["FAILED"] = "FAILED"
    new_stage: Literal["FAILED"] = "FAILED"
    new_command_state: Literal["FAILED"] = "FAILED"
    new_step_state: Literal["FAILED"] = "FAILED"
    receipt_sha256: Sha256

    @model_validator(mode="after")
    def exact_hash(self) -> Self:
        if self.receipt_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"receipt_sha256"})
        ):
            raise ValueError("LOCAL_INDEXING_RETIREMENT_RECEIPT_HASH_INVALID")
        return self


class LocalIndexingPreallocationRetirementCommandV11(LocalIndexingPreallocationRetirementCommand):
    """Observed executor-context failure before any native launch, not protocol failure."""

    schema_version: Literal["local-indexing-preallocation-retirement/1.1"] = (
        "local-indexing-preallocation-retirement/1.1"  # type: ignore[assignment]
    )
    reason: Literal["EMBEDDING_EXECUTION_CONTEXT_UNAVAILABLE"] = (
        "EMBEDDING_EXECUTION_CONTEXT_UNAVAILABLE"  # type: ignore[assignment]
    )


class LocalIndexingPreallocationRetirementReceiptV11(LocalIndexingPreallocationRetirementReceipt):
    schema_version: Literal["local-indexing-preallocation-retirement/1.1"] = (
        "local-indexing-preallocation-retirement/1.1"  # type: ignore[assignment]
    )
    command: LocalIndexingPreallocationRetirementCommandV11


type SupportedLocalIndexingRetirementCommand = (
    LocalIndexingPreallocationRetirementCommand | LocalIndexingPreallocationRetirementCommandV11
)
type SupportedLocalIndexingRetirementReceipt = (
    LocalIndexingPreallocationRetirementReceipt | LocalIndexingPreallocationRetirementReceiptV11
)


def parse_local_indexing_retirement_command(
    value: object,
) -> LocalIndexingPreallocationRetirementCommand:
    parsed = LocalIndexingPreallocationRetirementCommand.model_validate(value)
    document = parsed.model_dump(mode="json")
    if len(canonical_json_bytes(document)) > 8192:
        raise ValueError("LOCAL_INDEXING_RETIREMENT_CONTRACT_INVALID")
    _validator().validate(document)
    return parsed


def parse_local_indexing_retirement_receipt(
    value: object,
) -> LocalIndexingPreallocationRetirementReceipt:
    parsed = LocalIndexingPreallocationRetirementReceipt.model_validate(value)
    document = parsed.model_dump(mode="json")
    if len(canonical_json_bytes(document)) > 8192:
        raise ValueError("LOCAL_INDEXING_RETIREMENT_CONTRACT_INVALID")
    _validator().validate(document)
    return parsed


def parse_local_indexing_retirement_command_v11(
    value: object,
) -> LocalIndexingPreallocationRetirementCommandV11:
    parsed = LocalIndexingPreallocationRetirementCommandV11.model_validate(value)
    document = parsed.model_dump(mode="json")
    if len(canonical_json_bytes(document)) > 8192:
        raise ValueError("LOCAL_INDEXING_RETIREMENT_CONTRACT_INVALID")
    _v11_validator().validate(document)
    return parsed


def parse_local_indexing_retirement_receipt_v11(
    value: object,
) -> LocalIndexingPreallocationRetirementReceiptV11:
    parsed = LocalIndexingPreallocationRetirementReceiptV11.model_validate(value)
    document = parsed.model_dump(mode="json")
    if len(canonical_json_bytes(document)) > 8192:
        raise ValueError("LOCAL_INDEXING_RETIREMENT_CONTRACT_INVALID")
    _v11_validator().validate(document)
    return parsed


def parse_supported_local_indexing_retirement_command(
    value: object,
) -> SupportedLocalIndexingRetirementCommand:
    version = raw_similarity_contract_value(value).get("schema_version")
    if version == "local-indexing-preallocation-retirement/1.0":
        return parse_local_indexing_retirement_command(value)
    if version == "local-indexing-preallocation-retirement/1.1":
        return parse_local_indexing_retirement_command_v11(value)
    raise ValueError("LOCAL_INDEXING_RETIREMENT_CONTRACT_INVALID")


def parse_supported_local_indexing_retirement_receipt(
    value: object,
) -> SupportedLocalIndexingRetirementReceipt:
    version = raw_similarity_contract_value(value).get("schema_version")
    if version == "local-indexing-preallocation-retirement/1.0":
        return parse_local_indexing_retirement_receipt(value)
    if version == "local-indexing-preallocation-retirement/1.1":
        return parse_local_indexing_retirement_receipt_v11(value)
    raise ValueError("LOCAL_INDEXING_RETIREMENT_CONTRACT_INVALID")
