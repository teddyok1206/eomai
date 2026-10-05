"""Closed command selection for the existing isolated paired-comparison entry point."""

from __future__ import annotations

import json
import os
from pathlib import Path

from eom_image_contracts.models import content_json_bytes
from eom_image_contracts.sdxl_canny_comparison import LocalImageSdxlCannyComparisonCommand
from eom_image_contracts.sdxl_canny_reference import LocalImageSdxlCannyReferenceCommand
from eom_image_contracts.sdxl_learned_comparison import LocalImageSdxlLearnedComparisonCommand
from eom_image_contracts.sdxl_native_canny_reference import parse_reference_command
from eom_image_contracts.sdxl_photo_style_execution import (
    LocalImageSdxlPhotoStyleCommand,
    parse_photo_style_command,
)
from eom_image_contracts.sdxl_target_comparison import LocalImageSdxlTargetComparisonCommand
from eom_image_contracts.sdxl_validation_comparison import (
    LocalImageSdxlValidationComparisonCommand,
    parse_sdxl_validation_command,
)
from eom_image_contracts.validation import validate_contract
from jsonschema import ValidationError as SchemaError

from eom_image_provider.provider import ProviderError
from eom_image_provider.staged_file_io import read_staged_member, verified_directory


def load_sdxl_comparison_command(
    workspace: Path,
    command_path: Path,
) -> (
    LocalImageSdxlLearnedComparisonCommand
    | LocalImageSdxlTargetComparisonCommand
    | LocalImageSdxlCannyComparisonCommand
    | LocalImageSdxlCannyReferenceCommand
    | LocalImageSdxlValidationComparisonCommand
    | LocalImageSdxlPhotoStyleCommand
):
    if command_path != workspace / "command.json":
        raise ProviderError("SDXL_PROBE_INPUT_INVALID")
    try:
        with verified_directory(workspace, expected_owner_uid=os.geteuid()) as root:
            raw = read_staged_member(root, "command.json", maximum_bytes=128 * 1024)
        value = json.loads(raw)
        schema = value.get("schema_version") if isinstance(value, dict) else None
        parsed: (
            LocalImageSdxlLearnedComparisonCommand
            | LocalImageSdxlTargetComparisonCommand
            | LocalImageSdxlCannyComparisonCommand
            | LocalImageSdxlCannyReferenceCommand
            | LocalImageSdxlValidationComparisonCommand
            | LocalImageSdxlPhotoStyleCommand
        )
        if schema == "local-image-sdxl-learned-comparison-command/1.0":
            validate_contract("sdxl-learned-comparison-command", value)
            parsed = LocalImageSdxlLearnedComparisonCommand.model_validate(value)
        elif schema == "local-image-sdxl-target-comparison-command/1.0":
            validate_contract("sdxl-target-comparison-command", value)
            parsed = LocalImageSdxlTargetComparisonCommand.model_validate(value)
        elif schema == "local-image-sdxl-canny-comparison-command/1.0":
            validate_contract("sdxl-canny-comparison-command", value)
            parsed = LocalImageSdxlCannyComparisonCommand.model_validate(value)
        elif schema in (
            "local-image-sdxl-canny-reference-command/1.0",
            "local-image-sdxl-canny-reference-command/1.1",
            "local-image-sdxl-canny-reference-command/1.2",
        ):
            parsed = parse_reference_command(value)
        elif schema in (
            "local-image-sdxl-validation-comparison-command/1.0",
            "local-image-sdxl-validation-comparison-command/1.1",
        ):
            parsed = parse_sdxl_validation_command(value)
        elif schema in (
            "local-image-sdxl-photo-style-command/1.0",
            "local-image-sdxl-photo-style-command/1.1",
        ):
            parsed = parse_photo_style_command(value)
        else:
            raise ValueError("unsupported paired comparison command family")
        if raw != content_json_bytes(parsed.model_dump(mode="json")):
            raise ValueError("noncanonical paired comparison command")
        return parsed
    except (ValueError, TypeError, SchemaError) as exc:
        raise ProviderError("SDXL_PROBE_INPUT_INVALID") from exc
