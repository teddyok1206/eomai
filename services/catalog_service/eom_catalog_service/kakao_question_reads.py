"""Exact private read projections and member streams, without a parallel source store."""

from dataclasses import dataclass, field

from eom_catalog_contracts.kakao_question import (
    KakaoQuestionImage,
    KakaoQuestionProvenance,
    KakaoQuestionText,
)
from eom_catalog_contracts.kakao_question_rpc import (
    KakaoQuestionDisplayImage,
    KakaoQuestionDisplayText,
    KakaoQuestionImageDescriptor,
    KakaoQuestionView,
)
from eom_catalog_contracts.validation import validate_contract
from eom_operator_identity import ActorContext, PermissionKey
from eom_orchestrator.database import build_session_factory
from sqlalchemy import Engine

from .artifacts import CatalogArtifactService, VerifiedArtifactMemberStream
from .kakao_archive_authorization import KakaoArchiveError, authorize_kakao_room_scope
from .kakao_question_editing import resolve_question_text
from .kakao_question_service import KakaoQuestionService, ResolvedKakaoQuestions
from .kakao_source_pointers import validate_source_pointer_metadata_batch
from .kakao_source_service import KakaoSourceService


@dataclass(frozen=True, slots=True)
class KakaoOpenedQuestionImage:
    descriptor: KakaoQuestionImageDescriptor
    member: VerifiedArtifactMemberStream = field(repr=False)


class KakaoQuestionReads:
    def __init__(
        self,
        engine: Engine,
        *,
        questions: KakaoQuestionService,
        sources: KakaoSourceService,
        artifacts: CatalogArtifactService,
    ) -> None:
        self._sessions = build_session_factory(engine)
        self._questions, self._sources, self._artifacts = questions, sources, artifacts

    def _resolve(
        self, actor: ActorContext, binding: str, room: str | None, question: str, revision: str
    ) -> ResolvedKakaoQuestions:
        return self._questions.resolve_questions(
            actor,
            binding,
            (KakaoQuestionProvenance(question_id=question, question_revision_id=revision),),
            room_id=room,
        )

    def _reauthorize(self, actor: ActorContext, selected: ResolvedKakaoQuestions) -> None:
        stored = selected.questions[0].stored
        with self._sessions.begin() as session:
            authorize_kakao_room_scope(
                session,
                actor,
                stored.source_binding_id,
                stored.room_id,
                PermissionKey.KAKAO_ARCHIVE_READ,
                lock=False,
            )
            self._sources.validate_question_source_metadata(session, actor, selected.sources)
            validate_source_pointer_metadata_batch(session, (stored.manifest,))

    def read_question(
        self, actor: ActorContext, binding: str, room: str | None, question_id: str, revision: str
    ) -> KakaoQuestionView:
        selected = self._resolve(actor, binding, room, question_id, revision)
        item = selected.questions[0]
        question = item.published.question
        contexts = {
            source.resolved.normalization.normalization_revision_id: source.resolved
            for source in selected.sources
        }
        blocks: list[KakaoQuestionDisplayText | KakaoQuestionDisplayImage] = []
        for block in question.ordered_blocks:
            if isinstance(block, KakaoQuestionText):
                blocks.append(
                    KakaoQuestionDisplayText(
                        block_id=block.block_id,
                        role=block.role,
                        text=resolve_question_text(
                            block, contexts[block.normalization_revision_id]
                        ),
                    )
                )
            else:
                blocks.append(
                    KakaoQuestionDisplayImage(
                        block_id=block.block_id,
                        role=block.role,
                        attachment_id=block.attachment_id,
                        attachment_revision_id=block.attachment_revision_id,
                        availability=block.availability,
                        source_quality=block.source_quality,
                    )
                )
        view = KakaoQuestionView(
            question=item.stored,
            ordered_blocks=tuple(blocks),
            review_reasons=question.review_reasons,
            boundary_uncertain=question.boundary_uncertain,
        )
        validate_contract("catalog-kakao-question-v1", view.model_dump(mode="json"))
        self._reauthorize(actor, selected)
        return view

    def open_image(
        self,
        actor: ActorContext,
        binding: str,
        room: str | None,
        question_id: str,
        revision: str,
        attachment_id: str,
    ) -> KakaoOpenedQuestionImage:
        selected = self._resolve(actor, binding, room, question_id, revision)
        images = {
            block.attachment_id: block
            for block in selected.questions[0].published.question.ordered_blocks
            if isinstance(block, KakaoQuestionImage)
        }
        image = images.get(attachment_id)
        if image is None:
            raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
        pointer = image.source_pointer
        if image.availability != "available" or pointer is None:
            raise KakaoArchiveError("KAKAO_ARCHIVE_IMAGE_UNAVAILABLE")
        opened = self._artifacts.open_verified_member(
            artifact_id=pointer.artifact_id,
            revision_id=pointer.artifact_revision_id,
            member_path=pointer.member_path,
            sha256=pointer.sha256,
            media_type=pointer.media_type,
            schema_ref=pointer.schema_ref,
            max_bytes=32 * 1024 * 1024,
        )
        try:
            descriptor = KakaoQuestionImageDescriptor.model_validate(
                dict(
                    source_binding_id=binding,
                    room_id=selected.questions[0].stored.room_id,
                    question_id=question_id,
                    question_revision_id=revision,
                    attachment_id=attachment_id,
                    media_type=pointer.media_type,
                    content_length=opened.content_length,
                    sha256=opened.sha256,
                )
            )
            validate_contract("catalog-kakao-question-v1", descriptor.model_dump(mode="json"))
            self._reauthorize(actor, selected)
        except BaseException:
            opened.stream.close()
            raise
        return KakaoOpenedQuestionImage(descriptor, opened)
