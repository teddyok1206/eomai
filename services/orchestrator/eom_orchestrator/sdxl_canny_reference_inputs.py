"""Readmit spatial history before materializing three exact TRAIN initializers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from eom_image_contracts.models import content_json_bytes
from eom_image_contracts.sdxl_canny_comparison import LocalImageSdxlCannyComparisonCommand
from eom_image_contracts.sdxl_canny_reference import (
    LocalImageSdxlCannyReferenceCommand,
    SdxlCannyReferenceSources,
    parse_sdxl_canny_reference_sources,
)
from eom_image_contracts.validation import validate_contract
from sqlalchemy import Engine

from eom_orchestrator.control_artifact_resolution import (
    BoundedControlArtifactRead,
    resolve_control_artifact_member,
    resolve_control_artifact_members,
)
from eom_orchestrator.sdxl_canny_comparison_inputs import (
    ResolvedSdxlCannyComparisonMetadata,
    materialize_sdxl_canny_comparison_files,
    resolve_sdxl_canny_comparison_metadata,
    sdxl_canny_comparison_input_hashes,
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


def sdxl_canny_reference_metadata_hashes(
    admitted: ResolvedSdxlCannyReferenceMetadata,
) -> dict[str, str]:
    metadata = {file.member_path: file.payload for file in admitted.files}
    if (
        parse_sdxl_canny_reference_sources(admitted.command, metadata) != admitted.sources
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
    }


def sdxl_canny_reference_input_hashes(
    prepared: PreparedSdxlCannyReferenceInputs,
) -> dict[str, str]:
    metadata = {file.member_path: file.payload for file in prepared.files}
    if (
        parse_sdxl_canny_reference_sources(prepared.command, metadata) != prepared.sources
        or prepared.spatial_metadata.command != prepared.sources.spatial_command
        or prepared.spatial_metadata.sources != prepared.sources.spatial_sources
    ):
        raise ValueError("SDXL_CANNY_REFERENCE_HANDOFF_SOURCES_INVALID")
    expected = sdxl_canny_comparison_input_hashes(prepared.spatial_metadata)
    expected.pop("command.json")
    return {
        **expected,
        "command.json": "sha256:"
        + hashlib.sha256(content_json_bytes(prepared.command.model_dump(mode="json"))).hexdigest(),
        "inputs/spatial-command.json": prepared.command.spatial_command.sha256,
        "inputs/spatial-result.json": prepared.command.spatial_result.sha256,
        **{
            entry.case.staged_member_path: entry.case.reference_image.sha256
            for entry in prepared.sources.spatial_sources.parent.cases
        },
    }


def resolve_sdxl_canny_reference_metadata(
    engine: Engine,
    command: LocalImageSdxlCannyReferenceCommand,
) -> ResolvedSdxlCannyReferenceMetadata:
    validate_contract("sdxl-canny-reference-command", command.model_dump(mode="json"))
    command = LocalImageSdxlCannyReferenceCommand.model_validate_json(command.model_dump_json())
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
    sources = parse_sdxl_canny_reference_sources(command, metadata)
    metadata["command.json"] = content_json_bytes(command.model_dump(mode="json"))
    return ResolvedSdxlCannyReferenceMetadata(
        command,
        sources,
        admitted,
        tuple(
            SdxlProbeInputMember(name, "sha256:" + hashlib.sha256(raw).hexdigest(), raw)
            for name, raw in sorted(metadata.items())
        ),
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
    files = [
        file
        for file in materialize_sdxl_canny_comparison_files(engine, admitted)
        if file.member_path != "command.json"
    ]
    for name in ("inputs/spatial-command.json", "inputs/spatial-result.json"):
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
