"""Exact Graph metadata values; hashes and returned pointers never grant authority."""

from __future__ import annotations

from typing import Literal, get_args

from eom_identifiers import canonical_json_bytes, content_sha256
from pydantic import Field, model_validator

from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.validation import validate_contract

MAX_METADATA_FRAME_BYTES = 64 * 1024
type MetadataSourceClass = Literal["APPROVED_ITEM", "PAST_EXAM"]
InferenceTransferMetadataError = Literal[
    "INFERENCE_TRANSFER_FORBIDDEN",
    "INFERENCE_TRANSFER_METADATA_NOT_FOUND",
    "INFERENCE_TRANSFER_METADATA_PIN_MISMATCH",
    "INFERENCE_TRANSFER_METADATA_POLICY_INVALID",
    "INFERENCE_TRANSFER_METADATA_REQUEST_INVALID",
    "INFERENCE_TRANSFER_METADATA_UNAVAILABLE",
    "INFERENCE_TRANSFER_METADATA_BUDGET_EXCEEDED",
]
METADATA_ERRORS: frozenset[str] = frozenset(get_args(InferenceTransferMetadataError))


def _bound(value: FrozenModel) -> None:
    if len(canonical_json_bytes(value.model_dump(mode="json"))) + 1 > MAX_METADATA_FRAME_BYTES:
        raise ValueError("exact metadata frame exceeds its bound")


def _hashed(value: FrozenModel, field: str) -> None:
    if content_sha256(value.model_dump(mode="json", exclude={field})) != getattr(value, field):
        raise ValueError("exact metadata canonical hash differs")
    _bound(value)


def _classes(values: tuple[MetadataSourceClass, ...]) -> None:
    if values != tuple(sorted(set(values))):
        raise ValueError("metadata source classes must be sorted and unique")


class InferenceTransferMetadataResolveRequest(FrozenModel):
    schema_version: Literal["inference-transfer-metadata-request/1.0"] = (
        "inference-transfer-metadata-request/1.0"
    )
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    expected_snapshot_sha256: Sha256
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    access_policy_sha256: Sha256
    source_classes: tuple[MetadataSourceClass, ...] = Field(min_length=1, max_length=2)
    request_sha256: Sha256

    @model_validator(mode="after")
    def closed_hash(self) -> InferenceTransferMetadataResolveRequest:
        _classes(self.source_classes)
        _hashed(self, "request_sha256")
        return self


class InferenceTransferMetadataResolveResult(FrozenModel):
    schema_version: Literal["inference-transfer-metadata-result/1.0"] = (
        "inference-transfer-metadata-result/1.0"
    )
    request_sha256: Sha256
    graph_snapshot: KnowledgeGraphSnapshotPointer
    snapshot_sha256: Sha256
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    access_policy_sha256: Sha256
    source_classes: tuple[MetadataSourceClass, ...] = Field(min_length=1, max_length=2)
    result_sha256: Sha256

    @model_validator(mode="after")
    def closed_hash(self) -> InferenceTransferMetadataResolveResult:
        _classes(self.source_classes)
        member = self.graph_snapshot.manifest_artifact
        if (
            member.logical_name != "manifest.json"
            or member.member_path != "projections/manifest.json"
            or member.media_type != "application/json"
            or member.sha256 != self.graph_snapshot.manifest_sha256
            or member.schema_ref
            not in {
                f"eom://schemas/knowledge/knowledge-graph-snapshot-manifest/{version}.0"
                for version in range(2, 10)
            }
        ):
            raise ValueError("metadata Graph manifest member contract differs")
        _hashed(self, "result_sha256")
        return self


class InferenceTransferMetadataBindingRequest(FrozenModel):
    """Only the authenticated API composition supplies the actual operator."""

    schema_version: Literal["inference-transfer-metadata-binding-request/1.0"] = (
        "inference-transfer-metadata-binding-request/1.0"
    )
    operation: Literal["INFERENCE_TRANSFER_METADATA_RESOLVE"] = (
        "INFERENCE_TRANSFER_METADATA_RESOLVE"
    )
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    request: InferenceTransferMetadataResolveRequest

    @model_validator(mode="after")
    def bounded(self) -> InferenceTransferMetadataBindingRequest:
        _bound(self)
        return self


class InferenceTransferMetadataBindingReply(FrozenModel):
    schema_version: Literal["inference-transfer-metadata-binding-reply/1.0"] = (
        "inference-transfer-metadata-binding-reply/1.0"
    )
    operation: Literal["INFERENCE_TRANSFER_METADATA_RESOLVE"] = (
        "INFERENCE_TRANSFER_METADATA_RESOLVE"
    )
    status: Literal["SUCCESS", "FAILED"]
    actor_id: str | None = Field(pattern=r"^operator_[0-9a-f]{32}$")
    request_sha256: Sha256 | None
    result: InferenceTransferMetadataResolveResult | None
    error_code: InferenceTransferMetadataError | None

    @model_validator(mode="after")
    def closed_presence(self) -> InferenceTransferMetadataBindingReply:
        if (
            (self.status == "SUCCESS") != (self.result is not None)
            or (self.status == "FAILED") != (self.error_code is not None)
            or (self.actor_id is None) != (self.request_sha256 is None)
            or (self.status == "SUCCESS" and self.actor_id is None)
        ):
            raise ValueError("metadata binding reply presence differs")
        _bound(self)
        return self


def _parse[T: FrozenModel](value: object, cls: type[T]) -> T:
    if not isinstance(value, dict):
        raise ValueError("metadata contract must be a JSON object")
    validate_contract("item-inference-transfer-metadata", value)
    return cls.model_validate(value)


def parse_metadata_request(value: object) -> InferenceTransferMetadataResolveRequest:
    return _parse(value, InferenceTransferMetadataResolveRequest)


def parse_metadata_result(value: object) -> InferenceTransferMetadataResolveResult:
    return _parse(value, InferenceTransferMetadataResolveResult)


def parse_metadata_binding_request(value: object) -> InferenceTransferMetadataBindingRequest:
    return _parse(value, InferenceTransferMetadataBindingRequest)


def parse_metadata_binding_reply(value: object) -> InferenceTransferMetadataBindingReply:
    return _parse(value, InferenceTransferMetadataBindingReply)


def validate_metadata_result(
    request: InferenceTransferMetadataResolveRequest,
    result: InferenceTransferMetadataResolveResult,
) -> None:
    request = parse_metadata_request(request.model_dump(mode="json"))
    result = parse_metadata_result(result.model_dump(mode="json"))
    if (
        result.request_sha256 != request.request_sha256
        or result.graph_snapshot.graph_snapshot_revision_id != request.graph_snapshot_revision_id
        or result.snapshot_sha256 != request.expected_snapshot_sha256
        or result.access_policy_revision_id != request.access_policy_revision_id
        or result.access_policy_sha256 != request.access_policy_sha256
        or result.source_classes != request.source_classes
    ):
        raise ValueError("metadata result differs from the exact pinned request")


def validate_metadata_binding_reply(
    request: InferenceTransferMetadataBindingRequest,
    reply: InferenceTransferMetadataBindingReply,
) -> None:
    request = parse_metadata_binding_request(request.model_dump(mode="json"))
    reply = parse_metadata_binding_reply(reply.model_dump(mode="json"))
    if reply.actor_id != request.actor_id or reply.request_sha256 != request.request.request_sha256:
        raise ValueError("metadata private reply belongs to another request or principal")
    if reply.result is not None:
        validate_metadata_result(request.request, reply.result)
