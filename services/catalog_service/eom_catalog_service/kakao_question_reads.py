"""Exact private read projections and member streams, without a parallel source store."""

from dataclasses import dataclass, field

from eom_catalog_contracts.kakao_question import (
    KakaoQuestionImage,
    KakaoQuestionProvenance,
    KakaoQuestionText,
)
from eom_catalog_contracts.kakao_question_candidates import (
    KakaoCandidateSummary,
    KakaoQuestionCandidatePage,
)
from eom_catalog_contracts.kakao_question_edit_context import (
    KakaoQuestionEditContext,
    KakaoTextEditRange,
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
from sqlalchemy import Engine, select

from .artifacts import CatalogArtifactService, VerifiedArtifactMemberStream
from .kakao_archive_authorization import (
    KakaoArchiveError,
    authorize_kakao_binding_scope,
    authorize_kakao_room_scope,
)
from .kakao_question_editing import resolve_question_text
from .kakao_question_models import KakaoQuestionRecord
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

    def _reauthorize(
        self,
        actor: ActorContext,
        selected: ResolvedKakaoQuestions,
        permission: PermissionKey = PermissionKey.KAKAO_ARCHIVE_READ,
    ) -> None:
        stored = selected.questions[0].stored
        with self._sessions.begin() as session:
            authorize_kakao_room_scope(
                session,
                actor,
                stored.source_binding_id,
                stored.room_id,
                permission,
                lock=False,
            )
            self._sources.validate_question_source_metadata(session, actor, selected.sources)
            validate_source_pointer_metadata_batch(session, (stored.manifest,))

    def read_edit_context(
        self, actor: ActorContext, binding: str, room: str | None, question_id: str, revision: str
    ) -> KakaoQuestionEditContext:
        with self._sessions.begin() as session:
            authorize_kakao_binding_scope(
                session, actor, binding, PermissionKey.KAKAO_ARCHIVE_EDIT, lock=False
            )
        selected = self._resolve(actor, binding, room, question_id, revision)
        item = selected.questions[0]
        ranges: list[KakaoTextEditRange] = []
        for block in item.published.question.ordered_blocks:
            if not isinstance(block, KakaoQuestionText):
                continue
            # An override is display text, not a coordinate system for source spans.
            available = (
                block.display_override is None
                and block.end_codepoint - block.start_codepoint >= 2
                and 0 <= block.start_codepoint < block.end_codepoint <= 65536
            )
            ranges.append(
                KakaoTextEditRange(
                    block_id=block.block_id,
                    can_split=available,
                    start_codepoint=block.start_codepoint if available else None,
                    end_codepoint=block.end_codepoint if available else None,
                )
            )
        result = KakaoQuestionEditContext(
            source_binding_id=binding,
            room_id=item.stored.room_id,
            question_id=question_id,
            question_revision_id=revision,
            resource_version=item.stored.resource_version,
            text_blocks=tuple(ranges),
        )
        self._reauthorize(actor, selected, PermissionKey.KAKAO_ARCHIVE_EDIT)
        return result

    def _candidate_scope(self, actor: ActorContext, binding: str, room_id: str) -> tuple[str, str]:
        with self._sessions.begin() as session:
            authorize_kakao_room_scope(
                session, actor, binding, room_id, PermissionKey.KAKAO_ARCHIVE_READ, lock=False
            )
            owner, room = authorize_kakao_room_scope(
                session, actor, binding, room_id, PermissionKey.KAKAO_ARCHIVE_EDIT, lock=False
            )
            mapping = room.current_mapping_revision_id
            self._questions.current_student_pin(session, room, mapping)
            return owner, mapping

    def list_candidates(
        self,
        actor: ActorContext,
        binding: str,
        room_id: str,
        *,
        source_revision_id: str | None = None,
        after_ordinal: int = 0,
        limit: int = 50,
    ) -> KakaoQuestionCandidatePage:
        if (
            type(limit) is not int
            or not 1 <= limit <= 100
            or type(after_ordinal) is not int
            or not 0 <= after_ordinal <= 100000
            or (after_ordinal and source_revision_id is None)
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_REQUEST_INVALID")
        owner, mapping = self._candidate_scope(actor, binding, room_id)
        selected_revision = source_revision_id
        if selected_revision is None:
            selected_revision = self._sources.current_source_revision(actor, binding, room_id)
        if selected_revision is None:
            if self._candidate_scope(actor, binding, room_id) != (owner, mapping):
                raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
            return KakaoQuestionCandidatePage(
                source_binding_id=binding,
                room_id=room_id,
                source_revision_id=None,
                source_resolution_sha256=None,
                mapping_revision_id=mapping,
                total_candidates=0,
                unknown_sender_rows=0,
                items=(),
                next_after_ordinal=None,
            )
        context = self._sources.resolve_question_source_context(
            actor, binding, room_id, source_revision_id=selected_revision
        )
        source = context.resolved
        total = len(source.candidates)
        chosen = tuple(
            source.candidates[i]
            for i in range(after_ordinal + 1, min(total, after_ordinal + limit) + 1)
        )
        origins = {source.occurrence_ids[item.student_rows[0]] for item in chosen}
        with self._sessions.begin() as session:
            late_owner, room = authorize_kakao_room_scope(
                session, actor, binding, room_id, PermissionKey.KAKAO_ARCHIVE_EDIT, lock=False
            )
            self._questions.current_student_pin(session, room, mapping)
            self._sources.validate_question_source_metadata(session, actor, (context,))
            if late_owner != owner:
                raise KakaoArchiveError("KAKAO_ARCHIVE_PERMISSION_DENIED")
            # One indexed membership query for this page, including superseded origins.
            # Their source must never be imported again over the reviewed split/merge.
            registered = (
                {
                    row[0]: (row[1], row[2], row[3] is not None)
                    for row in session.execute(
                        select(
                            KakaoQuestionRecord.origin_occurrence_id,
                            KakaoQuestionRecord.question_id,
                            KakaoQuestionRecord.current_revision_id,
                            KakaoQuestionRecord.superseded_by_composition_id,
                        ).where(
                            KakaoQuestionRecord.owner_operator_id == owner,
                            KakaoQuestionRecord.source_binding_id == binding,
                            KakaoQuestionRecord.room_id == room_id,
                            KakaoQuestionRecord.origin_occurrence_id.in_(tuple(origins)),
                        )
                    )
                }
                if origins
                else {}
            )
        items = []
        for candidate in chosen:
            saved = registered.get(source.occurrence_ids[candidate.student_rows[0]])
            items.append(
                KakaoCandidateSummary(
                    candidate_ordinal=candidate.candidate_ordinal,
                    student_message_count=len(candidate.student_rows),
                    reply_message_count=len(candidate.reply_rows),
                    photo_count=len(candidate.attachments),
                    first_student_at_utc=candidate.first_student_at_utc,
                    preview=source.messages[candidate.student_rows[0]].text[:240],
                    boundary_uncertain=candidate.boundary_uncertain,
                    review_reasons=candidate.review_reasons,
                    saved_question=None
                    if saved is None
                    else KakaoQuestionProvenance(
                        question_id=saved[0], question_revision_id=saved[1]
                    ),
                    recomposed=False if saved is None else saved[2],
                )
            )
        return KakaoQuestionCandidatePage(
            source_binding_id=binding,
            room_id=room_id,
            source_revision_id=selected_revision,
            source_resolution_sha256=context.accepted.manifest.sha256,
            mapping_revision_id=mapping,
            total_candidates=total,
            unknown_sender_rows=sum(
                message.role == "unknown" for message in source.normalization.messages
            ),
            items=tuple(items),
            next_after_ordinal=chosen[-1].candidate_ordinal
            if chosen and chosen[-1].candidate_ordinal < total
            else None,
        )

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
