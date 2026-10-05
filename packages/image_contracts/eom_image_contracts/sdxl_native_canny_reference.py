"""Closed native-adapter substitution over unchanged reviewed source-initialized cases."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
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
from eom_image_contracts.sdxl_native_geometry import (
    LocalImageSdxlNativeGeometryCommandV2,
    validate_sdxl_native_geometry_sources,
)
from eom_image_contracts.validation import validate_contract


class LocalImageSdxlNativeCannyReferenceCommand(LocalImageSdxlCannyReferenceCommand):
    schema_version: Literal["local-image-sdxl-canny-reference-command/1.1"]  # type: ignore[assignment]
    native_evaluation_command: ImageEvaluationArtifactMember
    case_relation: Literal["REVIEWED_TRAIN_REFERENCE_NOT_HOLDOUT"]

    @model_validator(mode="after")
    def native_pin(self) -> Self:
        pin = self.native_evaluation_command
        protocol = reference_protocol(self)
        if (
            pin.schema_ref != protocol.evaluation_schema
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


class LocalImageSdxlNativeCannyReferenceCommandV2(LocalImageSdxlNativeCannyReferenceCommand):
    schema_version: Literal["local-image-sdxl-canny-reference-command/1.2"]  # type: ignore[assignment]


class LocalImageSdxlNativeCannyReferenceResultV2(LocalImageSdxlNativeCannyReferenceResult):
    schema_version: Literal["local-image-sdxl-canny-reference-result/1.2"]  # type: ignore[assignment]


@dataclass(frozen=True, slots=True)
class SdxlReferenceProtocol:
    command_version: str
    result_version: str
    command_model: type[LocalImageSdxlCannyReferenceCommand]
    result_model: type[LocalImageSdxlCannyReferenceResult]
    command_contract: str
    result_contract: str
    evaluation_schema: str | None = None
    evaluation_model: type[LocalImageSdxlNativeEvaluationCommand] | None = None
    evaluation_contract: str | None = None


# One closed codec owns parsing, provenance and result selection across all consumers.
_PROTOCOLS = (
    SdxlReferenceProtocol(
        "local-image-sdxl-canny-reference-command/1.0",
        "local-image-sdxl-canny-reference-result/1.0",
        LocalImageSdxlCannyReferenceCommand,
        LocalImageSdxlCannyReferenceResult,
        "sdxl-canny-reference-command",
        "sdxl-canny-reference-result",
    ),
    SdxlReferenceProtocol(
        "local-image-sdxl-canny-reference-command/1.1",
        "local-image-sdxl-canny-reference-result/1.1",
        LocalImageSdxlNativeCannyReferenceCommand,
        LocalImageSdxlNativeCannyReferenceResult,
        "sdxl-canny-reference-command-v2",
        "sdxl-canny-reference-result-v2",
        "eom://schemas/image-provider/local-image-sdxl-lora-evaluation-command/1.2",
        LocalImageSdxlNativeEvaluationCommand,
        "sdxl-lora-evaluation-command-v3",
    ),
    SdxlReferenceProtocol(
        "local-image-sdxl-canny-reference-command/1.2",
        "local-image-sdxl-canny-reference-result/1.2",
        LocalImageSdxlNativeCannyReferenceCommandV2,
        LocalImageSdxlNativeCannyReferenceResultV2,
        "sdxl-canny-reference-command-v3",
        "sdxl-canny-reference-result-v3",
        "eom://schemas/image-provider/local-image-sdxl-lora-evaluation-command/1.4",
        LocalImageSdxlNativeGeometryCommandV2,
        "sdxl-lora-evaluation-command-v5",
    ),
)
_COMMAND_PROTOCOLS = MappingProxyType({p.command_version: p for p in _PROTOCOLS})
_RESULT_PROTOCOLS = MappingProxyType({p.result_version: p for p in _PROTOCOLS})


def reference_protocol(command: LocalImageSdxlCannyReferenceCommand) -> SdxlReferenceProtocol:
    protocol = _COMMAND_PROTOCOLS.get(command.schema_version)
    if protocol is None or type(command) is not protocol.command_model:
        raise ValueError("SDXL_CANNY_REFERENCE_COMMAND_FAMILY_INVALID")
    return protocol


@dataclass(frozen=True, slots=True)
class SdxlNativeCannyReferenceSources(SdxlCannyReferenceSources):
    evaluation: LocalImageSdxlNativeEvaluationCommand
    native: SdxlNativeEvaluationSources


def native_reference_evaluation(
    command: LocalImageSdxlNativeCannyReferenceCommand, raw: bytes
) -> LocalImageSdxlNativeEvaluationCommand:
    protocol = reference_protocol(command)
    if protocol.evaluation_model is None or protocol.evaluation_contract is None:
        raise ValueError("SDXL_CANNY_REFERENCE_COMMAND_FAMILY_INVALID")
    return _document(
        raw,
        command.native_evaluation_command,
        protocol.evaluation_model,
        protocol.evaluation_contract,
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
    if isinstance(evaluation, LocalImageSdxlNativeGeometryCommandV2):
        validate_sdxl_native_geometry_sources(evaluation, native)
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
    return reference_protocol(command).command_contract


def parse_reference_command(value: object) -> LocalImageSdxlCannyReferenceCommand:
    if not isinstance(value, dict):
        raise ValueError("SDXL_CANNY_REFERENCE_COMMAND_FAMILY_INVALID")
    version = value.get("schema_version")
    protocol = _COMMAND_PROTOCOLS.get(version) if isinstance(version, str) else None
    if protocol is None:
        raise ValueError("SDXL_CANNY_REFERENCE_COMMAND_FAMILY_INVALID")
    validate_contract(protocol.command_contract, value)
    return protocol.command_model.model_validate(value)


def parse_reference_result(value: object) -> LocalImageSdxlCannyReferenceResult:
    if not isinstance(value, dict):
        raise ValueError("SDXL_CANNY_REFERENCE_RESULT_FAMILY_INVALID")
    version = value.get("schema_version")
    protocol = _RESULT_PROTOCOLS.get(version) if isinstance(version, str) else None
    if protocol is None:
        raise ValueError("SDXL_CANNY_REFERENCE_RESULT_FAMILY_INVALID")
    validate_contract(protocol.result_contract, value)
    return protocol.result_model.model_validate(value)


def validate_reference_result(
    command: LocalImageSdxlCannyReferenceCommand,
    sources: SdxlCannyReferenceSources,
    result: LocalImageSdxlCannyReferenceResult,
) -> None:
    if type(result) is not reference_protocol(command).result_model:
        raise ValueError("reference result family/adapter identity mismatch")
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
