"""Principal-injected private snapshot transport values, not a worker permission grant."""

from __future__ import annotations

from typing import Literal

from eom_identifiers import canonical_json_bytes
from pydantic import model_validator

from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotAuthorizeRequest,
    InferenceTransferSnapshotAuthorizeResult,
    InferenceTransferSnapshotPrepareRequest,
    InferenceTransferSnapshotPrepareResult,
    InferenceTransferSnapshotReadRequest,
    InferenceTransferSnapshotReadResult,
    InferenceTransferSnapshotRequest,
    InferenceTransferSnapshotResult,
    validate_snapshot_authorize_result,
    validate_snapshot_prepare_result,
    validate_snapshot_read_result_context,
)
from eom_catalog_contracts.models import ActorId, FrozenModel
from eom_catalog_contracts.validation import validate_contract

type InferenceTransferSnapshotBindingError = Literal[
    "INFERENCE_TRANSFER_FORBIDDEN",
    "INFERENCE_TRANSFER_SNAPSHOT_CHANGED",
    "INFERENCE_TRANSFER_SNAPSHOT_POPULATION_TRUNCATED",
    "INFERENCE_TRANSFER_SNAPSHOT_SELECTION_INVALID",
    "INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH",
    "INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID",
    "INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE",
    "INFERENCE_TRANSFER_SNAPSHOT_BUDGET_EXCEEDED",
]
MAX_PRIVATE_SNAPSHOT_FRAME_BYTES = 4 * 1024**2


def _frame_bound(value: FrozenModel) -> None:
    if len(canonical_json_bytes(value.model_dump(mode="json"))) > MAX_PRIVATE_SNAPSHOT_FRAME_BYTES:
        raise ValueError("private snapshot binding exceeds its bounded frame")


class InferenceTransferSnapshotBindingRequest(FrozenModel):
    """Only the authenticated API owner supplies actor_id, never a public body/model."""

    schema_version: Literal["inference-transfer-snapshot-binding-request/1.0"] = (
        "inference-transfer-snapshot-binding-request/1.0"
    )
    operation: Literal["INFERENCE_TRANSFER_SNAPSHOT"] = "INFERENCE_TRANSFER_SNAPSHOT"
    actor_id: ActorId
    request: InferenceTransferSnapshotRequest

    @model_validator(mode="after")
    def exact_principal_identity(self) -> InferenceTransferSnapshotBindingRequest:
        if (
            isinstance(
                self.request,
                (InferenceTransferSnapshotReadRequest, InferenceTransferSnapshotAuthorizeRequest),
            )
            and self.request.header.actor_id != self.actor_id
        ):
            raise ValueError("private snapshot request actor differs from frozen header owner")
        _frame_bound(self)
        return self


class InferenceTransferSnapshotBindingReply(FrozenModel):
    schema_version: Literal["inference-transfer-snapshot-binding-reply/1.0"] = (
        "inference-transfer-snapshot-binding-reply/1.0"
    )
    operation: Literal["INFERENCE_TRANSFER_SNAPSHOT"] = "INFERENCE_TRANSFER_SNAPSHOT"
    status: Literal["SUCCESS", "FAILED"]
    result: InferenceTransferSnapshotResult | None
    error_code: InferenceTransferSnapshotBindingError | None

    @model_validator(mode="after")
    def exact_result_presence(self) -> InferenceTransferSnapshotBindingReply:
        if (self.status == "SUCCESS") != (self.result is not None) or (
            (self.status == "FAILED") != (self.error_code is not None)
        ):
            raise ValueError("private snapshot status/result/error presence differs")
        _frame_bound(self)
        return self


def parse_binding_request(value: object) -> InferenceTransferSnapshotBindingRequest:
    if not isinstance(value, dict):
        raise ValueError("private snapshot request must be a JSON object")
    validate_contract("item-inference-transfer-snapshot-binding", value)
    return InferenceTransferSnapshotBindingRequest.model_validate(value)


def parse_binding_reply(value: object) -> InferenceTransferSnapshotBindingReply:
    if not isinstance(value, dict):
        raise ValueError("private snapshot reply must be a JSON object")
    validate_contract("item-inference-transfer-snapshot-binding", value)
    return InferenceTransferSnapshotBindingReply.model_validate(value)


def validate_binding_reply(
    request: InferenceTransferSnapshotBindingRequest,
    reply: InferenceTransferSnapshotBindingReply,
) -> None:
    """Validate reply identity without treating transport metadata as source authority."""
    request = parse_binding_request(request.model_dump(mode="json"))
    reply = parse_binding_reply(reply.model_dump(mode="json"))
    if reply.status == "FAILED":
        return
    body = request.request
    result = reply.result
    if isinstance(body, InferenceTransferSnapshotPrepareRequest) and isinstance(
        result, InferenceTransferSnapshotPrepareResult
    ):
        validate_snapshot_prepare_result(body, result)
        if result.header.actor_id != request.actor_id:
            raise ValueError("private snapshot prepare reply belongs to another actor")
        return
    if isinstance(body, InferenceTransferSnapshotReadRequest) and isinstance(
        result, InferenceTransferSnapshotReadResult
    ):
        validate_snapshot_read_result_context(body, result)
        return
    if isinstance(body, InferenceTransferSnapshotAuthorizeRequest) and isinstance(
        result, InferenceTransferSnapshotAuthorizeResult
    ):
        validate_snapshot_authorize_result(body, result)
        return
    raise ValueError("private snapshot reply phase differs from the exact requested phase")
