"""Closed schema dispatch shared by publication, admission and the isolated evaluator."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from eom_image_contracts.sdxl_lora_evaluation import (
    LocalImageSdxlLoraEvaluationCommand,
    LocalImageSdxlLoraEvaluationResult,
)
from eom_image_contracts.sdxl_native_evaluation import (
    LocalImageSdxlNativeEvaluationCommand,
    LocalImageSdxlNativeEvaluationResult,
)
from eom_image_contracts.sdxl_reviewed_evaluation import (
    LocalImageSdxlReviewedEvaluationCommand,
    LocalImageSdxlReviewedEvaluationResult,
)
from eom_image_contracts.validation import validate_contract

_COMMANDS: Mapping[str, tuple[str, type[LocalImageSdxlLoraEvaluationCommand]]] = MappingProxyType(
    {
        "local-image-sdxl-lora-evaluation-command/1.0": (
            "sdxl-lora-evaluation-command",
            LocalImageSdxlLoraEvaluationCommand,
        ),
        "local-image-sdxl-lora-evaluation-command/1.1": (
            "sdxl-lora-evaluation-command-v2",
            LocalImageSdxlReviewedEvaluationCommand,
        ),
        "local-image-sdxl-lora-evaluation-command/1.2": (
            "sdxl-lora-evaluation-command-v3",
            LocalImageSdxlNativeEvaluationCommand,
        ),
    }
)
_RESULTS: Mapping[str, tuple[str, type[LocalImageSdxlLoraEvaluationResult]]] = MappingProxyType(
    {
        "local-image-sdxl-lora-evaluation-result/1.0": (
            "sdxl-lora-evaluation-result",
            LocalImageSdxlLoraEvaluationResult,
        ),
        "local-image-sdxl-lora-evaluation-result/1.1": (
            "sdxl-lora-evaluation-result-v2",
            LocalImageSdxlReviewedEvaluationResult,
        ),
        "local-image-sdxl-lora-evaluation-result/1.2": (
            "sdxl-lora-evaluation-result-v3",
            LocalImageSdxlNativeEvaluationResult,
        ),
    }
)


def sdxl_evaluation_command_contract(command: LocalImageSdxlLoraEvaluationCommand) -> str:
    entry = _COMMANDS.get(command.schema_version)
    if entry is None or type(command) is not entry[1]:
        raise ValueError("SDXL_EVALUATION_COMMAND_FAMILY_INVALID")
    return entry[0]


def parse_sdxl_evaluation_command(value: object) -> LocalImageSdxlLoraEvaluationCommand:
    if not isinstance(value, dict) or not isinstance(value.get("schema_version"), str):
        raise ValueError("SDXL_EVALUATION_COMMAND_FAMILY_INVALID")
    entry = _COMMANDS.get(value["schema_version"])
    if entry is None:
        raise ValueError("SDXL_EVALUATION_COMMAND_FAMILY_INVALID")
    validate_contract(entry[0], value)
    return entry[1].model_validate(value)


def parse_sdxl_evaluation_result(value: object) -> LocalImageSdxlLoraEvaluationResult:
    if not isinstance(value, dict) or not isinstance(value.get("schema_version"), str):
        raise ValueError("SDXL_EVALUATION_RESULT_FAMILY_INVALID")
    entry = _RESULTS.get(value["schema_version"])
    if entry is None:
        raise ValueError("SDXL_EVALUATION_RESULT_FAMILY_INVALID")
    validate_contract(entry[0], value)
    return entry[1].model_validate(value)
