"""Read-only curriculum capability projections."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from eom_api_contracts.common import ApiModel, Sha256


class CurriculumGraphCapabilityView(ApiModel):
    schema_version: Literal["curriculum-graph-capability/1.0"] = "curriculum-graph-capability/1.0"
    corpus_key: Literal["integrated-science-textbooks"] = "integrated-science-textbooks"
    outline_key: Literal["eom-integrated-science-editorial-outline"] = (
        "eom-integrated-science-editorial-outline"
    )
    outline_revision: Literal["1.0"] = "1.0"
    outline_sha256: Sha256
    capability_state: Literal["READY", "UNAVAILABLE"]
    graph_grounding_available: bool
    reason: Literal[
        "READY",
        "CORPUS_UNAVAILABLE",
        "SNAPSHOT_UNAVAILABLE",
        "CURRICULUM_MAPPING_INCOMPLETE",
        "CURRENT_POINTER_CHANGED",
    ]
    graph_snapshot_revision_id: str | None = Field(default=None, pattern=r"^graphrev_[0-9a-f]{32}$")
    snapshot_sha256: Sha256 | None = None
    framework_revision_id: str | None = Field(default=None, pattern=r"^curriculumrev_[0-9a-f]{32}$")
    unit_count: int = Field(ge=0, le=100_000)
    closure_count: int = Field(ge=0, le=1_000_000)

    @model_validator(mode="after")
    def exact_ready_or_closed_unavailable(self) -> Self:
        pointers = (
            self.graph_snapshot_revision_id,
            self.snapshot_sha256,
            self.framework_revision_id,
        )
        if self.capability_state == "READY":
            if (
                not self.graph_grounding_available
                or self.reason != "READY"
                or any(pointer is None for pointer in pointers)
                or self.unit_count != 43
                or self.closure_count != 119
            ):
                raise ValueError("READY curriculum capability requires exact published pointers")
        elif (
            self.graph_grounding_available
            or self.reason == "READY"
            or any(pointer is not None for pointer in pointers)
        ):
            raise ValueError("unavailable curriculum capability must fail closed")
        return self


class AssessmentItemOccurrenceView(ApiModel):
    """One immutable past-examination placement in the current Graph snapshot."""

    schema_version: Literal["assessment-item-occurrence-view/1.0"] = (
        "assessment-item-occurrence-view/1.0"
    )
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    placement_node_id: str = Field(pattern=r"^knode_[0-9a-f]{64}$")
    occurrence_node_id: str = Field(pattern=r"^knode_[0-9a-f]{64}$")
    item_node_id: str = Field(pattern=r"^knode_[0-9a-f]{64}$")
    analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    assessment_occurrence_id: str = Field(pattern=r"^occurrence_[0-9a-f]{32}$")
    assessment_occurrence_revision_id: str = Field(pattern=r"^occurrev_[0-9a-f]{32}$")
    assessment_occurrence_revision_sha256: Sha256
    occurrence_display_label: str = Field(min_length=1, max_length=512)
    administration_year: int = Field(ge=1900, le=2200)
    administration_month: int = Field(ge=1, le=12)
    target_school_level: Literal["ELEMENTARY", "MIDDLE_SCHOOL", "HIGH_SCHOOL"]
    target_grade: int = Field(ge=1, le=6)
    subject_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,159}$")
    item_number: int = Field(ge=1, le=200)
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    curriculum_unit_ids: tuple[Annotated[str, Field(pattern=r"^currunit_[0-9a-f]{32}$")], ...] = (
        Field(min_length=1, max_length=8)
    )
    placement_sha256: Sha256

    @model_validator(mode="after")
    def closed_placement(self) -> Self:
        if tuple(sorted(set(self.curriculum_unit_ids))) != self.curriculum_unit_ids:
            raise ValueError("curriculum unit IDs must be sorted and unique")
        if (
            self.target_school_level == "HIGH_SCHOOL"
            and self.target_grade == 1
            and self.administration_month == 3
        ):
            raise ValueError("high-school grade 1 March evidence is not learnable")
        return self
