"""Contracts for fixed additional-seed science visual subject evaluation."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
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
from eom_image_contracts.science_subject_benchmark import (
    ADAPTER_MANIFEST_SCHEMA_REF,
    SUBJECT_BENCHMARK_PLAN_SCHEMA_REF,
    SUBJECT_BENCHMARK_REVIEW_SCHEMA_REF,
    SUBJECT_INVENTORY_SCHEMA_REF,
    LocalImageScienceVisualSubjectBenchmarkPlan,
    LocalImageScienceVisualSubjectBenchmarkResult,
    LocalImageScienceVisualSubjectBenchmarkReview,
    LocalImageScienceVisualSubjectInventory,
)

SUBJECT_MULTISEED_PLAN_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-visual-subject-multiseed-plan/1.0"
)
SUBJECT_MULTISEED_COMMAND_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-visual-subject-multiseed-command/1.0"
)
SUBJECT_MULTISEED_RESULT_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-visual-subject-multiseed-result/1.0"
)
SUBJECT_MULTISEED_REVIEW_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-visual-subject-multiseed-review/1.0"
)

ScienceVisualRasterRoute = Literal["HYBRID", "LORA_RASTER"]
ScienceVisualMultiseedDecision = Literal["ADAPTER", "BASE", "NEITHER"]
ScienceVisualMultiseedStability = Literal[
    "MIXED",
    "NEITHER_ACCEPTABLE",
    "STABLE_ADAPTER_PREFERRED",
    "STABLE_BASE_PREFERRED",
]
ScienceVisualMultiseedNextAction = Literal[
    "ADAPTER_PRODUCTION_CANARY",
    "DATASET_AUGMENTATION",
    "KEEP_BASE_ONLY",
    "PROMPT_REFINEMENT",
    "ROUTE_RECLASSIFICATION",
]


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("timestamp must be UTC")
    return value


def _safe_ascii(value: str) -> str:
    if (
        value != value.strip()
        or value != unicodedata.normalize("NFC", value)
        or not value.isascii()
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise ValueError("prompt must be trimmed printable ASCII")
    return value


def _require_pointer(
    pointer: ImageEvaluationArtifactMember,
    *,
    schema_ref: str,
    member_path: str,
) -> None:
    if (
        pointer.schema_ref != schema_ref
        or pointer.member_path != member_path
        or pointer.media_type != "application/json"
    ):
        raise ValueError("science subject multi-seed pointer contract mismatch")


def science_subject_multiseed_value(subject_key: str, seed_ordinal: int) -> int:
    """Return the deterministic additional seed for one subject and ordinal."""

    if re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", subject_key) is None or seed_ordinal not in {1, 2}:
        raise ValueError("science subject multi-seed input is invalid")
    return (
        int(
            content_sha256(f"{subject_key}:multi-seed:{seed_ordinal}").removeprefix("sha256:")[:8],
            16,
        )
        % 2_147_483_648
    )


class ScienceVisualSubjectMultiseedCase(FrozenModel):
    case_id: str = Field(pattern=r"^imgscisubjectseedcase_[0-9a-f]{32}$")
    subject_id: str = Field(pattern=r"^imgscisubject_[0-9a-f]{32}$")
    subject_key: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")
    render_route: ScienceVisualRasterRoute
    seed_ordinal: int = Field(ge=1, le=2)
    seed: int = Field(ge=0, le=2_147_483_647)
    prompt_en: str = Field(min_length=20, max_length=2000)
    prompt_sha256: Sha256
    negative_prompt_en: str = Field(min_length=1, max_length=2000)
    negative_prompt_sha256: Sha256

    @field_validator("prompt_en", "negative_prompt_en")
    @classmethod
    def safe_prompt(cls, value: str) -> str:
        return _safe_ascii(value)

    @model_validator(mode="after")
    def exact_case_identity(self) -> Self:
        if (
            self.prompt_sha256 != text_sha256(self.prompt_en)
            or self.negative_prompt_sha256 != text_sha256(self.negative_prompt_en)
            or self.seed != science_subject_multiseed_value(self.subject_key, self.seed_ordinal)
        ):
            raise ValueError("science subject multi-seed prompt or seed mismatch")
        identity = content_sha256(
            {
                "seed": self.seed,
                "seed_ordinal": self.seed_ordinal,
                "subject_id": self.subject_id,
            }
        ).removeprefix("sha256:")[:32]
        if self.case_id != f"imgscisubjectseedcase_{identity}":
            raise ValueError("science subject multi-seed case ID mismatch")
        return self


class LocalImageScienceVisualSubjectMultiseedPlan(FrozenModel):
    schema_version: Literal["local-image-science-visual-subject-multiseed-plan/1.0"]
    plan_id: str = Field(pattern=r"^imgscisubjectmultiseed_[0-9a-f]{32}$")
    subject_inventory: ImageEvaluationArtifactMember
    initial_benchmark_plan: ImageEvaluationArtifactMember
    initial_quality_review: ImageEvaluationArtifactMember
    base_model: LocalImageModelPointer
    adapter_manifest: ImageEvaluationArtifactMember
    generation_width_px: Literal[800]
    generation_height_px: Literal[504]
    delivery_width_px: Literal[800]
    delivery_height_px: Literal[500]
    inference_steps: Literal[20]
    guidance_scale_milli: Literal[7500]
    seeds_per_subject: Literal[2]
    cases: tuple[ScienceVisualSubjectMultiseedCase, ...] = Field(min_length=2, max_length=128)
    activation_policy: Literal["FORBIDDEN"]
    created_at: datetime
    created_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    plan_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_created_at(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def exact_plan_identity(self) -> Self:
        _require_pointer(
            self.subject_inventory,
            schema_ref=SUBJECT_INVENTORY_SCHEMA_REF,
            member_path="manifests/science-visual-subject-inventory.json",
        )
        _require_pointer(
            self.initial_benchmark_plan,
            schema_ref=SUBJECT_BENCHMARK_PLAN_SCHEMA_REF,
            member_path="manifests/science-visual-subject-benchmark-plan.json",
        )
        _require_pointer(
            self.initial_quality_review,
            schema_ref=SUBJECT_BENCHMARK_REVIEW_SCHEMA_REF,
            member_path="manifests/science-visual-subject-benchmark-review.json",
        )
        _require_pointer(
            self.adapter_manifest,
            schema_ref=ADAPTER_MANIFEST_SCHEMA_REF,
            member_path="manifests/adapter-manifest.json",
        )
        case_ids = tuple(case.case_id for case in self.cases)
        case_keys = tuple((case.subject_key, case.seed_ordinal) for case in self.cases)
        if case_ids != tuple(sorted(set(case_ids))) or len(case_keys) != len(set(case_keys)):
            raise ValueError("science subject multi-seed cases must be uniquely sorted")
        identity = content_sha256(
            self.model_dump(
                mode="json",
                exclude={"plan_id", "created_at", "created_by", "plan_sha256"},
            )
        ).removeprefix("sha256:")[:32]
        if self.plan_id != f"imgscisubjectmultiseed_{identity}":
            raise ValueError("science subject multi-seed plan ID mismatch")
        expected = content_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))
        if self.plan_sha256 != expected:
            raise ValueError("science subject multi-seed plan hash mismatch")
        return self


class LocalImageScienceVisualSubjectMultiseedCommand(FrozenModel):
    schema_version: Literal["local-image-science-visual-subject-multiseed-command/1.0"]
    run_id: str = Field(pattern=r"^imgscisubjectmultiseedrun_[0-9a-f]{32}$")
    plan: ImageEvaluationArtifactMember
    plan_sha256: Sha256
    staged_plan_path: Literal["inputs/subject-multiseed-plan.json"]
    staged_subject_inventory_path: Literal["inputs/science-visual-subject-inventory.json"]
    staged_initial_benchmark_plan_path: Literal["inputs/science-visual-subject-benchmark-plan.json"]
    staged_initial_quality_review_path: Literal[
        "inputs/science-visual-subject-benchmark-review.json"
    ]
    staged_adapter_manifest_path: Literal["inputs/adapter/adapter-manifest.json"]
    staged_adapter_model_path: Literal["inputs/adapter/adapter_model.safetensors"]
    staged_adapter_config_path: Literal["inputs/adapter/adapter_config.json"]
    output_directory: Literal["outputs"]
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    command_sha256: Sha256

    @model_validator(mode="after")
    def exact_command_identity(self) -> Self:
        _require_pointer(
            self.plan,
            schema_ref=SUBJECT_MULTISEED_PLAN_SCHEMA_REF,
            member_path="manifests/science-visual-subject-multiseed-plan.json",
        )
        identity = content_sha256(
            self.model_dump(mode="json", exclude={"run_id", "command_sha256"})
        ).removeprefix("sha256:")[:32]
        if self.run_id != f"imgscisubjectmultiseedrun_{identity}":
            raise ValueError("science subject multi-seed run ID mismatch")
        expected = content_sha256(self.model_dump(mode="json", exclude={"command_sha256"}))
        if self.command_sha256 != expected:
            raise ValueError("science subject multi-seed command hash mismatch")
        return self


class ScienceVisualSubjectMultiseedOutput(FrozenModel):
    case_id: str = Field(pattern=r"^imgscisubjectseedcase_[0-9a-f]{32}$")
    variant: Literal["ADAPTER", "BASE"]
    relative_path: str = Field(
        pattern=r"^outputs/imgscisubjectseedcase_[0-9a-f]{32}-(adapter|base)\.png$"
    )
    media_type: Literal["image/png"]
    bytes: int = Field(ge=1, le=64 * 1024 * 1024)
    sha256: Sha256
    width_px: Literal[800]
    height_px: Literal[500]

    @model_validator(mode="after")
    def output_path_matches_identity(self) -> Self:
        if self.relative_path != f"outputs/{self.case_id}-{self.variant.lower()}.png":
            raise ValueError("science subject multi-seed output path mismatch")
        return self


class LocalImageScienceVisualSubjectMultiseedResult(FrozenModel):
    schema_version: Literal["local-image-science-visual-subject-multiseed-result/1.0"]
    run_id: str = Field(pattern=r"^imgscisubjectmultiseedrun_[0-9a-f]{32}$")
    plan_id: str = Field(pattern=r"^imgscisubjectmultiseed_[0-9a-f]{32}$")
    plan_sha256: Sha256
    command_sha256: Sha256
    status: Literal["FAILED", "SUCCEEDED"]
    error_code: (
        Literal[
            "SCIENCE_SUBJECT_MULTISEED_ADAPTER_INVALID",
            "SCIENCE_SUBJECT_MULTISEED_EXEC_FAILED",
            "SCIENCE_SUBJECT_MULTISEED_GPU_RUNTIME_DRIFT",
            "SCIENCE_SUBJECT_MULTISEED_INPUT_HASH_MISMATCH",
            "SCIENCE_SUBJECT_MULTISEED_INPUT_INVALID",
            "SCIENCE_SUBJECT_MULTISEED_MODEL_INVALID",
            "SCIENCE_SUBJECT_MULTISEED_OOM",
            "SCIENCE_SUBJECT_MULTISEED_OUTPUT_INVALID",
        ]
        | None
    )
    outputs: tuple[ScienceVisualSubjectMultiseedOutput, ...] = Field(max_length=256)
    started_at: datetime
    completed_at: datetime
    result_sha256: Sha256

    @field_validator("started_at", "completed_at")
    @classmethod
    def utc_timestamps(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def terminal_result_is_closed(self) -> Self:
        if self.completed_at < self.started_at:
            raise ValueError("science subject multi-seed completion precedes start")
        keys = tuple((output.case_id, output.variant) for output in self.outputs)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("science subject multi-seed outputs must be uniquely sorted")
        if self.status == "SUCCEEDED":
            if self.error_code is not None or not self.outputs:
                raise ValueError("successful science subject multi-seed result is incomplete")
        elif self.error_code is None or self.outputs:
            raise ValueError("failed science subject multi-seed result must be empty and coded")
        expected = content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        if self.result_sha256 != expected:
            raise ValueError("science subject multi-seed result hash mismatch")
        return self


class ScienceVisualSubjectSeedEvaluation(FrozenModel):
    source: Literal["ADDITIONAL", "INITIAL"]
    case_id: str = Field(pattern=r"^imgscisubject(seed)?case_[0-9a-f]{32}$")
    seed: int = Field(ge=0, le=2_147_483_647)
    decision: ScienceVisualMultiseedDecision


class ScienceVisualSubjectMultiseedReviewEntry(FrozenModel):
    subject_id: str = Field(pattern=r"^imgscisubject_[0-9a-f]{32}$")
    subject_key: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")
    render_route: ScienceVisualRasterRoute
    evaluations: tuple[ScienceVisualSubjectSeedEvaluation, ...] = Field(min_length=3, max_length=3)
    stability_status: ScienceVisualMultiseedStability
    next_actions: tuple[ScienceVisualMultiseedNextAction, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def stability_matches_decisions(self) -> Self:
        identities = tuple((value.source, value.case_id) for value in self.evaluations)
        if (
            len(set(identities)) != 3
            or sum(value.source == "INITIAL" for value in self.evaluations) != 1
            or sum(value.source == "ADDITIONAL" for value in self.evaluations) != 2
            or self.next_actions != tuple(sorted(set(self.next_actions)))
        ):
            raise ValueError("science subject multi-seed evaluations are not closed")
        decisions = {value.decision for value in self.evaluations}
        if decisions == {"ADAPTER"}:
            valid = (
                self.stability_status == "STABLE_ADAPTER_PREFERRED"
                and "ADAPTER_PRODUCTION_CANARY" in self.next_actions
            )
        elif decisions == {"BASE"}:
            valid = (
                self.stability_status == "STABLE_BASE_PREFERRED"
                and "KEEP_BASE_ONLY" in self.next_actions
            )
        elif decisions == {"NEITHER"}:
            valid = self.stability_status == "NEITHER_ACCEPTABLE" and bool(
                set(self.next_actions)
                & {"DATASET_AUGMENTATION", "PROMPT_REFINEMENT", "ROUTE_RECLASSIFICATION"}
            )
        else:
            valid = self.stability_status == "MIXED" and bool(
                set(self.next_actions)
                & {"DATASET_AUGMENTATION", "KEEP_BASE_ONLY", "PROMPT_REFINEMENT"}
            )
        if not valid:
            raise ValueError("science subject multi-seed stability decision mismatch")
        return self


class LocalImageScienceVisualSubjectMultiseedReview(FrozenModel):
    schema_version: Literal["local-image-science-visual-subject-multiseed-review/1.0"]
    review_id: str = Field(pattern=r"^imgscisubjectmultiseedreview_[0-9a-f]{32}$")
    multiseed_plan: ImageEvaluationArtifactMember
    multiseed_result: ImageEvaluationArtifactMember
    initial_quality_review: ImageEvaluationArtifactMember
    reviews: tuple[ScienceVisualSubjectMultiseedReviewEntry, ...] = Field(
        min_length=1, max_length=64
    )
    stable_adapter_preferred_count: int = Field(ge=0, le=64)
    stable_base_preferred_count: int = Field(ge=0, le=64)
    mixed_count: int = Field(ge=0, le=64)
    neither_acceptable_count: int = Field(ge=0, le=64)
    adapter_activation_recommendation: Literal["FORBIDDEN"]
    reviewed_at: datetime
    reviewed_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    review_sha256: Sha256

    @field_validator("reviewed_at")
    @classmethod
    def utc_reviewed_at(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def exact_review_identity(self) -> Self:
        _require_pointer(
            self.multiseed_plan,
            schema_ref=SUBJECT_MULTISEED_PLAN_SCHEMA_REF,
            member_path="manifests/science-visual-subject-multiseed-plan.json",
        )
        _require_pointer(
            self.multiseed_result,
            schema_ref=SUBJECT_MULTISEED_RESULT_SCHEMA_REF,
            member_path="result.json",
        )
        _require_pointer(
            self.initial_quality_review,
            schema_ref=SUBJECT_BENCHMARK_REVIEW_SCHEMA_REF,
            member_path="manifests/science-visual-subject-benchmark-review.json",
        )
        keys = tuple(value.subject_key for value in self.reviews)
        if keys != tuple(sorted(set(keys))) or len(
            {value.subject_id for value in self.reviews}
        ) != len(self.reviews):
            raise ValueError("science subject multi-seed reviews must be uniquely sorted")
        counts = Counter(value.stability_status for value in self.reviews)
        if (
            counts["MIXED"] != self.mixed_count
            or counts["NEITHER_ACCEPTABLE"] != self.neither_acceptable_count
            or counts["STABLE_ADAPTER_PREFERRED"] != self.stable_adapter_preferred_count
            or counts["STABLE_BASE_PREFERRED"] != self.stable_base_preferred_count
        ):
            raise ValueError("science subject multi-seed review count mismatch")
        identity = content_sha256(
            self.model_dump(
                mode="json", exclude={"review_id", "reviewed_at", "reviewed_by", "review_sha256"}
            )
        ).removeprefix("sha256:")[:32]
        if self.review_id != f"imgscisubjectmultiseedreview_{identity}":
            raise ValueError("science subject multi-seed review ID mismatch")
        expected = content_sha256(self.model_dump(mode="json", exclude={"review_sha256"}))
        if self.review_sha256 != expected:
            raise ValueError("science subject multi-seed review hash mismatch")
        return self


def validate_science_visual_subject_multiseed_plan(
    inventory: LocalImageScienceVisualSubjectInventory,
    initial_plan: LocalImageScienceVisualSubjectBenchmarkPlan,
    initial_review: LocalImageScienceVisualSubjectBenchmarkReview,
    plan: LocalImageScienceVisualSubjectMultiseedPlan,
) -> None:
    """Bind the successor plan to exactly the initial raster subject population."""

    if (
        plan.subject_inventory != initial_plan.subject_inventory
        or initial_review.subject_inventory != plan.subject_inventory
        or initial_review.benchmark_plan != plan.initial_benchmark_plan
        or plan.base_model != initial_plan.base_model
        or plan.adapter_manifest != initial_plan.adapter_manifest
        or (
            plan.generation_width_px,
            plan.generation_height_px,
            plan.delivery_width_px,
            plan.delivery_height_px,
            plan.inference_steps,
            plan.guidance_scale_milli,
        )
        != (
            initial_plan.generation_width_px,
            initial_plan.generation_height_px,
            initial_plan.delivery_width_px,
            initial_plan.delivery_height_px,
            initial_plan.inference_steps,
            initial_plan.guidance_scale_milli,
        )
    ):
        raise ValueError("science subject multi-seed source binding mismatch")
    subjects = {value.subject_id: value for value in inventory.subjects}
    initial_cases = {
        value.subject_id: value for value in initial_plan.cases if value.case_kind == "QUALITY"
    }
    reviewed = {
        value.subject_id: value
        for value in initial_review.reviews
        if value.render_route in {"HYBRID", "LORA_RASTER"}
    }
    if set(initial_cases) != set(reviewed):
        raise ValueError("science subject multi-seed initial raster coverage mismatch")
    cases_by_subject: dict[str, list[ScienceVisualSubjectMultiseedCase]] = defaultdict(list)
    for case in plan.cases:
        cases_by_subject[case.subject_id].append(case)
    if set(cases_by_subject) != set(reviewed):
        raise ValueError("science subject multi-seed plan lacks exact raster coverage")
    for subject_id, cases in cases_by_subject.items():
        subject = subjects.get(subject_id)
        original = initial_cases[subject_id]
        review = reviewed[subject_id]
        if (
            subject is None
            or subject.subject_key != review.subject_key
            or subject.render_route != review.render_route
            or tuple(sorted(value.seed_ordinal for value in cases)) != (1, 2)
            or any(
                value.subject_key != subject.subject_key
                or value.render_route != subject.render_route
                or value.prompt_en != subject.raster_prompt_en
                or value.prompt_sha256 != subject.raster_prompt_sha256
                or value.negative_prompt_en != original.negative_prompt_en
                or value.negative_prompt_sha256 != original.negative_prompt_sha256
                or value.seed == original.seed
                for value in cases
            )
        ):
            raise ValueError("science subject multi-seed case source mismatch")


def validate_science_visual_subject_multiseed_result(
    plan: LocalImageScienceVisualSubjectMultiseedPlan,
    command: LocalImageScienceVisualSubjectMultiseedCommand,
    result: LocalImageScienceVisualSubjectMultiseedResult,
) -> None:
    if (
        command.plan_sha256 != plan.plan_sha256
        or result.run_id != command.run_id
        or result.plan_id != plan.plan_id
        or result.plan_sha256 != plan.plan_sha256
        or result.command_sha256 != command.command_sha256
    ):
        raise ValueError("science subject multi-seed result binding mismatch")
    if result.status != "SUCCEEDED":
        return
    expected = {(case.case_id, variant) for case in plan.cases for variant in ("ADAPTER", "BASE")}
    actual = {(output.case_id, output.variant) for output in result.outputs}
    if actual != expected:
        raise ValueError("science subject multi-seed result lacks exact paired coverage")


def validate_science_visual_subject_multiseed_review(
    initial_plan: LocalImageScienceVisualSubjectBenchmarkPlan,
    initial_result: LocalImageScienceVisualSubjectBenchmarkResult,
    initial_review: LocalImageScienceVisualSubjectBenchmarkReview,
    plan: LocalImageScienceVisualSubjectMultiseedPlan,
    result: LocalImageScienceVisualSubjectMultiseedResult,
    review: LocalImageScienceVisualSubjectMultiseedReview,
    *,
    plan_pointer: ImageEvaluationArtifactMember,
    result_pointer: ImageEvaluationArtifactMember,
    initial_review_pointer: ImageEvaluationArtifactMember,
) -> None:
    if (
        review.multiseed_plan != plan_pointer
        or review.multiseed_result != result_pointer
        or review.initial_quality_review != initial_review_pointer
        or plan.initial_quality_review != initial_review_pointer
        or initial_review.benchmark_result_sha256 != initial_result.result_sha256
        or result.status != "SUCCEEDED"
        or result.plan_id != plan.plan_id
        or result.plan_sha256 != plan.plan_sha256
    ):
        raise ValueError("science subject multi-seed review source binding mismatch")
    expected_outputs = {
        (case.case_id, variant) for case in plan.cases for variant in ("ADAPTER", "BASE")
    }
    if {(output.case_id, output.variant) for output in result.outputs} != expected_outputs:
        raise ValueError("science subject multi-seed review result coverage mismatch")
    initial_cases = {
        value.subject_id: value for value in initial_plan.cases if value.case_kind == "QUALITY"
    }
    additional_by_subject: dict[str, list[ScienceVisualSubjectMultiseedCase]] = defaultdict(list)
    for case in plan.cases:
        additional_by_subject[case.subject_id].append(case)
    review_by_subject = {value.subject_id: value for value in review.reviews}
    if set(review_by_subject) != set(additional_by_subject):
        raise ValueError("science subject multi-seed review coverage mismatch")
    for subject_id, entry in review_by_subject.items():
        original = initial_cases[subject_id]
        additional = additional_by_subject[subject_id]
        expected = {
            ("INITIAL", original.case_id, original.seed),
            *(("ADDITIONAL", value.case_id, value.seed) for value in additional),
        }
        actual = {(value.source, value.case_id, value.seed) for value in entry.evaluations}
        if actual != expected:
            raise ValueError("science subject multi-seed review evaluation binding mismatch")
