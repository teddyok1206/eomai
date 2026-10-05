"""Shared bounded staged configuration reader; never opens pixels or weights."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from eom_image_contracts.models import ImageEvaluationArtifactMember
from eom_image_contracts.sdxl_canny_reference import (
    LocalImageSdxlCannyReferenceCommand,
    parse_sdxl_canny_reference_predecessors,
)
from eom_image_contracts.sdxl_native_canny_reference import (
    LocalImageSdxlNativeCannyReferenceCommand,
    SdxlNativeCannyReferenceSources,
    native_reference_evaluation,
    native_reference_metadata_pointers,
    parse_reference_command,
    parse_reference_sources,
)
from eom_image_contracts.sdxl_native_lora_sources import (
    NATIVE_LORA_MAX_METADATA_BYTES,
    SdxlNativeLoraMetadataAdmission,
    SdxlNativeLoraSources,
    sdxl_native_lora_metadata_member_path,
)

from eom_image_provider.sdxl_canny_comparison import read_sdxl_canny_comparison_metadata
from eom_image_provider.staged_file_io import read_staged_member


@dataclass(frozen=True, slots=True)
class StagedSdxlReferenceMetadata:
    command: LocalImageSdxlCannyReferenceCommand
    command_raw: bytes
    inherited: Mapping[str, bytes]
    native_training_sources: SdxlNativeLoraSources | None


def read_sdxl_reference_metadata(
    root: int, configuration_anchor: ImageEvaluationArtifactMember
) -> StagedSdxlReferenceMetadata:
    anchor_raw = read_staged_member(
        root,
        "inputs/configuration-command.json",
        maximum_bytes=256 * 1024,
        expected_sha256=configuration_anchor.sha256,
    )
    anchor = parse_reference_command(json.loads(anchor_raw))
    inherited = {}
    native_training_sources = None
    for name, pointer in (
        ("spatial-command", anchor.spatial_command),
        ("spatial-result", anchor.spatial_result),
    ):
        inherited["inputs/" + name + ".json"] = read_staged_member(
            root,
            "inputs/" + name + ".json",
            maximum_bytes=256 * 1024,
            expected_sha256=pointer.sha256,
        )
    spatial, _ = parse_sdxl_canny_reference_predecessors(
        anchor, inherited["inputs/spatial-command.json"], inherited["inputs/spatial-result.json"]
    )
    inherited.update(read_sdxl_canny_comparison_metadata(root, spatial))
    if isinstance(anchor, LocalImageSdxlNativeCannyReferenceCommand):
        raw = read_staged_member(
            root,
            "inputs/native-evaluation-command.json",
            maximum_bytes=256 * 1024,
            expected_sha256=anchor.native_evaluation_command.sha256,
        )
        evaluation = native_reference_evaluation(anchor, raw)
        inherited["inputs/native-evaluation-command.json"] = raw
        for name, pin in native_reference_metadata_pointers(anchor, evaluation).items():
            if name not in inherited:
                inherited[name] = read_staged_member(
                    root, name, maximum_bytes=256 * 1024, expected_sha256=pin.sha256
                )
        native_sources = parse_reference_sources(anchor, inherited)
        if not isinstance(native_sources, SdxlNativeCannyReferenceSources):
            raise ValueError("SDXL_VALIDATION_NATIVE_CONFIGURATION_MISSING")
        admission = SdxlNativeLoraMetadataAdmission(native_sources.native.training_command)
        while pending := admission.pending_pointers():
            for pointer in pending:
                name = sdxl_native_lora_metadata_member_path(pointer)
                raw = read_staged_member(
                    root,
                    name,
                    maximum_bytes=NATIVE_LORA_MAX_METADATA_BYTES,
                    expected_sha256=pointer.sha256,
                )
                admission.admit(pointer, raw)
                inherited[name] = raw
        native_training_sources = admission.validated_sources()
    return StagedSdxlReferenceMetadata(
        anchor, anchor_raw, MappingProxyType(inherited), native_training_sources
    )
