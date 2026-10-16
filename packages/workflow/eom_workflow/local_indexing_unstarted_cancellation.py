"""Exact deployment-owner cancellation of a never-claimed indexing request."""

from __future__ import annotations

import json
from functools import cache
from importlib.resources import files
from typing import Literal, Self

from eom_catalog_contracts.models import Sha256
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_operator_identity import LocalIndexingServiceReference
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import Field, model_validator

from eom_workflow.control_plane import UtcDatetime
from eom_workflow.schemas import NativeEmbeddingContract

LOCAL_INDEXING_UNSTARTED_CANCELLATION_SCHEMA_RESOURCE = (
    "local-indexing-unstarted-cancellation-v1.schema.json",
    "eom://schemas/workflow/local-indexing-unstarted-cancellation/1.0",
    "sha256:e13e1c507f6b8bf2061c826a63d1ec9e0c0ea6b9931a0d34e6f469c8ec022dc6",
)


@cache
def _validator() -> Draft202012Validator:
    # Removing this owner-maintenance leaf must not change any runtime schema
    # family/registry/hash or make unrelated admission load its resource.
    filename, schema_id, expected = LOCAL_INDEXING_UNSTARTED_CANCELLATION_SCHEMA_RESOURCE
    with files("eom_workflow").joinpath("resources", filename).open("rb") as stream:
        raw = stream.read(16 * 1024 + 1)
    if not 0 < len(raw) <= 16 * 1024 or sha256_bytes(raw) != expected:
        raise ValueError("LOCAL_INDEXING_CANCELLATION_SCHEMA_UNAVAILABLE")
    schema = json.loads(raw)
    if not isinstance(schema, dict) or schema.get("$id") != schema_id:
        raise ValueError("LOCAL_INDEXING_CANCELLATION_SCHEMA_UNAVAILABLE")
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


class LocalIndexingUnstartedCancellationCommand(NativeEmbeddingContract):
    schema_version: Literal["local-indexing-unstarted-cancellation/1.0"] = (
        "local-indexing-unstarted-cancellation/1.0"
    )
    record_type: Literal["COMMAND"] = "COMMAND"
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    workflow_request_sha256: Sha256
    command_id: str = Field(pattern=r"^wfcmd_[0-9a-f]{32}$")
    service: LocalIndexingServiceReference
    successor_source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    reason: Literal["NATIVE_RUNTIME_RELEASE_SUPERSEDED"] = "NATIVE_RUNTIME_RELEASE_SUPERSEDED"
    command_sha256: Sha256

    @model_validator(mode="after")
    def exact_hash(self) -> Self:
        if self.command_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"command_sha256"})
        ):
            raise ValueError("LOCAL_INDEXING_CANCELLATION_COMMAND_HASH_INVALID")
        return self


class LocalIndexingUnstartedCancellationReceipt(NativeEmbeddingContract):
    schema_version: Literal["local-indexing-unstarted-cancellation/1.0"] = (
        "local-indexing-unstarted-cancellation/1.0"
    )
    record_type: Literal["RECEIPT"] = "RECEIPT"
    command: LocalIndexingUnstartedCancellationCommand
    performed_by: str = Field(min_length=1, max_length=63, pattern=r"^[a-z_][a-z0-9_]*$")
    performed_at: UtcDatetime
    prior_workflow_state: Literal["REQUESTED"] = "REQUESTED"
    prior_command_state: Literal["PENDING"] = "PENDING"
    step_run_count: int = Field(strict=True, ge=0, le=0)
    new_workflow_state: Literal["CANCELLED"] = "CANCELLED"
    new_stage: Literal["CANCELLED"] = "CANCELLED"
    new_command_state: Literal["CANCELLED"] = "CANCELLED"
    receipt_sha256: Sha256

    @model_validator(mode="after")
    def exact_hash(self) -> Self:
        if self.receipt_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"receipt_sha256"})
        ):
            raise ValueError("LOCAL_INDEXING_CANCELLATION_RECEIPT_HASH_INVALID")
        return self


def parse_local_indexing_cancellation_command(
    value: object,
) -> LocalIndexingUnstartedCancellationCommand:
    parsed = LocalIndexingUnstartedCancellationCommand.model_validate(value)
    document = parsed.model_dump(mode="json")
    if len(canonical_json_bytes(document)) > 8192:
        raise ValueError("LOCAL_INDEXING_CANCELLATION_CONTRACT_INVALID")
    _validator().validate(document)
    return parsed


def parse_local_indexing_cancellation_receipt(
    value: object,
) -> LocalIndexingUnstartedCancellationReceipt:
    parsed = LocalIndexingUnstartedCancellationReceipt.model_validate(value)
    document = parsed.model_dump(mode="json")
    if len(canonical_json_bytes(document)) > 8192:
        raise ValueError("LOCAL_INDEXING_CANCELLATION_CONTRACT_INVALID")
    _validator().validate(document)
    return parsed
