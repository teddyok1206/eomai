"""Preserve exact question roles/metadata at the study-render materialization boundary."""

from collections.abc import Mapping
from zoneinfo import ZoneInfo

from eom_catalog_contracts.kakao_question import (
    KakaoQuestionBlock,
    KakaoQuestionPacket,
    KakaoQuestionText,
)
from eom_kakao_archive_contracts.render import (
    RenderBlockReference,
    RenderImageReference,
    RenderText,
    RenderTextReference,
)
from eom_kakao_archive_contracts.study import (
    StudyMessageMetadata,
    StudyQuestion,
    StudyRenderManifest,
    StudySourceContent,
    StudySourceImage,
    StudySourceText,
)

from .kakao_question_editing import (
    PublishedKakaoQuestion,
    ResolvedKakaoQuestionSource,
    resolve_question_text,
)
from .kakao_render_projection import (
    KakaoRenderImageInput,
    image_pointer_key,
    project_kakao_render_image,
    resolve_kakao_render_selection,
)


def project_kakao_source_content(
    blocks: tuple[KakaoQuestionBlock, ...],
    sources: Mapping[str, ResolvedKakaoQuestionSource],
    images: Mapping[tuple[str, ...], KakaoRenderImageInput],
    used_images: set[tuple[str, ...]],
) -> StudySourceContent:
    text: list[StudySourceText] = []
    pictures: list[StudySourceImage] = []
    order: list[RenderBlockReference] = []
    for block in blocks:
        if isinstance(block, KakaoQuestionText):
            text.append(
                StudySourceText(
                    source_occurrence_id=block.source_occurrence_id,
                    value=RenderText(
                        span_id=block.block_id,
                        text=resolve_question_text(block, sources[block.normalization_revision_id]),
                    ),
                )
            )
            order.append(RenderTextReference(kind="TEXT", span_id=block.block_id))
        else:
            image, key = project_kakao_render_image(block, images)
            if key is not None:
                used_images.add(key)
            pictures.append(
                StudySourceImage(source_occurrence_id=block.source_occurrence_id, value=image)
            )
            order.append(
                RenderImageReference(kind="IMAGE", attachment_occurrence_id=block.attachment_id)
            )
    return StudySourceContent(
        text_blocks=tuple(text), images=tuple(pictures), ordered_blocks=tuple(order)
    )


def project_kakao_student_study(
    *,
    packet: KakaoQuestionPacket,
    student_id: str,
    questions: tuple[PublishedKakaoQuestion, ...],
    sources: tuple[ResolvedKakaoQuestionSource, ...],
    images: tuple[KakaoRenderImageInput, ...],
) -> StudyRenderManifest:
    """Core authorizes before/after I/O; this pure projection neither fetches nor publishes.

    Only stored original questions are projected here. Supplements require the future
    saved-study owner; callers cannot submit arbitrary notes or invented citations here.
    """
    selected = resolve_kakao_render_selection(
        packet=packet, student_id=student_id, questions=questions, sources=sources
    )
    image_index = {image_pointer_key(value.pointer): value for value in images}
    if len(image_index) != len(images):
        raise ValueError("KAKAO_ARCHIVE_RENDER_IMAGE_DUPLICATED")
    used: set[tuple[str, ...]] = set()
    rendered: list[StudyQuestion] = []
    for item in selected.questions:
        question = item.question
        groups: dict[str, list[KakaoQuestionBlock]] = {"student": [], "staff": []}
        metadata: dict[str, StudyMessageMetadata] = {}
        for block in question.ordered_blocks:
            if block.role == "staff" and not selected.packet.include_replies:
                continue
            groups[block.role].append(block)
            source = selected.sources[block.normalization_revision_id]
            value = StudyMessageMetadata(
                source_occurrence_id=block.source_occurrence_id,
                role=block.role,
                kind=source.messages[block.row_ordinal].kind,
                raw_date=source.messages[block.row_ordinal].raw_date,
                source_timezone=source.normalization.source_timezone,
                sent_at_utc=block.sent_at_utc,
            )
            if metadata.setdefault(block.source_occurrence_id, value) != value:
                raise ValueError("KAKAO_STUDY_RENDER_MESSAGE_METADATA_MISMATCH")
        rendered.append(
            StudyQuestion(
                question_revision_id=question.question_revision_id,
                header_date=question.first_student_at_utc.astimezone(ZoneInfo("Asia/Seoul")).date()
                if question.first_student_at_utc is not None
                else None,
                student=project_kakao_source_content(
                    tuple(groups["student"]), selected.sources, image_index, used
                ),
                staff=project_kakao_source_content(
                    tuple(groups["staff"]), selected.sources, image_index, used
                )
                if groups["staff"]
                else None,
                messages=tuple(metadata.values()),
                supplements=(),
            )
        )
    if used != set(image_index):
        raise ValueError("KAKAO_ARCHIVE_RENDER_IMAGE_SET_MISMATCH")
    return StudyRenderManifest(
        schema_version="kakao-study-render-manifest/1.0",
        source_binding_id=selected.packet.source_binding_id,
        packet_revision_id=selected.packet.packet_revision_id,
        study_revision_id=None,
        student_id=selected.subset.student_id,
        student_display_name=selected.subset.display_name,
        subset_sha256=selected.subset.subset_sha256,
        mode=selected.packet.mode,
        questions=tuple(rendered),
    )
