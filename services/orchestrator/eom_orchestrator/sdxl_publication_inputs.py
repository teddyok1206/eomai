"""Admit pinned comparison history once, then only its native PNGs for CPU publication."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from eom_image_contracts.models import content_json_bytes
from eom_image_contracts.sdxl_publication_comparison import (
    LocalImageSdxlPublicationComparisonCommand,
    SdxlPublicationSources,
    parse_sdxl_publication_sources,
    sdxl_publication_member,
    sdxl_publication_source_pointer,
    validate_sdxl_publication_sources,
)
from eom_image_contracts.sdxl_target_comparison import (
    LocalImageSdxlTargetComparisonCommand,
    LocalImageSdxlTargetComparisonResult,
)
from eom_image_contracts.validation import validate_contract
from sqlalchemy import Engine

from eom_orchestrator.control_artifact_resolution import (
    BoundedControlArtifactRead,
    resolve_control_artifact_members,
)
from eom_orchestrator.sdxl_probe_inputs import SdxlProbeInputMember
from eom_orchestrator.sdxl_target_comparison_inputs import (
    ResolvedSdxlTargetComparisonMetadata,
    resolve_sdxl_target_comparison_metadata,
    sdxl_target_comparison_metadata_hashes,
)


@dataclass(frozen=True, slots=True)
class PreparedSdxlPublicationInputs:
    command: LocalImageSdxlPublicationComparisonCommand
    sources: SdxlPublicationSources
    source_metadata: ResolvedSdxlTargetComparisonMetadata
    files: tuple[SdxlProbeInputMember, ...]


def sdxl_publication_input_hashes(prepared: PreparedSdxlPublicationInputs) -> dict[str, str]:
    metadata = {file.member_path: file.payload for file in prepared.files}
    sources = parse_sdxl_publication_sources(prepared.command, metadata)
    if sources != prepared.sources:
        raise ValueError("SDXL_PUBLICATION_HANDOFF_SOURCES_INVALID")
    expected = sdxl_target_comparison_metadata_hashes(prepared.source_metadata)
    expected.pop("command.json")
    return {
        **expected,
        "inputs/parent-command.json": prepared.command.source_command.sha256,
        "inputs/parent-result.json": prepared.command.source_result.sha256,
        "command.json": "sha256:"
        + hashlib.sha256(content_json_bytes(prepared.command.model_dump(mode="json"))).hexdigest(),
        **{
            sdxl_publication_member(output, staged=True): output.sha256
            for output in sources.result.outputs
        },
    }


def prepare_sdxl_publication_inputs(
    engine: Engine, command: LocalImageSdxlPublicationComparisonCommand
) -> PreparedSdxlPublicationInputs:
    validate_contract("sdxl-publication-comparison-command", command.model_dump(mode="json"))
    command = LocalImageSdxlPublicationComparisonCommand.model_validate_json(
        command.model_dump_json()
    )
    raw_command, raw_result = resolve_control_artifact_members(
        engine,
        (
            BoundedControlArtifactRead(command.source_command, 256 * 1024),
            BoundedControlArtifactRead(command.source_result, 256 * 1024),
        ),
    )
    parent_command = LocalImageSdxlTargetComparisonCommand.model_validate_json(raw_command)
    parent_result = LocalImageSdxlTargetComparisonResult.model_validate_json(raw_result)
    for kind, raw, parent in (
        ("command", raw_command, parent_command),
        ("result", raw_result, parent_result),
    ):
        validate_contract(f"sdxl-target-comparison-{kind}", parent.model_dump(mode="json"))
        if raw != content_json_bytes(parent.model_dump(mode="json")):
            raise ValueError("SDXL_PUBLICATION_PARENT_METADATA_INVALID")
    admitted = resolve_sdxl_target_comparison_metadata(engine, parent_command)
    sources = SdxlPublicationSources(parent_command, parent_result, admitted.sources)
    validate_sdxl_publication_sources(command, sources)
    reads = tuple(
        BoundedControlArtifactRead(
            sdxl_publication_source_pointer(command, output), output.size_bytes
        )
        for output in parent_result.outputs
    )
    payloads = resolve_control_artifact_members(engine, reads)
    files = [file for file in admitted.files if file.member_path != "command.json"]
    for name, raw in (
        ("command.json", content_json_bytes(command.model_dump(mode="json"))),
        ("inputs/parent-command.json", raw_command),
        ("inputs/parent-result.json", raw_result),
    ):
        files.append(SdxlProbeInputMember(name, "sha256:" + hashlib.sha256(raw).hexdigest(), raw))
    for output, pixels in zip(parent_result.outputs, payloads, strict=True):
        if len(pixels) != output.size_bytes:
            raise ValueError("SDXL_PUBLICATION_NATIVE_SIZE_INVALID")
        files.append(
            SdxlProbeInputMember(
                sdxl_publication_member(output, staged=True), output.sha256, pixels
            )
        )
    return PreparedSdxlPublicationInputs(
        command, sources, admitted, tuple(sorted(files, key=lambda file: file.member_path))
    )
