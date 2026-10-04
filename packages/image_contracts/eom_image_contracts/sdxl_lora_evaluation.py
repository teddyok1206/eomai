"""Matched-input SDXL LoRA evaluation; baseline and training stay immutable pointers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Self, cast

from pydantic import Field, field_validator, model_validator

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
    SdxlLineartProbeConditioning,
    SdxlLineartProbeOutput,
    SdxlLineartStackPointer,
    SdxlProbeErrorCode,
)
from eom_image_contracts.sdxl_lora_micro import (
    LocalImageSdxlLoraMicroAdapterManifest,
    LocalImageSdxlLoraMicroCommand,
    LocalImageSdxlLoraMicroResult,
    validate_sdxl_lora_micro_result,
)
from eom_image_contracts.sdxl_reviewed_micro import (
    LocalImageSdxlReviewedMicroCommand,
    LocalImageSdxlReviewedMicroResult,
)

_PREFIX = "eom://schemas/image-provider/"


class SdxlLoraEvaluationPin(FrozenModel):
    baseline_command: ImageEvaluationArtifactMember
    training_command: ImageEvaluationArtifactMember
    training_result: ImageEvaluationArtifactMember
    adapter_manifest: ImageEvaluationArtifactMember
    adapter_id: str = Field(pattern=r"^imgadapter_[0-9a-f]{32}$")
    adapter_revision_id: str = Field(pattern=r"^imgadapterrev_[0-9a-f]{32}$")
    adapter_manifest_sha256: Sha256
    adapter_strength: float = Field(gt=0, le=1)

    def training_contract_version(self) -> str:
        return "1.0"

    @model_validator(mode="after")
    def exact_pointers(self) -> Self:
        for pointer, member, family in (
            (self.baseline_command, "sdxl-lineart-probe-command", "sdxl-lineart-probe-command"),
            (self.training_command, "sdxl-lora-micro-command", "sdxl-lora-micro-command"),
            (self.training_result, "sdxl-lora-micro-result", "sdxl-lora-micro-result"),
            (
                self.adapter_manifest,
                "sdxl-lora-micro-adapter-manifest",
                "sdxl-lora-micro-adapter-manifest",
            ),
        ):
            version = (
                self.training_contract_version()
                if family in {"sdxl-lora-micro-command", "sdxl-lora-micro-result"}
                else "1.0"
            )
            if (
                pointer.media_type != "application/json"
                or pointer.schema_ref != _PREFIX + "local-image-" + family + "/" + version
                or pointer.member_path != "manifests/" + member + ".json"
            ):
                raise ValueError("SDXL evaluation metadata pointer contract mismatch")
        if (
            self.training_result.artifact_id != self.adapter_manifest.artifact_id
            or self.training_result.artifact_revision_id
            != self.adapter_manifest.artifact_revision_id
        ):
            raise ValueError("SDXL adapter must belong to its accepted result revision")
        return self


class LocalImageSdxlLoraEvaluationCommand(FrozenModel):
    schema_version: Literal["local-image-sdxl-lora-evaluation-command/1.0"]
    run_id: str = Field(pattern=r"^imgsdxlloraevalrun_[0-9a-f]{32}$")
    created_at: datetime
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    evaluation: SdxlLoraEvaluationPin
    purpose: Literal["EVALUATION_ONLY_MATCHED_SDXL_LORA"]
    activation_policy: Literal["FORBIDDEN"]
    command_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_created(cls, value: datetime) -> datetime:
        if value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("SDXL evaluation timestamp must use UTC")
        return value

    @model_validator(mode="after")
    def immutable_identity(self) -> Self:
        identity = content_sha256(
            self.model_dump(mode="json", exclude={"run_id", "command_sha256"})
        )
        if self.run_id != "imgsdxlloraevalrun_" + identity[
            7:39
        ] or self.command_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"command_sha256"})
        ):
            raise ValueError("SDXL evaluation immutable command identity/hash mismatch")
        return self


def validate_sdxl_lora_evaluation_sources(
    command: LocalImageSdxlLoraEvaluationCommand,
    baseline: LocalImageSdxlLineartProbeCommand,
    training_command: LocalImageSdxlLoraMicroCommand | LocalImageSdxlReviewedMicroCommand,
    training_result: LocalImageSdxlLoraMicroResult,
    manifest: LocalImageSdxlLoraMicroAdapterManifest,
) -> None:
    validate_sdxl_lora_micro_result(training_command, training_result)
    pin = command.evaluation
    sources = {sample.source_image for sample in training_command.training_samples}
    reviewed = isinstance(training_command, LocalImageSdxlReviewedMicroCommand)
    if reviewed != (command.evaluation.training_contract_version() == "1.1"):
        raise ValueError("SDXL evaluation training family differs from declared diagnostic")
    if (
        training_result.status != "SUCCEEDED"
        or training_result.adapter_manifest != manifest
        or manifest.base_model != baseline.model
        or manifest.adapter_id != pin.adapter_id
        or manifest.adapter_revision_id != pin.adapter_revision_id
        or manifest.manifest_sha256 != pin.adapter_manifest_sha256
        or training_result.completed_at > command.created_at
        or baseline.created_at > command.created_at
        or "INTERNAL_SDXL_COMPARISON"
        not in training_command.experiment_authorization.permitted_uses
        or (not reviewed and any(case.reference_image not in sources for case in baseline.cases))
    ):
        raise ValueError("SDXL evaluation training/baseline provenance mismatch")


@dataclass(frozen=True, slots=True)
class SdxlLoraEvaluationSources:
    baseline: LocalImageSdxlLineartProbeCommand
    training_command: LocalImageSdxlLoraMicroCommand | LocalImageSdxlReviewedMicroCommand
    training_result: LocalImageSdxlLoraMicroResult
    manifest: LocalImageSdxlLoraMicroAdapterManifest


def parse_sdxl_lora_evaluation_sources(
    command: LocalImageSdxlLoraEvaluationCommand,
    *,
    baseline_payload: bytes,
    training_command_payload: bytes,
    training_result_payload: bytes,
    manifest_payload: bytes,
) -> SdxlLoraEvaluationSources:
    """Pure byte/schema/provenance checks shared by the two authorized I/O boundaries."""
    from eom_image_contracts.validation import validate_contract

    pin = command.evaluation
    reviewed = pin.training_contract_version() == "1.1"
    entries = (
        (
            pin.baseline_command,
            baseline_payload,
            "sdxl-lineart-probe-command",
            LocalImageSdxlLineartProbeCommand,
        ),
        (
            pin.training_command,
            training_command_payload,
            "sdxl-lora-micro-command-v2" if reviewed else "sdxl-lora-micro-command",
            LocalImageSdxlReviewedMicroCommand if reviewed else LocalImageSdxlLoraMicroCommand,
        ),
        (
            pin.training_result,
            training_result_payload,
            "sdxl-lora-micro-result-v2" if reviewed else "sdxl-lora-micro-result",
            LocalImageSdxlReviewedMicroResult if reviewed else LocalImageSdxlLoraMicroResult,
        ),
        (
            pin.adapter_manifest,
            manifest_payload,
            "sdxl-lora-micro-adapter-manifest",
            LocalImageSdxlLoraMicroAdapterManifest,
        ),
    )
    parsed_fields: list[FrozenModel] = []
    for pointer, raw, contract, model in entries:
        if (
            not 0 < len(raw) <= 256 * 1024
            or "sha256:" + hashlib.sha256(raw).hexdigest() != pointer.sha256
        ):
            raise ValueError("SDXL evaluation metadata hash/bound mismatch")
        value = json.loads(raw)
        validate_contract(contract, value)
        parsed = model.model_validate(value)
        canonical = content_json_bytes(parsed.model_dump(mode="json"))
        if raw not in (canonical, canonical + b"\n"):
            raise ValueError("SDXL evaluation metadata is noncanonical")
        parsed_fields.append(parsed)
    sources = SdxlLoraEvaluationSources(
        cast(LocalImageSdxlLineartProbeCommand, parsed_fields[0]),
        cast(LocalImageSdxlLoraMicroCommand | LocalImageSdxlReviewedMicroCommand, parsed_fields[1]),
        cast(LocalImageSdxlLoraMicroResult, parsed_fields[2]),
        cast(LocalImageSdxlLoraMicroAdapterManifest, parsed_fields[3]),
    )
    validate_sdxl_lora_evaluation_sources(
        command,
        sources.baseline,
        sources.training_command,
        sources.training_result,
        sources.manifest,
    )
    return sources


class LocalImageSdxlLoraEvaluationResult(FrozenModel):
    schema_version: Literal["local-image-sdxl-lora-evaluation-result/1.0"]
    run_id: str = Field(pattern=r"^imgsdxlloraevalrun_[0-9a-f]{32}$")
    command_sha256: Sha256
    evaluation: SdxlLoraEvaluationPin
    baseline_command_sha256: Sha256
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
    def utc_time(cls, value: datetime) -> datetime:
        if value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("SDXL evaluation timestamp must use UTC")
        return value

    @model_validator(mode="after")
    def exact_evidence(self) -> Self:
        from eom_image_contracts.sdxl_lineart_probe import validate_sdxl_probe_evidence

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
            raise ValueError("SDXL evaluation result hash mismatch")
        return self


def validate_sdxl_lora_evaluation_result(
    command: LocalImageSdxlLoraEvaluationCommand,
    baseline: LocalImageSdxlLineartProbeCommand,
    result: LocalImageSdxlLoraEvaluationResult,
) -> None:
    from eom_image_contracts.sdxl_lineart_probe import validate_sdxl_probe_coverage

    if (
        result.run_id != command.run_id
        or result.schema_version.rsplit("/", 1)[1] != command.schema_version.rsplit("/", 1)[1]
        or result.command_sha256 != command.command_sha256
        or result.evaluation != command.evaluation
        or result.baseline_command_sha256 != baseline.command_sha256
        or result.model != baseline.model
        or result.started_at < command.created_at
    ):
        raise ValueError("SDXL evaluation result differs from pinned command")
    validate_sdxl_probe_coverage(
        baseline,
        status=result.status,
        conditionings=result.conditionings,
        outputs=result.outputs,
        duration_ms=result.duration_ms,
    )
