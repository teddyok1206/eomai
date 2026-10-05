"""Metadata-only preparation; no photograph/weight materialization or dispatch."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from eom_image_contracts.models import content_json_bytes
from eom_image_contracts.sdxl_native_canny_reference import (
    SdxlNativeCannyReferenceSources,
    parse_reference_command,
)
from eom_image_contracts.sdxl_photo_style import (
    LocalImageSdxlPhotoStylePlan,
    SdxlPhotoStyleSource,
    parse_photo_style_bundle,
    parse_photo_style_source,
    photo_style_artifact_pointer,
    validate_photo_style_sources,
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
)
from eom_orchestrator.sdxl_probe_inputs import SdxlProbeInputMember


@dataclass(frozen=True, slots=True)
class ResolvedSdxlPhotoStyleMetadata:
    plan: LocalImageSdxlPhotoStylePlan
    configuration: ResolvedSdxlCannyReferenceMetadata
    sources: tuple[SdxlPhotoStyleSource, ...]
    files: tuple[SdxlProbeInputMember, ...]


def resolve_sdxl_photo_style_metadata(
    engine: Engine, plan: LocalImageSdxlPhotoStylePlan
) -> ResolvedSdxlPhotoStyleMetadata:
    """Re-admit configuration and licensed sources before any binary input can be read."""
    value = plan.model_dump(mode="json")
    validate_contract("sdxl-photo-style-plan", value)
    plan = LocalImageSdxlPhotoStylePlan.model_validate(value)
    anchor_raw = resolve_control_artifact_member(
        engine, plan.configuration_anchor, maximum_bytes=256 * 1024
    )
    if content_json_bytes(json.loads(anchor_raw)) != anchor_raw:
        raise ValueError("PHOTO_STYLE_CONFIGURATION_NONCANONICAL")
    anchor = parse_reference_command(json.loads(anchor_raw))
    admitted = resolve_sdxl_canny_reference_metadata(engine, anchor)
    if (
        not isinstance(admitted.sources, SdxlNativeCannyReferenceSources)
        or admitted.native_admission is None
        or plan.created_at < anchor.created_at
        or plan.seed != admitted.sources.spatial_sources.parent.seed
    ):
        raise ValueError("PHOTO_STYLE_NATIVE_CONFIGURATION_MISMATCH")
    # Two bounded batched reads, not per-case DB queries or binary opening.
    references = tuple(row.visual_reference for row in plan.cases)
    bundle_raws = resolve_control_artifact_members(
        engine,
        tuple(
            BoundedControlArtifactRead(
                photo_style_artifact_pointer(ref.bundle_manifest), ref.bundle_manifest.size_bytes
            )
            for ref in references
        ),
    )
    bundles = tuple(
        parse_photo_style_bundle(ref, raw) for ref, raw in zip(references, bundle_raws, strict=True)
    )
    intent_pointers = tuple(dict.fromkeys(bundle.intent for bundle in bundles))
    raw_intents = resolve_control_artifact_members(
        engine,
        tuple(
            BoundedControlArtifactRead(photo_style_artifact_pointer(pin), pin.size_bytes)
            for pin in intent_pointers
        ),
    )
    intents = dict(zip(intent_pointers, raw_intents, strict=True))
    sources = tuple(
        parse_photo_style_source(ref, bundle_raw=raw, intent_raw=intents[bundle.intent])
        for ref, raw, bundle in zip(references, bundle_raws, bundles, strict=True)
    )
    native = admitted.native_admission
    training_hashes = frozenset(
        member.sha256
        for batch in native.sources.batches
        for member in batch.sources.crop_set.members
    ) | frozenset(target.sha256 for target in native.sources.targets)
    validate_photo_style_sources(plan, sources, training_image_hashes=training_hashes)
    # This immutable handoff carries the already admitted metadata, not another
    # canonical traversal or any duplicated image/adapter binary.
    metadata = {
        member.member_path: member.payload
        for member in admitted.files
        if member.member_path != "command.json"
    }
    metadata.update({member.member_path: member.payload for member in native.metadata})
    metadata["inputs/configuration-command.json"] = anchor_raw
    metadata["plan.json"] = content_json_bytes(plan.model_dump(mode="json"))
    for entry, raw, bundle in zip(plan.cases, bundle_raws, bundles, strict=True):
        prefix = "inputs/photo-sources/" + entry.case.case_id + "/"
        metadata[prefix + "bundle.json"] = raw
        metadata[prefix + "intent.json"] = intents[bundle.intent]
    return ResolvedSdxlPhotoStyleMetadata(
        plan,
        admitted,
        sources,
        tuple(
            SdxlProbeInputMember(path, "sha256:" + hashlib.sha256(raw).hexdigest(), raw)
            for path, raw in sorted(metadata.items())
        ),
    )
