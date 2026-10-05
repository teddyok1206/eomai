"""Explicit native-trained adapter consumer; fixed TRAIN diagnostic, never holdout PASS."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from eom_image_contracts.sdxl_lineart_probe import LocalImageSdxlLineartProbeCommand
from eom_image_contracts.sdxl_lora_evaluation import (
    LocalImageSdxlLoraEvaluationCommand,
    LocalImageSdxlLoraEvaluationResult,
    SdxlLoraEvaluationPin,
    parse_sdxl_evaluation_metadata,
)
from eom_image_contracts.sdxl_native_lora import (
    LocalImageSdxlNativeLoraAdapterManifest,
    LocalImageSdxlNativeLoraResult,
    NativeLoraCommand,
    native_lora_command_protocol,
    validate_sdxl_native_lora_result,
)


class SdxlNativeLoraEvaluationPin(SdxlLoraEvaluationPin):
    def training_contract_family(self) -> str:
        return "sdxl-native-lora"


class SdxlNativeLoraEvaluationPinV2(SdxlNativeLoraEvaluationPin):
    """Explicit command1.1/result1.0 map; no released pin gains new meanings."""

    def training_contract_version(self) -> str:
        return "1.1"

    def training_result_contract_version(self) -> str:
        return "1.0"


class LocalImageSdxlNativeEvaluationCommand(LocalImageSdxlLoraEvaluationCommand):
    schema_version: Literal["local-image-sdxl-lora-evaluation-command/1.2"]  # type: ignore[assignment]
    evaluation: SdxlNativeLoraEvaluationPin
    case_relation: Literal["LEGACY_TRAIN_REFERENCE_DIAGNOSTIC_NOT_HOLDOUT"]


class LocalImageSdxlNativeEvaluationResult(LocalImageSdxlLoraEvaluationResult):
    schema_version: Literal["local-image-sdxl-lora-evaluation-result/1.2"]  # type: ignore[assignment]
    evaluation: SdxlNativeLoraEvaluationPin
    case_relation: Literal["LEGACY_TRAIN_REFERENCE_DIAGNOSTIC_NOT_HOLDOUT"]


@dataclass(frozen=True, slots=True)
class SdxlNativeEvaluationSources:
    baseline: LocalImageSdxlLineartProbeCommand
    training_command: NativeLoraCommand
    training_result: LocalImageSdxlNativeLoraResult
    manifest: LocalImageSdxlNativeLoraAdapterManifest


def parse_sdxl_native_evaluation_sources(
    command: LocalImageSdxlNativeEvaluationCommand,
    *,
    baseline_payload: bytes,
    training_command_payload: bytes,
    training_result_payload: bytes,
    manifest_payload: bytes,
) -> SdxlNativeEvaluationSources:
    pin = command.evaluation
    baseline = parse_sdxl_evaluation_metadata(
        pin.baseline_command,
        baseline_payload,
        "sdxl-lineart-probe-command",
        LocalImageSdxlLineartProbeCommand,
    )
    protocol = native_lora_command_protocol(
        "local-image-sdxl-native-lora-command/" + pin.training_contract_version()
    )
    training = parse_sdxl_evaluation_metadata(
        pin.training_command,
        training_command_payload,
        protocol.contract,
        protocol.model,
    )
    result = parse_sdxl_evaluation_metadata(
        pin.training_result,
        training_result_payload,
        "sdxl-native-lora-result",
        LocalImageSdxlNativeLoraResult,
    )
    manifest = parse_sdxl_evaluation_metadata(
        pin.adapter_manifest,
        manifest_payload,
        "sdxl-native-lora-adapter-manifest",
        LocalImageSdxlNativeLoraAdapterManifest,
    )
    validate_sdxl_native_lora_result(training, result)
    if (
        result.status != "SUCCEEDED"
        or result.adapter_manifest != manifest
        or manifest.base_model != baseline.model
        or manifest.adapter_id != pin.adapter_id
        or manifest.adapter_revision_id != pin.adapter_revision_id
        or manifest.manifest_sha256 != pin.adapter_manifest_sha256
        or result.completed_at > command.created_at
        or baseline.created_at > command.created_at
        or "INTERNAL_SDXL_COMPARISON" not in training.experiment_authorization.permitted_uses
    ):
        raise ValueError("SDXL_NATIVE_EVALUATION_PROVENANCE_MISMATCH")
    return SdxlNativeEvaluationSources(baseline, training, result, manifest)
