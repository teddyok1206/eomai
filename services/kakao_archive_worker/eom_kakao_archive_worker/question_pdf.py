"""One question per A4 page, with bounded measured layout and no source cropping.

The caller supplies an already authorized immutable student subset. This worker
does not authorize sources, publish Artifacts, load URLs, or select another subset.
Layout cost is linear in text/pixels for a fixed four candidate layouts.
"""

from __future__ import annotations

import io
import json
import math
import os
import unicodedata
from contextlib import ExitStack
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pymupdf  # type: ignore[import-untyped]
from eom_kakao_archive_contracts import (
    LocalMember,
    RenderCommand,
    RenderImage,
    RenderImageReference,
    RenderImageTransform,
    RenderManifest,
    RenderQuestion,
    RenderResult,
    RenderTextReference,
    canonical_bytes,
    sha256,
)
from eom_kakao_archive_contracts.layout import RenderLayoutReceipt, check_layout_receipt
from eom_kakao_archive_contracts.render import render_input_members
from eom_kakao_archive_contracts.validation import validate_contract
from PIL import Image, ImageOps

from .local_members import directory_descriptor, read_member, write_member

PAGE_WIDTH, PAGE_HEIGHT = 595.276, 841.89
MARGIN, BODY_TOP, BODY_BOTTOM, GAP = 34.016, 86.0, 790.0, 8.0
MIN_IMAGE_SIDE = 127.56  # 45 mm; geometric minimum, not a claim of readable photo text.
MAX_PIXELS = 40_000_000
MAX_INPUT_BYTES = 256 * 1024 * 1024
MAX_TOTAL_PIXELS = 64_000_000
MAX_DISPLAY_BYTES = 256 * 1024 * 1024


class LayoutReview(ValueError):
    def __init__(self, code: str, revision_id: str | None = None):
        super().__init__(code)
        self.code = code
        self.revision_id = revision_id


@dataclass(frozen=True)
class TextLine:
    span_id: str
    start: int
    end: int
    text: str
    x: float
    baseline: float
    bounds: tuple[float, float, float, float]


@dataclass(frozen=True)
class PageLayout:
    font_size: float
    lines: tuple[TextLine, ...]
    image_bounds: tuple[tuple[float, float, float, float], ...]
    columns: int


def _fixed_coordinates(layout: PageLayout) -> PageLayout:
    """Freeze sub-micro-point float noise, not overflow: 790.0000000000001 is 790 pt."""

    def bounds(value: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        x0, y0, x1, y1 = value
        return round(x0, 6), round(y0, 6), round(x1, 6), round(y1, 6)

    return replace(
        layout,
        lines=tuple(
            replace(
                line,
                x=round(line.x, 6),
                baseline=round(line.baseline, 6),
                bounds=bounds(line.bounds),
            )
            for line in layout.lines
        ),
        image_bounds=tuple(bounds(rectangle) for rectangle in layout.image_bounds),
    )


def _check_glyphs(font: Any, text: str) -> None:
    for character in set(text):
        if character in "\n\r":
            continue
        if unicodedata.category(character).startswith("C") or not font.has_glyph(
            ord(character), fallback=False
        ):
            raise LayoutReview("UNSUPPORTED_GLYPH")


def _wrap(text: str, font: Any, size: float, width: float) -> tuple[tuple[int, int, str], ...]:
    """Preserve codepoint ranges and hard breaks; never split a combining cluster."""
    clusters: list[tuple[int, int, str]] = []
    for i, character in enumerate(text):
        if clusters and (
            unicodedata.combining(character) or (character == "\n" and clusters[-1][2] == "\r")
        ):
            start, _, previous = clusters[-1]
            clusters[-1] = (start, i + 1, previous + character)
        else:
            clusters.append((i, i + 1, character))
    lines: list[tuple[int, int, str]] = []
    start, current, used = 0, "", 0.0
    for i, end, cluster in clusters:
        if cluster in {"\n", "\r", "\r\n"}:
            lines.append((start, end, current))
            start, current, used = end, "", 0.0
            continue
        advance = float(font.text_length(cluster, fontsize=size))
        if advance > width:
            raise LayoutReview("NEEDS_LAYOUT_REVIEW")
        if used + advance > width:
            lines.append((start, i, current))
            start, current, used = i, "", 0.0
        current += cluster
        used += advance
    if start < len(text):
        lines.append((start, len(text), current))
    return tuple(lines)


def _layout(question: RenderQuestion, font: Any, images: tuple[tuple[int, int], ...]) -> PageLayout:
    width = PAGE_WIDTH - 2 * MARGIN
    runs: list[RenderTextReference | list[RenderImageReference]] = []
    for ref in question.ordered_blocks:
        if isinstance(ref, RenderTextReference):
            runs.append(ref)
        elif runs and isinstance(runs[-1], list):
            group = runs[-1]
            assert isinstance(group, list)
            group.append(ref)
        else:
            runs.append([ref])
    dimensions = {
        image.attachment_occurrence_id: size
        for image, size in zip(question.images, images, strict=True)
    }
    for size in (11.0, 10.0):
        line_height = max(size * 1.35, (font.ascender - font.descender) * size)
        wrapped = {
            block.span_id: _wrap(block.text, font, size, width) for block in question.text_blocks
        }
        text_height = sum(len(lines) * line_height for lines in wrapped.values())
        for columns in (1, 2):
            rows = sum(math.ceil(len(run) / columns) for run in runs if isinstance(run, list))
            gap_height = max(len(question.text_blocks) + rows - 1, 0) * GAP
            remaining = BODY_BOTTOM - BODY_TOP - text_height - gap_height
            if remaining < 0:
                continue
            cell_height = remaining / rows if rows else 0.0
            cell_width = (width - GAP * (columns - 1)) / columns
            lines: list[TextLine] = []
            image_bounds: dict[str, tuple[float, float, float, float]] = {}
            top, fits = BODY_TOP, True
            for run in runs:
                if isinstance(run, RenderTextReference):
                    for start, end, text in wrapped[run.span_id]:
                        bounds = (
                            MARGIN,
                            top,
                            MARGIN + float(font.text_length(text, fontsize=size)),
                            top + line_height,
                        )
                        lines.append(
                            TextLine(
                                run.span_id,
                                start,
                                end,
                                text,
                                MARGIN,
                                top + font.ascender * size,
                                bounds,
                            )
                        )
                        top += line_height
                    top += GAP
                else:
                    for index, image_ref in enumerate(run):
                        image_width, image_height = dimensions[image_ref.attachment_occurrence_id]
                        scale = min(cell_width / image_width, cell_height / image_height)
                        w, h = image_width * scale, image_height * scale
                        if min(w, h) < MIN_IMAGE_SIDE:
                            fits = False
                            break
                        x = MARGIN + (index % columns) * (cell_width + GAP)
                        y = top + (index // columns) * (cell_height + GAP)
                        image_bounds[image_ref.attachment_occurrence_id] = (x, y, x + w, y + h)
                    top += math.ceil(len(run) / columns) * (cell_height + GAP)
                if not fits:
                    break
            if fits:
                return _fixed_coordinates(
                    PageLayout(
                        size,
                        tuple(lines),
                        tuple(
                            image_bounds[image.attachment_occurrence_id]
                            for image in question.images
                        ),
                        columns,
                    )
                )
    raise LayoutReview("NEEDS_LAYOUT_REVIEW", question.question_revision_id)


def _validate_text_coverage(question: RenderQuestion, layout: PageLayout) -> None:
    blocks = {block.span_id: block.text for block in question.text_blocks}
    ends = dict.fromkeys(blocks, 0)
    for line in layout.lines:
        source = blocks[line.span_id]
        if (
            line.start != ends[line.span_id]
            or not line.start < line.end <= len(source)
            or source[line.start : line.end].rstrip("\r\n") != line.text
            or line.bounds[0] < MARGIN
            or line.bounds[1] < BODY_TOP
            or line.bounds[2] > PAGE_WIDTH - MARGIN + 0.01
            or line.bounds[3] > BODY_BOTTOM + 0.01
        ):
            raise ValueError("KAKAO_RENDER_TEXT_COVERAGE_INVALID")
        ends[line.span_id] = line.end
    if any(ends[span_id] != len(text) for span_id, text in blocks.items()):
        raise ValueError("KAKAO_RENDER_TEXT_COVERAGE_INVALID")


def _text_characters(text: str) -> str:
    # Extraction can normalize spaces/line endings; non-whitespace glyphs must remain exact.
    return "".join(c for c in unicodedata.normalize("NFC", text) if not c.isspace())


def _image_bytes(root: Path, image: RenderImage) -> tuple[bytes, tuple[int, int], int]:
    member = image.member
    assert member is not None
    raw = read_member(root, member)
    mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
    with Image.open(io.BytesIO(raw), formats=("PNG", "JPEG", "WEBP")) as source:
        if mime.get(source.format) != member.media_type:
            raise ValueError("KAKAO_RENDER_IMAGE_TYPE_INVALID")
        width, height = source.size
        if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
            raise ValueError("KAKAO_RENDER_IMAGE_PIXELS_EXCEEDED")
        if getattr(source, "n_frames", 1) != 1:
            raise ValueError("KAKAO_RENDER_ANIMATED_IMAGE_UNSUPPORTED")
        # A local display derivative; source bytes/hash remain unchanged.
        with ExitStack() as resources:
            current = ImageOps.exif_transpose(source)
            resources.callback(current.close)
            if image.transform is not None:
                rotation = image.transform.rotate_clockwise
                if rotation:
                    current = current.transpose(
                        {
                            90: Image.Transpose.ROTATE_270,
                            180: Image.Transpose.ROTATE_180,
                            270: Image.Transpose.ROTATE_90,
                        }[rotation]
                    )
                    resources.callback(current.close)
                crop = image.transform.crop
                if crop is not None:
                    rotated_width, rotated_height = current.size
                    rectangle = (
                        crop.left_ppm * rotated_width // 1000000,
                        crop.top_ppm * rotated_height // 1000000,
                        (crop.right_ppm * rotated_width + 999999) // 1000000,
                        (crop.bottom_ppm * rotated_height + 999999) // 1000000,
                    )
                    current = current.crop(rectangle)
                    resources.callback(current.close)
            converted = current.convert("RGBA" if "A" in current.getbands() else "RGB")
            resources.callback(converted.close)
            target = io.BytesIO()
            converted.save(target, format="PNG")
            return target.getvalue(), converted.size, width * height


def _manifest(command: RenderCommand, input_root: Path) -> RenderManifest:
    raw = read_member(input_root, command.manifest)
    decoded = json.loads(raw)
    validate_contract("manifest", decoded)
    value = RenderManifest.model_validate(decoded)
    render_input_members(command, value)
    return value


def render_questions(
    command: RenderCommand, *, input_root: Path, output_root: Path, renderer_release_sha256: str
) -> RenderResult:
    """Render only to an owner-created empty local directory. Never publishes results."""
    validate_contract("command", command.model_dump(mode="json"))
    command_hash = sha256(canonical_bytes(command.model_dump(mode="json")))
    base = {
        "export_id": command.export_id,
        "command_sha256": command_hash,
        "manifest_sha256": command.manifest.sha256,
    }
    try:
        if input_root.is_relative_to(output_root) or output_root.is_relative_to(input_root):
            raise ValueError("KAKAO_RENDER_WORKSPACE_OVERLAP")
        with directory_descriptor(output_root) as directory:
            if os.listdir(directory):
                raise ValueError("KAKAO_RENDER_OUTPUT_NOT_EMPTY")
        if command.renderer_release_sha256 != renderer_release_sha256:
            raise ValueError("KAKAO_RENDER_RELEASE_MISMATCH")
        manifest = _manifest(command, input_root)
        font_bytes = read_member(input_root, command.font)
        font = pymupdf.Font(fontbuffer=font_bytes)
        outputs = _render(command, manifest, font, font_bytes, input_root, output_root)
        result = RenderResult(
            execution=command.execution,
            schema_version="kakao-question-render-result/1.0",
            **base,
            status="COMPLETED",
            page_count=len(manifest.questions),
            outputs=outputs,
            error_code=None,
            question_revision_id=None,
        )
    except LayoutReview as exc:
        result = RenderResult(
            execution=command.execution,
            schema_version="kakao-question-render-result/1.0",
            **base,
            status="NEEDS_LAYOUT_REVIEW",
            page_count=0,
            outputs=(),
            error_code=exc.code,
            question_revision_id=exc.revision_id,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        # Never expose parser errors containing text, filenames or credentials.
        code = str(exc)
        if not code.startswith("KAKAO_RENDER_") or len(code) > 80:
            code = "KAKAO_RENDER_INPUT_OR_OUTPUT_INVALID"
        result = RenderResult(
            execution=command.execution,
            schema_version="kakao-question-render-result/1.0",
            **base,
            status="INVALID_INPUT",
            page_count=0,
            outputs=(),
            error_code=code,
            question_revision_id=None,
        )
    validate_contract("result", result.model_dump(mode="json"))
    return result


def _render(
    command: RenderCommand,
    manifest: RenderManifest,
    font: Any,
    font_bytes: bytes,
    input_root: Path,
    output_root: Path,
) -> tuple[LocalMember, ...]:
    _check_glyphs(font, manifest.student_display_name + "검토용 질문 미확보 사진")
    plans = []
    image_cache: dict[
        tuple[LocalMember, RenderImageTransform | None], tuple[bytes, tuple[int, int], int]
    ] = {}
    total_pixels, total_display_bytes = 0, 0
    for number, question in enumerate(manifest.questions, 1):
        header = f"{manifest.student_display_name} · 질문 {number} · {question.header_date}"
        if manifest.mode == "DRAFT":
            header = "[검토용] " + header
        _check_glyphs(font, header)
        if font.text_length(header, fontsize=11) > PAGE_WIDTH - 2 * MARGIN:
            raise LayoutReview("HEADER_OVERFLOW", question.question_revision_id)
        for block in question.text_blocks:
            try:
                _check_glyphs(font, block.text)
            except LayoutReview as exc:
                raise LayoutReview(exc.code, question.question_revision_id) from exc
        images: list[tuple[bytes | None, tuple[int, int]]] = []
        for image in question.images:
            if image.member is None:
                if manifest.mode == "FINAL":
                    raise LayoutReview("REQUIRED_IMAGE_UNAVAILABLE", question.question_revision_id)
                images.append((None, (400, 400)))
            else:
                if manifest.mode == "FINAL" and not image.quality_accepted:
                    raise LayoutReview(
                        "IMAGE_QUALITY_REVIEW_REQUIRED", question.question_revision_id
                    )
                cache_key = (image.member, image.transform)
                if cache_key not in image_cache:
                    display, dimensions, decoded_pixels = _image_bytes(input_root, image)
                    total_pixels += decoded_pixels
                    total_display_bytes += len(display)
                    if total_pixels > MAX_TOTAL_PIXELS or total_display_bytes > MAX_DISPLAY_BYTES:
                        raise ValueError("KAKAO_RENDER_DISPLAY_BUDGET_EXCEEDED")
                    image_cache[cache_key] = (display, dimensions, decoded_pixels)
                display, dimensions, _ = image_cache[cache_key]
                images.append((display, dimensions))
        layout = _layout(question, font, tuple(size for _, size in images))
        _validate_text_coverage(question, layout)
        plans.append((question, header, images, layout))
    pages = []
    with pymupdf.open() as document:
        for number, (question, header, images, layout) in enumerate(plans, 1):
            page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            page.insert_font(fontname="KakaoFont", fontbuffer=font_bytes)
            page.insert_text((MARGIN, 52), header, fontname="KakaoFont", fontsize=11)
            lines_by_span: dict[str, list[TextLine]] = {}
            for line in layout.lines:
                lines_by_span.setdefault(line.span_id, []).append(line)
            image_by_occurrence = {
                image.attachment_occurrence_id: (raw, bounds)
                for image, (raw, _), bounds in zip(
                    question.images, images, layout.image_bounds, strict=True
                )
            }
            for reference in question.ordered_blocks:
                if isinstance(reference, RenderTextReference):
                    for line in lines_by_span[reference.span_id]:
                        if line.text:
                            page.insert_text(
                                (line.x, line.baseline),
                                line.text,
                                fontname="KakaoFont",
                                fontsize=layout.font_size,
                            )
                else:
                    raw, bounds = image_by_occurrence[reference.attachment_occurrence_id]
                    rectangle = pymupdf.Rect(bounds)
                    if raw is None:
                        page.draw_rect(rectangle, color=(0.5, 0.5, 0.5))
                        page.insert_text(
                            (rectangle.x0 + 8, rectangle.y0 + 20),
                            "미확보 사진",
                            fontname="KakaoFont",
                            fontsize=11,
                        )
                    else:
                        page.insert_image(rectangle, stream=raw, keep_proportion=True)
            image_receipts = []
            for image, (raw, dimensions), bounds in zip(
                question.images, images, layout.image_bounds, strict=True
            ):
                image_receipts.append(
                    {
                        "attachment_occurrence_id": image.attachment_occurrence_id,
                        "attachment_revision_id": image.attachment_revision_id,
                        "source_sha256": image.member.sha256 if image.member else None,
                        "display_transform": "exif-rotate-crop-to-png/1.0" if raw else None,
                        "display_sha256": sha256(raw) if raw else None,
                        "display_size_bytes": len(raw) if raw else None,
                        "display_width_px": dimensions[0] if raw else None,
                        "display_height_px": dimensions[1] if raw else None,
                        "availability": image.availability,
                        "bounds_pt": bounds,
                        "crop": image.transform.crop.model_dump(mode="json")
                        if image.transform and image.transform.crop
                        else None,
                        "transform": image.transform.model_dump(mode="json")
                        if image.transform
                        else None,
                    }
                )
            page.insert_text((MARGIN, 802), str(number), fontname="KakaoFont", fontsize=10)
            pages.append(
                {
                    "question_revision_id": question.question_revision_id,
                    "page_number": number,
                    "font_size_pt": layout.font_size,
                    "image_columns": layout.columns,
                    "text_blocks": [
                        {
                            "span_id": line.span_id,
                            "start_codepoint": line.start,
                            "end_codepoint": line.end,
                            "bounds_pt": line.bounds,
                        }
                        for line in layout.lines
                    ],
                    "image_blocks": image_receipts,
                }
            )
        pdf = document.tobytes(garbage=4, deflate=True, no_new_id=True)
    # No success output is published before every page has passed measured layout.
    previews = []
    with pymupdf.open(stream=pdf, filetype="pdf") as check:
        if len(check) != len(manifest.questions):
            raise ValueError("KAKAO_RENDER_PAGE_COUNT_MISMATCH")
        for number, (page, (question, header, images, _layout_receipt)) in enumerate(
            zip(check, plans, strict=True), 1
        ):
            if (
                abs(page.rect.width - PAGE_WIDTH) > 0.01
                or abs(page.rect.height - PAGE_HEIGHT) > 0.01
            ):
                raise ValueError("KAKAO_RENDER_PAGE_GEOMETRY_INVALID")
            if not page.get_fonts() or any(
                not check.extract_font(font_entry[0])[3] for font_entry in page.get_fonts()
            ):
                raise ValueError("KAKAO_RENDER_FONT_MISSING")
            source_text = {block.span_id: block.text for block in question.text_blocks}
            missing = {
                image.attachment_occurrence_id for image in question.images if image.member is None
            }
            expected = (
                header
                + "".join(
                    source_text[ref.span_id]
                    if isinstance(ref, RenderTextReference)
                    else "미확보 사진"
                    if ref.attachment_occurrence_id in missing
                    else ""
                    for ref in question.ordered_blocks
                )
                + str(number)
            )
            if _text_characters(page.get_text()) != _text_characters(expected):
                raise ValueError("KAKAO_RENDER_TEXT_READBACK_MISMATCH")
            if len(page.get_image_info()) != sum(raw is not None for raw, _ in images):
                raise ValueError("KAKAO_RENDER_IMAGE_READBACK_MISMATCH")
            for block in page.get_text("dict")["blocks"]:
                x0, y0, x1, y1 = block["bbox"]
                if (
                    x0 < MARGIN - 0.05
                    or y0 < MARGIN - 0.05
                    or x1 > PAGE_WIDTH - MARGIN + 0.05
                    or y1 > PAGE_HEIGHT - MARGIN + 0.05
                ):
                    raise ValueError("KAKAO_RENDER_PAGE_CLIPPED")
            previews.append(
                page.get_pixmap(matrix=pymupdf.Matrix(1.0, 1.0), alpha=False).tobytes("png")
            )
    receipt = canonical_bytes(
        {
            "schema_version": "kakao-question-layout-receipt/1.0",
            "command_sha256": sha256(canonical_bytes(command.model_dump(mode="json"))),
            "manifest_sha256": command.manifest.sha256,
            "font_sha256": command.font.sha256,
            "layout_policy": command.layout_policy,
            "renderer_release_sha256": command.renderer_release_sha256,
            "mode": command.mode,
            "pages": pages,
        }
    )
    decoded_receipt = json.loads(receipt)
    validate_contract("layout", decoded_receipt)
    check_layout_receipt(command, manifest, RenderLayoutReceipt.model_validate(decoded_receipt))
    if len(pdf) + len(receipt) + sum(len(preview) for preview in previews) > 256 * 1024 * 1024:
        raise ValueError("KAKAO_RENDER_OUTPUT_BUDGET_EXCEEDED")
    outputs = [
        write_member(output_root, "report.pdf", pdf, "application/pdf"),
        write_member(output_root, "layout.json", receipt, "application/json"),
    ]
    for number, preview in enumerate(previews, 1):
        outputs.append(write_member(output_root, f"page-{number:04d}.png", preview, "image/png"))
    return tuple(outputs)
