"""Explicit private PDF input materialization, never a renderer or NAS writer."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast

from eom_catalog_contracts.kakao_question import KakaoQuestionImage
from eom_identifiers import sha256_bytes
from eom_kakao_archive_contracts import LocalMember, canonical_bytes
from eom_kakao_archive_contracts.pdf_contracts import PdfManifest
from eom_orchestrator.kakao_pdf_files import (
    local_directory,
    read_local,
    require_owner_directory,
    write_local,
)
from eom_protocol.artifact_members import ArtifactMemberPointer

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.kakao_packet_service import AcceptedKakaoPacket
from eom_catalog_service.kakao_question_editing import (
    packet_student_subset,
    validate_question_sources,
)
from eom_catalog_service.kakao_question_service import ResolvedKakaoQuestions
from eom_catalog_service.kakao_render_projection import (
    KakaoRenderImageInput,
    image_pointer_key,
    project_kakao_student_render,
)
from eom_catalog_service.kakao_study_projection import project_kakao_student_study

MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_IMAGES_BYTES = 256 * 1024 * 1024
MAX_FONT_BYTES = 32 * 1024 * 1024
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
_EXTENSION = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


@dataclass(frozen=True, slots=True)
class KakaoPreparedPdfInputs:
    manifest: PdfManifest = field(repr=False)
    manifest_member: LocalMember
    font_member: LocalMember
    images: tuple[KakaoRenderImageInput, ...]
    source_root: Path = field(repr=False)


def _font_bytes(path: Path, member: LocalMember) -> bytes:
    if (
        member.relative_path != "font.otf"
        or member.media_type != "font/otf"
        or member.size_bytes > MAX_FONT_BYTES
    ):
        raise ValueError("KAKAO_ARCHIVE_RENDER_FONT_INVALID")
    # The installed profile owns this path; no browser/worker chooses a font path.
    with local_directory(path.parent) as parent:
        fd = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent
        )
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid not in {0, os.geteuid()}
            or before.st_mode & 0o022
            or before.st_size != member.size_bytes
        ):
            raise ValueError("KAKAO_ARCHIVE_RENDER_FONT_INVALID")
        raw = stream.read(member.size_bytes + 1)
        after = os.fstat(stream.fileno())
        if (
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            or len(raw) != member.size_bytes
            or sha256_bytes(raw) != member.sha256
        ):
            raise ValueError("KAKAO_ARCHIVE_RENDER_FONT_INVALID")
        return raw


def prepare_kakao_pdf_inputs(
    artifacts: CatalogArtifactService,
    *,
    packet: AcceptedKakaoPacket,
    student_id: str,
    selection: ResolvedKakaoQuestions,
    source_root: Path,
    font_source: Path,
    font: LocalMember,
    authorize: Callable[[], None],
    layout_policy: Literal[
        "student-question-a4/1.0", "student-study-a4/1.0"
    ] = "student-question-a4/1.0",
) -> KakaoPreparedPdfInputs:
    """Only exact selected sources are staged, once per binary pointer.

    The caller allocates a new local input directory and owns the cleanup policy.
    No file is overwritten and this function grants no source/read/run authority.
    """
    if not callable(authorize):
        raise ValueError("KAKAO_ARCHIVE_RENDER_AUTHORITY_REQUIRED")
    authorize()
    if layout_policy not in {"student-question-a4/1.0", "student-study-a4/1.0"}:
        raise ValueError("KAKAO_ARCHIVE_RENDER_LAYOUT_POLICY_INVALID")
    if (
        source_root == artifacts.settings.staging_root
        or not source_root.is_relative_to(artifacts.settings.staging_root)
        or source_root.is_relative_to(artifacts.settings.nas_artifact_root)
    ):
        raise ValueError("KAKAO_ARCHIVE_RENDER_STAGING_ROOT_INVALID")
    require_owner_directory(source_root, os.geteuid(), os.getgid())
    with local_directory(source_root) as directory:
        if os.listdir(directory):
            raise ValueError("KAKAO_ARCHIVE_RENDER_INPUT_NOT_EMPTY")
    font = LocalMember.model_validate(font.model_dump(mode="json"))
    subset = packet_student_subset(packet.packet, student_id)
    expected = tuple(
        (item.question_id, item.question_revision_id, item.room_id, item.student, item.manifest)
        for item in subset.questions
    )
    actual = tuple(
        (
            item.stored.question_id,
            item.stored.question_revision_id,
            item.stored.room_id,
            item.stored.student,
            item.stored.manifest,
        )
        for item in selection.questions
    )
    if actual != expected:
        raise ValueError("KAKAO_ARCHIVE_RENDER_QUESTION_SET_MISMATCH")
    contexts = {
        item.resolved.normalization.normalization_revision_id: item.resolved
        for item in selection.sources
    }
    required_sources = {
        pin.normalization_revision_id
        for item in selection.questions
        for pin in item.published.question.sources
    }
    if len(contexts) != len(selection.sources) or set(contexts) != required_sources:
        raise ValueError("KAKAO_ARCHIVE_RENDER_SOURCE_SET_MISMATCH")
    for item in selection.questions:
        validate_question_sources(
            item.published.question,
            tuple(
                contexts[pin.normalization_revision_id] for pin in item.published.question.sources
            ),
        )
    raw_font = _font_bytes(font_source, font)
    write_local(source_root, "font.otf", raw_font, gid=os.getgid())
    pointers: dict[tuple[str, ...], ArtifactMemberPointer] = {}
    for item in selection.questions:
        for block in item.published.question.ordered_blocks:
            if (
                isinstance(block, KakaoQuestionImage)
                and block.source_pointer is not None
                and (block.role == "student" or packet.packet.include_replies)
            ):
                pointers.setdefault(image_pointer_key(block.source_pointer), block.source_pointer)
    images = []
    total = 0
    for ordinal, pointer in enumerate(pointers.values(), 1):
        if pointer.media_type not in _EXTENSION:
            raise ValueError("KAKAO_ARCHIVE_RENDER_IMAGE_MEDIA_INVALID")
        opened = artifacts.open_verified_member(
            artifact_id=pointer.artifact_id,
            revision_id=pointer.artifact_revision_id,
            member_path=pointer.member_path,
            sha256=pointer.sha256,
            schema_ref=pointer.schema_ref,
            media_type=pointer.media_type,
            max_bytes=MAX_IMAGE_BYTES,
        )
        with opened.stream as stream:
            total += opened.content_length
            if total > MAX_IMAGES_BYTES:
                raise ValueError("KAKAO_ARCHIVE_RENDER_INPUT_TOO_LARGE")
            raw = stream.read(MAX_IMAGE_BYTES + 1)
            if len(raw) != opened.content_length or sha256_bytes(raw) != pointer.sha256:
                raise ValueError("KAKAO_ARCHIVE_RENDER_IMAGE_HASH_MISMATCH")
        name = f"image-{ordinal:04d}." + _EXTENSION[pointer.media_type]
        member = LocalMember(
            relative_path=name,
            sha256=pointer.sha256,
            size_bytes=len(raw),
            media_type=cast(Literal["image/png", "image/jpeg", "image/webp"], pointer.media_type),
        )
        write_local(source_root, name, raw, gid=os.getgid())
        images.append(KakaoRenderImageInput(pointer, member))
    projector = (
        project_kakao_student_study
        if layout_policy == "student-study-a4/1.0"
        else project_kakao_student_render
    )
    manifest = projector(
        packet=packet.packet,
        student_id=student_id,
        questions=tuple(item.published for item in selection.questions),
        sources=tuple(item.resolved for item in selection.sources),
        images=tuple(images),
    )
    raw_manifest = canonical_bytes(manifest.model_dump(mode="json"))
    if len(raw_manifest) > MAX_MANIFEST_BYTES:
        raise ValueError("KAKAO_ARCHIVE_RENDER_INPUT_TOO_LARGE")
    write_local(source_root, "manifest.json", raw_manifest, gid=os.getgid())
    manifest_member = LocalMember(
        relative_path="manifest.json",
        sha256=sha256_bytes(raw_manifest),
        size_bytes=len(raw_manifest),
        media_type="application/json",
    )
    authorize()
    # Revalidate the same local materialization; no source path survives in the wire manifest.
    if (
        read_local(source_root, "manifest.json", limit=MAX_MANIFEST_BYTES, uid=os.geteuid())
        != raw_manifest
    ):
        raise ValueError("KAKAO_ARCHIVE_RENDER_INPUT_CHANGED")
    return KakaoPreparedPdfInputs(manifest, manifest_member, font, tuple(images), source_root)
