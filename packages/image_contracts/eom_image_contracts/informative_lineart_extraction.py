"""Pure, bounded learned preprocessing receipts that preserve original SDXL case identity."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.informative_lineart import (
    INFORMATIVE_LINEART_MANIFEST_SCHEMA_REF,
    InformativeLineartPointer,
)
from eom_image_contracts.models import (
    FrozenModel,
    ImageEvaluationArtifactMember,
    Sha256,
    content_sha256,
)
from eom_image_contracts.sdxl_lineart_probe import (
    LocalImageSdxlLineartProbeCommand,
    SdxlLineartProbeCase,
)

INFORMATIVE_EXTRACTION_COMMAND_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-informative-lineart-extraction-command/1.0"
)
INFORMATIVE_EXTRACTION_RESULT_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-informative-lineart-extraction-result/1.0"
)
ExtractionCaseId = Annotated[str, Field(pattern=r"^imgsdxlcase_[0-9a-f]{32}$")]
ExtractionErrorCode = Literal[
    "LINEART_EXTRACTION_INPUT_INVALID",
    "LINEART_EXTRACTION_MODEL_INVALID",
    "LINEART_EXTRACTION_HASH_MISMATCH",
    "LINEART_EXTRACTION_GPU_UNAVAILABLE",
    "LINEART_EXTRACTION_OOM",
    "LINEART_EXTRACTION_EXEC_FAILED",
    "LINEART_EXTRACTION_OUTPUT_INVALID",
    "LINEART_EXTRACTION_BUDGET_EXCEEDED",
]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("lineart extraction timestamp must use UTC")
    return value


class InformativeLineartExtractionBudget(FrozenModel):
    maximum_duration_ms: int = Field(ge=1, le=600_000)
    maximum_peak_gpu_memory_bytes: int = Field(ge=1, le=16 * 1024**3)


class LocalImageInformativeLineartExtractionCommand(FrozenModel):
    schema_version: Literal["local-image-informative-lineart-extraction-command/1.0"]
    run_id: str = Field(pattern=r"^imglineartextractrun_[0-9a-f]{32}$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    created_at: datetime
    purpose: Literal["EVALUATION_ONLY_LEARNED_LINEART_PREPROCESSING"]
    activation_policy: Literal["FORBIDDEN"]
    extractor: InformativeLineartPointer
    extractor_manifest: ImageEvaluationArtifactMember
    baseline_command: ImageEvaluationArtifactMember
    case_ids: tuple[ExtractionCaseId, ...] = Field(min_length=1, max_length=6)
    preprocessing_policy: Literal["FIT_RGB_EXTRACT_INVERT_832X512/1.0"]
    budget: InformativeLineartExtractionBudget
    command_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_created(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def exact_command(self) -> Self:
        expected = (
            (self.extractor_manifest, INFORMATIVE_LINEART_MANIFEST_SCHEMA_REF),
            (
                self.baseline_command,
                "eom://schemas/image-provider/local-image-sdxl-lineart-probe-command/1.0",
            ),
        )
        if any(
            pointer.schema_ref != schema or pointer.media_type != "application/json"
            for pointer, schema in expected
        ):
            raise ValueError("lineart extraction source contract mismatch")
        if self.case_ids != tuple(sorted(set(self.case_ids))):
            raise ValueError("lineart extraction case IDs must be uniquely sorted")
        value = self.model_dump(mode="json", exclude={"run_id", "command_sha256"})
        if self.run_id != "imglineartextractrun_" + content_sha256(value)[7:39]:
            raise ValueError("lineart extraction run identity mismatch")
        if self.command_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"command_sha256"})
        ):
            raise ValueError("lineart extraction command hash mismatch")
        return self


class InformativeLineartExtractionRuntime(FrozenModel):
    provider_version: Literal["eom-informative-lineart-extractor/1.0"]
    torch_version: Literal["2.7.1+cu128"]
    safetensors_version: Literal["0.6.2"]
    pillow_version: Literal["11.3.0"]
    cuda_version: Literal["12.8"]
    compute_capability: Literal["12.0"]
    dtype: Literal["float32"]
    gpu_name: str = Field(min_length=1, max_length=128)


class InformativeLineartExtractionOutput(FrozenModel):
    case_id: ExtractionCaseId
    reference_sha256: Sha256
    lineart_member_path: str = Field(pattern=r"^outputs/lineart/imgsdxlcase_[0-9a-f]{32}\.png$")
    lineart_sha256: Sha256
    lineart_size_bytes: int = Field(ge=1, le=16 * 1024**2)
    conditioning_member_path: str = Field(
        pattern=r"^outputs/conditioning/imgsdxlcase_[0-9a-f]{32}\.png$"
    )
    conditioning_sha256: Sha256
    conditioning_size_bytes: int = Field(ge=1, le=16 * 1024**2)
    width_px: Literal[832]
    height_px: Literal[512]
    lineart_mode: Literal["L"]
    conditioning_mode: Literal["RGB"]
    duration_ms: int = Field(ge=1, le=600_000)
    peak_gpu_memory_bytes: int = Field(ge=1, le=16 * 1024**3)

    @model_validator(mode="after")
    def exact_output_paths(self) -> Self:
        if (
            self.lineart_member_path != f"outputs/lineart/{self.case_id}.png"
            or self.conditioning_member_path != f"outputs/conditioning/{self.case_id}.png"
        ):
            raise ValueError("lineart extraction output path/case mismatch")
        return self


class LocalImageInformativeLineartExtractionResult(FrozenModel):
    schema_version: Literal["local-image-informative-lineart-extraction-result/1.0"]
    run_id: str = Field(pattern=r"^imglineartextractrun_[0-9a-f]{32}$")
    command_sha256: Sha256
    extractor: InformativeLineartPointer
    preprocessing_policy: Literal["FIT_RGB_EXTRACT_INVERT_832X512/1.0"]
    status: Literal["SUCCEEDED", "FAILED"]
    error_code: ExtractionErrorCode | None
    runtime: InformativeLineartExtractionRuntime | None
    outputs: tuple[InformativeLineartExtractionOutput, ...] = Field(max_length=6)
    started_at: datetime
    completed_at: datetime
    duration_ms: int = Field(ge=1, le=1_200_000)
    peak_gpu_memory_bytes: int = Field(ge=0, le=16 * 1024**3)
    result_sha256: Sha256

    @field_validator("started_at", "completed_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def exact_result(self) -> Self:
        if self.completed_at < self.started_at:
            raise ValueError("lineart extraction completion precedes start")
        if (self.status == "SUCCEEDED") != (self.error_code is None):
            raise ValueError("lineart extraction status/error mismatch")
        ids = tuple(output.case_id for output in self.outputs)
        if ids != tuple(sorted(set(ids))):
            raise ValueError("lineart extraction outputs must be uniquely sorted")
        if self.status == "SUCCEEDED" and (not self.outputs or self.runtime is None):
            raise ValueError("lineart extraction success lacks outputs/runtime")
        if self.runtime is None and (self.outputs or self.peak_gpu_memory_bytes != 0):
            raise ValueError("lineart extraction evidence lacks runtime")
        if self.outputs and self.peak_gpu_memory_bytes < max(
            output.peak_gpu_memory_bytes for output in self.outputs
        ):
            raise ValueError("lineart extraction global peak omits output memory")
        if self.result_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"result_sha256"})
        ):
            raise ValueError("lineart extraction result hash mismatch")
        return self


def select_informative_lineart_cases(
    command: LocalImageInformativeLineartExtractionCommand,
    baseline: LocalImageSdxlLineartProbeCommand,
) -> tuple[SdxlLineartProbeCase, ...]:
    """Original case identity is admitted by exact lookup, not reconstructed from derived pixels."""
    by_id = {case.case_id: case for case in baseline.cases}
    if not set(command.case_ids) <= set(by_id) or command.created_at < baseline.created_at:
        raise ValueError("lineart extraction selection/baseline mismatch")
    return tuple(by_id[case_id] for case_id in command.case_ids)


def validate_informative_lineart_extraction_result(
    command: LocalImageInformativeLineartExtractionCommand,
    baseline: LocalImageSdxlLineartProbeCommand,
    result: LocalImageInformativeLineartExtractionResult,
) -> None:
    cases = select_informative_lineart_cases(command, baseline)
    if (
        result.run_id != command.run_id
        or result.command_sha256 != command.command_sha256
        or result.extractor != command.extractor
        or result.preprocessing_policy != command.preprocessing_policy
    ):
        raise ValueError("lineart extraction result differs from command")
    observed = tuple(output.case_id for output in result.outputs)
    expected = tuple(case.case_id for case in cases)
    if result.status == "SUCCEEDED":
        if (
            observed != expected
            or result.duration_ms > command.budget.maximum_duration_ms
            or result.peak_gpu_memory_bytes > command.budget.maximum_peak_gpu_memory_bytes
        ):
            raise ValueError("lineart extraction success coverage/budget mismatch")
    elif observed != expected[: len(observed)]:
        raise ValueError("lineart extraction failed output is not an execution prefix")
    references = {case.case_id: case.reference_image.sha256 for case in cases}
    if any(output.reference_sha256 != references[output.case_id] for output in result.outputs):
        raise ValueError("lineart extraction original reference hash mismatch")
