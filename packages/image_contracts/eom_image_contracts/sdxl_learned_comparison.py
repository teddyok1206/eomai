"""Fixed BASE/LORA pair using separately identified learned conditioning, never fake crops."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Self, cast

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.informative_lineart_extraction import (
    ExtractionCaseId,
    LocalImageInformativeLineartExtractionCommand,
    LocalImageInformativeLineartExtractionResult,
    validate_informative_lineart_extraction_result,
)
from eom_image_contracts.models import (
    FrozenModel,
    ImageEvaluationArtifactMember,
    LocalImageRuntime,
    Sha256,
    content_json_bytes,
    content_sha256,
)
from eom_image_contracts.sdxl_lineart_probe import (
    LocalImageSdxlLineartProbeCommand,
    SdxlLineartProbeCase,
    SdxlLineartStackPointer,
    SdxlProbeErrorCode,
)
from eom_image_contracts.sdxl_lora_evaluation import (
    LocalImageSdxlLoraEvaluationCommand,
    SdxlLoraEvaluationSources,
    parse_sdxl_lora_evaluation_sources,
    validate_sdxl_lora_evaluation_sources,
)

SDXL_LEARNED_COMMAND_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-sdxl-learned-comparison-command/1.0"
)
SDXL_LEARNED_RESULT_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-sdxl-learned-comparison-result/1.0"
)
LearnedComparisonArm = Literal["BASE", "LORA"]
LEARNED_COMPARISON_ARMS: tuple[LearnedComparisonArm, ...] = ("BASE", "LORA")


def validate_inference_arms(arms: tuple[LearnedComparisonArm, ...]) -> None:
    """Internal closed dispatch choices; released pair contracts remain fixed pairs."""
    if type(arms) is not tuple or arms not in (LEARNED_COMPARISON_ARMS, ("LORA",)):
        raise ValueError("SDXL_COMPARISON_ARM_SELECTION_INVALID")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("learned comparison timestamp must use UTC")
    return value


class SdxlLearnedComparisonBudget(FrozenModel):
    maximum_duration_ms: int = Field(ge=1, le=1_800_000)
    maximum_peak_gpu_memory_bytes: int = Field(ge=1, le=16 * 1024**3)


class LocalImageSdxlLearnedComparisonCommand(FrozenModel):
    schema_version: Literal["local-image-sdxl-learned-comparison-command/1.0"]
    run_id: str = Field(pattern=r"^imgsdxllearnedrun_[0-9a-f]{32}$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    created_at: datetime
    purpose: Literal["EVALUATION_ONLY_MATCHED_LEARNED_CONDITIONING"]
    activation_policy: Literal["FORBIDDEN"]
    baseline_command: ImageEvaluationArtifactMember
    extraction_command: ImageEvaluationArtifactMember
    extraction_result: ImageEvaluationArtifactMember
    lora_evaluation_command: ImageEvaluationArtifactMember
    conditioning_policy: Literal["PINNED_LEARNED_FINE_INVERTED/1.0"]
    case_ids: tuple[ExtractionCaseId, ...] = Field(min_length=1, max_length=3)
    seed: int = Field(ge=0, le=2**32 - 1)
    budget: SdxlLearnedComparisonBudget
    command_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_created(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def exact_command(self) -> Self:
        for pointer, family in (
            (self.baseline_command, "sdxl-lineart-probe-command"),
            (self.extraction_command, "informative-lineart-extraction-command"),
            (self.extraction_result, "informative-lineart-extraction-result"),
            (self.lora_evaluation_command, "sdxl-lora-evaluation-command"),
        ):
            if (
                pointer.media_type != "application/json"
                or pointer.schema_ref
                != "eom://schemas/image-provider/local-image-" + family + "/1.0"
                or pointer.member_path != "manifests/" + family + ".json"
            ):
                raise ValueError("learned comparison pointer contract mismatch")
        if self.case_ids != tuple(sorted(set(self.case_ids))):
            raise ValueError("learned comparison case selection is not uniquely sorted")
        body = self.model_dump(mode="json", exclude={"run_id", "command_sha256"})
        if self.run_id != "imgsdxllearnedrun_" + content_sha256(body)[
            7:39
        ] or self.command_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"command_sha256"})
        ):
            raise ValueError("learned comparison command identity/hash mismatch")
        return self


@dataclass(frozen=True, slots=True)
class SdxlLearnedComparisonSources:
    extraction_command: LocalImageInformativeLineartExtractionCommand
    extraction_result: LocalImageInformativeLineartExtractionResult
    lora_evaluation_command: LocalImageSdxlLoraEvaluationCommand
    lora_sources: SdxlLoraEvaluationSources

    @property
    def baseline(self) -> LocalImageSdxlLineartProbeCommand:
        return self.lora_sources.baseline


def select_sdxl_learned_cases(
    command: LocalImageSdxlLearnedComparisonCommand, baseline: LocalImageSdxlLineartProbeCommand
) -> tuple[SdxlLineartProbeCase, ...]:
    by_id = {case.case_id: case for case in baseline.cases}
    if not set(command.case_ids) <= set(by_id) or any(
        command.seed not in by_id[case_id].seeds for case_id in command.case_ids
    ):
        raise ValueError("learned comparison original case/seed mismatch")
    return tuple(by_id[case_id] for case_id in command.case_ids)


def validate_sdxl_learned_comparison_sources(
    command: LocalImageSdxlLearnedComparisonCommand, sources: SdxlLearnedComparisonSources
) -> None:
    extraction_command, extraction_result = sources.extraction_command, sources.extraction_result
    baseline = sources.baseline
    validate_sdxl_lora_evaluation_sources(
        sources.lora_evaluation_command,
        baseline,
        sources.lora_sources.training_command,
        sources.lora_sources.training_result,
        sources.lora_sources.manifest,
    )
    validate_informative_lineart_extraction_result(extraction_command, baseline, extraction_result)
    select_sdxl_learned_cases(command, baseline)
    if (
        command.baseline_command != extraction_command.baseline_command
        or command.baseline_command != sources.lora_evaluation_command.evaluation.baseline_command
        or extraction_result.status != "SUCCEEDED"
        or not set(command.case_ids) <= {output.case_id for output in extraction_result.outputs}
        or command.created_at
        < max(extraction_result.completed_at, sources.lora_evaluation_command.created_at)
    ):
        raise ValueError("learned comparison source lineage/status/time mismatch")


def _document(
    payload: bytes, pointer: ImageEvaluationArtifactMember, family: str, model: type[FrozenModel]
) -> FrozenModel:
    from eom_image_contracts.validation import validate_contract

    if (
        not 0 < len(payload) <= 256 * 1024
        or "sha256:" + hashlib.sha256(payload).hexdigest() != pointer.sha256
    ):
        raise ValueError("learned comparison metadata hash/bound mismatch")
    value = json.loads(payload)
    validate_contract(family, value)
    parsed = model.model_validate(value)
    if payload != content_json_bytes(parsed.model_dump(mode="json")):
        raise ValueError("noncanonical learned comparison metadata")
    return parsed


def parse_sdxl_learned_comparison_sources(
    command: LocalImageSdxlLearnedComparisonCommand,
    *,
    baseline_payload: bytes,
    extraction_command_payload: bytes,
    extraction_result_payload: bytes,
    lora_evaluation_command_payload: bytes,
    training_command_payload: bytes,
    training_result_payload: bytes,
    adapter_manifest_payload: bytes,
) -> SdxlLearnedComparisonSources:
    lora_command = cast(
        LocalImageSdxlLoraEvaluationCommand,
        _document(
            lora_evaluation_command_payload,
            command.lora_evaluation_command,
            "sdxl-lora-evaluation-command",
            LocalImageSdxlLoraEvaluationCommand,
        ),
    )
    if lora_command.evaluation.baseline_command != command.baseline_command:
        raise ValueError("learned comparison baseline differs from LoRA evaluation")
    lora_sources = parse_sdxl_lora_evaluation_sources(
        lora_command,
        baseline_payload=baseline_payload,
        training_command_payload=training_command_payload,
        training_result_payload=training_result_payload,
        manifest_payload=adapter_manifest_payload,
    )
    extraction_command = cast(
        LocalImageInformativeLineartExtractionCommand,
        _document(
            extraction_command_payload,
            command.extraction_command,
            "informative-lineart-extraction-command",
            LocalImageInformativeLineartExtractionCommand,
        ),
    )
    extraction_result = cast(
        LocalImageInformativeLineartExtractionResult,
        _document(
            extraction_result_payload,
            command.extraction_result,
            "informative-lineart-extraction-result",
            LocalImageInformativeLineartExtractionResult,
        ),
    )
    sources = SdxlLearnedComparisonSources(
        extraction_command, extraction_result, lora_command, lora_sources
    )
    validate_sdxl_learned_comparison_sources(command, sources)
    return sources


class SdxlLearnedComparisonOutput(FrozenModel):
    arm: LearnedComparisonArm
    case_id: ExtractionCaseId
    seed: int = Field(ge=0, le=2**32 - 1)
    reference_sha256: Sha256
    conditioning_sha256: Sha256
    member_path: str = Field(
        pattern=r"^outputs/(?:base|lora)/final/imgsdxlcase_[0-9a-f]{32}-[0-9]{10}\.png$"
    )
    sha256: Sha256
    size_bytes: int = Field(ge=1, le=16 * 1024**2)
    raw_member_path: str = Field(
        pattern=r"^outputs/(?:base|lora)/raw/imgsdxlcase_[0-9a-f]{32}-[0-9]{10}\.png$"
    )
    raw_sha256: Sha256
    raw_size_bytes: int = Field(ge=1, le=16 * 1024**2)
    width_px: Literal[800]
    height_px: Literal[500]
    duration_ms: int = Field(ge=1, le=1_800_000)
    peak_gpu_memory_bytes: int = Field(ge=1, le=16 * 1024**3)

    @model_validator(mode="after")
    def exact_member_identity(self) -> Self:
        filename = f"{self.case_id}-{self.seed:010d}.png"
        if (
            self.member_path != f"outputs/{self.arm.lower()}/final/{filename}"
            or self.raw_member_path != f"outputs/{self.arm.lower()}/raw/{filename}"
        ):
            raise ValueError("learned comparison output member identity differs")
        return self


class LocalImageSdxlLearnedComparisonResult(FrozenModel):
    schema_version: Literal["local-image-sdxl-learned-comparison-result/1.0"]
    run_id: str = Field(pattern=r"^imgsdxllearnedrun_[0-9a-f]{32}$")
    command_sha256: Sha256
    baseline_command_sha256: Sha256
    extraction_result_sha256: Sha256
    model: SdxlLineartStackPointer
    conditioning_policy: Literal["PINNED_LEARNED_FINE_INVERTED/1.0"]
    status: Literal["SUCCEEDED", "FAILED"]
    error_code: SdxlProbeErrorCode | None
    runtime: LocalImageRuntime | None
    outputs: tuple[SdxlLearnedComparisonOutput, ...] = Field(max_length=6)
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
        keys = tuple((entry.arm, entry.case_id, entry.seed) for entry in self.outputs)
        if keys != tuple(sorted(set(keys))) or self.completed_at < self.started_at:
            raise ValueError("learned comparison result order/UTC mismatch")
        if (self.status == "SUCCEEDED") != (self.error_code is None):
            raise ValueError("learned comparison result status/error mismatch")
        if self.status == "SUCCEEDED" and (self.runtime is None or not self.outputs):
            raise ValueError("learned comparison success lacks runtime/output")
        if self.outputs and (
            self.runtime is None
            or self.runtime.peak_gpu_memory_bytes
            < max(entry.peak_gpu_memory_bytes for entry in self.outputs)
        ):
            raise ValueError("learned comparison peak/runtime omits output memory")
        if self.result_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"result_sha256"})
        ):
            raise ValueError("learned comparison result hash mismatch")
        return self


def validate_sdxl_learned_comparison_result(
    command: LocalImageSdxlLearnedComparisonCommand,
    sources: SdxlLearnedComparisonSources,
    result: LocalImageSdxlLearnedComparisonResult,
) -> None:
    validate_sdxl_learned_comparison_sources(command, sources)
    cases = select_sdxl_learned_cases(command, sources.baseline)
    expected = tuple(
        (arm, case.case_id, command.seed) for arm in LEARNED_COMPARISON_ARMS for case in cases
    )
    observed = tuple((output.arm, output.case_id, output.seed) for output in result.outputs)
    if (
        result.run_id != command.run_id
        or result.command_sha256 != command.command_sha256
        or result.baseline_command_sha256 != sources.baseline.command_sha256
        or result.extraction_result_sha256 != sources.extraction_result.result_sha256
        or result.model != sources.baseline.model
        or result.conditioning_policy != command.conditioning_policy
    ):
        raise ValueError("learned comparison result differs from pinned inputs")
    if result.status == "SUCCEEDED":
        if (
            observed != expected
            or result.duration_ms > command.budget.maximum_duration_ms
            or result.runtime is None
            or result.runtime.peak_gpu_memory_bytes > command.budget.maximum_peak_gpu_memory_bytes
        ):
            raise ValueError("learned comparison success coverage/budget mismatch")
    elif observed != expected[: len(observed)]:
        raise ValueError("learned comparison failure is not an execution prefix")
    originals = {case.case_id: case.reference_image.sha256 for case in cases}
    conditionings = {
        entry.case_id: entry.conditioning_sha256 for entry in sources.extraction_result.outputs
    }
    if any(
        output.reference_sha256 != originals[output.case_id]
        or output.conditioning_sha256 != conditionings[output.case_id]
        for output in result.outputs
    ):
        raise ValueError("learned comparison output source hash mismatch")
