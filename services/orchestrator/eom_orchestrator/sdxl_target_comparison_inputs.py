"""Full metadata lineage admission, then selected target/adapter bytes only."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from eom_image_contracts.models import ImageEvaluationArtifactMember, content_json_bytes
from eom_image_contracts.sdxl_lora_evaluation import parse_sdxl_lora_evaluation_sources
from eom_image_contracts.sdxl_reviewed_evaluation import LocalImageSdxlReviewedEvaluationCommand
from eom_image_contracts.sdxl_reviewed_micro import (
    LocalImageSdxlReviewedMicroCommand,
    sdxl_reviewed_micro_metadata_pointers,
)
from eom_image_contracts.sdxl_target_comparison import (
    LocalImageSdxlTargetComparisonCommand,
    SdxlTargetComparisonSources,
    parse_sdxl_target_comparison_sources,
)
from eom_image_contracts.validation import validate_contract
from sqlalchemy import Engine

from eom_orchestrator.control_artifact_resolution import (
    BoundedControlArtifactRead,
    resolve_control_artifact_member,
    resolve_control_artifact_members,
)
from eom_orchestrator.sdxl_micro_inputs import resolve_sdxl_reviewed_micro_sources
from eom_orchestrator.sdxl_probe_inputs import SdxlProbeInputMember, resolve_sdxl_probe_sources


@dataclass(frozen=True, slots=True)
class PreparedSdxlTargetComparisonInputs:
    command: LocalImageSdxlTargetComparisonCommand
    sources: SdxlTargetComparisonSources
    files: tuple[SdxlProbeInputMember, ...]


@dataclass(frozen=True, slots=True)
class ResolvedSdxlTargetComparisonMetadata:
    """Approved source history without targets, weights or generation pixels."""

    command: LocalImageSdxlTargetComparisonCommand
    sources: SdxlTargetComparisonSources
    files: tuple[SdxlProbeInputMember, ...]


def sdxl_target_comparison_metadata_hashes(
    prepared: PreparedSdxlTargetComparisonInputs | ResolvedSdxlTargetComparisonMetadata,
) -> dict[str, str]:
    command, sources = prepared.command, prepared.sources
    metadata = {file.member_path: file.payload for file in prepared.files}
    parse_sdxl_target_comparison_sources(command, metadata)
    training = sources.lora.training_command
    if not isinstance(training, LocalImageSdxlReviewedMicroCommand):
        raise ValueError("SDXL_TARGET_COMPARISON_TRAINING_INVALID")
    pin = sources.evaluation.evaluation
    pointers = {
        "inputs/lora-evaluation-command.json": command.lora_evaluation_command,
        "inputs/baseline-command.json": pin.baseline_command,
        "inputs/training-command.json": pin.training_command,
        "inputs/training-result.json": pin.training_result,
        "inputs/adapter-manifest.json": pin.adapter_manifest,
        "inputs/prompt-policy.json": sources.lora.baseline.prompt_policy,
        **sdxl_reviewed_micro_metadata_pointers(training, metadata["inputs/source-crop-set.json"]),
    }
    return {
        "command.json": "sha256:"
        + hashlib.sha256(content_json_bytes(command.model_dump(mode="json"))).hexdigest(),
        **{name: pointer.sha256 for name, pointer in pointers.items()},
    }


def sdxl_target_comparison_input_hashes(
    prepared: PreparedSdxlTargetComparisonInputs,
) -> dict[str, str]:
    return {
        **sdxl_target_comparison_metadata_hashes(prepared),
        **{
            entry.case.staged_member_path: entry.case.reference_image.sha256
            for entry in prepared.command.cases
        },
        **{
            "inputs/adapter/" + file.relative_path: file.sha256
            for file in prepared.sources.lora.manifest.files
        },
    }


def resolve_sdxl_target_comparison_metadata(
    engine: Engine,
    command: LocalImageSdxlTargetComparisonCommand,
) -> ResolvedSdxlTargetComparisonMetadata:
    validate_contract("sdxl-target-comparison-command", command.model_dump(mode="json"))
    command = LocalImageSdxlTargetComparisonCommand.model_validate_json(command.model_dump_json())
    raw = resolve_control_artifact_member(
        engine, command.lora_evaluation_command, maximum_bytes=256 * 1024
    )
    validate_contract(
        "sdxl-lora-evaluation-command-v2",
        LocalImageSdxlReviewedEvaluationCommand.model_validate_json(raw).model_dump(mode="json"),
    )
    evaluation = LocalImageSdxlReviewedEvaluationCommand.model_validate_json(raw)
    pin = evaluation.evaluation
    metadata = {"inputs/lora-evaluation-command.json": raw}
    for name, pointer in (
        ("baseline-command", pin.baseline_command),
        ("training-command", pin.training_command),
        ("training-result", pin.training_result),
        ("adapter-manifest", pin.adapter_manifest),
    ):
        metadata["inputs/" + name + ".json"] = resolve_control_artifact_member(
            engine, pointer, maximum_bytes=256 * 1024
        )
    lora = parse_sdxl_lora_evaluation_sources(
        evaluation,
        baseline_payload=metadata["inputs/baseline-command.json"],
        training_command_payload=metadata["inputs/training-command.json"],
        training_result_payload=metadata["inputs/training-result.json"],
        manifest_payload=metadata["inputs/adapter-manifest.json"],
    )
    if not isinstance(lora.training_command, LocalImageSdxlReviewedMicroCommand):
        raise ValueError("SDXL_TARGET_COMPARISON_TRAINING_INVALID")
    admitted = resolve_sdxl_reviewed_micro_sources(engine, lora.training_command)
    metadata.update({file.member_path: file.payload for file in admitted.metadata})
    sources = parse_sdxl_target_comparison_sources(command, metadata)
    original = resolve_sdxl_probe_sources(engine, lora.baseline)
    metadata["inputs/prompt-policy.json"] = original.policy_payload
    metadata["command.json"] = content_json_bytes(command.model_dump(mode="json"))
    return ResolvedSdxlTargetComparisonMetadata(
        command,
        sources,
        tuple(
            SdxlProbeInputMember(name, "sha256:" + hashlib.sha256(raw).hexdigest(), raw)
            for name, raw in sorted(metadata.items())
        ),
    )


def prepare_sdxl_target_comparison_inputs(
    engine: Engine,
    command: LocalImageSdxlTargetComparisonCommand,
) -> PreparedSdxlTargetComparisonInputs:
    admitted = resolve_sdxl_target_comparison_metadata(engine, command)
    command, sources = admitted.command, admitted.sources
    lora, pin = sources.lora, sources.evaluation.evaluation
    targets = {target.sample_id: target for target in sources.targets}
    reads = []
    paths = []
    for entry in command.cases:
        size = targets[entry.sample_id].size_bytes
        if not 0 < size <= 16 * 1024**2:
            raise ValueError("SDXL_TARGET_COMPARISON_SIZE_INVALID")
        reads.append(BoundedControlArtifactRead(entry.case.reference_image, size))
        paths.append(entry.case.staged_member_path)
    for file in lora.manifest.files:
        limit = 64 * 1024 if file.relative_path.endswith(".json") else 64 * 1024**2
        if not 0 < file.size_bytes <= limit:
            raise ValueError("SDXL_TARGET_COMPARISON_ADAPTER_SIZE_INVALID")
        pointer = ImageEvaluationArtifactMember(
            artifact_id=pin.training_result.artifact_id,
            artifact_revision_id=pin.training_result.artifact_revision_id,
            member_path="adapter/" + file.relative_path,
            schema_ref="eom://schemas/image-provider/local-image-lora-adapter-file/1.0",
            media_type="application/json"
            if file.relative_path.endswith(".json")
            else "application/octet-stream",
            sha256=file.sha256,
        )
        reads.append(BoundedControlArtifactRead(pointer, file.size_bytes))
        paths.append("inputs/adapter/" + file.relative_path)
    payloads = resolve_control_artifact_members(engine, tuple(reads))
    files = []
    for path, read, payload in zip(paths, reads, payloads, strict=True):
        if len(payload) != read.maximum_bytes:
            raise ValueError("SDXL_TARGET_COMPARISON_SIZE_INVALID")
        files.append(SdxlProbeInputMember(path, read.pointer.sha256, payload))
    files.extend(admitted.files)
    return PreparedSdxlTargetComparisonInputs(
        command, sources, tuple(sorted(files, key=lambda file: file.member_path))
    )
