"""Canonical native source-set publication and read-only replay, owned by Orchestrator."""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from eom_image_contracts import INSTITUTIONAL_CROP_SCHEMA_REF, ImageEvaluationArtifactMember
from eom_image_contracts.models import content_json_bytes, content_sha256
from eom_image_contracts.source_page_crops import ScienceSourcePageCropMember
from eom_image_contracts.source_pdf_crops import (
    SOURCE_PDF_CROP_COMMAND_SCHEMA_REF,
    SOURCE_PDF_CROP_SET_SCHEMA_REF,
    LocalImageScienceSourcePdfCropCommand,
    LocalImageScienceSourcePdfCropSet,
    NativeSourcePdfRenderRequest,
    native_source_pdf_render_request,
    validate_native_source_pdf_crop_set,
)
from eom_image_contracts.validation import validate_contract
from sqlalchemy import Engine

from eom_orchestrator.control_artifact_resolution import (
    BoundedControlArtifactRead,
    resolve_control_artifact_member,
    resolve_control_artifact_members,
)
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
    PublishedControlFileSet,
)
from eom_orchestrator.settings import Settings
from eom_orchestrator.source_page_crop_processing import ScienceSourcePageCropPixels
from eom_orchestrator.source_pdf_crop_inputs import (
    iter_source_pdf_crop_payloads,
    prepare_source_pdf_crop_reads,
)
from eom_orchestrator.source_pdf_crop_processing import (
    process_source_pdf_crops,
    validate_native_source_pdf_crop_pixels,
)


@dataclass(frozen=True, slots=True)
class PublishedScienceSourcePdfCrops:
    crop_set: LocalImageScienceSourcePdfCropSet
    publication: PublishedControlFileSet


def _write(path: Path, raw: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())


def _command(
    engine: Engine, pointer: ImageEvaluationArtifactMember
) -> LocalImageScienceSourcePdfCropCommand:
    if (
        pointer.schema_ref != SOURCE_PDF_CROP_COMMAND_SCHEMA_REF
        or pointer.media_type != "application/json"
        or pointer.member_path != "manifests/science-source-pdf-crop-command.json"
    ):
        raise ValueError("NATIVE_PDF_CROP_COMMAND_POINTER_INVALID")
    raw = resolve_control_artifact_member(engine, pointer, maximum_bytes=128 * 1024)
    command = LocalImageScienceSourcePdfCropCommand.model_validate_json(raw)
    validate_contract("science-source-pdf-crop-command", command.model_dump(mode="json"))
    if content_json_bytes(command.model_dump(mode="json")) != raw:
        raise ValueError("NATIVE_PDF_CROP_COMMAND_NONCANONICAL")
    return command


def materialize_and_publish_source_pdf_crops(
    engine: Engine,
    settings: Settings,
    command_pointer: ImageEvaluationArtifactMember,
    *,
    workspace: Path,
    created_at: datetime,
    execution_source_commit: str,
    process: Callable[
        [NativeSourcePdfRenderRequest, bytes], tuple[ScienceSourcePageCropPixels, ...]
    ] = process_source_pdf_crops,
) -> PublishedScienceSourcePdfCrops:
    """Read unique PDFs once, render CPU frames and commit only the fully validated set.

    A failed/uncertain processor leaves local diagnostic files and the existing immutable
    command intact; no successful set is committed or automatically redispatched. Completed
    canonical results can be verified by read-only replay without running the renderer.
    """
    if not workspace.is_absolute() or os.path.lexists(workspace):
        raise ValueError("NATIVE_PDF_CROP_WORKSPACE_NOT_EXCLUSIVE")
    if re.fullmatch(r"[0-9a-f]{40}", execution_source_commit) is None:
        raise ValueError("NATIVE_PDF_CROP_EXECUTION_SOURCE_INVALID")
    command = _command(engine, command_pointer)
    if (
        created_at.tzinfo is None
        or created_at.utcoffset() != UTC.utcoffset(created_at)
        or (created_at < command.created_at)
    ):
        raise ValueError("NATIVE_PDF_CROP_TIMESTAMP_INVALID")
    prepared = prepare_source_pdf_crop_reads(engine, command)
    try:
        workspace.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise ValueError("NATIVE_PDF_CROP_WORKSPACE_NOT_EXCLUSIVE") from exc
    (workspace / "manifests").mkdir(mode=0o700)
    (workspace / "crops").mkdir(mode=0o700)
    members, files = [], []
    for read, raw in iter_source_pdf_crop_payloads(engine, prepared):
        request = native_source_pdf_render_request(command, read.source, read.selections)
        outputs = process(request, raw)
        if tuple(output.selection_id for output in outputs) != tuple(
            region.selection_id for region in request.regions
        ):
            raise ValueError("NATIVE_PDF_CROP_PROCESSING_COVERAGE_INVALID")
        for output in outputs:
            member = ScienceSourcePageCropMember(
                selection_id=output.selection_id,
                member_path="crops/" + output.selection_id + ".png",
                sha256="sha256:" + hashlib.sha256(output.payload).hexdigest(),
                size_bytes=len(output.payload),
                width_px=output.width_px,
                height_px=output.height_px,
                perceptual_hash=output.perceptual_hash,
            )
            validate_native_source_pdf_crop_pixels(member, output.payload)
            _write(workspace / member.member_path, output.payload)
            members.append(member)
            files.append(
                ControlFileSetMember(
                    member.member_path,
                    workspace / member.member_path,
                    member.sha256,
                    member.size_bytes,
                    INSTITUTIONAL_CROP_SCHEMA_REF,
                    "image/png",
                )
            )
    members.sort(key=lambda member: member.selection_id)
    value = {
        "schema_version": "local-image-science-source-pdf-crop-set/1.0",
        "crop_set_id": "imgpdfcropset_"
        + content_sha256({"selection_ids": command.selection_ids})[7:39],
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "command": command_pointer.model_dump(mode="json"),
        "command_sha256": command.command_sha256,
        "members": [member.model_dump(mode="json") for member in members],
        "state": "RENDERED_SOURCE_DERIVATIVES_PENDING_TARGET_REVIEW",
        "activation_policy": "FORBIDDEN",
    }
    value["crop_set_revision_id"] = "imgpdfcropsetrev_" + content_sha256(value)[7:39]
    value["crop_set_sha256"] = content_sha256(value)
    crop_set = LocalImageScienceSourcePdfCropSet.model_validate(value)
    validate_native_source_pdf_crop_set(
        command, prepared.review, crop_set, command_pointer=command_pointer
    )
    raw = content_json_bytes(crop_set.model_dump(mode="json"))
    name = "manifests/science-source-pdf-crop-set.json"
    _write(workspace / name, raw)
    files.append(
        ControlFileSetMember(
            name,
            workspace / name,
            "sha256:" + hashlib.sha256(raw).hexdigest(),
            len(raw),
            SOURCE_PDF_CROP_SET_SCHEMA_REF,
            "application/json",
        )
    )
    published = ControlFileSetPublisher(engine, settings).publish(
        members=tuple(sorted(files, key=lambda member: member.file_name)),
        primary_file=name,
        artifact_type="control_local_image_science_source_pdf_crop_set",
        manifest_version="science-source-pdf-crop-set-files/1.0",
        # One command has one canonical delivery; a changed timestamp/output must
        # conflict with its existing commit, not create another successful identity.
        idempotency_key="source-pdf-crop-set:" + command.command_sha256,
        source_commit=execution_source_commit,
        created_at=created_at,
    )
    if published.primary_sha256 != "sha256:" + hashlib.sha256(raw).hexdigest():
        raise ValueError("NATIVE_PDF_CROP_COMMIT_MISMATCH")
    return PublishedScienceSourcePdfCrops(crop_set, published)


def replay_published_source_pdf_crops(
    engine: Engine,
    pointer: ImageEvaluationArtifactMember,
) -> LocalImageScienceSourcePdfCropSet:
    """Resolve exact canonical lineage/PNG closure; zero PDF reads, render calls or writes."""
    if pointer.schema_ref != SOURCE_PDF_CROP_SET_SCHEMA_REF or (
        pointer.media_type != "application/json"
        or pointer.member_path != "manifests/science-source-pdf-crop-set.json"
    ):
        raise ValueError("NATIVE_PDF_CROP_SET_POINTER_INVALID")
    raw = resolve_control_artifact_member(engine, pointer, maximum_bytes=128 * 1024)
    crop_set = LocalImageScienceSourcePdfCropSet.model_validate_json(raw)
    if raw != content_json_bytes(crop_set.model_dump(mode="json")):
        raise ValueError("NATIVE_PDF_CROP_SET_NONCANONICAL")
    command = _command(engine, crop_set.command)
    prepared = prepare_source_pdf_crop_reads(engine, command)
    validate_native_source_pdf_crop_set(
        command, prepared.review, crop_set, command_pointer=crop_set.command
    )
    reads = tuple(
        BoundedControlArtifactRead(
            ImageEvaluationArtifactMember(
                artifact_id=pointer.artifact_id,
                artifact_revision_id=pointer.artifact_revision_id,
                member_path=member.member_path,
                schema_ref=INSTITUTIONAL_CROP_SCHEMA_REF,
                media_type="image/png",
                sha256=member.sha256,
            ),
            member.size_bytes,
        )
        for member in crop_set.members
    )
    payloads = resolve_control_artifact_members(engine, reads)
    for member, payload in zip(crop_set.members, payloads, strict=True):
        validate_native_source_pdf_crop_pixels(member, payload)
    return crop_set
