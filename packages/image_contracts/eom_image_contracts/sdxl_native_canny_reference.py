"""Closed native-adapter substitution over unchanged reviewed source-initialized cases."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Self

from pydantic import model_validator

from eom_image_contracts.models import ImageEvaluationArtifactMember, Sha256
from eom_image_contracts.sdxl_canny_comparison import _document
from eom_image_contracts.sdxl_canny_reference import (
    LocalImageSdxlCannyReferenceCommand,
    LocalImageSdxlCannyReferenceResult,
    SdxlCannyReferenceSources,
    parse_sdxl_canny_reference_sources,
    validate_sdxl_canny_reference_result,
)
from eom_image_contracts.sdxl_native_evaluation import (
    LocalImageSdxlNativeEvaluationCommand,
    SdxlNativeEvaluationSources,
    parse_sdxl_native_evaluation_sources,
)
from eom_image_contracts.validation import validate_contract


class LocalImageSdxlNativeCannyReferenceCommand(LocalImageSdxlCannyReferenceCommand):
    schema_version: Literal["local-image-sdxl-canny-reference-command/1.1"]  # type: ignore[assignment]
    native_evaluation_command: ImageEvaluationArtifactMember
    case_relation: Literal["REVIEWED_TRAIN_REFERENCE_NOT_HOLDOUT"]

    @model_validator(mode="after")
    def native_pin(self) -> Self:
        pin = self.native_evaluation_command
        if (
            pin.schema_ref
            != "eom://schemas/image-provider/local-image-sdxl-lora-evaluation-command/1.2"
            or pin.media_type != "application/json"
            or pin.member_path != "manifests/sdxl-lora-evaluation-command.json"
        ):
            raise ValueError("native reference requires explicit native evaluation lineage")
        return self


class LocalImageSdxlNativeCannyReferenceResult(LocalImageSdxlCannyReferenceResult):
    schema_version: Literal["local-image-sdxl-canny-reference-result/1.1"]  # type: ignore[assignment]
    native_evaluation_command_sha256: Sha256
    native_adapter_manifest_sha256: Sha256
    case_relation: Literal["REVIEWED_TRAIN_REFERENCE_NOT_HOLDOUT"]


@dataclass(frozen=True, slots=True)
class SdxlNativeCannyReferenceSources(SdxlCannyReferenceSources):
    evaluation: LocalImageSdxlNativeEvaluationCommand
    native: SdxlNativeEvaluationSources


def native_reference_evaluation(
    command: LocalImageSdxlNativeCannyReferenceCommand, raw: bytes
) -> LocalImageSdxlNativeEvaluationCommand:
    return _document(
        raw,
        command.native_evaluation_command,
        LocalImageSdxlNativeEvaluationCommand,
        "sdxl-lora-evaluation-command-v3",
    )


def native_reference_metadata_pointers(
    command: LocalImageSdxlNativeCannyReferenceCommand,
    evaluation: LocalImageSdxlNativeEvaluationCommand,
) -> dict[str, ImageEvaluationArtifactMember]:
    pin = evaluation.evaluation
    return {
        "inputs/native-evaluation-command.json": command.native_evaluation_command,
        "inputs/native-baseline-command.json": pin.baseline_command,
        "inputs/native-training-command.json": pin.training_command,
        "inputs/native-training-result.json": pin.training_result,
        "inputs/native-adapter-manifest.json": pin.adapter_manifest,
    }


def attach_native_reference_sources(
    command: LocalImageSdxlNativeCannyReferenceCommand,
    inherited: SdxlCannyReferenceSources,
    metadata: Mapping[str, bytes],
) -> SdxlNativeCannyReferenceSources:
    evaluation = native_reference_evaluation(
        command, metadata["inputs/native-evaluation-command.json"]
    )
    native = parse_sdxl_native_evaluation_sources(
        evaluation,
        baseline_payload=metadata["inputs/native-baseline-command.json"],
        training_command_payload=metadata["inputs/native-training-command.json"],
        training_result_payload=metadata["inputs/native-training-result.json"],
        manifest_payload=metadata["inputs/native-adapter-manifest.json"],
    )
    historical = inherited.spatial_sources.targets.lora
    if (
        evaluation.created_at > command.created_at
        or native.baseline.model != historical.baseline.model
        or native.training_command.training_authorization
        != historical.training_command.training_authorization
    ):
        raise ValueError("native reference model/authorization/chronology mismatch")
    return SdxlNativeCannyReferenceSources(
        inherited.spatial_command,
        inherited.spatial_result,
        inherited.spatial_sources,
        evaluation,
        native,
    )


def parse_reference_sources(
    command: LocalImageSdxlCannyReferenceCommand, metadata: Mapping[str, bytes]
) -> SdxlCannyReferenceSources:
    inherited = parse_sdxl_canny_reference_sources(command, metadata)
    if isinstance(command, LocalImageSdxlNativeCannyReferenceCommand):
        return attach_native_reference_sources(command, inherited, metadata)
    return inherited


def reference_command_contract(command: LocalImageSdxlCannyReferenceCommand) -> str:
    if type(command) is LocalImageSdxlNativeCannyReferenceCommand:
        return "sdxl-canny-reference-command-v2"
    if type(command) is LocalImageSdxlCannyReferenceCommand:
        return "sdxl-canny-reference-command"
    raise ValueError("SDXL_CANNY_REFERENCE_COMMAND_FAMILY_INVALID")


def parse_reference_command(value: object) -> LocalImageSdxlCannyReferenceCommand:
    if not isinstance(value, dict):
        raise ValueError("SDXL_CANNY_REFERENCE_COMMAND_FAMILY_INVALID")
    model: type[LocalImageSdxlCannyReferenceCommand]
    if value.get("schema_version") == "local-image-sdxl-canny-reference-command/1.0":
        model, contract = LocalImageSdxlCannyReferenceCommand, "sdxl-canny-reference-command"
    elif value.get("schema_version") == "local-image-sdxl-canny-reference-command/1.1":
        model, contract = (
            LocalImageSdxlNativeCannyReferenceCommand,
            "sdxl-canny-reference-command-v2",
        )
    else:
        raise ValueError("SDXL_CANNY_REFERENCE_COMMAND_FAMILY_INVALID")
    validate_contract(contract, value)
    return model.model_validate(value)


def parse_reference_result(value: object) -> LocalImageSdxlCannyReferenceResult:
    if not isinstance(value, dict):
        raise ValueError("SDXL_CANNY_REFERENCE_RESULT_FAMILY_INVALID")
    model: type[LocalImageSdxlCannyReferenceResult]
    if value.get("schema_version") == "local-image-sdxl-canny-reference-result/1.0":
        model, contract = LocalImageSdxlCannyReferenceResult, "sdxl-canny-reference-result"
    elif value.get("schema_version") == "local-image-sdxl-canny-reference-result/1.1":
        model, contract = LocalImageSdxlNativeCannyReferenceResult, "sdxl-canny-reference-result-v2"
    else:
        raise ValueError("SDXL_CANNY_REFERENCE_RESULT_FAMILY_INVALID")
    validate_contract(contract, value)
    return model.model_validate(value)


def validate_reference_result(
    command: LocalImageSdxlCannyReferenceCommand,
    sources: SdxlCannyReferenceSources,
    result: LocalImageSdxlCannyReferenceResult,
) -> None:
    validate_sdxl_canny_reference_result(command, sources, result)
    if isinstance(command, LocalImageSdxlNativeCannyReferenceCommand):
        if (
            not isinstance(sources, SdxlNativeCannyReferenceSources)
            or not isinstance(result, LocalImageSdxlNativeCannyReferenceResult)
            or result.native_evaluation_command_sha256 != sources.evaluation.command_sha256
            or result.native_adapter_manifest_sha256 != sources.native.manifest.manifest_sha256
        ):
            raise ValueError("native reference result adapter identity mismatch")
    elif type(result) is not LocalImageSdxlCannyReferenceResult:
        raise ValueError("legacy reference result family mismatch")
