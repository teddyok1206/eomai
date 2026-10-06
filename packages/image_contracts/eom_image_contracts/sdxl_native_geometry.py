"""Closed TRAIN-only size diagnostic; legacy receipts keep their original meaning."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.models import FrozenModel, LocalImageRuntime, Sha256, content_sha256
from eom_image_contracts.sdxl_lineart_probe import SdxlLineartStackPointer, SdxlProbeErrorCode
from eom_image_contracts.sdxl_native_evaluation import (
    LocalImageSdxlNativeEvaluationCommand,
    SdxlNativeEvaluationSources,
    SdxlNativeLoraEvaluationPin,
    SdxlNativeLoraEvaluationPinV2,
    SdxlNativeLoraEvaluationPinV3,
)
from eom_image_contracts.sdxl_native_training_targets import NATIVE_TARGET_CANVASES

GeometryCanvas = Literal["LEGACY_832X512", "SQUARE_1024", "PORTRAIT_768X1024", "LANDSCAPE_1024X768"]
GeometryArm = Literal["BASE", "LORA"]
GEOMETRY_ARMS: tuple[GeometryArm, ...] = ("BASE", "LORA")


def geometry_dimensions(canvas: GeometryCanvas) -> tuple[int, int]:
    if canvas == "LEGACY_832X512":
        return (832, 512)
    return NATIVE_TARGET_CANVASES[canvas]


class SdxlNativeGeometryCase(FrozenModel):
    sample_id: str = Field(pattern=r"^imgsourcecrop_[0-9a-f]{32}$")
    native_canvas: Literal["SQUARE_1024", "PORTRAIT_768X1024", "LANDSCAPE_1024X768"]
    training_caption_sha256: Sha256


class SdxlNativeGeometryNumerics(FrozenModel):
    inference_steps: Literal[30] = 30
    guidance_scale: float = Field(default=7.0, ge=7.0, le=7.0)
    adapter_conditioning_scale: float = Field(default=0.0, ge=0.0, le=0.0)
    seed: Literal[104729] = 104729


class SdxlNativeGeometryBudget(FrozenModel):
    maximum_generations: int = Field(ge=4, le=8, multiple_of=4)
    maximum_duration_ms: int = Field(ge=1000, le=600_000)
    maximum_peak_gpu_memory_bytes: int = Field(ge=1, le=16 * 1024**3)


class LocalImageSdxlNativeGeometryCommand(LocalImageSdxlNativeEvaluationCommand):
    schema_version: Literal["local-image-sdxl-lora-evaluation-command/1.3"]  # type: ignore[assignment]
    case_relation: Literal["ADMITTED_NATIVE_TRAIN_GEOMETRY_DIAGNOSTIC_NOT_HOLDOUT"]  # type: ignore[assignment]
    conditioning_policy: Literal["SYNTHETIC_BLACK_T2I_ZERO_NO_INITIALIZER/1.0"]
    cases: tuple[SdxlNativeGeometryCase, ...] = Field(min_length=1, max_length=2)
    negative_prompt_sha256: Sha256
    numerics: SdxlNativeGeometryNumerics
    budget: SdxlNativeGeometryBudget

    @model_validator(mode="after")
    def bounded_cases(self) -> Self:
        ids = tuple(case.sample_id for case in self.cases)
        if (
            ids != tuple(sorted(set(ids)))
            or self.budget.maximum_generations != 4 * len(ids)
            or self.evaluation.adapter_strength != 1.0
        ):
            raise ValueError("SDXL_NATIVE_GEOMETRY_CASE_OR_BUDGET_INVALID")
        return self


class LocalImageSdxlNativeGeometryCommandV2(LocalImageSdxlNativeGeometryCommand):
    schema_version: Literal["local-image-sdxl-lora-evaluation-command/1.4"]  # type: ignore[assignment]
    evaluation: SdxlNativeLoraEvaluationPinV2


class LocalImageSdxlNativeGeometryCommandV3(LocalImageSdxlNativeGeometryCommandV2):
    schema_version: Literal["local-image-sdxl-lora-evaluation-command/1.5"]  # type: ignore[assignment]
    evaluation: SdxlNativeLoraEvaluationPinV3


def validate_sdxl_native_geometry_sources(
    command: LocalImageSdxlNativeGeometryCommand, sources: SdxlNativeEvaluationSources
) -> None:
    from eom_image_contracts.models import text_sha256

    samples = {sample.sample_id: sample for sample in sources.training_command.training_samples}
    negatives = {case.negative_prompt_en for case in sources.baseline.cases}
    if len(negatives) != 1 or command.negative_prompt_sha256 != text_sha256(next(iter(negatives))):
        raise ValueError("SDXL_NATIVE_GEOMETRY_NEGATIVE_POLICY_MISMATCH")
    for case in command.cases:
        sample = samples.get(case.sample_id)
        if (
            sample is None
            or sample.canvas != case.native_canvas
            or sample.training_caption_sha256 != case.training_caption_sha256
        ):
            raise ValueError("SDXL_NATIVE_GEOMETRY_TRAIN_CASE_MISMATCH")


class SdxlNativeGeometryOutput(FrozenModel):
    sample_id: str = Field(pattern=r"^imgsourcecrop_[0-9a-f]{32}$")
    arm: GeometryArm
    canvas: GeometryCanvas
    width_px: int = Field(ge=512, le=1024)
    height_px: int = Field(ge=512, le=1024)
    prompt_sha256: Sha256
    negative_prompt_sha256: Sha256
    member_path: str
    sha256: Sha256
    size_bytes: int = Field(ge=1, le=16 * 1024**2)
    duration_ms: int = Field(ge=1, le=600_000)

    @model_validator(mode="after")
    def exact_raw_member(self) -> Self:
        if (
            (self.width_px, self.height_px) != geometry_dimensions(self.canvas)
            or self.member_path
            != f"outputs/raw/{self.sample_id}-{self.canvas.lower()}-{self.arm.lower()}.png"
        ):
            raise ValueError("SDXL_NATIVE_GEOMETRY_OUTPUT_IDENTITY_INVALID")
        return self


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("SDXL_NATIVE_GEOMETRY_TIMESTAMP_NOT_UTC")
    return value


class LocalImageSdxlNativeGeometryResult(FrozenModel):
    schema_version: Literal["local-image-sdxl-lora-evaluation-result/1.3"]
    run_id: str = Field(pattern=r"^imgsdxlloraevalrun_[0-9a-f]{32}$")
    command_sha256: Sha256
    evaluation: SdxlNativeLoraEvaluationPin
    baseline_command_sha256: Sha256
    model: SdxlLineartStackPointer
    case_relation: Literal["ADMITTED_NATIVE_TRAIN_GEOMETRY_DIAGNOSTIC_NOT_HOLDOUT"]
    conditioning_policy: Literal["SYNTHETIC_BLACK_T2I_ZERO_NO_INITIALIZER/1.0"]
    numerics: SdxlNativeGeometryNumerics
    status: Literal["SUCCEEDED", "FAILED"]
    error_code: SdxlProbeErrorCode | None
    runtime: LocalImageRuntime | None
    generation_calls: int = Field(ge=0, le=8)
    outputs: tuple[SdxlNativeGeometryOutput, ...] = Field(max_length=8)
    started_at: datetime
    completed_at: datetime
    duration_ms: int = Field(ge=1, le=3_600_000)
    result_sha256: Sha256

    _utc_time = field_validator("started_at", "completed_at")(_utc)

    @model_validator(mode="after")
    def closed_evidence(self) -> Self:
        keys = tuple((o.arm, o.sample_id, o.canvas) for o in self.outputs)
        if (
            len(set(keys)) != len(keys)
            or len({o.member_path for o in self.outputs}) != len(keys)
            or self.completed_at < self.started_at
            or (self.status == "SUCCEEDED") != (self.error_code is None)
            or (self.outputs and self.runtime is None)
            or self.generation_calls < len(self.outputs)
            or (self.status == "SUCCEEDED" and (not self.outputs or self.runtime is None))
            or self.result_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        ):
            raise ValueError("SDXL_NATIVE_GEOMETRY_RECEIPT_INVALID")
        return self


class LocalImageSdxlNativeGeometryResultV2(LocalImageSdxlNativeGeometryResult):
    schema_version: Literal["local-image-sdxl-lora-evaluation-result/1.4"]  # type: ignore[assignment]
    evaluation: SdxlNativeLoraEvaluationPinV2


class LocalImageSdxlNativeGeometryResultV3(LocalImageSdxlNativeGeometryResultV2):
    schema_version: Literal["local-image-sdxl-lora-evaluation-result/1.5"]  # type: ignore[assignment]
    evaluation: SdxlNativeLoraEvaluationPinV3


def validate_sdxl_native_geometry_result(
    command: LocalImageSdxlNativeGeometryCommand,
    sources: SdxlNativeEvaluationSources,
    result: LocalImageSdxlNativeGeometryResult,
) -> None:
    validate_sdxl_native_geometry_sources(command, sources)
    expected = tuple(
        (arm, case.sample_id, canvas)
        for arm in GEOMETRY_ARMS
        for case in command.cases
        for canvas in ("LEGACY_832X512", case.native_canvas)
    )
    actual = tuple((o.arm, o.sample_id, o.canvas) for o in result.outputs)
    captions = {c.sample_id: c.training_caption_sha256 for c in command.cases}
    if (
        result.schema_version != command.schema_version.replace("-command/", "-result/")
        or result.run_id != command.run_id
        or result.command_sha256 != command.command_sha256
        or result.evaluation != command.evaluation
        or result.model != sources.baseline.model
        or result.baseline_command_sha256 != sources.baseline.command_sha256
        or result.case_relation != command.case_relation
        or result.conditioning_policy != command.conditioning_policy
        or result.numerics != command.numerics
        or result.generation_calls > command.budget.maximum_generations
        or result.started_at < command.created_at
        or actual != expected[: len(actual)]
        or (result.status == "SUCCEEDED" and actual != expected)
        or (result.status == "SUCCEEDED" and result.generation_calls != len(expected))
        or any(
            o.prompt_sha256 != captions[o.sample_id]
            or o.negative_prompt_sha256 != command.negative_prompt_sha256
            for o in result.outputs
        )
        or (
            result.status == "SUCCEEDED"
            and (
                result.duration_ms > command.budget.maximum_duration_ms
                or result.runtime is None
                or result.runtime.peak_gpu_memory_bytes
                > command.budget.maximum_peak_gpu_memory_bytes
                or any(
                    getattr(result.runtime, name)
                    != getattr(sources.training_command.dependencies, name)
                    for name in (
                        "python_version",
                        "torch_version",
                        "diffusers_version",
                        "transformers_version",
                    )
                )
            )
        )
    ):
        raise ValueError("SDXL_NATIVE_GEOMETRY_RESULT_COMMAND_MISMATCH")
