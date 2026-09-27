"""Contracts for corpus-grounded science visual subject coverage benchmarks."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.models import (
    FrozenModel,
    ImageEvaluationArtifactMember,
    LocalImageModelPointer,
    Sha256,
    content_sha256,
    text_sha256,
)

SUBJECT_INVENTORY_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-visual-subject-inventory/1.0"
)
SUBJECT_BENCHMARK_PLAN_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-visual-subject-benchmark-plan/1.0"
)
SUBJECT_BENCHMARK_COMMAND_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-visual-subject-benchmark-command/1.0"
)
SUBJECT_BENCHMARK_RESULT_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-visual-subject-benchmark-result/1.0"
)
SUBJECT_BENCHMARK_REVIEW_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-visual-subject-benchmark-review/1.0"
)
TRAINING_AUTHORIZATION_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-training-authorization/1.0"
)
PATTERN_INVENTORY_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-visual-campaign-pattern-inventory/1.0"
)
ADAPTER_MANIFEST_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-campaign-lora-micro-adapter-manifest/1.1"
)

ScienceVisualSubjectFamily = Literal[
    "ABSTRACT_SCIENCE_MODEL",
    "EARTH_SPACE",
    "LAB_APPARATUS",
    "LIVING_ORGANISM",
    "MICROSCOPIC_STRUCTURE",
    "PHYSICAL_OBJECT",
    "REAL_WORLD_SCENE",
]
ScienceVisualSubjectRoute = Literal["BLOCKED", "HYBRID", "LORA_RASTER", "PYTHON_SVG"]
ScienceVisualSubjectPrimitive = Literal[
    "APPARATUS",
    "AXIS_PLOT",
    "CELL_CROSS_SECTION",
    "CIRCUIT",
    "CONTENT_TABLE",
    "FLOW_DIAGRAM",
    "GENERIC_LABELLED_DIAGRAM",
    "GEOLOGIC_SECTION",
    "MAP_BOUNDARY",
    "ORBITAL_SYSTEM",
    "PARTICLE_SYSTEM",
    "RAY_DIAGRAM",
    "TIMELINE",
    "VECTOR_FIELD",
]
ScienceVisualSubjectRepresentation = Literal[
    "APPARATUS",
    "BAR_GRAPH",
    "COMPOSITE",
    "CROSS_SECTION",
    "DIAGRAM",
    "FLOW",
    "LINE_GRAPH",
    "MAP",
    "NONE",
    "OTHER_OBSERVED",
    "PARTICLE_MODEL",
    "PHOTOGRAPH",
    "SCATTER_PLOT",
    "TABLE",
    "TIMELINE",
]


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("timestamp must be UTC")
    return value


def _safe_text(value: str) -> str:
    if value != value.strip() or value != unicodedata.normalize("NFC", value):
        raise ValueError("text must be trimmed NFC")
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ValueError("text contains a control character")
    return value


def _safe_ascii_text(value: str) -> str:
    value = _safe_text(value)
    if not value.isascii():
        raise ValueError("text must be ASCII")
    return value


def _require_pointer(
    pointer: ImageEvaluationArtifactMember,
    *,
    schema_ref: str,
    media_type: str = "application/json",
) -> None:
    if pointer.schema_ref != schema_ref or pointer.media_type != media_type:
        raise ValueError("subject benchmark artifact pointer contract mismatch")


class ScienceVisualSubjectSourceReference(FrozenModel):
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    accepted_analysis_result: ImageEvaluationArtifactMember
    extraction_result: ImageEvaluationArtifactMember
    item_proposal_id: str = Field(pattern=r"^itemproposal_[0-9a-f]{32}$")
    visual_pattern_id: str = Field(pattern=r"^visualpattern_[0-9a-f]{32}$")
    source_anchor_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    representation_kind: ScienceVisualSubjectRepresentation
    rendering_mode: Literal["MIXED", "RASTER", "TEXT_ONLY", "VECTOR_LIKE"]
    composition_summary_sha256: Sha256
    reconstruction_guidance_sha256: Sha256

    @model_validator(mode="after")
    def exact_source_reference(self) -> Self:
        _require_pointer(
            self.accepted_analysis_result,
            schema_ref="eom://schemas/knowledge/knowledge-analysis-result/9.0",
        )
        _require_pointer(
            self.extraction_result,
            schema_ref="eom://schemas/legacy-assessment/legacy-item-extraction-result/1.0",
        )
        if self.source_anchor_ids != tuple(sorted(set(self.source_anchor_ids))):
            raise ValueError("source anchor IDs must be uniquely sorted")
        if any(
            re.fullmatch(r"assessmentanchor_[0-9a-f]{32}", value) is None
            for value in self.source_anchor_ids
        ):
            raise ValueError("source anchor ID is invalid")
        return self

    @property
    def observation_key(self) -> tuple[str, str, str]:
        return self.item_revision_id, self.item_proposal_id, self.visual_pattern_id


class ScienceVisualSubject(FrozenModel):
    subject_id: str = Field(pattern=r"^imgscisubject_[0-9a-f]{32}$")
    subject_key: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")
    label_ko: str = Field(min_length=1, max_length=120)
    label_en: str = Field(min_length=1, max_length=160, pattern=r"^[ -~]+$")
    aliases_ko: tuple[str, ...] = Field(min_length=1, max_length=32)
    family: ScienceVisualSubjectFamily
    render_route: ScienceVisualSubjectRoute
    renderer_primitive: ScienceVisualSubjectPrimitive | None
    raster_prompt_en: str | None = Field(default=None, min_length=20, max_length=2000)
    raster_prompt_sha256: Sha256 | None
    blocked_reason: (
        Literal[
            "COPYRIGHT_REPRODUCTION_RISK",
            "NO_SAFE_RENDER_ROUTE",
            "POLICY_PROHIBITED_CONTENT",
        ]
        | None
    )
    references: tuple[ScienceVisualSubjectSourceReference, ...] = Field(
        min_length=1, max_length=512
    )

    @field_validator("label_ko", "aliases_ko")
    @classmethod
    def safe_korean_text(cls, value: str | tuple[str, ...]) -> str | tuple[str, ...]:
        if isinstance(value, str):
            return _safe_text(value)
        return tuple(_safe_text(item) for item in value)

    @field_validator("label_en")
    @classmethod
    def safe_english_label(cls, value: str) -> str:
        return _safe_ascii_text(value)

    @field_validator("raster_prompt_en")
    @classmethod
    def safe_prompt(cls, value: str | None) -> str | None:
        return None if value is None else _safe_ascii_text(value)

    @model_validator(mode="after")
    def route_and_sources_are_closed(self) -> Self:
        identity = content_sha256(self.subject_key).removeprefix("sha256:")[:32]
        if self.subject_id != f"imgscisubject_{identity}":
            raise ValueError("subject ID does not match the subject key")
        if self.aliases_ko != tuple(sorted(set(self.aliases_ko))):
            raise ValueError("subject aliases must be uniquely sorted")
        keys = tuple(reference.observation_key for reference in self.references)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("subject references must be uniquely sorted")
        has_raster = self.raster_prompt_en is not None
        if self.raster_prompt_sha256 != (
            text_sha256(self.raster_prompt_en) if self.raster_prompt_en is not None else None
        ):
            raise ValueError("subject raster prompt hash mismatch")
        if self.render_route == "LORA_RASTER":
            valid = has_raster and self.renderer_primitive is None and self.blocked_reason is None
        elif self.render_route == "PYTHON_SVG":
            valid = (
                not has_raster
                and self.renderer_primitive is not None
                and self.blocked_reason is None
            )
        elif self.render_route == "HYBRID":
            valid = (
                has_raster and self.renderer_primitive is not None and self.blocked_reason is None
            )
        else:
            valid = (
                not has_raster
                and self.renderer_primitive is None
                and self.blocked_reason is not None
            )
        if not valid:
            raise ValueError("subject fields do not match the render route")
        return self


class ScienceVisualSubjectOmission(FrozenModel):
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_proposal_id: str = Field(pattern=r"^itemproposal_[0-9a-f]{32}$")
    visual_pattern_id: str = Field(pattern=r"^visualpattern_[0-9a-f]{32}$")
    reason: Literal["NO_RENDERED_SUBJECT", "TEXT_ONLY_PATTERN"]

    @property
    def observation_key(self) -> tuple[str, str, str]:
        return self.item_revision_id, self.item_proposal_id, self.visual_pattern_id


class LocalImageScienceVisualSubjectInventory(FrozenModel):
    schema_version: Literal["local-image-science-visual-subject-inventory/1.0"]
    inventory_id: str = Field(pattern=r"^imgscisubjectinventory_[0-9a-f]{32}$")
    inventory_revision_id: str = Field(pattern=r"^imgscisubjectinventoryrev_[0-9a-f]{32}$")
    revision_number: int = Field(ge=1, le=100_000)
    previous_revision_id: str | None = Field(pattern=r"^imgscisubjectinventoryrev_[0-9a-f]{32}$")
    training_authorization: ImageEvaluationArtifactMember
    pattern_inventory: ImageEvaluationArtifactMember
    target_set_sha256: Sha256
    source_item_count: int = Field(ge=1, le=1_000_000)
    source_visual_observation_count: int = Field(ge=1, le=1_000_000)
    covered_visual_observation_count: int = Field(ge=0, le=1_000_000)
    subjects: tuple[ScienceVisualSubject, ...] = Field(min_length=1, max_length=256)
    omissions: tuple[ScienceVisualSubjectOmission, ...] = Field(max_length=1024)
    created_at: datetime
    created_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    inventory_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_created(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def complete_unique_subject_index(self) -> Self:
        _require_pointer(
            self.training_authorization,
            schema_ref=TRAINING_AUTHORIZATION_SCHEMA_REF,
        )
        _require_pointer(self.pattern_inventory, schema_ref=PATTERN_INVENTORY_SCHEMA_REF)
        if (self.revision_number == 1) != (self.previous_revision_id is None):
            raise ValueError("subject inventory revision chain is inconsistent")
        keys = tuple(subject.subject_key for subject in self.subjects)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("subjects must be uniquely sorted by subject key")
        ids = tuple(subject.subject_id for subject in self.subjects)
        if len(ids) != len(set(ids)):
            raise ValueError("subject IDs must be unique")
        references = {
            reference.observation_key
            for subject in self.subjects
            for reference in subject.references
        }
        omission_keys = tuple(omission.observation_key for omission in self.omissions)
        if omission_keys != tuple(sorted(set(omission_keys))):
            raise ValueError("subject omissions must be uniquely sorted")
        if references.intersection(omission_keys):
            raise ValueError("covered observations cannot also be omitted")
        if self.covered_visual_observation_count != len(references):
            raise ValueError("covered visual observation count mismatch")
        if len(references) + len(omission_keys) != self.source_visual_observation_count:
            raise ValueError("subject inventory does not close the source observation set")
        expected = content_sha256(self.model_dump(mode="json", exclude={"inventory_sha256"}))
        if self.inventory_sha256 != expected:
            raise ValueError("subject inventory hash mismatch")
        return self


class ScienceVisualSubjectBenchmarkCase(FrozenModel):
    case_id: str = Field(pattern=r"^imgscisubjectcase_[0-9a-f]{32}$")
    subject_id: str = Field(pattern=r"^imgscisubject_[0-9a-f]{32}$")
    render_route: ScienceVisualSubjectRoute
    case_kind: Literal["GPU_POLICY_NEGATIVE", "QUALITY", "ROUTE"]
    prompt_en: str | None = Field(default=None, min_length=20, max_length=2000)
    prompt_sha256: Sha256 | None
    negative_prompt_en: str | None = Field(default=None, min_length=1, max_length=2000)
    negative_prompt_sha256: Sha256 | None
    seed: int | None = Field(default=None, ge=0, le=2_147_483_647)
    renderer_primitive: ScienceVisualSubjectPrimitive | None
    expected_outcome: Literal["BASE_ADAPTER_PAIR", "DETERMINISTIC_RENDERED", "POLICY_REJECTED"]

    @field_validator("prompt_en", "negative_prompt_en")
    @classmethod
    def safe_prompt(cls, value: str | None) -> str | None:
        return None if value is None else _safe_ascii_text(value)

    @model_validator(mode="after")
    def route_specific_case(self) -> Self:
        if self.prompt_sha256 != (
            None if self.prompt_en is None else text_sha256(self.prompt_en)
        ) or self.negative_prompt_sha256 != (
            None if self.negative_prompt_en is None else text_sha256(self.negative_prompt_en)
        ):
            raise ValueError("benchmark case prompt hash mismatch")
        identity = content_sha256(
            {"subject_id": self.subject_id, "case_kind": self.case_kind}
        ).removeprefix("sha256:")[:32]
        if self.case_id != f"imgscisubjectcase_{identity}":
            raise ValueError("benchmark case ID mismatch")
        has_generation = (
            self.prompt_en is not None
            and self.negative_prompt_en is not None
            and self.seed is not None
        )
        if self.case_kind == "QUALITY":
            valid = (
                self.render_route in {"HYBRID", "LORA_RASTER"}
                and has_generation
                and self.expected_outcome == "BASE_ADAPTER_PAIR"
                and (
                    (self.render_route == "LORA_RASTER" and self.renderer_primitive is None)
                    or (self.render_route == "HYBRID" and self.renderer_primitive is not None)
                )
            )
        elif self.case_kind == "ROUTE":
            valid = (
                self.render_route == "PYTHON_SVG"
                and not has_generation
                and self.prompt_en is None
                and self.negative_prompt_en is None
                and self.seed is None
                and self.renderer_primitive is not None
                and self.expected_outcome == "DETERMINISTIC_RENDERED"
            )
        else:
            valid = (
                self.render_route == "PYTHON_SVG"
                and has_generation
                and self.renderer_primitive is not None
                and self.expected_outcome == "POLICY_REJECTED"
            )
        if not valid:
            raise ValueError("benchmark case fields do not match the case kind")
        return self


class LocalImageScienceVisualSubjectBenchmarkPlan(FrozenModel):
    schema_version: Literal["local-image-science-visual-subject-benchmark-plan/1.0"]
    plan_id: str = Field(pattern=r"^imgscisubjectbenchmark_[0-9a-f]{32}$")
    subject_inventory: ImageEvaluationArtifactMember
    subject_inventory_sha256: Sha256
    base_model: LocalImageModelPointer
    adapter_manifest: ImageEvaluationArtifactMember
    generation_width_px: Literal[800]
    generation_height_px: Literal[504]
    delivery_width_px: Literal[800]
    delivery_height_px: Literal[500]
    inference_steps: int = Field(ge=1, le=100)
    guidance_scale_milli: int = Field(ge=1000, le=20_000)
    cases: tuple[ScienceVisualSubjectBenchmarkCase, ...] = Field(min_length=1, max_length=256)
    created_at: datetime
    created_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    plan_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_created(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def pinned_unique_plan(self) -> Self:
        _require_pointer(self.subject_inventory, schema_ref=SUBJECT_INVENTORY_SCHEMA_REF)
        _require_pointer(self.adapter_manifest, schema_ref=ADAPTER_MANIFEST_SCHEMA_REF)
        if self.subject_inventory_sha256 != self.subject_inventory.sha256:
            raise ValueError("subject inventory hash pin mismatch")
        case_ids = tuple(case.case_id for case in self.cases)
        if case_ids != tuple(sorted(set(case_ids))):
            raise ValueError("benchmark cases must be uniquely sorted")
        identity = content_sha256(
            self.model_dump(
                mode="json", exclude={"plan_id", "created_at", "created_by", "plan_sha256"}
            )
        ).removeprefix("sha256:")[:32]
        if self.plan_id != f"imgscisubjectbenchmark_{identity}":
            raise ValueError("subject benchmark plan ID mismatch")
        expected = content_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))
        if self.plan_sha256 != expected:
            raise ValueError("subject benchmark plan hash mismatch")
        return self


class LocalImageScienceVisualSubjectBenchmarkCommand(FrozenModel):
    schema_version: Literal["local-image-science-visual-subject-benchmark-command/1.0"]
    run_id: str = Field(pattern=r"^imgscisubjectbenchmarkrun_[0-9a-f]{32}$")
    plan: ImageEvaluationArtifactMember
    plan_sha256: Sha256
    staged_plan_path: Literal["inputs/subject-benchmark-plan.json"]
    staged_subject_inventory_path: Literal["inputs/science-visual-subject-inventory.json"]
    staged_adapter_manifest_path: Literal["inputs/adapter/adapter-manifest.json"]
    staged_adapter_model_path: Literal["inputs/adapter/adapter_model.safetensors"]
    staged_adapter_config_path: Literal["inputs/adapter/adapter_config.json"]
    output_directory: Literal["outputs"]
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    command_sha256: Sha256

    @model_validator(mode="after")
    def pinned_command(self) -> Self:
        _require_pointer(self.plan, schema_ref=SUBJECT_BENCHMARK_PLAN_SCHEMA_REF)
        identity = content_sha256(
            self.model_dump(mode="json", exclude={"run_id", "command_sha256"})
        ).removeprefix("sha256:")[:32]
        if self.run_id != f"imgscisubjectbenchmarkrun_{identity}":
            raise ValueError("subject benchmark run ID mismatch")
        expected = content_sha256(self.model_dump(mode="json", exclude={"command_sha256"}))
        if self.command_sha256 != expected:
            raise ValueError("subject benchmark command hash mismatch")
        return self


class ScienceVisualSubjectBenchmarkOutput(FrozenModel):
    case_id: str = Field(pattern=r"^imgscisubjectcase_[0-9a-f]{32}$")
    variant: Literal["ADAPTER", "BASE", "DETERMINISTIC"]
    relative_path: str = Field(
        pattern=(r"^outputs/imgscisubjectcase_[0-9a-f]{32}-(adapter|base|deterministic)\.png$")
    )
    media_type: Literal["image/png"]
    bytes: int = Field(ge=1, le=64 * 1024 * 1024)
    sha256: Sha256
    width_px: Literal[800]
    height_px: Literal[500]

    @model_validator(mode="after")
    def derived_output_path(self) -> Self:
        expected = f"outputs/{self.case_id}-{self.variant.lower()}.png"
        if self.relative_path != expected:
            raise ValueError("subject benchmark output path mismatch")
        return self


class ScienceVisualSubjectBenchmarkOutcome(FrozenModel):
    case_id: str = Field(pattern=r"^imgscisubjectcase_[0-9a-f]{32}$")
    outcome: Literal["BASE_ADAPTER_PAIR", "DETERMINISTIC_RENDERED", "POLICY_REJECTED"]
    stable_code: Literal["LOCAL_IMAGE_HUMAN_SUBJECT_FORBIDDEN"] | None

    @model_validator(mode="after")
    def stable_code_matches_outcome(self) -> Self:
        expected = (
            "LOCAL_IMAGE_HUMAN_SUBJECT_FORBIDDEN" if self.outcome == "POLICY_REJECTED" else None
        )
        if self.stable_code != expected:
            raise ValueError("subject benchmark outcome stable code mismatch")
        return self


class LocalImageScienceVisualSubjectBenchmarkResult(FrozenModel):
    schema_version: Literal["local-image-science-visual-subject-benchmark-result/1.0"]
    run_id: str = Field(pattern=r"^imgscisubjectbenchmarkrun_[0-9a-f]{32}$")
    plan_id: str = Field(pattern=r"^imgscisubjectbenchmark_[0-9a-f]{32}$")
    plan_sha256: Sha256
    command_sha256: Sha256
    status: Literal["FAILED", "SUCCEEDED"]
    error_code: (
        Literal[
            "SCIENCE_SUBJECT_BENCHMARK_ADAPTER_INVALID",
            "SCIENCE_SUBJECT_BENCHMARK_EXEC_FAILED",
            "SCIENCE_SUBJECT_BENCHMARK_GPU_RUNTIME_DRIFT",
            "SCIENCE_SUBJECT_BENCHMARK_INPUT_HASH_MISMATCH",
            "SCIENCE_SUBJECT_BENCHMARK_INPUT_INVALID",
            "SCIENCE_SUBJECT_BENCHMARK_MODEL_INVALID",
            "SCIENCE_SUBJECT_BENCHMARK_OOM",
            "SCIENCE_SUBJECT_BENCHMARK_OUTPUT_INVALID",
        ]
        | None
    )
    outcomes: tuple[ScienceVisualSubjectBenchmarkOutcome, ...] = Field(max_length=256)
    outputs: tuple[ScienceVisualSubjectBenchmarkOutput, ...] = Field(max_length=768)
    started_at: datetime
    completed_at: datetime
    result_sha256: Sha256

    @field_validator("started_at", "completed_at")
    @classmethod
    def utc_timestamps(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def result_is_canonical(self) -> Self:
        if self.completed_at < self.started_at:
            raise ValueError("subject benchmark completion precedes start")
        if self.status == "SUCCEEDED":
            if self.error_code is not None or not self.outcomes:
                raise ValueError("successful subject benchmark result is incomplete")
        elif self.error_code is None or self.outcomes or self.outputs:
            raise ValueError("failed subject benchmark result must be empty and coded")
        outcome_ids = tuple(outcome.case_id for outcome in self.outcomes)
        if outcome_ids != tuple(sorted(set(outcome_ids))):
            raise ValueError("benchmark outcomes must be uniquely sorted")
        output_keys = tuple((output.case_id, output.variant) for output in self.outputs)
        if output_keys != tuple(sorted(set(output_keys))):
            raise ValueError("benchmark outputs must be uniquely sorted")
        expected = content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        if self.result_sha256 != expected:
            raise ValueError("subject benchmark result hash mismatch")
        return self


ScienceVisualSubjectQualityStatus = Literal[
    "ADAPTER_PREFERRED",
    "BASE_PREFERRED",
    "DIAGNOSTIC_ONLY",
    "NEITHER_ACCEPTABLE",
]
ScienceVisualSubjectQualityFailureReason = Literal[
    "ADAPTER_SEMANTIC_MISMATCH",
    "BASE_SEMANTIC_MISMATCH",
    "COMPOSITION_ARTIFACT",
    "EXCESSIVE_DETAIL",
    "INSUFFICIENT_DETAIL",
    "NO_SAFE_RENDER_ROUTE",
    "PRODUCTION_PATH_NOT_EXERCISED",
    "PSEUDOTEXT",
    "STYLE_MISMATCH",
]
ScienceVisualSubjectQualityNextAction = Literal[
    "ADAPTER_CANDIDATE_AFTER_CANARY",
    "BUILD_PRODUCTION_VECTOR_FIXTURE",
    "DATASET_AUGMENTATION",
    "KEEP_BASE_ONLY",
    "MULTI_SEED_REEVALUATION",
    "PROMPT_REFINEMENT",
    "ROUTE_RECLASSIFICATION",
]


class ScienceVisualSubjectQualityReviewEntry(FrozenModel):
    subject_id: str = Field(pattern=r"^imgscisubject_[0-9a-f]{32}$")
    subject_key: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")
    render_route: ScienceVisualSubjectRoute
    benchmark_case_ids: tuple[str, ...] = Field(max_length=2)
    quality_status: ScienceVisualSubjectQualityStatus
    preferred_variant: Literal["ADAPTER", "BASE"] | None
    failure_reasons: tuple[ScienceVisualSubjectQualityFailureReason, ...] = Field(max_length=16)
    next_actions: tuple[ScienceVisualSubjectQualityNextAction, ...] = Field(
        min_length=1, max_length=8
    )

    @model_validator(mode="after")
    def review_entry_is_closed(self) -> Self:
        if self.benchmark_case_ids != tuple(sorted(set(self.benchmark_case_ids))) or any(
            re.fullmatch(r"imgscisubjectcase_[0-9a-f]{32}", value) is None
            for value in self.benchmark_case_ids
        ):
            raise ValueError("quality-review case IDs must be uniquely sorted")
        if self.failure_reasons != tuple(sorted(set(self.failure_reasons))):
            raise ValueError("quality-review reasons must be uniquely sorted")
        if self.next_actions != tuple(sorted(set(self.next_actions))):
            raise ValueError("quality-review actions must be uniquely sorted")
        if self.quality_status == "DIAGNOSTIC_ONLY":
            valid = (
                self.render_route == "PYTHON_SVG"
                and self.preferred_variant is None
                and "PRODUCTION_PATH_NOT_EXERCISED" in self.failure_reasons
                and "BUILD_PRODUCTION_VECTOR_FIXTURE" in self.next_actions
            )
        elif self.quality_status == "BASE_PREFERRED":
            valid = (
                self.render_route in {"HYBRID", "LORA_RASTER"}
                and self.preferred_variant == "BASE"
                and "KEEP_BASE_ONLY" in self.next_actions
                and "MULTI_SEED_REEVALUATION" in self.next_actions
            )
        elif self.quality_status == "ADAPTER_PREFERRED":
            valid = (
                self.render_route in {"HYBRID", "LORA_RASTER"}
                and self.preferred_variant == "ADAPTER"
                and "ADAPTER_CANDIDATE_AFTER_CANARY" in self.next_actions
                and "MULTI_SEED_REEVALUATION" in self.next_actions
            )
        else:
            valid = (
                self.preferred_variant is None
                and bool(self.failure_reasons)
                and bool(
                    set(self.next_actions)
                    & {"DATASET_AUGMENTATION", "PROMPT_REFINEMENT", "ROUTE_RECLASSIFICATION"}
                )
            )
        if not valid:
            raise ValueError("quality-review status, route, variant, and action mismatch")
        if self.render_route == "BLOCKED" and (
            self.quality_status != "NEITHER_ACCEPTABLE"
            or self.benchmark_case_ids
            or "NO_SAFE_RENDER_ROUTE" not in self.failure_reasons
        ):
            raise ValueError("blocked subject quality review is invalid")
        return self


class LocalImageScienceVisualSubjectBenchmarkReview(FrozenModel):
    schema_version: Literal["local-image-science-visual-subject-benchmark-review/1.0"]
    review_id: str = Field(pattern=r"^imgscisubjectreview_[0-9a-f]{32}$")
    subject_inventory: ImageEvaluationArtifactMember
    benchmark_plan: ImageEvaluationArtifactMember
    benchmark_result: ImageEvaluationArtifactMember
    benchmark_result_sha256: Sha256
    reviews: tuple[ScienceVisualSubjectQualityReviewEntry, ...] = Field(
        min_length=1, max_length=256
    )
    diagnostic_only_count: int = Field(ge=0, le=256)
    base_preferred_count: int = Field(ge=0, le=256)
    adapter_preferred_count: int = Field(ge=0, le=256)
    neither_acceptable_count: int = Field(ge=0, le=256)
    adapter_activation_recommendation: Literal["FORBIDDEN"]
    reviewed_at: datetime
    reviewed_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    review_sha256: Sha256

    @field_validator("reviewed_at")
    @classmethod
    def utc_reviewed_at(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def review_is_canonical(self) -> Self:
        _require_pointer(self.subject_inventory, schema_ref=SUBJECT_INVENTORY_SCHEMA_REF)
        _require_pointer(self.benchmark_plan, schema_ref=SUBJECT_BENCHMARK_PLAN_SCHEMA_REF)
        _require_pointer(self.benchmark_result, schema_ref=SUBJECT_BENCHMARK_RESULT_SCHEMA_REF)
        keys = tuple(entry.subject_key for entry in self.reviews)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("quality reviews must be uniquely sorted by subject key")
        if len({entry.subject_id for entry in self.reviews}) != len(self.reviews):
            raise ValueError("quality reviews contain duplicate subject IDs")
        counts = {
            "DIAGNOSTIC_ONLY": self.diagnostic_only_count,
            "BASE_PREFERRED": self.base_preferred_count,
            "ADAPTER_PREFERRED": self.adapter_preferred_count,
            "NEITHER_ACCEPTABLE": self.neither_acceptable_count,
        }
        for status, declared in counts.items():
            if declared != sum(entry.quality_status == status for entry in self.reviews):
                raise ValueError("quality-review summary count mismatch")
        identity = content_sha256(
            {
                "subject_inventory": self.subject_inventory.model_dump(mode="json"),
                "benchmark_plan": self.benchmark_plan.model_dump(mode="json"),
                "benchmark_result": self.benchmark_result.model_dump(mode="json"),
                "benchmark_result_sha256": self.benchmark_result_sha256,
                "reviews": [entry.model_dump(mode="json") for entry in self.reviews],
            }
        ).removeprefix("sha256:")[:32]
        if self.review_id != f"imgscisubjectreview_{identity}":
            raise ValueError("quality-review ID mismatch")
        expected = content_sha256(self.model_dump(mode="json", exclude={"review_sha256"}))
        if self.review_sha256 != expected:
            raise ValueError("quality-review hash mismatch")
        return self


def validate_science_visual_subject_benchmark_plan(
    inventory: LocalImageScienceVisualSubjectInventory,
    plan: LocalImageScienceVisualSubjectBenchmarkPlan,
) -> None:
    """Validate exact inventory coverage and route preservation in O(S + C)."""

    if plan.subject_inventory.sha256 != content_sha256(inventory.model_dump(mode="json")):
        raise ValueError("subject benchmark plan inventory bytes mismatch")
    subjects = {subject.subject_id: subject for subject in inventory.subjects}
    primary_cases: dict[str, ScienceVisualSubjectBenchmarkCase] = {}
    negative_subject_ids: set[str] = set()
    for case in plan.cases:
        subject = subjects.get(case.subject_id)
        if subject is None:
            raise ValueError("benchmark case references an unknown subject")
        if case.case_kind == "GPU_POLICY_NEGATIVE":
            if subject.render_route != "PYTHON_SVG":
                raise ValueError("GPU policy negative must reference a deterministic subject")
            negative_subject_ids.add(subject.subject_id)
            continue
        if subject.subject_id in primary_cases:
            raise ValueError("subject has more than one primary benchmark case")
        if case.render_route != subject.render_route:
            raise ValueError("benchmark case changes the subject render route")
        if case.renderer_primitive != subject.renderer_primitive:
            raise ValueError("benchmark case changes the subject renderer primitive")
        if case.prompt_en != subject.raster_prompt_en:
            raise ValueError("benchmark case changes the subject raster prompt")
        primary_cases[subject.subject_id] = case
    expected_primary = {
        subject.subject_id for subject in inventory.subjects if subject.render_route != "BLOCKED"
    }
    if set(primary_cases) != expected_primary:
        raise ValueError("benchmark primary cases do not cover every renderable subject")
    human_subjects = {
        subject.subject_id
        for subject in inventory.subjects
        if subject.subject_key in {"HUMAN_FIGURE", "STUDENT_OR_TEACHER"}
    }
    if human_subjects and not human_subjects.issubset(negative_subject_ids):
        raise ValueError("human subjects require GPU policy negative controls")


def validate_science_visual_subject_benchmark_result(
    plan: LocalImageScienceVisualSubjectBenchmarkPlan,
    command: LocalImageScienceVisualSubjectBenchmarkCommand,
    result: LocalImageScienceVisualSubjectBenchmarkResult,
) -> None:
    """Validate exact command/result closure with indexed lookups in O(C + O)."""

    if (
        command.plan_sha256 != plan.plan_sha256
        or command.plan.sha256 != content_sha256(plan.model_dump(mode="json"))
        or result.run_id != command.run_id
        or result.plan_id != plan.plan_id
        or result.plan_sha256 != plan.plan_sha256
        or result.command_sha256 != command.command_sha256
    ):
        raise ValueError("subject benchmark command/result pointer mismatch")
    if result.status == "FAILED":
        return
    outcomes = {outcome.case_id: outcome for outcome in result.outcomes}
    if set(outcomes) != {case.case_id for case in plan.cases}:
        raise ValueError("subject benchmark outcome set mismatch")
    outputs: dict[str, set[str]] = {}
    for output in result.outputs:
        outputs.setdefault(output.case_id, set()).add(output.variant)
    for case in plan.cases:
        outcome = outcomes[case.case_id]
        if outcome.outcome != case.expected_outcome:
            raise ValueError("subject benchmark outcome does not match the plan")
        expected_variants = (
            {"BASE", "ADAPTER"}
            if case.expected_outcome == "BASE_ADAPTER_PAIR"
            else {"DETERMINISTIC"}
            if case.expected_outcome == "DETERMINISTIC_RENDERED"
            else set()
        )
        if outputs.get(case.case_id, set()) != expected_variants:
            raise ValueError("subject benchmark output variants do not match the plan")
    if set(outputs).difference(outcomes):
        raise ValueError("subject benchmark has output for an unknown case")


def validate_science_visual_subject_benchmark_review(
    inventory: LocalImageScienceVisualSubjectInventory,
    plan: LocalImageScienceVisualSubjectBenchmarkPlan,
    result: LocalImageScienceVisualSubjectBenchmarkResult,
    review: LocalImageScienceVisualSubjectBenchmarkReview,
) -> None:
    """Close one quality review over the exact subject/case population in O(S + C + O)."""

    validate_science_visual_subject_benchmark_plan(inventory, plan)
    if result.status != "SUCCEEDED":
        raise ValueError("subject quality review requires a successful benchmark")
    command_stub_matches = result.plan_id == plan.plan_id and result.plan_sha256 == plan.plan_sha256
    if not command_stub_matches:
        raise ValueError("subject quality review plan/result mismatch")
    if (
        review.subject_inventory != plan.subject_inventory
        or review.benchmark_plan.sha256 != content_sha256(plan.model_dump(mode="json"))
        or review.benchmark_result_sha256 != result.result_sha256
    ):
        raise ValueError("subject quality review pointer chain mismatch")
    subjects = {subject.subject_id: subject for subject in inventory.subjects}
    entries = {entry.subject_id: entry for entry in review.reviews}
    if set(entries) != set(subjects):
        raise ValueError("subject quality review population mismatch")
    cases_by_subject: dict[str, set[str]] = {}
    cases_by_id = {case.case_id: case for case in plan.cases}
    for case in plan.cases:
        cases_by_subject.setdefault(case.subject_id, set()).add(case.case_id)
    outcome_by_case = {outcome.case_id: outcome for outcome in result.outcomes}
    output_variants: dict[str, set[str]] = {}
    for output in result.outputs:
        output_variants.setdefault(output.case_id, set()).add(output.variant)
    for subject_id, subject in subjects.items():
        entry = entries[subject_id]
        if entry.subject_key != subject.subject_key or entry.render_route != subject.render_route:
            raise ValueError("subject quality review changes subject identity or route")
        expected_cases = cases_by_subject.get(subject_id, set())
        if set(entry.benchmark_case_ids) != expected_cases:
            raise ValueError("subject quality review case population mismatch")
        if subject.render_route == "BLOCKED":
            continue
        primary = [
            cases_by_id[case_id]
            for case_id in expected_cases
            if cases_by_id[case_id].case_kind != "GPU_POLICY_NEGATIVE"
        ]
        if len(primary) != 1:
            raise ValueError("subject quality review primary case mismatch")
        primary_case = primary[0]
        outcome = outcome_by_case.get(primary_case.case_id)
        if outcome is None or outcome.outcome != primary_case.expected_outcome:
            raise ValueError("subject quality review benchmark outcome mismatch")
        variants = output_variants.get(primary_case.case_id, set())
        if entry.quality_status == "DIAGNOSTIC_ONLY":
            if primary_case.case_kind != "ROUTE" or variants != {"DETERMINISTIC"}:
                raise ValueError("diagnostic-only review is not backed by a route case")
        elif primary_case.case_kind != "QUALITY" or variants != {"BASE", "ADAPTER"}:
            raise ValueError("raster quality review is not backed by an exact output pair")
