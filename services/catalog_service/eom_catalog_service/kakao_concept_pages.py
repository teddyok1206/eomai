"""Exact textbook page materialization; local crops are unadopted derivatives, not Artifacts."""

from __future__ import annotations

import io
import math
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

from eom_catalog_contracts import EducationalDocumentKnowledgeSourceV4
from eom_catalog_contracts.material_knowledge_analysis import EducationalDocumentKnowledgeSourceV5
from eom_kakao_archive_contracts import LocalMember, canonical_bytes, sha256
from eom_kakao_archive_contracts.concepts import (
    ConceptComposeRequest,
    ConceptEvidenceContext,
    ConceptPage,
    ConceptResult,
    validate_concept_result,
)
from eom_orchestrator.kakao_pdf_files import (
    local_directory,
    read_pinned,
    require_owner_directory,
    write_local,
)
from eom_protocol.artifact_members import ArtifactMemberPointer

from .artifacts import CatalogArtifactReader
from .kakao_archive_authorization import KakaoArchiveError

if TYPE_CHECKING:
    from eom_catalog_contracts.knowledge import KnowledgeAnalysisDocumentMaterializationMemberV4
    from eom_catalog_contracts.material_knowledge_analysis import MaterialKnowledgePageMember
    from PIL.Image import Image

    from .kakao_concept_knowledge import (
        ConceptTextbookMaterial,
        ResolvedConceptTextbookKnowledge,
    )

MAX_PAGE_BYTES = 16 * 1024 * 1024
MAX_PAGE_TOTAL_BYTES = 96 * 1024 * 1024
MAX_PAGE_PIXELS = 16_000_000
MAX_PAGES_PER_EVIDENCE = 4
CROP_PROFILE = "textbook-original-png-crop/1.0"


@dataclass(frozen=True, slots=True)
class ConceptPageSource:
    page: ConceptPage
    original: ArtifactMemberPointer

    def __post_init__(self) -> None:
        if (
            self.page.member.sha256 != self.original.sha256
            or self.original.media_type != "image/png"
            or self.original.schema_ref != "eom://schemas/educational-document/page-image/1.0"
        ):
            raise KakaoArchiveError("KAKAO_CONCEPT_PAGE_POINTER_INVALID")


@dataclass(frozen=True, slots=True)
class PreparedConceptPages:
    knowledge: ResolvedConceptTextbookKnowledge
    context: ConceptEvidenceContext
    sources: tuple[ConceptPageSource, ...]
    source_root: Path = field(repr=False)

    def __post_init__(self) -> None:
        if self.context.pages != tuple(source.page for source in self.sources):
            raise KakaoArchiveError("KAKAO_CONCEPT_CAPTURE_CONTEXT_MISMATCH")
        originals: dict[
            tuple[str, int | None],
            KnowledgeAnalysisDocumentMaterializationMemberV4 | MaterialKnowledgePageMember,
        ] = {}
        for index, material in enumerate(self.knowledge.materials, 1):
            document_source = material.analysis.source
            if isinstance(
                document_source,
                (EducationalDocumentKnowledgeSourceV4, EducationalDocumentKnowledgeSourceV5),
            ):
                originals.update(
                    ((f"E{index}", member.physical_page), member)
                    for member in document_source.materialization_members
                    if member.member_kind == "PAGE_IMAGE"
                )
        for source in self.sources:
            page = source.page
            member = originals.get((page.evidence_key, page.physical_page))
            if (
                member is None
                or any(
                    getattr(source.original, name) != getattr(member, name)
                    for name in ArtifactMemberPointer.model_fields
                )
                or (page.width_pixels, page.height_pixels, page.member.size_bytes)
                != (member.width_pixels, member.height_pixels, member.bytes)
            ):
                raise KakaoArchiveError("KAKAO_CONCEPT_PAGE_POINTER_INVALID")


@dataclass(frozen=True, slots=True)
class PreparedConceptCapture:
    block_index: int
    capture_index: int
    page_key: str
    original: ArtifactMemberPointer
    pixel_bounds: tuple[int, int, int, int]
    member: LocalMember
    profile: str = CROP_PROFILE


def _private_root(artifacts: CatalogArtifactReader, root: Path) -> None:
    settings = artifacts.settings
    if (
        not root.is_absolute()
        or root == settings.staging_root
        or not root.is_relative_to(settings.staging_root)
        or root.is_relative_to(settings.nas_artifact_root)
    ):
        raise KakaoArchiveError("KAKAO_CONCEPT_STAGING_ROOT_INVALID")
    require_owner_directory(root, os.geteuid(), os.getgid())


def _private_empty_root(artifacts: CatalogArtifactReader, root: Path) -> None:
    _private_root(artifacts, root)
    with local_directory(root) as directory:
        if os.listdir(directory):
            raise KakaoArchiveError("KAKAO_CONCEPT_STAGING_NOT_EMPTY")


def _decode_page(raw: bytes, width: int, height: int) -> Image:
    # Pillow is already an optional Kakao-runtime dependency, never a pure-contract import.
    from PIL import Image as pillow_image

    if (
        not 0 < len(raw) <= MAX_PAGE_BYTES
        or not 0 < width <= 20_000
        or not 0 < height <= 20_000
        or width * height > MAX_PAGE_PIXELS
    ):
        raise KakaoArchiveError("KAKAO_CONCEPT_PAGE_DIMENSIONS_INVALID")
    try:
        with pillow_image.open(io.BytesIO(raw), formats=("PNG",)) as candidate:
            if candidate.size != (width, height) or getattr(candidate, "n_frames", 1) != 1:
                raise KakaoArchiveError("KAKAO_CONCEPT_PAGE_DIMENSIONS_INVALID")
            candidate.verify()
        with pillow_image.open(io.BytesIO(raw), formats=("PNG",)) as candidate:
            # PNG getexif() may load the image; verify() must run on the first fresh handle.
            if candidate.getexif().get(274, 1) != 1:
                raise KakaoArchiveError("KAKAO_CONCEPT_PAGE_ORIENTATION_UNSUPPORTED")
            candidate.load()
            return cast("Image", candidate.copy())
    except KakaoArchiveError:
        raise
    except Exception:
        raise KakaoArchiveError("KAKAO_CONCEPT_PAGE_DECODE_FAILED") from None


def _selected_page_members(material: ConceptTextbookMaterial) -> tuple[tuple[int, ...], bool]:
    """Use typed page attestations or exact members, never parse a prose locator."""
    source = material.analysis.source
    if not isinstance(
        source, (EducationalDocumentKnowledgeSourceV4, EducationalDocumentKnowledgeSourceV5)
    ):
        return (), False
    images = {
        member.physical_page: member
        for member in source.materialization_members
        if member.member_kind == "PAGE_IMAGE" and member.physical_page is not None
    }
    anchors = {anchor.anchor_id for anchor in material.analysis.selected_anchors}
    selected = set()
    for observation in material.analysis.page_observations:
        member = images.get(observation.physical_page)
        if member is None or member.sha256 != observation.image_sha256:
            raise KakaoArchiveError("KAKAO_CONCEPT_PAGE_OBSERVATION_MISMATCH")
        if set(observation.anchor_ids) & anchors:
            selected.add(observation.physical_page)
    by_member = {
        (member.artifact_revision_id, member.member_path): member.physical_page
        for member in source.materialization_members
        if member.member_kind != "INDEX"
    }
    for anchor in material.analysis.selected_anchors:
        number = by_member.get((anchor.artifact_revision_id, anchor.member_path))
        if number is not None:
            selected.add(number)
    if not selected and len(images) <= MAX_PAGES_PER_EVIDENCE:
        selected.update(images)
    numbers = tuple(sorted(selected))
    return numbers[:MAX_PAGES_PER_EVIDENCE], len(numbers) > MAX_PAGES_PER_EVIDENCE or not numbers


def prepare_kakao_concept_pages(
    artifacts: CatalogArtifactReader,
    *,
    knowledge: ResolvedConceptTextbookKnowledge,
    source_root: Path,
    authorize: Callable[[], None],
) -> PreparedConceptPages:
    """Caller reauthorizes the exact private question AND pinned public textbook sources."""
    authorize()
    _private_empty_root(artifacts, source_root)
    context = knowledge.worker_context().model_dump(mode="json", exclude={"context_sha256"})
    limitations = ["승인된 분석 텍스트는 교재 원문 인용이 아닙니다."]
    if not knowledge.materials:
        limitations.append("허용된 교재에서 관련 분석 근거를 찾지 못했습니다.")
    pages: list[ConceptPage] = []
    sources = []
    staged: dict[ArtifactMemberPointer, tuple[LocalMember, int, int]] = {}
    total = 0
    for index, material in enumerate(knowledge.materials, 1):
        key = f"E{index}"
        numbers, omitted = _selected_page_members(material)
        source = material.analysis.source
        if not isinstance(
            source, (EducationalDocumentKnowledgeSourceV4, EducationalDocumentKnowledgeSourceV5)
        ):
            limitations.append(
                f"{key}: 저장된 원문 PNG가 없는 분석 근거입니다. 그림을 열람하지 않았습니다."
            )
            continue
        images = {
            member.physical_page: member
            for member in source.materialization_members
            if member.member_kind == "PAGE_IMAGE"
        }
        for number in numbers:
            member = images[number]
            original = ArtifactMemberPointer.model_validate(
                {name: getattr(member, name) for name in ArtifactMemberPointer.model_fields}
            )
            if original not in staged:
                if total + member.bytes > MAX_PAGE_TOTAL_BYTES:
                    raise KakaoArchiveError("KAKAO_CONCEPT_PAGES_TOO_LARGE")
                raw = artifacts.read_member(
                    artifact_id=original.artifact_id,
                    revision_id=original.artifact_revision_id,
                    member_path=original.member_path,
                    sha256=original.sha256,
                    media_type=original.media_type,
                    schema_ref=original.schema_ref,
                    max_bytes=MAX_PAGE_BYTES,
                )
                if len(raw) != member.bytes or sha256(raw) != original.sha256:
                    raise KakaoArchiveError("KAKAO_CONCEPT_PAGE_HASH_MISMATCH")
                if member.width_pixels is None or member.height_pixels is None:
                    raise KakaoArchiveError("KAKAO_CONCEPT_PAGE_DIMENSIONS_INVALID")
                _decode_page(raw, member.width_pixels, member.height_pixels).close()
                local = LocalMember(
                    relative_path=f"pages/{key}P{number}.png",
                    sha256=original.sha256,
                    size_bytes=len(raw),
                    media_type="image/png",
                )
                write_local(source_root, local.relative_path, raw, gid=os.getgid())
                staged[original] = (local, member.width_pixels, member.height_pixels)
                total += len(raw)
            local, width, height = staged[original]
            if local.size_bytes != member.bytes:
                raise KakaoArchiveError("KAKAO_CONCEPT_PAGE_HASH_MISMATCH")
            if (width, height) != (member.width_pixels, member.height_pixels):
                raise KakaoArchiveError("KAKAO_CONCEPT_PAGE_DIMENSIONS_INVALID")
            page = ConceptPage(
                page_key=f"{key}P{number}",
                evidence_key=key,
                physical_page=number,
                width_pixels=width,
                height_pixels=height,
                member=local,
            )
            pages.append(page)
            sources.append(ConceptPageSource(page, original))
        if numbers:
            context["evidence"][index - 1]["location"] = (
                "제공한 원문 PNG의 물리 페이지 "
                + ", ".join(map(str, numbers))
                + " · 인쇄 쪽수 미확인"
            )
        if omitted:
            limitations.append(
                f"{key}: 선택 근거의 일부 원문 페이지가 미제공됐습니다. 제공된 그림만 확인하세요."
            )
    if not pages:
        limitations.append(
            "교재 원문 페이지를 제공하지 못했습니다. 인용·캡처 위치를 만들지 마세요."
        )
    context["pages"] = [page.model_dump(mode="json") for page in pages]
    context["limitations"] = limitations
    checked = ConceptEvidenceContext.model_validate(
        context | dict(context_sha256=sha256(canonical_bytes(context)))
    )
    authorize()
    return PreparedConceptPages(knowledge, checked, tuple(sources), source_root)


def prepare_kakao_concept_captures(
    artifacts: CatalogArtifactReader,
    *,
    prepared: PreparedConceptPages,
    request: ConceptComposeRequest,
    result: ConceptResult,
    output_root: Path,
    authorize: Callable[[], None],
) -> tuple[PreparedConceptCapture, ...]:
    """Read only supplied original PNGs; no resize, guessed coordinates or NAS publication."""
    authorize()
    _private_empty_root(artifacts, output_root)
    _private_root(artifacts, prepared.source_root)
    if request.context != prepared.context:
        raise KakaoArchiveError("KAKAO_CONCEPT_CAPTURE_CONTEXT_MISMATCH")
    validated = validate_concept_result(request, result.model_dump(mode="json"))
    if validated.output.phase != "COMPOSE":
        raise KakaoArchiveError("KAKAO_CONCEPT_CAPTURE_CONTEXT_MISMATCH")
    pages = {source.page.page_key: source for source in prepared.sources}
    if (
        len(pages) != len(prepared.sources)
        or tuple(source.page for source in prepared.sources) != prepared.context.pages
    ):
        raise KakaoArchiveError("KAKAO_CONCEPT_CAPTURE_CONTEXT_MISMATCH")
    # Group by original member, so aliases and repeated captures decode it only once.
    grouped: dict[ArtifactMemberPointer, list[tuple[int, int, str, tuple[int, int, int, int]]]] = {}
    for block_index, block in enumerate(validated.output.blocks):
        for capture_index, capture in enumerate(block.captures):
            source = pages[capture.page_key]
            page, rect = source.page, capture.rectangle
            bounds = (
                math.floor(rect.x * page.width_pixels),
                math.floor(rect.y * page.height_pixels),
                math.ceil((rect.x + rect.width) * page.width_pixels),
                math.ceil((rect.y + rect.height) * page.height_pixels),
            )
            if not (
                0 <= bounds[0] < bounds[2] <= page.width_pixels
                and 0 <= bounds[1] < bounds[3] <= page.height_pixels
            ):
                raise KakaoArchiveError("KAKAO_CONCEPT_CROP_OUTSIDE_PAGE")
            grouped.setdefault(source.original, []).append(
                (block_index, capture_index, page.page_key, bounds)
            )
    output = []
    total = 0
    for original, uses in grouped.items():
        page = pages[uses[0][2]].page
        raw = read_pinned(prepared.source_root, page.member, uid=os.geteuid(), gid=os.getgid())
        image = _decode_page(raw, page.width_pixels, page.height_pixels)
        local_by_bounds: dict[tuple[int, int, int, int], LocalMember] = {}
        try:
            for block_index, capture_index, page_key, bounds in uses:
                if bounds not in local_by_bounds:
                    identity = sha256(
                        canonical_bytes(
                            dict(
                                profile=CROP_PROFILE,
                                original=original.model_dump(mode="json"),
                                pixel_bounds=bounds,
                            )
                        )
                    )
                    with image.crop(bounds) as crop, io.BytesIO() as stream:
                        crop.save(stream, format="PNG")
                        payload = stream.getvalue()
                    total += len(payload)
                    if len(payload) > MAX_PAGE_BYTES or total > MAX_PAGE_TOTAL_BYTES:
                        raise KakaoArchiveError("KAKAO_CONCEPT_PAGES_TOO_LARGE")
                    member = LocalMember(
                        relative_path=f"captures/{identity[7:]}.png",
                        sha256=sha256(payload),
                        size_bytes=len(payload),
                        media_type="image/png",
                    )
                    write_local(output_root, member.relative_path, payload, gid=os.getgid())
                    local_by_bounds[bounds] = member
                output.append(
                    PreparedConceptCapture(
                        block_index,
                        capture_index,
                        page_key,
                        original,
                        bounds,
                        local_by_bounds[bounds],
                    )
                )
        finally:
            image.close()
    authorize()
    return tuple(sorted(output, key=lambda capture: (capture.block_index, capture.capture_index)))
