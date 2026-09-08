"""Graph-pinned item-bank read models."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from eom_api_contracts.common import ApiModel


class ItemBankCurriculumUnitView(ApiModel):
    curriculum_unit_id: str = Field(pattern=r"^currunit_[0-9a-f]{32}$")
    unit_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,191}$")
    unit_code: str = Field(min_length=1, max_length=32)
    label: str = Field(min_length=1, max_length=200)
    unit_level: Literal["MAJOR", "MIDDLE", "MINOR", "ACHIEVEMENT_STANDARD"]
    parent_unit_id: str | None = Field(default=None, pattern=r"^currunit_[0-9a-f]{32}$")


class ItemBankEntryView(ApiModel):
    """One immutable Item placement in a pinned published Graph snapshot."""

    schema_version: Literal["item-bank-entry-view/1.0"] = "item-bank-entry-view/1.0"
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    snapshot_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    graph_placement_node_id: str = Field(pattern=r"^knode_[0-9a-f]{32}$")
    assessment_occurrence_id: str = Field(pattern=r"^occurrence_[0-9a-f]{32}$")
    assessment_occurrence_revision_id: str = Field(pattern=r"^occurrev_[0-9a-f]{32}$")
    assessment_occurrence_revision_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    occurrence_display_label: str = Field(min_length=1, max_length=512)
    administration_year: int = Field(ge=1900, le=2200)
    administration_month: int = Field(ge=1, le=12)
    target_school_level: Literal["ELEMENTARY", "MIDDLE_SCHOOL", "HIGH_SCHOOL"]
    target_grade: int = Field(ge=1, le=6)
    subject_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,159}$")
    item_number: int = Field(ge=1, le=200)
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_revision_state: Literal["APPROVED", "SUPERSEDED"]
    item_type_key: str = Field(min_length=1, max_length=128)
    difficulty_band: str | None = Field(default=None, min_length=1, max_length=64)
    item_manifest_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    curriculum_units: tuple[ItemBankCurriculumUnitView, ...] = Field(min_length=1, max_length=8)
    placement_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def exact_graph_item(self) -> Self:
        unit_keys = tuple(unit.unit_key for unit in self.curriculum_units)
        unit_ids = tuple(unit.curriculum_unit_id for unit in self.curriculum_units)
        if unit_keys != tuple(sorted(set(unit_keys))) or len(unit_ids) != len(set(unit_ids)):
            raise ValueError("item-bank curriculum units must be sorted and unique")
        if (
            self.target_school_level == "HIGH_SCHOOL"
            and self.target_grade == 1
            and self.administration_month == 3
        ):
            raise ValueError("high-school grade 1 March evidence is not learnable")
        return self


class ProductionItemContentComponentView(ApiModel):
    """Exact canonical content pointer used to determine structural production capability."""

    item_component_id: str = Field(pattern=r"^itemcomponent_[0-9a-f]{32}$")
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    schema_ref: str = Field(min_length=1, max_length=256)
    media_type: str = Field(pattern=r"^[a-z0-9.+-]+/[A-Za-z0-9.+-]+(?:;[A-Za-z0-9=._+ -]+)?$")
    logical_name: str = Field(min_length=1, max_length=128)
    editorial_markdown_member: Literal["content-team-item.md"] | None = None
    editorial_markdown_sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def editorial_pointer_is_complete(self) -> Self:
        if (self.editorial_markdown_member is None) != (self.editorial_markdown_sha256 is None):
            raise ValueError("content-team editorial Markdown pointer must be complete or absent")
        return self


class ProductionPastExamContextView(ApiModel):
    """Typed past-exam placement attached only to a past-exam production candidate."""

    graph_placement_node_id: str = Field(pattern=r"^knode_[0-9a-f]{32}$")
    assessment_occurrence_id: str = Field(pattern=r"^occurrence_[0-9a-f]{32}$")
    assessment_occurrence_revision_id: str = Field(pattern=r"^occurrev_[0-9a-f]{32}$")
    assessment_occurrence_revision_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    occurrence_display_label: str = Field(min_length=1, max_length=512)
    administration_year: int = Field(ge=1900, le=2200)
    administration_month: int = Field(ge=1, le=12)
    target_school_level: Literal["ELEMENTARY", "MIDDLE_SCHOOL", "HIGH_SCHOOL"]
    target_grade: int = Field(ge=1, le=6)
    subject_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,159}$")
    item_number: int = Field(ge=1, le=200)
    placement_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def excludes_middle_school_march_scope(self) -> Self:
        if (
            self.target_school_level == "HIGH_SCHOOL"
            and self.target_grade == 1
            and self.administration_month == 3
        ):
            raise ValueError("high-school grade 1 March evidence is not learnable")
        return self


ProductionIneligibilityReason = Literal[
    "CONTENT_TEAM_EDITORIAL_MARKDOWN_POINTER_REQUIRED",
    "CONTENT_TEAM_ITEM_V2_REQUIRED",
    "ITEM_CONTENT_COMPONENT_MISSING",
    "ITEM_CONTENT_SCHEMA_UNSUPPORTED",
    "ITEM_NOT_ACTIVE",
    "ITEM_REVISION_NOT_ELIGIBLE",
]
ProductionContentProfile = Literal[
    "LEGACY_ITEM_CONTENT_V1",
    "CONTENT_TEAM_ITEM_CONTENT_V2",
    "UNSUPPORTED",
]


class ProductionItemCandidateView(ApiModel):
    """One Graph-pinned approved Item with an honest structural production capability."""

    schema_version: Literal["production-item-candidate-view/1.0"] = (
        "production-item-candidate-view/1.0"
    )
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    snapshot_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    graph_item_node_id: str = Field(pattern=r"^knode_[0-9a-f]{32}$")
    source_class: Literal["APPROVED_ITEM", "PAST_EXAM"]
    source_display_label: str = Field(min_length=1, max_length=512)
    past_exam_context: ProductionPastExamContextView | None
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_revision_state: Literal[
        "DRAFT", "IN_REVIEW", "APPROVED", "REJECTED", "SUPERSEDED", "RETIRED"
    ]
    item_lifecycle_state: Literal["DRAFT", "ACTIVE", "RETIRED", "DELETED_SOFT"]
    item_current_revision: bool
    item_type_key: str = Field(min_length=1, max_length=128)
    difficulty_band: str | None = Field(default=None, min_length=1, max_length=64)
    item_manifest_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    curriculum_units: tuple[ItemBankCurriculumUnitView, ...] = Field(min_length=1, max_length=8)
    content_profile: Literal[
        "LEGACY_ITEM_CONTENT_V1", "CONTENT_TEAM_ITEM_CONTENT_V2", "UNSUPPORTED"
    ]
    content_component: ProductionItemContentComponentView | None
    mock_exam_assembly_eligible: bool
    hwpx_exam_eligible: bool
    ineligibility_reasons: tuple[ProductionIneligibilityReason, ...] = Field(max_length=6)

    @model_validator(mode="after")
    def closed_production_capability(self) -> Self:
        unit_keys = tuple(unit.unit_key for unit in self.curriculum_units)
        unit_ids = tuple(unit.curriculum_unit_id for unit in self.curriculum_units)
        if unit_keys != tuple(sorted(set(unit_keys))) or len(unit_ids) != len(set(unit_ids)):
            raise ValueError("production candidate curriculum units must be sorted and unique")
        if (self.source_class == "PAST_EXAM") != (self.past_exam_context is not None):
            raise ValueError("production candidate source class and past-exam context differ")
        if self.ineligibility_reasons != tuple(sorted(set(self.ineligibility_reasons))):
            raise ValueError("production ineligibility reasons must be sorted and unique")

        reasons: list[ProductionIneligibilityReason] = []
        if self.item_lifecycle_state != "ACTIVE":
            reasons.append("ITEM_NOT_ACTIVE")
        if self.item_revision_state not in {"APPROVED", "SUPERSEDED"}:
            reasons.append("ITEM_REVISION_NOT_ELIGIBLE")
        component = self.content_component
        if component is None:
            reasons.append("ITEM_CONTENT_COMPONENT_MISSING")
            if self.content_profile != "UNSUPPORTED":
                raise ValueError("missing content component must use unsupported profile")
        elif self.content_profile == "LEGACY_ITEM_CONTENT_V1":
            if component.media_type != "application/json" or component.schema_ref not in {
                "eom.assessment.item-content/1.0",
                "eom://schemas/item-registry/assessment-item-content-v1",
            }:
                raise ValueError("legacy content profile differs from its component schema")
            reasons.append("CONTENT_TEAM_ITEM_V2_REQUIRED")
        elif self.content_profile == "CONTENT_TEAM_ITEM_CONTENT_V2":
            if component.media_type != "application/json" or component.schema_ref not in {
                "eom.assessment.item-content/2.0",
                "eom://schemas/item-registry/assessment-item-content-v2",
            }:
                raise ValueError("content-team profile differs from its component schema")
            if component.editorial_markdown_member is None:
                reasons.append("CONTENT_TEAM_EDITORIAL_MARKDOWN_POINTER_REQUIRED")
        else:
            reasons.append("ITEM_CONTENT_SCHEMA_UNSUPPORTED")

        expected = tuple(sorted(reasons))
        eligible = not expected
        if (
            self.ineligibility_reasons != expected
            or self.mock_exam_assembly_eligible != eligible
            or self.hwpx_exam_eligible != eligible
        ):
            raise ValueError("production eligibility differs from structural Item capability")
        return self


class ProductionItemContentComponentViewV2(ProductionItemContentComponentView):
    """V2 projection adds the pinned editorial-Markdown protocol identity."""

    editorial_markdown_schema_ref: (
        Literal["eom://schemas/hwpx/content-team-editorial-markdown/2.0"] | None
    )

    @model_validator(mode="after")
    def editorial_schema_requires_pointer(self) -> Self:
        if (
            self.editorial_markdown_schema_ref is not None
            and self.editorial_markdown_member is None
        ):
            raise ValueError("editorial Markdown schema cannot exist without its artifact pointer")
        return self


ProductionContentProfileV2 = Literal[
    "LEGACY_ITEM_CONTENT_V1",
    "CONTENT_TEAM_ITEM_CONTENT_V2",
    "CONTENT_TEAM_ITEM_CONTENT_V3",
    "UNSUPPORTED",
]


class ProductionItemCandidateViewV2(ProductionItemCandidateView):
    """Additive production projection for graph-grounded Item Content V3."""

    schema_version: Literal["production-item-candidate-view/2.0"] = (
        "production-item-candidate-view/2.0"  # type: ignore[assignment]
    )
    content_profile: Literal["CONTENT_TEAM_ITEM_CONTENT_V3"]  # type: ignore[assignment]
    content_component: ProductionItemContentComponentViewV2

    @model_validator(mode="after")
    def closed_production_capability(self) -> Self:
        unit_keys = tuple(unit.unit_key for unit in self.curriculum_units)
        unit_ids = tuple(unit.curriculum_unit_id for unit in self.curriculum_units)
        if unit_keys != tuple(sorted(set(unit_keys))) or len(unit_ids) != len(set(unit_ids)):
            raise ValueError("production candidate curriculum units must be sorted and unique")
        if (self.source_class == "PAST_EXAM") != (self.past_exam_context is not None):
            raise ValueError("production candidate source class and past-exam context differ")
        if self.ineligibility_reasons != tuple(sorted(set(self.ineligibility_reasons))):
            raise ValueError("production ineligibility reasons must be sorted and unique")

        reasons: list[ProductionIneligibilityReason] = []
        if self.item_lifecycle_state != "ACTIVE":
            reasons.append("ITEM_NOT_ACTIVE")
        if self.item_revision_state not in {"APPROVED", "SUPERSEDED"}:
            reasons.append("ITEM_REVISION_NOT_ELIGIBLE")
        component = self.content_component
        if component.media_type != "application/json" or component.schema_ref not in {
            "eom.assessment.item-content/3.0",
            "eom://schemas/item-registry/assessment-item-content-v3",
        }:
            raise ValueError("content-team profile differs from its component schema")
        if (
            component.editorial_markdown_member is None
            or component.editorial_markdown_schema_ref
            != "eom://schemas/hwpx/content-team-editorial-markdown/2.0"
        ):
            reasons.append("CONTENT_TEAM_EDITORIAL_MARKDOWN_POINTER_REQUIRED")

        expected = tuple(sorted(reasons))
        eligible = not expected
        if (
            self.ineligibility_reasons != expected
            or self.mock_exam_assembly_eligible != eligible
            or self.hwpx_exam_eligible != eligible
        ):
            raise ValueError("production eligibility differs from structural Item capability")
        return self


ProductionItemCandidateViewContract = Annotated[
    ProductionItemCandidateView | ProductionItemCandidateViewV2,
    Field(discriminator="schema_version"),
]
