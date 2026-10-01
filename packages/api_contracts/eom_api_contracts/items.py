"""Item Registry query DTOs."""

from __future__ import annotations

from typing import Literal

from eom_catalog_contracts import AssessmentItemContentContract
from pydantic import Field, model_validator

from eom_api_contracts.common import ApiModel, ArtifactPointer, OpaqueId, UtcDatetime


class ItemApprovalView(ApiModel):
    schema_version: Literal["item-approval-view/1.0"] = "item-approval-view/1.0"
    status: Literal["PENDING", "APPROVED", "REJECTED", "SUPERSEDED", "RETIRED"]
    human_review_required: bool
    approved_at: UtcDatetime | None = None
    approved_by: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    approval_receipt_sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    hwpx_build_id: str | None = Field(default=None, pattern=r"^hwpxbuild_[0-9a-f]{32}$")

    @model_validator(mode="after")
    def exact_human_approval_evidence(self) -> ItemApprovalView:
        evidence = (
            self.approved_at,
            self.approved_by,
            self.approval_receipt_sha256,
            self.hwpx_build_id,
        )
        if self.status == "PENDING" and any(value is not None for value in evidence):
            raise ValueError("pending Item approval must not carry approval evidence")
        if (
            self.status in {"APPROVED", "SUPERSEDED", "RETIRED"}
            and self.human_review_required
            and any(value is None for value in evidence)
        ):
            raise ValueError("human-reviewed approval requires exact receipt and HWPX evidence")
        return self


class ItemView(ApiModel):
    item_id: OpaqueId
    human_reference_code: str | None = None
    lifecycle_state: str
    current_revision_id: OpaqueId | None = None
    resource_version: int = Field(ge=1)
    created_at: UtcDatetime
    approval: ItemApprovalView | None = None


class ItemRevisionApprovalRequest(ApiModel):
    schema_version: Literal["item-revision-approval-request/1.0"] = (
        "item-revision-approval-request/1.0"
    )
    hwpx_build_id: str = Field(pattern=r"^hwpxbuild_[0-9a-f]{32}$")
    reason: str = Field(min_length=1, max_length=2000)


class ItemRevisionView(ApiModel):
    item_revision_id: OpaqueId
    item_id: OpaqueId
    revision_number: int = Field(ge=1)
    revision_state: str
    content_pack_release_id: OpaqueId
    workflow_id: OpaqueId
    item_type_key: str
    manifest: ArtifactPointer
    resource_version: int = Field(ge=1)
    created_at: UtcDatetime
    approval: ItemApprovalView


class ItemComponentView(ApiModel):
    item_component_id: OpaqueId
    item_revision_id: OpaqueId
    component_type: str
    ordinal: int = Field(ge=0)
    logical_name: str
    required: bool
    artifact: ArtifactPointer


class ItemRelationshipView(ApiModel):
    item_relationship_id: OpaqueId
    source_item_id: OpaqueId
    target_item_id: OpaqueId
    relationship_type: str
    created_at: UtcDatetime


class ItemRetirementRequest(ApiModel):
    reason: str = Field(min_length=1, max_length=1000)


class StructuredItemContentImportRequest(ApiModel):
    """Explicitly reviewed import of one canonical content snapshot."""

    reviewed: Literal[True]
    review_reason: str = Field(min_length=10, max_length=2000)
    content: AssessmentItemContentContract
