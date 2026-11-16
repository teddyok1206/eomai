"""Persist exact private questions through existing source and Artifact owners.

Reservations are small metadata. Source reads and immutable publication happen
outside write transactions; adoption checks the original pins and current ACL.
This does not collect messages, reinterpret a snapshot or create a worker queue.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import uuid4

from eom_catalog_contracts.kakao_question import (
    QUESTION_REF,
    KakaoNormalizationRef,
    KakaoQuestionManifest,
    KakaoQuestionProvenance,
    KakaoQuestionStudentPin,
)
from eom_catalog_contracts.kakao_question_store import (
    KakaoQuestionChange,
    KakaoQuestionCreate,
    KakaoQuestionMutation,
    KakaoQuestionPage,
    KakaoStoredQuestion,
)
from eom_catalog_contracts.kakao_rooms import room_mapping_sha256
from eom_catalog_contracts.kakao_students import student_display_sha256
from eom_identifiers import sha256_bytes
from eom_operator_identity.contracts import ActorContext, PermissionKey
from eom_orchestrator.database import build_session_factory
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import Engine, Select, and_, select, tuple_
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.kakao_archive_authorization import (
    KakaoArchiveError,
    authorize_kakao_actor,
    authorize_kakao_binding_scope,
    authorize_kakao_room_scope,
)
from eom_catalog_service.kakao_archive_commands import (
    kakao_command_sha256,
    lock_kakao_intent,
    validate_kakao_idempotency_key,
)
from eom_catalog_service.kakao_question_editing import (
    PublishedKakaoQuestion,
    edit_question,
    question_from_candidate,
    validate_question_sources,
)
from eom_catalog_service.kakao_question_models import (
    KakaoQuestionCommandRecord,
    KakaoQuestionRecord,
    KakaoQuestionRevisionRecord,
)
from eom_catalog_service.kakao_question_publication import (
    MAX_MANIFEST_BYTES,
    KakaoQuestionPublication,
    publish_kakao_question,
)
from eom_catalog_service.kakao_room_models import (
    KakaoRoomMappingRevisionRecord,
    KakaoRoomRecord,
)
from eom_catalog_service.kakao_source_models import KakaoSourceRevisionRecord
from eom_catalog_service.kakao_source_pointers import validate_source_pointer_metadata_batch
from eom_catalog_service.kakao_source_service import (
    AcceptedKakaoQuestionSource,
    KakaoSourceService,
)
from eom_catalog_service.kakao_student_models import (
    KakaoStudentDisplayRevisionRecord,
    KakaoStudentRecord,
)

QuestionCommand = KakaoQuestionCreate | KakaoQuestionChange
_MAX_SOURCE_BYTES = 128 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class AcceptedKakaoQuestion:
    stored: KakaoStoredQuestion
    published: PublishedKakaoQuestion


@dataclass(frozen=True, slots=True)
class ResolvedKakaoQuestions:
    questions: tuple[AcceptedKakaoQuestion, ...]
    sources: tuple[AcceptedKakaoQuestionSource, ...]


@dataclass(frozen=True, slots=True)
class _Reservation:
    command_id: str
    question_id: str
    revision_id: str
    mapping_id: str
    at: datetime
    completed: bool


def _scope_key(command: QuestionCommand) -> str:
    return (
        "candidate/" + command.room_id
        if isinstance(command, KakaoQuestionCreate)
        else "question/" + command.question_id
    )


def _student_pin(
    mapping: KakaoRoomMappingRevisionRecord,
    display: KakaoStudentDisplayRevisionRecord | None,
) -> KakaoQuestionStudentPin | None:
    if mapping.sha256 != room_mapping_sha256(
        student_id=mapping.student_id,
        student_display_revision_id=mapping.student_display_revision_id,
        reason=mapping.reason,
    ):
        raise KakaoArchiveError("KAKAO_ARCHIVE_STORED_ROOM_INVALID")
    if mapping.student_id is None:
        if mapping.state != "UNMAPPED" or display is not None:
            raise KakaoArchiveError("KAKAO_ARCHIVE_STORED_ROOM_INVALID")
        return None
    if (
        mapping.state != "MAPPED"
        or display is None
        or (display.student_id, display.display_revision_id, display.state)
        != (mapping.student_id, mapping.student_display_revision_id, "ACTIVE")
        or display.sha256 != student_display_sha256(display.display_name, "ACTIVE")
    ):
        raise KakaoArchiveError("KAKAO_ARCHIVE_STORED_ROOM_INVALID")
    return KakaoQuestionStudentPin(
        student_id=display.student_id,
        student_display_revision_id=display.display_revision_id,
        room_mapping_revision_id=mapping.mapping_revision_id,
        display_name=display.display_name,
    )


def _mapping_statement() -> Select[
    tuple[KakaoRoomMappingRevisionRecord, KakaoStudentDisplayRevisionRecord]
]:
    return select(KakaoRoomMappingRevisionRecord, KakaoStudentDisplayRevisionRecord).outerjoin(
        KakaoStudentDisplayRevisionRecord,
        and_(
            KakaoStudentDisplayRevisionRecord.student_id
            == KakaoRoomMappingRevisionRecord.student_id,
            KakaoStudentDisplayRevisionRecord.display_revision_id
            == KakaoRoomMappingRevisionRecord.student_display_revision_id,
        ),
    )


class KakaoQuestionService:
    def __init__(
        self,
        engine: Engine,
        *,
        artifacts: CatalogArtifactService,
        sources: KakaoSourceService,
    ) -> None:
        self._sessions = build_session_factory(engine)
        self._artifacts = artifacts
        self._sources = sources

    @staticmethod
    def current_student_pin(
        session: Session, room: KakaoRoomRecord, mapping_id: str
    ) -> KakaoQuestionStudentPin | None:
        """Shared question-write gate; caller holds the authorized room transaction."""
        if room.current_mapping_revision_id != mapping_id:
            raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
        pair = session.execute(
            _mapping_statement().where(
                KakaoRoomMappingRevisionRecord.room_id == room.room_id,
                KakaoRoomMappingRevisionRecord.mapping_revision_id == mapping_id,
                KakaoRoomMappingRevisionRecord.owner_operator_id == room.owner_operator_id,
                KakaoRoomMappingRevisionRecord.source_binding_id == room.source_binding_id,
            )
        ).one_or_none()
        if pair is None:
            raise KakaoArchiveError("KAKAO_ARCHIVE_STORED_ROOM_INVALID")
        pin = _student_pin(pair[0], pair[1])
        if pin is not None:
            student = session.get(KakaoStudentRecord, pin.student_id, populate_existing=True)
            if (
                student is None
                or student.owner_operator_id != room.owner_operator_id
                or student.state != "ACTIVE"
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
        return pin

    @staticmethod
    def _head(session: Session, owner: str, command: KakaoQuestionChange) -> KakaoQuestionRecord:
        head = session.scalar(
            select(KakaoQuestionRecord)
            .where(
                KakaoQuestionRecord.owner_operator_id == owner,
                KakaoQuestionRecord.source_binding_id == command.source_binding_id,
                KakaoQuestionRecord.room_id == command.room_id,
                KakaoQuestionRecord.question_id == command.question_id,
            )
            .with_for_update()
        )
        if head is None:
            raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
        if head.superseded_by_composition_id is not None:
            raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
        if (head.current_revision_id, head.resource_version) != (
            command.edit.parent_revision_id,
            command.expected_resource_version,
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
        return head

    def _reserve(self, actor: ActorContext, command: QuestionCommand, key: str) -> _Reservation:
        digest, scope = kakao_command_sha256(command), _scope_key(command)
        with self._sessions.begin() as session:
            owner = authorize_kakao_actor(
                session, actor, PermissionKey.KAKAO_ARCHIVE_EDIT, now=datetime.now(UTC)
            )
            lock_kakao_intent(session, owner, scope, key)
            _, room = authorize_kakao_room_scope(
                session,
                actor,
                command.source_binding_id,
                command.room_id,
                PermissionKey.KAKAO_ARCHIVE_EDIT,
                lock=True,
            )
            old = session.scalar(
                select(KakaoQuestionCommandRecord).where(
                    KakaoQuestionCommandRecord.owner_operator_id == owner,
                    KakaoQuestionCommandRecord.idempotency_scope == scope,
                    KakaoQuestionCommandRecord.idempotency_key == key,
                )
            )
            if old is not None:
                if old.request_sha256 != digest:
                    raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
                return _Reservation(
                    old.command_id,
                    old.question_id,
                    old.question_revision_id,
                    old.mapping_revision_id,
                    old.reserved_at,
                    old.state == "COMPLETED",
                )
            create = isinstance(command, KakaoQuestionCreate)
            if isinstance(command, KakaoQuestionChange):
                self._head(session, owner, command)
            mapping_id = (
                command.expected_mapping_revision_id
                if isinstance(command, KakaoQuestionCreate)
                else room.current_mapping_revision_id
            )
            self.current_student_pin(session, room, mapping_id)
            result = _Reservation(
                "kakaocommand_" + uuid4().hex,
                "kakaoquestion_" + uuid4().hex
                if isinstance(command, KakaoQuestionCreate)
                else command.question_id,
                "kakaoquestionrev_" + uuid4().hex,
                mapping_id,
                datetime.now(UTC),
                False,
            )
            session.add(
                KakaoQuestionCommandRecord(
                    command_id=result.command_id,
                    owner_operator_id=owner,
                    source_binding_id=command.source_binding_id,
                    room_id=command.room_id,
                    idempotency_scope=scope,
                    idempotency_key=key,
                    request_sha256=digest,
                    action="CREATE" if create else "EDIT",
                    question_id=result.question_id,
                    question_revision_id=result.revision_id,
                    previous_revision_id=None
                    if isinstance(command, KakaoQuestionCreate)
                    else command.edit.parent_revision_id,
                    expected_version=0
                    if isinstance(command, KakaoQuestionCreate)
                    else command.expected_resource_version,
                    mapping_revision_id=mapping_id,
                    state="RESERVED",
                    reserved_at=result.at,
                    completed_at=None,
                )
            )
            return result

    def _check(
        self,
        actor: ActorContext,
        command: QuestionCommand,
        reserved: _Reservation,
        sources: tuple[AcceptedKakaoQuestionSource, ...],
    ) -> KakaoQuestionStudentPin | None:
        with self._sessions.begin() as session:
            owner, room = authorize_kakao_room_scope(
                session,
                actor,
                command.source_binding_id,
                command.room_id,
                PermissionKey.KAKAO_ARCHIVE_EDIT,
                lock=True,
            )
            self._sources.validate_question_source_metadata(session, actor, sources)
            intent = session.get(KakaoQuestionCommandRecord, reserved.command_id)
            if intent is None or intent.request_sha256 != kakao_command_sha256(command):
                raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
            if intent.state == "COMPLETED":
                return self._stored_in_session(
                    session,
                    owner,
                    command.source_binding_id,
                    command.room_id,
                    reserved.question_id,
                    reserved.revision_id,
                ).student
            pin = self.current_student_pin(session, room, reserved.mapping_id)
            if isinstance(command, KakaoQuestionChange):
                self._head(session, owner, command)
            else:
                source = sources[0].resolved
                candidate = source.candidates.get(command.candidate_ordinal)
                if candidate is None:
                    raise KakaoArchiveError("KAKAO_ARCHIVE_CANDIDATE_NOT_FOUND")
                origin = source.occurrence_ids[candidate.student_rows[0]]
                if (
                    session.scalar(
                        select(KakaoQuestionRecord.question_id).where(
                            KakaoQuestionRecord.room_id == command.room_id,
                            KakaoQuestionRecord.origin_occurrence_id == origin,
                        )
                    )
                    is not None
                ):
                    raise KakaoArchiveError("KAKAO_ARCHIVE_CANDIDATE_ALREADY_REGISTERED")
            return pin

    def create_question(
        self, actor: ActorContext, command: KakaoQuestionCreate, *, idempotency_key: str
    ) -> KakaoQuestionMutation:
        command = KakaoQuestionCreate.model_validate(command.model_dump(mode="json"))
        key = validate_kakao_idempotency_key(idempotency_key)
        reserved = self._reserve(actor, command, key)
        if reserved.completed:
            return self._replay(actor, command, reserved)
        context = self._sources.resolve_question_source_context(
            actor,
            command.source_binding_id,
            command.room_id,
            source_revision_id=command.source_revision_id,
        )
        source = context.resolved
        candidate = source.candidates.get(command.candidate_ordinal)
        if candidate is None:
            raise KakaoArchiveError("KAKAO_ARCHIVE_CANDIDATE_NOT_FOUND")
        student = self._check(actor, command, reserved, (context,))
        question = question_from_candidate(
            source,
            candidate,
            question_id=reserved.question_id,
            question_revision_id=reserved.revision_id,
            student=student,
            actor_id=cast(str, actor.operator_id),
            created_at=reserved.at,
        )

        def authorize() -> None:
            self._check(actor, command, reserved, (context,))

        published = publish_kakao_question(
            self._artifacts,
            question=question,
            sources=(source,),
            authorize=authorize,
        )
        return self._adopt(
            actor,
            command,
            reserved,
            published,
            key,
            sources=(context,),
            origin_occurrence_id=source.occurrence_ids[candidate.student_rows[0]],
        )

    def change_question(
        self, actor: ActorContext, command: KakaoQuestionChange, *, idempotency_key: str
    ) -> KakaoQuestionMutation:
        command = KakaoQuestionChange.model_validate(command.model_dump(mode="json"))
        key = validate_kakao_idempotency_key(idempotency_key)
        reserved = self._reserve(actor, command, key)
        if reserved.completed:
            return self._replay(actor, command, reserved)
        accepted, contexts = self._resolved_question(
            actor,
            command.source_binding_id,
            command.room_id,
            command.question_id,
            command.edit.parent_revision_id,
        )
        self._check(actor, command, reserved, contexts)
        sources = tuple(item.resolved for item in contexts)
        question = edit_question(
            accepted.published.question,
            command.edit,
            question_revision_id=reserved.revision_id,
            actor_id=cast(str, actor.operator_id),
            created_at=reserved.at,
            sources=sources,
        )

        def authorize() -> None:
            self._check(actor, command, reserved, contexts)

        published = publish_kakao_question(
            self._artifacts,
            question=question,
            sources=sources,
            authorize=authorize,
        )
        return self._adopt(actor, command, reserved, published, key, sources=contexts)

    def _adopt(
        self,
        actor: ActorContext,
        command: QuestionCommand,
        reserved: _Reservation,
        publication: KakaoQuestionPublication,
        key: str,
        *,
        sources: tuple[AcceptedKakaoQuestionSource, ...],
        origin_occurrence_id: str | None = None,
    ) -> KakaoQuestionMutation:
        question, pointer = publication.published.question, publication.published.pointer
        with self._sessions.begin() as session:
            owner = authorize_kakao_actor(
                session, actor, PermissionKey.KAKAO_ARCHIVE_EDIT, now=datetime.now(UTC)
            )
            lock_kakao_intent(session, owner, _scope_key(command), key)
            _, room = authorize_kakao_room_scope(
                session,
                actor,
                command.source_binding_id,
                command.room_id,
                PermissionKey.KAKAO_ARCHIVE_EDIT,
                lock=True,
            )
            intent = session.get(KakaoQuestionCommandRecord, reserved.command_id)
            if (
                intent is None
                or intent.owner_operator_id != owner
                or intent.request_sha256 != kakao_command_sha256(command)
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
            self._sources.validate_question_source_metadata(session, actor, sources)
            pointers = (
                pointer,
                *(source.pointer for source in question.sources),
                *(
                    block.source_pointer
                    for block in question.ordered_blocks
                    if block.kind == "IMAGE" and block.source_pointer is not None
                ),
            )
            metadata = validate_source_pointer_metadata_batch(session, pointers)
            logical, revision = metadata[(pointer.artifact_id, pointer.artifact_revision_id)]
            if (
                logical.artifact_type != "kakao-question-manifest"
                or revision.job_id != publication.publication_job_id
                or revision.content_hash != pointer.sha256
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_EVIDENCE_INVALID")
            if intent.state == "COMPLETED":
                stored = self._stored_in_session(
                    session,
                    owner,
                    command.source_binding_id,
                    command.room_id,
                    reserved.question_id,
                    reserved.revision_id,
                )
                if stored.manifest != pointer:
                    raise KakaoArchiveError("KAKAO_ARCHIVE_STORED_QUESTION_INVALID")
                return KakaoQuestionMutation(question=stored, replayed=True)
            pin = self.current_student_pin(session, room, reserved.mapping_id)
            if question.student != pin:
                raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
            if isinstance(command, KakaoQuestionCreate):
                if origin_occurrence_id is None:
                    raise KakaoArchiveError("KAKAO_ARCHIVE_STORED_QUESTION_INVALID")
                if (
                    session.scalar(
                        select(KakaoQuestionRecord.question_id).where(
                            KakaoQuestionRecord.room_id == command.room_id,
                            KakaoQuestionRecord.origin_occurrence_id == origin_occurrence_id,
                        )
                    )
                    is not None
                ):
                    raise KakaoArchiveError("KAKAO_ARCHIVE_CANDIDATE_ALREADY_REGISTERED")
                source = session.scalar(
                    select(KakaoSourceRevisionRecord).where(
                        KakaoSourceRevisionRecord.source_revision_id == command.source_revision_id,
                        KakaoSourceRevisionRecord.owner_operator_id == owner,
                        KakaoSourceRevisionRecord.source_binding_id == command.source_binding_id,
                        KakaoSourceRevisionRecord.room_id == command.room_id,
                    )
                )
                if (
                    source is None
                    or len(question.sources) != 1
                    or question.sources[0].normalization_revision_id
                    != source.normalization_revision_id
                ):
                    raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
                head = KakaoQuestionRecord(
                    question_id=reserved.question_id,
                    owner_operator_id=owner,
                    source_binding_id=command.source_binding_id,
                    room_id=command.room_id,
                    origin_source_revision_id=command.source_revision_id,
                    origin_candidate_ordinal=command.candidate_ordinal,
                    origin_occurrence_id=origin_occurrence_id,
                    current_revision_id=reserved.revision_id,
                    resource_version=1,
                    created_at=reserved.at,
                )
                session.add(head)
                session.flush()
            else:
                head = self._head(session, owner, command)
                head.current_revision_id, head.resource_version = (
                    reserved.revision_id,
                    command.expected_resource_version + 1,
                )
            session.add(
                KakaoQuestionRevisionRecord(
                    question_revision_id=reserved.revision_id,
                    question_id=reserved.question_id,
                    room_id=command.room_id,
                    command_id=reserved.command_id,
                    previous_revision_id=question.previous_revision_id,
                    resource_version=head.resource_version,
                    mapping_revision_id=reserved.mapping_id,
                    review_state=question.review_state,
                    first_student_at_utc=question.first_student_at_utc,
                    manifest_artifact_id=pointer.artifact_id,
                    manifest_artifact_revision_id=pointer.artifact_revision_id,
                    manifest_sha256=pointer.sha256,
                    publication_job_id=publication.publication_job_id,
                    created_at=reserved.at,
                )
            )
            intent.state, intent.completed_at = "COMPLETED", datetime.now(UTC)
            session.flush()
            stored = self._stored_in_session(
                session,
                owner,
                command.source_binding_id,
                command.room_id,
                reserved.question_id,
                reserved.revision_id,
            )
            return KakaoQuestionMutation(question=stored, replayed=False)

    @staticmethod
    def _descriptor(
        head: KakaoQuestionRecord,
        revision: KakaoQuestionRevisionRecord,
        mapping: KakaoRoomMappingRevisionRecord,
        display: KakaoStudentDisplayRevisionRecord | None,
    ) -> KakaoStoredQuestion:
        if (
            revision.question_id,
            revision.room_id,
            mapping.room_id,
            mapping.owner_operator_id,
            mapping.source_binding_id,
        ) != (
            head.question_id,
            head.room_id,
            head.room_id,
            head.owner_operator_id,
            head.source_binding_id,
        ) or (
            head.current_revision_id == revision.question_revision_id
            and head.resource_version != revision.resource_version
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_STORED_QUESTION_INVALID")
        return KakaoStoredQuestion(
            source_binding_id=head.source_binding_id,
            room_id=head.room_id,
            question_id=head.question_id,
            question_revision_id=revision.question_revision_id,
            previous_revision_id=revision.previous_revision_id,
            resource_version=revision.resource_version,
            manifest=ArtifactMemberPointer(
                artifact_id=revision.manifest_artifact_id,
                artifact_revision_id=revision.manifest_artifact_revision_id,
                member_path="question.json",
                schema_ref=QUESTION_REF,
                media_type="application/json",
                sha256=revision.manifest_sha256,
            ),
            review_state=cast(
                Literal["UNREVIEWED", "CONFIRMED", "EXCLUDED"], revision.review_state
            ),
            first_student_at_utc=revision.first_student_at_utc,
            student=_student_pin(mapping, display),
            created_at=revision.created_at,
        )

    @staticmethod
    def _read_statement() -> Select[
        tuple[
            KakaoQuestionRecord,
            KakaoQuestionRevisionRecord,
            KakaoRoomMappingRevisionRecord,
            KakaoStudentDisplayRevisionRecord,
        ]
    ]:
        return (
            select(
                KakaoQuestionRecord,
                KakaoQuestionRevisionRecord,
                KakaoRoomMappingRevisionRecord,
                KakaoStudentDisplayRevisionRecord,
            )
            .join(
                KakaoQuestionRevisionRecord,
                KakaoQuestionRevisionRecord.question_id == KakaoQuestionRecord.question_id,
            )
            .join(
                KakaoRoomMappingRevisionRecord,
                and_(
                    KakaoRoomMappingRevisionRecord.room_id == KakaoQuestionRecord.room_id,
                    KakaoRoomMappingRevisionRecord.mapping_revision_id
                    == KakaoQuestionRevisionRecord.mapping_revision_id,
                ),
            )
            .outerjoin(
                KakaoStudentDisplayRevisionRecord,
                and_(
                    KakaoStudentDisplayRevisionRecord.student_id
                    == KakaoRoomMappingRevisionRecord.student_id,
                    KakaoStudentDisplayRevisionRecord.display_revision_id
                    == KakaoRoomMappingRevisionRecord.student_display_revision_id,
                ),
            )
        )

    @classmethod
    def _stored_in_session(
        cls,
        session: Session,
        owner: str,
        binding: str,
        room: str,
        question_id: str,
        revision_id: str,
    ) -> KakaoStoredQuestion:
        row = session.execute(
            cls._read_statement().where(
                KakaoQuestionRecord.owner_operator_id == owner,
                KakaoQuestionRecord.source_binding_id == binding,
                KakaoQuestionRecord.room_id == room,
                KakaoQuestionRecord.question_id == question_id,
                KakaoQuestionRevisionRecord.question_revision_id == revision_id,
            )
        ).one_or_none()
        if row is None:
            raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
        return cls._descriptor(*row)

    def _sources_for(
        self, actor: ActorContext, binding_id: str, questions: tuple[KakaoQuestionManifest, ...]
    ) -> tuple[AcceptedKakaoQuestionSource, ...]:
        pins: dict[str, KakaoNormalizationRef] = {}
        rooms: dict[str, str] = {}
        for question in questions:
            if question.source_binding_id != binding_id:
                raise KakaoArchiveError("KAKAO_ARCHIVE_SOURCE_REFERENCE_INVALID")
            for pin in question.sources:
                identity = pin.normalization_revision_id
                if (
                    pins.setdefault(identity, pin) != pin
                    or rooms.setdefault(identity, question.room_id) != question.room_id
                ):
                    raise KakaoArchiveError("KAKAO_ARCHIVE_SOURCE_REFERENCE_INVALID")
        with self._sessions.begin() as session:
            owner, _ = authorize_kakao_binding_scope(
                session, actor, binding_id, PermissionKey.KAKAO_ARCHIVE_READ, lock=False
            )
            rows = tuple(
                session.scalars(
                    select(KakaoSourceRevisionRecord).where(
                        KakaoSourceRevisionRecord.owner_operator_id == owner,
                        KakaoSourceRevisionRecord.source_binding_id == binding_id,
                        KakaoSourceRevisionRecord.normalization_revision_id.in_(tuple(pins)),
                    )
                )
            )
            if (
                len(rows) != len(pins)
                or sum(row.row_count for row in rows) > 100000
                or any(row.room_id != rooms[row.normalization_revision_id] for row in rows)
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_SOURCE_REFERENCE_INVALID")
            metadata = validate_source_pointer_metadata_batch(
                session, tuple(pin.pointer for pin in pins.values())
            )
            total = 0
            for pin in pins.values():
                _, revision = metadata[(pin.pointer.artifact_id, pin.pointer.artifact_revision_id)]
                total += sum(
                    entry["bytes"]
                    for entry in revision.manifest["files"]
                    if entry["file_name"] == pin.pointer.member_path
                )
            if total > _MAX_SOURCE_BYTES:
                raise KakaoArchiveError("KAKAO_ARCHIVE_SOURCE_BYTES_LIMIT")
            identities = {row.normalization_revision_id: row.source_revision_id for row in rows}
        result = tuple(
            self._sources.resolve_question_source_context(
                actor, binding_id, rooms[identity], source_revision_id=identities[identity]
            )
            for identity in pins
        )
        if any(
            item.resolved.reference != pins[item.resolved.normalization.normalization_revision_id]
            for item in result
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_SOURCE_REFERENCE_INVALID")
        return result

    def _read_manifest(
        self, actor: ActorContext, stored: KakaoStoredQuestion
    ) -> KakaoQuestionManifest:
        pointer = stored.manifest
        try:
            raw = self._artifacts.read_member(
                artifact_id=pointer.artifact_id,
                revision_id=pointer.artifact_revision_id,
                member_path=pointer.member_path,
                schema_ref=pointer.schema_ref,
                media_type=pointer.media_type,
                sha256=pointer.sha256,
                max_bytes=MAX_MANIFEST_BYTES,
            )
            if len(raw) > MAX_MANIFEST_BYTES or sha256_bytes(raw) != pointer.sha256:
                raise ValueError("question hash mismatch")
            question = KakaoQuestionManifest.model_validate_json(raw)
            if question.created_by != actor.operator_id or (
                question.question_id,
                question.question_revision_id,
                question.previous_revision_id,
                question.source_binding_id,
                question.room_id,
                question.review_state,
                question.first_student_at_utc,
                question.student,
                question.created_at,
            ) != (
                stored.question_id,
                stored.question_revision_id,
                stored.previous_revision_id,
                stored.source_binding_id,
                stored.room_id,
                stored.review_state,
                stored.first_student_at_utc,
                stored.student,
                stored.created_at,
            ):
                raise ValueError("question projection mismatch")
            return question
        except (ValueError, OSError):
            raise KakaoArchiveError("KAKAO_ARCHIVE_STORED_QUESTION_INVALID") from None

    def resolve_questions(
        self,
        actor: ActorContext,
        binding_id: str,
        pins: tuple[KakaoQuestionProvenance, ...],
        *,
        room_id: str | None = None,
    ) -> ResolvedKakaoQuestions:
        """Exact ordered selection, one indexed read and one parse per unique source.

        Shared by packet creation and export. No source cache survives this request;
        current permission/lifecycle is rechecked after all file materialization.
        """
        identities = tuple((pin.question_id, pin.question_revision_id) for pin in pins)
        if not 1 <= len(identities) <= 200 or len(set(identities)) != len(identities):
            raise KakaoArchiveError("KAKAO_ARCHIVE_QUESTION_SELECTION_INVALID")
        with self._sessions.begin() as session:
            owner, _ = authorize_kakao_binding_scope(
                session, actor, binding_id, PermissionKey.KAKAO_ARCHIVE_READ, lock=False
            )
            statement = (
                self._read_statement()
                .join(KakaoRoomRecord, KakaoRoomRecord.room_id == KakaoQuestionRecord.room_id)
                .where(
                    KakaoQuestionRecord.owner_operator_id == owner,
                    KakaoQuestionRecord.source_binding_id == binding_id,
                    KakaoRoomRecord.state == "ACTIVE",
                    tuple_(
                        KakaoQuestionRecord.question_id,
                        KakaoQuestionRevisionRecord.question_revision_id,
                    ).in_(identities),
                )
            )
            if room_id is not None:
                authorize_kakao_room_scope(
                    session,
                    actor,
                    binding_id,
                    room_id,
                    PermissionKey.KAKAO_ARCHIVE_READ,
                    lock=False,
                )
                statement = statement.where(KakaoQuestionRecord.room_id == room_id)
            rows = session.execute(statement).all()
            stored_by_id = {
                (row[0].question_id, row[1].question_revision_id): self._descriptor(*row)
                for row in rows
            }
            if len(stored_by_id) != len(identities):
                raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
            ordered = tuple(stored_by_id[identity] for identity in identities)
            metadata = validate_source_pointer_metadata_batch(
                session, tuple(item.manifest for item in ordered)
            )
            expected_jobs = {
                (row[1].manifest_artifact_id, row[1].manifest_artifact_revision_id): row[
                    1
                ].publication_job_id
                for row in rows
            }
            if any(
                logical.artifact_type != "kakao-question-manifest"
                or revision.job_id != expected_jobs[identity]
                or revision.manifest.get("primary_file") != "question.json"
                for identity, (logical, revision) in metadata.items()
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_EVIDENCE_INVALID")
            total = sum(
                entry["bytes"]
                for _, revision in metadata.values()
                for entry in revision.manifest["files"]
                if entry["file_name"] == "question.json"
            )
            if total > _MAX_SOURCE_BYTES:
                raise KakaoArchiveError("KAKAO_ARCHIVE_SOURCE_BYTES_LIMIT")
        questions = tuple(self._read_manifest(actor, item) for item in ordered)
        sources = self._sources_for(actor, binding_id, questions)
        by_normalization = {
            item.resolved.normalization.normalization_revision_id: item.resolved for item in sources
        }
        for question in questions:
            validate_question_sources(
                question,
                tuple(by_normalization[pin.normalization_revision_id] for pin in question.sources),
            )
        with self._sessions.begin() as session:
            authorize_kakao_binding_scope(
                session, actor, binding_id, PermissionKey.KAKAO_ARCHIVE_READ, lock=False
            )
            self._sources.validate_question_source_metadata(session, actor, sources)
            validate_source_pointer_metadata_batch(
                session, tuple(item.manifest for item in ordered)
            )
        return ResolvedKakaoQuestions(
            tuple(
                AcceptedKakaoQuestion(stored, PublishedKakaoQuestion(question, stored.manifest))
                for stored, question in zip(ordered, questions, strict=True)
            ),
            sources,
        )

    def _resolved_question(
        self, actor: ActorContext, binding: str, room: str, question_id: str, revision_id: str
    ) -> tuple[AcceptedKakaoQuestion, tuple[AcceptedKakaoQuestionSource, ...]]:
        result = self.resolve_questions(
            actor,
            binding,
            (KakaoQuestionProvenance(question_id=question_id, question_revision_id=revision_id),),
            room_id=room,
        )
        return result.questions[0], result.sources

    def get_question(
        self,
        actor: ActorContext,
        source_binding_id: str,
        room_id: str,
        question_id: str,
        *,
        revision_id: str,
    ) -> AcceptedKakaoQuestion:
        return self._resolved_question(actor, source_binding_id, room_id, question_id, revision_id)[
            0
        ]

    def _replay(
        self, actor: ActorContext, command: QuestionCommand, reserved: _Reservation
    ) -> KakaoQuestionMutation:
        accepted = self.get_question(
            actor,
            command.source_binding_id,
            command.room_id,
            reserved.question_id,
            revision_id=reserved.revision_id,
        )
        return KakaoQuestionMutation(question=accepted.stored, replayed=True)

    def list_questions(
        self,
        actor: ActorContext,
        source_binding_id: str,
        *,
        room_id: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> KakaoQuestionPage:
        if (
            type(limit) is not int
            or not 1 <= limit <= 100
            or (cursor is not None and re.fullmatch(r"kakaoquestion_[0-9a-f]{32}", cursor) is None)
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_REQUEST_INVALID")
        with self._sessions.begin() as session:
            owner, _ = authorize_kakao_binding_scope(
                session, actor, source_binding_id, PermissionKey.KAKAO_ARCHIVE_READ, lock=False
            )
            statement = (
                self._read_statement()
                .join(KakaoRoomRecord, KakaoRoomRecord.room_id == KakaoQuestionRecord.room_id)
                .where(
                    KakaoQuestionRecord.owner_operator_id == owner,
                    KakaoQuestionRecord.source_binding_id == source_binding_id,
                    KakaoQuestionRecord.superseded_by_composition_id.is_(None),
                    KakaoRoomRecord.state == "ACTIVE",
                    KakaoQuestionRevisionRecord.question_revision_id
                    == KakaoQuestionRecord.current_revision_id,
                )
            )
            if room_id is not None:
                authorize_kakao_room_scope(
                    session,
                    actor,
                    source_binding_id,
                    room_id,
                    PermissionKey.KAKAO_ARCHIVE_READ,
                    lock=False,
                )
                statement = statement.where(KakaoQuestionRecord.room_id == room_id)
            if cursor is not None:
                statement = statement.where(KakaoQuestionRecord.question_id > cursor)
            rows = session.execute(
                statement.order_by(KakaoQuestionRecord.question_id).limit(limit + 1)
            ).all()
            items = tuple(self._descriptor(*row) for row in rows[:limit])
            validate_source_pointer_metadata_batch(session, tuple(item.manifest for item in items))
            return KakaoQuestionPage(
                items=items, next_cursor=items[-1].question_id if len(rows) > limit else None
            )
