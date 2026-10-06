"""Read-only parent/source metadata bridge, not staged pixels or execution authority."""

from __future__ import annotations

import json
from dataclasses import dataclass

from eom_image_contracts.models import content_json_bytes
from eom_image_contracts.sdxl_ip_style_comparison import (
    LocalImageSdxlIpStyleComparisonPlan,
    SdxlIpStyleSelectedSource,
    select_sdxl_ip_style_sources,
)
from eom_image_contracts.sdxl_ip_style_execution import (
    LocalImageSdxlIpStyleComparisonCommand,
    parse_sdxl_ip_style_command,
    parse_sdxl_ip_style_execution_plan,
)
from eom_image_contracts.sdxl_native_lora import LocalImageSdxlNativeLoraCommandV4
from eom_image_contracts.sdxl_photo_style_execution import (
    parse_photo_style_command,
    parse_photo_style_result,
    validate_photo_style_result,
)
from eom_image_contracts.sdxl_photo_style_result import LocalImageSdxlPhotoStyleResult
from eom_image_contracts.validation import validate_contract
from sqlalchemy import Engine

from eom_orchestrator.control_artifact_resolution import (
    BoundedControlArtifactRead,
    resolve_control_artifact_members,
)
from eom_orchestrator.sdxl_native_lora_inputs import (
    AdmittedSdxlNativeLoraSources,
    resolve_sdxl_native_lora_sources,
)
from eom_orchestrator.sdxl_photo_style_inputs import (
    ResolvedSdxlPhotoStyleExecutionMetadata,
    resolve_sdxl_photo_style_execution_metadata,
)


@dataclass(frozen=True, slots=True)
class ResolvedSdxlIpStyleSelectionMetadata:
    plan: LocalImageSdxlIpStyleComparisonPlan
    photo: ResolvedSdxlPhotoStyleExecutionMetadata
    photo_result: LocalImageSdxlPhotoStyleResult
    style: AdmittedSdxlNativeLoraSources
    cases: tuple[SdxlIpStyleSelectedSource, ...]


@dataclass(frozen=True, slots=True)
class ResolvedSdxlIpStyleExecutionMetadata:
    """Canonical metadata admission only, not pixels/models/lease/permission to dispatch."""

    command: LocalImageSdxlIpStyleComparisonCommand
    selection: ResolvedSdxlIpStyleSelectionMetadata


def resolve_sdxl_ip_style_execution_metadata(
    engine: Engine, command: LocalImageSdxlIpStyleComparisonCommand
) -> ResolvedSdxlIpStyleExecutionMetadata:
    command = parse_sdxl_ip_style_command(command.model_dump(mode="json"))
    (raw,) = resolve_control_artifact_members(
        engine, (BoundedControlArtifactRead(command.plan, 64 * 1024),)
    )
    plan = parse_sdxl_ip_style_execution_plan(command, raw)
    selection = resolve_sdxl_ip_style_selection_metadata(engine, plan)
    if selection.plan != plan:
        raise ValueError("SDXL_IP_STYLE_EXECUTION_OWNER_PLAN_MISMATCH")
    return ResolvedSdxlIpStyleExecutionMetadata(command, selection)


def resolve_sdxl_ip_style_selection_metadata(
    engine: Engine, plan: LocalImageSdxlIpStyleComparisonPlan
) -> ResolvedSdxlIpStyleSelectionMetadata:
    """Canonical source owners admit lineage before any pixel/model load; no dispatch."""
    value = plan.model_dump(mode="json")
    validate_contract("sdxl-ip-style-comparison-plan", value)
    plan = LocalImageSdxlIpStyleComparisonPlan.model_validate(value)
    pointers = (plan.photo_command, plan.photo_result, plan.style_training_command)
    raw_command, raw_result, raw_style = resolve_control_artifact_members(
        engine, tuple(BoundedControlArtifactRead(pin, 256 * 1024) for pin in pointers)
    )
    command = parse_photo_style_command(json.loads(raw_command))
    result = parse_photo_style_result(json.loads(raw_result))
    validate_contract("sdxl-native-lora-command-v4", json.loads(raw_style))
    style_command = LocalImageSdxlNativeLoraCommandV4.model_validate_json(raw_style)
    for pointer, raw, document, version in zip(
        pointers,
        (raw_command, raw_result, raw_style),
        (command, result, style_command),
        (command.schema_version, result.schema_version, style_command.schema_version),
        strict=True,
    ):
        if (
            pointer.schema_ref != "eom://schemas/image-provider/" + version
            or raw != content_json_bytes(document.model_dump(mode="json"))
        ):
            raise ValueError("SDXL_IP_STYLE_PARENT_FAMILY_OR_CANONICAL_BYTES_INVALID")
    if (
        result.status != "SUCCEEDED"
        or result.completed_at > plan.created_at
        or command.created_at > plan.created_at
        or style_command.created_at > plan.created_at
    ):
        raise ValueError("SDXL_IP_STYLE_PARENT_STATUS_OR_CHRONOLOGY_INVALID")
    photo = resolve_sdxl_photo_style_execution_metadata(engine, command)
    validate_photo_style_result(command, photo.sources, result)
    style = resolve_sdxl_native_lora_sources(engine, style_command)
    if photo.command != command or style.command != style_command:
        raise ValueError("SDXL_IP_STYLE_OWNER_COMMAND_MISMATCH")
    cases = select_sdxl_ip_style_sources(
        plan,
        photo_cases=photo.sources.plan.cases,
        photo_traces=result.inputs,
        style_samples=style_command.training_samples,
        style_regions=style.sources.regions,
    )
    return ResolvedSdxlIpStyleSelectionMetadata(plan, photo, result, style, cases)
