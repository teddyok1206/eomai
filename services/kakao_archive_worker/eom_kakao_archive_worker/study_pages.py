"""Bounded study sections: one question page, then readable flowing continuation pages."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from eom_kakao_archive_contracts import (
    RenderImage,
    RenderImageReference,
    RenderQuestion,
    RenderText,
)
from eom_kakao_archive_contracts.render import RenderBlockReference
from eom_kakao_archive_contracts.study import StudyRenderManifest
from eom_kakao_archive_contracts.study_layout import (
    StudyPageSpan,
    StudySection,
    build_study_sections,
)

from .question_pdf import (
    BODY_BOTTOM,
    BODY_TOP,
    GAP,
    MARGIN,
    MIN_IMAGE_SIDE,
    PAGE_WIDTH,
    LayoutReview,
    PageLayout,
    QuestionPagePlan,
    RenderImageCache,
    TextLine,
    _check_glyphs,
    _fixed_coordinates,
    _validate_text_coverage,
    _wrap,
    plan_question_page,
)


@dataclass(frozen=True, slots=True)
class StudyPagePlan:
    section: StudySection = field(repr=False)
    spans: tuple[StudyPageSpan, ...]
    page: QuestionPagePlan = field(repr=False)


@dataclass(slots=True)
class _FlowPage:
    top: float = BODY_TOP
    characters: int = 0
    texts: list[RenderText] = field(default_factory=list, repr=False)
    images: list[RenderImage] = field(default_factory=list, repr=False)
    order: list[RenderBlockReference] = field(default_factory=list)
    spans: list[StudyPageSpan] = field(default_factory=list)
    lines: list[TextLine] = field(default_factory=list, repr=False)
    image_bytes: list[tuple[bytes | None, tuple[int, int]]] = field(
        default_factory=list, repr=False
    )
    image_bounds: list[tuple[float, float, float, float]] = field(default_factory=list)

    def freeze(self, section: StudySection, header: str, header_date: date | None) -> StudyPagePlan:
        question = RenderQuestion(
            question_revision_id=section.question_revision_id,
            header_date=header_date,
            text_blocks=tuple(self.texts),
            images=tuple(self.images),
            ordered_blocks=tuple(self.order),
        )
        layout = _fixed_coordinates(
            PageLayout(11.0, tuple(self.lines), tuple(self.image_bounds), 1)
        )
        _validate_text_coverage(question, layout)
        return StudyPagePlan(
            section,
            tuple(self.spans),
            QuestionPagePlan(question, header, tuple(self.image_bytes), layout),
        )


def _flow_section(
    section: StudySection,
    header: str,
    header_date: date | None,
    *,
    mode: Literal["DRAFT", "FINAL"],
    cache: RenderImageCache,
    font: Any,
    page_budget: int,
) -> tuple[StudyPagePlan, ...]:
    """Wrap each span once; consume its codepoint ranges monotonically without truncation."""
    width, size = PAGE_WIDTH - 2 * MARGIN, 11.0
    line_height = max(size * 1.35, (font.ascender - font.descender) * size)
    texts = {value.span_id: value for value in section.text_blocks}
    images = {value.attachment_occurrence_id: value for value in section.images}
    result: list[StudyPagePlan] = []
    page = _FlowPage()

    def flush() -> None:
        nonlocal page
        if not page.order or len(result) >= page_budget:
            raise LayoutReview("NEEDS_LAYOUT_REVIEW", section.question_revision_id)
        result.append(page.freeze(section, header, header_date))
        page = _FlowPage()

    for reference in section.ordered_blocks:
        if isinstance(reference, RenderImageReference):
            image = images[reference.attachment_occurrence_id]
            raw, dimensions = cache.load(
                image, mode=mode, question_revision_id=section.question_revision_id
            )
            image_width, image_height = dimensions
            scale = min(width / image_width, (BODY_BOTTOM - BODY_TOP) / image_height)
            w, h = image_width * scale, image_height * scale
            if min(w, h) < MIN_IMAGE_SIDE:
                raise LayoutReview("NEEDS_LAYOUT_REVIEW", section.question_revision_id)
            if page.top + h > BODY_BOTTOM + 0.000001:
                flush()
            page.images.append(image)
            page.order.append(reference)
            page.image_bytes.append((raw, dimensions))
            page.image_bounds.append((MARGIN, page.top, MARGIN + w, page.top + h))
            page.top += h + GAP
            continue
        block = texts[reference.span_id]
        try:
            _check_glyphs(font, block.text)
        except LayoutReview as error:
            raise LayoutReview(error.code, section.question_revision_id) from error
        wrapped = _wrap(block.text, font, size, width)
        cursor = 0
        while cursor < len(wrapped):
            if (
                page.top + line_height > BODY_BOTTOM
                or len(page.texts) >= 200
                or page.characters + wrapped[cursor][1] - wrapped[cursor][0] > 20000
            ):
                flush()
            start = wrapped[cursor][0]
            end = start
            while cursor < len(wrapped):
                line_start, line_end, text = wrapped[cursor]
                if (
                    page.top + line_height > BODY_BOTTOM
                    or page.characters + line_end - start > 20000
                ):
                    break
                page.lines.append(
                    TextLine(
                        block.span_id,
                        line_start - start,
                        line_end - start,
                        text,
                        MARGIN,
                        page.top + font.ascender * size,
                        (
                            MARGIN,
                            page.top,
                            MARGIN + float(font.text_length(text, fontsize=size)),
                            page.top + line_height,
                        ),
                    )
                )
                page.top += line_height
                end, cursor = line_end, cursor + 1
            page.texts.append(RenderText(span_id=block.span_id, text=block.text[start:end]))
            page.spans.append(
                StudyPageSpan(span_id=block.span_id, start_codepoint=start, end_codepoint=end)
            )
            page.order.append(reference)
            page.characters += end - start
            if cursor < len(wrapped):
                flush()
            else:
                page.top += GAP
    if page.order:
        flush()
    return tuple(result)


def plan_study_pages(
    manifest: StudyRenderManifest, *, font: Any, cache: RenderImageCache
) -> tuple[StudyPagePlan, ...]:
    """No I/O except the staged image cache; all pages retain original question/span identity."""
    _check_glyphs(font, manifest.student_display_name + "검토용 질문 미확보 사진")
    questions = {value.question_revision_id: value for value in manifest.questions}
    result: list[StudyPagePlan] = []
    labels = {"STUDENT": "질문", "STAFF": "답변", "SUPPLEMENT": "관련 자료"}
    for section in build_study_sections(manifest):
        question = questions[section.question_revision_id]
        day = question.header_date.isoformat() if question.header_date else "날짜 확인 필요"
        header = (
            f"{manifest.student_display_name} · 질문 {section.question_number} · "
            f"{day} · {labels[section.kind]}"
        )
        if manifest.mode == "DRAFT":
            header = "[검토용] " + header
        _check_glyphs(font, header)
        if font.text_length(header, fontsize=11) > PAGE_WIDTH - 2 * MARGIN:
            raise LayoutReview("HEADER_OVERFLOW", section.question_revision_id)
        if section.kind == "STUDENT":
            if (
                len(section.text_blocks) > 200
                or sum(len(value.text) for value in section.text_blocks) > 20000
            ):
                raise LayoutReview("NEEDS_LAYOUT_REVIEW", section.question_revision_id)
            content = RenderQuestion(
                question_revision_id=section.question_revision_id,
                header_date=question.header_date,
                text_blocks=section.text_blocks,
                images=section.images,
                ordered_blocks=section.ordered_blocks,
            )
            result.append(
                StudyPagePlan(
                    section,
                    tuple(
                        StudyPageSpan(
                            span_id=value.span_id, start_codepoint=0, end_codepoint=len(value.text)
                        )
                        for value in section.text_blocks
                    ),
                    plan_question_page(content, header, mode=manifest.mode, cache=cache, font=font),
                )
            )
        else:
            result.extend(
                _flow_section(
                    section,
                    header,
                    question.header_date,
                    mode=manifest.mode,
                    cache=cache,
                    font=font,
                    page_budget=200 - len(result),
                )
            )
        if len(result) > 200:
            raise LayoutReview("NEEDS_LAYOUT_REVIEW", section.question_revision_id)
    return tuple(result)
