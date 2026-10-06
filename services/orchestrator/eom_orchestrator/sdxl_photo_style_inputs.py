"""Metadata-only preparation; no photograph/weight materialization or dispatch."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from eom_image_contracts.models import ImageEvaluationArtifactMember, content_json_bytes
from eom_image_contracts.photo_object_support import (
    PhotoBaselineReuseDocuments,
    PhotoObjectSupportParentDocuments,
)
from eom_image_contracts.sdxl_native_canny_reference import (
    LocalImageSdxlNativeCannyReferenceCommandV2,
    LocalImageSdxlNativeCannyReferenceCommandV4,
    SdxlNativeCannyReferenceSources,
    parse_reference_command,
    sdxl_reference_adapter,
)
from eom_image_contracts.sdxl_native_lora_sources import (
    parse_sdxl_native_lora_sources,
    sdxl_native_lora_metadata_member_path,
)
from eom_image_contracts.sdxl_photo_baseline_reuse import (
    parse_reused_photo_baseline,
    photo_baseline_reuse_documents,
    photo_baseline_reuse_geometry_member,
    photo_baseline_reuse_metadata_members,
)
from eom_image_contracts.sdxl_photo_object_support_lineage import (
    photo_object_support_metadata_members,
    photo_object_support_parent_documents,
    photo_object_support_pixel_members,
    validate_photo_object_support_lineage,
)
from eom_image_contracts.sdxl_photo_style import (
    LocalImageSdxlPhotoObjectSupportPlan,
    LocalImageSdxlPhotoReusedBaselinePlan,
    LocalImageSdxlPhotoStylePlan,
    LocalImageSdxlPhotoStyleRetainedRegionPlan,
    SdxlPhotoStyleSource,
    parse_photo_style_bundle,
    parse_photo_style_plan_value,
    parse_photo_style_source,
    photo_style_artifact_pointer,
    photo_style_training_image_hashes,
    validate_photo_style_region_evidence,
    validate_photo_style_sources,
)
from eom_image_contracts.sdxl_photo_style_execution import (
    LocalImageSdxlPhotoStyleCommand,
    SdxlPhotoStyleExecutionSources,
    parse_photo_style_command,
    parse_photo_style_plan,
    validate_photo_style_execution_sources,
)
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


@dataclass(frozen=True, slots=True)
class ResolvedSdxlPhotoStyleMetadata:
    plan: LocalImageSdxlPhotoStylePlan
    configuration: ResolvedSdxlCannyReferenceMetadata
    sources: tuple[SdxlPhotoStyleSource, ...]
    files: tuple[SdxlProbeInputMember, ...]
    object_support: PhotoObjectSupportParentDocuments | None = None
    baseline_reuse: PhotoBaselineReuseDocuments | None = None


@dataclass(frozen=True, slots=True)
class ResolvedSdxlPhotoStyleExecutionMetadata:
    command: LocalImageSdxlPhotoStyleCommand
    admitted: ResolvedSdxlPhotoStyleMetadata
    sources: SdxlPhotoStyleExecutionSources
    files: tuple[SdxlProbeInputMember, ...]


@dataclass(frozen=True, slots=True)
class PreparedSdxlPhotoStyleInputs:
    metadata: ResolvedSdxlPhotoStyleExecutionMetadata
    files: tuple[SdxlProbeInputMember, ...]

    @property
    def command(self) -> LocalImageSdxlPhotoStyleCommand:
        return self.metadata.command


def resolve_sdxl_photo_style_execution_metadata(
    engine: Engine, command: LocalImageSdxlPhotoStyleCommand
) -> ResolvedSdxlPhotoStyleExecutionMetadata:
    command = parse_photo_style_command(command.model_dump(mode="json"))
    raw = resolve_control_artifact_member(engine, command.plan, maximum_bytes=256 * 1024)
    plan = parse_photo_style_plan(command, raw)
    admitted = resolve_sdxl_photo_style_metadata(engine, plan)
    native = admitted.configuration.native_admission
    if (
        native is None
        or not isinstance(
            admitted.configuration.command, LocalImageSdxlNativeCannyReferenceCommandV2
        )
        or not isinstance(admitted.configuration.sources, SdxlNativeCannyReferenceSources)
    ):
        raise ValueError("PHOTO_STYLE_NATIVE_CONFIGURATION_MISMATCH")
    sources = SdxlPhotoStyleExecutionSources(
        plan,
        admitted.configuration.command,
        admitted.configuration.sources,
        native.sources,
        admitted.sources,
        admitted.object_support,
        admitted.baseline_reuse,
    )
    validate_photo_style_execution_sources(command, sources)
    files = tuple(
        sorted(
            (
                *admitted.files,
                SdxlProbeInputMember(
                    "command.json",
                    "sha256:"
                    + hashlib.sha256(
                        content_json_bytes(command.model_dump(mode="json"))
                    ).hexdigest(),
                    content_json_bytes(command.model_dump(mode="json")),
                ),
            ),
            key=lambda file: file.member_path,
        )
    )
    return ResolvedSdxlPhotoStyleExecutionMetadata(command, admitted, sources, files)


def sdxl_photo_style_input_hashes(prepared: PreparedSdxlPhotoStyleInputs) -> dict[str, str]:
    admitted = prepared.metadata.admitted
    command, sources = prepared.command, prepared.metadata.sources
    metadata = {file.member_path: file.payload for file in prepared.metadata.files}
    if (
        parse_photo_style_plan(command, metadata["plan.json"]) != sources.plan
        or parse_sdxl_native_lora_sources(
            sources.configuration_sources.native.training_command,
            {path: raw for path, raw in metadata.items() if path.startswith("inputs/metadata/")},
        )
        != sources.native_training_sources
        or tuple(
            parse_photo_style_source(
                entry.visual_reference,
                bundle_raw=metadata["inputs/photo-sources/" + entry.case.case_id + "/bundle.json"],
                intent_raw=metadata["inputs/photo-sources/" + entry.case.case_id + "/intent.json"],
            )
            for entry in sources.plan.cases
        )
        != sources.photos
    ):
        raise ValueError("PHOTO_STYLE_HANDOFF_SOURCES_INVALID")
    validate_photo_style_execution_sources(command, sources)
    if (
        sources.plan != admitted.plan
        or sources.configuration != admitted.configuration.command
        or sources.configuration_sources != admitted.configuration.sources
        or admitted.configuration.native_admission is None
        or sources.native_training_sources != admitted.configuration.native_admission.sources
        or sources.photos != admitted.sources
        or sources.object_support != admitted.object_support
        or sources.baseline_reuse != admitted.baseline_reuse
    ):
        raise ValueError("PHOTO_STYLE_HANDOFF_SOURCES_INVALID")
    expected = sdxl_canny_reference_metadata_hashes(admitted.configuration)
    expected.pop("command.json")
    expected.update(
        {
            "command.json": "sha256:"
            + hashlib.sha256(content_json_bytes(command.model_dump(mode="json"))).hexdigest(),
            "plan.json": command.plan.sha256,
            "inputs/configuration-command.json": sources.plan.configuration_anchor.sha256,
        }
    )
    if isinstance(sources.plan, LocalImageSdxlPhotoStyleRetainedRegionPlan):
        validate_photo_style_region_evidence(
            sources.plan, metadata["inputs/photo-region-review.txt"]
        )
        expected["inputs/photo-region-review.txt"] = sources.plan.region_review_evidence.sha256
    if isinstance(sources.plan, LocalImageSdxlPhotoObjectSupportPlan):
        support = photo_object_support_parent_documents(sources.plan, metadata)
        if support != sources.object_support:
            raise ValueError("PHOTO_STYLE_OBJECT_SUPPORT_HANDOFF_INVALID")
        review = validate_photo_object_support_lineage(sources.plan, support).review
        expected.update(
            dict(
                (path, pin.sha256)
                for path, pin in photo_object_support_metadata_members(sources.plan)
            )
        )
        expected.update(
            dict((path, pin.sha256) for path, pin in photo_object_support_pixel_members(review))
        )
    expected.update(
        {
            sdxl_native_lora_metadata_member_path(p): p.sha256
            for p in sources.native_training_sources.metadata_pointers
        }
    )
    if isinstance(sources.plan, LocalImageSdxlPhotoReusedBaselinePlan):
        if (
            photo_baseline_reuse_documents(sources.plan, metadata, sources.configuration_sources)
            != sources.baseline_reuse
        ):
            raise ValueError("PHOTO_STYLE_BASELINE_REUSE_HANDOFF_INVALID")
        expected.update(
            {path: pin.sha256 for path, pin in photo_baseline_reuse_metadata_members(sources.plan)}
        )
        path, pin = photo_baseline_reuse_geometry_member(
            sources.plan,
            metadata["inputs/photo-reuse/prior-configuration.json"],
            sources.configuration_sources,
        )
        expected[path] = pin.sha256
    for entry, source in zip(sources.plan.cases, sources.photos, strict=True):
        prefix = "inputs/photo-sources/" + entry.case.case_id + "/"
        expected[prefix + "bundle.json"] = source.reference.bundle_manifest.sha256
        expected[prefix + "intent.json"] = source.bundle.intent.sha256
        expected[entry.case.staged_member_path] = entry.case.reference_image.sha256
    selected = sdxl_reference_adapter(sources.configuration_sources)
    expected.update(
        {"inputs/adapter/" + file.relative_path: file.sha256 for file in selected.manifest.files}
    )
    return expected


def prepare_sdxl_photo_style_inputs(
    engine: Engine, command: LocalImageSdxlPhotoStyleCommand
) -> PreparedSdxlPhotoStyleInputs:
    admitted = resolve_sdxl_photo_style_execution_metadata(engine, command)
    paths, reads = [], []
    for entry, source in zip(admitted.sources.plan.cases, admitted.sources.photos, strict=True):
        paths.append(entry.case.staged_member_path)
        reads.append(
            BoundedControlArtifactRead(
                entry.case.reference_image, source.bundle.normalized_member.size_bytes
            )
        )
    selected = sdxl_reference_adapter(admitted.sources.configuration_sources)
    for file in selected.manifest.files:
        bound = 64 * 1024 if file.relative_path.endswith(".json") else 64 * 1024**2
        if not 0 < file.size_bytes <= bound:
            raise ValueError("PHOTO_STYLE_ADAPTER_SIZE_INVALID")
        reads.append(
            BoundedControlArtifactRead(
                ImageEvaluationArtifactMember(
                    artifact_id=selected.training_result.artifact_id,
                    artifact_revision_id=selected.training_result.artifact_revision_id,
                    member_path="adapter/" + file.relative_path,
                    schema_ref="eom://schemas/image-provider/local-image-lora-adapter-file/1.0",
                    media_type="application/json"
                    if file.relative_path.endswith(".json")
                    else "application/octet-stream",
                    sha256=file.sha256,
                ),
                file.size_bytes,
            )
        )
        paths.append("inputs/adapter/" + file.relative_path)
    exact_paths = frozenset(paths)
    if isinstance(admitted.sources.plan, LocalImageSdxlPhotoObjectSupportPlan):
        if admitted.sources.object_support is None:
            raise ValueError("PHOTO_STYLE_OBJECT_SUPPORT_METADATA_MISSING")
        review = validate_photo_object_support_lineage(
            admitted.sources.plan, admitted.sources.object_support
        ).review
        for path, pin in photo_object_support_pixel_members(review):
            paths.append(path)
            reads.append(BoundedControlArtifactRead(pin, 16 * 1024**2))
    payloads = resolve_control_artifact_members(engine, tuple(reads))
    files = list(admitted.files)
    for path, read, raw in zip(paths, reads, payloads, strict=True):
        if not 0 < len(raw) <= read.maximum_bytes or (
            path in exact_paths and len(raw) != read.maximum_bytes
        ):
            raise ValueError("PHOTO_STYLE_INPUT_SIZE_INVALID")
        files.append(SdxlProbeInputMember(path, read.pointer.sha256, raw))
    prepared = PreparedSdxlPhotoStyleInputs(
        admitted, tuple(sorted(files, key=lambda f: f.member_path))
    )
    sdxl_photo_style_input_hashes(prepared)
    return prepared


def resolve_sdxl_photo_style_metadata(
    engine: Engine, plan: LocalImageSdxlPhotoStylePlan
) -> ResolvedSdxlPhotoStyleMetadata:
    """Re-admit configuration and licensed sources before any binary input can be read."""
    value = plan.model_dump(mode="json")
    plan = parse_photo_style_plan_value(value)
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
    training_hashes = photo_style_training_image_hashes(native.sources)
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
    support_documents = None
    baseline_documents = None
    if isinstance(plan, LocalImageSdxlPhotoObjectSupportPlan):
        members = photo_object_support_metadata_members(plan)
        pins = tuple(dict.fromkeys(pin for _, pin in members))
        payloads = resolve_control_artifact_members(
            engine, tuple(BoundedControlArtifactRead(pin, 256 * 1024) for pin in pins)
        )
        support_payloads = dict(zip(pins, payloads, strict=True))
        metadata.update({path: support_payloads[pin] for path, pin in members})
        support_documents = photo_object_support_parent_documents(plan, metadata)
        validate_photo_object_support_lineage(plan, support_documents)
    if isinstance(plan, LocalImageSdxlPhotoReusedBaselinePlan):
        members = photo_baseline_reuse_metadata_members(plan)
        raw_reused = resolve_control_artifact_members(
            engine, tuple(BoundedControlArtifactRead(pin, 256 * 1024) for _, pin in members)
        )
        metadata.update({path: raw for (path, _), raw in zip(members, raw_reused, strict=True)})
        path, pin = photo_baseline_reuse_geometry_member(
            plan, metadata["inputs/photo-reuse/prior-configuration.json"], admitted.sources
        )
        if path not in metadata:
            metadata[path] = resolve_control_artifact_member(engine, pin, maximum_bytes=256 * 1024)
        baseline_documents = photo_baseline_reuse_documents(plan, metadata, admitted.sources)
        if not isinstance(anchor, LocalImageSdxlNativeCannyReferenceCommandV4):
            raise ValueError("PHOTO_STYLE_BASELINE_REUSE_CONFIGURATION_INVALID")
        parse_reused_photo_baseline(plan, anchor, admitted.sources, baseline_documents)
    if isinstance(plan, LocalImageSdxlPhotoStyleRetainedRegionPlan):
        review_raw = resolve_control_artifact_member(
            engine, plan.region_review_evidence, maximum_bytes=64 * 1024
        )
        validate_photo_style_region_evidence(plan, review_raw)
        metadata["inputs/photo-region-review.txt"] = review_raw
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
        support_documents,
        baseline_documents,
    )
