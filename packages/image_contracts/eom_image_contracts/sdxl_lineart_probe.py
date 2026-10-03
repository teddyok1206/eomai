"""Bounded immutable inputs and measured outputs for a base SDXL lineart diagnostic."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.institutional_style_evaluation import InstitutionalStyleTrack
from eom_image_contracts.models import (
    FrozenModel,
    ImageEvaluationArtifactMember,
    LocalImageRuntime,
    Sha256,
    content_sha256,
    text_sha256,
)

SdxlProbeErrorCode = Literal[
    "SDXL_PROBE_INPUT_INVALID",
    "SDXL_PROBE_MODEL_INVALID",
    "SDXL_PROBE_HASH_MISMATCH",
    "SDXL_PROBE_GPU_UNAVAILABLE",
    "SDXL_PROBE_OOM",
    "SDXL_PROBE_EXEC_FAILED",
    "SDXL_PROBE_OUTPUT_INVALID",
    "SDXL_PROBE_BUDGET_EXCEEDED",
    "SDXL_PROBE_PROMPT_TRUNCATED",
]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("SDXL probe timestamp must use UTC")
    return value


class SdxlLineartStackPointer(FrozenModel):
    model_id: str = Field(pattern=r"^imgmodel_[0-9a-f]{32}$")
    model_revision_id: str = Field(pattern=r"^imgmodelrev_[0-9a-f]{32}$")
    manifest_sha256: Sha256
    provider_family: Literal["diffusers-sdxl-t2i-lineart"]
    runtime_contract_version: Literal["eom-local-image-sdxl-lineart-runner/1.0"]


class SdxlLineartProbeCase(FrozenModel):
    case_id: str = Field(pattern=r"^imgsdxlcase_[0-9a-f]{32}$")
    depiction_key: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    reference_image: ImageEvaluationArtifactMember
    reference_width_px: int = Field(ge=1, le=4096)
    reference_height_px: int = Field(ge=1, le=4096)
    staged_member_path: str = Field(pattern=r"^inputs/imgsdxlcase_[0-9a-f]{32}\.png$")
    prompt_en: str = Field(min_length=10, max_length=1200, pattern=r"^[ -~]+$")
    prompt_sha256: Sha256
    negative_prompt_en: str = Field(min_length=10, max_length=1200, pattern=r"^[ -~]+$")
    negative_prompt_sha256: Sha256
    seeds: tuple[int, ...] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def exact_input(self) -> Self:
        if self.reference_image.media_type != "image/png":
            raise ValueError("SDXL probe reference must be PNG")
        for prompt, sha in (
            (self.prompt_en, self.prompt_sha256),
            (self.negative_prompt_en, self.negative_prompt_sha256),
        ):
            if prompt != prompt.strip() or text_sha256(prompt) != sha:
                raise ValueError("SDXL probe prompt identity mismatch")
        if self.seeds != tuple(sorted(set(self.seeds))) or any(
            not 0 <= seed < 2**32 for seed in self.seeds
        ):
            raise ValueError("SDXL probe seeds must be sorted unique uint32 values")
        identity = content_sha256(
            self.model_dump(mode="json", exclude={"case_id", "staged_member_path"})
        )[7:39]
        if (
            self.case_id != "imgsdxlcase_" + identity
            or self.staged_member_path != f"inputs/{self.case_id}.png"
        ):
            raise ValueError("SDXL probe case identity/member mismatch")
        return self


class SdxlLineartProbeBudget(FrozenModel):
    maximum_duration_ms: int = Field(ge=1, le=1_800_000)
    maximum_peak_gpu_memory_bytes: int = Field(ge=1, le=16 * 1024**3)


class SdxlPromptSourcePin(FrozenModel):
    role: Literal["AUTHORING_GUIDANCE", "EDITOR_HANDOFF", "ILLUSTRATION_GUIDANCE"]
    source_name: str = Field(min_length=1, max_length=240, pattern=r"^[A-Za-z0-9._/-]+$")
    sha256: Sha256


class SdxlExperimentAuthorization(FrozenModel):
    """Pinned operator approval; original SSD-1B permission is not silently widened."""

    approved_at: datetime
    approved_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    approval_message_sha256: Sha256
    permitted_uses: tuple[
        Literal["INTERNAL_SDXL_COMPARISON", "INTERNAL_SDXL_LORA_TRAINING"], ...
    ] = Field(min_length=1, max_length=2)
    external_export: Literal["FORBIDDEN"]
    automatic_activation: Literal["FORBIDDEN"]

    @field_validator("approved_at")
    @classmethod
    def utc_approval(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def exact_scope(self) -> Self:
        if self.permitted_uses != tuple(sorted(set(self.permitted_uses))):
            raise ValueError("SDXL approved uses must be sorted and unique")
        if "INTERNAL_SDXL_COMPARISON" not in self.permitted_uses:
            raise ValueError("SDXL diagnostic requires explicit internal comparison approval")
        return self


class LocalImageSdxlLineartPromptPolicy(FrozenModel):
    """Small compiled provenance, not a new production prompt or mutable registry."""

    schema_version: Literal["local-image-sdxl-lineart-prompt-policy/1.0"]
    crop_set: ImageEvaluationArtifactMember
    training_authorization: ImageEvaluationArtifactMember
    experiment_authorization: SdxlExperimentAuthorization
    experiment_partition: Literal["TRAIN"]
    catalog_policy_revision: Literal[
        "local-gpu-image-prompt-policy/1.7",
        "local-gpu-image-prompt-policy/1.8.1",
        "local-gpu-image-prompt-policy/1.9.1",
    ]
    sources: tuple[SdxlPromptSourcePin, ...] = Field(min_length=3, max_length=3)
    cases: tuple[SdxlLineartProbeCase, ...] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def exact_provenance(self) -> Self:
        if tuple(source.role for source in self.sources) != (
            "AUTHORING_GUIDANCE",
            "EDITOR_HANDOFF",
            "ILLUSTRATION_GUIDANCE",
        ):
            raise ValueError("SDXL prompt sources must be complete, unique and ordered")
        ids = tuple(case.case_id for case in self.cases)
        if ids != tuple(sorted(set(ids))):
            raise ValueError("SDXL prompt cases must be uniquely sorted")
        if (
            self.crop_set.media_type != "application/json"
            or self.training_authorization.media_type != "application/json"
        ):
            raise ValueError("SDXL prompt authorization and crop manifest must be JSON")
        return self


class LocalImageSdxlLineartProbeCommand(FrozenModel):
    schema_version: Literal["local-image-sdxl-lineart-probe-command/1.0"]
    run_id: str = Field(pattern=r"^imgsdxlproberun_[0-9a-f]{32}$")
    created_at: datetime
    model: SdxlLineartStackPointer
    prompt_policy: ImageEvaluationArtifactMember
    style_track: InstitutionalStyleTrack
    conditioning_policy: Literal["FIT_GRAYSCALE_INVERT_832X512/1.0"]
    inference_steps: int = Field(ge=1, le=50)
    guidance_scale: float = Field(ge=0, le=12)
    adapter_conditioning_scale: float = Field(ge=0, le=1.5)
    budget: SdxlLineartProbeBudget
    cases: tuple[SdxlLineartProbeCase, ...] = Field(min_length=1, max_length=6)
    command_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_created(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def exact_command(self) -> Self:
        if self.prompt_policy.media_type != "application/json" or self.prompt_policy.schema_ref != (
            "eom://schemas/image-provider/local-image-sdxl-lineart-prompt-policy/1.0"
        ):
            raise ValueError("SDXL probe prompt provenance must be JSON")
        case_ids = tuple(case.case_id for case in self.cases)
        if case_ids != tuple(sorted(set(case_ids))):
            raise ValueError("SDXL probe cases must be uniquely sorted")
        if self.command_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"command_sha256"})
        ):
            raise ValueError("SDXL probe command hash mismatch")
        return self


class SdxlLineartProbeConditioning(FrozenModel):
    case_id: str = Field(pattern=r"^imgsdxlcase_[0-9a-f]{32}$")
    member_path: str = Field(pattern=r"^outputs/conditioning/imgsdxlcase_[0-9a-f]{32}\.png$")
    sha256: Sha256
    width_px: Literal[832]
    height_px: Literal[512]

    @model_validator(mode="after")
    def exact_member(self) -> Self:
        if self.member_path != f"outputs/conditioning/{self.case_id}.png":
            raise ValueError("SDXL conditioning member differs from case")
        return self


class SdxlLineartProbeOutput(FrozenModel):
    case_id: str = Field(pattern=r"^imgsdxlcase_[0-9a-f]{32}$")
    seed: int = Field(ge=0, le=2**32 - 1)
    member_path: str = Field(pattern=r"^outputs/final/imgsdxlcase_[0-9a-f]{32}-[0-9]{10}\.png$")
    sha256: Sha256
    raw_member_path: str = Field(pattern=r"^outputs/raw/imgsdxlcase_[0-9a-f]{32}-[0-9]{10}\.png$")
    raw_sha256: Sha256
    width_px: Literal[800]
    height_px: Literal[500]
    duration_ms: int = Field(ge=1, le=3_600_000)
    peak_gpu_memory_bytes: int = Field(ge=1, le=16 * 1024**3)

    @model_validator(mode="after")
    def exact_member(self) -> Self:
        name = f"{self.case_id}-{self.seed:010d}.png"
        if (
            self.member_path != "outputs/final/" + name
            or self.raw_member_path != "outputs/raw/" + name
        ):
            raise ValueError("SDXL output member differs from case/seed")
        return self


class LocalImageSdxlLineartProbeResult(FrozenModel):
    schema_version: Literal["local-image-sdxl-lineart-probe-result/1.0"]
    run_id: str = Field(pattern=r"^imgsdxlproberun_[0-9a-f]{32}$")
    command_sha256: Sha256
    model: SdxlLineartStackPointer
    status: Literal["SUCCEEDED", "FAILED"]
    error_code: SdxlProbeErrorCode | None
    runtime: LocalImageRuntime | None
    conditionings: tuple[SdxlLineartProbeConditioning, ...] = Field(max_length=6)
    outputs: tuple[SdxlLineartProbeOutput, ...] = Field(max_length=12)
    started_at: datetime
    completed_at: datetime
    duration_ms: int = Field(ge=1, le=3_600_000)
    result_sha256: Sha256

    @field_validator("started_at", "completed_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def exact_result(self) -> Self:
        validate_sdxl_probe_evidence(
            status=self.status,
            error_code=self.error_code,
            runtime=self.runtime,
            conditionings=self.conditionings,
            outputs=self.outputs,
            started_at=self.started_at,
            completed_at=self.completed_at,
        )
        if self.result_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"result_sha256"})
        ):
            raise ValueError("SDXL probe result hash mismatch")
        return self


def validate_sdxl_probe_evidence(
    *,
    status: str,
    error_code: str | None,
    runtime: LocalImageRuntime | None,
    conditionings: tuple[SdxlLineartProbeConditioning, ...],
    outputs: tuple[SdxlLineartProbeOutput, ...],
    started_at: datetime,
    completed_at: datetime,
) -> None:
    """Shared evidence invariant; no command identity is reinterpreted across families."""
    if completed_at < started_at:
        raise ValueError("SDXL probe completion precedes start")
    if (status == "SUCCEEDED") != (error_code is None):
        raise ValueError("SDXL probe status/error mismatch")
    if status == "SUCCEEDED" and (runtime is None or not outputs):
        raise ValueError("SDXL probe success lacks runtime/outputs")
    keys = tuple((output.case_id, output.seed) for output in outputs)
    if keys != tuple(sorted(set(keys))):
        raise ValueError("SDXL probe output keys must be uniquely sorted")
    conditioning_ids = tuple(value.case_id for value in conditionings)
    if conditioning_ids != tuple(sorted(set(conditioning_ids))):
        raise ValueError("SDXL probe conditioning cases must be uniquely sorted")
    if not {key[0] for key in keys} <= set(conditioning_ids):
        raise ValueError("SDXL probe output lacks conditioning")
    if outputs and (
        runtime is None
        or runtime.peak_gpu_memory_bytes != max(output.peak_gpu_memory_bytes for output in outputs)
    ):
        raise ValueError("SDXL probe runtime peak differs from measured outputs")


def validate_sdxl_lineart_probe_result(
    command: LocalImageSdxlLineartProbeCommand,
    result: LocalImageSdxlLineartProbeResult,
) -> None:
    if (
        result.run_id != command.run_id
        or result.command_sha256 != command.command_sha256
        or result.model != command.model
    ):
        raise ValueError("SDXL probe result differs from pinned command")
    validate_sdxl_probe_coverage(
        command,
        status=result.status,
        conditionings=result.conditionings,
        outputs=result.outputs,
        duration_ms=result.duration_ms,
    )


def validate_sdxl_probe_coverage(
    command: LocalImageSdxlLineartProbeCommand,
    *,
    status: str,
    conditionings: tuple[SdxlLineartProbeConditioning, ...],
    outputs: tuple[SdxlLineartProbeOutput, ...],
    duration_ms: int,
) -> None:
    expected = tuple((case.case_id, seed) for case in command.cases for seed in case.seeds)
    observed = tuple((output.case_id, output.seed) for output in outputs)
    expected_cases = tuple(case.case_id for case in command.cases)
    observed_cases = tuple(value.case_id for value in conditionings)
    if status == "SUCCEEDED":
        if observed != expected or observed_cases != expected_cases:
            raise ValueError("SDXL probe success coverage differs from command")
        if duration_ms > command.budget.maximum_duration_ms or any(
            output.peak_gpu_memory_bytes > command.budget.maximum_peak_gpu_memory_bytes
            for output in outputs
        ):
            raise ValueError("SDXL probe success exceeded frozen budget")
    elif (
        observed != expected[: len(observed)]
        or observed_cases != expected_cases[: len(observed_cases)]
    ):
        raise ValueError("SDXL probe partial failure is not an execution prefix")
