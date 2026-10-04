"""Matched spatial diagnostic pinned to reviewed Canny inputs and existing T2I history."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Self, TypeVar

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.models import (
    FrozenModel,
    ImageEvaluationArtifactMember,
    LocalImageRuntime,
    Sha256,
    content_json_bytes,
    content_sha256,
)
from eom_image_contracts.sdxl_canny_conditioning import (
    PREFIX,
    LocalImageSdxlCannyConditioningCommand,
    LocalImageSdxlCannyConditioningResult,
    parse_sdxl_canny_parent,
    validate_sdxl_canny_result,
)
from eom_image_contracts.sdxl_canny_controlnet import SdxlCannyControllerPointer
from eom_image_contracts.sdxl_learned_comparison import (
    LEARNED_COMPARISON_ARMS,
    SdxlLearnedComparisonBudget,
    SdxlLearnedComparisonOutput,
)
from eom_image_contracts.sdxl_lineart_probe import SdxlLineartStackPointer, SdxlProbeErrorCode
from eom_image_contracts.sdxl_target_comparison import (
    LocalImageSdxlTargetComparisonCommand,
    LocalImageSdxlTargetComparisonResult,
    SdxlTargetComparisonSources,
    parse_sdxl_target_comparison_sources,
    validate_sdxl_target_comparison_result,
)

_T = TypeVar("_T", bound=FrozenModel)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("spatial comparison timestamp must use UTC")
    return value


def _pin(pin: ImageEvaluationArtifactMember, family: str, filename: str) -> None:
    if (
        pin.schema_ref != PREFIX + family + "/1.0"
        or pin.media_type != "application/json"
        or pin.member_path != "manifests/" + filename + ".json"
    ):
        raise ValueError("spatial comparison requires an exact pinned source family/member")


# The isolated numerical runner is Python 3.11; PEP 695 syntax cannot be installed there.
def _document(  # noqa: UP047
    raw: bytes, pin: ImageEvaluationArtifactMember, model: type[_T], schema: str
) -> _T:
    from eom_image_contracts.validation import validate_contract

    if not 0 < len(raw) <= 256 * 1024 or "sha256:" + hashlib.sha256(raw).hexdigest() != pin.sha256:
        raise ValueError("spatial source metadata bound/hash mismatch")
    validate_contract(schema, json.loads(raw))
    value = model.model_validate_json(raw)
    if raw != content_json_bytes(value.model_dump(mode="json")):
        raise ValueError("spatial source metadata is noncanonical")
    return value


class SdxlCannyDetailDecision(FrozenModel):
    case_id: str = Field(pattern=r"^imgsdxlcase_[0-9a-f]{32}$")
    source_sha256: Sha256
    conditioning_sha256: Sha256
    disposition: Literal["PASS", "FAIL"]
    reason: str = Field(min_length=1, max_length=512)


class LocalImageSdxlCannyDetailReview(FrozenModel):
    schema_version: Literal["local-image-sdxl-canny-detail-review/1.0"]
    created_at: datetime
    created_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    conditioning_command: ImageEvaluationArtifactMember
    conditioning_result: ImageEvaluationArtifactMember
    own_review_evidence: ImageEvaluationArtifactMember
    mode: Literal["OWN_DIRECT_SOURCE_AND_CONDITIONING_NOT_BLIND"]
    final_illustration_quality: Literal["NOT_EVALUATED"]
    decisions: tuple[SdxlCannyDetailDecision, ...] = Field(min_length=1, max_length=3)
    review_sha256: Sha256

    _created_utc = field_validator("created_at")(_utc)

    @model_validator(mode="after")
    def exact_review(self) -> Self:
        _pin(
            self.conditioning_command,
            "sdxl-canny-conditioning-command",
            "sdxl-canny-conditioning-command",
        )
        _pin(
            self.conditioning_result,
            "sdxl-canny-conditioning-result",
            "sdxl-canny-conditioning-result",
        )
        evidence = self.own_review_evidence
        if (
            evidence.member_path != "reports/own-input-review.json"
            or evidence.media_type != "text/plain"
            or evidence.schema_ref != "eom://schemas/operations/plain-text-log/1.0"
        ):
            raise ValueError("Canny detail review lacks pinned own-review evidence")
        ids = tuple(decision.case_id for decision in self.decisions)
        if ids != tuple(sorted(set(ids))) or self.review_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"review_sha256"})
        ):
            raise ValueError("Canny detail review order/hash mismatch")
        return self


class SdxlCannyControlParameters(FrozenModel):
    conditioning_scale: float = Field(default=1.0, ge=1.0, le=1.0, strict=True)
    guidance_start: float = Field(default=0.0, ge=0.0, le=0.0, strict=True)
    guidance_end: float = Field(default=1.0, ge=1.0, le=1.0, strict=True)
    resource_profile: Literal["ALL_GPU_FP16_NO_OFFLOAD"] = "ALL_GPU_FP16_NO_OFFLOAD"


class SdxlCannyComparisonBudget(SdxlLearnedComparisonBudget):
    maximum_outputs: Literal[6] = 6


class LocalImageSdxlCannyComparisonCommand(FrozenModel):
    schema_version: Literal["local-image-sdxl-canny-comparison-command/1.0"]
    run_id: str = Field(pattern=r"^imgsdxlcannycmprun_[0-9a-f]{32}$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    created_at: datetime
    purpose: Literal["EVALUATION_ONLY_MATCHED_CANNY_CONTROLNET"]
    activation_policy: Literal["FORBIDDEN"]
    case_relation: Literal["REVIEWED_TRAIN_TARGET_NOT_HOLDOUT"]
    conditioning_command: ImageEvaluationArtifactMember
    conditioning_result: ImageEvaluationArtifactMember
    detail_review: ImageEvaluationArtifactMember
    baseline_result: ImageEvaluationArtifactMember
    controller: SdxlCannyControllerPointer
    control: SdxlCannyControlParameters
    budget: SdxlCannyComparisonBudget
    command_sha256: Sha256

    _created_utc = field_validator("created_at")(_utc)

    @model_validator(mode="after")
    def exact_command(self) -> Self:
        for pin, family in (
            (self.conditioning_command, "sdxl-canny-conditioning-command"),
            (self.conditioning_result, "sdxl-canny-conditioning-result"),
            (self.detail_review, "sdxl-canny-detail-review"),
            (self.baseline_result, "sdxl-target-comparison-result"),
        ):
            _pin(pin, family, family)
        if self.run_id != "imgsdxlcannycmprun_" + content_sha256(
            self.model_dump(mode="json", exclude={"run_id", "command_sha256"})
        )[7:39] or self.command_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"command_sha256"})
        ):
            raise ValueError("spatial comparison command identity/hash mismatch")
        return self


@dataclass(frozen=True, slots=True)
class SdxlCannyComparisonSources:
    preparation: LocalImageSdxlCannyConditioningCommand
    conditionings: LocalImageSdxlCannyConditioningResult
    parent: LocalImageSdxlTargetComparisonCommand
    targets: SdxlTargetComparisonSources
    review: LocalImageSdxlCannyDetailReview
    baseline: LocalImageSdxlTargetComparisonResult


def parse_sdxl_canny_comparison_sources(
    command: LocalImageSdxlCannyComparisonCommand,
    metadata: Mapping[str, bytes],
) -> SdxlCannyComparisonSources:
    preparation = _document(
        metadata["inputs/canny-command.json"],
        command.conditioning_command,
        LocalImageSdxlCannyConditioningCommand,
        "sdxl-canny-conditioning-command",
    )
    parent = parse_sdxl_canny_parent(preparation, metadata["inputs/parent-command.json"])
    targets = parse_sdxl_target_comparison_sources(parent, metadata)
    conditionings = _document(
        metadata["inputs/canny-result.json"],
        command.conditioning_result,
        LocalImageSdxlCannyConditioningResult,
        "sdxl-canny-conditioning-result",
    )
    review = _document(
        metadata["inputs/canny-detail-review.json"],
        command.detail_review,
        LocalImageSdxlCannyDetailReview,
        "sdxl-canny-detail-review",
    )
    baseline = _document(
        metadata["inputs/source-target-result.json"],
        command.baseline_result,
        LocalImageSdxlTargetComparisonResult,
        "sdxl-target-comparison-result",
    )
    evidence = metadata["inputs/canny-own-review-evidence.json"]
    if (
        not 0 < len(evidence) <= 256 * 1024
        or "sha256:" + hashlib.sha256(evidence).hexdigest() != review.own_review_evidence.sha256
    ):
        raise ValueError("Canny input review evidence bound/hash mismatch")
    own = json.loads(evidence)
    if (
        own["status"] != "OWN_CANNY_SOURCE_DETAIL_REVIEW_COMPLETE"
        or own["conditioning_result_sha256"] != command.conditioning_result.sha256
        or own["conditioning_artifact_id"] != command.conditioning_result.artifact_id
        or own["conditioning_artifact_revision_id"]
        != command.conditioning_result.artifact_revision_id
        or own["final_illustration_quality"] != "NOT_EVALUATED"
        or own["review_mode"] != review.mode
        or len(own["rows"]) != len(review.decisions)
        or review.created_at < _utc(datetime.fromisoformat(own["created_at"]))
    ):
        raise ValueError("Canny input review evidence refers to different inputs or acceptance")
    for row, decision in zip(own["rows"], review.decisions, strict=True):
        if (
            row["case_id"] != decision.case_id
            or row["source"]["sha256"] != decision.source_sha256
            or row["sha256"] != decision.conditioning_sha256
            or row["own_input_detail_status"] != decision.disposition
        ):
            raise ValueError("Canny input detail decision differs from its recorded own evidence")
    sources = SdxlCannyComparisonSources(
        preparation, conditionings, parent, targets, review, baseline
    )
    validate_sdxl_canny_comparison_sources(command, sources)
    return sources


def validate_sdxl_canny_comparison_sources(
    command: LocalImageSdxlCannyComparisonCommand,
    sources: SdxlCannyComparisonSources,
) -> None:
    validate_sdxl_canny_result(
        sources.preparation, sources.parent, sources.targets, sources.conditionings
    )
    validate_sdxl_target_comparison_result(sources.parent, sources.targets, sources.baseline)
    if (
        sources.conditionings.status != "SUCCEEDED"
        or sources.baseline.status != "SUCCEEDED"
        or sources.review.conditioning_command != command.conditioning_command
        or sources.review.conditioning_result != command.conditioning_result
        or sources.review.created_at < sources.conditionings.completed_at
        or command.created_at < max(sources.review.created_at, sources.baseline.completed_at)
    ):
        raise ValueError("spatial comparison source status/review/time mismatch")
    expected = tuple(
        (out.case_id, out.source.sha256, out.sha256) for out in sources.conditionings.outputs
    )
    actual = tuple(
        (row.case_id, row.source_sha256, row.conditioning_sha256)
        for row in sources.review.decisions
    )
    if (
        actual != expected
        or any(row.disposition != "PASS" for row in sources.review.decisions)
        or 2 * len(expected) > command.budget.maximum_outputs
    ):
        raise ValueError("spatial comparison input detail gate or coverage/budget fails")


class LocalImageSdxlCannyComparisonResult(FrozenModel):
    schema_version: Literal["local-image-sdxl-canny-comparison-result/1.0"]
    run_id: str = Field(pattern=r"^imgsdxlcannycmprun_[0-9a-f]{32}$")
    command_sha256: Sha256
    preparation_result_sha256: Sha256
    detail_review_sha256: Sha256
    baseline_result_sha256: Sha256
    base_model: SdxlLineartStackPointer
    controller: SdxlCannyControllerPointer
    control: SdxlCannyControlParameters
    case_relation: Literal["REVIEWED_TRAIN_TARGET_NOT_HOLDOUT"]
    quality_acceptance: Literal["NOT_REVIEWED"]
    activation_policy: Literal["FORBIDDEN"]
    status: Literal["SUCCEEDED", "FAILED"]
    error_code: SdxlProbeErrorCode | None
    runtime: LocalImageRuntime | None
    outputs: tuple[SdxlLearnedComparisonOutput, ...] = Field(max_length=6)
    started_at: datetime
    completed_at: datetime
    duration_ms: int = Field(ge=1, le=3_600_000)
    result_sha256: Sha256

    _timestamps_utc = field_validator("started_at", "completed_at")(_utc)

    @model_validator(mode="after")
    def exact_result(self) -> Self:
        keys = tuple((out.arm, out.case_id, out.seed) for out in self.outputs)
        if (
            keys != tuple(sorted(set(keys)))
            or self.completed_at < self.started_at
            or (self.status == "SUCCEEDED") != (self.error_code is None)
        ):
            raise ValueError("spatial comparison result order/status/time mismatch")
        if self.outputs and (
            self.runtime is None
            or self.runtime.peak_gpu_memory_bytes
            < max(out.peak_gpu_memory_bytes for out in self.outputs)
        ):
            raise ValueError("spatial comparison result lacks output runtime evidence")
        if self.result_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"result_sha256"})
        ):
            raise ValueError("spatial comparison result hash mismatch")
        return self


def validate_sdxl_canny_comparison_result(
    command: LocalImageSdxlCannyComparisonCommand,
    sources: SdxlCannyComparisonSources,
    result: LocalImageSdxlCannyComparisonResult,
) -> None:
    validate_sdxl_canny_comparison_sources(command, sources)
    expected = tuple(
        (arm, out.case_id, sources.parent.seed)
        for arm in LEARNED_COMPARISON_ARMS
        for out in sources.conditionings.outputs
    )
    observed = tuple((out.arm, out.case_id, out.seed) for out in result.outputs)
    if (
        result.run_id != command.run_id
        or result.command_sha256 != command.command_sha256
        or result.preparation_result_sha256 != sources.conditionings.result_sha256
        or result.detail_review_sha256 != sources.review.review_sha256
        or result.baseline_result_sha256 != sources.baseline.result_sha256
        or result.base_model != sources.targets.lora.baseline.model
        or result.controller != command.controller
        or result.control != command.control
        or result.started_at < command.created_at
        or observed != expected[: len(observed)]
    ):
        raise ValueError(
            "spatial comparison result differs from pinned source/model/control/prefix"
        )
    if result.status == "SUCCEEDED" and (
        observed != expected
        or result.runtime is None
        or result.runtime.peak_gpu_memory_bytes > command.budget.maximum_peak_gpu_memory_bytes
        or result.duration_ms > command.budget.maximum_duration_ms
    ):
        raise ValueError("spatial comparison success coverage/resource budget mismatch")
    maps = {out.case_id: out for out in sources.conditionings.outputs}
    if any(
        out.reference_sha256 != maps[out.case_id].source.sha256
        or out.conditioning_sha256 != maps[out.case_id].sha256
        for out in result.outputs
    ):
        raise ValueError("spatial comparison output source/conditioning hash mismatch")
