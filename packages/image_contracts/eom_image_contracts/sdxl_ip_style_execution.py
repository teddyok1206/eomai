"""Closed matched OFF/ON wire family; no dispatch approval or numerical/source authority."""

from __future__ import annotations

import hashlib
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
from eom_image_contracts.sdxl_ip_style import SdxlIpStyleModelPointer
from eom_image_contracts.sdxl_ip_style_comparison import (
    LocalImageSdxlIpStyleComparisonPlan,
    SdxlIpStyleSelectedSource,
    parse_sdxl_ip_style_comparison_plan,
)
from eom_image_contracts.sdxl_lineart_probe import SdxlProbeErrorCode
from eom_image_contracts.sdxl_photo_style_result import (
    LocalImageSdxlPhotoStyleBalancedExposureResult,
    LocalImageSdxlPhotoStyleResult,
    parse_photo_style_result,
)
from eom_image_contracts.validation import validate_contract

SDXL_IP_STYLE_COMMAND_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-sdxl-ip-style-comparison-command/1.0"
)
SDXL_IP_STYLE_RESULT_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-sdxl-ip-style-comparison-result/1.0"
)
IpStyleArm = Literal["OFF", "ON"]
IP_STYLE_ARMS: tuple[IpStyleArm, ...] = ("OFF", "ON")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("SDXL_IP_STYLE_EXECUTION_TIMESTAMP_NOT_UTC")
    return value


class LocalImageSdxlIpStyleComparisonCommand(FrozenModel):
    schema_version: Literal["local-image-sdxl-ip-style-comparison-command/1.0"]
    run_id: str = Field(pattern=r"^imgsdxlipstylerun_[0-9a-f]{32}$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    created_at: datetime
    purpose: Literal["EVALUATION_ONLY_MATCHED_STYLE_REFERENCE"]
    activation_policy: Literal["FORBIDDEN"]
    plan: ImageEvaluationArtifactMember
    plan_id: str = Field(pattern=r"^imgsdxlipstyleplan_[0-9a-f]{32}$")
    plan_sha256: Sha256
    encoder_policy: Literal["CPU_FLOAT32_EAGER_GLOBAL_CFG/1.0"]
    maximum_peak_host_memory_bytes: int = Field(ge=1, le=64 * 1024**3, strict=True)
    command_sha256: Sha256

    _created_utc = field_validator("created_at")(_utc)

    @model_validator(mode="after")
    def exact_command(self) -> Self:
        if (
            self.plan.schema_ref
            != "eom://schemas/image-provider/local-image-sdxl-ip-style-comparison-plan/1.0"
            or self.plan.member_path != "manifests/sdxl-ip-style-comparison-plan.json"
            or self.plan.media_type != "application/json"
        ):
            raise ValueError("SDXL_IP_STYLE_EXECUTION_PLAN_POINTER_INVALID")
        if self.run_id != "imgsdxlipstylerun_" + content_sha256(
            self.model_dump(mode="json", exclude={"run_id", "command_sha256"})
        )[7:39] or self.command_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"command_sha256"})
        ):
            raise ValueError("SDXL_IP_STYLE_EXECUTION_COMMAND_ID_OR_HASH_INVALID")
        return self


def parse_sdxl_ip_style_execution_plan(
    command: LocalImageSdxlIpStyleComparisonCommand, raw: bytes
) -> LocalImageSdxlIpStyleComparisonPlan:
    validate_contract("sdxl-ip-style-comparison-command", command.model_dump(mode="json"))
    command = LocalImageSdxlIpStyleComparisonCommand.model_validate(command.model_dump(mode="json"))
    plan = parse_sdxl_ip_style_comparison_plan(command.plan, raw)
    if (
        plan.plan_id != command.plan_id
        or plan.plan_sha256 != command.plan_sha256
        or plan.created_at > command.created_at
    ):
        raise ValueError("SDXL_IP_STYLE_EXECUTION_PLAN_ID_HASH_OR_CHRONOLOGY_INVALID")
    return plan


def parse_sdxl_ip_style_command(value: object) -> LocalImageSdxlIpStyleComparisonCommand:
    if not isinstance(value, dict):
        raise ValueError("SDXL_IP_STYLE_EXECUTION_COMMAND_OBJECT_REQUIRED")
    validate_contract("sdxl-ip-style-comparison-command", value)
    return LocalImageSdxlIpStyleComparisonCommand.model_validate(value)


class SdxlIpStyleInputTrace(FrozenModel):
    case_id: str = Field(pattern=r"^imgsdxlcase_[0-9a-f]{32}$")
    style_sample_id: str = Field(pattern=r"^imgsourcecrop_[0-9a-f]{32}$")
    style_source_sha256: Sha256
    style_rgb_sha256: Sha256
    encoder_input_sha256: Sha256
    cfg_embedding_sha256: Sha256
    reference_sha256: Sha256
    conditioning_sha256: Sha256
    initialization_rgb_sha256: Sha256
    prompt_sha256: Sha256
    negative_prompt_sha256: Sha256
    seed: int = Field(ge=0, le=2**32 - 1, strict=True)


class SdxlIpStyleComparisonOutput(FrozenModel):
    arm: IpStyleArm
    case_id: str = Field(pattern=r"^imgsdxlcase_[0-9a-f]{32}$")
    seed: int = Field(ge=0, le=2**32 - 1, strict=True)
    cfg_embedding_sha256: Sha256
    initial_generator_state_sha256: Sha256
    prompt_sha256: Sha256
    negative_prompt_sha256: Sha256
    member_path: str = Field(
        pattern=r"^outputs/(?:off|on)/final/imgsdxlcase_[0-9a-f]{32}-[0-9]{10}\.png$"
    )
    sha256: Sha256
    size_bytes: int = Field(ge=1, le=16 * 1024**2, strict=True)
    raw_member_path: str = Field(
        pattern=r"^outputs/(?:off|on)/raw/imgsdxlcase_[0-9a-f]{32}-[0-9]{10}\.png$"
    )
    raw_sha256: Sha256
    raw_size_bytes: int = Field(ge=1, le=16 * 1024**2, strict=True)
    width_px: Literal[800]
    height_px: Literal[500]
    duration_ms: int = Field(ge=1, le=600_000, strict=True)
    peak_gpu_memory_bytes: int = Field(ge=1, le=16 * 1024**3, strict=True)

    @model_validator(mode="after")
    def exact_member_identity(self) -> Self:
        filename = f"{self.case_id}-{self.seed:010d}.png"
        if (
            self.member_path != f"outputs/{self.arm.lower()}/final/{filename}"
            or self.raw_member_path != f"outputs/{self.arm.lower()}/raw/{filename}"
        ):
            raise ValueError("SDXL_IP_STYLE_EXECUTION_OUTPUT_MEMBER_INVALID")
        return self


class LocalImageSdxlIpStyleComparisonResult(FrozenModel):
    schema_version: Literal["local-image-sdxl-ip-style-comparison-result/1.0"]
    run_id: str = Field(pattern=r"^imgsdxlipstylerun_[0-9a-f]{32}$")
    command_sha256: Sha256
    plan_sha256: Sha256
    photo_result_sha256: Sha256
    native_adapter_manifest_sha256: Sha256
    style_model: SdxlIpStyleModelPointer
    encoder_policy: Literal["CPU_FLOAT32_EAGER_GLOBAL_CFG/1.0"]
    routing_policy: Literal["UP_BLOCK0_ATTN1_ONLY/1.0"]
    quality_acceptance: Literal["NOT_REVIEWED"]
    activation_policy: Literal["FORBIDDEN"]
    holdout_binary_reads: Literal[0]
    training_steps: Literal[0]
    status: Literal["SUCCEEDED", "FAILED"]
    error_code: SdxlProbeErrorCode | None
    runtime: LocalImageRuntime | None
    peak_host_memory_bytes: int = Field(ge=1, le=2**63 - 1, strict=True)
    inputs: tuple[SdxlIpStyleInputTrace, ...] = Field(max_length=2)
    outputs: tuple[SdxlIpStyleComparisonOutput, ...] = Field(max_length=4)
    started_at: datetime
    completed_at: datetime
    duration_ms: int = Field(ge=1, le=3_600_000, strict=True)
    result_sha256: Sha256

    _timestamps_utc = field_validator("started_at", "completed_at")(_utc)

    @model_validator(mode="after")
    def exact_result(self) -> Self:
        ids = tuple(row.case_id for row in self.inputs)
        keys = tuple((row.case_id, row.arm) for row in self.outputs)
        if (
            ids != tuple(sorted(set(ids)))
            or keys != tuple(sorted(set(keys)))
            or self.completed_at < self.started_at
            or sum(row.duration_ms for row in self.outputs) > self.duration_ms
            or (self.status == "SUCCEEDED") != (self.error_code is None)
            or self.result_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        ):
            raise ValueError("SDXL_IP_STYLE_EXECUTION_RESULT_ORDER_STATUS_TIME_OR_HASH_INVALID")
        inputs = {row.case_id: row for row in self.inputs}
        style_values: dict[str, tuple[str, str, str, str]] = {}
        for row in self.inputs:
            value = (
                row.style_source_sha256,
                row.style_rgb_sha256,
                row.encoder_input_sha256,
                row.cfg_embedding_sha256,
            )
            if style_values.setdefault(row.style_sample_id, value) != value:
                raise ValueError("SDXL_IP_STYLE_EXECUTION_SHARED_STYLE_TRACE_CONFLICT")
        states: dict[str, str] = {}
        for output in self.outputs:
            input_row = inputs.get(output.case_id)
            if input_row is None or (
                output.seed,
                output.cfg_embedding_sha256,
                output.prompt_sha256,
                output.negative_prompt_sha256,
            ) != (
                input_row.seed,
                input_row.cfg_embedding_sha256,
                input_row.prompt_sha256,
                input_row.negative_prompt_sha256,
            ):
                raise ValueError("SDXL_IP_STYLE_EXECUTION_OUTPUT_INPUT_TRACE_MISMATCH")
            if (
                states.setdefault(output.case_id, output.initial_generator_state_sha256)
                != output.initial_generator_state_sha256
            ):
                raise ValueError("SDXL_IP_STYLE_EXECUTION_MATCHED_RNG_STATE_MISMATCH")
        if self.outputs and (
            len(self.inputs) != 2
            or self.runtime is None
            or self.runtime.peak_gpu_memory_bytes
            < max(row.peak_gpu_memory_bytes for row in self.outputs)
        ):
            raise ValueError("SDXL_IP_STYLE_EXECUTION_RUNTIME_OR_INPUT_CLOSURE_INVALID")
        if self.status == "SUCCEEDED" and (
            len(self.inputs) != 2 or len(self.outputs) != 4 or self.runtime is None
        ):
            raise ValueError("SDXL_IP_STYLE_EXECUTION_SUCCESS_CLOSURE_INVALID")
        return self


def parse_sdxl_ip_style_result(value: object) -> LocalImageSdxlIpStyleComparisonResult:
    if not isinstance(value, dict):
        raise ValueError("SDXL_IP_STYLE_EXECUTION_RESULT_OBJECT_REQUIRED")
    validate_contract("sdxl-ip-style-comparison-result", value)
    return LocalImageSdxlIpStyleComparisonResult.model_validate(value)


def validate_sdxl_ip_style_execution_result(
    command: LocalImageSdxlIpStyleComparisonCommand,
    plan: LocalImageSdxlIpStyleComparisonPlan,
    selected: tuple[SdxlIpStyleSelectedSource, ...],
    photo_result: LocalImageSdxlPhotoStyleResult,
    result: LocalImageSdxlIpStyleComparisonResult,
) -> None:
    """Canonical owners admit sources first; this proves metadata relations, not pixels/approval."""
    plan = parse_sdxl_ip_style_execution_plan(
        command, content_json_bytes(plan.model_dump(mode="json"))
    )
    photo_result = parse_photo_style_result(photo_result.model_dump(mode="json"))
    parent_raw_sha = (
        "sha256:"
        + hashlib.sha256(content_json_bytes(photo_result.model_dump(mode="json"))).hexdigest()
    )
    validate_contract("sdxl-ip-style-comparison-result", result.model_dump(mode="json"))
    result = LocalImageSdxlIpStyleComparisonResult.model_validate(result.model_dump(mode="json"))
    if (
        tuple(row.selection for row in selected) != plan.cases
        or not isinstance(photo_result, LocalImageSdxlPhotoStyleBalancedExposureResult)
        or photo_result.status != "SUCCEEDED"
        or parent_raw_sha != plan.photo_result.sha256
        or photo_result.completed_at > plan.created_at
        or result.run_id != command.run_id
        or result.command_sha256 != command.command_sha256
        or result.plan_sha256 != plan.plan_sha256
        or result.photo_result_sha256 != photo_result.result_sha256
        or result.native_adapter_manifest_sha256 != photo_result.native_adapter_manifest_sha256
        or result.style_model != plan.style_model
        or result.started_at < command.created_at
    ):
        raise ValueError("SDXL_IP_STYLE_EXECUTION_PARENT_IDENTITY_OR_TIME_MISMATCH")
    case_ids = tuple(row.case_id for row in plan.cases)
    if tuple(row.case_id for row in result.inputs) != case_ids[: len(result.inputs)]:
        raise ValueError("SDXL_IP_STYLE_EXECUTION_INPUT_PREFIX_INVALID")
    expected_outputs = tuple((case_id, arm) for case_id in case_ids for arm in IP_STYLE_ARMS)
    if (
        tuple((row.case_id, row.arm) for row in result.outputs)
        != expected_outputs[: len(result.outputs)]
    ):
        raise ValueError("SDXL_IP_STYLE_EXECUTION_OUTPUT_PREFIX_INVALID")
    parent_seeds = {row.case_id: row.seed for row in photo_result.outputs if row.arm == "LORA"}
    for row, source in zip(result.inputs, selected, strict=False):
        choice = source.selection
        if (
            row.style_sample_id != choice.style_sample_id
            or row.style_source_sha256 != source.style_sample.source_image.sha256
            or row.style_rgb_sha256 != choice.style_rgb_sha256
            or row.reference_sha256 != source.photo.case.reference_image.sha256
            or row.conditioning_sha256 != choice.conditioning_sha256
            or row.initialization_rgb_sha256 != choice.initialization_rgb_sha256
            or row.prompt_sha256 != source.photo.case.prompt_sha256
            or row.negative_prompt_sha256 != source.photo.case.negative_prompt_sha256
            or row.seed != parent_seeds.get(row.case_id)
        ):
            raise ValueError("SDXL_IP_STYLE_EXECUTION_INPUT_SOURCE_TRACE_MISMATCH")
    over_budget = (
        result.duration_ms > plan.budget.maximum_duration_ms
        or result.peak_host_memory_bytes > command.maximum_peak_host_memory_bytes
        or (
            result.runtime is not None
            and result.runtime.peak_gpu_memory_bytes > plan.budget.maximum_peak_gpu_memory_bytes
        )
    )
    # Resource breach cannot succeed; preserve the actual first failure (e.g. OOM),
    # rather than rewriting historical error identity to a budget error afterwards.
    if over_budget and result.status != "FAILED":
        raise ValueError("SDXL_IP_STYLE_EXECUTION_RESOURCE_BOUND_EXCEEDED")
