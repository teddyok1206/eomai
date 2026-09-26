"""Contracts for the bounded science-corpus visual learning pilot."""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Literal

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.models import (
    FrozenModel,
    ImageEvaluationArtifactMember,
    ImageEvaluationBoundingBox,
    Sha256,
    content_sha256,
    text_sha256,
)

CORPUS_MANIFEST_SCHEMA_REF = (
    "eom://schemas/legacy-assessment/science-assessment-web-corpus-manifest/2.0"
)
CORPUS_SOURCE_SCHEMA_REF = "eom://schemas/content-intake/source-file/1.0"
CORPUS_AUTHORIZATION_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-corpus-training-authorization/1.0"
)
CORPUS_PILOT_PLAN_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-corpus-visual-pilot-plan/1.0"
)
CORPUS_PILOT_PLAN_V2_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-corpus-visual-pilot-plan/1.1"
)
CORPUS_PILOT_COMMAND_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-corpus-visual-pilot-command/1.0"
)
CORPUS_PILOT_RESULT_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-corpus-visual-pilot-result/1.0"
)
CORPUS_PATTERN_INVENTORY_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-visual-pattern-inventory/1.0"
)
CORPUS_PATTERN_INVENTORY_V2_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-visual-pattern-inventory/1.1"
)
CORPUS_REVIEWED_CROP_SET_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-visual-crop-set/1.0"
)
CORPUS_RASTER_REVIEWED_CROP_SET_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-visual-crop-set/1.1"
)
CORPUS_RASTER_SUITABILITY_REVIEW_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-raster-suitability-review/1.0"
)
CORPUS_RASTER_REFINEMENT_PLAN_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-raster-refinement-plan/1.0"
)

ScienceSubjectFamily = Literal[
    "CHEMISTRY",
    "EARTH_SCIENCE",
    "GENERAL_SCIENCE",
    "INTEGRATED_SCIENCE",
    "LIFE_SCIENCE",
    "PHYSICS",
]
ScienceIssuerType = Literal["EDUCATION_AUTHORITY", "KICE"]
ScienceVisualPartition = Literal["HOLDOUT", "TRAIN", "VALIDATION"]
ScienceVisualRepresentationKind = Literal[
    "APPARATUS",
    "COMPOSITE",
    "CROSS_SECTION",
    "DIAGRAM",
    "MAP",
    "PARTICLE_MODEL",
    "PHOTOGRAPH",
    "PLOT",
    "TABLE",
    "UNKNOWN",
]
ScienceVisualFeature = Literal[
    "ARROWS",
    "AXES",
    "BOUNDARY",
    "CALLOUT",
    "DATA_POINTS",
    "GRID",
    "HATCHING",
    "LABELS",
    "LEADER_LINES",
    "LEGEND",
    "MULTIPLE_PANELS",
    "NUMBERED_STEPS",
    "PATTERN_FILL",
    "SCALE",
    "SYMBOL_KEY",
    "TRAJECTORY",
]
ScienceVisualPatternFamily = Literal[
    "APPARATUS",
    "ASTRONOMICAL_SCENE",
    "CELL_CROSS_SECTION",
    "CIRCUIT",
    "FOSSIL",
    "GENERIC_LABELLED_DIAGRAM",
    "GEOLOGIC_SECTION",
    "GEOLOGIC_TEXTURE",
    "MAP_BOUNDARY",
    "MICROSCOPIC_TEXTURE",
    "NATURAL_TEXTURE",
    "ORBITAL_SYSTEM",
    "ORGANISM",
    "PARTICLE_SYSTEM",
    "PLOT",
    "RAY_DIAGRAM",
    "TABLE",
    "VECTOR_FIELD",
    "OTHER",
]
ScienceRendererPrimitiveKey = Literal[
    "APPARATUS",
    "AXIS_PLOT",
    "CELL_CROSS_SECTION",
    "CIRCUIT",
    "GENERIC_LABELLED_DIAGRAM",
    "GEOLOGIC_SECTION",
    "MAP_BOUNDARY",
    "ORBITAL_SYSTEM",
    "PARTICLE_SYSTEM",
    "RAY_DIAGRAM",
    "VECTOR_FIELD",
]

_PRIMITIVE_PATTERN_FAMILY: dict[ScienceRendererPrimitiveKey, ScienceVisualPatternFamily] = {
    "APPARATUS": "APPARATUS",
    "AXIS_PLOT": "PLOT",
    "CELL_CROSS_SECTION": "CELL_CROSS_SECTION",
    "CIRCUIT": "CIRCUIT",
    "GENERIC_LABELLED_DIAGRAM": "GENERIC_LABELLED_DIAGRAM",
    "GEOLOGIC_SECTION": "GEOLOGIC_SECTION",
    "MAP_BOUNDARY": "MAP_BOUNDARY",
    "ORBITAL_SYSTEM": "ORBITAL_SYSTEM",
    "PARTICLE_SYSTEM": "PARTICLE_SYSTEM",
    "RAY_DIAGRAM": "RAY_DIAGRAM",
    "VECTOR_FIELD": "VECTOR_FIELD",
}
_GUIDANCE_PATHS = {
    "AUTHORING_TEAM_LEAD": (
        "config/control-plane/standard-item-v5/references/guidance/"
        "content-team-integrated-science-authoring-v05.md"
    ),
    "HWPX_EDITOR_TEAM_LEAD": (
        "config/control-plane/standard-item-v6/references/guidance/"
        "content-team-hwp-question-editor-handoff-v1.md"
    ),
    "KICE_ILLUSTRATION_GUIDE": "content/image-specs/kice-integrated-science-illustration-v1.md",
}


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("timestamp must be UTC")
    return value


def _require_pointer(
    value: ImageEvaluationArtifactMember,
    *,
    schema_ref: str,
    media_type: str,
    member_path: str | None = None,
) -> None:
    if (
        value.schema_ref != schema_ref
        or value.media_type != media_type
        or (member_path is not None and value.member_path != member_path)
    ):
        raise ValueError("science visual artifact pointer contract mismatch")


class LocalImageScienceCorpusTrainingAuthorization(FrozenModel):
    schema_version: Literal["local-image-science-corpus-training-authorization/1.0"]
    authorization_id: str = Field(pattern=r"^imgscicorpusauth_[0-9a-f]{32}$")
    authorization_revision_id: str = Field(pattern=r"^imgscicorpusauthrev_[0-9a-f]{32}$")
    revision_number: int = Field(ge=1, le=100_000)
    previous_revision_id: str | None = Field(pattern=r"^imgscicorpusauthrev_[0-9a-f]{32}$")
    corpus_manifest: ImageEvaluationArtifactMember
    corpus_id: str = Field(pattern=r"^sciencecorpus_[0-9a-f]{32}$")
    corpus_manifest_sha256: Sha256
    acquisition_sha256: Sha256
    resolution_sha256: Sha256
    resolution_policy_id: str = Field(pattern=r"^sciencecorpuspolicy_[0-9a-f]{32}$")
    resolution_policy_sha256: Sha256
    authorization_basis: Literal["USER_APPROVED_INTERNAL_EXAM_MATERIALS"]
    permitted_uses: tuple[
        Literal["DETERMINISTIC_PATTERN_ANALYSIS"],
        Literal["INTERNAL_SSD1B_LORA_TRAINING"],
    ]
    derivative_output: Literal["LORA_ADAPTER_ONLY"]
    raw_source_export: Literal["FORBIDDEN"]
    state: Literal["APPROVED"]
    approved_at: datetime
    approved_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    authorization_sha256: Sha256

    @field_validator("approved_at")
    @classmethod
    def utc_approval(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def immutable_authorization_is_coherent(
        self,
    ) -> LocalImageScienceCorpusTrainingAuthorization:
        _require_pointer(
            self.corpus_manifest,
            schema_ref=CORPUS_MANIFEST_SCHEMA_REF,
            media_type="application/json",
            member_path="corpus-manifest.json",
        )
        if (self.revision_number == 1) != (self.previous_revision_id is None):
            raise ValueError("science corpus authorization revision chain is inconsistent")
        identity = content_sha256(
            self.model_dump(
                mode="json",
                exclude={
                    "authorization_id",
                    "authorization_revision_id",
                    "revision_number",
                    "previous_revision_id",
                    "approved_at",
                    "approved_by",
                    "authorization_sha256",
                },
            )
        ).removeprefix("sha256:")
        if self.authorization_id != "imgscicorpusauth_" + identity[:32]:
            raise ValueError("science corpus authorization ID does not bind its scope")
        revision_identity = content_sha256(
            self.model_dump(
                mode="json",
                exclude={"authorization_revision_id", "authorization_sha256"},
            )
        ).removeprefix("sha256:")
        if self.authorization_revision_id != "imgscicorpusauthrev_" + revision_identity[:32]:
            raise ValueError("science corpus authorization revision ID differs")
        expected = content_sha256(self.model_dump(mode="json", exclude={"authorization_sha256"}))
        if self.authorization_sha256 != expected:
            raise ValueError("science corpus authorization hash mismatch")
        return self


class ScienceVisualGuidanceAuthority(FrozenModel):
    role: Literal[
        "AUTHORING_TEAM_LEAD",
        "HWPX_EDITOR_TEAM_LEAD",
        "KICE_ILLUSTRATION_GUIDE",
    ]
    logical_name: str = Field(min_length=1, max_length=240, pattern=r"^[A-Za-z0-9._/-]+$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    sha256: Sha256

    @model_validator(mode="after")
    def exact_authority_path(self) -> ScienceVisualGuidanceAuthority:
        if self.logical_name != _GUIDANCE_PATHS[self.role]:
            raise ValueError("science visual guidance authority path differs")
        return self


class ScienceVisualToolIdentity(FrozenModel):
    path: Literal["/usr/bin/pdftoppm", "/usr/bin/tesseract"]
    sha256: Sha256
    version: str = Field(min_length=1, max_length=128)


class ScienceVisualToolSet(FrozenModel):
    pdftoppm: ScienceVisualToolIdentity
    tesseract: ScienceVisualToolIdentity

    @model_validator(mode="after")
    def tool_paths_match_fields(self) -> ScienceVisualToolSet:
        if self.pdftoppm.path != "/usr/bin/pdftoppm" or self.tesseract.path != "/usr/bin/tesseract":
            raise ValueError("science visual tool identity is assigned to another field")
        return self


class ScienceVisualPilotSource(FrozenModel):
    document_id: str = Field(pattern=r"^sciencedoc_[0-9a-f]{32}$")
    source_file_id: str = Field(pattern=r"^sourcefile_[0-9a-f]{32}$")
    pdf: ImageEvaluationArtifactMember
    bytes: int = Field(ge=1024, le=100 * 1024 * 1024)
    page_count: int = Field(ge=1, le=512)
    subject_family: ScienceSubjectFamily
    issuer_type: ScienceIssuerType
    administration_year: int = Field(ge=1994, le=2200)
    grade: int = Field(ge=1, le=3)
    session_label: str = Field(min_length=1, max_length=128)
    exam_group_sha256: Sha256
    partition: ScienceVisualPartition

    @model_validator(mode="after")
    def immutable_source_is_coherent(self) -> ScienceVisualPilotSource:
        _require_pointer(
            self.pdf,
            schema_ref=CORPUS_SOURCE_SCHEMA_REF,
            media_type="application/pdf",
        )
        validate_source_member_path(self.pdf.member_path)
        digest = self.pdf.sha256.removeprefix("sha256:")
        member_path = PurePosixPath(self.pdf.member_path)
        if (
            self.document_id != "sciencedoc_" + digest[:32]
            or member_path.parts[0] != "source"
            or member_path.suffix.lower() != ".pdf"
        ):
            raise ValueError("science visual source does not bind its PDF bytes")
        expected_group = content_sha256(
            {
                "issuer_type": self.issuer_type,
                "administration_year": self.administration_year,
                "grade": self.grade,
                "session_label": self.session_label,
            }
        )
        if self.exam_group_sha256 != expected_group:
            raise ValueError("science visual exam group hash mismatch")
        return self


class _LocalImageScienceCorpusVisualPilotPlanBase(FrozenModel):
    pilot_id: str = Field(pattern=r"^imgscivispilot_[0-9a-f]{32}$")
    corpus_manifest: ImageEvaluationArtifactMember
    corpus_id: str = Field(pattern=r"^sciencecorpus_[0-9a-f]{32}$")
    corpus_manifest_sha256: Sha256
    acquisition_sha256: Sha256
    resolution_sha256: Sha256
    resolution_policy_id: str = Field(pattern=r"^sciencecorpuspolicy_[0-9a-f]{32}$")
    resolution_policy_sha256: Sha256
    training_authorization: ImageEvaluationArtifactMember
    selection_algorithm: Literal["SCIENCE_VISUAL_STRATIFIED_SHA256_V1"]
    selection_seed_sha256: Sha256
    selected_sources: tuple[ScienceVisualPilotSource, ...] = Field(min_length=12, max_length=96)
    max_page_images: int = Field(ge=12, le=384)
    max_visual_candidates: int = Field(ge=12, le=512)
    max_lora_training_crops: int = Field(ge=12, le=96)
    page_render_dpi: Literal[144]
    guidance_authorities: tuple[ScienceVisualGuidanceAuthority, ...] = Field(
        min_length=3, max_length=3
    )
    tools: ScienceVisualToolSet
    created_at: datetime
    created_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    plan_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_creation(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def immutable_plan_is_coherent(self) -> _LocalImageScienceCorpusVisualPilotPlanBase:
        _require_pointer(
            self.corpus_manifest,
            schema_ref=CORPUS_MANIFEST_SCHEMA_REF,
            media_type="application/json",
            member_path="corpus-manifest.json",
        )
        _require_pointer(
            self.training_authorization,
            schema_ref=CORPUS_AUTHORIZATION_SCHEMA_REF,
            media_type="application/json",
            member_path="manifests/science-corpus-training-authorization.json",
        )
        source_ids = tuple(value.document_id for value in self.selected_sources)
        if source_ids != tuple(sorted(set(source_ids))):
            raise ValueError("science visual pilot sources must be uniquely sorted")
        pdf_hashes = tuple(value.pdf.sha256 for value in self.selected_sources)
        if len(pdf_hashes) != len(set(pdf_hashes)):
            raise ValueError("science visual pilot repeats PDF bytes")
        group_partitions: dict[str, str] = {}
        for source in self.selected_sources:
            existing = group_partitions.setdefault(source.exam_group_sha256, source.partition)
            if existing != source.partition:
                raise ValueError("science visual exam group crosses a partition")
        partition_counts = Counter(value.partition for value in self.selected_sources)
        if (
            partition_counts["TRAIN"] < 6
            or partition_counts["VALIDATION"] < 3
            or partition_counts["HOLDOUT"] < 3
        ):
            raise ValueError("science visual partitions are too small")
        if sum(value.page_count for value in self.selected_sources) > self.max_page_images:
            raise ValueError("science visual page limit cannot cover selected sources")
        if self.max_lora_training_crops > self.max_visual_candidates:
            raise ValueError("science visual training limit exceeds candidate limit")
        roles = tuple(value.role for value in self.guidance_authorities)
        if (
            roles != tuple(sorted(_GUIDANCE_PATHS))
            or len({value.source_commit for value in self.guidance_authorities}) != 1
        ):
            raise ValueError("science visual guidance authorities are not exact and ordered")
        identity = content_sha256(
            self.model_dump(mode="json", exclude={"pilot_id", "plan_sha256"})
        ).removeprefix("sha256:")
        if self.pilot_id != "imgscivispilot_" + identity[:32]:
            raise ValueError("science visual pilot ID does not bind its plan")
        expected = content_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))
        if self.plan_sha256 != expected:
            raise ValueError("science visual pilot plan hash mismatch")
        return self


class LocalImageScienceCorpusVisualPilotPlan(_LocalImageScienceCorpusVisualPilotPlanBase):
    schema_version: Literal["local-image-science-corpus-visual-pilot-plan/1.0"]
    locator_revision: Literal["science-corpus-visual-locator/1.0"]


class ScienceVisualLocatorPolicyV2(FrozenModel):
    max_candidates_per_page: int = Field(ge=1, le=8)
    max_candidates_per_source: int = Field(ge=2, le=32)
    maximum_redaction_area_milli: int = Field(ge=0, le=800)
    minimum_interior_ink_milli: int = Field(ge=1, le=250)
    maximum_border_ink_fraction_milli: int = Field(ge=250, le=1000)
    minimum_aspect_ratio_milli: int = Field(ge=50, le=1000)
    maximum_aspect_ratio_milli: int = Field(ge=1000, le=20_000)

    @model_validator(mode="after")
    def bounds_are_coherent(self) -> ScienceVisualLocatorPolicyV2:
        if self.max_candidates_per_source < self.max_candidates_per_page:
            raise ValueError("science visual source cap is smaller than its page cap")
        if self.minimum_aspect_ratio_milli > self.maximum_aspect_ratio_milli:
            raise ValueError("science visual aspect-ratio bounds are inverted")
        return self


class LocalImageScienceCorpusVisualPilotPlanV2(_LocalImageScienceCorpusVisualPilotPlanBase):
    schema_version: Literal["local-image-science-corpus-visual-pilot-plan/1.1"]
    locator_revision: Literal["science-corpus-visual-locator/1.1"]
    locator_policy: ScienceVisualLocatorPolicyV2

    @model_validator(mode="after")
    def locator_policy_fits_plan(self) -> LocalImageScienceCorpusVisualPilotPlanV2:
        if self.locator_policy.max_candidates_per_source > self.max_visual_candidates:
            raise ValueError("science visual source cap exceeds the plan candidate limit")
        return self


class ScienceVisualStagedSource(FrozenModel):
    document_id: str = Field(pattern=r"^sciencedoc_[0-9a-f]{32}$")
    staged_pdf_member: str = Field(pattern=r"^input/pdfs/sciencedoc_[0-9a-f]{32}\.pdf$")
    sha256: Sha256
    bytes: int = Field(ge=1024, le=100 * 1024 * 1024)
    page_count: int = Field(ge=1, le=512)

    @model_validator(mode="after")
    def staged_member_matches_document(self) -> ScienceVisualStagedSource:
        if self.staged_pdf_member != f"input/pdfs/{self.document_id}.pdf":
            raise ValueError("science visual staged PDF member differs from its document")
        return self


def _validate_visual_pilot_command(
    command: FrozenModel,
    *,
    plan: ImageEvaluationArtifactMember,
    plan_schema_ref: str,
    staged_sources: tuple[ScienceVisualStagedSource, ...],
    attempt_id: str,
    command_sha256: Sha256,
) -> None:
    _require_pointer(
        plan,
        schema_ref=plan_schema_ref,
        media_type="application/json",
        member_path="manifests/visual-pilot-plan.json",
    )
    source_ids = tuple(value.document_id for value in staged_sources)
    if source_ids != tuple(sorted(set(source_ids))):
        raise ValueError("science visual staged sources must be uniquely sorted")
    identity = content_sha256(
        command.model_dump(mode="json", exclude={"attempt_id", "command_sha256"})
    ).removeprefix("sha256:")
    if attempt_id != "imgscivisattempt_" + identity[:32]:
        raise ValueError("science visual attempt ID does not bind its command")
    expected = content_sha256(command.model_dump(mode="json", exclude={"command_sha256"}))
    if command_sha256 != expected:
        raise ValueError("science visual pilot command hash mismatch")


class _LocalImageScienceCorpusVisualPilotCommandBase(FrozenModel):
    attempt_id: str = Field(pattern=r"^imgscivisattempt_[0-9a-f]{32}$")
    plan: ImageEvaluationArtifactMember
    plan_sha256: Sha256
    staged_plan_member: Literal["input/visual-pilot-plan.json"]
    staged_sources: tuple[ScienceVisualStagedSource, ...] = Field(min_length=12, max_length=96)
    result_member: Literal["manifests/visual-pilot-result.json"]
    requested_at: datetime
    requested_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    command_sha256: Sha256

    @field_validator("requested_at")
    @classmethod
    def utc_request(cls, value: datetime) -> datetime:
        return _require_utc(value)


class LocalImageScienceCorpusVisualPilotCommand(_LocalImageScienceCorpusVisualPilotCommandBase):
    schema_version: Literal["local-image-science-corpus-visual-pilot-command/1.0"]

    @model_validator(mode="after")
    def immutable_command_is_coherent(self) -> LocalImageScienceCorpusVisualPilotCommand:
        _validate_visual_pilot_command(
            self,
            plan=self.plan,
            plan_schema_ref=CORPUS_PILOT_PLAN_SCHEMA_REF,
            staged_sources=self.staged_sources,
            attempt_id=self.attempt_id,
            command_sha256=self.command_sha256,
        )
        return self


class LocalImageScienceCorpusVisualPilotCommandV2(_LocalImageScienceCorpusVisualPilotCommandBase):
    schema_version: Literal["local-image-science-corpus-visual-pilot-command/1.1"]

    @model_validator(mode="after")
    def immutable_command_is_coherent(self) -> LocalImageScienceCorpusVisualPilotCommandV2:
        _validate_visual_pilot_command(
            self,
            plan=self.plan,
            plan_schema_ref=CORPUS_PILOT_PLAN_V2_SCHEMA_REF,
            staged_sources=self.staged_sources,
            attempt_id=self.attempt_id,
            command_sha256=self.command_sha256,
        )
        return self


class ScienceVisualPageImage(FrozenModel):
    document_id: str = Field(pattern=r"^sciencedoc_[0-9a-f]{32}$")
    physical_page: int = Field(ge=1, le=512)
    member_path: str = Field(pattern=r"^pages/sciencedoc_[0-9a-f]{32}/page-[0-9]{1,3}\.png$")
    sha256: Sha256
    size_bytes: int = Field(ge=64, le=64 * 1024 * 1024)
    width_px: int = Field(ge=100, le=10_000)
    height_px: int = Field(ge=100, le=10_000)

    @model_validator(mode="after")
    def page_member_matches_identity(self) -> ScienceVisualPageImage:
        expected = f"pages/{self.document_id}/page-{self.physical_page}.png"
        if self.member_path != expected:
            raise ValueError("science visual page member differs from its identity")
        return self


class ScienceVisualCandidate(FrozenModel):
    candidate_id: str = Field(pattern=r"^imgsciviscandidate_[0-9a-f]{32}$")
    document_id: str = Field(pattern=r"^sciencedoc_[0-9a-f]{32}$")
    physical_page: int = Field(ge=1, le=512)
    page_image_sha256: Sha256
    bounding_box: ImageEvaluationBoundingBox
    member_path: str = Field(pattern=r"^crops/imgsciviscandidate_[0-9a-f]{32}\.png$")
    sha256: Sha256
    size_bytes: int = Field(ge=64, le=64 * 1024 * 1024)
    representation_kind: ScienceVisualRepresentationKind
    rendering_mode: Literal["MIXED", "RASTER", "VECTOR_LIKE"]
    visual_features: tuple[ScienceVisualFeature, ...] = Field(max_length=16)
    authority_class: Literal[
        "AUTHORITATIVE_DETERMINISTIC_GEOMETRY",
        "NON_AUTHORITATIVE_RASTER_STYLE",
        "UNKNOWN_REVIEW_REQUIRED",
    ]
    review_state: Literal["PENDING"]
    locator_score_milli: int = Field(ge=1, le=1000)

    @model_validator(mode="after")
    def immutable_candidate_is_coherent(self) -> ScienceVisualCandidate:
        if self.visual_features != tuple(sorted(set(self.visual_features))):
            raise ValueError("science visual candidate features must be sorted and unique")
        identity_body = self.model_dump(
            mode="json",
            exclude={"candidate_id", "member_path", "sha256", "size_bytes"},
        )
        identity = content_sha256(identity_body).removeprefix("sha256:")
        if self.candidate_id != "imgsciviscandidate_" + identity[:32]:
            raise ValueError("science visual candidate ID does not bind its observation")
        if self.member_path != f"crops/{self.candidate_id}.png":
            raise ValueError("science visual candidate member path differs")
        return self


class ScienceVisualOmission(FrozenModel):
    document_id: str = Field(pattern=r"^sciencedoc_[0-9a-f]{32}$")
    physical_page: int = Field(ge=1, le=512)
    reason: Literal[
        "CANDIDATE_LIMIT_REACHED",
        "NO_VISUAL_REGION",
        "PAGE_RENDER_FAILED",
        "PDF_POINTER_INVALID",
    ]


class ScienceVisualPilotRuntime(FrozenModel):
    python_version: str = Field(min_length=1, max_length=64)
    pillow_version: str = Field(min_length=1, max_length=64)
    opencv_version: str = Field(min_length=1, max_length=64)
    tesseract_version: str = Field(min_length=1, max_length=128)
    pdftoppm_version: str = Field(min_length=1, max_length=128)


class LocalImageScienceCorpusVisualPilotResult(FrozenModel):
    schema_version: Literal["local-image-science-corpus-visual-pilot-result/1.0"]
    pilot_id: str = Field(pattern=r"^imgscivispilot_[0-9a-f]{32}$")
    plan_sha256: Sha256
    status: Literal["FAILED", "SUCCEEDED"]
    page_images: tuple[ScienceVisualPageImage, ...] = Field(max_length=384)
    visual_candidates: tuple[ScienceVisualCandidate, ...] = Field(max_length=512)
    omissions: tuple[ScienceVisualOmission, ...] = Field(max_length=384)
    runtime: ScienceVisualPilotRuntime
    error_code: str | None = Field(pattern=r"^SCIENCE_VISUAL_PILOT_[A-Z0-9_]{3,80}$")
    started_at: datetime
    completed_at: datetime
    result_sha256: Sha256

    @field_validator("started_at", "completed_at")
    @classmethod
    def utc_timestamps(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def terminal_result_is_coherent(self) -> LocalImageScienceCorpusVisualPilotResult:
        if self.completed_at < self.started_at:
            raise ValueError("science visual pilot completion precedes start")
        page_keys = tuple((value.document_id, value.physical_page) for value in self.page_images)
        if page_keys != tuple(sorted(set(page_keys))):
            raise ValueError("science visual page images must be uniquely sorted")
        candidate_ids = tuple(value.candidate_id for value in self.visual_candidates)
        if candidate_ids != tuple(sorted(set(candidate_ids))):
            raise ValueError("science visual candidates must be uniquely sorted")
        if len({value.sha256 for value in self.visual_candidates}) != len(self.visual_candidates):
            raise ValueError("science visual candidates repeat crop bytes")
        omission_keys = tuple(
            (value.document_id, value.physical_page, value.reason) for value in self.omissions
        )
        if omission_keys != tuple(sorted(set(omission_keys))):
            raise ValueError("science visual omissions must be uniquely sorted")
        page_hashes = {
            key: value.sha256 for key, value in zip(page_keys, self.page_images, strict=True)
        }
        if any(
            page_hashes.get((value.document_id, value.physical_page)) != value.page_image_sha256
            for value in self.visual_candidates
        ):
            raise ValueError("science visual candidate lacks its exact page image")
        if self.status == "SUCCEEDED":
            if not self.page_images or not self.visual_candidates or self.error_code is not None:
                raise ValueError("successful science visual pilot result is incomplete")
        elif (
            self.page_images or self.visual_candidates or self.omissions or self.error_code is None
        ):
            raise ValueError("failed science visual pilot result requires only an error code")
        expected = content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        if self.result_sha256 != expected:
            raise ValueError("science visual pilot result hash mismatch")
        return self


def validate_science_visual_pilot_result(
    plan: LocalImageScienceCorpusVisualPilotPlan | LocalImageScienceCorpusVisualPilotPlanV2,
    result: LocalImageScienceCorpusVisualPilotResult,
) -> None:
    if result.pilot_id != plan.pilot_id or result.plan_sha256 != plan.plan_sha256:
        raise ValueError("science visual pilot result does not bind the plan")
    if result.status != "SUCCEEDED":
        return
    if (
        len(result.page_images) > plan.max_page_images
        or len(result.visual_candidates) > plan.max_visual_candidates
    ):
        raise ValueError("science visual pilot result exceeds plan limits")
    source_pages = {
        (source.document_id, page)
        for source in plan.selected_sources
        for page in range(1, source.page_count + 1)
    }
    actual_pages = {(value.document_id, value.physical_page) for value in result.page_images}
    if actual_pages != source_pages:
        raise ValueError("science visual pilot result does not render every selected page")
    if any(
        (value.document_id, value.physical_page) not in source_pages
        for value in result.visual_candidates
    ) or any(
        (value.document_id, value.physical_page) not in source_pages for value in result.omissions
    ):
        raise ValueError("science visual pilot result contains an unplanned source page")
    if isinstance(plan, LocalImageScienceCorpusVisualPilotPlanV2):
        candidates_per_page = Counter(
            (value.document_id, value.physical_page) for value in result.visual_candidates
        )
        candidates_per_source = Counter(value.document_id for value in result.visual_candidates)
        if any(
            count > plan.locator_policy.max_candidates_per_page
            for count in candidates_per_page.values()
        ) or any(
            count > plan.locator_policy.max_candidates_per_source
            for count in candidates_per_source.values()
        ):
            raise ValueError("science visual pilot result exceeds locator limits")


def validate_science_visual_pilot_command(
    plan: LocalImageScienceCorpusVisualPilotPlan | LocalImageScienceCorpusVisualPilotPlanV2,
    command: LocalImageScienceCorpusVisualPilotCommand
    | LocalImageScienceCorpusVisualPilotCommandV2,
) -> None:
    if isinstance(plan, LocalImageScienceCorpusVisualPilotPlanV2) != isinstance(
        command, LocalImageScienceCorpusVisualPilotCommandV2
    ):
        raise ValueError("science visual plan and command contract versions differ")
    if command.plan_sha256 != plan.plan_sha256:
        raise ValueError("science visual pilot command does not bind the plan")
    expected = tuple(
        (
            source.document_id,
            source.pdf.sha256,
            source.bytes,
            source.page_count,
        )
        for source in plan.selected_sources
    )
    actual = tuple(
        (
            source.document_id,
            source.sha256,
            source.bytes,
            source.page_count,
        )
        for source in command.staged_sources
    )
    if actual != expected:
        raise ValueError("science visual staged PDFs differ from the plan")


class ScienceVisualPatternReview(FrozenModel):
    candidate_id: str = Field(pattern=r"^imgsciviscandidate_[0-9a-f]{32}$")
    decision: Literal["DETERMINISTIC_RENDERER_ONLY", "EXCLUDED", "LORA_ELIGIBLE"]
    pattern_family: ScienceVisualPatternFamily
    visual_features: tuple[ScienceVisualFeature, ...] = Field(max_length=16)
    caption_en: str | None = Field(
        default=None,
        min_length=3,
        max_length=240,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9 ,.'()/_:-]{2,239}$",
    )
    caption_sha256: Sha256 | None
    reviewed_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    reviewed_at: datetime

    @field_validator("reviewed_at")
    @classmethod
    def utc_review(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def review_is_coherent(self) -> ScienceVisualPatternReview:
        if self.visual_features != tuple(sorted(set(self.visual_features))):
            raise ValueError("science visual review features must be sorted and unique")
        if self.decision == "LORA_ELIGIBLE":
            if self.caption_en is None or self.caption_sha256 != text_sha256(self.caption_en):
                raise ValueError("LoRA-eligible review requires an exact English caption")
        elif self.caption_en is not None or self.caption_sha256 is not None:
            raise ValueError("non-LoRA review cannot carry a training caption")
        return self


class ScienceRendererPrimitiveRecommendation(FrozenModel):
    primitive_key: ScienceRendererPrimitiveKey
    support_count: int = Field(ge=2, le=512)
    visual_features: tuple[ScienceVisualFeature, ...] = Field(max_length=16)
    geometry_authority: Literal["AUTHORITATIVE"]
    render_route: Literal["PYTHON_SVG"]

    @model_validator(mode="after")
    def features_are_canonical(self) -> ScienceRendererPrimitiveRecommendation:
        if self.visual_features != tuple(sorted(set(self.visual_features))):
            raise ValueError("renderer primitive features must be sorted and unique")
        return self


def _validate_pattern_inventory_common(
    *,
    inventory: FrozenModel,
    inventory_id: str,
    reviews: tuple[ScienceVisualPatternReview, ...],
    primitive_recommendations: tuple[ScienceRendererPrimitiveRecommendation, ...],
    lora_eligible_count: int,
    deterministic_renderer_count: int,
    excluded_count: int,
    inventory_sha256: Sha256,
) -> None:
    review_ids = tuple(value.candidate_id for value in reviews)
    if review_ids != tuple(sorted(set(review_ids))):
        raise ValueError("science visual reviews must be uniquely sorted")
    counts = Counter(value.decision for value in reviews)
    if (
        lora_eligible_count != counts["LORA_ELIGIBLE"]
        or deterministic_renderer_count != counts["DETERMINISTIC_RENDERER_ONLY"]
        or excluded_count != counts["EXCLUDED"]
    ):
        raise ValueError("science visual inventory counts differ from its reviews")
    primitive_keys = tuple(value.primitive_key for value in primitive_recommendations)
    if primitive_keys != tuple(sorted(set(primitive_keys))):
        raise ValueError("renderer primitive recommendations must be uniquely sorted")
    support: Counter[ScienceVisualPatternFamily] = Counter(
        value.pattern_family for value in reviews if value.decision == "DETERMINISTIC_RENDERER_ONLY"
    )
    for recommendation in primitive_recommendations:
        if support[_PRIMITIVE_PATTERN_FAMILY[recommendation.primitive_key]] != (
            recommendation.support_count
        ):
            raise ValueError("renderer primitive support count differs from reviewed patterns")
    identity = content_sha256(
        inventory.model_dump(mode="json", exclude={"inventory_id", "inventory_sha256"})
    ).removeprefix("sha256:")
    if inventory_id != "imgscivisinventory_" + identity[:32]:
        raise ValueError("science visual inventory ID does not bind its content")
    expected = content_sha256(inventory.model_dump(mode="json", exclude={"inventory_sha256"}))
    if inventory_sha256 != expected:
        raise ValueError("science visual inventory hash mismatch")


class LocalImageScienceVisualPatternInventory(FrozenModel):
    schema_version: Literal["local-image-science-visual-pattern-inventory/1.0"]
    inventory_id: str = Field(pattern=r"^imgscivisinventory_[0-9a-f]{32}$")
    pilot_result: ImageEvaluationArtifactMember
    pilot_result_sha256: Sha256
    reviews: tuple[ScienceVisualPatternReview, ...] = Field(min_length=1, max_length=512)
    primitive_recommendations: tuple[ScienceRendererPrimitiveRecommendation, ...] = Field(
        max_length=32
    )
    lora_eligible_count: int = Field(ge=0, le=512)
    deterministic_renderer_count: int = Field(ge=0, le=512)
    excluded_count: int = Field(ge=0, le=512)
    created_at: datetime
    created_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    inventory_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_creation(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def immutable_inventory_is_coherent(self) -> LocalImageScienceVisualPatternInventory:
        _require_pointer(
            self.pilot_result,
            schema_ref=CORPUS_PILOT_RESULT_SCHEMA_REF,
            media_type="application/json",
            member_path="manifests/visual-pilot-result.json",
        )
        if self.pilot_result.sha256 != self.pilot_result_sha256:
            raise ValueError("science visual inventory result hash differs from its pointer")
        _validate_pattern_inventory_common(
            inventory=self,
            inventory_id=self.inventory_id,
            reviews=self.reviews,
            primitive_recommendations=self.primitive_recommendations,
            lora_eligible_count=self.lora_eligible_count,
            deterministic_renderer_count=self.deterministic_renderer_count,
            excluded_count=self.excluded_count,
            inventory_sha256=self.inventory_sha256,
        )
        return self


class LocalImageScienceVisualPatternInventoryV2(FrozenModel):
    """Reviewed pattern inventory with distinct file and semantic result hashes."""

    schema_version: Literal["local-image-science-visual-pattern-inventory/1.1"]
    inventory_id: str = Field(pattern=r"^imgscivisinventory_[0-9a-f]{32}$")
    pilot_result: ImageEvaluationArtifactMember
    pilot_result_file_sha256: Sha256
    pilot_result_semantic_sha256: Sha256
    reviews: tuple[ScienceVisualPatternReview, ...] = Field(min_length=1, max_length=512)
    primitive_recommendations: tuple[ScienceRendererPrimitiveRecommendation, ...] = Field(
        max_length=32
    )
    lora_eligible_count: int = Field(ge=0, le=512)
    deterministic_renderer_count: int = Field(ge=0, le=512)
    excluded_count: int = Field(ge=0, le=512)
    created_at: datetime
    created_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    inventory_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_creation(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def immutable_inventory_is_coherent(self) -> LocalImageScienceVisualPatternInventoryV2:
        _require_pointer(
            self.pilot_result,
            schema_ref=CORPUS_PILOT_RESULT_SCHEMA_REF,
            media_type="application/json",
            member_path="manifests/visual-pilot-result.json",
        )
        if self.pilot_result.sha256 != self.pilot_result_file_sha256:
            raise ValueError("science visual inventory file hash differs from its pointer")
        _validate_pattern_inventory_common(
            inventory=self,
            inventory_id=self.inventory_id,
            reviews=self.reviews,
            primitive_recommendations=self.primitive_recommendations,
            lora_eligible_count=self.lora_eligible_count,
            deterministic_renderer_count=self.deterministic_renderer_count,
            excluded_count=self.excluded_count,
            inventory_sha256=self.inventory_sha256,
        )
        return self


ScienceVisualRasterPatternFamily = Literal[
    "ASTRONOMICAL_SCENE",
    "FOSSIL",
    "GEOLOGIC_TEXTURE",
    "MICROSCOPIC_TEXTURE",
    "NATURAL_TEXTURE",
    "ORGANISM",
]

ScienceVisualRasterSuitabilityDecision = Literal[
    "EXCLUDED",
    "GPU_RASTER_ELIGIBLE",
    "PYTHON_SVG_REQUIRED",
]
ScienceVisualRasterSemanticAlignment = Literal["MISMATCH", "NOT_APPLICABLE", "VERIFIED"]
ScienceVisualRasterSuitabilityReason = Literal[
    "AUTHORITATIVE_STRUCTURE",
    "CAPTION_MISMATCH",
    "INSUFFICIENT_IMAGE_CONTENT",
    "NON_RASTER_STYLE",
    "PANEL_COMPOSITION",
    "REDACTION_OR_MASK",
    "TEXT_OR_LABEL",
]


class ScienceVisualRasterSuitabilityEntry(FrozenModel):
    """One second-pass decision for a previously LoRA-eligible crop.

    The original broad inventory remains immutable. This successor review is deliberately
    strict: only one verified, single-subject raster can carry a training caption.
    """

    candidate_id: str = Field(pattern=r"^imgsciviscandidate_[0-9a-f]{32}$")
    decision: ScienceVisualRasterSuitabilityDecision
    semantic_alignment: ScienceVisualRasterSemanticAlignment
    reasons: tuple[ScienceVisualRasterSuitabilityReason, ...] = Field(max_length=8)
    caption_en: str | None = Field(
        default=None,
        min_length=3,
        max_length=240,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9 ,.'()/_:-]{2,239}$",
    )
    caption_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def decision_is_safe_for_training(self) -> ScienceVisualRasterSuitabilityEntry:
        if self.reasons != tuple(sorted(set(self.reasons))):
            raise ValueError("science raster-suitability reasons must be sorted and unique")
        if self.decision == "GPU_RASTER_ELIGIBLE":
            if (
                self.semantic_alignment != "VERIFIED"
                or self.reasons
                or self.caption_en is None
                or self.caption_sha256 != text_sha256(self.caption_en)
            ):
                raise ValueError("GPU raster eligibility requires a verified exact caption")
        else:
            if self.caption_en is not None or self.caption_sha256 is not None:
                raise ValueError("non-GPU raster decision cannot carry a training caption")
            if not self.reasons:
                raise ValueError("non-GPU raster decision requires a disqualification reason")
            if self.semantic_alignment == "MISMATCH" and "CAPTION_MISMATCH" not in self.reasons:
                raise ValueError("caption mismatch requires its explicit reason")
        return self


class LocalImageScienceVisualRasterSuitabilityReview(FrozenModel):
    """Complete immutable second-pass audit of a pinned broad LoRA population."""

    schema_version: Literal["local-image-science-raster-suitability-review/1.0"]
    review_id: str = Field(pattern=r"^imgscivisrasterreview_[0-9a-f]{32}$")
    pattern_inventory: ImageEvaluationArtifactMember
    pattern_inventory_file_sha256: Sha256
    pattern_inventory_semantic_sha256: Sha256
    entries: tuple[ScienceVisualRasterSuitabilityEntry, ...] = Field(min_length=1, max_length=512)
    gpu_raster_eligible_count: int = Field(ge=0, le=512)
    python_svg_required_count: int = Field(ge=0, le=512)
    excluded_count: int = Field(ge=0, le=512)
    reviewed_at: datetime
    reviewed_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    review_sha256: Sha256

    @field_validator("reviewed_at")
    @classmethod
    def utc_review(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def complete_immutable_review_is_coherent(
        self,
    ) -> LocalImageScienceVisualRasterSuitabilityReview:
        _require_pointer(
            self.pattern_inventory,
            schema_ref=CORPUS_PATTERN_INVENTORY_V2_SCHEMA_REF,
            media_type="application/json",
            member_path="manifests/science-visual-pattern-inventory.json",
        )
        if self.pattern_inventory.sha256 != self.pattern_inventory_file_sha256:
            raise ValueError("science raster-suitability inventory file hash differs from pointer")
        entry_ids = tuple(value.candidate_id for value in self.entries)
        if entry_ids != tuple(sorted(set(entry_ids))):
            raise ValueError("science raster-suitability entries must be uniquely sorted")
        counts = Counter(value.decision for value in self.entries)
        if (
            self.gpu_raster_eligible_count != counts["GPU_RASTER_ELIGIBLE"]
            or self.python_svg_required_count != counts["PYTHON_SVG_REQUIRED"]
            or self.excluded_count != counts["EXCLUDED"]
        ):
            raise ValueError("science raster-suitability counts differ from entries")
        identity = content_sha256(
            self.model_dump(mode="json", exclude={"review_id", "review_sha256"})
        ).removeprefix("sha256:")
        if self.review_id != "imgscivisrasterreview_" + identity[:32]:
            raise ValueError("science raster-suitability review ID does not bind its content")
        expected = content_sha256(self.model_dump(mode="json", exclude={"review_sha256"}))
        if self.review_sha256 != expected:
            raise ValueError("science raster-suitability review hash mismatch")
        return self


class ScienceVisualRasterRefinementProposal(FrozenModel):
    """One reviewed panel-level crop derived from a pinned parent candidate."""

    refinement_id: str = Field(pattern=r"^imgscivisrefine_[0-9a-f]{32}$")
    parent_candidate_id: str = Field(pattern=r"^imgsciviscandidate_[0-9a-f]{32}$")
    crop_bounding_box: ImageEvaluationBoundingBox
    caption_en: str = Field(
        min_length=3,
        max_length=240,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9 ,.'()/_:-]{2,239}$",
    )
    caption_sha256: Sha256
    partition: Literal["TRAIN"]
    refinement_reasons: tuple[Literal["BORDER_TRIM", "PANEL_SPLIT"], ...] = Field(
        min_length=1,
        max_length=2,
    )

    @model_validator(mode="after")
    def proposal_is_canonical(self) -> ScienceVisualRasterRefinementProposal:
        if self.refinement_reasons != tuple(sorted(set(self.refinement_reasons))):
            raise ValueError("science raster refinement reasons must be uniquely sorted")
        if self.caption_sha256 != text_sha256(self.caption_en):
            raise ValueError("science raster refinement caption hash mismatch")
        if (
            self.crop_bounding_box.right - self.crop_bounding_box.left < 500
            or self.crop_bounding_box.bottom - self.crop_bounding_box.top < 500
        ):
            raise ValueError("science raster refinement crop is too small")
        identity = content_sha256(
            self.model_dump(mode="json", exclude={"refinement_id"})
        ).removeprefix("sha256:")
        if self.refinement_id != "imgscivisrefine_" + identity[:32]:
            raise ValueError("science raster refinement ID does not bind its content")
        return self


class LocalImageScienceVisualRasterRefinementPlan(FrozenModel):
    """Immutable review plan for train-only crops from natural-image panels."""

    schema_version: Literal["local-image-science-raster-refinement-plan/1.0"]
    refinement_plan_id: str = Field(pattern=r"^imgscivisrefineplan_[0-9a-f]{32}$")
    pattern_inventory: ImageEvaluationArtifactMember
    pattern_inventory_semantic_sha256: Sha256
    raster_suitability_review: ImageEvaluationArtifactMember
    raster_suitability_review_sha256: Sha256
    pilot_result: ImageEvaluationArtifactMember
    pilot_result_semantic_sha256: Sha256
    proposals: tuple[ScienceVisualRasterRefinementProposal, ...] = Field(
        min_length=1,
        max_length=1024,
    )
    created_at: datetime
    created_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    plan_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_creation(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def plan_is_coherent(self) -> LocalImageScienceVisualRasterRefinementPlan:
        _require_pointer(
            self.pattern_inventory,
            schema_ref=CORPUS_PATTERN_INVENTORY_V2_SCHEMA_REF,
            media_type="application/json",
            member_path="manifests/science-visual-pattern-inventory.json",
        )
        _require_pointer(
            self.raster_suitability_review,
            schema_ref=CORPUS_RASTER_SUITABILITY_REVIEW_SCHEMA_REF,
            media_type="application/json",
            member_path="manifests/science-raster-suitability-review.json",
        )
        _require_pointer(
            self.pilot_result,
            schema_ref=CORPUS_PILOT_RESULT_SCHEMA_REF,
            media_type="application/json",
            member_path="manifests/visual-pilot-result.json",
        )
        proposal_ids = tuple(value.refinement_id for value in self.proposals)
        if proposal_ids != tuple(sorted(set(proposal_ids))):
            raise ValueError("science raster refinements must be uniquely sorted")
        parent_boxes = tuple(
            (
                value.parent_candidate_id,
                value.crop_bounding_box.left,
                value.crop_bounding_box.top,
                value.crop_bounding_box.right,
                value.crop_bounding_box.bottom,
            )
            for value in self.proposals
        )
        if len(parent_boxes) != len(set(parent_boxes)):
            raise ValueError("science raster refinement plan repeats a crop")
        identity = content_sha256(
            self.model_dump(mode="json", exclude={"refinement_plan_id", "plan_sha256"})
        ).removeprefix("sha256:")
        if self.refinement_plan_id != "imgscivisrefineplan_" + identity[:32]:
            raise ValueError("science raster refinement plan ID does not bind its content")
        expected = content_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))
        if self.plan_sha256 != expected:
            raise ValueError("science raster refinement plan hash mismatch")
        return self


class ScienceVisualReviewedCropMember(FrozenModel):
    """One exact post-review PNG member; the containing Artifact owns its bytes."""

    candidate_id: str = Field(pattern=r"^imgsciviscandidate_[0-9a-f]{32}$")
    document_id: str = Field(pattern=r"^sciencedoc_[0-9a-f]{32}$")
    physical_page: int = Field(ge=1, le=512)
    exam_group_sha256: Sha256
    partition: ScienceVisualPartition
    pattern_family: ScienceVisualRasterPatternFamily
    member_path: str = Field(pattern=r"^crops/imgsciviscandidate_[0-9a-f]{32}\.png$")
    media_type: Literal["image/png"]
    width_px: int = Field(ge=16, le=10_000)
    height_px: int = Field(ge=16, le=10_000)
    size_bytes: int = Field(ge=64, le=64 * 1024 * 1024)
    sha256: Sha256
    caption_en: str = Field(
        min_length=3,
        max_length=240,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9 ,.'()/_:-]{2,239}$",
    )
    caption_sha256: Sha256
    perceptual_hash: str = Field(pattern=r"^[0-9a-f]{16}$")

    @model_validator(mode="after")
    def immutable_member_is_coherent(self) -> ScienceVisualReviewedCropMember:
        if self.member_path != f"crops/{self.candidate_id}.png":
            raise ValueError("science visual crop member path differs from its candidate")
        if self.caption_sha256 != text_sha256(self.caption_en):
            raise ValueError("science visual crop caption hash mismatch")
        return self


class LocalImageScienceVisualCropSet(FrozenModel):
    """Group-deduplicated reviewed crop set for one bounded internal micro probe."""

    schema_version: Literal["local-image-science-visual-crop-set/1.0"]
    crop_set_id: str = Field(pattern=r"^imgsciviscropset_[0-9a-f]{32}$")
    pattern_inventory: ImageEvaluationArtifactMember
    pattern_inventory_semantic_sha256: Sha256
    pilot_plan: ImageEvaluationArtifactMember
    pilot_plan_sha256: Sha256
    pilot_result: ImageEvaluationArtifactMember
    pilot_result_semantic_sha256: Sha256
    training_authorization: ImageEvaluationArtifactMember
    members: tuple[ScienceVisualReviewedCropMember, ...] = Field(min_length=12, max_length=96)
    created_at: datetime
    created_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    crop_set_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_creation(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def immutable_crop_set_is_coherent(self) -> LocalImageScienceVisualCropSet:
        _require_pointer(
            self.pattern_inventory,
            schema_ref=CORPUS_PATTERN_INVENTORY_V2_SCHEMA_REF,
            media_type="application/json",
            member_path="manifests/science-visual-pattern-inventory.json",
        )
        _require_pointer(
            self.pilot_plan,
            schema_ref=CORPUS_PILOT_PLAN_V2_SCHEMA_REF,
            media_type="application/json",
            member_path="manifests/visual-pilot-plan.json",
        )
        _require_pointer(
            self.pilot_result,
            schema_ref=CORPUS_PILOT_RESULT_SCHEMA_REF,
            media_type="application/json",
            member_path="manifests/visual-pilot-result.json",
        )
        _require_pointer(
            self.training_authorization,
            schema_ref=CORPUS_AUTHORIZATION_SCHEMA_REF,
            media_type="application/json",
            member_path="manifests/science-corpus-training-authorization.json",
        )
        member_ids = tuple(value.candidate_id for value in self.members)
        if member_ids != tuple(sorted(set(member_ids))):
            raise ValueError("science visual crop members must be uniquely sorted")
        for label, values in (
            ("documents", (value.document_id for value in self.members)),
            ("exam groups", (value.exam_group_sha256 for value in self.members)),
            ("crop hashes", (value.sha256 for value in self.members)),
            ("perceptual hashes", (value.perceptual_hash for value in self.members)),
        ):
            sequence = tuple(values)
            if len(sequence) != len(set(sequence)):
                raise ValueError(f"science visual crop set repeats {label}")
        partition_counts = Counter(value.partition for value in self.members)
        if (
            partition_counts["TRAIN"] < 12
            or partition_counts["VALIDATION"] < 1
            or partition_counts["HOLDOUT"] < 2
        ):
            raise ValueError("science visual crop partitions are too small")
        identity = content_sha256(
            self.model_dump(mode="json", exclude={"crop_set_id", "crop_set_sha256"})
        ).removeprefix("sha256:")
        if self.crop_set_id != "imgsciviscropset_" + identity[:32]:
            raise ValueError("science visual crop-set ID does not bind its content")
        expected = content_sha256(self.model_dump(mode="json", exclude={"crop_set_sha256"}))
        if self.crop_set_sha256 != expected:
            raise ValueError("science visual crop-set hash mismatch")
        return self


class LocalImageScienceVisualCropSetV2(FrozenModel):
    """Successor crop set that pins the second-pass raster suitability audit.

    This is deliberately additive: V1 remains the immutable record of the
    broad-review micro probe.  Any future raster LoRA run must use this
    successor and therefore cannot silently treat a diagram, montage, or
    redacted crop as a GPU-training image.
    """

    schema_version: Literal["local-image-science-visual-crop-set/1.1"]
    crop_set_id: str = Field(pattern=r"^imgsciviscropset_[0-9a-f]{32}$")
    pattern_inventory: ImageEvaluationArtifactMember
    pattern_inventory_semantic_sha256: Sha256
    raster_suitability_review: ImageEvaluationArtifactMember
    raster_suitability_review_sha256: Sha256
    pilot_plan: ImageEvaluationArtifactMember
    pilot_plan_sha256: Sha256
    pilot_result: ImageEvaluationArtifactMember
    pilot_result_semantic_sha256: Sha256
    training_authorization: ImageEvaluationArtifactMember
    members: tuple[ScienceVisualReviewedCropMember, ...] = Field(min_length=12, max_length=96)
    created_at: datetime
    created_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    crop_set_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_creation(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def immutable_crop_set_is_coherent(self) -> LocalImageScienceVisualCropSetV2:
        _require_pointer(
            self.pattern_inventory,
            schema_ref=CORPUS_PATTERN_INVENTORY_V2_SCHEMA_REF,
            media_type="application/json",
            member_path="manifests/science-visual-pattern-inventory.json",
        )
        _require_pointer(
            self.raster_suitability_review,
            schema_ref=CORPUS_RASTER_SUITABILITY_REVIEW_SCHEMA_REF,
            media_type="application/json",
            member_path="manifests/science-raster-suitability-review.json",
        )
        _require_pointer(
            self.pilot_plan,
            schema_ref=CORPUS_PILOT_PLAN_V2_SCHEMA_REF,
            media_type="application/json",
            member_path="manifests/visual-pilot-plan.json",
        )
        _require_pointer(
            self.pilot_result,
            schema_ref=CORPUS_PILOT_RESULT_SCHEMA_REF,
            media_type="application/json",
            member_path="manifests/visual-pilot-result.json",
        )
        _require_pointer(
            self.training_authorization,
            schema_ref=CORPUS_AUTHORIZATION_SCHEMA_REF,
            media_type="application/json",
            member_path="manifests/science-corpus-training-authorization.json",
        )
        member_ids = tuple(value.candidate_id for value in self.members)
        if member_ids != tuple(sorted(set(member_ids))):
            raise ValueError("science visual crop members must be uniquely sorted")
        for label, values in (
            ("documents", (value.document_id for value in self.members)),
            ("exam groups", (value.exam_group_sha256 for value in self.members)),
            ("crop hashes", (value.sha256 for value in self.members)),
            ("perceptual hashes", (value.perceptual_hash for value in self.members)),
        ):
            sequence = tuple(values)
            if len(sequence) != len(set(sequence)):
                raise ValueError(f"science visual crop set repeats {label}")
        partition_counts = Counter(value.partition for value in self.members)
        if (
            partition_counts["TRAIN"] < 12
            or partition_counts["VALIDATION"] < 1
            or partition_counts["HOLDOUT"] < 2
        ):
            raise ValueError("science visual crop partitions are too small")
        identity = content_sha256(
            self.model_dump(mode="json", exclude={"crop_set_id", "crop_set_sha256"})
        ).removeprefix("sha256:")
        if self.crop_set_id != "imgsciviscropset_" + identity[:32]:
            raise ValueError("science visual crop-set ID does not bind its content")
        expected = content_sha256(self.model_dump(mode="json", exclude={"crop_set_sha256"}))
        if self.crop_set_sha256 != expected:
            raise ValueError("science visual crop-set hash mismatch")
        return self


def validate_science_visual_crop_set(
    *,
    authorization: LocalImageScienceCorpusTrainingAuthorization,
    plan: LocalImageScienceCorpusVisualPilotPlanV2,
    result: LocalImageScienceCorpusVisualPilotResult,
    inventory: LocalImageScienceVisualPatternInventoryV2,
    crop_set: LocalImageScienceVisualCropSet,
) -> None:
    """Bind every crop member to its approved source, review, partition, and bytes."""

    validate_science_visual_authorization_plan(authorization, plan)
    validate_science_visual_pilot_result(plan, result)
    validate_science_visual_pattern_inventory_v2(result, inventory)
    if (
        crop_set.pattern_inventory_semantic_sha256 != inventory.inventory_sha256
        or crop_set.pilot_plan_sha256 != plan.plan_sha256
        or crop_set.pilot_result_semantic_sha256 != result.result_sha256
        or crop_set.pilot_result != inventory.pilot_result
        or crop_set.training_authorization != plan.training_authorization
        or crop_set.training_authorization.sha256
        != content_sha256(authorization.model_dump(mode="json"))
    ):
        raise ValueError("science visual crop-set source hash differs")
    sources = {value.document_id: value for value in plan.selected_sources}
    candidates = {value.candidate_id: value for value in result.visual_candidates}
    reviews = {value.candidate_id: value for value in inventory.reviews}
    for member in crop_set.members:
        source = sources.get(member.document_id)
        candidate = candidates.get(member.candidate_id)
        review = reviews.get(member.candidate_id)
        if (
            source is None
            or candidate is None
            or review is None
            or candidate.document_id != member.document_id
            or candidate.physical_page != member.physical_page
            or candidate.member_path != member.member_path
            or candidate.sha256 != member.sha256
            or source.exam_group_sha256 != member.exam_group_sha256
            or source.partition != member.partition
            or review.decision != "LORA_ELIGIBLE"
            or review.pattern_family != member.pattern_family
            or review.caption_en != member.caption_en
            or review.caption_sha256 != member.caption_sha256
        ):
            raise ValueError("science visual crop member differs from reviewed evidence")


def validate_science_visual_crop_set_v2(
    *,
    authorization: LocalImageScienceCorpusTrainingAuthorization,
    plan: LocalImageScienceCorpusVisualPilotPlanV2,
    result: LocalImageScienceCorpusVisualPilotResult,
    inventory: LocalImageScienceVisualPatternInventoryV2,
    raster_suitability_review: LocalImageScienceVisualRasterSuitabilityReview,
    crop_set: LocalImageScienceVisualCropSetV2,
) -> None:
    """Require each successor crop to be a verified GPU-raster candidate.

    The maps make the cross-artifact binding linear in the bounded member
    count; no binary image data is materialized here.
    """

    # Bind the common immutable pilot chain first.  A V1-shaped temporary is
    # intentionally not constructed: V2 must keep its raster-review pointer
    # in the canonical identity rather than merely borrowing V1 validation.
    validate_science_visual_authorization_plan(authorization, plan)
    validate_science_visual_pilot_result(plan, result)
    validate_science_visual_pattern_inventory_v2(result, inventory)
    validate_science_visual_raster_suitability_review(inventory, raster_suitability_review)
    if (
        crop_set.pattern_inventory_semantic_sha256 != inventory.inventory_sha256
        or crop_set.raster_suitability_review_sha256 != raster_suitability_review.review_sha256
        or raster_suitability_review.pattern_inventory != crop_set.pattern_inventory
        or crop_set.raster_suitability_review.sha256
        != content_sha256(raster_suitability_review.model_dump(mode="json"))
        or crop_set.pilot_plan_sha256 != plan.plan_sha256
        or crop_set.pilot_result_semantic_sha256 != result.result_sha256
        or crop_set.pilot_result != inventory.pilot_result
        or crop_set.training_authorization != plan.training_authorization
        or crop_set.training_authorization.sha256
        != content_sha256(authorization.model_dump(mode="json"))
    ):
        raise ValueError("science raster-reviewed crop-set source hash differs")
    sources = {value.document_id: value for value in plan.selected_sources}
    candidates = {value.candidate_id: value for value in result.visual_candidates}
    reviews = {value.candidate_id: value for value in inventory.reviews}
    raster_reviews = {value.candidate_id: value for value in raster_suitability_review.entries}
    for member in crop_set.members:
        source = sources.get(member.document_id)
        candidate = candidates.get(member.candidate_id)
        review = reviews.get(member.candidate_id)
        raster_review = raster_reviews.get(member.candidate_id)
        if (
            source is None
            or candidate is None
            or review is None
            or raster_review is None
            or candidate.document_id != member.document_id
            or candidate.physical_page != member.physical_page
            or candidate.member_path != member.member_path
            or candidate.sha256 != member.sha256
            or source.exam_group_sha256 != member.exam_group_sha256
            or source.partition != member.partition
            or review.decision != "LORA_ELIGIBLE"
            or review.pattern_family != member.pattern_family
            or raster_review.decision != "GPU_RASTER_ELIGIBLE"
            or raster_review.semantic_alignment != "VERIFIED"
            or raster_review.caption_en != member.caption_en
            or raster_review.caption_sha256 != member.caption_sha256
        ):
            raise ValueError("science crop member differs from raster suitability evidence")


def validate_science_visual_raster_refinement_plan(
    *,
    result: LocalImageScienceCorpusVisualPilotResult,
    inventory: LocalImageScienceVisualPatternInventoryV2,
    raster_suitability_review: LocalImageScienceVisualRasterSuitabilityReview,
    plan: LocalImageScienceVisualRasterRefinementPlan,
) -> None:
    """Bind train-only panel splits to non-authoritative reviewed raster parents."""

    validate_science_visual_pattern_inventory_v2(result, inventory)
    validate_science_visual_raster_suitability_review(inventory, raster_suitability_review)
    if (
        plan.pattern_inventory != raster_suitability_review.pattern_inventory
        or plan.pattern_inventory_semantic_sha256 != inventory.inventory_sha256
        or plan.raster_suitability_review.sha256
        != content_sha256(raster_suitability_review.model_dump(mode="json"))
        or plan.raster_suitability_review_sha256 != raster_suitability_review.review_sha256
        or plan.pilot_result != inventory.pilot_result
        or plan.pilot_result_semantic_sha256 != result.result_sha256
    ):
        raise ValueError("science raster refinement plan source hash differs")
    candidates = {value.candidate_id: value for value in result.visual_candidates}
    broad_reviews = {value.candidate_id: value for value in inventory.reviews}
    raster_reviews = {value.candidate_id: value for value in raster_suitability_review.entries}
    for proposal in plan.proposals:
        candidate = candidates.get(proposal.parent_candidate_id)
        broad_review = broad_reviews.get(proposal.parent_candidate_id)
        raster_review = raster_reviews.get(proposal.parent_candidate_id)
        if (
            candidate is None
            or broad_review is None
            or raster_review is None
            or broad_review.decision != "LORA_ELIGIBLE"
            or candidate.authority_class != "NON_AUTHORITATIVE_RASTER_STYLE"
            or candidate.representation_kind in {"PLOT", "TABLE"}
            or (
                raster_review.decision == "EXCLUDED"
                and "PANEL_COMPOSITION" not in raster_review.reasons
            )
            or raster_review.decision not in {"EXCLUDED", "GPU_RASTER_ELIGIBLE"}
        ):
            raise ValueError("science raster refinement parent is not an eligible raster source")
        if raster_review.decision == "EXCLUDED":
            if "PANEL_SPLIT" not in proposal.refinement_reasons:
                raise ValueError("science panel refinement requires PANEL_SPLIT")
        elif proposal.refinement_reasons != ("BORDER_TRIM",):
            raise ValueError("single raster refinement may only trim a border")


def _validate_pattern_inventory_against_result(
    result: LocalImageScienceCorpusVisualPilotResult,
    *,
    semantic_sha256: Sha256,
    reviews: tuple[ScienceVisualPatternReview, ...],
) -> None:
    if result.status != "SUCCEEDED" or result.result_sha256 != semantic_sha256:
        raise ValueError("science visual inventory does not bind a successful pilot result")
    candidates = {value.candidate_id: value for value in result.visual_candidates}
    candidate_ids = set(candidates)
    review_ids = {value.candidate_id for value in reviews}
    if review_ids != candidate_ids:
        raise ValueError("science visual inventory does not review every candidate exactly once")
    for review in reviews:
        candidate = candidates[review.candidate_id]
        if review.decision == "LORA_ELIGIBLE" and (
            candidate.authority_class == "AUTHORITATIVE_DETERMINISTIC_GEOMETRY"
            or candidate.representation_kind in {"PLOT", "TABLE"}
        ):
            raise ValueError("science visual LoRA review selects authoritative content")
        if (
            review.decision == "DETERMINISTIC_RENDERER_ONLY"
            and candidate.authority_class == "NON_AUTHORITATIVE_RASTER_STYLE"
        ):
            raise ValueError("science visual renderer review selects non-authoritative content")


def validate_science_visual_pattern_inventory(
    result: LocalImageScienceCorpusVisualPilotResult,
    inventory: LocalImageScienceVisualPatternInventory,
) -> None:
    _validate_pattern_inventory_against_result(
        result,
        semantic_sha256=inventory.pilot_result_sha256,
        reviews=inventory.reviews,
    )


def validate_science_visual_pattern_inventory_v2(
    result: LocalImageScienceCorpusVisualPilotResult,
    inventory: LocalImageScienceVisualPatternInventoryV2,
) -> None:
    _validate_pattern_inventory_against_result(
        result,
        semantic_sha256=inventory.pilot_result_semantic_sha256,
        reviews=inventory.reviews,
    )


def validate_science_visual_raster_suitability_review(
    inventory: LocalImageScienceVisualPatternInventoryV2,
    review: LocalImageScienceVisualRasterSuitabilityReview,
) -> None:
    """Require a complete second-pass audit of exactly the broad raster population."""

    if review.pattern_inventory_semantic_sha256 != inventory.inventory_sha256:
        raise ValueError("science raster-suitability review source binding differs")
    eligible_ids = {
        value.candidate_id for value in inventory.reviews if value.decision == "LORA_ELIGIBLE"
    }
    actual_ids = {value.candidate_id for value in review.entries}
    if actual_ids != eligible_ids:
        raise ValueError(
            "science raster-suitability review does not cover every broad raster candidate"
        )


def validate_science_visual_authorization_plan(
    authorization: LocalImageScienceCorpusTrainingAuthorization,
    plan: LocalImageScienceCorpusVisualPilotPlan | LocalImageScienceCorpusVisualPilotPlanV2,
) -> None:
    if (
        authorization.corpus_manifest != plan.corpus_manifest
        or authorization.corpus_id != plan.corpus_id
        or authorization.corpus_manifest_sha256 != plan.corpus_manifest_sha256
        or authorization.acquisition_sha256 != plan.acquisition_sha256
        or authorization.resolution_sha256 != plan.resolution_sha256
        or authorization.resolution_policy_id != plan.resolution_policy_id
        or authorization.resolution_policy_sha256 != plan.resolution_policy_sha256
        or content_sha256(authorization.model_dump(mode="json"))
        != plan.training_authorization.sha256
    ):
        raise ValueError("science visual plan is outside its training authorization")
    _require_pointer(
        plan.training_authorization,
        schema_ref=CORPUS_AUTHORIZATION_SCHEMA_REF,
        media_type="application/json",
        member_path="manifests/science-corpus-training-authorization.json",
    )


def validate_source_member_path(value: str) -> None:
    """Shared defensive path check used by the future staging adapter."""

    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("science visual source member path is unsafe")
    if "\\" in value or re.search(r"[\x00-\x1f\x7f]", value):
        raise ValueError("science visual source member path is unsafe")
