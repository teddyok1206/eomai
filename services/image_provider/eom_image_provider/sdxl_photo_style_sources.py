"""Licensed photo and native source closure checks before staged binary inputs."""

from __future__ import annotations

from eom_image_contracts.sdxl_native_canny_reference import (
    LocalImageSdxlNativeCannyReferenceCommandV2,
    SdxlNativeCannyReferenceSources,
    parse_reference_sources,
)
from eom_image_contracts.sdxl_photo_object_support_lineage import (
    photo_object_support_metadata_members,
    photo_object_support_parent_documents,
)
from eom_image_contracts.sdxl_photo_style import (
    LocalImageSdxlPhotoObjectSupportPlan,
    LocalImageSdxlPhotoStyleRetainedRegionPlan,
    parse_photo_style_bundle,
    parse_photo_style_source,
    validate_photo_style_region_evidence,
)
from eom_image_contracts.sdxl_photo_style_execution import (
    LocalImageSdxlPhotoStyleCommand,
    SdxlPhotoStyleExecutionSources,
    parse_photo_style_plan,
    validate_photo_style_execution_sources,
)

from eom_image_provider.sdxl_reference_metadata import read_sdxl_reference_metadata
from eom_image_provider.staged_file_io import read_staged_member


def read_sdxl_photo_style_sources(
    root: int, command: LocalImageSdxlPhotoStyleCommand
) -> SdxlPhotoStyleExecutionSources:
    plan = parse_photo_style_plan(
        command,
        read_staged_member(
            root, "plan.json", maximum_bytes=256 * 1024, expected_sha256=command.plan.sha256
        ),
    )
    metadata = read_sdxl_reference_metadata(root, plan.configuration_anchor)
    if isinstance(plan, LocalImageSdxlPhotoStyleRetainedRegionPlan):
        validate_photo_style_region_evidence(
            plan,
            read_staged_member(
                root,
                "inputs/photo-region-review.txt",
                maximum_bytes=64 * 1024,
                expected_sha256=plan.region_review_evidence.sha256,
            ),
        )
    if (
        not isinstance(metadata.command, LocalImageSdxlNativeCannyReferenceCommandV2)
        or metadata.native_training_sources is None
    ):
        raise ValueError("PHOTO_STYLE_NATIVE_CONFIGURATION_MISSING")
    native = parse_reference_sources(metadata.command, metadata.inherited)
    if not isinstance(native, SdxlNativeCannyReferenceSources):
        raise ValueError("PHOTO_STYLE_NATIVE_CONFIGURATION_MISSING")
    photos = []
    for entry in plan.cases:
        reference = entry.visual_reference
        prefix = "inputs/photo-sources/" + entry.case.case_id + "/"
        bundle_raw = read_staged_member(
            root,
            prefix + "bundle.json",
            maximum_bytes=reference.bundle_manifest.size_bytes,
            expected_sha256=reference.bundle_manifest.sha256,
        )
        bundle = parse_photo_style_bundle(reference, bundle_raw)
        intent_raw = read_staged_member(
            root,
            prefix + "intent.json",
            maximum_bytes=bundle.intent.size_bytes,
            expected_sha256=bundle.intent.sha256,
        )
        photos.append(
            parse_photo_style_source(reference, bundle_raw=bundle_raw, intent_raw=intent_raw)
        )
    support = None
    if isinstance(plan, LocalImageSdxlPhotoObjectSupportPlan):
        payloads = {
            path: read_staged_member(
                root, path, maximum_bytes=256 * 1024, expected_sha256=pin.sha256
            )
            for path, pin in photo_object_support_metadata_members(plan)
        }
        support = photo_object_support_parent_documents(plan, payloads)
    sources = SdxlPhotoStyleExecutionSources(
        plan, metadata.command, native, metadata.native_training_sources, tuple(photos), support
    )
    validate_photo_style_execution_sources(command, sources)
    return sources
