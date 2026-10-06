"""Orchestrator-owned validation and publication of one reserved GPU diagnostic."""

from __future__ import annotations

import hashlib
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from eom_image_contracts.models import ImageEvaluationArtifactMember, content_json_bytes
from eom_image_contracts.sdxl_photo_style_execution import (
    LocalImageSdxlPhotoObjectSupportResult,
    LocalImageSdxlPhotoStyleCommand,
    LocalImageSdxlPhotoStyleResult,
)
from eom_image_contracts.sdxl_validation_comparison import (
    LocalImageSdxlValidationComparisonCommand,
    LocalImageSdxlValidationComparisonResult,
)
from eom_image_provider.sdxl_photo_style import validate_sdxl_photo_style_workspace_result
from eom_image_provider.sdxl_validation_comparison import validate_sdxl_validation_workspace_result
from eom_image_provider.staged_file_io import read_staged_member, verified_directory
from eom_orchestrator.control_artifact_resolution import resolve_control_artifact_member
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
    PublishedControlFileSet,
)
from eom_orchestrator.sdxl_photo_style_inputs import prepare_sdxl_photo_style_inputs
from eom_orchestrator.sdxl_validation_inputs import prepare_sdxl_validation_inputs
from sqlalchemy import Engine

_PREFIX = "eom://schemas/image-provider/local-image-"


def verify_reserved_transforms_cpu(workspace: Path, expected_result: bytes) -> None:
    """Fixed no-DB numerical adapter; reuse the result schema, not another IPC family."""
    if workspace.parent != Path("/srv/eom/image-training-workspaces"):
        raise ValueError("SDXL_VALIDATION_PUBLICATION_WORKSPACE_INVALID")
    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "from eom_image_contracts.models import content_json_bytes\n"
        "from eom_image_provider.sdxl_reference_transform_verification "
        "import verify_sdxl_initialized_reference_transforms\n"
        "r=verify_sdxl_initialized_reference_transforms(Path(sys.argv[1]))\n"
        "assert 'torch' not in sys.modules\n"
        "sys.stdout.buffer.write(content_json_bytes(r.model_dump(mode='json')))\n"
    )
    try:
        completed = subprocess.run(
            [
                "/usr/sbin/runuser",
                "--user",
                "eom-image",
                "--",
                "/srv/eom/conda/envs/eom-image-trainer/bin/python",
                "-I",
                "-c",
                script,
                str(workspace),
            ],
            capture_output=True,
            check=False,
            timeout=60,
            env={
                "PATH": "/usr/bin:/bin",
                "PYTHONNOUSERSITE": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "CUDA_VISIBLE_DEVICES": "",
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
            },
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("SDXL_VALIDATION_PUBLICATION_CPU_UNAVAILABLE") from exc
    if completed.returncode != 0 or not 0 < len(completed.stdout) <= 256 * 1024:
        raise ValueError("SDXL_VALIDATION_PUBLICATION_CPU_FAILED")
    if completed.stdout != expected_result:
        raise ValueError("SDXL_VALIDATION_PUBLICATION_CPU_RESULT_MISMATCH")


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
    return _publish_initialized_reference_comparison(
        engine,
        command,
        command_pointer=command_pointer,
        workspace=workspace,
        worker_uid=worker_uid,
        source_commit=source_commit,
        created_at=created_at,
    )


def publish_sdxl_photo_style_comparison(
    engine: Engine,
    command: LocalImageSdxlPhotoStyleCommand,
    *,
    command_pointer: ImageEvaluationArtifactMember,
    workspace: Path,
    worker_uid: int,
    source_commit: str,
    created_at: datetime,
) -> PublishedControlFileSet:
    return _publish_initialized_reference_comparison(
        engine,
        command,
        command_pointer=command_pointer,
        workspace=workspace,
        worker_uid=worker_uid,
        source_commit=source_commit,
        created_at=created_at,
    )


def _publish_initialized_reference_comparison(
    engine: Engine,
    command: LocalImageSdxlValidationComparisonCommand | LocalImageSdxlPhotoStyleCommand,
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
    family = (
        "sdxl-photo-style"
        if isinstance(command, LocalImageSdxlPhotoStyleCommand)
        else "sdxl-validation-comparison"
    )
    if (
        created_at.tzinfo is None
        or created_at.utcoffset() != UTC.utcoffset(created_at)
        or command_pointer.schema_ref != "eom://schemas/image-provider/" + command.schema_version
        or command_pointer.member_path != "manifests/" + family + "-command.json"
        or command_pointer.media_type != "application/json"
    ):
        raise ValueError("SDXL_VALIDATION_PUBLICATION_COMMAND_INVALID")
    command_raw = resolve_control_artifact_member(engine, command_pointer, maximum_bytes=128 * 1024)
    if command_raw != content_json_bytes(command.model_dump(mode="json")):
        raise ValueError("SDXL_VALIDATION_PUBLICATION_COMMAND_MISMATCH")
    result: LocalImageSdxlPhotoStyleResult | LocalImageSdxlValidationComparisonResult
    if isinstance(command, LocalImageSdxlPhotoStyleCommand):
        photo_prepared = prepare_sdxl_photo_style_inputs(engine, command)
        files = photo_prepared.files
        result = validate_sdxl_photo_style_workspace_result(
            command=command,
            sources=photo_prepared.metadata.sources,
            workspace=workspace,
            expected_owner_uid=worker_uid,
        )
    else:
        prepared = prepare_sdxl_validation_inputs(engine, command)
        files = prepared.files
        result = validate_sdxl_validation_workspace_result(
            command=command,
            sources=prepared.metadata.sources,
            workspace=workspace,
            expected_owner_uid=worker_uid,
        )
    if created_at < result.completed_at:
        raise ValueError("SDXL_VALIDATION_PUBLICATION_TIME_INVALID")
    members = []
    with verified_directory(workspace, expected_owner_uid=worker_uid) as root:
        for file in files:
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
        verify_reserved_transforms_cpu(
            workspace, content_json_bytes(result.model_dump(mode="json"))
        )

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

        primary = "manifests/" + family + "-result.json"
        admit(
            "result.json", result.schema_version.removeprefix("local-image-"), destination=primary
        )
        for trace in result.inputs:
            # 1.6 consumes an existing canonical candidate. The local conditioning
            # file is a validation/workspace materialization, not a second Artifact.
            if not isinstance(result, LocalImageSdxlPhotoObjectSupportResult):
                admit(
                    "conditionings/" + trace.case_id + ".png",
                    "sdxl-canny-conditioning-output/1.0",
                    sha=trace.conditioning_sha256,
                )
            admit("initializers/" + trace.case_id + ".png", "sdxl-validation-initializer/1.0")
        for output in result.outputs:
            admit(
                output.raw_member_path,
                "sdxl-lineart-probe-raw/1.0",
                sha=output.raw_sha256,
                size=output.raw_size_bytes,
            )
            admit(
                output.member_path,
                "sdxl-lineart-probe-output/1.0",
                sha=output.sha256,
                size=output.size_bytes,
            )
    # The command has its own immutable Artifact; results never duplicate source PNGs.
    return ControlFileSetPublisher(engine).publish(
        members=tuple(sorted(members, key=lambda member: member.file_name)),
        primary_file=primary,
        artifact_type="control_local_image_sdxl_photo_style_result"
        if isinstance(command, LocalImageSdxlPhotoStyleCommand)
        else "control_local_image_sdxl_validation_result",
        manifest_version=result.schema_version.removeprefix("local-image-").replace(
            "-result/", "-result-artifact/"
        ),
        idempotency_key=(
            "sdxl-photo-style-result:"
            if isinstance(command, LocalImageSdxlPhotoStyleCommand)
            else "sdxl-validation-result:"
        )
        + command.command_sha256[7:],
        source_commit=source_commit,
        created_at=created_at,
    )
