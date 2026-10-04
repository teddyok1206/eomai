"""Pinned CPU publication derivatives, never replacement native SDXL evidence."""

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
    Sha256,
    content_json_bytes,
    content_sha256,
)
from eom_image_contracts.sdxl_learned_comparison import SdxlLearnedComparisonOutput
from eom_image_contracts.sdxl_target_comparison import (
    LocalImageSdxlTargetComparisonCommand,
    LocalImageSdxlTargetComparisonResult,
    SdxlTargetComparisonSources,
    parse_sdxl_target_comparison_sources,
    validate_sdxl_target_comparison_result,
)
from eom_image_contracts.visual_reference import (
    LocalImageAssessmentLineArtMetricsV2,
    LocalImageAssessmentLineArtPostprocessV2,
    LocalImageAssessmentLineArtRuntimeV2,
)

PREFIX = "eom://schemas/image-provider/local-image-"
PublicationErrorCode = Literal[
    "LOCAL_IMAGE_LINE_ART_INPUT_INVALID",
    "LOCAL_IMAGE_LINE_ART_FOREGROUND_INVALID",
    "LOCAL_IMAGE_LINE_ART_BORDER_INVALID",
    "LOCAL_IMAGE_LINE_ART_EDGE_DENSITY_INVALID",
    "LOCAL_IMAGE_LINE_ART_FINE_DETAIL_INVALID",
    "LOCAL_IMAGE_LINE_ART_TINY_COMPONENTS_INVALID",
    "LOCAL_IMAGE_LINE_ART_COMPONENT_COUNT_INVALID",
    "SDXL_PUBLICATION_EXEC_FAILED",
    "SDXL_PUBLICATION_BUDGET_EXCEEDED",
]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("publication comparison timestamp must use UTC")
    return value


class SdxlPublicationBudget(FrozenModel):
    maximum_outputs: Literal[6] = 6
    maximum_duration_ms: int = Field(ge=1000, le=90_000)
    maximum_input_png_bytes: Literal[16_777_216] = 16_777_216


class LocalImageSdxlPublicationComparisonCommand(FrozenModel):
    schema_version: Literal["local-image-sdxl-publication-comparison-command/1.0"]
    run_id: str = Field(pattern=r"^imgsdxlpublicationrun_[0-9a-f]{32}$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    created_at: datetime
    purpose: Literal["EVALUATION_ONLY_PINNED_CPU_PUBLICATION"]
    activation_policy: Literal["FORBIDDEN"]
    case_relation: Literal["REVIEWED_TRAIN_TARGET_NOT_HOLDOUT"]
    source_command: ImageEvaluationArtifactMember
    source_result: ImageEvaluationArtifactMember
    postprocess: LocalImageAssessmentLineArtPostprocessV2
    policy_sha256: Sha256
    pillow_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$", max_length=32)
    budget: SdxlPublicationBudget
    command_sha256: Sha256

    _created_utc = field_validator("created_at")(_utc)

    @model_validator(mode="after")
    def exact_command(self) -> Self:
        for kind, pin in (("command", self.source_command), ("result", self.source_result)):
            if (
                pin.member_path != f"manifests/sdxl-target-comparison-{kind}.json"
                or pin.schema_ref != PREFIX + f"sdxl-target-comparison-{kind}/1.0"
                or pin.media_type != "application/json"
            ):
                raise ValueError("publication requires exact target-comparison pointers")
        if self.policy_sha256 != content_sha256(self.postprocess.model_dump(mode="json")):
            raise ValueError("publication policy hash mismatch")
        expected_id = (
            "imgsdxlpublicationrun_"
            + content_sha256(self.model_dump(mode="json", exclude={"run_id", "command_sha256"}))[
                7:39
            ]
        )
        if self.run_id != expected_id or self.command_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"command_sha256"})
        ):
            raise ValueError("publication command identity/hash mismatch")
        return self


@dataclass(frozen=True, slots=True)
class SdxlPublicationSources:
    command: LocalImageSdxlTargetComparisonCommand
    result: LocalImageSdxlTargetComparisonResult
    lineage: SdxlTargetComparisonSources


def parse_sdxl_publication_sources(
    command: LocalImageSdxlPublicationComparisonCommand, metadata: Mapping[str, bytes]
) -> SdxlPublicationSources:
    from eom_image_contracts.validation import validate_contract

    parsed = []
    for kind, pin, model in (
        ("command", command.source_command, LocalImageSdxlTargetComparisonCommand),
        ("result", command.source_result, LocalImageSdxlTargetComparisonResult),
    ):
        raw = metadata[f"inputs/parent-{kind}.json"]
        if not 0 < len(raw) <= 256 * 1024 or (
            "sha256:" + hashlib.sha256(raw).hexdigest() != pin.sha256
        ):
            raise ValueError("publication parent metadata hash/bound mismatch")
        value = json.loads(raw)
        validate_contract(f"sdxl-target-comparison-{kind}", value)
        parent = model.model_validate(value)
        if raw != content_json_bytes(parent.model_dump(mode="json")):
            raise ValueError("publication parent metadata is noncanonical")
        parsed.append(parent)
    parent_command, parent_result = parsed
    assert isinstance(parent_command, LocalImageSdxlTargetComparisonCommand)
    assert isinstance(parent_result, LocalImageSdxlTargetComparisonResult)
    lineage = parse_sdxl_target_comparison_sources(parent_command, metadata)
    sources = SdxlPublicationSources(parent_command, parent_result, lineage)
    validate_sdxl_publication_sources(command, sources)
    return sources


def validate_sdxl_publication_sources(
    command: LocalImageSdxlPublicationComparisonCommand, sources: SdxlPublicationSources
) -> None:
    validate_sdxl_target_comparison_result(sources.command, sources.lineage, sources.result)
    if (
        sources.result.status != "SUCCEEDED"
        or command.created_at < sources.result.completed_at
        or len(sources.result.outputs) > command.budget.maximum_outputs
        or any(
            output.size_bytes > command.budget.maximum_input_png_bytes
            for output in sources.result.outputs
        )
    ):
        raise ValueError("publication parent is failed, incomplete, too large or in the future")


def sdxl_publication_source_pointer(
    command: LocalImageSdxlPublicationComparisonCommand, output: SdxlLearnedComparisonOutput
) -> ImageEvaluationArtifactMember:
    return ImageEvaluationArtifactMember(
        artifact_id=command.source_result.artifact_id,
        artifact_revision_id=command.source_result.artifact_revision_id,
        member_path=output.member_path,
        schema_ref=PREFIX + "sdxl-lineart-probe-output/1.0",
        media_type="image/png",
        sha256=output.sha256,
    )


def sdxl_publication_member(output: SdxlLearnedComparisonOutput, *, staged: bool) -> str:
    folder = "inputs/native" if staged else "outputs"
    return f"{folder}/{output.arm.lower()}/{output.case_id}-{output.seed:010d}.png"


class SdxlPublicationOutput(FrozenModel):
    case_id: str = Field(pattern=r"^imgsdxlcase_[0-9a-f]{32}$")
    arm: Literal["BASE", "LORA"]
    seed: int = Field(ge=0, le=2**32 - 1)
    source: ImageEvaluationArtifactMember
    member_path: str = Field(
        pattern=r"^outputs/(base|lora)/imgsdxlcase_[0-9a-f]{32}-[0-9]{10}\.png$"
    )
    sha256: Sha256
    size_bytes: int = Field(ge=1, le=16_777_216)
    width_px: Literal[800] = 800
    height_px: Literal[500] = 500
    mode: Literal["RGB"] = "RGB"
    output_tones: tuple[Literal[32, 96, 255], ...] = Field(min_length=1, max_length=3)
    metrics: LocalImageAssessmentLineArtMetricsV2

    @model_validator(mode="after")
    def exact_member(self) -> Self:
        if self.member_path != (
            f"outputs/{self.arm.lower()}/{self.case_id}-{self.seed:010d}.png"
        ) or self.output_tones != tuple(sorted(set(self.output_tones))):
            raise ValueError("publication output path/tones mismatch")
        return self


class LocalImageSdxlPublicationComparisonResult(FrozenModel):
    schema_version: Literal["local-image-sdxl-publication-comparison-result/1.0"]
    run_id: str = Field(pattern=r"^imgsdxlpublicationrun_[0-9a-f]{32}$")
    command_sha256: Sha256
    source_result_sha256: Sha256
    policy_sha256: Sha256
    status: Literal["SUCCEEDED", "FAILED"]
    error_code: PublicationErrorCode | None
    case_relation: Literal["REVIEWED_TRAIN_TARGET_NOT_HOLDOUT"]
    quality_state: Literal["UNREVIEWED_PUBLICATION_CANDIDATES"]
    activation_policy: Literal["FORBIDDEN"]
    runtime: LocalImageAssessmentLineArtRuntimeV2
    outputs: tuple[SdxlPublicationOutput, ...] = Field(max_length=6)
    started_at: datetime
    completed_at: datetime
    duration_ms: int = Field(ge=1, le=120_000)
    result_sha256: Sha256

    _timestamps_utc = field_validator("started_at", "completed_at")(_utc)

    @model_validator(mode="after")
    def exact_result(self) -> Self:
        keys = tuple((output.arm, output.case_id, output.seed) for output in self.outputs)
        if (
            keys != tuple(sorted(set(keys)))
            or self.completed_at < self.started_at
            or (self.status == "SUCCEEDED") != (self.error_code is None)
            or (self.status == "SUCCEEDED" and not self.outputs)
        ):
            raise ValueError("publication result order/status/time mismatch")
        if self.result_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"result_sha256"})
        ):
            raise ValueError("publication result hash mismatch")
        return self


def validate_sdxl_publication_result(
    command: LocalImageSdxlPublicationComparisonCommand,
    sources: SdxlPublicationSources,
    result: LocalImageSdxlPublicationComparisonResult,
) -> None:
    validate_sdxl_publication_sources(command, sources)
    expected = sources.result.outputs
    if (
        result.run_id != command.run_id
        or result.command_sha256 != command.command_sha256
        or result.source_result_sha256 != sources.result.result_sha256
        or result.policy_sha256 != command.policy_sha256
        or result.started_at < command.created_at
        or result.runtime.pillow_version != command.pillow_version
        or len(result.outputs) > len(expected)
    ):
        raise ValueError("publication result differs from pinned inputs/runtime")
    for source, output in zip(expected[: len(result.outputs)], result.outputs, strict=True):
        if (
            (output.arm, output.case_id, output.seed) != (source.arm, source.case_id, source.seed)
            or output.source != sdxl_publication_source_pointer(command, source)
            or output.member_path != sdxl_publication_member(source, staged=False)
        ):
            raise ValueError("publication output source/coverage mismatch")
        output.metrics.validate_policy(command.postprocess)
    if result.status == "SUCCEEDED" and (
        len(result.outputs) != len(expected)
        or result.duration_ms > command.budget.maximum_duration_ms
    ):
        raise ValueError("publication success lacks complete bounded coverage")
