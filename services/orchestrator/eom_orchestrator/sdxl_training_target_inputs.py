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
from sqlalchemy import Engine

from eom_orchestrator.control_artifact_resolution import (
    BoundedControlArtifactRead,
    resolve_control_artifact_member,
    resolve_control_artifact_members,
)
from eom_orchestrator.sdxl_probe_inputs import SdxlProbeInputMember, resolve_sdxl_training_sources


@dataclass(frozen=True, slots=True)
class PreparedSdxlTrainingTargetInputs:
    command: LocalImageSdxlTrainingTargetCommand
    sources: SdxlTrainingTargetSources
    files: tuple[SdxlProbeInputMember, ...]


def sdxl_training_target_input_hashes(
    command: LocalImageSdxlTrainingTargetCommand,
    sources: SdxlTrainingTargetSources,
) -> dict[str, str]:
    prepared_ids = {
        decision.sample_id for decision in command.decisions if decision.disposition == "PREPARE"
    }
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
    command: LocalImageSdxlTrainingTargetCommand,
) -> PreparedSdxlTrainingTargetInputs:
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
