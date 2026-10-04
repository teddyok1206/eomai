"""Source-initialized successor pins an existing spatial comparison without copying it."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.models import (
    FrozenModel,
    ImageEvaluationArtifactMember,
    LocalImageRuntime,
    Sha256,
    content_sha256,
)
from eom_image_contracts.sdxl_canny_comparison import (
    LocalImageSdxlCannyComparisonCommand,
    LocalImageSdxlCannyComparisonResult,
    SdxlCannyComparisonBudget,
    SdxlCannyComparisonSources,
    _document,
    _pin,
    _utc,
    parse_sdxl_canny_comparison_sources,
    validate_sdxl_canny_comparison_result,
)
from eom_image_contracts.sdxl_learned_comparison import (
    LEARNED_COMPARISON_ARMS,
    SdxlLearnedComparisonOutput,
)
from eom_image_contracts.sdxl_lineart_probe import SdxlProbeErrorCode


class SdxlCannyReferenceInitialization(FrozenModel):
    policy: Literal["FIT_GRAYSCALE_WHITE_RGB_832X512/1.0"] = "FIT_GRAYSCALE_WHITE_RGB_832X512/1.0"
    denoising_strength: float = Field(default=0.35, ge=0.35, le=0.35, strict=True)
    scheduler_steps: int = Field(default=30, ge=3, le=100, strict=True)
    effective_denoising_steps: int = Field(default=10, ge=1, le=100, strict=True)
    pillow_version: Literal["11.3.0"] = "11.3.0"

    @model_validator(mode="after")
    def exact_timestep_count(self) -> Self:
        if self.effective_denoising_steps != int(self.scheduler_steps * self.denoising_strength):
            raise ValueError("reference effective steps differ from pinned scheduler/strength")
        return self


class LocalImageSdxlCannyReferenceCommand(FrozenModel):
    schema_version: Literal["local-image-sdxl-canny-reference-command/1.0"]
    run_id: str = Field(pattern=r"^imgsdxlcannyrefrun_[0-9a-f]{32}$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    created_at: datetime
    purpose: Literal["EVALUATION_ONLY_MATCHED_CANNY_SOURCE_INITIALIZATION"]
    activation_policy: Literal["FORBIDDEN"]
    spatial_command: ImageEvaluationArtifactMember
    spatial_result: ImageEvaluationArtifactMember
    initialization: SdxlCannyReferenceInitialization
    budget: SdxlCannyComparisonBudget
    command_sha256: Sha256

    _created_utc = field_validator("created_at")(_utc)

    @model_validator(mode="after")
    def exact_command(self) -> Self:
        _pin(self.spatial_command, "sdxl-canny-comparison-command", "sdxl-canny-comparison-command")
        _pin(self.spatial_result, "sdxl-canny-comparison-result", "sdxl-canny-comparison-result")
        if self.run_id != "imgsdxlcannyrefrun_" + content_sha256(
            self.model_dump(mode="json", exclude={"run_id", "command_sha256"})
        )[7:39] or self.command_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"command_sha256"})
        ):
            raise ValueError("reference comparison command identity/hash mismatch")
        return self


@dataclass(frozen=True, slots=True)
class SdxlCannyReferenceSources:
    spatial_command: LocalImageSdxlCannyComparisonCommand
    spatial_result: LocalImageSdxlCannyComparisonResult
    spatial_sources: SdxlCannyComparisonSources


def parse_sdxl_canny_reference_predecessors(
    command: LocalImageSdxlCannyReferenceCommand,
    spatial_command_raw: bytes,
    spatial_result_raw: bytes,
) -> tuple[LocalImageSdxlCannyComparisonCommand, LocalImageSdxlCannyComparisonResult]:
    spatial = _document(
        spatial_command_raw,
        command.spatial_command,
        LocalImageSdxlCannyComparisonCommand,
        "sdxl-canny-comparison-command",
    )
    result = _document(
        spatial_result_raw,
        command.spatial_result,
        LocalImageSdxlCannyComparisonResult,
        "sdxl-canny-comparison-result",
    )
    return spatial, result


def parse_sdxl_canny_reference_sources(
    command: LocalImageSdxlCannyReferenceCommand,
    metadata: Mapping[str, bytes],
) -> SdxlCannyReferenceSources:
    spatial, result = parse_sdxl_canny_reference_predecessors(
        command, metadata["inputs/spatial-command.json"], metadata["inputs/spatial-result.json"]
    )
    sources = SdxlCannyReferenceSources(
        spatial, result, parse_sdxl_canny_comparison_sources(spatial, metadata)
    )
    validate_sdxl_canny_reference_sources(command, sources)
    return sources


def validate_sdxl_canny_reference_sources(
    command: LocalImageSdxlCannyReferenceCommand,
    sources: SdxlCannyReferenceSources,
) -> None:
    validate_sdxl_canny_comparison_result(
        sources.spatial_command, sources.spatial_sources, sources.spatial_result
    )
    cases = sources.spatial_sources.parent.cases
    hashes = {entry.case.reference_image.sha256 for entry in cases}
    if (
        sources.spatial_result.status != "SUCCEEDED"
        or command.created_at < sources.spatial_result.completed_at
        or sources.spatial_sources.targets.lora.baseline.inference_steps
        != command.initialization.scheduler_steps
        or len(hashes) != len(cases)
        or len(cases) * len(LEARNED_COMPARISON_ARMS) > command.budget.maximum_outputs
    ):
        raise ValueError("reference initialization source/status/time/step/identity mismatch")


class SdxlCannyReferenceTrace(FrozenModel):
    case_id: str = Field(pattern=r"^imgsdxlcase_[0-9a-f]{32}$")
    source_sha256: Sha256
    conditioning_sha256: Sha256
    initialization_rgb_sha256: Sha256
    width_px: Literal[832] = 832
    height_px: Literal[512] = 512


class LocalImageSdxlCannyReferenceResult(FrozenModel):
    schema_version: Literal["local-image-sdxl-canny-reference-result/1.0"]
    run_id: str = Field(pattern=r"^imgsdxlcannyrefrun_[0-9a-f]{32}$")
    command_sha256: Sha256
    spatial_command_sha256: Sha256
    spatial_result_sha256: Sha256
    initialization: SdxlCannyReferenceInitialization
    inputs: tuple[SdxlCannyReferenceTrace, ...] = Field(min_length=1, max_length=3)
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
        ids = tuple(row.case_id for row in self.inputs)
        if (
            keys != tuple(sorted(set(keys)))
            or ids != tuple(sorted(set(ids)))
            or self.completed_at < self.started_at
            or (self.status == "SUCCEEDED") != (self.error_code is None)
        ):
            raise ValueError("reference result order/status/time mismatch")
        if self.outputs and (
            self.runtime is None
            or self.runtime.peak_gpu_memory_bytes
            < max(out.peak_gpu_memory_bytes for out in self.outputs)
        ):
            raise ValueError("reference result lacks numerical evidence")
        if self.result_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"result_sha256"})
        ):
            raise ValueError("reference result hash mismatch")
        return self


def validate_sdxl_canny_reference_result(
    command: LocalImageSdxlCannyReferenceCommand,
    sources: SdxlCannyReferenceSources,
    result: LocalImageSdxlCannyReferenceResult,
) -> None:
    validate_sdxl_canny_reference_sources(command, sources)
    spatial = sources.spatial_sources
    maps = {row.case_id: row for row in spatial.conditionings.outputs}
    expected = tuple(
        (arm, entry.case.case_id, spatial.parent.seed)
        for arm in LEARNED_COMPARISON_ARMS
        for entry in spatial.parent.cases
    )
    observed = tuple((row.arm, row.case_id, row.seed) for row in result.outputs)
    if (
        result.run_id != command.run_id
        or result.command_sha256 != command.command_sha256
        or result.spatial_command_sha256 != sources.spatial_command.command_sha256
        or result.spatial_result_sha256 != sources.spatial_result.result_sha256
        or result.initialization != command.initialization
        or result.started_at < command.created_at
        or observed != expected[: len(observed)]
        or tuple(row.case_id for row in result.inputs) != tuple(maps)
        or any(
            row.source_sha256 != maps[row.case_id].source.sha256
            or row.conditioning_sha256 != maps[row.case_id].sha256
            for row in result.inputs
        )
        or any(
            row.reference_sha256 != maps[row.case_id].source.sha256
            or row.conditioning_sha256 != maps[row.case_id].sha256
            for row in result.outputs
        )
    ):
        raise ValueError("reference result differs from pinned source/conditioning/prefix")
    if result.status == "SUCCEEDED" and (
        observed != expected
        or result.runtime is None
        or result.runtime.peak_gpu_memory_bytes > command.budget.maximum_peak_gpu_memory_bytes
        or result.duration_ms > command.budget.maximum_duration_ms
    ):
        raise ValueError("reference result success coverage/resource budget mismatch")
