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
from eom_image_contracts.sdxl_reviewed_micro import (
    LocalImageSdxlReviewedMicroCommand,
    parse_sdxl_reviewed_micro_sources,
    sdxl_reviewed_micro_metadata_pointers,
)
from eom_image_contracts.sdxl_source_training_targets import SdxlPreparedSourceTrainingTarget
from eom_image_contracts.source_page_crops import (
    LocalImageScienceSourcePageCropReview,
    LocalImageScienceSourcePageCropReviewV2,
)
from sqlalchemy import Engine

from eom_orchestrator.control_artifact_resolution import (
    BoundedControlArtifactRead,
    resolve_control_artifact_member,
    resolve_control_artifact_members,
)
from eom_orchestrator.sdxl_probe_inputs import (
    SdxlProbeInputMember,
    resolve_sdxl_training_sources,
)
from eom_orchestrator.source_page_crop_inputs import prepare_source_page_crop_reads


class SdxlMicroAdmissionError(ValueError):
    """Invalid micro input declaration; no worker dispatch or persistence has occurred."""


@dataclass(frozen=True, slots=True)
class PreparedSdxlMicroInputs:
    command: LocalImageSdxlLoraMicroCommand | LocalImageSdxlReviewedMicroCommand
    files: tuple[SdxlProbeInputMember, ...]


def prepare_sdxl_micro_inputs(
    engine: Engine, command: LocalImageSdxlLoraMicroCommand | LocalImageSdxlReviewedMicroCommand
) -> PreparedSdxlMicroInputs:
    if isinstance(command, LocalImageSdxlReviewedMicroCommand):
        return _prepare_reviewed_inputs(engine, command)
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


def _prepare_reviewed_inputs(
    engine: Engine,
    command: LocalImageSdxlReviewedMicroCommand,
) -> PreparedSdxlMicroInputs:
    sources = resolve_sdxl_reviewed_micro_sources(engine, command)
    command = sources.command
    targets = {target.sample_id: target for target in sources.targets}
    reads = tuple(
        BoundedControlArtifactRead(sample.source_image, targets[sample.sample_id].size_bytes)
        for sample in command.training_samples
    )
    if any(not 0 < read.maximum_bytes <= 16 * 1024**2 for read in reads):
        raise SdxlMicroAdmissionError("SDXL_MICRO_REFERENCE_SIZE_INVALID")
    pixels = resolve_control_artifact_members(engine, reads)
    files = []
    for sample, read, raw in zip(command.training_samples, reads, pixels, strict=True):
        if len(raw) != read.maximum_bytes:
            raise SdxlMicroAdmissionError("SDXL_MICRO_REFERENCE_SIZE_INVALID")
        files.append(
            SdxlProbeInputMember(sample.staged_member_path, sample.source_image.sha256, raw)
        )
    files.extend(sources.metadata)
    raw_command = content_json_bytes(command.model_dump(mode="json"))
    files.append(
        SdxlProbeInputMember(
            "command.json", "sha256:" + hashlib.sha256(raw_command).hexdigest(), raw_command
        )
    )
    return PreparedSdxlMicroInputs(command, tuple(sorted(files, key=lambda file: file.member_path)))


def sdxl_micro_input_hashes(prepared: PreparedSdxlMicroInputs) -> dict[str, str]:
    """Derive exact handoff closure rather than trusting arbitrary caller-supplied members."""
    command = prepared.command
    payload = content_json_bytes(command.model_dump(mode="json"))
    expected = {
        "command.json": "sha256:" + hashlib.sha256(payload).hexdigest(),
        "inputs/authorization.json": command.training_authorization.sha256,
        **{
            sample.staged_member_path: sample.source_image.sha256
            for sample in command.training_samples
        },
    }
    if isinstance(command, LocalImageSdxlReviewedMicroCommand):
        files = {file.member_path: file.payload for file in prepared.files}
        try:
            pointers = sdxl_reviewed_micro_metadata_pointers(
                command, files["inputs/source-crop-set.json"]
            )
            parse_sdxl_reviewed_micro_sources(command, files)
        except (KeyError, ValueError) as exc:
            raise SdxlMicroAdmissionError("SDXL_MICRO_SOURCE_LINEAGE_INVALID") from exc
        expected.update({name: pointer.sha256 for name, pointer in pointers.items()})
    else:
        expected["inputs/crop-set.json"] = command.crop_set.sha256
    return expected


@dataclass(frozen=True, slots=True)
class AdmittedSdxlReviewedMicroSources:
    command: LocalImageSdxlReviewedMicroCommand
    metadata: tuple[SdxlProbeInputMember, ...]
    targets: tuple[SdxlPreparedSourceTrainingTarget, ...]


def resolve_sdxl_reviewed_micro_sources(
    engine: Engine, command: LocalImageSdxlReviewedMicroCommand
) -> AdmittedSdxlReviewedMicroSources:
    """Read metadata and full lineage only; evaluation does not copy training PNGs."""
    validate_contract("sdxl-lora-micro-command-v2", command.model_dump(mode="json"))
    command = LocalImageSdxlReviewedMicroCommand.model_validate(command.model_dump(mode="json"))
    crop_raw = resolve_control_artifact_member(
        engine, command.source_crop_set, maximum_bytes=2 * 1024**2
    )
    pointers = sdxl_reviewed_micro_metadata_pointers(command, crop_raw)
    others = tuple(
        (name, pointer)
        for name, pointer in pointers.items()
        if name != "inputs/source-crop-set.json"
    )
    payloads = resolve_control_artifact_members(
        engine, tuple(BoundedControlArtifactRead(pointer, 2 * 1024**2) for _, pointer in others)
    )
    metadata = {
        "inputs/source-crop-set.json": crop_raw,
        **{name: raw for (name, _), raw in zip(others, payloads, strict=True)},
    }
    selected = parse_sdxl_reviewed_micro_sources(command, metadata)
    # Full approved PDF/discovery/partition lineage admission before any target PNG read.
    review_model = (
        LocalImageScienceSourcePageCropReviewV2
        if pointers["inputs/source-review.json"].schema_ref.endswith("/1.1")
        else LocalImageScienceSourcePageCropReview
    )
    prepare_source_page_crop_reads(
        engine, review_model.model_validate_json(metadata["inputs/source-review.json"])
    )
    return AdmittedSdxlReviewedMicroSources(
        command,
        tuple(
            SdxlProbeInputMember(name, "sha256:" + hashlib.sha256(raw).hexdigest(), raw)
            for name, raw in sorted(metadata.items())
        ),
        tuple(selected[sample.sample_id] for sample in command.training_samples),
    )
