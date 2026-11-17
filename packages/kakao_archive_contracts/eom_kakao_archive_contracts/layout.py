"""Measured page receipts; acceptance rules are shared by worker and owner."""

from itertools import pairwise
from typing import Annotated, Literal

from pydantic import Field

from .render import (
    AttachmentId,
    AttachmentRevisionId,
    FrozenModel,
    QuestionRevisionId,
    RenderCommand,
    RenderImageCrop,
    RenderImageReference,
    RenderImageTransform,
    RenderManifest,
    RenderQuestion,
    RenderTextReference,
    Sha256,
    canonical_bytes,
    sha256,
)

Coordinate = Annotated[float, Field(ge=0, le=842, allow_inf_nan=False, strict=True)]
Bounds = tuple[Coordinate, Coordinate, Coordinate, Coordinate]


class TextLayout(FrozenModel):
    span_id: str = Field(min_length=1, max_length=128)
    start_codepoint: int = Field(ge=0, le=20000, strict=True)
    end_codepoint: int = Field(ge=0, le=20000, strict=True)
    bounds_pt: Bounds


class ImageLayout(FrozenModel):
    attachment_occurrence_id: AttachmentId
    attachment_revision_id: AttachmentRevisionId
    source_sha256: Sha256 | None
    display_transform: Literal["exif-rotate-crop-to-png/1.0"] | None
    display_sha256: Sha256 | None
    display_size_bytes: int | None = Field(ge=1, le=67108864, strict=True)
    display_width_px: int | None = Field(ge=1, le=67108864, strict=True)
    display_height_px: int | None = Field(ge=1, le=67108864, strict=True)
    availability: Literal["AVAILABLE", "MISSING", "UNRESOLVED", "EXPIRED"]
    bounds_pt: Bounds
    crop: RenderImageCrop | None
    transform: RenderImageTransform | None


class PageLayoutReceipt(FrozenModel):
    question_revision_id: QuestionRevisionId
    page_number: int = Field(ge=1, le=200, strict=True)
    font_size_pt: Annotated[float, Field(strict=True)]
    image_columns: int = Field(ge=1, le=2, strict=True)
    text_blocks: tuple[TextLayout, ...] = Field(max_length=20000)
    image_blocks: tuple[ImageLayout, ...] = Field(max_length=30)


class RenderLayoutReceipt(FrozenModel):
    schema_version: Literal["kakao-question-layout-receipt/1.0"]
    command_sha256: Sha256
    manifest_sha256: Sha256
    font_sha256: Sha256
    layout_policy: Literal["student-question-a4/1.0"]
    renderer_release_sha256: Sha256
    mode: Literal["DRAFT", "FINAL"]
    pages: tuple[PageLayoutReceipt, ...] = Field(min_length=1, max_length=200)


def check_layout_receipt(
    command: RenderCommand, manifest: RenderManifest, receipt: RenderLayoutReceipt
) -> None:
    """Reject missing text/photo uses and stale pins without parsing binary PDFs in core."""
    if (
        receipt.command_sha256 != sha256(canonical_bytes(command.model_dump(mode="json")))
        or receipt.manifest_sha256 != command.manifest.sha256
        or receipt.font_sha256 != command.font.sha256
        or receipt.layout_policy != command.layout_policy
        or receipt.renderer_release_sha256 != command.renderer_release_sha256
        or receipt.mode != command.mode
        or len(receipt.pages) != len(manifest.questions)
    ):
        raise ValueError("KAKAO_RENDER_LAYOUT_PINS_MISMATCH")
    for number, (page, question) in enumerate(
        zip(receipt.pages, manifest.questions, strict=True), 1
    ):
        check_page_layout(question, page, number, mode=command.mode)


def check_page_layout(
    question: RenderQuestion,
    page: PageLayoutReceipt,
    number: int,
    *,
    mode: Literal["DRAFT", "FINAL"],
) -> None:
    """Common per-page coverage/geometry rule; each family owns global ordering."""
    if (
        page.question_revision_id != question.question_revision_id
        or page.page_number != number
        or page.font_size_pt not in (10.0, 11.0)
    ):
        raise ValueError("KAKAO_RENDER_LAYOUT_PAGE_INVALID")
    # Ordered ranges include hard breaks, so text cannot disappear between lines.
    lines = iter(page.text_blocks)
    for block in question.text_blocks:
        end = 0
        while end < len(block.text):
            line = next(lines, None)
            if (
                line is None
                or line.span_id != block.span_id
                or line.start_codepoint != end
                or not end < line.end_codepoint <= len(block.text)
            ):
                raise ValueError("KAKAO_RENDER_LAYOUT_TEXT_MISSING")
            _check_bounds(line.bounds_pt)
            end = line.end_codepoint
    if next(lines, None) is not None or len(page.image_blocks) != len(question.images):
        raise ValueError("KAKAO_RENDER_LAYOUT_CONTENT_MISMATCH")
    for image, rendered in zip(question.images, page.image_blocks, strict=True):
        if (
            rendered.attachment_occurrence_id != image.attachment_occurrence_id
            or rendered.attachment_revision_id != image.attachment_revision_id
            or rendered.source_sha256 != (image.member.sha256 if image.member else None)
            or rendered.availability != image.availability
            or rendered.display_transform
            != ("exif-rotate-crop-to-png/1.0" if image.member else None)
            or rendered.transform != image.transform
            or rendered.crop != (image.transform.crop if image.transform else None)
            or (mode == "FINAL" and (not image.member or not image.quality_accepted))
        ):
            raise ValueError("KAKAO_RENDER_LAYOUT_IMAGE_MISMATCH")
        derivative_values = (
            rendered.display_sha256,
            rendered.display_size_bytes,
            rendered.display_width_px,
            rendered.display_height_px,
        )
        if (image.member and any(value is None for value in derivative_values)) or (
            not image.member and any(value is not None for value in derivative_values)
        ):
            raise ValueError("KAKAO_RENDER_LAYOUT_DERIVATIVE_INVALID")
        _check_bounds(rendered.bounds_pt)
        x0, y0, x1, y1 = rendered.bounds_pt
        if min(x1 - x0, y1 - y0) < 127.55:
            raise ValueError("KAKAO_RENDER_LAYOUT_IMAGE_TOO_SMALL")
        if (
            rendered.display_width_px is not None
            and rendered.display_height_px is not None
            and (
                rendered.display_width_px * rendered.display_height_px > 40000000
                or abs(
                    (x1 - x0) * rendered.display_height_px - (y1 - y0) * rendered.display_width_px
                )
                > 0.01 * max(rendered.display_width_px, rendered.display_height_px)
            )
        ):
            raise ValueError("KAKAO_RENDER_LAYOUT_IMAGE_ASPECT_INVALID")
    _check_order(question, page)


def _check_order(question: RenderQuestion, page: PageLayoutReceipt) -> None:
    """Linear ordered flow check: text spans and adjacent photo rows cannot overlap."""
    text_bounds: dict[str, list[Bounds]] = {}
    for line in page.text_blocks:
        text_bounds.setdefault(line.span_id, []).append(line.bounds_pt)
    image_bounds = {image.attachment_occurrence_id: image.bounds_pt for image in page.image_blocks}
    cursor, index = 86.0, 0
    while index < len(question.ordered_blocks):
        ref = question.ordered_blocks[index]
        if isinstance(ref, RenderTextReference):
            for bounds in text_bounds[ref.span_id]:
                if bounds[1] < cursor - 0.01:
                    raise ValueError("KAKAO_RENDER_LAYOUT_ORDER_INVALID")
                cursor = bounds[3]
            index += 1
            continue
        row: list[Bounds] = []
        while index < len(question.ordered_blocks) and isinstance(
            question.ordered_blocks[index], RenderImageReference
        ):
            image_ref = question.ordered_blocks[index]
            assert isinstance(image_ref, RenderImageReference)
            row.append(image_bounds[image_ref.attachment_occurrence_id])
            index += 1
            next_is_text = index == len(question.ordered_blocks) or isinstance(
                question.ordered_blocks[index], RenderTextReference
            )
            if len(row) == page.image_columns or next_is_text:
                if any(
                    bounds[1] < cursor - 0.01 or abs(bounds[1] - row[0][1]) > 0.01 for bounds in row
                ):
                    raise ValueError("KAKAO_RENDER_LAYOUT_ORDER_INVALID")
                if any(left[2] > right[0] + 0.01 for left, right in pairwise(row)):
                    raise ValueError("KAKAO_RENDER_LAYOUT_OVERLAP")
                cursor = max(bounds[3] for bounds in row)
                row = []


def _check_bounds(bounds: Bounds) -> None:
    x0, y0, x1, y1 = bounds
    if not (34.0 <= x0 <= x1 <= 561.3 and 86 <= y0 < y1 <= 790):
        raise ValueError("KAKAO_RENDER_LAYOUT_BOUNDS_INVALID")
