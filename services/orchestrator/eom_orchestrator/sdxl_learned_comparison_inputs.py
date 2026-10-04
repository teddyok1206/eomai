"""Read-only original/learned/LoRA provenance admission, then one bounded input materialization."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageSdxlLearnedComparisonCommand,
    LocalImageSdxlLoraEvaluationCommand,
    SdxlLearnedComparisonSources,
    content_json_bytes,
    parse_sdxl_learned_comparison_sources,
    validate_contract,
    validate_sdxl_lora_micro_sources,
)
from sqlalchemy import Engine

from eom_orchestrator.control_artifact_resolution import (
    BoundedControlArtifactRead,
    resolve_control_artifact_member,
    resolve_control_artifact_members,
)
from eom_orchestrator.sdxl_probe_inputs import SdxlProbeInputMember, resolve_sdxl_probe_sources


@dataclass(frozen=True, slots=True)
class PreparedSdxlLearnedComparisonInputs:
    command: LocalImageSdxlLearnedComparisonCommand
    sources: SdxlLearnedComparisonSources
    files: tuple[SdxlProbeInputMember, ...]


def sdxl_learned_input_hashes(
    command: LocalImageSdxlLearnedComparisonCommand,
    sources: SdxlLearnedComparisonSources,
) -> dict[str, str]:
    """Exact staged member identity for the admission/handoff boundary; no implicit inputs."""
    pin = sources.lora_evaluation_command.evaluation
    extracted = {output.case_id: output for output in sources.extraction_result.outputs}
    return {
        "command.json": "sha256:"
        + hashlib.sha256(content_json_bytes(command.model_dump(mode="json"))).hexdigest(),
        "inputs/baseline-command.json": command.baseline_command.sha256,
        "inputs/extraction-command.json": command.extraction_command.sha256,
        "inputs/extraction-result.json": command.extraction_result.sha256,
        "inputs/lora-evaluation-command.json": command.lora_evaluation_command.sha256,
        "inputs/training-command.json": pin.training_command.sha256,
        "inputs/training-result.json": pin.training_result.sha256,
        "inputs/adapter-manifest.json": pin.adapter_manifest.sha256,
        "inputs/prompt-policy.json": sources.baseline.prompt_policy.sha256,
        **{
            f"inputs/conditioning/{case_id}.png": extracted[case_id].conditioning_sha256
            for case_id in command.case_ids
        },
        **{
            "inputs/adapter/" + file.relative_path: file.sha256
            for file in sources.lora_sources.manifest.files
        },
    }


def prepare_sdxl_learned_comparison_inputs(
    engine: Engine, command: LocalImageSdxlLearnedComparisonCommand
) -> PreparedSdxlLearnedComparisonInputs:
    validate_contract("sdxl-learned-comparison-command", command.model_dump(mode="json"))
    command = LocalImageSdxlLearnedComparisonCommand.model_validate_json(command.model_dump_json())
    metadata = {
        name: resolve_control_artifact_member(engine, pointer, maximum_bytes=256 * 1024)
        for name, pointer in (
            ("baseline-command", command.baseline_command),
            ("extraction-command", command.extraction_command),
            ("extraction-result", command.extraction_result),
            ("lora-evaluation-command", command.lora_evaluation_command),
        )
    }
    # This small document is required before resolving the three training provenance pointers.
    validate_contract(
        "sdxl-lora-evaluation-command", json.loads(metadata["lora-evaluation-command"])
    )
    evaluation = LocalImageSdxlLoraEvaluationCommand.model_validate_json(
        metadata["lora-evaluation-command"]
    )
    pin = evaluation.evaluation
    for name, pointer in (
        ("training-command", pin.training_command),
        ("training-result", pin.training_result),
        ("adapter-manifest", pin.adapter_manifest),
    ):
        metadata[name] = resolve_control_artifact_member(engine, pointer, maximum_bytes=256 * 1024)
    sources = parse_sdxl_learned_comparison_sources(
        command,
        baseline_payload=metadata["baseline-command"],
        extraction_command_payload=metadata["extraction-command"],
        extraction_result_payload=metadata["extraction-result"],
        lora_evaluation_command_payload=metadata["lora-evaluation-command"],
        training_command_payload=metadata["training-command"],
        training_result_payload=metadata["training-result"],
        adapter_manifest_payload=metadata["adapter-manifest"],
    )
    original = resolve_sdxl_probe_sources(engine, sources.baseline)
    if sources.lora_sources.training_command.crop_set != original.policy.crop_set:
        raise ValueError("SDXL_LEARNED_CROP_REVISION_MISMATCH")
    validate_sdxl_lora_micro_sources(sources.lora_sources.training_command, original.crop_set)
    # No original PNG is copied into this workspace: conditioning has its own receipt identity.
    selected = {output.case_id: output for output in sources.extraction_result.outputs}
    pointers = []
    paths = []
    for case_id in command.case_ids:
        output = selected[case_id]
        pointer = ImageEvaluationArtifactMember(
            **{
                **command.extraction_result.model_dump(mode="json"),
                "member_path": output.conditioning_member_path,
                "sha256": output.conditioning_sha256,
                "schema_ref": "eom://schemas/image-provider/local-image-informative-lineart-extraction-conditioning/1.0",
                "media_type": "image/png",
            }
        )
        pointers.append(BoundedControlArtifactRead(pointer, output.conditioning_size_bytes))
        paths.append(f"inputs/conditioning/{case_id}.png")
    for file in sources.lora_sources.manifest.files:
        limit = 64 * 1024 if file.relative_path.endswith(".json") else 64 * 1024**2
        if file.size_bytes > limit:
            raise ValueError("SDXL_LEARNED_ADAPTER_SIZE_INVALID")
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
        pointers.append(BoundedControlArtifactRead(pointer, file.size_bytes))
        paths.append("inputs/adapter/" + file.relative_path)
    payloads = resolve_control_artifact_members(engine, tuple(pointers))
    files = [
        SdxlProbeInputMember(path, bounded.pointer.sha256, raw)
        for path, bounded, raw in zip(paths, pointers, payloads, strict=True)
    ]
    metadata["prompt-policy"] = original.policy_payload
    command_payload = content_json_bytes(command.model_dump(mode="json"))
    files.append(
        SdxlProbeInputMember(
            "command.json",
            "sha256:" + hashlib.sha256(command_payload).hexdigest(),
            command_payload,
        )
    )
    for name, raw in metadata.items():
        files.append(
            SdxlProbeInputMember(
                "inputs/" + name + ".json", "sha256:" + hashlib.sha256(raw).hexdigest(), raw
            )
        )
    return PreparedSdxlLearnedComparisonInputs(
        command, sources, tuple(sorted(files, key=lambda file: file.member_path))
    )
