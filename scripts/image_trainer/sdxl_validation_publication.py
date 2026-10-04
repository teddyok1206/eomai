"""Orchestrator-owned validation and publication of one reserved GPU diagnostic."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

from eom_image_contracts.models import ImageEvaluationArtifactMember, content_json_bytes
from eom_image_contracts.sdxl_validation_comparison import LocalImageSdxlValidationComparisonCommand
from eom_image_provider.sdxl_canny_pixels import (
    canny_conditioning_canvas_png,
    read_canny_runtime,
    sdxl_canny_native_source_canvas,
)
from eom_image_provider.sdxl_lineart_probe import sdxl_publication
from eom_image_provider.sdxl_validation_comparison import validate_sdxl_validation_workspace_result
from eom_image_provider.staged_file_io import read_staged_member, verified_directory
from eom_orchestrator.control_artifact_resolution import resolve_control_artifact_member
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
    PublishedControlFileSet,
)
from eom_orchestrator.sdxl_validation_inputs import prepare_sdxl_validation_inputs
from sqlalchemy import Engine

_PREFIX = "eom://schemas/image-provider/local-image-"


def publish_sdxl_validation_comparison(
    engine: Engine,
    command: LocalImageSdxlValidationComparisonCommand,
    *,
    command_pointer: ImageEvaluationArtifactMember,
    workspace: Path,
    worker_uid: int,
    source_commit: str,
    created_at: datetime,
) -> PublishedControlFileSet:
    """Readmit canonical source/adapter lineage before any Artifact mutation.

    Workspace comparisons and CPU transform checks are an explicit validation boundary.
    No worker, model, GPU, implicit latest or command identity is created here.
    """
    if (
        created_at.tzinfo is None
        or created_at.utcoffset() != UTC.utcoffset(created_at)
        or command_pointer.schema_ref != _PREFIX + "sdxl-validation-comparison-command/1.0"
        or command_pointer.member_path != "manifests/sdxl-validation-comparison-command.json"
        or command_pointer.media_type != "application/json"
    ):
        raise ValueError("SDXL_VALIDATION_PUBLICATION_COMMAND_INVALID")
    command_raw = resolve_control_artifact_member(engine, command_pointer, maximum_bytes=128 * 1024)
    if command_raw != content_json_bytes(command.model_dump(mode="json")):
        raise ValueError("SDXL_VALIDATION_PUBLICATION_COMMAND_MISMATCH")
    prepared = prepare_sdxl_validation_inputs(engine, command)
    sources = prepared.metadata.sources
    spatial = sources.configuration.sources.spatial_sources
    if (
        metadata.version("Pillow") != sources.configuration.command.initialization.pillow_version
        or read_canny_runtime() != spatial.preparation.runtime
    ):
        raise ValueError("SDXL_VALIDATION_PUBLICATION_RUNTIME_INVALID")
    result = validate_sdxl_validation_workspace_result(
        command=command, sources=sources, workspace=workspace, expected_owner_uid=worker_uid
    )
    if created_at < result.completed_at:
        raise ValueError("SDXL_VALIDATION_PUBLICATION_TIME_INVALID")
    payloads = {file.member_path: file.payload for file in prepared.files}
    cases = {entry.case.case_id: entry.case for entry in command.cases}
    members = []
    with verified_directory(workspace, expected_owner_uid=worker_uid) as root:
        for file in prepared.files:
            if (
                read_staged_member(
                    root,
                    file.member_path,
                    maximum_bytes=len(file.payload),
                    expected_sha256=file.sha256,
                )
                != file.payload
            ):
                raise ValueError("SDXL_VALIDATION_PUBLICATION_INPUT_MISMATCH")

        def admit(
            name: str,
            schema: str,
            *,
            sha: str | None = None,
            size: int = 16 * 1024**2,
            destination: str | None = None,
        ) -> bytes:
            raw = read_staged_member(
                root, name, maximum_bytes=size, expected_sha256=sha, expected_owner_uid=worker_uid
            )
            members.append(
                ControlFileSetMember(
                    destination or name,
                    workspace / name,
                    "sha256:" + hashlib.sha256(raw).hexdigest(),
                    len(raw),
                    _PREFIX + schema,
                    "application/json" if name.endswith(".json") else "image/png",
                )
            )
            return raw

        primary = "manifests/sdxl-validation-comparison-result.json"
        admit("result.json", "sdxl-validation-comparison-result/1.0", destination=primary)
        for trace in result.inputs:
            case = cases[trace.case_id]
            canvas = sdxl_canny_native_source_canvas(
                payloads[case.staged_member_path],
                width_px=case.reference_width_px,
                height_px=case.reference_height_px,
            )
            if (
                "sha256:" + hashlib.sha256(canvas.convert("RGB").tobytes()).hexdigest()
                != trace.initialization_rgb_sha256
            ):
                raise ValueError("SDXL_VALIDATION_PUBLICATION_INITIALIZER_MISMATCH")
            control = admit(
                "conditionings/" + trace.case_id + ".png",
                "sdxl-canny-conditioning-output/1.0",
                sha=trace.conditioning_sha256,
            )
            if control != canny_conditioning_canvas_png(canvas, policy=spatial.preparation.policy):
                raise ValueError("SDXL_VALIDATION_PUBLICATION_CANNY_MISMATCH")
            admit("initializers/" + trace.case_id + ".png", "sdxl-validation-initializer/1.0")
        for output in result.outputs:
            raw = admit(
                output.raw_member_path,
                "sdxl-lineart-probe-raw/1.0",
                sha=output.raw_sha256,
                size=output.raw_size_bytes,
            )
            final = admit(
                output.member_path,
                "sdxl-lineart-probe-output/1.0",
                sha=output.sha256,
                size=output.size_bytes,
            )
            if final != sdxl_publication(raw):
                raise ValueError("SDXL_VALIDATION_PUBLICATION_OUTPUT_MISMATCH")
    # The command has its own immutable Artifact; results never duplicate source PNGs.
    return ControlFileSetPublisher(engine).publish(
        members=tuple(sorted(members, key=lambda member: member.file_name)),
        primary_file=primary,
        artifact_type="control_local_image_sdxl_validation_result",
        manifest_version="sdxl-validation-comparison-result-artifact/1.0",
        idempotency_key="sdxl-validation-result:" + command.command_sha256[7:],
        source_commit=source_commit,
        created_at=created_at,
    )
