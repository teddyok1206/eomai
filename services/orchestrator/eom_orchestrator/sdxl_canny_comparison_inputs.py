"""Admit full source/review history, then only pinned control maps and LoRA material."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from eom_image_contracts.models import ImageEvaluationArtifactMember, content_json_bytes
from eom_image_contracts.sdxl_canny_comparison import (
    LocalImageSdxlCannyComparisonCommand,
    LocalImageSdxlCannyDetailReview,
    SdxlCannyComparisonSources,
    parse_sdxl_canny_comparison_sources,
)
from eom_image_contracts.sdxl_canny_conditioning import (
    LocalImageSdxlCannyConditioningCommand,
    parse_sdxl_canny_parent,
)
from eom_image_contracts.validation import validate_contract
from sqlalchemy import Engine

from eom_orchestrator.control_artifact_resolution import (
    BoundedControlArtifactRead,
    resolve_control_artifact_member,
    resolve_control_artifact_members,
)
from eom_orchestrator.sdxl_probe_inputs import SdxlProbeInputMember
from eom_orchestrator.sdxl_target_comparison_inputs import (
    ResolvedSdxlTargetComparisonMetadata,
    resolve_sdxl_target_comparison_metadata,
    sdxl_target_comparison_metadata_hashes,
)


@dataclass(frozen=True, slots=True)
class PreparedSdxlCannyComparisonInputs:
    command: LocalImageSdxlCannyComparisonCommand
    sources: SdxlCannyComparisonSources
    source_metadata: ResolvedSdxlTargetComparisonMetadata
    files: tuple[SdxlProbeInputMember, ...]


def sdxl_canny_comparison_input_hashes(
    prepared: PreparedSdxlCannyComparisonInputs,
) -> dict[str, str]:
    command, sources = prepared.command, prepared.sources
    metadata = {file.member_path: file.payload for file in prepared.files}
    if (
        parse_sdxl_canny_comparison_sources(command, metadata) != sources
        or prepared.source_metadata.command != sources.parent
        or prepared.source_metadata.sources != sources.targets
    ):
        raise ValueError("SDXL_CANNY_COMPARISON_HANDOFF_SOURCES_INVALID")
    expected = sdxl_target_comparison_metadata_hashes(prepared.source_metadata)
    expected.pop("command.json")
    return {
        **expected,
        "command.json": "sha256:"
        + hashlib.sha256(content_json_bytes(command.model_dump(mode="json"))).hexdigest(),
        "inputs/parent-command.json": sources.preparation.source_command.sha256,
        "inputs/canny-command.json": command.conditioning_command.sha256,
        "inputs/canny-result.json": command.conditioning_result.sha256,
        "inputs/canny-detail-review.json": command.detail_review.sha256,
        "inputs/source-target-result.json": command.baseline_result.sha256,
        "inputs/canny-own-review-evidence.json": sources.review.own_review_evidence.sha256,
        **{
            "inputs/canny/" + out.case_id + ".png": out.sha256
            for out in sources.conditionings.outputs
        },
        **{
            "inputs/adapter/" + file.relative_path: file.sha256
            for file in sources.targets.lora.manifest.files
        },
    }


def prepare_sdxl_canny_comparison_inputs(
    engine: Engine,
    command: LocalImageSdxlCannyComparisonCommand,
) -> PreparedSdxlCannyComparisonInputs:
    validate_contract("sdxl-canny-comparison-command", command.model_dump(mode="json"))
    command = LocalImageSdxlCannyComparisonCommand.model_validate_json(command.model_dump_json())
    metadata = {}
    for name, pointer in (
        ("canny-command", command.conditioning_command),
        ("canny-result", command.conditioning_result),
        ("canny-detail-review", command.detail_review),
        ("source-target-result", command.baseline_result),
    ):
        metadata["inputs/" + name + ".json"] = resolve_control_artifact_member(
            engine,
            pointer,
            maximum_bytes=256 * 1024,
        )
    preparation = LocalImageSdxlCannyConditioningCommand.model_validate_json(
        metadata["inputs/canny-command.json"]
    )
    metadata["inputs/parent-command.json"] = resolve_control_artifact_member(
        engine,
        preparation.source_command,
        maximum_bytes=256 * 1024,
    )
    parent = parse_sdxl_canny_parent(preparation, metadata["inputs/parent-command.json"])
    admitted = resolve_sdxl_target_comparison_metadata(engine, parent)
    metadata.update(
        {
            file.member_path: file.payload
            for file in admitted.files
            if file.member_path != "command.json"
        }
    )
    review = LocalImageSdxlCannyDetailReview.model_validate_json(
        metadata["inputs/canny-detail-review.json"]
    )
    metadata["inputs/canny-own-review-evidence.json"] = resolve_control_artifact_member(
        engine,
        review.own_review_evidence,
        maximum_bytes=256 * 1024,
    )
    sources = parse_sdxl_canny_comparison_sources(command, metadata)
    # Only now may image and adapter bytes cross the explicit workspace boundary.
    reads = []
    paths = []
    for output in sources.conditionings.outputs:
        reads.append(
            BoundedControlArtifactRead(
                ImageEvaluationArtifactMember(
                    artifact_id=command.conditioning_result.artifact_id,
                    artifact_revision_id=command.conditioning_result.artifact_revision_id,
                    member_path=output.member_path,
                    schema_ref="eom://schemas/image-provider/local-image-sdxl-canny-conditioning-output/1.0",
                    media_type="image/png",
                    sha256=output.sha256,
                ),
                output.size_bytes,
            )
        )
        paths.append("inputs/canny/" + output.case_id + ".png")
    pin = sources.targets.evaluation.evaluation
    for file in sources.targets.lora.manifest.files:
        if (
            not 0
            < file.size_bytes
            <= (64 * 1024 if file.relative_path.endswith(".json") else 64 * 1024**2)
        ):
            raise ValueError("SDXL_CANNY_COMPARISON_ADAPTER_SIZE_INVALID")
        reads.append(
            BoundedControlArtifactRead(
                ImageEvaluationArtifactMember(
                    artifact_id=pin.training_result.artifact_id,
                    artifact_revision_id=pin.training_result.artifact_revision_id,
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
    payloads = resolve_control_artifact_members(engine, tuple(reads))
    metadata["command.json"] = content_json_bytes(command.model_dump(mode="json"))
    files = [
        SdxlProbeInputMember(name, "sha256:" + hashlib.sha256(raw).hexdigest(), raw)
        for name, raw in metadata.items()
    ]
    for path, read, raw in zip(paths, reads, payloads, strict=True):
        if len(raw) != read.maximum_bytes:
            raise ValueError("SDXL_CANNY_COMPARISON_INPUT_SIZE_INVALID")
        files.append(SdxlProbeInputMember(path, read.pointer.sha256, raw))
    return PreparedSdxlCannyComparisonInputs(
        command, sources, admitted, tuple(sorted(files, key=lambda file: file.member_path))
    )
