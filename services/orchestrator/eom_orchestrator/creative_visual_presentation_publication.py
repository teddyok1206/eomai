"""Commit a directly verified original-image rendition; Item/Graph/INDEX remain untouched."""

from __future__ import annotations

import os
import stat
import struct
import zlib
from collections.abc import Callable, Mapping
from pathlib import Path
from tempfile import TemporaryDirectory

from eom_catalog_contracts.assessment_item import AssessmentItemContent
from eom_catalog_contracts.creative_bitmap_presentation import (
    CreativeBitmapPresentationManifest,
    RecoveredBitmapVisual,
    VisualPresentationManifest,
    read_visual_presentation_manifest,
    visual_presentation_schema_ref,
)
from eom_catalog_contracts.creative_visual_derivation import derive_creative_visual_content
from eom_catalog_contracts.creative_visual_presentation import (
    VISUAL_PRESENTATION_ARTIFACT_TYPE,
    VISUAL_PRESENTATION_CONTENT_MEMBER,
    VISUAL_PRESENTATION_CONTENT_SCHEMA_REF,
    VISUAL_PRESENTATION_MEMBER,
    RecoveredSourceVisual,
    visual_presentation_key,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes

from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetIdentity,
    ControlFileSetMember,
    ControlFileSetPublisher,
    PublishedControlFileSet,
)

WHOLE_SOURCE_PNG_SCHEMA_REF = "eom://schemas/external-item/whole-source-png/1.0"


def _read_verified_png(path: Path, visual: RecoveredSourceVisual | RecoveredBitmapVisual) -> bytes:
    if not path.is_absolute():
        raise ValueError("CREATIVE_VISUAL_PUBLICATION_IMAGE_INVALID")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size != visual.content_length
        ):
            raise ValueError("CREATIVE_VISUAL_PUBLICATION_IMAGE_INVALID")
        payload = stream.read(16 * 1024 * 1024 + 1)
        after = os.fstat(stream.fileno())
    if (
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        or len(payload) != visual.content_length
        or sha256_bytes(payload) != visual.sha256
        or len(payload) < 33
        or payload[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        or struct.unpack(">II", payload[16:24]) != (visual.width_px, visual.height_px)
        or struct.unpack(">I", payload[29:33])[0] != zlib.crc32(payload[12:29]) & 0xFFFFFFFF
    ):
        raise ValueError("CREATIVE_VISUAL_PUBLICATION_IMAGE_MISMATCH")
    return payload


def publish_creative_visual_presentation(
    publisher: ControlFileSetPublisher,
    *,
    identity: ControlFileSetIdentity,
    manifest: VisualPresentationManifest,
    canonical: AssessmentItemContent,
    image_files: Mapping[str, Path],
    source_commit: str,
    authorize: Callable[[str], None],
) -> PublishedControlFileSet:
    """The caller reauthorizes the real operator and the exact original source.

    Only an already compared embedded-image selection is admitted. Raster parsing
    and extraction happen in the local document/image adapter, never in a Codex
    slot. The existing publisher alone owns NAS/transaction/replay behavior.
    """
    schema_ref = visual_presentation_schema_ref(manifest)
    manifest = read_visual_presentation_manifest(manifest.model_dump(mode="json"), schema_ref)
    if content_sha256(canonical.model_dump(mode="json")) != manifest.canonical_content.sha256:
        raise ValueError("CREATIVE_VISUAL_PUBLICATION_SOURCE_MISMATCH")
    expected = {visual.canonical_block_id for visual in manifest.visuals}
    if set(image_files) != expected:
        raise ValueError("CREATIVE_VISUAL_PUBLICATION_IMAGE_SET_MISMATCH")
    display = derive_creative_visual_content(
        canonical,
        manifest,
        artifact_id=identity.artifact_id,
        artifact_revision_id=identity.artifact_revision_id,
    )
    content = canonical_json_bytes(display.model_dump(mode="json"))
    if sha256_bytes(content) != manifest.content_sha256:
        raise ValueError("CREATIVE_VISUAL_PUBLICATION_CONTENT_MISMATCH")
    authorize(manifest.authorized_by_operator_id)
    with TemporaryDirectory(
        prefix="creative-visual-presentation-", dir=publisher.settings.staging_root
    ) as raw:
        workspace = Path(raw)
        content_path = workspace / VISUAL_PRESENTATION_CONTENT_MEMBER
        content_path.write_bytes(content)
        content_path.chmod(0o400)
        manifest_payload = canonical_json_bytes(manifest.model_dump(mode="json"))
        manifest_path = workspace / VISUAL_PRESENTATION_MEMBER
        manifest_path.write_bytes(manifest_payload)
        manifest_path.chmod(0o400)
        members = [
            ControlFileSetMember(
                VISUAL_PRESENTATION_CONTENT_MEMBER,
                content_path,
                manifest.content_sha256,
                len(content),
                VISUAL_PRESENTATION_CONTENT_SCHEMA_REF,
                "application/json",
            ),
            ControlFileSetMember(
                VISUAL_PRESENTATION_MEMBER,
                manifest_path,
                sha256_bytes(manifest_payload),
                len(manifest_payload),
                schema_ref,
                "application/json",
            ),
        ]
        seen: set[str] = set()
        (workspace / "images").mkdir()
        for visual in manifest.visuals:
            payload = _read_verified_png(image_files[visual.canonical_block_id], visual)
            if visual.member_path in seen:
                continue
            path = workspace / visual.member_path
            path.write_bytes(payload)
            path.chmod(0o400)
            members.append(
                ControlFileSetMember(
                    visual.member_path,
                    path,
                    visual.sha256,
                    visual.content_length,
                    (
                        "eom://schemas/external-item/source-bitmap-region-png/1.0"
                        if isinstance(manifest, CreativeBitmapPresentationManifest)
                        else WHOLE_SOURCE_PNG_SCHEMA_REF
                    ),
                    "image/png",
                )
            )
            seen.add(visual.member_path)
        authorize(manifest.authorized_by_operator_id)
        published = publisher.publish_identified(
            identity=identity,
            members=tuple(sorted(members, key=lambda member: member.file_name)),
            primary_file=VISUAL_PRESENTATION_CONTENT_MEMBER,
            artifact_type=VISUAL_PRESENTATION_ARTIFACT_TYPE,
            manifest_version=manifest.schema_version,
            idempotency_key=visual_presentation_key(manifest.item_revision_id),
            source_commit=source_commit,
            created_at=manifest.created_at,
        )
    authorize(manifest.authorized_by_operator_id)
    return published
