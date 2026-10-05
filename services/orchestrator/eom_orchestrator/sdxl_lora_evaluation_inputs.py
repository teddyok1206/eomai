"""Admit pinned matched-input LoRA evaluation, then stage only declared files."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageSdxlLineartProbeCommand,
    LocalImageSdxlLoraEvaluationCommand,
    LocalImageSdxlLoraMicroAdapterManifest,
    content_json_bytes,
    validate_sdxl_lora_micro_sources,
)
from eom_image_contracts.sdxl_evaluation_codec import parse_sdxl_evaluation_command
from eom_image_contracts.sdxl_lora_evaluation import parse_sdxl_lora_evaluation_sources
from eom_image_contracts.sdxl_native_evaluation import (
    LocalImageSdxlNativeEvaluationCommand,
    parse_sdxl_native_evaluation_sources,
)
from eom_image_contracts.sdxl_native_lora import LocalImageSdxlNativeLoraAdapterManifest
from eom_image_contracts.sdxl_reviewed_micro import LocalImageSdxlReviewedMicroCommand
from sqlalchemy import Engine

from eom_orchestrator.control_artifact_resolution import resolve_control_artifact_member
from eom_orchestrator.sdxl_micro_inputs import resolve_sdxl_reviewed_micro_sources
from eom_orchestrator.sdxl_native_lora_inputs import resolve_sdxl_native_lora_sources
from eom_orchestrator.sdxl_probe_inputs import (
    SdxlProbeInputMember,
    materialize_sdxl_probe_inputs,
    resolve_sdxl_probe_sources,
)


@dataclass(frozen=True, slots=True)
class PreparedSdxlLoraEvaluationInputs:
    command: LocalImageSdxlLoraEvaluationCommand
    baseline: LocalImageSdxlLineartProbeCommand
    manifest: LocalImageSdxlLoraMicroAdapterManifest | LocalImageSdxlNativeLoraAdapterManifest
    files: tuple[SdxlProbeInputMember, ...]


def prepare_sdxl_lora_evaluation_inputs(
    engine: Engine, command: LocalImageSdxlLoraEvaluationCommand
) -> PreparedSdxlLoraEvaluationInputs:
    command = parse_sdxl_evaluation_command(command.model_dump(mode="json"))
    pin = command.evaluation
    metadata = {
        name: resolve_control_artifact_member(engine, pointer, maximum_bytes=256 * 1024)
        for name, pointer in (
            ("baseline-command", pin.baseline_command),
            ("training-command", pin.training_command),
            ("training-result", pin.training_result),
            ("adapter-manifest", pin.adapter_manifest),
        )
    }
    payloads = {
        "baseline_payload": metadata["baseline-command"],
        "training_command_payload": metadata["training-command"],
        "training_result_payload": metadata["training-result"],
        "manifest_payload": metadata["adapter-manifest"],
    }
    manifest: LocalImageSdxlLoraMicroAdapterManifest | LocalImageSdxlNativeLoraAdapterManifest
    if isinstance(command, LocalImageSdxlNativeEvaluationCommand):
        native = parse_sdxl_native_evaluation_sources(command, **payloads)
        baseline, manifest = native.baseline, native.manifest
        probe_sources = resolve_sdxl_probe_sources(engine, baseline)
        admitted = resolve_sdxl_native_lora_sources(engine, native.training_command)
        if (
            admitted.sources.batches[0].sources.review.basis_crop_set
            != probe_sources.policy.crop_set
        ):
            raise ValueError("SDXL_EVALUATION_CROP_REVISION_MISMATCH")
    else:
        sources = parse_sdxl_lora_evaluation_sources(command, **payloads)
        baseline, manifest = sources.baseline, sources.manifest
        probe_sources = resolve_sdxl_probe_sources(engine, baseline)
        if isinstance(sources.training_command, LocalImageSdxlReviewedMicroCommand):
            resolve_sdxl_reviewed_micro_sources(engine, sources.training_command)
        else:
            if sources.training_command.crop_set != probe_sources.policy.crop_set:
                raise ValueError("SDXL_EVALUATION_CROP_REVISION_MISMATCH")
            validate_sdxl_lora_micro_sources(sources.training_command, probe_sources.crop_set)
    # Bound both adapter members before the existing full-lineage PNG admission materializes bytes.
    if any(
        file.size_bytes > (64 * 1024 if file.relative_path.endswith(".json") else 64 * 1024**2)
        for file in manifest.files
    ):
        raise ValueError("SDXL_EVALUATION_ADAPTER_SIZE_INVALID")
    baseline_inputs = materialize_sdxl_probe_inputs(engine, baseline, probe_sources)
    files = [file for file in baseline_inputs.files if file.member_path != "command.json"]
    for file in manifest.files:
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
        raw = resolve_control_artifact_member(engine, pointer, maximum_bytes=file.size_bytes)
        if len(raw) != file.size_bytes:
            raise ValueError("SDXL_EVALUATION_ADAPTER_SIZE_INVALID")
        files.append(SdxlProbeInputMember("inputs/adapter/" + file.relative_path, file.sha256, raw))
    metadata["command"] = content_json_bytes(command.model_dump(mode="json"))
    for name, raw in metadata.items():
        path = "command.json" if name == "command" else "inputs/" + name + ".json"
        files.append(SdxlProbeInputMember(path, "sha256:" + hashlib.sha256(raw).hexdigest(), raw))
    return PreparedSdxlLoraEvaluationInputs(
        command,
        baseline,
        manifest,
        tuple(sorted(files, key=lambda file: file.member_path)),
    )
