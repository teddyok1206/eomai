"""Owner-scoped student directory with exact display revisions and idempotent edits."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from eom_catalog_contracts.kakao_students import (
    KakaoStudent,
    KakaoStudentCommand,
    KakaoStudentCreate,
    KakaoStudentMutation,
    KakaoStudentPage,
    KakaoStudentRename,
    KakaoStudentRetire,
    StudentState,
    student_display_sha256,
)
from eom_operator_identity.contracts import ActorContext, PermissionKey
from eom_orchestrator.database import build_session_factory
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError, authorize_kakao_actor
from eom_catalog_service.kakao_archive_commands import (
    kakao_command_sha256,
    lock_kakao_intent,
    validate_kakao_idempotency_key,
)
from eom_catalog_service.kakao_student_models import (
    KakaoStudentCommandRecord,
    KakaoStudentDisplayRevisionRecord,
    KakaoStudentRecord,
)


def _student_id(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"kakaostudent_[0-9a-f]{32}", value) is None:
        raise KakaoArchiveError("KAKAO_ARCHIVE_REQUEST_INVALID")
    return value


def _view(student: KakaoStudentRecord, revision: KakaoStudentDisplayRevisionRecord) -> KakaoStudent:
    try:
        if student.student_id != revision.student_id or (
            student.current_display_revision_id == revision.display_revision_id
            and (
                student.resource_version != revision.revision_number
                or student.state != revision.state
            )
        ):
            raise ValueError("invalid stored identity")
        return KakaoStudent(
            student_id=student.student_id,
            display_revision_id=revision.display_revision_id,
            previous_revision_id=revision.previous_revision_id,
            resource_version=revision.revision_number,
            display_name=revision.display_name,
            state=cast(StudentState, revision.state),
            sha256=revision.sha256,
            created_at=student.created_at,
            updated_at=revision.created_at,
        )
    except ValueError:
        raise KakaoArchiveError("KAKAO_ARCHIVE_STORED_STUDENT_INVALID") from None


class KakaoStudentService:
    def __init__(self, engine: Engine) -> None:
        self._sessions = build_session_factory(engine)

    @staticmethod
    def _authorize(session: Session, actor: ActorContext, *, mutate: bool) -> str:
        return authorize_kakao_actor(
            session,
            actor,
            PermissionKey.KAKAO_ARCHIVE_EDIT if mutate else PermissionKey.KAKAO_ARCHIVE_READ,
            now=datetime.now(UTC),
        )

    @staticmethod
    def _owned(
        session: Session, owner: str, student_id: str, *, lock: bool = False
    ) -> KakaoStudentRecord:
        statement = select(KakaoStudentRecord).where(
            KakaoStudentRecord.student_id == student_id,
            KakaoStudentRecord.owner_operator_id == owner,
        )
        if lock:
            statement = statement.with_for_update()
        row = session.scalar(statement)
        if row is None:
            raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
        return row

    @staticmethod
    def _revision(
        session: Session, student_id: str, revision_id: str
    ) -> KakaoStudentDisplayRevisionRecord:
        row = session.scalar(
            select(KakaoStudentDisplayRevisionRecord).where(
                KakaoStudentDisplayRevisionRecord.student_id == student_id,
                KakaoStudentDisplayRevisionRecord.display_revision_id == revision_id,
            )
        )
        if row is None:
            raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
        return row

    def _replay(
        self, session: Session, owner: str, scope: str, key: str, request_hash: str
    ) -> KakaoStudentMutation | None:
        row = session.scalar(
            select(KakaoStudentCommandRecord).where(
                KakaoStudentCommandRecord.owner_operator_id == owner,
                KakaoStudentCommandRecord.idempotency_scope == scope,
                KakaoStudentCommandRecord.idempotency_key == key,
            )
        )
        if row is None:
            return None
        if row.request_sha256 != request_hash:
            raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
        student = self._owned(session, owner, row.student_id)
        revision = self._revision(session, student.student_id, row.result_display_revision_id)
        return KakaoStudentMutation(student=_view(student, revision), replayed=True)

    @staticmethod
    def _record(
        session: Session,
        actor: ActorContext,
        student: KakaoStudentRecord,
        revision: KakaoStudentDisplayRevisionRecord,
        scope: str,
        key: str,
        digest: str,
        action: str,
    ) -> None:
        session.add(
            KakaoStudentCommandRecord(
                command_id="kakaocommand_" + uuid4().hex,
                owner_operator_id=student.owner_operator_id,
                student_id=student.student_id,
                idempotency_scope=scope,
                idempotency_key=key,
                request_sha256=digest,
                request_id=actor.request_id,
                action=action,
                result_display_revision_id=revision.display_revision_id,
                completed_at=revision.created_at,
            )
        )

    def create_student(
        self, actor: ActorContext, command: KakaoStudentCreate, *, idempotency_key: str
    ) -> KakaoStudentMutation:
        try:
            command = KakaoStudentCreate.model_validate(command.model_dump(mode="json"))
        except (AttributeError, ValueError):
            raise KakaoArchiveError("KAKAO_ARCHIVE_REQUEST_INVALID") from None
        key = validate_kakao_idempotency_key(idempotency_key)
        digest, scope = kakao_command_sha256(command), "students"
        with self._sessions.begin() as session:
            owner = self._authorize(session, actor, mutate=True)
            lock_kakao_intent(session, owner, scope, key)
            self._authorize(session, actor, mutate=True)
            replay = self._replay(session, owner, scope, key, digest)
            if replay is not None:
                return replay
            now = datetime.now(UTC)
            student_id, revision_id = (
                "kakaostudent_" + uuid4().hex,
                "kakaostudentrev_" + uuid4().hex,
            )
            student = KakaoStudentRecord(
                student_id=student_id,
                owner_operator_id=owner,
                state="ACTIVE",
                resource_version=1,
                current_display_revision_id=revision_id,
                created_at=now,
            )
            revision = KakaoStudentDisplayRevisionRecord(
                display_revision_id=revision_id,
                student_id=student_id,
                previous_revision_id=None,
                revision_number=1,
                display_name=command.display_name,
                state="ACTIVE",
                sha256=student_display_sha256(command.display_name, "ACTIVE"),
                created_at=now,
                created_by=owner,
            )
            session.add(student)
            session.flush([student])
            session.add(revision)
            session.flush([revision])
            self._record(session, actor, student, revision, scope, key, digest, command.action)
            return KakaoStudentMutation(student=_view(student, revision), replayed=False)

    def command_student(
        self,
        actor: ActorContext,
        student_id: str,
        command: KakaoStudentCommand,
        *,
        idempotency_key: str,
    ) -> KakaoStudentMutation:
        _student_id(student_id)
        try:
            if isinstance(command, KakaoStudentRename):
                command = KakaoStudentRename.model_validate(command.model_dump(mode="json"))
            elif isinstance(command, KakaoStudentRetire):
                command = KakaoStudentRetire.model_validate(command.model_dump(mode="json"))
            else:
                raise ValueError("unsupported student command")
        except ValueError:
            raise KakaoArchiveError("KAKAO_ARCHIVE_REQUEST_INVALID") from None
        key = validate_kakao_idempotency_key(idempotency_key)
        digest, scope = kakao_command_sha256(command), "students/" + student_id + "/commands"
        with self._sessions.begin() as session:
            owner = self._authorize(session, actor, mutate=True)
            lock_kakao_intent(session, owner, scope, key)
            student = self._owned(session, owner, student_id, lock=True)
            self._authorize(session, actor, mutate=True)
            replay = self._replay(session, owner, scope, key, digest)
            if replay is not None:
                return replay
            if (
                student.resource_version != command.expected_resource_version
                or student.current_display_revision_id != command.parent_revision_id
                or student.resource_version == 2147483647
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
            if student.state != "ACTIVE":
                raise KakaoArchiveError("KAKAO_ARCHIVE_STUDENT_RETIRED")
            previous = self._revision(session, student_id, student.current_display_revision_id)
            _view(student, previous)
            name = (
                command.display_name
                if isinstance(command, KakaoStudentRename)
                else previous.display_name
            )
            state: StudentState = "RETIRED" if isinstance(command, KakaoStudentRetire) else "ACTIVE"
            revision = KakaoStudentDisplayRevisionRecord(
                display_revision_id="kakaostudentrev_" + uuid4().hex,
                student_id=student_id,
                previous_revision_id=previous.display_revision_id,
                revision_number=student.resource_version + 1,
                display_name=name,
                state=state,
                sha256=student_display_sha256(name, state),
                created_at=datetime.now(UTC),
                created_by=owner,
            )
            session.add(revision)
            session.flush([revision])
            student.current_display_revision_id = revision.display_revision_id
            student.resource_version = revision.revision_number
            student.state = state
            self._record(session, actor, student, revision, scope, key, digest, command.action)
            return KakaoStudentMutation(student=_view(student, revision), replayed=False)

    def get_student(
        self, actor: ActorContext, student_id: str, *, display_revision_id: str | None = None
    ) -> KakaoStudent:
        _student_id(student_id)
        if (
            display_revision_id is not None
            and re.fullmatch(r"kakaostudentrev_[0-9a-f]{32}", display_revision_id) is None
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_REQUEST_INVALID")
        with self._sessions.begin() as session:
            owner = self._authorize(session, actor, mutate=False)
            student = self._owned(session, owner, student_id)
            revision = self._revision(
                session, student_id, display_revision_id or student.current_display_revision_id
            )
            return _view(student, revision)

    def list_students(
        self, actor: ActorContext, *, limit: int = 50, cursor: str | None = None
    ) -> KakaoStudentPage:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise KakaoArchiveError("KAKAO_ARCHIVE_REQUEST_INVALID")
        if cursor is not None:
            _student_id(cursor)
        with self._sessions.begin() as session:
            owner = self._authorize(session, actor, mutate=False)
            statement = (
                select(KakaoStudentRecord, KakaoStudentDisplayRevisionRecord)
                .join(
                    KakaoStudentDisplayRevisionRecord,
                    (KakaoStudentDisplayRevisionRecord.student_id == KakaoStudentRecord.student_id)
                    & (
                        KakaoStudentDisplayRevisionRecord.display_revision_id
                        == KakaoStudentRecord.current_display_revision_id
                    ),
                )
                .where(KakaoStudentRecord.owner_operator_id == owner)
            )
            if cursor is not None:
                statement = statement.where(KakaoStudentRecord.student_id > cursor)
            rows = session.execute(
                statement.order_by(KakaoStudentRecord.student_id).limit(limit + 1)
            ).all()
            items = tuple(_view(student, revision) for student, revision in rows[:limit])
            return KakaoStudentPage(
                items=items, next_cursor=items[-1].student_id if len(rows) > limit else None
            )
