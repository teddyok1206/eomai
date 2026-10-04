"""Bounded metadata-only source admission shared by generation and CPU publication."""

from __future__ import annotations

import json

from eom_image_contracts.models import content_json_bytes
from eom_image_contracts.sdxl_lineart_probe import (
    LocalImageSdxlLineartProbeCommand,
    LocalImageSdxlLineartPromptPolicy,
)
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

from eom_image_provider.staged_file_io import read_staged_member


def read_sdxl_target_comparison_metadata(
    root: int, command: LocalImageSdxlTargetComparisonCommand
) -> dict[str, bytes]:
    evaluation_raw = read_staged_member(
        root,
        "inputs/lora-evaluation-command.json",
        maximum_bytes=256 * 1024,
        expected_sha256=command.lora_evaluation_command.sha256,
    )
    evaluation = LocalImageSdxlReviewedEvaluationCommand.model_validate_json(evaluation_raw)
    metadata = {"inputs/lora-evaluation-command.json": evaluation_raw}
    pin = evaluation.evaluation
    for name, pointer in (
        ("baseline-command", pin.baseline_command),
        ("training-command", pin.training_command),
        ("training-result", pin.training_result),
        ("adapter-manifest", pin.adapter_manifest),
    ):
        metadata["inputs/" + name + ".json"] = read_staged_member(
            root,
            "inputs/" + name + ".json",
            maximum_bytes=256 * 1024,
            expected_sha256=pointer.sha256,
        )
    training = LocalImageSdxlReviewedMicroCommand.model_validate_json(
        metadata["inputs/training-command.json"]
    )
    crop_raw = read_staged_member(
        root,
        "inputs/source-crop-set.json",
        maximum_bytes=2 * 1024**2,
        expected_sha256=training.source_crop_set.sha256,
    )
    for name, pointer in sdxl_reviewed_micro_metadata_pointers(training, crop_raw).items():
        metadata[name] = (
            crop_raw
            if name == "inputs/source-crop-set.json"
            else read_staged_member(
                root, name, maximum_bytes=2 * 1024**2, expected_sha256=pointer.sha256
            )
        )
    baseline = LocalImageSdxlLineartProbeCommand.model_validate_json(
        metadata["inputs/baseline-command.json"]
    )
    policy_raw = read_staged_member(
        root,
        "inputs/prompt-policy.json",
        maximum_bytes=256 * 1024,
        expected_sha256=baseline.prompt_policy.sha256,
    )
    value = json.loads(policy_raw)
    validate_contract("sdxl-lineart-prompt-policy", value)
    policy = LocalImageSdxlLineartPromptPolicy.model_validate(value)
    # The historical policy authenticates numerical/source provenance, not new target membership.
    if policy.cases != baseline.cases or policy_raw != content_json_bytes(
        policy.model_dump(mode="json")
    ):
        raise ValueError("target comparison baseline prompt provenance mismatch")
    metadata["inputs/prompt-policy.json"] = policy_raw
    return metadata


def read_sdxl_target_comparison_sources(
    root: int, command: LocalImageSdxlTargetComparisonCommand
) -> SdxlTargetComparisonSources:
    return parse_sdxl_target_comparison_sources(
        command, read_sdxl_target_comparison_metadata(root, command)
    )
