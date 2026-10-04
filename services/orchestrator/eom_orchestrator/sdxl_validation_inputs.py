"""Metadata-first reserved comparison admission; no TRAIN/HOLDOUT image fallback."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from eom_image_contracts.models import ImageEvaluationArtifactMember, content_json_bytes
from eom_image_contracts.sdxl_canny_reference import LocalImageSdxlCannyReferenceCommand
from eom_image_contracts.sdxl_validation_comparison import (
    LocalImageSdxlValidationComparisonCommand,
    SdxlValidationComparisonSources,
    parse_sdxl_validation_configuration,
    parse_sdxl_validation_crop_source,
    validate_sdxl_validation_sources,
)
from eom_image_contracts.validation import validate_contract
from sqlalchemy import Engine

from eom_orchestrator.control_artifact_resolution import (
    BoundedControlArtifactRead,
    resolve_control_artifact_member,
    resolve_control_artifact_members,
)
from eom_orchestrator.sdxl_canny_reference_inputs import (
    ResolvedSdxlCannyReferenceMetadata,
    resolve_sdxl_canny_reference_metadata,
    sdxl_canny_reference_metadata_hashes,
)
from eom_orchestrator.sdxl_probe_inputs import SdxlProbeInputMember
from eom_orchestrator.source_page_crop_inputs import prepare_source_page_crop_reads


@dataclass(frozen=True, slots=True)
class ResolvedSdxlValidationMetadata:
    command: LocalImageSdxlValidationComparisonCommand
    sources: SdxlValidationComparisonSources
    configuration_metadata: ResolvedSdxlCannyReferenceMetadata
    files: tuple[SdxlProbeInputMember, ...]


@dataclass(frozen=True, slots=True)
class PreparedSdxlValidationInputs:
    metadata: ResolvedSdxlValidationMetadata
    files: tuple[SdxlProbeInputMember, ...]

    @property
    def command(self) -> LocalImageSdxlValidationComparisonCommand:
        return self.metadata.command


def resolve_sdxl_validation_metadata(
    engine: Engine, command: LocalImageSdxlValidationComparisonCommand
) -> ResolvedSdxlValidationMetadata:
    validate_contract("sdxl-validation-comparison-command", command.model_dump(mode="json"))
    command = LocalImageSdxlValidationComparisonCommand.model_validate_json(
        command.model_dump_json()
    )
    anchor_raw = resolve_control_artifact_member(
        engine, command.configuration_anchor, maximum_bytes=256 * 1024
    )
    anchor = LocalImageSdxlCannyReferenceCommand.model_validate_json(anchor_raw)
    configuration_metadata = resolve_sdxl_canny_reference_metadata(engine, anchor)
    inherited = {
        file.member_path: file.payload
        for file in configuration_metadata.files
        if file.member_path != "command.json"
    }
    configuration = parse_sdxl_validation_configuration(command, anchor_raw, inherited)
    metadata = {**inherited, "inputs/configuration-command.json": anchor_raw}
    crop_sources = []
    for index, pin in enumerate(command.crop_sources):
        review_raw = resolve_control_artifact_member(engine, pin.review, maximum_bytes=2 * 1024**2)
        crop_set_raw = resolve_control_artifact_member(
            engine, pin.crop_set, maximum_bytes=2 * 1024**2
        )
        source = parse_sdxl_validation_crop_source(
            pin, review_raw=review_raw, crop_set_raw=crop_set_raw
        )
        # This existing owner checks full original/supplemental lineage; returned page
        # reads are intentionally not executed. Only reviewed literal crop PNGs follow.
        prepare_source_page_crop_reads(engine, source.review)
        crop_sources.append(source)
        metadata[f"inputs/validation-sources/{index}/review.json"] = review_raw
        metadata[f"inputs/validation-sources/{index}/crop-set.json"] = crop_set_raw
    sources = SdxlValidationComparisonSources(configuration, tuple(crop_sources))
    validate_sdxl_validation_sources(command, sources)
    metadata["command.json"] = content_json_bytes(command.model_dump(mode="json"))
    return ResolvedSdxlValidationMetadata(
        command,
        sources,
        configuration_metadata,
        tuple(
            SdxlProbeInputMember(name, "sha256:" + hashlib.sha256(raw).hexdigest(), raw)
            for name, raw in sorted(metadata.items())
        ),
    )


def sdxl_validation_metadata_hashes(admitted: ResolvedSdxlValidationMetadata) -> dict[str, str]:
    command = admitted.command
    metadata = {file.member_path: file.payload for file in admitted.files}
    configuration = parse_sdxl_validation_configuration(
        command, metadata["inputs/configuration-command.json"], metadata
    )
    crops = tuple(
        parse_sdxl_validation_crop_source(
            pin,
            review_raw=metadata[f"inputs/validation-sources/{index}/review.json"],
            crop_set_raw=metadata[f"inputs/validation-sources/{index}/crop-set.json"],
        )
        for index, pin in enumerate(command.crop_sources)
    )
    parsed = SdxlValidationComparisonSources(configuration, crops)
    validate_sdxl_validation_sources(command, parsed)
    if (
        parsed != admitted.sources
        or configuration.sources != admitted.configuration_metadata.sources
    ):
        raise ValueError("SDXL_VALIDATION_HANDOFF_SOURCES_INVALID")
    expected = sdxl_canny_reference_metadata_hashes(admitted.configuration_metadata)
    expected.pop("command.json")
    expected.update(
        {
            "command.json": "sha256:"
            + hashlib.sha256(content_json_bytes(command.model_dump(mode="json"))).hexdigest(),
            "inputs/configuration-command.json": command.configuration_anchor.sha256,
        }
    )
    for index, source in enumerate(command.crop_sources):
        expected[f"inputs/validation-sources/{index}/review.json"] = source.review.sha256
        expected[f"inputs/validation-sources/{index}/crop-set.json"] = source.crop_set.sha256
    return expected


def sdxl_validation_input_hashes(prepared: PreparedSdxlValidationInputs) -> dict[str, str]:
    expected = sdxl_validation_metadata_hashes(prepared.metadata)
    sources = prepared.metadata.sources
    pin = sources.configuration.sources.spatial_sources.targets.evaluation.evaluation
    expected.update(
        {
            entry.case.staged_member_path: entry.case.reference_image.sha256
            for entry in prepared.command.cases
        }
    )
    expected.update(
        {
            "inputs/adapter/" + file.relative_path: file.sha256
            for file in sources.configuration.sources.spatial_sources.targets.lora.manifest.files
        }
    )
    if pin.training_result.artifact_revision_id != pin.adapter_manifest.artifact_revision_id:
        raise ValueError("SDXL_VALIDATION_ADAPTER_REVISION_INVALID")
    return expected


def prepare_sdxl_validation_inputs(
    engine: Engine, command: LocalImageSdxlValidationComparisonCommand
) -> PreparedSdxlValidationInputs:
    admitted = resolve_sdxl_validation_metadata(engine, command)
    members = validate_sdxl_validation_sources(admitted.command, admitted.sources)
    reads = []
    paths = []
    for entry, (_, member) in zip(admitted.command.cases, members, strict=True):
        reads.append(BoundedControlArtifactRead(entry.case.reference_image, member.size_bytes))
        paths.append(entry.case.staged_member_path)
    spatial = admitted.sources.configuration.sources.spatial_sources
    pin = spatial.targets.evaluation.evaluation
    for file in spatial.targets.lora.manifest.files:
        bound = 64 * 1024 if file.relative_path.endswith(".json") else 64 * 1024**2
        if not 0 < file.size_bytes <= bound:
            raise ValueError("SDXL_VALIDATION_ADAPTER_SIZE_INVALID")
        pointer = ImageEvaluationArtifactMember(
            artifact_id=pin.training_result.artifact_id,
            artifact_revision_id=pin.training_result.artifact_revision_id,
            member_path="adapter/" + file.relative_path,
            schema_ref="eom://schemas/image-provider/local-image-lora-adapter-file/1.0",
            media_type="application/json"
            if file.relative_path.endswith(".json")
            else "application/octet-stream",
            sha256=file.sha256,
        )
        reads.append(BoundedControlArtifactRead(pointer, file.size_bytes))
        paths.append("inputs/adapter/" + file.relative_path)
    # Every source and all selected cases have passed before the first binary read.
    payloads = resolve_control_artifact_members(engine, tuple(reads))
    files = list(admitted.files)
    for name, read, raw in zip(paths, reads, payloads, strict=True):
        if len(raw) != read.maximum_bytes:
            raise ValueError("SDXL_VALIDATION_INPUT_SIZE_INVALID")
        files.append(SdxlProbeInputMember(name, read.pointer.sha256, raw))
    return PreparedSdxlValidationInputs(
        admitted, tuple(sorted(files, key=lambda file: file.member_path))
    )
