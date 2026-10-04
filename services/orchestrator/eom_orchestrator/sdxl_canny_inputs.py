"""Full immutable TRAIN source admission, then only the selected CPU source PNGs."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from eom_image_contracts.models import content_json_bytes
from eom_image_contracts.sdxl_canny_conditioning import (
    LocalImageSdxlCannyConditioningCommand,
    parse_sdxl_canny_parent,
    validate_sdxl_canny_sources,
)
from eom_image_contracts.sdxl_target_comparison import parse_sdxl_target_comparison_sources
from eom_image_contracts.validation import validate_contract
from sqlalchemy import Engine

from eom_orchestrator.control_artifact_resolution import (
    BoundedControlArtifactRead,
    resolve_control_artifact_member,
    resolve_control_artifact_members,
)
from eom_orchestrator.sdxl_probe_inputs import SdxlProbeInputMember
from eom_orchestrator.sdxl_target_comparison_inputs import (
    ResolvedSdxlTargetComparisonMetadata,
    resolve_sdxl_target_comparison_metadata,
    sdxl_target_comparison_metadata_hashes,
)


@dataclass(frozen=True, slots=True)
class PreparedSdxlCannyInputs:
    command: LocalImageSdxlCannyConditioningCommand
    source_metadata: ResolvedSdxlTargetComparisonMetadata
    files: tuple[SdxlProbeInputMember, ...]


def sdxl_canny_input_hashes(prepared: PreparedSdxlCannyInputs) -> dict[str, str]:
    metadata = {file.member_path: file.payload for file in prepared.files}
    parent = parse_sdxl_canny_parent(prepared.command, metadata["inputs/parent-command.json"])
    sources = parse_sdxl_target_comparison_sources(parent, metadata)
    validate_sdxl_canny_sources(prepared.command, parent, sources)
    if (parent, sources) != (
        prepared.source_metadata.command,
        prepared.source_metadata.sources,
    ):
        raise ValueError("SDXL_CANNY_HANDOFF_SOURCES_INVALID")
    expected = sdxl_target_comparison_metadata_hashes(prepared.source_metadata)
    expected.pop("command.json")
    return {
        **expected,
        "command.json": "sha256:"
        + hashlib.sha256(content_json_bytes(prepared.command.model_dump(mode="json"))).hexdigest(),
        "inputs/parent-command.json": prepared.command.source_command.sha256,
        **{
            entry.case.staged_member_path: entry.case.reference_image.sha256
            for entry in parent.cases
        },
    }


def prepare_sdxl_canny_inputs(
    engine: Engine, command: LocalImageSdxlCannyConditioningCommand
) -> PreparedSdxlCannyInputs:
    validate_contract("sdxl-canny-conditioning-command", command.model_dump(mode="json"))
    command = LocalImageSdxlCannyConditioningCommand.model_validate_json(command.model_dump_json())
    raw = resolve_control_artifact_member(engine, command.source_command, maximum_bytes=256 * 1024)
    parent = parse_sdxl_canny_parent(command, raw)
    admitted = resolve_sdxl_target_comparison_metadata(engine, parent)
    validate_sdxl_canny_sources(command, parent, admitted.sources)
    targets = {target.sample_id: target for target in admitted.sources.targets}
    reads = []
    for entry in parent.cases:
        size = targets[entry.sample_id].size_bytes
        if not 0 < size <= command.budget.maximum_input_png_bytes:
            raise ValueError("SDXL_CANNY_SOURCE_SIZE_INVALID")
        reads.append(BoundedControlArtifactRead(entry.case.reference_image, size))
    pixels = resolve_control_artifact_members(engine, tuple(reads))
    files = [file for file in admitted.files if file.member_path != "command.json"]
    for path, payload in (
        ("command.json", content_json_bytes(command.model_dump(mode="json"))),
        ("inputs/parent-command.json", raw),
    ):
        files.append(
            SdxlProbeInputMember(path, "sha256:" + hashlib.sha256(payload).hexdigest(), payload)
        )
    for entry, read, payload in zip(parent.cases, reads, pixels, strict=True):
        if len(payload) != read.maximum_bytes:
            raise ValueError("SDXL_CANNY_SOURCE_SIZE_INVALID")
        files.append(
            SdxlProbeInputMember(entry.case.staged_member_path, read.pointer.sha256, payload)
        )
    return PreparedSdxlCannyInputs(
        command, admitted, tuple(sorted(files, key=lambda file: file.member_path))
    )
