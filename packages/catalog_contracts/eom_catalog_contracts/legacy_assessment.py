"""Immutable contracts for extracting legacy assessment items from reviewed source bundles."""

from __future__ import annotations

import re
from collections.abc import Hashable
from datetime import date
from typing import Annotated, Literal

from eom_identifiers import content_sha256
from pydantic import Field, field_validator, model_validator

from eom_catalog_contracts.assessment_item import AssessmentItemContent
from eom_catalog_contracts.item_origin import (
    AssessmentOccurrencePointer,
    OriginArtifactMemberPointer,
    RightsPolicyPointer,
)
from eom_catalog_contracts.models import ActorId, FrozenModel, Sha256, UtcDatetime, _safe_text

SafeKey = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,159}$")]
SourceRole = Literal[
    "PROBLEM_DOCUMENT",
    "ANSWER_EXPLANATION_DOCUMENT",
    "STRUCTURED_RECONSTRUCTION",
    "ITEM_CLASSIFICATION_WORKBOOK",
    "TYPE_CODE_REFERENCE",
    "OTHER_REVIEWED_EVIDENCE",
]
AnchorId = Annotated[str, Field(pattern=r"^assessmentanchor_[0-9a-f]{32}$")]
_ASSESSMENT_PAGE_ID = re.compile(r"^assessmentpage_[0-9a-f]{32}$")
_LEGACY_ENTRY_ID = re.compile(r"^legacyentry_[0-9a-f]{32}$")
MAX_ASSESSMENT_IMAGE_PIXELS = 64_000_000
MAX_ASSESSMENT_IMAGE_TOTAL_PIXELS = 256_000_000


def _require_self_hash(model: FrozenModel, field_name: str) -> None:
    expected = content_sha256(model.model_dump(mode="json", exclude={field_name}))
    if getattr(model, field_name) != expected:
        raise ValueError(f"{field_name} does not match canonical content")


def _unique[HashableValue: Hashable](values: tuple[HashableValue, ...], message: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(message)


class AssessmentArtifactMemberPointer(OriginArtifactMemberPointer):
    """Compatibility name for the shared origin Artifact member pointer."""


class AssessmentInventoryEntryPointer(FrozenModel):
    inventory_id: str = Field(pattern=r"^legacyinventory_[0-9a-f]{32}$")
    inventory_sha256: Sha256
    entry_key: str = Field(pattern=r"^legacyentry_[0-9a-f]{32}$")
    content_sha256: Sha256


class AssessmentRightsPolicyPointer(RightsPolicyPointer):
    """Compatibility name for the shared origin Rights Policy pointer."""


class AssessmentSourceBundlePointer(FrozenModel):
    assessment_source_bundle_id: str = Field(pattern=r"^assessbundle_[0-9a-f]{32}$")
    assessment_source_bundle_revision_id: str = Field(pattern=r"^assessbundlerev_[0-9a-f]{32}$")
    bundle_manifest_sha256: Sha256


class NormalizedBoundingBox(FrozenModel):
    left: int = Field(ge=0, le=9999)
    top: int = Field(ge=0, le=9999)
    right: int = Field(ge=1, le=10000)
    bottom: int = Field(ge=1, le=10000)

    @model_validator(mode="after")
    def ordered_coordinates(self) -> NormalizedBoundingBox:
        if self.right <= self.left or self.bottom <= self.top:
            raise ValueError("normalized bounding box must have positive area")
        return self


class AssessmentSourceAnchor(FrozenModel):
    anchor_id: AnchorId
    source: AssessmentArtifactMemberPointer
    source_role: SourceRole
    physical_page: int | None = Field(default=None, ge=1, le=100000)
    bounding_box: NormalizedBoundingBox | None
    locator_detail: str = Field(min_length=1, max_length=256)

    _text = field_validator("locator_detail")(_safe_text)

    @model_validator(mode="after")
    def coherent_page_locator(self) -> AssessmentSourceAnchor:
        if self.bounding_box is not None and self.physical_page is None:
            raise ValueError("bounded source anchor requires a physical page")
        if self.source_role in {"PROBLEM_DOCUMENT", "ANSWER_EXPLANATION_DOCUMENT"} and (
            self.physical_page is None
        ):
            raise ValueError("problem and answer source anchors require a physical page")
        return self


class AssessmentConflictObservation(FrozenModel):
    conflict_id: str = Field(pattern=r"^assessmentconflict_[0-9a-f]{32}$")
    field_path: str = Field(pattern=r"^[A-Za-z0-9_][A-Za-z0-9_.\[\]-]{0,255}$")
    conflict_kind: Literal[
        "SOURCE_DISAGREEMENT",
        "MISSING_SOURCE",
        "AMBIGUOUS_LAYOUT",
        "UNRESOLVED_OCCURRENCE",
        "UNRESOLVED_CURRICULUM",
        "UNREADABLE_CONTENT",
        "UNSUPPORTED_STRUCTURE",
        "OTHER_REVIEWED",
    ]
    source_anchor_ids: tuple[AnchorId, ...] = Field(min_length=1, max_length=32)
    description: str = Field(min_length=1, max_length=2000)
    blocking: bool

    _text = field_validator("description")(_safe_text)

    @model_validator(mode="after")
    def unique_anchor_ids(self) -> AssessmentConflictObservation:
        _unique(self.source_anchor_ids, "conflict source anchor IDs must be unique")
        return self


class AssessmentBundleConflictObservation(FrozenModel):
    conflict_id: str = Field(pattern=r"^assessmentconflict_[0-9a-f]{32}$")
    field_path: str = Field(pattern=r"^[A-Za-z0-9_][A-Za-z0-9_.\[\]-]{0,255}$")
    conflict_kind: Literal[
        "SOURCE_DISAGREEMENT",
        "MISSING_SOURCE",
        "AMBIGUOUS_BUNDLE",
        "UNRESOLVED_OCCURRENCE",
        "UNSUPPORTED_MEDIA",
        "OTHER_REVIEWED",
    ]
    source_entry_keys: tuple[str, ...] = Field(min_length=1, max_length=32)
    description: str = Field(min_length=1, max_length=2000)
    blocking: bool

    _text = field_validator("description")(_safe_text)

    @field_validator("source_entry_keys")
    @classmethod
    def valid_source_entry_keys(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(_LEGACY_ENTRY_ID.fullmatch(entry) is None for entry in value):
            raise ValueError("bundle conflict source entry key is invalid")
        _unique(value, "bundle conflict source entry keys must be unique")
        return value


class AssessmentCurriculumObservation(FrozenModel):
    observation_id: str = Field(pattern=r"^curriculumobservation_[0-9a-f]{32}$")
    observed_code: str | None = Field(default=None, max_length=128)
    observed_label: str = Field(min_length=1, max_length=256)
    resolved_unit_key: SafeKey | None
    source_anchor_ids: tuple[AnchorId, ...] = Field(min_length=1, max_length=32)
    confidence_milli: int = Field(ge=0, le=1000)

    _text = field_validator("observed_code", "observed_label")(
        lambda value: None if value is None else _safe_text(value)
    )

    @model_validator(mode="after")
    def unique_anchor_ids(self) -> AssessmentCurriculumObservation:
        _unique(self.source_anchor_ids, "curriculum source anchor IDs must be unique")
        return self


class AssessmentLinguisticPatternObservation(FrozenModel):
    pattern_id: str = Field(pattern=r"^linguisticpattern_[0-9a-f]{32}$")
    prompt_form: Literal[
        "SELECT_CORRECT",
        "SELECT_INCORRECT",
        "SELECT_MOST_APPROPRIATE",
        "SELECT_COMBINATION",
        "CALCULATE",
        "INFER",
        "MATCH",
        "ORDER",
        "CONSTRUCT_RESPONSE",
        "OTHER_OBSERVED",
    ]
    polarity: Literal["POSITIVE", "NEGATIVE", "MIXED", "NOT_APPLICABLE"]
    condition_placement: Literal["BEFORE_STEM", "INLINE", "AFTER_STEM", "MIXED", "NONE"]
    choice_grammar: Literal[
        "COMPLETE_SENTENCE",
        "NOUN_PHRASE",
        "NUMERIC_OR_SYMBOLIC",
        "STATEMENT_COMBINATION",
        "MIXED",
        "NOT_APPLICABLE",
    ]
    uses_statement_set: bool
    closing_expression: str = Field(min_length=1, max_length=200)
    structure_summary: str = Field(min_length=1, max_length=2000)
    reusable_pattern: str = Field(min_length=1, max_length=2000)
    source_anchor_ids: tuple[AnchorId, ...] = Field(min_length=1, max_length=32)

    _text = field_validator("closing_expression", "structure_summary", "reusable_pattern")(
        _safe_text
    )

    @model_validator(mode="after")
    def coherent_statement_interaction(self) -> AssessmentLinguisticPatternObservation:
        _unique(self.source_anchor_ids, "linguistic source anchor IDs must be unique")
        if self.uses_statement_set and self.choice_grammar != "STATEMENT_COMBINATION":
            raise ValueError("statement-set pattern requires statement-combination choices")
        if self.prompt_form == "SELECT_COMBINATION" and not self.uses_statement_set:
            raise ValueError("combination prompt requires a statement set")
        return self


class AssessmentVisualPatternObservation(FrozenModel):
    pattern_id: str = Field(pattern=r"^visualpattern_[0-9a-f]{32}$")
    representation_kind: Literal[
        "NONE",
        "TABLE",
        "LINE_GRAPH",
        "BAR_GRAPH",
        "SCATTER_PLOT",
        "DIAGRAM",
        "PARTICLE_MODEL",
        "APPARATUS",
        "MAP",
        "CROSS_SECTION",
        "TIMELINE",
        "FLOW",
        "PHOTOGRAPH",
        "COMPOSITE",
        "OTHER_OBSERVED",
    ]
    rendering_mode: Literal["VECTOR_LIKE", "RASTER", "MIXED", "TEXT_ONLY"]
    color_mode: Literal["MONOCHROME", "GRAYSCALE", "LIMITED_COLOR", "FULL_COLOR"]
    background: Literal["WHITE", "TRANSPARENT", "OTHER_OBSERVED"]
    panel_layout: Literal["SINGLE", "HORIZONTAL", "VERTICAL", "GRID", "OVERLAID", "NONE"]
    features: tuple[
        Literal[
            "AXES",
            "GRID",
            "LEGEND",
            "ARROWS",
            "LEADER_LINES",
            "LABELS",
            "SCALE",
            "PATTERN_FILL",
            "SYMBOL_KEY",
            "NUMBERED_STEPS",
            "MULTIPLE_PANELS",
            "CALLOUT",
            "BOUNDARY",
            "TRAJECTORY",
            "DATA_POINTS",
            "ERROR_BAR",
        ],
        ...,
    ] = Field(max_length=24)
    pedagogical_function: Literal[
        "PRIMARY_DATA",
        "CONTEXT",
        "COMPARISON",
        "PROCESS",
        "SPATIAL_RELATION",
        "CLASSIFICATION",
        "DECORATIVE",
        "OTHER_OBSERVED",
    ]
    composition_summary: str = Field(min_length=1, max_length=3000)
    reconstruction_guidance: str = Field(min_length=1, max_length=3000)
    source_anchor_ids: tuple[AnchorId, ...] = Field(min_length=1, max_length=32)

    _text = field_validator("composition_summary", "reconstruction_guidance")(_safe_text)

    @model_validator(mode="after")
    def coherent_visual_pattern(self) -> AssessmentVisualPatternObservation:
        _unique(self.features, "visual features must be unique")
        _unique(self.source_anchor_ids, "visual source anchor IDs must be unique")
        if self.representation_kind == "NONE" and (
            self.rendering_mode != "TEXT_ONLY" or self.panel_layout != "NONE" or self.features
        ):
            raise ValueError("empty visual pattern cannot declare rendered visual features")
        return self


class AssessmentPageImageInput(FrozenModel):
    page_input_id: str = Field(pattern=r"^assessmentpage_[0-9a-f]{32}$")
    source_role: Literal["PROBLEM_DOCUMENT", "ANSWER_EXPLANATION_DOCUMENT"]
    physical_page: int = Field(ge=1, le=100000)
    source: AssessmentArtifactMemberPointer
    image: AssessmentArtifactMemberPointer
    workspace_relative_path: str = Field(pattern=r"^source/pages/assessmentpage_[0-9a-f]{32}\.png$")
    width_px: int = Field(ge=1, le=20000)
    height_px: int = Field(ge=1, le=20000)

    @model_validator(mode="after")
    def image_media_type(self) -> AssessmentPageImageInput:
        if self.image.media_type != "image/png":
            raise ValueError("assessment page image must be a PNG")
        if self.width_px * self.height_px > MAX_ASSESSMENT_IMAGE_PIXELS:
            raise ValueError("assessment page image exceeds the decoded-pixel limit")
        expected_path = f"source/pages/{self.page_input_id}.png"
        if self.workspace_relative_path != expected_path:
            raise ValueError("assessment page image path must be derived from its page input ID")
        return self


class AssessmentBundleProposalMember(FrozenModel):
    source: AssessmentInventoryEntryPointer
    proposed_role: SourceRole
    pairing_reason_codes: tuple[
        Literal[
            "EXACT_OCCURRENCE_TOKEN",
            "EXACT_SUBJECT_TOKEN",
            "EXACT_DATE_TOKEN",
            "EXACT_DOCUMENT_ROLE_TOKEN",
            "SAME_REVIEWED_DIRECTORY",
            "WORKBOOK_INTERNAL_IDENTITY",
            "EXACT_CONTENT_HASH",
            "MANUAL_RELATION_EVIDENCE",
        ],
        ...,
    ] = Field(min_length=1, max_length=16)
    confidence_milli: int = Field(ge=0, le=1000)

    @model_validator(mode="after")
    def unique_reason_codes(self) -> AssessmentBundleProposalMember:
        _unique(self.pairing_reason_codes, "pairing reason codes must be unique")
        return self


class AssessmentOccurrenceObservation(FrozenModel):
    organization_label: str | None = Field(default=None, max_length=256)
    exam_family_label: str = Field(min_length=1, max_length=256)
    administration_year: int | None = Field(default=None, ge=1900, le=2200)
    administration_date: date | None
    session_label: str | None = Field(default=None, max_length=128)
    subject_label: str = Field(min_length=1, max_length=128)
    form_label: str | None = Field(default=None, max_length=128)
    source_entry_keys: tuple[str, ...] = Field(min_length=1, max_length=32)

    _text = field_validator(
        "organization_label", "exam_family_label", "session_label", "subject_label", "form_label"
    )(lambda value: None if value is None else _safe_text(value))

    @field_validator("source_entry_keys")
    @classmethod
    def valid_source_entry_keys(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(_LEGACY_ENTRY_ID.fullmatch(entry) is None for entry in value):
            raise ValueError("occurrence source entry key is invalid")
        _unique(value, "occurrence source entry keys must be unique")
        return value


class AssessmentSourceBundleProposal(FrozenModel):
    schema_version: Literal["assessment-source-bundle-proposal/1.0"]
    proposal_id: str = Field(pattern=r"^assessbundleproposal_[0-9a-f]{32}$")
    inventory_id: str = Field(pattern=r"^legacyinventory_[0-9a-f]{32}$")
    inventory_sha256: Sha256
    candidate_key: SafeKey
    members: tuple[AssessmentBundleProposalMember, ...] = Field(min_length=1, max_length=32)
    occurrence_observation: AssessmentOccurrenceObservation
    conflicts: tuple[AssessmentBundleConflictObservation, ...] = Field(max_length=64)
    created_at: UtcDatetime
    proposal_sha256: Sha256

    @model_validator(mode="after")
    def coherent_proposal(self) -> AssessmentSourceBundleProposal:
        entries = tuple(member.source.entry_key for member in self.members)
        _unique(entries, "bundle proposal source entries must be unique")
        for member in self.members:
            if (member.source.inventory_id, member.source.inventory_sha256) != (
                self.inventory_id,
                self.inventory_sha256,
            ):
                raise ValueError("bundle proposal member inventory pointer is inconsistent")
        if not set(self.occurrence_observation.source_entry_keys).issubset(entries):
            raise ValueError("occurrence observation points outside bundle proposal members")
        if any(
            not set(conflict.source_entry_keys).issubset(entries) for conflict in self.conflicts
        ):
            raise ValueError("bundle conflict points outside bundle proposal members")
        _require_self_hash(self, "proposal_sha256")
        return self


class AssessmentSourceBundleMember(FrozenModel):
    member_id: str = Field(pattern=r"^assessbundlemember_[0-9a-f]{32}$")
    role: SourceRole
    source: AssessmentArtifactMemberPointer
    inventory_source: AssessmentInventoryEntryPointer


class AssessmentSourceBundleRevision(FrozenModel):
    schema_version: Literal["assessment-source-bundle/1.0"]
    assessment_source_bundle_id: str = Field(pattern=r"^assessbundle_[0-9a-f]{32}$")
    assessment_source_bundle_revision_id: str = Field(pattern=r"^assessbundlerev_[0-9a-f]{32}$")
    revision_number: int = Field(ge=1)
    previous_revision_id: str | None = Field(
        default=None, pattern=r"^assessbundlerev_[0-9a-f]{32}$"
    )
    bundle_key: SafeKey
    state: Literal["REVIEWED", "SUPERSEDED", "WITHDRAWN"]
    inventory_id: str = Field(pattern=r"^legacyinventory_[0-9a-f]{32}$")
    inventory_sha256: Sha256
    inventory_artifact: AssessmentArtifactMemberPointer
    occurrence: AssessmentOccurrencePointer
    rights_policy: AssessmentRightsPolicyPointer
    members: tuple[AssessmentSourceBundleMember, ...] = Field(min_length=1, max_length=32)
    reviewed_at: UtcDatetime
    reviewed_by: ActorId
    bundle_manifest_sha256: Sha256

    @model_validator(mode="after")
    def coherent_revision(self) -> AssessmentSourceBundleRevision:
        if (self.revision_number == 1) != (self.previous_revision_id is None):
            raise ValueError("bundle previous revision must be null only for revision one")
        member_ids = tuple(member.member_id for member in self.members)
        source_ids = tuple(
            (member.source.artifact_revision_id, member.source.member_path)
            for member in self.members
        )
        inventory_ids = tuple(member.inventory_source.entry_key for member in self.members)
        _unique(member_ids, "bundle member IDs must be unique")
        _unique(source_ids, "bundle source pointers must be unique")
        _unique(inventory_ids, "bundle inventory source pointers must be unique")
        if any(
            (
                member.inventory_source.inventory_id,
                member.inventory_source.inventory_sha256,
            )
            != (self.inventory_id, self.inventory_sha256)
            for member in self.members
        ):
            raise ValueError("bundle member inventory pointer is inconsistent")
        if any(
            member.source.sha256 != member.inventory_source.content_sha256
            for member in self.members
        ):
            raise ValueError("bundle member source hash differs from reviewed inventory")
        if (
            self.inventory_artifact.schema_ref
            != "eom://schemas/legacy-knowledge/legacy-source-inventory/2.0"
            or self.inventory_artifact.media_type != "application/json"
        ):
            raise ValueError("bundle inventory artifact contract is invalid")
        _require_self_hash(self, "bundle_manifest_sha256")
        return self


class AssessmentLayoutPageObservation(FrozenModel):
    page: AssessmentPageImageInput
    observation_state: Literal["OBSERVED", "NO_ITEM_CONTENT", "UNCLEAR"]
    visible_item_numbers: tuple[int, ...] = Field(max_length=100)

    @model_validator(mode="after")
    def coherent_observation(self) -> AssessmentLayoutPageObservation:
        _unique(self.visible_item_numbers, "visible item numbers must be unique")
        if self.observation_state == "NO_ITEM_CONTENT" and self.visible_item_numbers:
            raise ValueError("page without item content cannot declare item numbers")
        return self


class AssessmentLayoutSegment(FrozenModel):
    page_input_id: str = Field(pattern=r"^assessmentpage_[0-9a-f]{32}$")
    bounding_box: NormalizedBoundingBox
    reading_ordinal: int = Field(ge=1, le=100)


class AssessmentItemBoundary(FrozenModel):
    boundary_id: str = Field(pattern=r"^itemboundary_[0-9a-f]{32}$")
    item_number: int = Field(ge=1, le=10000)
    segments: tuple[AssessmentLayoutSegment, ...] = Field(min_length=1, max_length=16)
    continues_across_pages: bool
    confidence_milli: int = Field(ge=0, le=1000)

    @model_validator(mode="after")
    def ordered_segments(self) -> AssessmentItemBoundary:
        ordinals = tuple(segment.reading_ordinal for segment in self.segments)
        if ordinals != tuple(range(1, len(self.segments) + 1)):
            raise ValueError("item boundary segments must use contiguous reading order")
        return self


class AssessmentLayoutObservation(FrozenModel):
    schema_version: Literal["assessment-layout-observation/1.0"]
    assessment_layout_observation_id: str = Field(pattern=r"^assessmentlayout_[0-9a-f]{32}$")
    bundle: AssessmentSourceBundlePointer
    pages: tuple[AssessmentLayoutPageObservation, ...] = Field(min_length=1, max_length=1000)
    item_boundaries: tuple[AssessmentItemBoundary, ...] = Field(min_length=1, max_length=10000)
    expected_item_numbers: tuple[int, ...] = Field(min_length=1, max_length=10000)
    conflicts: tuple[AssessmentConflictObservation, ...] = Field(max_length=1000)
    created_at: UtcDatetime
    observation_sha256: Sha256

    @model_validator(mode="after")
    def closed_layout(self) -> AssessmentLayoutObservation:
        page_ids = tuple(value.page.page_input_id for value in self.pages)
        _unique(page_ids, "layout page input IDs must be unique")
        item_numbers = tuple(value.item_number for value in self.item_boundaries)
        _unique(item_numbers, "layout item numbers must be unique")
        if self.expected_item_numbers != tuple(sorted(self.expected_item_numbers)):
            raise ValueError("expected item numbers must be sorted")
        _unique(self.expected_item_numbers, "expected item numbers must be unique")
        if set(item_numbers) != set(self.expected_item_numbers):
            raise ValueError("item boundaries must exactly cover expected item numbers")
        if any(
            segment.page_input_id not in set(page_ids)
            for boundary in self.item_boundaries
            for segment in boundary.segments
        ):
            raise ValueError("item boundary points outside supplied page inputs")
        _require_self_hash(self, "observation_sha256")
        return self


class AssessmentLayoutObservationPointer(FrozenModel):
    assessment_layout_observation_id: str = Field(pattern=r"^assessmentlayout_[0-9a-f]{32}$")
    artifact: AssessmentArtifactMemberPointer
    workspace_relative_path: Literal["source/layout-observation.json"] = (
        "source/layout-observation.json"
    )
    observation_sha256: Sha256

    @model_validator(mode="after")
    def exact_layout_artifact(self) -> AssessmentLayoutObservationPointer:
        if (
            self.artifact.schema_ref
            != "eom://schemas/legacy-assessment/assessment-layout-observation/1.0"
            or self.artifact.media_type != "application/json"
        ):
            raise ValueError("layout observation Artifact contract is invalid")
        return self


class AssessmentSourceMaterialization(FrozenModel):
    materialization_id: str = Field(pattern=r"^assessmaterial_[0-9a-f]{32}$")
    source_role: Literal[
        "STRUCTURED_RECONSTRUCTION",
        "ITEM_CLASSIFICATION_WORKBOOK",
        "TYPE_CODE_REFERENCE",
        "OTHER_REVIEWED_EVIDENCE",
    ]
    source: AssessmentArtifactMemberPointer
    workspace_relative_path: str = Field(pattern=r"^source/[A-Za-z0-9._/-]{1,240}$")

    @field_validator("workspace_relative_path")
    @classmethod
    def safe_workspace_path(cls, value: str) -> str:
        if any(part in {"", ".", ".."} for part in value.split("/")):
            raise ValueError("workspace path must be normalized")
        return value


class LegacyItemExtractionRequest(FrozenModel):
    schema_version: Literal["legacy-item-extraction-request/1.0"]
    extraction_request_id: str = Field(pattern=r"^itemextractreq_[0-9a-f]{32}$")
    bundle: AssessmentSourceBundlePointer
    occurrence: AssessmentOccurrencePointer
    layout_observation: AssessmentLayoutObservationPointer
    work_unit_ordinal: int = Field(ge=0, le=1000000)
    expected_item_numbers: tuple[int, ...] = Field(min_length=1, max_length=8)
    page_inputs: tuple[AssessmentPageImageInput, ...] = Field(min_length=1, max_length=64)
    source_materializations: tuple[AssessmentSourceMaterialization, ...] = Field(max_length=128)
    execution_preset_id: str = Field(pattern=r"^execpreset_[0-9a-f]{32}$")
    execution_preset_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    execution_preset_sha256: Sha256
    worker_result_schema_ref: Literal[
        "eom://schemas/legacy-assessment/legacy-item-extraction-result/1.0"
    ]
    created_at: UtcDatetime
    request_sha256: Sha256

    @model_validator(mode="after")
    def closed_request(self) -> LegacyItemExtractionRequest:
        if self.expected_item_numbers != tuple(sorted(self.expected_item_numbers)):
            raise ValueError("work-unit item numbers must be sorted")
        _unique(self.expected_item_numbers, "work-unit item numbers must be unique")
        page_ids = tuple(page.page_input_id for page in self.page_inputs)
        page_positions = tuple((page.source_role, page.physical_page) for page in self.page_inputs)
        _unique(page_ids, "work-unit page input IDs must be unique")
        _unique(page_positions, "work-unit page positions must be unique")
        if (
            sum(page.width_px * page.height_px for page in self.page_inputs)
            > MAX_ASSESSMENT_IMAGE_TOTAL_PIXELS
        ):
            raise ValueError("work-unit page images exceed the aggregate decoded-pixel limit")
        material_ids = tuple(value.materialization_id for value in self.source_materializations)
        material_paths = tuple(
            value.workspace_relative_path for value in self.source_materializations
        )
        _unique(material_ids, "source materialization IDs must be unique")
        _unique(material_paths, "source materialization paths must be unique")
        reserved_paths = {
            self.layout_observation.workspace_relative_path,
            *(page.workspace_relative_path for page in self.page_inputs),
        }
        if reserved_paths & set(material_paths):
            raise ValueError("source materialization path collides with a reserved input")
        _require_self_hash(self, "request_sha256")
        return self


class AssessmentContentAnchorMap(FrozenModel):
    content_path: str = Field(
        pattern=(
            r"^(title|body\[[0-9]+\](?:\.[A-Za-z0-9_\[\].-]+)?|"
            r"interaction(?:\.[A-Za-z0-9_\[\].-]+)?|"
            r"solution(?:\.[A-Za-z0-9_\[\].-]+)?|"
            r"score(?:\.[A-Za-z0-9_\[\].-]+)?)$"
        )
    )
    source_anchor_ids: tuple[AnchorId, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def unique_anchor_ids(self) -> AssessmentContentAnchorMap:
        _unique(self.source_anchor_ids, "content source anchor IDs must be unique")
        return self


class AssessmentMetadataObservation(FrozenModel):
    observation_id: str = Field(pattern=r"^metadataobservation_[0-9a-f]{32}$")
    key: Literal[
        "LEGACY_ITEM_ID",
        "INTERNAL_DIFFICULTY",
        "INQUIRY_FLAG",
        "CURRICULUM_VOLUME",
        "SCIENCE_DOMAIN",
        "SOURCE_EXAM_SUBJECT",
        "SOURCE_DISPLAY_NAME",
        "SOURCE_TYPE_CODE",
        "OTHER_REVIEWED",
    ]
    value: str = Field(min_length=1, max_length=1000)
    source_anchor_ids: tuple[AnchorId, ...] = Field(min_length=1, max_length=32)

    _text = field_validator("value")(_safe_text)

    @model_validator(mode="after")
    def unique_anchor_ids(self) -> AssessmentMetadataObservation:
        _unique(self.source_anchor_ids, "metadata source anchor IDs must be unique")
        return self


class LegacyAssessmentItemProposal(FrozenModel):
    item_proposal_id: str = Field(pattern=r"^itemproposal_[0-9a-f]{32}$")
    item_number: int = Field(ge=1, le=10000)
    item_content: AssessmentItemContent
    authoring_intent_evidence_state: Literal["SOURCE_STATED", "ANALYST_RECONSTRUCTED", "UNKNOWN"]
    source_anchors: tuple[AssessmentSourceAnchor, ...] = Field(min_length=1, max_length=512)
    content_anchor_map: tuple[AssessmentContentAnchorMap, ...] = Field(min_length=1, max_length=512)
    curriculum_observations: tuple[AssessmentCurriculumObservation, ...] = Field(max_length=32)
    linguistic_patterns: tuple[AssessmentLinguisticPatternObservation, ...] = Field(
        min_length=1, max_length=16
    )
    visual_patterns: tuple[AssessmentVisualPatternObservation, ...] = Field(max_length=32)
    metadata_observations: tuple[AssessmentMetadataObservation, ...] = Field(max_length=128)
    conflicts: tuple[AssessmentConflictObservation, ...] = Field(max_length=128)
    confidence_milli: int = Field(ge=0, le=1000)

    @model_validator(mode="after")
    def closed_source_references(self) -> LegacyAssessmentItemProposal:
        anchor_ids = tuple(anchor.anchor_id for anchor in self.source_anchors)
        _unique(anchor_ids, "item source anchor IDs must be unique")
        anchor_set = set(anchor_ids)
        paths = tuple(value.content_path for value in self.content_anchor_map)
        _unique(paths, "item content anchor paths must be unique")
        referenced_ids: set[str] = set()
        for mapping in self.content_anchor_map:
            referenced_ids.update(mapping.source_anchor_ids)
        for curriculum_observation in self.curriculum_observations:
            referenced_ids.update(curriculum_observation.source_anchor_ids)
        for linguistic_pattern in self.linguistic_patterns:
            referenced_ids.update(linguistic_pattern.source_anchor_ids)
        for visual_pattern in self.visual_patterns:
            referenced_ids.update(visual_pattern.source_anchor_ids)
        for metadata_observation in self.metadata_observations:
            referenced_ids.update(metadata_observation.source_anchor_ids)
        for conflict in self.conflicts:
            referenced_ids.update(conflict.source_anchor_ids)
        if not referenced_ids.issubset(anchor_set):
            raise ValueError("item observation points outside its closed source-anchor set")
        if not any(path == "title" for path in paths):
            raise ValueError("item title requires an exact source anchor")
        if not any(path.startswith("body[") for path in paths):
            raise ValueError("item body requires exact source anchors")
        return self


class LegacyItemExtractionResult(FrozenModel):
    schema_version: Literal["legacy-item-extraction-result/1.0"]
    extraction_result_id: str = Field(pattern=r"^itemextractresult_[0-9a-f]{32}$")
    extraction_request_id: str = Field(pattern=r"^itemextractreq_[0-9a-f]{32}$")
    request_sha256: Sha256
    observed_page_input_ids: tuple[str, ...] = Field(min_length=1, max_length=64)
    items: tuple[LegacyAssessmentItemProposal, ...] = Field(min_length=1, max_length=8)
    result_sha256: Sha256

    @field_validator("observed_page_input_ids")
    @classmethod
    def valid_page_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(_ASSESSMENT_PAGE_ID.fullmatch(item) is None for item in value):
            raise ValueError("observed page input ID is invalid")
        _unique(value, "observed page input IDs must be unique")
        return value

    @model_validator(mode="after")
    def unique_items_and_hash(self) -> LegacyItemExtractionResult:
        item_ids = tuple(item.item_proposal_id for item in self.items)
        item_numbers = tuple(item.item_number for item in self.items)
        _unique(item_ids, "item proposal IDs must be unique")
        _unique(item_numbers, "extracted item numbers must be unique")
        if item_numbers != tuple(sorted(item_numbers)):
            raise ValueError("extracted items must use ascending item-number order")
        _require_self_hash(self, "result_sha256")
        return self


class LegacyItemExtractionReceipt(FrozenModel):
    """Small immutable pointer returned after Orchestrator-owned result staging."""

    schema_version: Literal["legacy-item-extraction-receipt/1.0"]
    extraction_result_id: str = Field(pattern=r"^itemextractresult_[0-9a-f]{32}$")
    extraction_request_id: str = Field(pattern=r"^itemextractreq_[0-9a-f]{32}$")
    request_sha256: Sha256
    result_artifact: AssessmentArtifactMemberPointer
    result_sha256: Sha256
    observed_page_input_ids: tuple[str, ...] = Field(min_length=1, max_length=64)
    item_numbers: tuple[int, ...] = Field(min_length=1, max_length=8)
    completed_at: UtcDatetime
    receipt_sha256: Sha256

    @model_validator(mode="after")
    def exact_result_pointer_and_hash(self) -> LegacyItemExtractionReceipt:
        if (
            self.result_artifact.member_path != "result.json"
            or self.result_artifact.schema_ref
            != "eom://schemas/legacy-assessment/legacy-item-extraction-result/1.0"
            or self.result_artifact.media_type != "application/json"
        ):
            raise ValueError("extraction receipt result Artifact contract is invalid")
        if any(
            _ASSESSMENT_PAGE_ID.fullmatch(item) is None for item in self.observed_page_input_ids
        ):
            raise ValueError("extraction receipt page input ID is invalid")
        _unique(self.observed_page_input_ids, "extraction receipt page input IDs must be unique")
        _unique(self.item_numbers, "extraction receipt item numbers must be unique")
        if self.item_numbers != tuple(sorted(self.item_numbers)):
            raise ValueError("extraction receipt item numbers must be sorted")
        _require_self_hash(self, "receipt_sha256")
        return self


class LegacyExtractionResultPointer(FrozenModel):
    artifact: AssessmentArtifactMemberPointer
    extraction_result_id: str = Field(pattern=r"^itemextractresult_[0-9a-f]{32}$")
    result_sha256: Sha256

    @model_validator(mode="after")
    def exact_result_artifact(self) -> LegacyExtractionResultPointer:
        if (
            self.artifact.schema_ref
            != "eom://schemas/legacy-assessment/legacy-item-extraction-result/1.0"
            or self.artifact.media_type != "application/json"
        ):
            raise ValueError("extraction result Artifact contract is invalid")
        return self


class LegacyItemDecision(FrozenModel):
    item_proposal_id: str = Field(pattern=r"^itemproposal_[0-9a-f]{32}$")
    item_number: int = Field(ge=1, le=10000)
    decision: Literal["ACCEPT", "CORRECT_AND_ACCEPT", "REJECT"]
    accepted_content_paths: tuple[str, ...] = Field(max_length=512)
    rejected_content_paths: tuple[str, ...] = Field(max_length=512)
    required_corrections: tuple[str, ...] = Field(max_length=128)

    @field_validator("required_corrections")
    @classmethod
    def safe_required_corrections(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for correction in value:
            _safe_text(correction)
        return value

    @model_validator(mode="after")
    def coherent_decision(self) -> LegacyItemDecision:
        _unique(self.accepted_content_paths, "accepted content paths must be unique")
        _unique(self.rejected_content_paths, "rejected content paths must be unique")
        if set(self.accepted_content_paths) & set(self.rejected_content_paths):
            raise ValueError("accepted and rejected content paths cannot overlap")
        if self.decision == "CORRECT_AND_ACCEPT" and not self.required_corrections:
            raise ValueError("correct-and-accept decision requires corrections")
        if self.decision != "CORRECT_AND_ACCEPT" and self.required_corrections:
            raise ValueError("only correct-and-accept decision may require corrections")
        return self


class LegacyItemExtractionAcceptance(FrozenModel):
    schema_version: Literal["legacy-item-extraction-acceptance/1.0"]
    acceptance_id: str = Field(pattern=r"^itemacceptance_[0-9a-f]{32}$")
    extraction_result: LegacyExtractionResultPointer
    state: Literal["ACCEPTED", "ACCEPTED_WITH_CORRECTIONS", "REJECTED"]
    item_decisions: tuple[LegacyItemDecision, ...] = Field(min_length=1, max_length=8)
    coverage_state: Literal["COMPLETE", "INCOMPLETE", "CONFLICT"]
    reviewed_at: UtcDatetime
    reviewed_by: ActorId
    acceptance_sha256: Sha256

    @model_validator(mode="after")
    def coherent_acceptance(self) -> LegacyItemExtractionAcceptance:
        item_ids = tuple(item.item_proposal_id for item in self.item_decisions)
        item_numbers = tuple(item.item_number for item in self.item_decisions)
        _unique(item_ids, "acceptance item proposal IDs must be unique")
        _unique(item_numbers, "acceptance item numbers must be unique")
        decisions = {item.decision for item in self.item_decisions}
        expected_state = (
            "REJECTED"
            if decisions == {"REJECT"}
            else (
                "ACCEPTED_WITH_CORRECTIONS"
                if "CORRECT_AND_ACCEPT" in decisions or "REJECT" in decisions
                else "ACCEPTED"
            )
        )
        if self.state != expected_state:
            raise ValueError("acceptance state does not match item decisions")
        _require_self_hash(self, "acceptance_sha256")
        return self


class AcceptedCoverageItem(FrozenModel):
    item_number: int = Field(ge=1, le=10000)
    acceptance_id: str = Field(pattern=r"^itemacceptance_[0-9a-f]{32}$")
    acceptance_sha256: Sha256


class AssessmentBundleCoverage(FrozenModel):
    bundle: AssessmentSourceBundlePointer
    expected_item_numbers: tuple[int, ...] = Field(min_length=1, max_length=10000)
    accepted_items: tuple[AcceptedCoverageItem, ...] = Field(max_length=10000)
    missing_item_numbers: tuple[int, ...] = Field(max_length=10000)
    conflict_item_numbers: tuple[int, ...] = Field(max_length=10000)

    @model_validator(mode="after")
    def exact_partition(self) -> AssessmentBundleCoverage:
        if self.expected_item_numbers != tuple(sorted(self.expected_item_numbers)):
            raise ValueError("coverage expected item numbers must be sorted")
        _unique(self.expected_item_numbers, "coverage expected item numbers must be unique")
        accepted = tuple(item.item_number for item in self.accepted_items)
        _unique(accepted, "coverage accepted item numbers must be unique")
        _unique(self.missing_item_numbers, "coverage missing item numbers must be unique")
        _unique(self.conflict_item_numbers, "coverage conflict item numbers must be unique")
        partitions = (
            set(accepted),
            set(self.missing_item_numbers),
            set(self.conflict_item_numbers),
        )
        if any(
            left & right
            for index, left in enumerate(partitions)
            for right in partitions[index + 1 :]
        ):
            raise ValueError("coverage item partitions cannot overlap")
        if set().union(*partitions) != set(self.expected_item_numbers):
            raise ValueError("coverage partitions must exactly cover expected item numbers")
        return self


class LegacyItemCorpusCoverage(FrozenModel):
    schema_version: Literal["legacy-item-corpus-coverage/1.0"]
    coverage_id: str = Field(pattern=r"^itemcoverage_[0-9a-f]{32}$")
    inventory_id: str = Field(pattern=r"^legacyinventory_[0-9a-f]{32}$")
    inventory_sha256: Sha256
    bundle_coverages: tuple[AssessmentBundleCoverage, ...] = Field(min_length=1, max_length=10000)
    expected_item_count: int = Field(ge=0, le=10000000)
    accepted_item_count: int = Field(ge=0, le=10000000)
    missing_item_count: int = Field(ge=0, le=10000000)
    conflict_item_count: int = Field(ge=0, le=10000000)
    state: Literal["COMPLETE", "INCOMPLETE", "CONFLICT"]
    created_at: UtcDatetime
    coverage_sha256: Sha256

    @model_validator(mode="after")
    def exact_counts_and_state(self) -> LegacyItemCorpusCoverage:
        bundle_ids = tuple(
            value.bundle.assessment_source_bundle_revision_id for value in self.bundle_coverages
        )
        _unique(bundle_ids, "coverage bundle revisions must be unique")
        expected = sum(len(value.expected_item_numbers) for value in self.bundle_coverages)
        accepted = sum(len(value.accepted_items) for value in self.bundle_coverages)
        missing = sum(len(value.missing_item_numbers) for value in self.bundle_coverages)
        conflict = sum(len(value.conflict_item_numbers) for value in self.bundle_coverages)
        if (expected, accepted, missing, conflict) != (
            self.expected_item_count,
            self.accepted_item_count,
            self.missing_item_count,
            self.conflict_item_count,
        ):
            raise ValueError("corpus coverage counts do not match bundle partitions")
        expected_state = "CONFLICT" if conflict else ("INCOMPLETE" if missing else "COMPLETE")
        if self.state != expected_state:
            raise ValueError("corpus coverage state does not match gap counts")
        _require_self_hash(self, "coverage_sha256")
        return self
