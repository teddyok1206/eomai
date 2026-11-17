"""Deterministic section values and complete source-range acceptance for study PDFs."""

from dataclasses import dataclass
from typing import Literal, Self

from pydantic import Field, model_validator

from .layout import PageLayoutReceipt, check_page_layout
from .render import (
    BindingId,
    FrozenModel,
    PacketRevisionId,
    RenderBlockReference,
    RenderImage,
    RenderImageReference,
    RenderQuestion,
    RenderText,
    RenderTextReference,
    Sha256,
    StudentId,
    canonical_bytes,
    sha256,
)
from .study import StudyRenderCommand, StudyRenderManifest, StudyRevisionId
from .study_validation import validate_study_contract

SectionKind = Literal["STUDENT", "STAFF", "SUPPLEMENT"]


@dataclass(frozen=True, slots=True)
class StudySection:
    question_revision_id: str
    question_number: int
    kind: SectionKind
    supplement_id: str | None
    text_blocks: tuple[RenderText, ...]
    images: tuple[RenderImage, ...]
    ordered_blocks: tuple[RenderBlockReference, ...]


def _generated_texts(
    values: tuple[str, ...], used: set[str], prefix: str
) -> tuple[RenderText, ...]:
    cursor = 0
    result = []
    for value in values:
        while f"{prefix}-{cursor}" in used:
            cursor += 1
        key = f"{prefix}-{cursor}"
        used.add(key)
        result.append(RenderText(span_id=key, text=value))
    return tuple(result)


def build_study_sections(manifest: StudyRenderManifest) -> tuple[StudySection, ...]:
    """One source of printed metadata/labels/order, shared by renderer and core checks."""
    sections = []
    for number, question in enumerate(manifest.questions, 1):
        record_text = []
        for message in question.messages:
            speaker = "학생 질문" if message.role == "student" else "조교 답변"
            zone = "서울 시각" if message.source_timezone == "Asia/Seoul" else "원문 시간대 미확정"
            record_text.append(f"{speaker}: {message.raw_date} · {zone}")
        for kind, content in (("STUDENT", question.student), ("STAFF", question.staff)):
            if content is None:
                continue
            # Content validation already pins each type's relative order to ordered_blocks.
            texts = [item.value for item in content.text_blocks]
            images = tuple(item.value for item in content.images)
            # The output profile separates sender photos first, not the source's identity/order.
            order: list[RenderBlockReference] = [
                *(
                    RenderImageReference(
                        kind="IMAGE", attachment_occurrence_id=image.attachment_occurrence_id
                    )
                    for image in images
                ),
                *(RenderTextReference(kind="TEXT", span_id=text.span_id) for text in texts),
            ]
            if kind == "STAFF" or question.staff is None:
                records = _generated_texts(
                    ("기록 정보", *record_text), {value.span_id for value in texts}, "study-record"
                )
                texts.extend(records)
                order.extend(
                    RenderTextReference(kind="TEXT", span_id=value.span_id) for value in records
                )
            sections.append(
                StudySection(
                    question.question_revision_id,
                    number,
                    "STUDENT" if kind == "STUDENT" else "STAFF",
                    None,
                    tuple(texts),
                    images,
                    tuple(order),
                )
            )
        for supplement in question.supplements:
            texts = list(supplement.text_blocks)
            notice = {
                "USER_NOTE": "직접 작성한 설명",
                "SOURCE_EXCERPT": "교재 원문 자료",
                "MODEL_DRAFT": "AI 작성 초안 · 내용과 근거 확인 필요",
            }[supplement.origin]
            labels = _generated_texts(
                (
                    supplement.title,
                    notice,
                    *(
                        f"출처: {value.source_title} · {value.page_label}"
                        for value in supplement.citations
                    ),
                ),
                {value.span_id for value in texts},
                "study-label",
            )
            headings, citations = labels[:2], labels[2:]
            sections.append(
                StudySection(
                    question.question_revision_id,
                    number,
                    "SUPPLEMENT",
                    supplement.supplement_id,
                    (*headings, *texts, *citations),
                    supplement.images,
                    (
                        *(
                            RenderTextReference(kind="TEXT", span_id=value.span_id)
                            for value in headings
                        ),
                        *supplement.ordered_blocks,
                        *(
                            RenderTextReference(kind="TEXT", span_id=value.span_id)
                            for value in citations
                        ),
                    ),
                )
            )
    return tuple(sections)


class StudyPageSpan(FrozenModel):
    span_id: str = Field(min_length=1, max_length=128)
    start_codepoint: int = Field(ge=0, le=20000, strict=True)
    end_codepoint: int = Field(ge=1, le=20000, strict=True)

    @model_validator(mode="after")
    def positive_range(self) -> Self:
        if self.start_codepoint >= self.end_codepoint:
            raise ValueError("KAKAO_STUDY_RENDER_SPAN_INVALID")
        return self


class StudyPageReceipt(FrozenModel):
    section: SectionKind
    supplement_id: str | None = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    spans: tuple[StudyPageSpan, ...] = Field(max_length=200)
    layout: PageLayoutReceipt


class StudyLayoutReceipt(FrozenModel):
    schema_version: Literal["kakao-study-layout-receipt/1.0"]
    command_sha256: Sha256
    manifest_sha256: Sha256
    font_sha256: Sha256
    source_binding_id: BindingId
    packet_revision_id: PacketRevisionId
    study_revision_id: StudyRevisionId | None
    student_id: StudentId
    subset_sha256: Sha256
    layout_policy: Literal["student-study-a4/1.0"]
    renderer_release_sha256: Sha256
    mode: Literal["DRAFT", "FINAL"]
    pages: tuple[StudyPageReceipt, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def schema_matches(self) -> Self:
        validate_study_contract("layout", self.model_dump(mode="json"))
        return self


def check_study_layout(
    command: StudyRenderCommand, manifest: StudyRenderManifest, receipt: StudyLayoutReceipt
) -> None:
    expected = (
        sha256(canonical_bytes(command.model_dump(mode="json"))),
        command.manifest.sha256,
        command.font.sha256,
        command.source_binding_id,
        command.packet_revision_id,
        command.study_revision_id,
        command.student_id,
        command.subset_sha256,
        command.layout_policy,
        command.renderer_release_sha256,
        command.mode,
    )
    actual = (
        receipt.command_sha256,
        receipt.manifest_sha256,
        receipt.font_sha256,
        receipt.source_binding_id,
        receipt.packet_revision_id,
        receipt.study_revision_id,
        receipt.student_id,
        receipt.subset_sha256,
        receipt.layout_policy,
        receipt.renderer_release_sha256,
        receipt.mode,
    )
    if actual != expected:
        raise ValueError("KAKAO_STUDY_RENDER_LAYOUT_PINS_MISMATCH")
    sections = build_study_sections(manifest)
    text_indices = tuple(
        {value.span_id: value for value in section.text_blocks} for section in sections
    )
    image_indices = tuple(
        {value.attachment_occurrence_id: value for value in section.images} for section in sections
    )
    question_dates = {value.question_revision_id: value.header_date for value in manifest.questions}
    section_index = 0
    cursor = 0
    ends: dict[str, int] = {}
    for number, page in enumerate(receipt.pages, 1):
        if section_index >= len(sections):
            raise ValueError("KAKAO_STUDY_RENDER_LAYOUT_EXTRA_PAGE")
        section = sections[section_index]
        if (page.layout.question_revision_id, page.section, page.supplement_id) != (
            section.question_revision_id,
            section.kind,
            section.supplement_id,
        ):
            raise ValueError("KAKAO_STUDY_RENDER_LAYOUT_SECTION_MISMATCH")
        fragments = {value.span_id: value for value in page.spans}
        image_receipts = {
            value.attachment_occurrence_id: value for value in page.layout.image_blocks
        }
        if len(fragments) != len(page.spans) or len(image_receipts) != len(
            page.layout.image_blocks
        ):
            raise ValueError("KAKAO_STUDY_RENDER_LAYOUT_USE_DUPLICATED")
        text_index, image_index = text_indices[section_index], image_indices[section_index]
        text: list[RenderText] = []
        images: list[RenderImage] = []
        order: list[RenderBlockReference] = []
        consumed_spans, consumed_images = set(), set()
        while cursor < len(section.ordered_blocks):
            reference = section.ordered_blocks[cursor]
            if isinstance(reference, RenderTextReference):
                fragment = fragments.get(reference.span_id)
                if fragment is None:
                    break
                value = text_index[reference.span_id]
                if fragment.start_codepoint != ends.get(
                    value.span_id, 0
                ) or fragment.end_codepoint > len(value.text):
                    raise ValueError("KAKAO_STUDY_RENDER_LAYOUT_TEXT_MISSING")
                text.append(
                    RenderText(
                        span_id=value.span_id,
                        text=value.text[fragment.start_codepoint : fragment.end_codepoint],
                    )
                )
                order.append(reference)
                ends[value.span_id] = fragment.end_codepoint
                consumed_spans.add(value.span_id)
                if fragment.end_codepoint < len(value.text):
                    break
            else:
                key = reference.attachment_occurrence_id
                if key not in image_receipts:
                    break
                images.append(image_index[key])
                order.append(reference)
                consumed_images.add(key)
            cursor += 1
        if consumed_spans != set(fragments) or consumed_images != set(image_receipts):
            raise ValueError("KAKAO_STUDY_RENDER_LAYOUT_CONTENT_MISMATCH")
        if not order:
            raise ValueError("KAKAO_STUDY_RENDER_LAYOUT_EMPTY_PAGE")
        content = RenderQuestion(
            question_revision_id=section.question_revision_id,
            header_date=question_dates[section.question_revision_id],
            text_blocks=tuple(text),
            images=tuple(images),
            ordered_blocks=tuple(order),
        )
        check_page_layout(content, page.layout, number, mode=command.mode)
        if section.kind != "STUDENT" and page.layout.font_size_pt != 11.0:
            raise ValueError("KAKAO_STUDY_RENDER_LAYOUT_FONT_INVALID")
        if cursor == len(section.ordered_blocks):
            section_index += 1
            cursor, ends = 0, {}
        elif section.kind == "STUDENT":
            raise ValueError("KAKAO_STUDY_RENDER_STUDENT_PAGE_OVERFLOW")
    if section_index != len(sections):
        raise ValueError("KAKAO_STUDY_RENDER_LAYOUT_SECTION_MISSING")
