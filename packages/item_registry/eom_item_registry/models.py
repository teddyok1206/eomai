"""Typed value contracts for deterministic registry operations."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RegistryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ItemRevisionApprovalMode(StrEnum):
    """Registration-time approval policy for one immutable Item Revision."""

    IMMEDIATE = "IMMEDIATE"
    POST_REGISTRATION_HUMAN_REVIEW = "POST_REGISTRATION_HUMAN_REVIEW"


class ComponentPointer(RegistryModel):
    component_type: Literal[
        "UPPER_STEM",
        "LOWER_STEM",
        "DATA",
        "TABLE",
        "IMAGE",
        "IMAGE_SPEC",
        "STATEMENTS",
        "CHOICES",
        "POINTS",
        "ANSWER",
        "AUTHORING_INTENT",
        "SOLUTION_OVERVIEW",
        "STATEMENT_EXPLANATIONS",
        "REVIEW_REPORT",
        "SOURCE_REFERENCE",
        "METADATA",
        "ITEM_CONTENT",
        "OTHER",
    ]
    ordinal: int = Field(ge=0, le=1000)
    schema_ref: str = Field(min_length=1, max_length=256)
    media_type: str = Field(pattern=r"^[a-z0-9.+-]+/[A-Za-z0-9.+-]+$")
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    logical_name: str = Field(min_length=1, max_length=128)
    required: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class PastExamVariationSourcePointer(RegistryModel):
    """Exact approved source revision used to derive one new 1:1 variation Item."""

    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    content_artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    content_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    content_schema_ref: str = Field(min_length=1, max_length=256)
    content_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    plan_id: str = Field(pattern=r"^execplan_[0-9a-f]{32}$")
    plan_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    evidence_bundle_revision_id: str = Field(pattern=r"^evidencerev_[0-9a-f]{32}$")
    evidence_manifest_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class RegistrationRequest(RegistryModel):
    mode: Literal["CREATE_ITEM", "REVISE_ITEM"]
    registration_key: str = Field(min_length=1, max_length=200)
    item_id: str | None = Field(default=None, pattern=r"^item_[0-9a-f]{32}$")
    base_revision_id: str | None = Field(default=None, pattern=r"^itemrev_[0-9a-f]{32}$")
    content_pack_release_id: str = Field(pattern=r"^packrel_[0-9a-f]{32}$")
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    workflow_definition_key: str = Field(min_length=1, max_length=128)
    workflow_definition_version: str = Field(min_length=1, max_length=32)
    source_workflow_step_run_id: str = Field(pattern=r"^steprun_[0-9a-f]{32}$")
    source_intake_batch_ids: tuple[Annotated[str, Field(pattern=r"^intake_[0-9a-f]{32}$")], ...]
    item_type_key: str = Field(min_length=1, max_length=128)
    primary_taxonomy_ref: str | None = Field(default=None, max_length=256)
    difficulty_band: str | None = Field(default=None, max_length=64)
    tag_keys: tuple[str, ...] = ()
    estimated_time_seconds: int | None = Field(default=None, ge=1, le=86400)
    metadata_schema_ref: str = Field(min_length=1, max_length=256)
    metadata: dict[str, Any]
    components: tuple[ComponentPointer, ...] = Field(min_length=1, max_length=100)
    past_exam_variation_source: PastExamVariationSourcePointer | None = None
    approval_mode: ItemRevisionApprovalMode = ItemRevisionApprovalMode.IMMEDIATE
    created_by: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

    @model_validator(mode="after")
    def variation_is_a_new_item(self) -> RegistrationRequest:
        if self.past_exam_variation_source is not None and self.mode != "CREATE_ITEM":
            raise ValueError("past-exam variation must create a new logical Item")
        if self.approval_mode == ItemRevisionApprovalMode.POST_REGISTRATION_HUMAN_REVIEW and (
            (self.workflow_definition_key, self.workflow_definition_version)
            != ("generic-item-development", "1.16.0")
            or self.mode != "CREATE_ITEM"
            or self.item_id is not None
            or self.base_revision_id is not None
        ):
            raise ValueError(
                "post-registration approval requires a new Item from workflow definition 1.16"
            )
        return self
