"""Typed contracts for post-registration Item approval."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Self

from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_catalog_contracts.models import FrozenModel


class ItemRevisionApprovalPolicyV1(FrozenModel):
    mode: Literal["POST_REGISTRATION_HUMAN_REVIEW"] = "POST_REGISTRATION_HUMAN_REVIEW"
    initial_revision_state: Literal["IN_REVIEW"] = "IN_REVIEW"
    required_review_artifact: Literal["VALIDATED_HWPX"] = "VALIDATED_HWPX"


class ItemRevisionManifestContentPackV2(FrozenModel):
    release_id: str = Field(pattern=r"^packrel_[0-9a-f]{32}$")
    pack_key: str
    version: str
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ItemRevisionManifestSourceIntakeV2(FrozenModel):
    batch_ids: tuple[str, ...]


class ItemRevisionManifestWorkflowV2(FrozenModel):
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    definition_key: str
    definition_version: str


class ItemRevisionManifestComponentV2(FrozenModel):
    component_type: str
    ordinal: int = Field(ge=0)
    schema_ref: str
    media_type: str
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    logical_name: str
    required: bool


class ItemRevisionManifestMetadataV2(FrozenModel):
    schema_ref: str
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ItemRevisionManifestV2(FrozenModel):
    schema_version: Literal["2.0"] = "2.0"
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    revision_number: int = Field(ge=1)
    content_pack: ItemRevisionManifestContentPackV2
    source_intake: ItemRevisionManifestSourceIntakeV2
    workflow: ItemRevisionManifestWorkflowV2
    components: tuple[ItemRevisionManifestComponentV2, ...] = Field(min_length=1)
    metadata: ItemRevisionManifestMetadataV2
    provenance: tuple[dict[str, Any], ...]
    created_at: datetime
    revision_state: Literal["IN_REVIEW"] = "IN_REVIEW"
    approval_policy: ItemRevisionApprovalPolicyV1

    @model_validator(mode="after")
    def stable_collections(self) -> Self:
        if self.source_intake.batch_ids != tuple(sorted(set(self.source_intake.batch_ids))):
            raise ValueError("source intake batch IDs must be sorted and unique")
        positions = tuple((item.component_type, item.ordinal) for item in self.components)
        if positions != tuple(sorted(set(positions))):
            raise ValueError("Item manifest components must be sorted and unique")
        return self


class InspectItemRevisionHwpxEligibilityQueryV1(FrozenModel):
    operation: Literal["INSPECT_ITEM_REVISION_HWPX_ELIGIBILITY"] = (
        "INSPECT_ITEM_REVISION_HWPX_ELIGIBILITY"
    )
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")


class ItemRevisionHwpxEligibilityV1(FrozenModel):
    schema_version: Literal["item-revision-hwpx-eligibility/1.0"] = (
        "item-revision-hwpx-eligibility/1.0"
    )
    eligible: Literal[True] = True
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_revision_number: int = Field(ge=1)
    revision_state: Literal["IN_REVIEW"] = "IN_REVIEW"
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    workflow_definition_version: Literal["1.16.0"] = "1.16.0"
    manifest_artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    manifest_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    manifest_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    eligibility_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def exact_eligibility_hash(self) -> Self:
        body = self.model_dump(mode="json", exclude={"eligibility_sha256"})
        if content_sha256(body) != self.eligibility_sha256:
            raise ValueError("HWPX review eligibility hash differs")
        return self


class ApproveItemRevisionCommandV1(FrozenModel):
    operation: Literal["APPROVE_ITEM_REVISION"] = "APPROVE_ITEM_REVISION"
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    expected_revision_version: int = Field(ge=1)
    hwpx_build_id: str = Field(pattern=r"^hwpxbuild_[0-9a-f]{32}$")
    hwpx_output_artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    hwpx_output_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    hwpx_output_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=2000)
    approved_by: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    idempotency_key: str = Field(min_length=16, max_length=200)
    submission_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def exact_submission_hash(self) -> Self:
        body = self.model_dump(mode="json", exclude={"submission_sha256"})
        if content_sha256(body) != self.submission_sha256:
            raise ValueError("Item approval submission hash differs")
        return self


class ItemRevisionApprovalReceiptV1(FrozenModel):
    schema_version: Literal["item-revision-approval-receipt/1.0"] = (
        "item-revision-approval-receipt/1.0"
    )
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_revision_number: int = Field(ge=1)
    prior_revision_state: Literal["IN_REVIEW"] = "IN_REVIEW"
    approved_revision_state: Literal["APPROVED"] = "APPROVED"
    manifest_artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    manifest_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    manifest_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    registration_step_run_id: str = Field(pattern=r"^steprun_[0-9a-f]{32}$")
    hwpx_build_id: str = Field(pattern=r"^hwpxbuild_[0-9a-f]{32}$")
    hwpx_output_artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    hwpx_output_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    hwpx_output_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    approved_by: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    approved_at: datetime
    reason_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    idempotency_key: str = Field(min_length=16, max_length=200)
    approval_submission_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    receipt_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def exact_receipt_hash(self) -> Self:
        body = self.model_dump(mode="json", exclude={"receipt_sha256"})
        if content_sha256(body) != self.receipt_sha256:
            raise ValueError("Item approval receipt hash differs")
        return self
