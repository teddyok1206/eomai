"""Admit native TRAIN metadata and canonical lineage, then stage only selected target PNGs."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from eom_image_contracts import ImageEvaluationArtifactMember, content_json_bytes
from eom_image_contracts.sdxl_native_lora import LocalImageSdxlNativeLoraCommand
from eom_image_contracts.sdxl_native_lora_sources import (
    NATIVE_LORA_MAX_METADATA_BYTES,
    SdxlNativeLoraMetadataAdmission,
    SdxlNativeLoraSources,
    parse_sdxl_native_lora_sources,
    sdxl_native_lora_metadata_member_path,
)
from sqlalchemy import Engine

from eom_orchestrator.control_artifact_resolution import (
    BoundedControlArtifactRead,
    resolve_control_artifact_members,
)
from eom_orchestrator.sdxl_probe_inputs import (
    SdxlProbeInputMember,
    resolve_sdxl_training_sources,
)
from eom_orchestrator.source_page_crop_inputs import resolve_source_page_crop_provenance


@dataclass(frozen=True, slots=True)
class AdmittedSdxlNativeLoraSources:
    command: LocalImageSdxlNativeLoraCommand
    sources: SdxlNativeLoraSources
    metadata: tuple[SdxlProbeInputMember, ...]


@dataclass(frozen=True, slots=True)
class PreparedSdxlNativeLoraInputs:
    command: LocalImageSdxlNativeLoraCommand
    files: tuple[SdxlProbeInputMember, ...]


def resolve_sdxl_native_lora_sources(
    engine: Engine, command: LocalImageSdxlNativeLoraCommand
) -> AdmittedSdxlNativeLoraSources:
    """No PDF/page/target image read while any declaration or frozen lineage is unverified."""
    admission = SdxlNativeLoraMetadataAdmission(command)
    payloads: dict[ImageEvaluationArtifactMember, bytes] = {}
    while pending := admission.pending_pointers():
        raw_members = resolve_control_artifact_members(
            engine,
            tuple(
                BoundedControlArtifactRead(pointer, NATIVE_LORA_MAX_METADATA_BYTES)
                for pointer in pending
            ),
        )
        for pointer, raw in zip(pending, raw_members, strict=True):
            admission.admit(pointer, raw)
            payloads[pointer] = raw
    sources = admission.validated_sources()
    basis = resolve_sdxl_training_sources(
        engine,
        crop_set_pointer=sources.batches[0].sources.review.basis_crop_set,
        authorization_pointer=admission.command.training_authorization,
    )
    verified_reviews = set()
    for batch in sources.batches:
        pointer = batch.sources.source_command.source_review
        if pointer in verified_reviews:
            continue
        # Existing source owner validates original/supplemental frozen corpus and split.
        provenance = resolve_source_page_crop_provenance(engine, batch.sources.review, basis=basis)
        documents = {source.document_id: source for source in provenance.pdf_sources}
        for region in batch.sources.review.selections:
            source = documents.get(region.document_id)
            if source is None or (
                source.pdf != region.source_document
                or source.partition != region.partition
                or source.exam_group_sha256 != region.exam_group_sha256
            ):
                raise ValueError("SDXL_NATIVE_LORA_CANONICAL_SOURCE_PARTITION_MISMATCH")
        verified_reviews.add(pointer)
    return AdmittedSdxlNativeLoraSources(
        admission.command,
        sources,
        tuple(
            SdxlProbeInputMember(sdxl_native_lora_metadata_member_path(p), p.sha256, payloads[p])
            for p in sources.metadata_pointers
        ),
    )


def prepare_sdxl_native_lora_inputs(
    engine: Engine, command: LocalImageSdxlNativeLoraCommand
) -> PreparedSdxlNativeLoraInputs:
    admitted = resolve_sdxl_native_lora_sources(engine, command)
    command, sources = admitted.command, admitted.sources
    reads = tuple(
        BoundedControlArtifactRead(sample.source_image, target.size_bytes)
        for sample, target in zip(command.training_samples, sources.targets, strict=True)
    )
    pixels = resolve_control_artifact_members(engine, reads)
    files = list(admitted.metadata)
    for sample, target, raw in zip(command.training_samples, sources.targets, pixels, strict=True):
        if len(raw) != target.size_bytes:
            raise ValueError("SDXL_NATIVE_LORA_TARGET_SIZE_MISMATCH")
        files.append(
            SdxlProbeInputMember(sample.staged_member_path, sample.source_image.sha256, raw)
        )
    raw_command = content_json_bytes(command.model_dump(mode="json"))
    files.append(
        SdxlProbeInputMember(
            "command.json", "sha256:" + hashlib.sha256(raw_command).hexdigest(), raw_command
        )
    )
    return PreparedSdxlNativeLoraInputs(
        command, tuple(sorted(files, key=lambda member: member.member_path))
    )


def sdxl_native_lora_input_hashes(prepared: PreparedSdxlNativeLoraInputs) -> dict[str, str]:
    """Derive the closed handoff from canonical metadata, never arbitrary caller file hashes."""
    command = prepared.command
    metadata = {
        file.member_path: file.payload
        for file in prepared.files
        if file.member_path.startswith("inputs/metadata/")
    }
    sources = parse_sdxl_native_lora_sources(command, metadata)
    raw_command = content_json_bytes(command.model_dump(mode="json"))
    expected = {
        "command.json": "sha256:" + hashlib.sha256(raw_command).hexdigest(),
        **{sdxl_native_lora_metadata_member_path(p): p.sha256 for p in sources.metadata_pointers},
        **{s.staged_member_path: s.source_image.sha256 for s in command.training_samples},
    }
    paths = tuple(file.member_path for file in prepared.files)
    if len(set(paths)) != len(paths) or set(paths) != expected.keys():
        raise ValueError("SDXL_NATIVE_LORA_STAGED_INPUT_CLOSURE_INVALID")
    if any(file.sha256 != expected[file.member_path] for file in prepared.files):
        raise ValueError("SDXL_NATIVE_LORA_STAGED_INPUT_HASH_DECLARATION_INVALID")
    return expected
