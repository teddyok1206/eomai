"""Pinned CPU edge preparation from admitted TRAIN targets, not model output."""

from __future__ import annotations

import hashlib
import json
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
from eom_image_contracts.sdxl_target_comparison import (
    LocalImageSdxlTargetComparisonCommand,
    SdxlTargetComparisonSources,
    validate_sdxl_target_comparison_sources,
)

PREFIX = "eom://schemas/image-provider/local-image-"
CannyErrorCode = Literal[
    "SDXL_CANNY_INPUT_INVALID",
    "SDXL_CANNY_RUNTIME_INVALID",
    "SDXL_CANNY_EDGE_INVALID",
    "SDXL_CANNY_EXEC_FAILED",
    "SDXL_CANNY_BUDGET_EXCEEDED",
]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("Canny timestamp must use UTC")
    return value


class SdxlCannyPolicy(FrozenModel):
    policy_version: Literal["FIT_800X500_CENTER_832X512_OPENCV_CANNY/1.0"] = (
        "FIT_800X500_CENTER_832X512_OPENCV_CANNY/1.0"
    )
    source_width_px: Literal[768] = 768
    source_height_px: Literal[512] = 512
    fit_width_px: Literal[800] = 800
    fit_height_px: Literal[500] = 500
    width_px: Literal[832] = 832
    height_px: Literal[512] = 512
    resampling: Literal["PILLOW_LANCZOS"] = "PILLOW_LANCZOS"
    threshold_low: Literal[100] = 100
    threshold_high: Literal[200] = 200
    aperture_size: Literal[3] = 3
    l2_gradient: Literal[False] = False
    polarity: Literal["WHITE_EDGES_ON_BLACK_RGB"] = "WHITE_EDGES_ON_BLACK_RGB"


class SdxlCannyRuntime(FrozenModel):
    opencv_package_version: Literal["4.11.0.86"] = "4.11.0.86"
    opencv_module_version: Literal["4.11.0"] = "4.11.0"
    expected_opencv_wheel_sha256: Literal[
        "sha256:0e0a27c19dd1f40ddff94976cfe43066fbbe9dfbb2ec1907d66c19caef42a57b"
    ] = "sha256:0e0a27c19dd1f40ddff94976cfe43066fbbe9dfbb2ec1907d66c19caef42a57b"
    pillow_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$", max_length=32)
    numpy_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$", max_length=32)


class SdxlCannyBudget(FrozenModel):
    maximum_outputs: Literal[3] = 3
    maximum_input_png_bytes: Literal[16_777_216] = 16_777_216
    maximum_duration_ms: int = Field(ge=1000, le=60_000)


class LocalImageSdxlCannyConditioningCommand(FrozenModel):
    schema_version: Literal["local-image-sdxl-canny-conditioning-command/1.0"]
    run_id: str = Field(pattern=r"^imgsdxlcannyrun_[0-9a-f]{32}$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    created_at: datetime
    purpose: Literal["EVALUATION_ONLY_CANNY_INPUT_PREPARATION"]
    activation_policy: Literal["FORBIDDEN"]
    case_relation: Literal["REVIEWED_TRAIN_TARGET_NOT_HOLDOUT"]
    source_command: ImageEvaluationArtifactMember
    policy: SdxlCannyPolicy
    policy_sha256: Sha256
    runtime: SdxlCannyRuntime
    budget: SdxlCannyBudget
    command_sha256: Sha256

    _created_utc = field_validator("created_at")(_utc)

    @model_validator(mode="after")
    def exact_command(self) -> Self:
        pin = self.source_command
        if (
            pin.schema_ref != PREFIX + "sdxl-target-comparison-command/1.0"
            or pin.member_path != "manifests/sdxl-target-comparison-command.json"
            or pin.media_type != "application/json"
        ):
            raise ValueError("Canny preparation requires a pinned target-comparison command")
        if self.policy_sha256 != content_sha256(self.policy.model_dump(mode="json")):
            raise ValueError("Canny recipe hash mismatch")
        if self.run_id != "imgsdxlcannyrun_" + content_sha256(
            self.model_dump(mode="json", exclude={"run_id", "command_sha256"})
        )[7:39] or self.command_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"command_sha256"})
        ):
            raise ValueError("Canny command identity/hash mismatch")
        return self


def parse_sdxl_canny_parent(
    command: LocalImageSdxlCannyConditioningCommand, raw: bytes
) -> LocalImageSdxlTargetComparisonCommand:
    from eom_image_contracts.validation import validate_contract

    if not 0 < len(raw) <= 256 * 1024 or (
        "sha256:" + hashlib.sha256(raw).hexdigest() != command.source_command.sha256
    ):
        raise ValueError("Canny parent metadata bound/hash mismatch")
    validate_contract("sdxl-target-comparison-command", json.loads(raw))
    parent = LocalImageSdxlTargetComparisonCommand.model_validate_json(raw)
    if raw != content_json_bytes(parent.model_dump(mode="json")):
        raise ValueError("Canny parent metadata is noncanonical")
    if command.created_at < parent.created_at:
        raise ValueError("Canny preparation predates its pinned source")
    return parent


def validate_sdxl_canny_sources(
    command: LocalImageSdxlCannyConditioningCommand,
    parent: LocalImageSdxlTargetComparisonCommand,
    sources: SdxlTargetComparisonSources,
) -> None:
    parse_sdxl_canny_parent(command, content_json_bytes(parent.model_dump(mode="json")))
    validate_sdxl_target_comparison_sources(parent, sources)
    if len(parent.cases) > command.budget.maximum_outputs:
        raise ValueError("Canny preparation exceeds its source/output budget")


class SdxlCannyOutput(FrozenModel):
    case_id: str = Field(pattern=r"^imgsdxlcase_[0-9a-f]{32}$")
    source: ImageEvaluationArtifactMember
    member_path: str = Field(pattern=r"^outputs/conditioning/imgsdxlcase_[0-9a-f]{32}\.png$")
    sha256: Sha256
    size_bytes: int = Field(ge=1, le=16_777_216)
    width_px: Literal[832] = 832
    height_px: Literal[512] = 512
    mode: Literal["RGB"] = "RGB"
    pixel_tones: tuple[Literal[0], Literal[255]] = (0, 255)
    edge_pixels: int = Field(ge=1, lt=832 * 512)

    @model_validator(mode="after")
    def exact_member(self) -> Self:
        if self.member_path != "outputs/conditioning/" + self.case_id + ".png":
            raise ValueError("Canny output path/case mismatch")
        return self


class LocalImageSdxlCannyConditioningResult(FrozenModel):
    schema_version: Literal["local-image-sdxl-canny-conditioning-result/1.0"]
    run_id: str = Field(pattern=r"^imgsdxlcannyrun_[0-9a-f]{32}$")
    command_sha256: Sha256
    parent_command_content_sha256: Sha256
    policy_sha256: Sha256
    status: Literal["SUCCEEDED", "FAILED"]
    error_code: CannyErrorCode | None
    case_relation: Literal["REVIEWED_TRAIN_TARGET_NOT_HOLDOUT"]
    preparation_state: Literal["UNREVIEWED_CANNY_INPUTS"]
    activation_policy: Literal["FORBIDDEN"]
    model_executions: Literal[0] = 0
    training_steps: Literal[0] = 0
    runtime: SdxlCannyRuntime
    outputs: tuple[SdxlCannyOutput, ...] = Field(max_length=3)
    started_at: datetime
    completed_at: datetime
    duration_ms: int = Field(ge=1, le=120_000)
    result_sha256: Sha256

    _timestamps_utc = field_validator("started_at", "completed_at")(_utc)

    @model_validator(mode="after")
    def exact_result(self) -> Self:
        ids = tuple(output.case_id for output in self.outputs)
        if ids != tuple(sorted(set(ids))):
            raise ValueError("Canny output cases are unordered or duplicate")
        if (self.status == "SUCCEEDED") != (self.error_code is None):
            raise ValueError("Canny result status/error mismatch")
        if self.completed_at < self.started_at or self.result_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"result_sha256"})
        ):
            raise ValueError("Canny result timestamp/hash mismatch")
        return self


def validate_sdxl_canny_result(
    command: LocalImageSdxlCannyConditioningCommand,
    parent: LocalImageSdxlTargetComparisonCommand,
    sources: SdxlTargetComparisonSources,
    result: LocalImageSdxlCannyConditioningResult,
) -> None:
    validate_sdxl_canny_sources(command, parent, sources)
    if (
        result.run_id != command.run_id
        or result.command_sha256 != command.command_sha256
        or result.parent_command_content_sha256 != parent.command_sha256
        or result.policy_sha256 != command.policy_sha256
        or result.runtime != command.runtime
        or result.started_at < command.created_at
        or len(result.outputs) > len(parent.cases)
    ):
        raise ValueError("Canny result differs from pinned command/source/runtime")
    for output, entry in zip(result.outputs, parent.cases, strict=False):
        if output.case_id != entry.case.case_id or output.source != entry.case.reference_image:
            raise ValueError("Canny output is not the ordered admitted source prefix")
    if result.status == "SUCCEEDED" and (
        len(result.outputs) != len(parent.cases)
        or result.duration_ms > command.budget.maximum_duration_ms
    ):
        raise ValueError("Canny success is incomplete or over budget")
