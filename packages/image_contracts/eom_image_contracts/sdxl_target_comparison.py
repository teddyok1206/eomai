"""Truthful matched pair over exact reviewed TRAIN target revisions, not holdout evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.models import (
    FrozenModel,
    ImageEvaluationArtifactMember,
    LocalImageRuntime,
    Sha256,
    content_json_bytes,
    content_sha256,
)
from eom_image_contracts.sdxl_learned_comparison import (
    LEARNED_COMPARISON_ARMS,
    SdxlLearnedComparisonBudget,
    SdxlLearnedComparisonOutput,
)
from eom_image_contracts.sdxl_lineart_probe import (
    SdxlLineartProbeCase,
    SdxlLineartProbeConditioning,
    SdxlLineartStackPointer,
    SdxlProbeErrorCode,
)
from eom_image_contracts.sdxl_lora_evaluation import (
    SdxlLoraEvaluationSources,
    parse_sdxl_lora_evaluation_sources,
    validate_sdxl_lora_evaluation_sources,
)
from eom_image_contracts.sdxl_reviewed_evaluation import LocalImageSdxlReviewedEvaluationCommand
from eom_image_contracts.sdxl_reviewed_micro import (
    LocalImageSdxlReviewedMicroCommand,
    parse_sdxl_reviewed_micro_sources,
)
from eom_image_contracts.sdxl_source_training_targets import (
    LocalImageSdxlSourceTrainingTargetCommand,
    SdxlPreparedSourceTrainingTarget,
)
from eom_image_contracts.sdxl_training_targets import TargetExpression

_PREFIX = "eom://schemas/image-provider/local-image-"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("target comparison timestamp must use UTC")
    return value


class SdxlTargetComparisonCase(FrozenModel):
    sample_id: str = Field(pattern=r"^imgsourcecrop_[0-9a-f]{32}$")
    target_id: str = Field(pattern=r"^imgsdxltarget_[0-9a-f]{32}$")
    target_revision_id: str = Field(pattern=r"^imgsdxltargetrev_[0-9a-f]{32}$")
    expression: TargetExpression
    case: SdxlLineartProbeCase


class LocalImageSdxlTargetComparisonCommand(FrozenModel):
    schema_version: Literal["local-image-sdxl-target-comparison-command/1.0"]
    run_id: str = Field(pattern=r"^imgsdxltargetcmprun_[0-9a-f]{32}$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    created_at: datetime
    purpose: Literal["EVALUATION_ONLY_MATCHED_REVIEWED_TARGET"]
    activation_policy: Literal["FORBIDDEN"]
    case_relation: Literal["REVIEWED_TRAIN_TARGET_NOT_HOLDOUT"]
    lora_evaluation_command: ImageEvaluationArtifactMember
    conditioning_policy: Literal["FIT_GRAYSCALE_INVERT_832X512/1.0"]
    cases: tuple[SdxlTargetComparisonCase, ...] = Field(min_length=1, max_length=3)
    seed: int = Field(ge=0, le=2**32 - 1)
    budget: SdxlLearnedComparisonBudget
    command_sha256: Sha256

    _created_utc = field_validator("created_at")(_utc)

    @model_validator(mode="after")
    def exact_command(self) -> Self:
        pin = self.lora_evaluation_command
        if (
            pin.media_type != "application/json"
            or pin.member_path != "manifests/sdxl-lora-evaluation-command.json"
            or pin.schema_ref != _PREFIX + "sdxl-lora-evaluation-command/1.1"
        ):
            raise ValueError("target comparison requires the reviewed evaluation revision")
        ids = tuple(entry.case.case_id for entry in self.cases)
        if (
            ids != tuple(sorted(set(ids)))
            or any(
                len({getattr(entry, field) for entry in self.cases}) != len(ids)
                for field in ("sample_id", "target_id")
            )
            or len({entry.case.reference_image.sha256 for entry in self.cases}) != len(ids)
        ):
            raise ValueError("target comparison contains unordered/duplicate targets")
        if any(entry.case.seeds != (self.seed,) for entry in self.cases):
            raise ValueError("target comparison seed differs between cases/arms")
        if self.run_id != "imgsdxltargetcmprun_" + content_sha256(
            self.model_dump(mode="json", exclude={"run_id", "command_sha256"})
        )[7:39] or self.command_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"command_sha256"})
        ):
            raise ValueError("target comparison command identity/hash mismatch")
        return self


@dataclass(frozen=True, slots=True)
class SdxlTargetComparisonSources:
    evaluation: LocalImageSdxlReviewedEvaluationCommand
    lora: SdxlLoraEvaluationSources
    targets: tuple[SdxlPreparedSourceTrainingTarget, ...]
    expressions: tuple[tuple[str, TargetExpression], ...]


def parse_sdxl_target_comparison_sources(
    command: LocalImageSdxlTargetComparisonCommand, metadata: Mapping[str, bytes]
) -> SdxlTargetComparisonSources:
    from eom_image_contracts.validation import validate_contract

    raw = metadata["inputs/lora-evaluation-command.json"]
    if not 0 < len(raw) <= 256 * 1024 or (
        "sha256:" + hashlib.sha256(raw).hexdigest() != command.lora_evaluation_command.sha256
    ):
        raise ValueError("target comparison evaluation metadata hash/bound mismatch")
    validate_contract("sdxl-lora-evaluation-command-v2", json.loads(raw))
    evaluation = LocalImageSdxlReviewedEvaluationCommand.model_validate_json(raw)
    if raw != content_json_bytes(evaluation.model_dump(mode="json")):
        raise ValueError("target comparison evaluation is noncanonical")
    lora = parse_sdxl_lora_evaluation_sources(
        evaluation,
        baseline_payload=metadata["inputs/baseline-command.json"],
        training_command_payload=metadata["inputs/training-command.json"],
        training_result_payload=metadata["inputs/training-result.json"],
        manifest_payload=metadata["inputs/adapter-manifest.json"],
    )
    if not isinstance(lora.training_command, LocalImageSdxlReviewedMicroCommand):
        raise ValueError("target comparison requires reviewed training")
    targets = parse_sdxl_reviewed_micro_sources(lora.training_command, metadata)
    # Output revisions intentionally omit derived expression labels. Resolve them from the
    # already validated preparation command, keyed by the selected Artifact revision.
    recipes = {}
    for index, batch in enumerate(lora.training_command.target_batches):
        preparation = LocalImageSdxlSourceTrainingTargetCommand.model_validate_json(
            metadata[f"inputs/target-batches/{index}/command.json"]
        )
        for decision in preparation.decisions:
            if decision.disposition == "PREPARE":
                recipes[
                    (
                        batch.result.artifact_id,
                        batch.result.artifact_revision_id,
                        decision.sample_id,
                    )
                ] = decision.expression
    expressions = tuple(
        (
            sample.sample_id,
            recipes[
                (
                    sample.source_image.artifact_id,
                    sample.source_image.artifact_revision_id,
                    sample.sample_id,
                )
            ],
        )
        for sample in lora.training_command.training_samples
    )
    sources = SdxlTargetComparisonSources(evaluation, lora, tuple(targets.values()), expressions)
    validate_sdxl_target_comparison_sources(command, sources)
    return sources


def validate_sdxl_target_comparison_sources(
    command: LocalImageSdxlTargetComparisonCommand, sources: SdxlTargetComparisonSources
) -> None:
    validate_sdxl_lora_evaluation_sources(
        sources.evaluation,
        sources.lora.baseline,
        sources.lora.training_command,
        sources.lora.training_result,
        sources.lora.manifest,
    )
    training = sources.lora.training_command
    if not isinstance(training, LocalImageSdxlReviewedMicroCommand):
        raise ValueError("target comparison training family mismatch")
    samples = {sample.sample_id: sample for sample in training.training_samples}
    targets = {target.sample_id: target for target in sources.targets}
    expressions = dict(sources.expressions)
    if command.created_at < sources.evaluation.created_at:
        raise ValueError("target comparison predates its evaluation source")
    for entry in command.cases:
        sample, target = samples.get(entry.sample_id), targets.get(entry.sample_id)
        if (
            sample is None
            or target is None
            or (
                (entry.target_id, entry.target_revision_id)
                != (sample.target_id, sample.target_revision_id)
                or entry.case.reference_image != sample.source_image
                or entry.expression != expressions.get(entry.sample_id)
                or (entry.case.reference_width_px, entry.case.reference_height_px) != (768, 512)
            )
        ):
            raise ValueError("target comparison source/target revision/expression mismatch")


class LocalImageSdxlTargetComparisonResult(FrozenModel):
    schema_version: Literal["local-image-sdxl-target-comparison-result/1.0"]
    run_id: str = Field(pattern=r"^imgsdxltargetcmprun_[0-9a-f]{32}$")
    command_sha256: Sha256
    baseline_command_sha256: Sha256
    training_result_sha256: Sha256
    model: SdxlLineartStackPointer
    case_relation: Literal["REVIEWED_TRAIN_TARGET_NOT_HOLDOUT"]
    conditioning_policy: Literal["FIT_GRAYSCALE_INVERT_832X512/1.0"]
    status: Literal["SUCCEEDED", "FAILED"]
    error_code: SdxlProbeErrorCode | None
    runtime: LocalImageRuntime | None
    conditionings: tuple[SdxlLineartProbeConditioning, ...] = Field(max_length=3)
    outputs: tuple[SdxlLearnedComparisonOutput, ...] = Field(max_length=6)
    started_at: datetime
    completed_at: datetime
    duration_ms: int = Field(ge=1, le=3_600_000)
    result_sha256: Sha256

    _timestamps_utc = field_validator("started_at", "completed_at")(_utc)

    @model_validator(mode="after")
    def exact_result(self) -> Self:
        keys = tuple((out.arm, out.case_id, out.seed) for out in self.outputs)
        ids = tuple(entry.case_id for entry in self.conditionings)
        if (
            keys != tuple(sorted(set(keys)))
            or ids != tuple(sorted(set(ids)))
            or (
                self.completed_at < self.started_at
                or (self.status == "SUCCEEDED") != (self.error_code is None)
            )
        ):
            raise ValueError("target comparison result order/status/time mismatch")
        if (
            self.outputs
            and (
                self.runtime is None
                or self.runtime.peak_gpu_memory_bytes
                < max(out.peak_gpu_memory_bytes for out in self.outputs)
            )
        ) or (self.status == "SUCCEEDED" and (self.runtime is None or not self.outputs)):
            raise ValueError("target comparison lacks output/runtime evidence")
        if self.result_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"result_sha256"})
        ):
            raise ValueError("target comparison result hash mismatch")
        return self


def validate_sdxl_target_comparison_result(
    command: LocalImageSdxlTargetComparisonCommand,
    sources: SdxlTargetComparisonSources,
    result: LocalImageSdxlTargetComparisonResult,
) -> None:
    validate_sdxl_target_comparison_sources(command, sources)
    expected = tuple(
        (arm, entry.case.case_id, command.seed)
        for arm in LEARNED_COMPARISON_ARMS
        for entry in command.cases
    )
    observed = tuple((out.arm, out.case_id, out.seed) for out in result.outputs)
    if (
        result.run_id != command.run_id
        or result.command_sha256 != command.command_sha256
        or result.baseline_command_sha256 != sources.lora.baseline.command_sha256
        or result.training_result_sha256 != sources.lora.training_result.result_sha256
        or result.model != sources.lora.baseline.model
        or result.started_at < command.created_at
        or result.conditioning_policy != command.conditioning_policy
        or result.case_relation != command.case_relation
    ):
        raise ValueError("target comparison result differs from pinned inputs")
    if observed != expected[: len(observed)] or tuple(
        out.case_id for out in result.conditionings
    ) != tuple(entry.case.case_id for entry in command.cases):
        raise ValueError("target comparison output/conditioning coverage mismatch")
    if result.status == "SUCCEEDED" and (
        observed != expected
        or result.runtime is None
        or result.runtime.peak_gpu_memory_bytes > command.budget.maximum_peak_gpu_memory_bytes
        or result.duration_ms > command.budget.maximum_duration_ms
    ):
        raise ValueError("target comparison success coverage/budget mismatch")
    originals = {entry.case.case_id: entry.case.reference_image.sha256 for entry in command.cases}
    hashes = {entry.case_id: entry.sha256 for entry in result.conditionings}
    if any(
        out.reference_sha256 != originals[out.case_id]
        or out.conditioning_sha256 != hashes[out.case_id]
        for out in result.outputs
    ):
        raise ValueError("target comparison output source hash mismatch")
