"""Admit all pinned SDXL TRAIN sources before one bounded local handoff."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from eom_image_contracts import (
    LocalImageSdxlLoraMicroCommand,
    content_json_bytes,
    validate_contract,
    validate_sdxl_lora_micro_sources,
)
from sqlalchemy import Engine

from eom_orchestrator.control_artifact_resolution import resolve_control_artifact_member
from eom_orchestrator.sdxl_probe_inputs import (
    SdxlProbeInputMember,
    resolve_sdxl_training_sources,
)


class SdxlMicroAdmissionError(ValueError):
    """Invalid micro input declaration; no worker dispatch or persistence has occurred."""


@dataclass(frozen=True, slots=True)
class PreparedSdxlMicroInputs:
    command: LocalImageSdxlLoraMicroCommand
    files: tuple[SdxlProbeInputMember, ...]


def prepare_sdxl_micro_inputs(
    engine: Engine, command: LocalImageSdxlLoraMicroCommand
) -> PreparedSdxlMicroInputs:
    validate_contract("sdxl-lora-micro-command", command.model_dump(mode="json"))
    command = LocalImageSdxlLoraMicroCommand.model_validate(command.model_dump(mode="json"))
    sources = resolve_sdxl_training_sources(
        engine,
        crop_set_pointer=command.crop_set,
        authorization_pointer=command.training_authorization,
    )
    try:
        validate_sdxl_lora_micro_sources(command, sources.crop_set)
    except ValueError as exc:
        raise SdxlMicroAdmissionError("SDXL_MICRO_SOURCE_LINEAGE_INVALID") from exc
    members = {member.sample_id: member for member in sources.crop_set.members}
    for sample in command.training_samples:
        if (
            sample.source_image.artifact_id != command.crop_set.artifact_id
            or sample.source_image.artifact_revision_id != command.crop_set.artifact_revision_id
            or members[sample.sample_id].size_bytes > 16 * 1024**2
        ):
            raise SdxlMicroAdmissionError("SDXL_MICRO_REFERENCE_SOURCE_INVALID")
    files = []
    for sample in command.training_samples:
        member = members[sample.sample_id]
        raw = resolve_control_artifact_member(
            engine, sample.source_image, maximum_bytes=member.size_bytes
        )
        if len(raw) != member.size_bytes:
            raise SdxlMicroAdmissionError("SDXL_MICRO_REFERENCE_SIZE_INVALID")
        files.append(SdxlProbeInputMember(sample.staged_member_path, member.sha256, raw))
    for path, payload in (
        ("command.json", content_json_bytes(command.model_dump(mode="json"))),
        ("inputs/crop-set.json", sources.crop_set_payload),
        ("inputs/authorization.json", sources.authorization_payload),
    ):
        if len(payload) > 2 * 1024**2:
            raise SdxlMicroAdmissionError("SDXL_MICRO_METADATA_SIZE_INVALID")
        files.append(
            SdxlProbeInputMember(path, "sha256:" + hashlib.sha256(payload).hexdigest(), payload)
        )
    return PreparedSdxlMicroInputs(
        command, tuple(sorted(files, key=lambda member: member.member_path))
    )
