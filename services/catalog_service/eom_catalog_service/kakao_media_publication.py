"""Bounded original-photo validation and existing Artifact-owner publication.

No names, rooms, timestamps or association decisions enter this dedup receipt.
The content owner authorizes the binding, resolves observed attachment identity,
and adopts the returned pointers in its own short transaction. This adapter grants
neither source access nor permission to read a blob from its SHA alone.
"""

from __future__ import annotations

import io
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from eom_catalog_contracts.kakao_archive import KakaoBindingId
from eom_catalog_contracts.kakao_media import (
    MAX_MEDIA_BYTES,
    MAX_MEDIA_PIXELS,
    MEDIA_BLOB_REF,
    MEDIA_FORMAT_REF,
    KakaoMediaBlobReceipt,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import TypeAdapter

from eom_catalog_service.artifacts import CatalogArtifactService

_EXTENSIONS = {"image/png": "png", "image/jpeg": "jpeg", "image/webp": "webp"}


@dataclass(frozen=True, slots=True)
class KakaoMediaPublication:
    receipt: KakaoMediaBlobReceipt
    original: ArtifactMemberPointer
    manifest: ArtifactMemberPointer
    publication_job_id: str


def inspect_kakao_media(source_binding_id: str, source: bytes) -> KakaoMediaBlobReceipt:
    """Inspect bounded headers before decoding pixels; never rewrite original bytes."""
    binding = TypeAdapter(KakaoBindingId).validate_python(source_binding_id)
    if type(source) is not bytes or not 0 < len(source) <= MAX_MEDIA_BYTES:
        raise ValueError("KAKAO_ARCHIVE_MEDIA_SIZE_INVALID")
    # This decoder is an explicit optional Kakao runtime dependency. Feature-off
    # Catalog imports must not require a browser/PDF environment or ambient packages.
    try:
        from PIL import Image
    except ImportError:
        raise ValueError("KAKAO_ARCHIVE_MEDIA_DECODER_UNAVAILABLE") from None
    try:
        with Image.open(io.BytesIO(source), formats=("PNG", "JPEG", "WEBP")) as image:
            width, height = image.size
            media_type = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[
                image.format or ""
            ]
            if (
                type(width) is not int
                or type(height) is not int
                or not 0 < width <= 30_000
                or not 0 < height <= 30_000
                or width * height > MAX_MEDIA_PIXELS
            ):
                raise ValueError("KAKAO_ARCHIVE_MEDIA_DIMENSIONS_INVALID")
            if getattr(image, "n_frames", 1) != 1:
                raise ValueError("KAKAO_ARCHIVE_MEDIA_ANIMATION_UNSUPPORTED")
            image.verify()
        with Image.open(io.BytesIO(source), formats=("PNG", "JPEG", "WEBP")) as image:
            image.load()
            if image.size != (width, height):
                raise ValueError("KAKAO_ARCHIVE_MEDIA_DIMENSIONS_INVALID")
    except ValueError as error:
        if str(error) in {
            "KAKAO_ARCHIVE_MEDIA_DIMENSIONS_INVALID",
            "KAKAO_ARCHIVE_MEDIA_ANIMATION_UNSUPPORTED",
        }:
            raise
        raise ValueError("KAKAO_ARCHIVE_MEDIA_DECODE_FAILED") from None
    except Exception:
        raise ValueError("KAKAO_ARCHIVE_MEDIA_DECODE_FAILED") from None
    return KakaoMediaBlobReceipt.model_validate(
        dict(
            source_binding_id=binding,
            source_sha256=sha256_bytes(source),
            source_bytes=len(source),
            media_type=media_type,
            width_px=width,
            height_px=height,
            pixel_count=width * height,
        )
    )


def publish_kakao_media(
    artifacts: CatalogArtifactService,
    *,
    source_binding_id: str,
    source: bytes,
    authorize: Callable[[], None],
) -> KakaoMediaPublication:
    authorize()
    receipt = inspect_kakao_media(source_binding_id, source)
    receipt_bytes = canonical_json_bytes(receipt.model_dump(mode="json"))
    manifest_sha256 = sha256_bytes(receipt_bytes)
    member = "original." + _EXTENSIONS[receipt.media_type]
    with tempfile.TemporaryDirectory(
        prefix="kakao-media.", dir=artifacts.settings.staging_root
    ) as folder:
        root = Path(folder)
        (root / member).write_bytes(source)
        (root / "media.json").write_bytes(receipt_bytes)
        authorize()
        artifact = artifacts.commit_file_set(
            files={member: root / member, "media.json": root / "media.json"},
            primary_file="media.json",
            artifact_type="kakao-media-blob",
            idempotency_key=f"kakao:media:{receipt.source_binding_id}:{receipt.source_sha256[7:]}",
            request=receipt.model_dump(mode="json"),
            result={"receipt_sha256": manifest_sha256},
            file_metadata={
                member: {"schema_ref": MEDIA_FORMAT_REF, "media_type": receipt.media_type},
                "media.json": {"schema_ref": MEDIA_BLOB_REF, "media_type": "application/json"},
            },
            expected_file_sha256={member: receipt.source_sha256, "media.json": manifest_sha256},
        )
    if artifact.content_hash != manifest_sha256 or artifact.content_bytes != len(receipt_bytes):
        raise ValueError("KAKAO_ARCHIVE_PUBLICATION_MISMATCH")
    authorize()
    return KakaoMediaPublication(
        receipt=receipt,
        original=ArtifactMemberPointer(
            artifact_id=artifact.artifact_id,
            artifact_revision_id=artifact.revision_id,
            member_path=member,
            schema_ref=MEDIA_FORMAT_REF,
            media_type=receipt.media_type,
            sha256=receipt.source_sha256,
        ),
        manifest=ArtifactMemberPointer(
            artifact_id=artifact.artifact_id,
            artifact_revision_id=artifact.revision_id,
            member_path="media.json",
            schema_ref=MEDIA_BLOB_REF,
            media_type="application/json",
            sha256=manifest_sha256,
        ),
        publication_job_id=artifact.job_id,
    )
