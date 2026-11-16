"""Immutable private packet acceptance, without rendering, collection or a new queue."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from eom_catalog_contracts.kakao_packet_store import (
    PACKET_REF,
    KakaoPacketCommand,
    KakaoPacketCreate,
    KakaoPacketMutation,
    KakaoPacketPage,
    KakaoPacketRevise,
    KakaoStoredPacket,
)
from eom_catalog_contracts.kakao_question import KakaoQuestionPacket, KakaoQuestionProvenance
from eom_identifiers import sha256_bytes
from eom_operator_identity import ActorContext, PermissionKey
from eom_orchestrator.database import build_session_factory
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import TypeAdapter
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.kakao_archive_authorization import (
    KakaoArchiveError,
    authorize_kakao_actor,
    authorize_kakao_binding_scope,
    authorize_kakao_room_scopes,
)
from eom_catalog_service.kakao_archive_commands import (
    kakao_command_sha256,
    lock_kakao_intent,
    validate_kakao_idempotency_key,
)
from eom_catalog_service.kakao_packet_models import (
    KakaoPacketCommandRecord,
    KakaoPacketRecord,
    KakaoPacketRevisionRecord,
)
from eom_catalog_service.kakao_question_editing import build_question_packet, packet_student_subset
from eom_catalog_service.kakao_question_publication import (
    MAX_MANIFEST_BYTES,
    KakaoPacketPublication,
    publish_kakao_packet,
)
from eom_catalog_service.kakao_question_service import KakaoQuestionService, ResolvedKakaoQuestions
from eom_catalog_service.kakao_source_pointers import validate_source_pointer_metadata_batch
from eom_catalog_service.kakao_source_service import KakaoSourceService


@dataclass(frozen=True, slots=True)
class AcceptedKakaoPacket:
    stored: KakaoStoredPacket
    packet: KakaoQuestionPacket


@dataclass(frozen=True, slots=True)
class _Reservation:
    command_id: str
    packet_id: str
    revision_id: str
    at: datetime
    completed: bool


_COMMAND: TypeAdapter[KakaoPacketCommand] = TypeAdapter(KakaoPacketCommand)


def _scope(command: KakaoPacketCommand) -> str:
    return (
        "packet/" + command.packet_id
        if isinstance(command, KakaoPacketRevise)
        else "packet/create/" + command.source_binding_id
    )


def _view(row: KakaoPacketRevisionRecord) -> KakaoStoredPacket:
    return KakaoStoredPacket.model_validate(
        dict(
            source_binding_id=row.source_binding_id,
            packet_id=row.packet_id,
            packet_revision_id=row.packet_revision_id,
            previous_revision_id=row.previous_revision_id,
            resource_version=row.resource_version,
            title=row.title,
            mode=row.mode,
            include_replies=row.include_replies,
            display_start_date=row.display_start_date,
            display_end_date_inclusive=row.display_end_date_inclusive,
            question_count=row.question_count,
            student_count=row.student_count,
            created_at=row.created_at,
            manifest=ArtifactMemberPointer(
                artifact_id=row.manifest_artifact_id,
                artifact_revision_id=row.manifest_artifact_revision_id,
                member_path="packet.json",
                schema_ref=PACKET_REF,
                media_type="application/json",
                sha256=row.manifest_sha256,
            ),
        )
    )


class KakaoPacketService:
    def __init__(
        self,
        engine: Engine,
        *,
        artifacts: CatalogArtifactService,
        questions: KakaoQuestionService,
        sources: KakaoSourceService,
    ) -> None:
        self._sessions = build_session_factory(engine)
        self._artifacts, self._questions, self._sources = artifacts, questions, sources

    @staticmethod
    def _parent(
        session: Session, owner: str, command: KakaoPacketCommand
    ) -> KakaoPacketRecord | None:
        if isinstance(command, KakaoPacketCreate):
            return None
        head = session.scalar(
            select(KakaoPacketRecord)
            .where(
                KakaoPacketRecord.packet_id == command.packet_id,
                KakaoPacketRecord.source_binding_id == command.source_binding_id,
                KakaoPacketRecord.owner_operator_id == owner,
            )
            .with_for_update()
        )
        if head is None:
            raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
        if (head.current_revision_id, head.resource_version) != (
            command.parent_revision_id,
            command.expected_resource_version,
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
        return head

    def _reserve(self, actor: ActorContext, command: KakaoPacketCommand, key: str) -> _Reservation:
        digest = kakao_command_sha256(command)
        with self._sessions.begin() as session:
            owner = authorize_kakao_actor(
                session, actor, PermissionKey.KAKAO_ARCHIVE_EXPORT, now=datetime.now(UTC)
            )
            lock_kakao_intent(session, owner, _scope(command), key)
            authorize_kakao_binding_scope(
                session,
                actor,
                command.source_binding_id,
                PermissionKey.KAKAO_ARCHIVE_EXPORT,
                lock=True,
            )
            old = session.scalar(
                select(KakaoPacketCommandRecord).where(
                    KakaoPacketCommandRecord.owner_operator_id == owner,
                    KakaoPacketCommandRecord.idempotency_scope == _scope(command),
                    KakaoPacketCommandRecord.idempotency_key == key,
                )
            )
            if old is not None:
                if old.request_sha256 != digest:
                    raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
                return _Reservation(
                    old.command_id,
                    old.packet_id,
                    old.packet_revision_id,
                    old.reserved_at,
                    old.state == "COMPLETED",
                )
            self._parent(session, owner, command)
            item = _Reservation(
                "kakaocommand_" + uuid4().hex,
                command.packet_id
                if isinstance(command, KakaoPacketRevise)
                else "kakaopacket_" + uuid4().hex,
                "kakaopacketrev_" + uuid4().hex,
                datetime.now(UTC),
                False,
            )
            session.add(
                KakaoPacketCommandRecord(
                    command_id=item.command_id,
                    owner_operator_id=owner,
                    source_binding_id=command.source_binding_id,
                    idempotency_scope=_scope(command),
                    idempotency_key=key,
                    request_sha256=digest,
                    packet_id=item.packet_id,
                    packet_revision_id=item.revision_id,
                    previous_revision_id=command.parent_revision_id
                    if isinstance(command, KakaoPacketRevise)
                    else None,
                    expected_version=command.expected_resource_version
                    if isinstance(command, KakaoPacketRevise)
                    else 0,
                    state="RESERVED",
                    reserved_at=item.at,
                    completed_at=None,
                )
            )
            return item

    def _check(
        self,
        actor: ActorContext,
        command: KakaoPacketCommand,
        reserved: _Reservation,
        selection: ResolvedKakaoQuestions,
    ) -> None:
        with self._sessions.begin() as session:
            owner, _ = authorize_kakao_binding_scope(
                session,
                actor,
                command.source_binding_id,
                PermissionKey.KAKAO_ARCHIVE_EXPORT,
                lock=True,
            )
            self._sources.validate_question_source_metadata(session, actor, selection.sources)
            validate_source_pointer_metadata_batch(
                session, tuple(item.stored.manifest for item in selection.questions)
            )
            intent = session.get(KakaoPacketCommandRecord, reserved.command_id)
            if (
                intent is None
                or intent.owner_operator_id != owner
                or intent.request_sha256 != kakao_command_sha256(command)
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
            if intent.state != "COMPLETED":
                self._parent(session, owner, command)

    def save_packet(
        self, actor: ActorContext, command: KakaoPacketCommand, *, idempotency_key: str
    ) -> KakaoPacketMutation:
        command = _COMMAND.validate_python(command.model_dump(mode="json"))
        key = validate_kakao_idempotency_key(idempotency_key)
        reserved = self._reserve(actor, command, key)
        if reserved.completed:
            stored = self.get_packet(
                actor,
                command.source_binding_id,
                reserved.packet_id,
                revision_id=reserved.revision_id,
            ).stored
            return KakaoPacketMutation(packet=stored, replayed=True)
        selection = self._questions.resolve_questions(
            actor, command.source_binding_id, command.questions
        )
        packet = build_question_packet(
            tuple(item.published for item in selection.questions),
            packet_id=reserved.packet_id,
            packet_revision_id=reserved.revision_id,
            previous_revision_id=command.parent_revision_id
            if isinstance(command, KakaoPacketRevise)
            else None,
            start_date=command.display_start_date,
            end_date_inclusive=command.display_end_date_inclusive,
            mode=command.mode,
            include_replies=command.include_replies,
            actor_id=cast(str, actor.operator_id),
            created_at=reserved.at,
        )
        publication = publish_kakao_packet(
            self._artifacts,
            packet=packet,
            questions=tuple(item.published for item in selection.questions),
            authorize=lambda: self._check(actor, command, reserved, selection),
        )
        return self._adopt(actor, command, key, reserved, publication, selection)

    def _adopt(
        self,
        actor: ActorContext,
        command: KakaoPacketCommand,
        key: str,
        reserved: _Reservation,
        publication: KakaoPacketPublication,
        selection: ResolvedKakaoQuestions,
    ) -> KakaoPacketMutation:
        packet, pointer = publication.packet, publication.pointer
        with self._sessions.begin() as session:
            owner = authorize_kakao_actor(
                session, actor, PermissionKey.KAKAO_ARCHIVE_EXPORT, now=datetime.now(UTC)
            )
            lock_kakao_intent(session, owner, _scope(command), key)
            authorize_kakao_binding_scope(
                session,
                actor,
                command.source_binding_id,
                PermissionKey.KAKAO_ARCHIVE_EXPORT,
                lock=True,
            )
            self._sources.validate_question_source_metadata(session, actor, selection.sources)
            intent = session.get(KakaoPacketCommandRecord, reserved.command_id)
            if (
                intent is None
                or intent.owner_operator_id != owner
                or intent.request_sha256 != kakao_command_sha256(command)
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
            self._manifest_metadata(session, pointer, publication.publication_job_id)
            validate_source_pointer_metadata_batch(
                session, tuple(item.stored.manifest for item in selection.questions)
            )
            if intent.state == "COMPLETED":
                row = session.get(KakaoPacketRevisionRecord, reserved.revision_id)
                if row is None or _view(row).manifest != pointer:
                    raise KakaoArchiveError("KAKAO_ARCHIVE_STORED_PACKET_INVALID")
                return KakaoPacketMutation(packet=_view(row), replayed=True)
            head = self._parent(session, owner, command)
            version = 1 if head is None else head.resource_version + 1
            if head is None:
                head = KakaoPacketRecord(
                    packet_id=reserved.packet_id,
                    owner_operator_id=owner,
                    source_binding_id=command.source_binding_id,
                    current_revision_id=reserved.revision_id,
                    resource_version=version,
                )
                session.add(head)
                session.flush()
            else:
                head.current_revision_id, head.resource_version = reserved.revision_id, version
            row = KakaoPacketRevisionRecord(
                packet_revision_id=reserved.revision_id,
                packet_id=reserved.packet_id,
                owner_operator_id=owner,
                source_binding_id=command.source_binding_id,
                command_id=reserved.command_id,
                previous_revision_id=packet.previous_revision_id,
                resource_version=version,
                title=command.title,
                mode=packet.mode,
                include_replies=packet.include_replies,
                display_start_date=packet.display_start_date,
                display_end_date_inclusive=packet.display_end_date_inclusive,
                question_count=len(packet.questions),
                student_count=len({q.student.student_id for q in packet.questions}),
                manifest_artifact_id=pointer.artifact_id,
                manifest_artifact_revision_id=pointer.artifact_revision_id,
                manifest_sha256=pointer.sha256,
                publication_job_id=publication.publication_job_id,
                created_at=reserved.at,
            )
            session.add(row)
            intent.state, intent.completed_at = "COMPLETED", datetime.now(UTC)
            session.flush()
            return KakaoPacketMutation(packet=_view(row), replayed=False)

    @staticmethod
    def _manifest_metadata(session: Session, pointer: ArtifactMemberPointer, job_id: str) -> None:
        values = validate_source_pointer_metadata_batch(session, (pointer,))
        logical, revision = values[(pointer.artifact_id, pointer.artifact_revision_id)]
        if (
            logical.artifact_type != "kakao-question-packet"
            or revision.job_id != job_id
            or revision.content_hash != pointer.sha256
            or revision.manifest.get("primary_file") != "packet.json"
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_EVIDENCE_INVALID")

    def get_packet(
        self,
        actor: ActorContext,
        binding_id: str,
        packet_id: str,
        *,
        revision_id: str,
        student_id: str | None = None,
    ) -> AcceptedKakaoPacket:
        with self._sessions.begin() as session:
            owner, _ = authorize_kakao_binding_scope(
                session, actor, binding_id, PermissionKey.KAKAO_ARCHIVE_READ, lock=False
            )
            row = session.scalar(
                select(KakaoPacketRevisionRecord).where(
                    KakaoPacketRevisionRecord.packet_id == packet_id,
                    KakaoPacketRevisionRecord.packet_revision_id == revision_id,
                    KakaoPacketRevisionRecord.source_binding_id == binding_id,
                    KakaoPacketRevisionRecord.owner_operator_id == owner,
                )
            )
            if row is None:
                raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
            stored, job_id = _view(row), row.publication_job_id
            self._manifest_metadata(session, stored.manifest, job_id)
        p = stored.manifest
        try:
            raw = self._artifacts.read_member(
                artifact_id=p.artifact_id,
                revision_id=p.artifact_revision_id,
                member_path=p.member_path,
                sha256=p.sha256,
                schema_ref=p.schema_ref,
                media_type=p.media_type,
                max_bytes=MAX_MANIFEST_BYTES,
            )
            if len(raw) > MAX_MANIFEST_BYTES or sha256_bytes(raw) != p.sha256:
                raise ValueError("packet hash mismatch")
            packet = KakaoQuestionPacket.model_validate_json(raw)
            # Reuse the immutable descriptor validator to compare all canonical projections.
            if (
                packet.packet_id,
                packet.packet_revision_id,
                packet.previous_revision_id,
                packet.source_binding_id,
                packet.mode,
                packet.include_replies,
                packet.display_start_date,
                packet.display_end_date_inclusive,
                len(packet.questions),
                len({q.student.student_id for q in packet.questions}),
                packet.created_at,
                packet.created_by,
            ) != (
                stored.packet_id,
                stored.packet_revision_id,
                stored.previous_revision_id,
                binding_id,
                stored.mode,
                stored.include_replies,
                stored.display_start_date,
                stored.display_end_date_inclusive,
                stored.question_count,
                stored.student_count,
                stored.created_at,
                actor.operator_id,
            ):
                raise ValueError("packet projection mismatch")
        except (ValueError, OSError):
            raise KakaoArchiveError("KAKAO_ARCHIVE_STORED_PACKET_INVALID") from None
        try:
            selected = (
                packet.questions
                if student_id is None
                else packet_student_subset(packet, student_id).questions
            )
        except ValueError:
            raise KakaoArchiveError("KAKAO_ARCHIVE_STUDENT_NOT_IN_PACKET") from None
        with self._sessions.begin() as session:
            authorize_kakao_room_scopes(
                session,
                actor,
                binding_id,
                tuple({q.room_id for q in selected}),
                PermissionKey.KAKAO_ARCHIVE_READ,
            )
            self._manifest_metadata(session, p, job_id)
            validate_source_pointer_metadata_batch(session, tuple(q.manifest for q in selected))
        return AcceptedKakaoPacket(stored, packet)

    def resolve_student(
        self,
        actor: ActorContext,
        binding_id: str,
        packet_id: str,
        *,
        revision_id: str,
        student_id: str,
    ) -> tuple[AcceptedKakaoPacket, ResolvedKakaoQuestions]:
        accepted = self.get_packet(
            actor, binding_id, packet_id, revision_id=revision_id, student_id=student_id
        )
        subset = packet_student_subset(accepted.packet, student_id)
        selected = self._questions.resolve_questions(
            actor,
            binding_id,
            tuple(
                KakaoQuestionProvenance(
                    question_id=q.question_id, question_revision_id=q.question_revision_id
                )
                for q in subset.questions
            ),
        )
        for entry, resolved in zip(subset.questions, selected.questions, strict=True):
            if (entry.manifest, entry.student, entry.room_id) != (
                resolved.stored.manifest,
                resolved.stored.student,
                resolved.stored.room_id,
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_STORED_PACKET_INVALID")
        with self._sessions.begin() as session:
            authorize_kakao_binding_scope(
                session, actor, binding_id, PermissionKey.KAKAO_ARCHIVE_READ, lock=False
            )
            self._sources.validate_question_source_metadata(session, actor, selected.sources)
            validate_source_pointer_metadata_batch(session, (accepted.stored.manifest,))
        return accepted, selected

    def list_packets(
        self, actor: ActorContext, binding_id: str, *, limit: int = 50, cursor: str | None = None
    ) -> KakaoPacketPage:
        if (
            type(limit) is not int
            or not 1 <= limit <= 100
            or (cursor is not None and re.fullmatch(r"kakaopacket_[0-9a-f]{32}", cursor) is None)
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_REQUEST_INVALID")
        with self._sessions.begin() as session:
            owner, _ = authorize_kakao_binding_scope(
                session, actor, binding_id, PermissionKey.KAKAO_ARCHIVE_READ, lock=False
            )
            statement = (
                select(KakaoPacketRevisionRecord)
                .join(
                    KakaoPacketRecord,
                    KakaoPacketRecord.current_revision_id
                    == KakaoPacketRevisionRecord.packet_revision_id,
                )
                .where(
                    KakaoPacketRevisionRecord.owner_operator_id == owner,
                    KakaoPacketRevisionRecord.source_binding_id == binding_id,
                )
            )
            if cursor is not None:
                statement = statement.where(KakaoPacketRevisionRecord.packet_id > cursor)
            rows = session.scalars(
                statement.order_by(KakaoPacketRevisionRecord.packet_id).limit(limit + 1)
            ).all()
            items = tuple(_view(row) for row in rows[:limit])
            validate_source_pointer_metadata_batch(session, tuple(item.manifest for item in items))
            return KakaoPacketPage(
                items=items, next_cursor=items[-1].packet_id if len(rows) > limit else None
            )
