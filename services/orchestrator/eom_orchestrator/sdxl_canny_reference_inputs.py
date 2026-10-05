"""Readmit spatial history before materializing three exact TRAIN initializers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from eom_image_contracts.models import content_json_bytes
from eom_image_contracts.sdxl_canny_comparison import LocalImageSdxlCannyComparisonCommand
from eom_image_contracts.sdxl_canny_reference import (
    LocalImageSdxlCannyReferenceCommand,
    SdxlCannyReferenceSources,
)
from eom_image_contracts.sdxl_native_canny_reference import (
    LocalImageSdxlNativeCannyReferenceCommand,
    SdxlNativeCannyReferenceSources,
    native_reference_evaluation,
    native_reference_metadata_pointers,
    parse_reference_command,
    parse_reference_sources,
)
from eom_image_contracts.sdxl_reviewed_micro import (
    LocalImageSdxlReviewedMicroCommand,
    sdxl_reviewed_micro_metadata_pointers,
)
from eom_image_contracts.source_page_crops import parse_source_page_crop_review
from sqlalchemy import Engine

from eom_orchestrator.control_artifact_resolution import (
    BoundedControlArtifactRead,
    resolve_control_artifact_member,
    resolve_control_artifact_members,
)
from eom_orchestrator.sdxl_canny_comparison_inputs import (
    ResolvedSdxlCannyComparisonMetadata,
    SdxlCannyAdapterInput,
    materialize_sdxl_canny_comparison_files,
    resolve_sdxl_canny_comparison_metadata,
    sdxl_canny_comparison_input_hashes,
)
from eom_orchestrator.sdxl_native_lora_inputs import (
    AdmittedSdxlNativeLoraSources,
    resolve_sdxl_native_lora_sources,
)
from eom_orchestrator.sdxl_probe_inputs import SdxlProbeInputMember


@dataclass(frozen=True, slots=True)
class PreparedSdxlCannyReferenceInputs:
    command: LocalImageSdxlCannyReferenceCommand
    sources: SdxlCannyReferenceSources
    spatial_metadata: ResolvedSdxlCannyComparisonMetadata
    files: tuple[SdxlProbeInputMember, ...]


@dataclass(frozen=True, slots=True)
class ResolvedSdxlCannyReferenceMetadata:
    """The frozen numerical anchor without TRAIN PNG or adapter materialization."""

    command: LocalImageSdxlCannyReferenceCommand
    sources: SdxlCannyReferenceSources
    spatial_metadata: ResolvedSdxlCannyComparisonMetadata
    files: tuple[SdxlProbeInputMember, ...]
    native_admission: AdmittedSdxlNativeLoraSources | None = None


def sdxl_canny_reference_metadata_hashes(
    admitted: ResolvedSdxlCannyReferenceMetadata,
) -> dict[str, str]:
    metadata = {file.member_path: file.payload for file in admitted.files}
    if (
        parse_reference_sources(admitted.command, metadata) != admitted.sources
        or admitted.spatial_metadata.command != admitted.sources.spatial_command
        or admitted.spatial_metadata.sources != admitted.sources.spatial_sources
    ):
        raise ValueError("SDXL_CANNY_REFERENCE_HANDOFF_SOURCES_INVALID")
    expected = {
        path: sha
        for path, sha in sdxl_canny_comparison_input_hashes(admitted.spatial_metadata).items()
        if not path.startswith(("inputs/canny/", "inputs/adapter/")) and path != "command.json"
    }
    return {
        **expected,
        "command.json": "sha256:"
        + hashlib.sha256(content_json_bytes(admitted.command.model_dump(mode="json"))).hexdigest(),
        "inputs/spatial-command.json": admitted.command.spatial_command.sha256,
        "inputs/spatial-result.json": admitted.command.spatial_result.sha256,
        **_native_metadata_hashes(admitted.command, admitted.sources),
    }


def sdxl_canny_reference_input_hashes(
    prepared: PreparedSdxlCannyReferenceInputs,
) -> dict[str, str]:
    metadata = {file.member_path: file.payload for file in prepared.files}
    if (
        parse_reference_sources(prepared.command, metadata) != prepared.sources
        or prepared.spatial_metadata.command != prepared.sources.spatial_command
        or prepared.spatial_metadata.sources != prepared.sources.spatial_sources
    ):
        raise ValueError("SDXL_CANNY_REFERENCE_HANDOFF_SOURCES_INVALID")
    expected = sdxl_canny_comparison_input_hashes(prepared.spatial_metadata)
    expected.pop("command.json")
    if isinstance(prepared.sources, SdxlNativeCannyReferenceSources):
        expected = {
            path: sha for path, sha in expected.items() if not path.startswith("inputs/adapter/")
        }
        expected.update(
            {
                "inputs/adapter/" + file.relative_path: file.sha256
                for file in prepared.sources.native.manifest.files
            }
        )
    return {
        **expected,
        "command.json": "sha256:"
        + hashlib.sha256(content_json_bytes(prepared.command.model_dump(mode="json"))).hexdigest(),
        "inputs/spatial-command.json": prepared.command.spatial_command.sha256,
        "inputs/spatial-result.json": prepared.command.spatial_result.sha256,
        **_native_metadata_hashes(prepared.command, prepared.sources),
        **{
            entry.case.staged_member_path: entry.case.reference_image.sha256
            for entry in prepared.sources.spatial_sources.parent.cases
        },
    }


def _native_metadata_hashes(
    command: LocalImageSdxlCannyReferenceCommand, sources: SdxlCannyReferenceSources
) -> dict[str, str]:
    if isinstance(command, LocalImageSdxlNativeCannyReferenceCommand):
        if not isinstance(sources, SdxlNativeCannyReferenceSources):
            raise ValueError("SDXL_CANNY_REFERENCE_NATIVE_SOURCES_MISSING")
        return {
            name: pin.sha256
            for name, pin in native_reference_metadata_pointers(command, sources.evaluation).items()
        }
    return {}


def resolve_sdxl_canny_reference_metadata(
    engine: Engine,
    command: LocalImageSdxlCannyReferenceCommand,
) -> ResolvedSdxlCannyReferenceMetadata:
    command = parse_reference_command(command.model_dump(mode="json"))
    raw = resolve_control_artifact_member(engine, command.spatial_command, maximum_bytes=256 * 1024)
    spatial = LocalImageSdxlCannyComparisonCommand.model_validate_json(raw)
    admitted = resolve_sdxl_canny_comparison_metadata(engine, spatial)
    metadata = {
        file.member_path: file.payload
        for file in admitted.files
        if file.member_path != "command.json"
    }
    metadata["inputs/spatial-command.json"] = raw
    metadata["inputs/spatial-result.json"] = resolve_control_artifact_member(
        engine, command.spatial_result, maximum_bytes=256 * 1024
    )
    if isinstance(command, LocalImageSdxlNativeCannyReferenceCommand):
        native_raw = resolve_control_artifact_member(
            engine, command.native_evaluation_command, maximum_bytes=256 * 1024
        )
        evaluation = native_reference_evaluation(command, native_raw)
        metadata["inputs/native-evaluation-command.json"] = native_raw
        pointers = native_reference_metadata_pointers(command, evaluation)
        for name, pin in pointers.items():
            if name != "inputs/native-evaluation-command.json":
                metadata[name] = resolve_control_artifact_member(
                    engine, pin, maximum_bytes=256 * 1024
                )
    sources = parse_reference_sources(command, metadata)
    native = None
    if isinstance(sources, SdxlNativeCannyReferenceSources):
        native = resolve_sdxl_native_lora_sources(engine, sources.native.training_command)
        old_training = sources.spatial_sources.targets.lora.training_command
        if not isinstance(old_training, LocalImageSdxlReviewedMicroCommand):
            raise ValueError("SDXL_CANNY_REFERENCE_HISTORICAL_TRAINING_INVALID")
        old_pins = sdxl_reviewed_micro_metadata_pointers(
            old_training, metadata["inputs/source-crop-set.json"]
        )
        review = parse_source_page_crop_review(
            old_pins["inputs/source-review.json"], metadata["inputs/source-review.json"]
        )
        if native.sources.batches[0].sources.review.basis_crop_set != review.basis_crop_set:
            raise ValueError("SDXL_CANNY_REFERENCE_CROP_REVISION_MISMATCH")
    metadata["command.json"] = content_json_bytes(command.model_dump(mode="json"))
    return ResolvedSdxlCannyReferenceMetadata(
        command,
        sources,
        admitted,
        tuple(
            SdxlProbeInputMember(name, "sha256:" + hashlib.sha256(raw).hexdigest(), raw)
            for name, raw in sorted(metadata.items())
        ),
        native,
    )


def prepare_sdxl_canny_reference_inputs(
    engine: Engine,
    command: LocalImageSdxlCannyReferenceCommand,
) -> PreparedSdxlCannyReferenceInputs:
    reference = resolve_sdxl_canny_reference_metadata(engine, command)
    command = reference.command
    sources, admitted = reference.sources, reference.spatial_metadata
    metadata = {file.member_path: file.payload for file in reference.files}
    # Both successor and complete predecessor metadata are now admitted; no early pixels.
    selected = (
        SdxlCannyAdapterInput(
            sources.evaluation.evaluation.training_result, sources.native.manifest
        )
        if isinstance(sources, SdxlNativeCannyReferenceSources)
        else None
    )
    files = [
        file
        for file in materialize_sdxl_canny_comparison_files(
            engine, admitted, adapter_input=selected
        )
        if file.member_path != "command.json"
    ]
    for name in (
        "inputs/spatial-command.json",
        "inputs/spatial-result.json",
        *_native_metadata_hashes(command, sources),
    ):
        raw = metadata[name]
        files.append(SdxlProbeInputMember(name, "sha256:" + hashlib.sha256(raw).hexdigest(), raw))
    targets = {target.sample_id: target for target in sources.spatial_sources.targets.targets}
    reads = []
    for entry in sources.spatial_sources.parent.cases:
        size = targets[entry.sample_id].size_bytes
        if not 0 < size <= 16 * 1024**2:
            raise ValueError("SDXL_CANNY_REFERENCE_INPUT_SIZE_INVALID")
        reads.append(BoundedControlArtifactRead(entry.case.reference_image, size))
    payloads = resolve_control_artifact_members(engine, tuple(reads))
    for entry, read, pixels in zip(
        sources.spatial_sources.parent.cases, reads, payloads, strict=True
    ):
        if len(pixels) != read.maximum_bytes:
            raise ValueError("SDXL_CANNY_REFERENCE_INPUT_SIZE_INVALID")
        files.append(
            SdxlProbeInputMember(entry.case.staged_member_path, read.pointer.sha256, pixels)
        )
    raw = content_json_bytes(command.model_dump(mode="json"))
    files.append(
        SdxlProbeInputMember("command.json", "sha256:" + hashlib.sha256(raw).hexdigest(), raw)
    )
    return PreparedSdxlCannyReferenceInputs(
        command, sources, admitted, tuple(sorted(files, key=lambda file: file.member_path))
    )
