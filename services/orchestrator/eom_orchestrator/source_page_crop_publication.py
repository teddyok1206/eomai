"""One reviewed intent and one literal PNG file set, committed only by Orchestrator."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from eom_image_contracts import (
    INSTITUTIONAL_CROP_SCHEMA_REF,
    SOURCE_PAGE_CROP_REVIEW_SCHEMA_REF,
    SOURCE_PAGE_CROP_SET_SCHEMA_REF,
    ImageEvaluationArtifactMember,
    LocalImageScienceSourcePageCropReview,
    LocalImageScienceSourcePageCropSet,
    ScienceSourcePageCropMember,
    content_json_bytes,
    content_sha256,
    validate_contract,
    validate_source_page_crop_set,
)
from sqlalchemy import Engine

from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
    PublishedControlFileSet,
)
from eom_orchestrator.settings import Settings
from eom_orchestrator.source_page_crop_inputs import (
    iter_source_page_crop_payloads,
    prepare_source_page_crop_reads,
)
from eom_orchestrator.source_page_crop_processing import (
    ScienceSourcePageCropPixels,
    process_source_page_crops,
)


@dataclass(frozen=True, slots=True)
class PublishedScienceSourcePageCrops:
    review: PublishedControlFileSet
    crop_set: LocalImageScienceSourcePageCropSet
    publication: PublishedControlFileSet


def _write(path: Path, raw: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def materialize_and_publish_source_page_crops(
    engine: Engine,
    settings: Settings,
    review: LocalImageScienceSourcePageCropReview,
    *,
    workspace: Path,
    created_at: datetime,
    process: Callable[..., tuple[ScienceSourcePageCropPixels, ...]] = process_source_page_crops,
) -> PublishedScienceSourcePageCrops:
    """Admit, stage in a fresh workspace, process CPU inputs, publish immutable closure.

    A failed processor leaves the reviewed intent and workspace as evidence but publishes no
    successful crop set. Unknown completion is resolved by existing publisher idempotency,
    never by changing a review, generated pixels or key. The caller inspects failures explicitly.
    """
    if not workspace.is_absolute() or workspace.exists() or workspace.is_symlink():
        raise ValueError("SCIENCE_SOURCE_CROP_WORKSPACE_NOT_EXCLUSIVE")
    if (
        created_at.tzinfo is None
        or created_at.utcoffset() != review.created_at.utcoffset()
        or (created_at < review.created_at)
    ):
        raise ValueError("SCIENCE_SOURCE_CROP_TIMESTAMP_INVALID")
    reads = prepare_source_page_crop_reads(engine, review)
    workspace.mkdir(mode=0o700)
    (workspace / "manifests").mkdir(mode=0o700)
    (workspace / "crops").mkdir(mode=0o700)
    review_raw = content_json_bytes(review.model_dump(mode="json"))
    review_path = "manifests/science-source-page-crop-review.json"
    _write(workspace / review_path, review_raw)
    publisher = ControlFileSetPublisher(engine, settings)
    published_review = publisher.publish(
        members=(
            ControlFileSetMember(
                review_path,
                workspace / review_path,
                _sha(review_raw),
                len(review_raw),
                SOURCE_PAGE_CROP_REVIEW_SCHEMA_REF,
                "application/json",
            ),
        ),
        primary_file=review_path,
        artifact_type="control_local_image_science_source_page_crop_review",
        manifest_version="science-source-page-crop-review-files/1.0",
        idempotency_key="source-page-crop-review:" + review.review_sha256,
        source_commit=review.source_commit,
        created_at=review.created_at,
    )
    review_pointer = ImageEvaluationArtifactMember(
        artifact_id=published_review.artifact_id,
        artifact_revision_id=published_review.artifact_revision_id,
        member_path=published_review.primary_file,
        schema_ref=SOURCE_PAGE_CROP_REVIEW_SCHEMA_REF,
        media_type="application/json",
        sha256=published_review.primary_sha256,
    )
    if review_pointer.sha256 != _sha(review_raw):
        raise ValueError("SCIENCE_SOURCE_CROP_REVIEW_COMMIT_MISMATCH")
    outputs: list[ScienceSourcePageCropMember] = []
    file_members: list[ControlFileSetMember] = []
    for read, raw in iter_source_page_crop_payloads(engine, reads):
        processed = process(raw, read.selections, pillow_version=review.pillow_version)
        if tuple(output.selection_id for output in processed) != tuple(
            selection.selection_id for selection in read.selections
        ):
            raise ValueError("SCIENCE_SOURCE_CROP_PROCESSING_COVERAGE_INVALID")
        for selection, output in zip(read.selections, processed, strict=True):
            left, top, right, bottom = selection.pixel_box
            if (output.width_px, output.height_px) != (right - left, bottom - top):
                raise ValueError("SCIENCE_SOURCE_CROP_PROCESSING_DIMENSIONS_INVALID")
            path = "crops/" + output.selection_id + ".png"
            member = ScienceSourcePageCropMember(
                selection_id=output.selection_id,
                member_path=path,
                sha256=_sha(output.payload),
                size_bytes=len(output.payload),
                width_px=output.width_px,
                height_px=output.height_px,
                perceptual_hash=output.perceptual_hash,
            )
            _write(workspace / path, output.payload)
            outputs.append(member)
            file_members.append(
                ControlFileSetMember(
                    path,
                    workspace / path,
                    member.sha256,
                    member.size_bytes,
                    INSTITUTIONAL_CROP_SCHEMA_REF,
                    "image/png",
                )
            )
    outputs.sort(key=lambda member: member.selection_id)
    value: dict[str, object] = {
        "schema_version": "local-image-science-source-page-crop-set/1.0",
        "crop_set_id": "imgsourcecropset_"
        + content_sha256({"selection_ids": tuple(member.selection_id for member in outputs)})[7:39],
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "review": review_pointer.model_dump(mode="json"),
        "pillow_version": review.pillow_version,
        "members": [member.model_dump(mode="json") for member in outputs],
        "state": "REVIEWED_SOURCE_DERIVATIVES",
        "activation_policy": "FORBIDDEN",
    }
    value["crop_set_revision_id"] = "imgsourcecropsetrev_" + content_sha256(value)[7:39]
    value["crop_set_sha256"] = content_sha256(value)
    validate_contract("science-source-page-crop-set", value)
    crop_set = LocalImageScienceSourcePageCropSet.model_validate(value)
    validate_source_page_crop_set(review, crop_set)
    crop_raw = content_json_bytes(crop_set.model_dump(mode="json"))
    crop_path = "manifests/science-source-page-crop-set.json"
    _write(workspace / crop_path, crop_raw)
    file_members.append(
        ControlFileSetMember(
            crop_path,
            workspace / crop_path,
            _sha(crop_raw),
            len(crop_raw),
            SOURCE_PAGE_CROP_SET_SCHEMA_REF,
            "application/json",
        )
    )
    published_set = publisher.publish(
        members=tuple(sorted(file_members, key=lambda member: member.file_name)),
        primary_file=crop_path,
        artifact_type="control_local_image_science_source_page_crop_set",
        manifest_version="science-source-page-crop-set-files/1.0",
        idempotency_key="source-page-crop-set:" + crop_set.crop_set_sha256,
        source_commit=review.source_commit,
        created_at=created_at,
    )
    if published_set.primary_sha256 != _sha(crop_raw):
        raise ValueError("SCIENCE_SOURCE_CROP_SET_COMMIT_MISMATCH")
    return PublishedScienceSourcePageCrops(published_review, crop_set, published_set)
