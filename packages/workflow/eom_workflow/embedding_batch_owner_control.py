"""Closed finite root/source-owner metadata; parsing supplies neither source nor GPU authority."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Annotated, Any, Literal, Self

from eom_catalog_contracts.embedding_gpu_control import (
    EmbeddingGpuAllocationBusy,
    EmbeddingGpuAllocationReady,
    EmbeddingGpuAllocationRequest,
    EmbeddingGpuComputeGrant,
    validate_embedding_gpu_allocation_link,
)
from eom_catalog_contracts.embedding_native_installation_evidence import (
    parse_rootlocal_evidence_document,
)
from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.models import Sha256, UtcDatetime
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from referencing import Resource

from eom_workflow.embedding_batch_plan import (
    BATCH_PLAN_SCHEMA_REF,
    EmbeddingBatchBound,
    embedding_batch_plan_schema,
)
from eom_workflow.schemas import local_embedding_admission_schema_registry

BATCH_OWNER_CONTROL_SCHEMA_REF = "eom://schemas/workflow/embedding-batch-owner-control/1.0"
BATCH_OWNER_CONTROL_SCHEMA_SHA256 = (
    "sha256:c253a518f30cf1f12fbe5644b7758ce50b726143ebe4334078cfba6cabdc437b"
)
MAX_BATCH_OWNER_CONTROL_BYTES = 64 * 1024
MAX_BATCH_OWNER_CHECKS = 352
type _Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$", strict=True)]
type _Tick = Annotated[int, Field(ge=1, le=2**63 - 1, strict=True)]


class EmbeddingBatchOwnerControlError(ValueError):
    def __init__(self) -> None:
        super().__init__("EMBEDDING_BATCH_OWNER_CONTROL_INVALID")


def _require(condition: bool) -> None:
    if not condition:
        raise EmbeddingBatchOwnerControlError()


@lru_cache(maxsize=1)
def _schema_raw() -> bytes:
    with (
        files("eom_workflow")
        .joinpath("resources/embedding-batch-owner-control-v1.schema.json")
        .open("rb") as stream
    ):
        raw = stream.read(MAX_BATCH_OWNER_CONTROL_BYTES + 1)
    _require(
        0 < len(raw) <= MAX_BATCH_OWNER_CONTROL_BYTES
        and sha256_bytes(raw) == BATCH_OWNER_CONTROL_SCHEMA_SHA256
    )
    return raw


def embedding_batch_owner_control_schema() -> dict[str, Any]:
    value: dict[str, Any] = json.loads(_schema_raw())
    return value


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = embedding_batch_owner_control_schema()
    Draft202012Validator.check_schema(schema)
    registry = local_embedding_admission_schema_registry().with_resource(
        BATCH_PLAN_SCHEMA_REF, Resource.from_contents(embedding_batch_plan_schema())
    )
    return Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())


class _OwnerMessage(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="forbid", revalidate_instances="always", hide_input_in_errors=True
    )

    schema_version: Literal["embedding-batch-owner-control/1.0"]
    allocation_attempt_id: str = Field(pattern=r"^embeddingallocation_[0-9a-f]{32}$", strict=True)
    allocation_request_sha256: Sha256
    controller_release: str = Field(pattern=r"^[0-9a-f]{40}$", strict=True)
    message_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> Any:
        try:
            document = raw_similarity_contract_value(value)
            _require(len(canonical_json_bytes(document)) <= MAX_BATCH_OWNER_CONTROL_BYTES)
            _validator().validate(document)
            return document
        except Exception:
            raise EmbeddingBatchOwnerControlError() from None

    @model_validator(mode="after")
    def exact_hash(self) -> Self:
        _require(
            self.message_sha256
            == content_sha256(self.model_dump(mode="json", exclude={"message_sha256"}))
        )
        return self


class EmbeddingBatchRootReady(_OwnerMessage):
    message_type: Literal["ROOT_READY"]
    readiness: EmbeddingGpuAllocationReady
    unit_invocation_id: _Hex
    unit_started_monotonic: _Tick
    effective_policy_sha256: Sha256
    observed_at: UtcDatetime


class EmbeddingBatchOwnerBound(_OwnerMessage):
    message_type: Literal["OWNER_BOUND"]
    binding: EmbeddingBatchBound
    ready_message_sha256: Sha256
    input_raw_sha256: Sha256
    input_byte_count: int = Field(ge=1, le=64 * 1024**2, strict=True)
    owner_pid: int = Field(ge=1, le=2**31 - 1, strict=True)
    owner_start_ticks: _Tick


class EmbeddingBatchRootCheck(_OwnerMessage):
    message_type: Literal["ROOT_CHECK"]
    batch_request_sha256: Sha256
    child_request_sha256: Sha256
    sequence: int = Field(ge=1, le=MAX_BATCH_OWNER_CHECKS, strict=True)


class EmbeddingBatchOwnerChecked(_OwnerMessage):
    message_type: Literal["OWNER_CHECKED"]
    batch_request_sha256: Sha256
    child_request_sha256: Sha256
    sequence: int = Field(ge=1, le=MAX_BATCH_OWNER_CHECKS, strict=True)
    check_message_sha256: Sha256


class EmbeddingBatchRootCompleted(_OwnerMessage):
    """Root's original terminal/release claim; owner must validate local output and sources."""

    message_type: Literal["ROOT_COMPLETED"]
    bound_message_sha256: Sha256
    grant: EmbeddingGpuComputeGrant
    unit_invocation_id: _Hex
    unit_exited_monotonic: _Tick
    retired_at: UtcDatetime
    result_raw_sha256: Sha256
    result_sha256: Sha256
    result_byte_count: int = Field(ge=1, le=64 * 1024**2, strict=True)
    vectors_sha256: Sha256
    vectors_byte_count: int = Field(ge=4, le=16 * 1024**2, strict=True)


class EmbeddingBatchOwnerAck(_OwnerMessage):
    message_type: Literal["OWNER_ACK"]
    completion_message_sha256: Sha256
    evidence_state: Literal["RECEIVED_NOT_CANONICAL_PUBLICATION"]


class EmbeddingBatchRootBusy(_OwnerMessage):
    message_type: Literal["ROOT_BUSY"]
    allocation: EmbeddingGpuAllocationBusy
    unit_invocation_id: _Hex
    unit_started_monotonic: _Tick
    unit_exited_monotonic: _Tick
    retired_at: UtcDatetime

    @model_validator(mode="after")
    def ordered_terminal(self) -> Self:
        _require(self.unit_exited_monotonic >= self.unit_started_monotonic)
        return self


type EmbeddingBatchOwnerMessage = Annotated[
    EmbeddingBatchRootReady
    | EmbeddingBatchOwnerBound
    | EmbeddingBatchRootCheck
    | EmbeddingBatchOwnerChecked
    | EmbeddingBatchRootCompleted
    | EmbeddingBatchOwnerAck
    | EmbeddingBatchRootBusy,
    Field(discriminator="message_type"),
]


def parse_embedding_batch_owner_control(value: object) -> EmbeddingBatchOwnerMessage:
    try:
        return TypeAdapter(EmbeddingBatchOwnerMessage).validate_python(
            raw_similarity_contract_value(value)
        )
    except Exception:
        raise EmbeddingBatchOwnerControlError() from None


def embedding_batch_owner_control_bytes(value: EmbeddingBatchOwnerMessage) -> bytes:
    checked = parse_embedding_batch_owner_control(value)
    return canonical_json_bytes(checked.model_dump(mode="json"))


def parse_embedding_batch_owner_control_bytes(raw: bytes) -> EmbeddingBatchOwnerMessage:
    try:
        value = parse_rootlocal_evidence_document(raw, MAX_BATCH_OWNER_CONTROL_BYTES)
        checked = parse_embedding_batch_owner_control(value)
        _require(embedding_batch_owner_control_bytes(checked) == raw)
        return checked
    except Exception:
        raise EmbeddingBatchOwnerControlError() from None


def validate_embedding_batch_owner_context(
    request: EmbeddingGpuAllocationRequest,
    controller_release: str,
    message: EmbeddingBatchOwnerMessage,
) -> None:
    """Pure original request/release closure; no runtime, source or peer observation."""
    request = EmbeddingGpuAllocationRequest.model_validate(request)
    message = parse_embedding_batch_owner_control(message)
    _require(
        message.allocation_request_sha256 == request.message_sha256
        and message.allocation_attempt_id == request.allocation_attempt_id
        and message.controller_release == controller_release
    )
    if isinstance(message, EmbeddingBatchRootReady):
        validate_embedding_gpu_allocation_link(request, message.readiness)
    elif isinstance(message, EmbeddingBatchOwnerBound):
        _require(message.binding.request_sha256 == request.parent_request_sha256)
    elif isinstance(message, EmbeddingBatchRootCompleted):
        _require(
            message.grant.allocation_request_sha256 == request.message_sha256
            and message.grant.allocation_attempt_id == request.allocation_attempt_id
        )
    elif isinstance(message, EmbeddingBatchRootBusy):
        validate_embedding_gpu_allocation_link(request, message.allocation)


def validate_embedding_batch_owner_completion(
    request: EmbeddingGpuAllocationRequest,
    ready: EmbeddingBatchRootReady,
    bound: EmbeddingBatchOwnerBound,
    completed: EmbeddingBatchRootCompleted,
) -> None:
    """One pure original completion closure, not transport state or physical/source proof."""
    ready = EmbeddingBatchRootReady.model_validate(ready)
    bound = EmbeddingBatchOwnerBound.model_validate(bound)
    completed = EmbeddingBatchRootCompleted.model_validate(completed)
    for value in (ready, bound, completed):
        validate_embedding_batch_owner_context(request, ready.controller_release, value)
    grant = completed.grant
    _require(
        bound.ready_message_sha256 == ready.message_sha256
        and completed.bound_message_sha256 == bound.message_sha256
        and completed.unit_invocation_id == ready.unit_invocation_id
        and completed.unit_exited_monotonic >= ready.unit_started_monotonic
        and grant.ready_message_sha256 == ready.readiness.message_sha256
        and grant.batch_request_sha256 == bound.binding.batch_request_sha256
        and grant.batch_input_raw_sha256 == bound.input_raw_sha256
        and grant.batch_input_byte_count == bound.input_byte_count
    )
