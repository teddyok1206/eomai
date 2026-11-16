"""Project one exact student subset at the explicit offline-worker input boundary."""

from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo

from eom_catalog_contracts.kakao_question import (
    KakaoQuestionManifest,
    KakaoQuestionPacket,
    KakaoQuestionText,
)
from eom_kakao_archive_contracts.render import (
    LocalMember,
    RenderBlockReference,
    RenderImage,
    RenderImageReference,
    RenderImageTransform,
    RenderManifest,
    RenderQuestion,
    RenderText,
    RenderTextReference,
)
from eom_kakao_archive_contracts.validation import validate_contract
from eom_protocol.artifact_members import ArtifactMemberPointer

from eom_catalog_service.kakao_question_editing import (
    PublishedKakaoQuestion,
    ResolvedKakaoQuestionSource,
    build_question_packet,
    packet_student_subset,
    resolve_question_text,
    validate_question_sources,
)


@dataclass(frozen=True, slots=True)
class KakaoRenderImageInput:
    """A core-owned materialization receipt; runner still validates actual local bytes."""

    pointer: ArtifactMemberPointer
    member: LocalMember

    def __post_init__(self) -> None:
        if self.pointer.media_type not in {"image/png", "image/jpeg", "image/webp"} or (
            self.pointer.sha256 != self.member.sha256
            or self.pointer.media_type != self.member.media_type
        ):
            raise ValueError("KAKAO_ARCHIVE_RENDER_IMAGE_PIN_MISMATCH")


def _image_key(pointer: ArtifactMemberPointer) -> tuple[str, ...]:
    return (
        pointer.artifact_id,
        pointer.artifact_revision_id,
        pointer.member_path,
        pointer.schema_ref,
        pointer.media_type,
        pointer.sha256,
    )


def project_kakao_student_render(
    *,
    packet: KakaoQuestionPacket,
    student_id: str,
    questions: tuple[PublishedKakaoQuestion, ...],
    sources: tuple[ResolvedKakaoQuestionSource, ...],
    images: tuple[KakaoRenderImageInput, ...],
) -> RenderManifest:
    """No authority is created here: caller checks source/mapping before and after I/O."""
    packet = KakaoQuestionPacket.model_validate(packet.model_dump(mode="json"))
    subset = packet_student_subset(packet, student_id)
    indexed = {value.question.question_revision_id: value for value in questions}
    if len(indexed) != len(questions) or set(indexed) != {
        value.question_revision_id for value in subset.questions
    }:
        raise ValueError("KAKAO_ARCHIVE_RENDER_QUESTION_SET_MISMATCH")
    ordered = tuple(indexed[value.question_revision_id] for value in subset.questions)
    # Reuse packet selection rules instead of trusting submitted readiness flags.
    rebuilt = build_question_packet(
        tuple(
            PublishedKakaoQuestion(
                KakaoQuestionManifest.model_validate(value.question.model_dump(mode="json")),
                value.pointer,
            )
            for value in ordered
        ),
        packet_id=packet.packet_id,
        packet_revision_id=packet.packet_revision_id,
        previous_revision_id=packet.previous_revision_id,
        start_date=packet.display_start_date,
        end_date_inclusive=packet.display_end_date_inclusive,
        mode=packet.mode,
        include_replies=packet.include_replies,
        actor_id=packet.created_by,
        created_at=packet.created_at,
        collection_coverage=packet.collection_coverage,
    )
    if (
        rebuilt.source_binding_id != packet.source_binding_id
        or rebuilt.questions != subset.questions
    ):
        raise ValueError("KAKAO_ARCHIVE_RENDER_QUESTION_PIN_MISMATCH")
    source_index = {source.normalization.normalization_revision_id: source for source in sources}
    if len(source_index) != len(sources) or set(source_index) != {
        reference.normalization_revision_id
        for item in ordered
        for reference in item.question.sources
    }:
        raise ValueError("KAKAO_ARCHIVE_RENDER_SOURCE_SET_MISMATCH")
    image_index = {_image_key(image.pointer): image for image in images}
    if len(image_index) != len(images):
        raise ValueError("KAKAO_ARCHIVE_RENDER_IMAGE_DUPLICATED")
    used_images: set[tuple[str, ...]] = set()
    rendered: list[RenderQuestion] = []
    for item in ordered:
        question = item.question
        validate_question_sources(
            question,
            tuple(
                source_index[reference.normalization_revision_id] for reference in question.sources
            ),
        )
        text: list[RenderText] = []
        pictures: list[RenderImage] = []
        blocks: list[RenderBlockReference] = []
        for block in question.ordered_blocks:
            if block.role == "staff" and not packet.include_replies:
                continue
            if isinstance(block, KakaoQuestionText):
                value = resolve_question_text(block, source_index[block.normalization_revision_id])
                text.append(
                    RenderText(
                        span_id=block.block_id,
                        text=("답변\n" if block.role == "staff" else "") + value,
                    )
                )
                blocks.append(RenderTextReference(kind="TEXT", span_id=block.block_id))
                continue
            member = None
            if block.source_pointer is not None:
                key = _image_key(block.source_pointer)
                image = image_index.get(key)
                if image is None:
                    raise ValueError("KAKAO_ARCHIVE_RENDER_IMAGE_MISSING")
                member = image.member
                used_images.add(key)
            transform = (
                RenderImageTransform.model_validate(block.transform.model_dump(exclude={"reason"}))
                if block.transform is not None
                else None
            )
            pictures.append(
                RenderImage(
                    attachment_occurrence_id=block.attachment_id,
                    attachment_revision_id=block.attachment_revision_id,
                    member=member,
                    availability=(
                        "AVAILABLE"
                        if member is not None
                        else "EXPIRED"
                        if block.availability == "expired"
                        else "MISSING"
                        if block.availability in {"not_found", "denied"}
                        else "UNRESOLVED"
                    ),
                    quality_accepted=(
                        block.association in {"SOURCE_VERIFIED", "MANUAL_CONFIRMED"}
                        and (
                            block.source_quality == "ORIGINAL"
                            or block.quality_acceptance is not None
                        )
                    ),
                    transform=transform,
                )
            )
            blocks.append(
                RenderImageReference(kind="IMAGE", attachment_occurrence_id=block.attachment_id)
            )
        rendered.append(
            RenderQuestion(
                question_revision_id=question.question_revision_id,
                header_date=(
                    question.first_student_at_utc.astimezone(ZoneInfo("Asia/Seoul")).date()
                    if question.first_student_at_utc is not None
                    else None
                ),
                text_blocks=tuple(text),
                images=tuple(pictures),
                ordered_blocks=tuple(blocks),
            )
        )
    if used_images != set(image_index):
        raise ValueError("KAKAO_ARCHIVE_RENDER_IMAGE_SET_MISMATCH")
    result = RenderManifest(
        schema_version="kakao-question-render-manifest/1.0",
        source_binding_id=packet.source_binding_id,
        packet_revision_id=packet.packet_revision_id,
        student_id=subset.student_id,
        student_display_name=subset.display_name,
        subset_sha256=subset.subset_sha256,
        mode=packet.mode,
        questions=tuple(rendered),
    )
    validate_contract("manifest", result.model_dump(mode="json"))
    return result
