"""Admit immutable historical sources, then batch only reviewed PREPARE input PNGs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from eom_image_contracts import (
    LocalImageSdxlLoraMicroCommand,
    LocalImageSdxlTrainingTargetCommand,
    SdxlTrainingTargetSources,
    content_json_bytes,
    parse_sdxl_training_target_sources,
    validate_contract,
)
from eom_image_contracts.sdxl_native_training_targets import (
    LocalImageSdxlNativeTrainingTargetCommand,
    SdxlNativeTrainingTargetSources,
    parse_sdxl_native_training_target_sources,
)
from eom_image_contracts.sdxl_source_training_targets import (
    LocalImageSdxlSourceTrainingTargetCommand,
    SdxlSourceTrainingTargetSources,
    parse_sdxl_source_training_target_sources,
)
from eom_image_contracts.source_page_crops import (
    SOURCE_PAGE_CROP_SET_V2_SCHEMA_REF,
    LocalImageScienceSourcePageCropSet,
    LocalImageScienceSourcePageCropSetV2,
)
from eom_image_contracts.source_pdf_crops import (
    LocalImageScienceSourcePdfCropCommand,
    LocalImageScienceSourcePdfCropSet,
)
from sqlalchemy import Engine

from eom_orchestrator.control_artifact_resolution import (
    BoundedControlArtifactRead,
    resolve_control_artifact_member,
    resolve_control_artifact_members,
)
from eom_orchestrator.sdxl_probe_inputs import SdxlProbeInputMember, resolve_sdxl_training_sources
from eom_orchestrator.source_page_crop_inputs import prepare_source_page_crop_reads
from eom_orchestrator.source_pdf_crop_inputs import prepare_source_pdf_crop_reads

TrainingTargetCommand = (
    LocalImageSdxlTrainingTargetCommand
    | LocalImageSdxlSourceTrainingTargetCommand
    | LocalImageSdxlNativeTrainingTargetCommand
)
TrainingTargetSources = (
    SdxlTrainingTargetSources | SdxlSourceTrainingTargetSources | SdxlNativeTrainingTargetSources
)


@dataclass(frozen=True, slots=True)
class PreparedSdxlTrainingTargetInputs:
    command: TrainingTargetCommand
    sources: TrainingTargetSources
    files: tuple[SdxlProbeInputMember, ...]


def sdxl_training_target_input_hashes(
    command: TrainingTargetCommand,
    sources: TrainingTargetSources,
) -> dict[str, str]:
    prepared_ids = {
        decision.sample_id for decision in command.decisions if decision.disposition == "PREPARE"
    }
    if isinstance(command, LocalImageSdxlNativeTrainingTargetCommand):
        if not isinstance(sources, SdxlNativeTrainingTargetSources):
            raise ValueError("SDXL_TARGET_SOURCE_PROTOCOL_MISMATCH")
        return {
            "command.json": "sha256:"
            + hashlib.sha256(content_json_bytes(command.model_dump(mode="json"))).hexdigest(),
            "inputs/source-crop-set.json": command.source_crop_set.sha256,
            "inputs/native-crop-command.json": sources.crop_set.command.sha256,
            "inputs/source-review.json": sources.source_command.source_review.sha256,
            "inputs/authorization.json": command.training_authorization.sha256,
            **{
                sample.staged_member_path: sample.source_image.sha256
                for sample in sources.samples
                if sample.sample_id in prepared_ids
            },
        }
    if isinstance(command, LocalImageSdxlSourceTrainingTargetCommand):
        if not isinstance(sources, SdxlSourceTrainingTargetSources):
            raise ValueError("SDXL_TARGET_SOURCE_PROTOCOL_MISMATCH")
        return {
            "command.json": "sha256:"
            + hashlib.sha256(content_json_bytes(command.model_dump(mode="json"))).hexdigest(),
            "inputs/source-crop-set.json": command.source_crop_set.sha256,
            "inputs/source-review.json": sources.crop_set.review.sha256,
            "inputs/authorization.json": command.training_authorization.sha256,
            **{
                sample.staged_member_path: sample.source_image.sha256
                for sample in sources.samples
                if sample.sample_id in prepared_ids
            },
        }
    if not isinstance(sources, SdxlTrainingTargetSources):
        raise ValueError("SDXL_TARGET_SOURCE_PROTOCOL_MISMATCH")
    return {
        "command.json": "sha256:"
        + hashlib.sha256(content_json_bytes(command.model_dump(mode="json"))).hexdigest(),
        "inputs/training-command.json": command.original_training_command.sha256,
        "inputs/training-result.json": command.original_training_result.sha256,
        "inputs/crop-set.json": sources.training_command.crop_set.sha256,
        "inputs/authorization.json": sources.training_command.training_authorization.sha256,
        **{
            sample.staged_member_path: sample.source_image.sha256
            for sample in sources.training_command.training_samples
            if sample.sample_id in prepared_ids
        },
    }


def prepare_sdxl_training_target_inputs(
    engine: Engine,
    command: TrainingTargetCommand,
) -> PreparedSdxlTrainingTargetInputs:
    if isinstance(command, LocalImageSdxlNativeTrainingTargetCommand):
        return _prepare_native_source_inputs(engine, command)
    if isinstance(command, LocalImageSdxlSourceTrainingTargetCommand):
        return _prepare_literal_source_inputs(engine, command)
    validate_contract("sdxl-training-target-command", command.model_dump(mode="json"))
    command = LocalImageSdxlTrainingTargetCommand.model_validate(command.model_dump(mode="json"))
    original_raw = resolve_control_artifact_member(
        engine, command.original_training_command, maximum_bytes=2 * 1024**2
    )
    validate_contract("sdxl-lora-micro-command", json.loads(original_raw))
    original = LocalImageSdxlLoraMicroCommand.model_validate_json(original_raw)
    result_raw = resolve_control_artifact_member(
        engine, command.original_training_result, maximum_bytes=2 * 1024**2
    )
    lineage = resolve_sdxl_training_sources(
        engine,
        crop_set_pointer=original.crop_set,
        authorization_pointer=original.training_authorization,
    )
    sources = parse_sdxl_training_target_sources(
        command,
        training_command_payload=original_raw,
        training_result_payload=result_raw,
        crop_set_payload=lineage.crop_set_payload,
        authorization_payload=lineage.authorization_payload,
    )
    members = {member.sample_id: member for member in sources.crop_set.members}
    prepared_ids = {
        decision.sample_id for decision in command.decisions if decision.disposition == "PREPARE"
    }
    samples = tuple(
        sample for sample in original.training_samples if sample.sample_id in prepared_ids
    )
    for sample in samples:
        if (
            sample.source_image.artifact_id != original.crop_set.artifact_id
            or sample.source_image.artifact_revision_id != original.crop_set.artifact_revision_id
            or members[sample.sample_id].size_bytes > 16 * 1024**2
        ):
            raise ValueError("SDXL_TARGET_SOURCE_POINTER_INVALID")
    bounded = tuple(
        BoundedControlArtifactRead(sample.source_image, members[sample.sample_id].size_bytes)
        for sample in samples
    )
    payloads = resolve_control_artifact_members(engine, bounded)
    files = []
    for sample, read, raw in zip(samples, bounded, payloads, strict=True):
        if len(raw) != read.maximum_bytes:
            raise ValueError("SDXL_TARGET_SOURCE_SIZE_INVALID")
        files.append(
            SdxlProbeInputMember(sample.staged_member_path, sample.source_image.sha256, raw)
        )
    for path, raw in (
        ("command.json", content_json_bytes(command.model_dump(mode="json"))),
        ("inputs/training-command.json", original_raw),
        ("inputs/training-result.json", result_raw),
        ("inputs/crop-set.json", lineage.crop_set_payload),
        ("inputs/authorization.json", lineage.authorization_payload),
    ):
        files.append(SdxlProbeInputMember(path, "sha256:" + hashlib.sha256(raw).hexdigest(), raw))
    return PreparedSdxlTrainingTargetInputs(
        command, sources, tuple(sorted(files, key=lambda file: file.member_path))
    )


def _prepare_native_source_inputs(
    engine: Engine, command: LocalImageSdxlNativeTrainingTargetCommand
) -> PreparedSdxlTrainingTargetInputs:
    """Full source admission first; no PDF/page/deferred PNG read or substituted revision."""
    validate_contract("sdxl-training-target-command-v3", command.model_dump(mode="json"))
    command = LocalImageSdxlNativeTrainingTargetCommand.model_validate(
        command.model_dump(mode="json")
    )
    crop_raw = resolve_control_artifact_member(
        engine, command.source_crop_set, maximum_bytes=2 * 1024**2
    )
    crop_set = LocalImageScienceSourcePdfCropSet.model_validate_json(crop_raw)
    source_command_raw = resolve_control_artifact_member(
        engine, crop_set.command, maximum_bytes=128 * 1024
    )
    source_command = LocalImageScienceSourcePdfCropCommand.model_validate_json(source_command_raw)
    review_raw = resolve_control_artifact_member(
        engine, source_command.source_review, maximum_bytes=2 * 1024**2
    )
    auth_raw = resolve_control_artifact_member(
        engine, command.training_authorization, maximum_bytes=2 * 1024**2
    )
    sources = parse_sdxl_native_training_target_sources(
        command,
        crop_set_payload=crop_raw,
        source_command_payload=source_command_raw,
        review_payload=review_raw,
        authorization_payload=auth_raw,
    )
    prepare_source_pdf_crop_reads(engine, sources.source_command)
    prepared_ids = {d.sample_id for d in command.decisions if d.disposition == "PREPARE"}
    samples = tuple(sample for sample in sources.samples if sample.sample_id in prepared_ids)
    reads = tuple(
        BoundedControlArtifactRead(sample.source_image, sample.size_bytes) for sample in samples
    )
    payloads = resolve_control_artifact_members(engine, reads)
    files = []
    for sample, raw in zip(samples, payloads, strict=True):
        if len(raw) != sample.size_bytes:
            raise ValueError("SDXL_TARGET_SOURCE_SIZE_INVALID")
        files.append(
            SdxlProbeInputMember(sample.staged_member_path, sample.source_image.sha256, raw)
        )
    for path, raw in (
        ("command.json", content_json_bytes(command.model_dump(mode="json"))),
        ("inputs/source-crop-set.json", crop_raw),
        ("inputs/native-crop-command.json", source_command_raw),
        ("inputs/source-review.json", review_raw),
        ("inputs/authorization.json", auth_raw),
    ):
        files.append(SdxlProbeInputMember(path, "sha256:" + hashlib.sha256(raw).hexdigest(), raw))
    return PreparedSdxlTrainingTargetInputs(
        command, sources, tuple(sorted(files, key=lambda file: file.member_path))
    )


def _prepare_literal_source_inputs(
    engine: Engine,
    command: LocalImageSdxlSourceTrainingTargetCommand,
) -> PreparedSdxlTrainingTargetInputs:
    validate_contract("sdxl-training-target-command-v2", command.model_dump(mode="json"))
    command = LocalImageSdxlSourceTrainingTargetCommand.model_validate(
        command.model_dump(mode="json")
    )
    crop_raw = resolve_control_artifact_member(
        engine, command.source_crop_set, maximum_bytes=2 * 1024**2
    )
    supplemental = command.source_crop_set.schema_ref == SOURCE_PAGE_CROP_SET_V2_SCHEMA_REF
    validate_contract(
        "science-source-page-crop-set-v2" if supplemental else "science-source-page-crop-set",
        json.loads(crop_raw),
    )
    crop_set = (
        LocalImageScienceSourcePageCropSetV2 if supplemental else LocalImageScienceSourcePageCropSet
    ).model_validate_json(crop_raw)
    review_raw = resolve_control_artifact_member(engine, crop_set.review, maximum_bytes=2 * 1024**2)
    auth_raw = resolve_control_artifact_member(
        engine, command.training_authorization, maximum_bytes=2 * 1024**2
    )
    sources = parse_sdxl_source_training_target_sources(
        command,
        crop_set_payload=crop_raw,
        review_payload=review_raw,
        authorization_payload=auth_raw,
    )
    # Existing admission resolves the original frozen corpus and complete extraction provenance.
    # Only its metadata checks are reused; original page pixels are not materialized here.
    prepare_source_page_crop_reads(engine, sources.review)
    prepared_ids = {
        decision.sample_id for decision in command.decisions if decision.disposition == "PREPARE"
    }
    samples = tuple(sample for sample in sources.samples if sample.sample_id in prepared_ids)
    bounded = tuple(
        BoundedControlArtifactRead(sample.source_image, sample.size_bytes) for sample in samples
    )
    payloads = resolve_control_artifact_members(engine, bounded)
    files = []
    for sample, raw in zip(samples, payloads, strict=True):
        if len(raw) != sample.size_bytes:
            raise ValueError("SDXL_TARGET_SOURCE_SIZE_INVALID")
        files.append(
            SdxlProbeInputMember(sample.staged_member_path, sample.source_image.sha256, raw)
        )
    for path, raw in (
        ("command.json", content_json_bytes(command.model_dump(mode="json"))),
        ("inputs/source-crop-set.json", crop_raw),
        ("inputs/source-review.json", review_raw),
        ("inputs/authorization.json", auth_raw),
    ):
        files.append(SdxlProbeInputMember(path, "sha256:" + hashlib.sha256(raw).hexdigest(), raw))
    return PreparedSdxlTrainingTargetInputs(
        command, sources, tuple(sorted(files, key=lambda file: file.member_path))
    )
