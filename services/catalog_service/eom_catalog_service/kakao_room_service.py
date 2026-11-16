"""Catalog-owned room admission and immutable student mapping; no browser or NAS I/O."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from eom_catalog_contracts.kakao_rooms import (
    ROOM_OBSERVATION_REF,
    KakaoRoom,
    KakaoRoomCommand,
    KakaoRoomMap,
    KakaoRoomMapping,
    KakaoRoomMutation,
    KakaoRoomObservation,
    KakaoRoomPage,
    KakaoRoomUnmap,
    MappingState,
    room_mapping_sha256,
)
from eom_catalog_contracts.kakao_students import student_display_sha256
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_operator_identity.contracts import ActorContext, PermissionKey
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import Engine, and_, select
from sqlalchemy.orm import Session

from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError, authorize_kakao_actor
from eom_catalog_service.kakao_archive_commands import (
    kakao_command_sha256,
    lock_kakao_intent,
    validate_kakao_idempotency_key,
)
from eom_catalog_service.kakao_archive_models import KakaoChannelBindingRecord
from eom_catalog_service.kakao_room_models import (
    KakaoRoomAdmissionRecord,
    KakaoRoomMappingRevisionRecord,
    KakaoRoomRecord,
)
from eom_catalog_service.kakao_student_models import (
    KakaoStudentDisplayRevisionRecord,
    KakaoStudentRecord,
)

RoomObservationAuthorizer = Callable[
    [Session, ActorContext, KakaoRoomObservation, ArtifactMemberPointer], None
]
_INITIAL_REASON = "원본 대화방 확인 · 학생 연결 전"


def _identity(value: str, prefix: str) -> str:
    if not isinstance(value, str) or re.fullmatch(prefix + r"_[0-9a-f]{32}", value) is None:
        raise KakaoArchiveError("KAKAO_ARCHIVE_REQUEST_INVALID")
    return value


def _view(
    room: KakaoRoomRecord,
    mapping: KakaoRoomMappingRevisionRecord,
    display: KakaoStudentDisplayRevisionRecord | None,
) -> KakaoRoom:
    try:
        if (room.room_id, room.source_binding_id, room.owner_operator_id) != (
            mapping.room_id,
            mapping.source_binding_id,
            mapping.owner_operator_id,
        ) or (
            room.current_mapping_revision_id == mapping.mapping_revision_id
            and room.resource_version != mapping.revision_number
        ):
            raise ValueError("stored mapping identity mismatch")
        if mapping.student_id is not None and (
            display is None
            or display.student_id != mapping.student_id
            or display.display_revision_id != mapping.student_display_revision_id
            or display.state != "ACTIVE"
            or display.sha256 != student_display_sha256(display.display_name, "ACTIVE")
        ):
            raise ValueError("stored student display mismatch")
        value = KakaoRoomMapping(
            mapping_revision_id=mapping.mapping_revision_id,
            previous_revision_id=mapping.previous_revision_id,
            resource_version=mapping.revision_number,
            state=cast(MappingState, mapping.state),
            student_id=mapping.student_id,
            student_display_revision_id=mapping.student_display_revision_id,
            student_display_name=display.display_name if display is not None else None,
            reason=mapping.reason,
            sha256=mapping.sha256,
            created_at=mapping.created_at,
        )
        return KakaoRoom.model_validate(
            dict(
                source_binding_id=room.source_binding_id,
                room_id=room.room_id,
                display_name=room.display_name,
                state=room.state,
                identity_level=room.identity_level,
                resource_version=mapping.revision_number,
                created_at=room.created_at,
                last_observed_at=room.last_observed_at,
                mapping=value,
            )
        )
    except ValueError:
        raise KakaoArchiveError("KAKAO_ARCHIVE_STORED_ROOM_INVALID") from None


class KakaoRoomService:
    def __init__(self, engine: Engine) -> None:
        self._sessions = build_session_factory(engine)

    @staticmethod
    def _authorize(session: Session, actor: ActorContext, permission: PermissionKey) -> str:
        return authorize_kakao_actor(
            session,
            actor,
            permission,
            now=datetime.now(UTC),
            admin_only=permission == PermissionKey.KAKAO_ARCHIVE_COLLECT,
        )

    @staticmethod
    def _binding(
        session: Session, owner: str, binding_id: str, *, mutate: bool
    ) -> KakaoChannelBindingRecord:
        statement = select(KakaoChannelBindingRecord).where(
            KakaoChannelBindingRecord.source_binding_id == binding_id,
            KakaoChannelBindingRecord.owner_operator_id == owner,
        )
        if mutate:
            statement = statement.with_for_update(read=True)
        row = session.scalar(statement.execution_options(populate_existing=True))
        if row is None:
            raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
        if mutate and row.state == "RETIRED":
            raise KakaoArchiveError("KAKAO_ARCHIVE_BINDING_RETIRED")
        return row

    @staticmethod
    def _room(
        session: Session, owner: str, binding_id: str, room_id: str, *, lock: bool = False
    ) -> KakaoRoomRecord:
        statement = select(KakaoRoomRecord).where(
            KakaoRoomRecord.owner_operator_id == owner,
            KakaoRoomRecord.source_binding_id == binding_id,
            KakaoRoomRecord.room_id == room_id,
        )
        if lock:
            statement = statement.with_for_update()
        row = session.scalar(statement.execution_options(populate_existing=True))
        if row is None:
            raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
        return row

    @staticmethod
    def _mapped_view(session: Session, room: KakaoRoomRecord, revision_id: str) -> KakaoRoom:
        row = session.execute(
            select(KakaoRoomMappingRevisionRecord, KakaoStudentDisplayRevisionRecord)
            .outerjoin(
                KakaoStudentDisplayRevisionRecord,
                and_(
                    KakaoStudentDisplayRevisionRecord.student_id
                    == KakaoRoomMappingRevisionRecord.student_id,
                    KakaoStudentDisplayRevisionRecord.display_revision_id
                    == KakaoRoomMappingRevisionRecord.student_display_revision_id,
                ),
            )
            .where(
                KakaoRoomMappingRevisionRecord.room_id == room.room_id,
                KakaoRoomMappingRevisionRecord.mapping_revision_id == revision_id,
            )
        ).one_or_none()
        if row is None:
            raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
        return _view(room, row[0], row[1])

    @staticmethod
    def _evidence_metadata(
        session: Session, evidence: ArtifactMemberPointer
    ) -> tuple[ArtifactRecord, ArtifactRevisionRecord]:
        # Bytes were resolved by the mandatory owner adapter before this short transaction.
        # Re-check current lifecycle/manifest here, including on idempotent replay.
        row = session.execute(
            select(ArtifactRecord, ArtifactRevisionRecord, JobRecord.status)
            .join(
                ArtifactRevisionRecord,
                ArtifactRevisionRecord.logical_artifact_id == ArtifactRecord.logical_artifact_id,
            )
            .join(JobRecord, JobRecord.job_id == ArtifactRevisionRecord.job_id)
            .where(
                ArtifactRecord.logical_artifact_id == evidence.artifact_id,
                ArtifactRevisionRecord.revision_id == evidence.artifact_revision_id,
            )
        ).one_or_none()
        if row is None:
            raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_EVIDENCE_INVALID")
        logical, revision, status = row
        manifest = revision.manifest
        if not isinstance(manifest, dict):
            raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_EVIDENCE_INVALID")
        files = manifest.get("files")
        matching = (
            [
                entry
                for entry in files
                if isinstance(entry, dict) and entry.get("file_name") == evidence.member_path
            ]
            if isinstance(files, list)
            else []
        )
        if (
            not logical.approved
            or not revision.approved
            or status != "SUCCEEDED"
            or logical.job_id != revision.job_id
            or revision.manifest_hash != sha256_bytes(canonical_json_bytes(manifest))
            or manifest.get("job_id") != revision.job_id
            or manifest.get("logical_artifact_id") != evidence.artifact_id
            or manifest.get("revision_id") != evidence.artifact_revision_id
            or manifest.get("artifact_type") != logical.artifact_type
            or manifest.get("content_hash") != revision.content_hash
            or manifest.get("content_bytes") != revision.content_bytes
            or len(matching) != 1
            or matching[0].get("sha256") != evidence.sha256
            or matching[0].get("schema_ref") != evidence.schema_ref
            or matching[0].get("media_type") != evidence.media_type
            or type(matching[0].get("bytes")) is not int
            or matching[0]["bytes"] < 0
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_EVIDENCE_INVALID")
        return logical, revision

    @classmethod
    def _observation_metadata(
        cls, session: Session, observation: KakaoRoomObservation, evidence: ArtifactMemberPointer
    ) -> None:
        raw = canonical_json_bytes(observation.model_dump(mode="json"))
        if (
            evidence.schema_ref != ROOM_OBSERVATION_REF
            or evidence.media_type != "application/json"
            or evidence.member_path != "observation.json"
            or evidence.sha256 != sha256_bytes(raw)
            or observation.observed_at > datetime.now(UTC)
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_EVIDENCE_INVALID")
        cls._evidence_metadata(session, observation.source_evidence)
        logical, revision = cls._evidence_metadata(session, evidence)
        manifest = revision.manifest
        files = manifest["files"]
        if (
            logical.artifact_type != "kakao-room-identity"
            or revision.content_hash != evidence.sha256
            or revision.content_bytes != len(raw)
            or manifest.get("primary_file") != evidence.member_path
            or len(files) != 1
            or any(
                files[0].get(key) != expected
                for key, expected in {
                    "file_name": evidence.member_path,
                    "sha256": evidence.sha256,
                    "bytes": len(raw),
                    "schema_ref": evidence.schema_ref,
                    "media_type": evidence.media_type,
                }.items()
            )
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_EVIDENCE_INVALID")

    def admit_room(
        self,
        actor: ActorContext,
        observation: KakaoRoomObservation,
        *,
        evidence: ArtifactMemberPointer,
        idempotency_key: str,
        authorize_observation: RoomObservationAuthorizer,
    ) -> KakaoRoomMutation:
        """Internal only. Callback verifies already-read source bytes/current accepted authority.

        It is mandatory even on replay and must not do long I/O in this transaction.
        A public/worker-supplied callable or claimed ADMIN is never a supported input.
        """
        if not callable(authorize_observation):
            raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_AUTHORITY_REQUIRED")
        try:
            observation = KakaoRoomObservation.model_validate(observation.model_dump(mode="json"))
            evidence = ArtifactMemberPointer.model_validate(evidence.model_dump(mode="json"))
        except (AttributeError, ValueError):
            raise KakaoArchiveError("KAKAO_ARCHIVE_REQUEST_INVALID") from None
        key = validate_kakao_idempotency_key(idempotency_key)
        digest = sha256_bytes(
            canonical_json_bytes(
                {
                    "observation": observation.model_dump(mode="json"),
                    "evidence": evidence.model_dump(mode="json"),
                }
            )
        )
        with self._sessions.begin() as session:
            owner = self._authorize(session, actor, PermissionKey.KAKAO_ARCHIVE_COLLECT)
            scope = "room-admission/" + observation.source_binding_id
            lock_kakao_intent(session, owner, scope, key)
            self._binding(session, owner, observation.source_binding_id, mutate=True)
            self._authorize(session, actor, PermissionKey.KAKAO_ARCHIVE_COLLECT)
            try:
                authorize_observation(session, actor, observation, evidence)
            except KakaoArchiveError:
                raise
            except (PermissionError, ValueError):
                raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_AUTHORITY_REQUIRED") from None
            self._observation_metadata(session, observation, evidence)
            prior = session.scalar(
                select(KakaoRoomAdmissionRecord).where(
                    KakaoRoomAdmissionRecord.owner_operator_id == owner,
                    KakaoRoomAdmissionRecord.source_binding_id == observation.source_binding_id,
                    KakaoRoomAdmissionRecord.idempotency_key == key,
                )
            )
            if prior is not None:
                if prior.request_sha256 != digest:
                    raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
                prior_room = self._room(
                    session, owner, observation.source_binding_id, prior.room_id
                )
                return KakaoRoomMutation(
                    room=self._mapped_view(session, prior_room, prior.result_mapping_revision_id),
                    replayed=True,
                )
            lock_kakao_intent(
                session,
                owner,
                "room-identity/" + observation.source_binding_id,
                observation.identity_level + ":" + observation.source_identity_sha256,
            )
            room = session.scalar(
                select(KakaoRoomRecord)
                .where(
                    KakaoRoomRecord.owner_operator_id == owner,
                    KakaoRoomRecord.source_binding_id == observation.source_binding_id,
                    KakaoRoomRecord.identity_level == observation.identity_level,
                    KakaoRoomRecord.source_identity_sha256 == observation.source_identity_sha256,
                )
                .with_for_update(read=True)
            )
            now = datetime.now(UTC)
            if room is None:
                room = KakaoRoomRecord(
                    room_id="kakaoroom_" + uuid4().hex,
                    owner_operator_id=owner,
                    source_binding_id=observation.source_binding_id,
                    identity_level=observation.identity_level,
                    source_identity_sha256=observation.source_identity_sha256,
                    display_name=observation.display_name,
                    state="ACTIVE",
                    resource_version=1,
                    current_mapping_revision_id="kakaomappingrev_" + uuid4().hex,
                    evidence_artifact_id=evidence.artifact_id,
                    evidence_artifact_revision_id=evidence.artifact_revision_id,
                    evidence_sha256=evidence.sha256,
                    created_at=now,
                    last_observed_at=observation.observed_at,
                )
                session.add(room)
                session.flush([room])
                initial = KakaoRoomMappingRevisionRecord(
                    mapping_revision_id=room.current_mapping_revision_id,
                    room_id=room.room_id,
                    owner_operator_id=owner,
                    source_binding_id=room.source_binding_id,
                    previous_revision_id=None,
                    revision_number=1,
                    state="UNMAPPED",
                    student_id=None,
                    student_display_revision_id=None,
                    reason=_INITIAL_REASON,
                    sha256=room_mapping_sha256(
                        student_id=None, student_display_revision_id=None, reason=_INITIAL_REASON
                    ),
                    idempotency_key=None,
                    request_sha256=None,
                    created_by=owner,
                    created_at=now,
                )
                session.add(initial)
                session.flush([initial])
            if room.state != "ACTIVE":
                raise KakaoArchiveError("KAKAO_ARCHIVE_ROOM_RETIRED")
            session.add(
                KakaoRoomAdmissionRecord(
                    command_id="kakaocommand_" + uuid4().hex,
                    owner_operator_id=owner,
                    source_binding_id=room.source_binding_id,
                    room_id=room.room_id,
                    idempotency_key=key,
                    request_sha256=digest,
                    evidence_artifact_id=evidence.artifact_id,
                    evidence_artifact_revision_id=evidence.artifact_revision_id,
                    evidence_sha256=evidence.sha256,
                    result_mapping_revision_id=room.current_mapping_revision_id,
                    completed_at=now,
                )
            )
            return KakaoRoomMutation(
                room=self._mapped_view(session, room, room.current_mapping_revision_id),
                replayed=False,
            )

    def command_room(
        self,
        actor: ActorContext,
        source_binding_id: str,
        room_id: str,
        command: KakaoRoomCommand,
        *,
        idempotency_key: str,
    ) -> KakaoRoomMutation:
        _identity(source_binding_id, "kakaobinding")
        _identity(room_id, "kakaoroom")
        try:
            if isinstance(command, KakaoRoomMap):
                command = KakaoRoomMap.model_validate(command.model_dump(mode="json"))
            elif isinstance(command, KakaoRoomUnmap):
                command = KakaoRoomUnmap.model_validate(command.model_dump(mode="json"))
            else:
                raise ValueError("unsupported command")
        except ValueError:
            raise KakaoArchiveError("KAKAO_ARCHIVE_REQUEST_INVALID") from None
        key, digest = validate_kakao_idempotency_key(idempotency_key), kakao_command_sha256(command)
        with self._sessions.begin() as session:
            owner = self._authorize(session, actor, PermissionKey.KAKAO_ARCHIVE_EDIT)
            lock_kakao_intent(session, owner, "room-mapping/" + room_id, key)
            self._binding(session, owner, source_binding_id, mutate=True)
            room = self._room(session, owner, source_binding_id, room_id, lock=True)
            self._authorize(session, actor, PermissionKey.KAKAO_ARCHIVE_EDIT)
            replay = session.scalar(
                select(KakaoRoomMappingRevisionRecord).where(
                    KakaoRoomMappingRevisionRecord.owner_operator_id == owner,
                    KakaoRoomMappingRevisionRecord.room_id == room_id,
                    KakaoRoomMappingRevisionRecord.idempotency_key == key,
                )
            )
            if replay is not None:
                if replay.request_sha256 != digest:
                    raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
                return KakaoRoomMutation(
                    room=self._mapped_view(session, room, replay.mapping_revision_id), replayed=True
                )
            if room.state != "ACTIVE":
                raise KakaoArchiveError("KAKAO_ARCHIVE_ROOM_RETIRED")
            if (
                command.parent_revision_id != room.current_mapping_revision_id
                or command.expected_resource_version != room.resource_version
                or room.resource_version == 2147483647
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
            self._mapped_view(session, room, room.current_mapping_revision_id)
            student_id = display_id = None
            if isinstance(command, KakaoRoomMap):
                student = session.scalar(
                    select(KakaoStudentRecord)
                    .where(
                        KakaoStudentRecord.student_id == command.student_id,
                        KakaoStudentRecord.owner_operator_id == owner,
                    )
                    .with_for_update(read=True)
                    .execution_options(populate_existing=True)
                )
                if student is None:
                    raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
                if student.state != "ACTIVE":
                    raise KakaoArchiveError("KAKAO_ARCHIVE_STUDENT_RETIRED")
                if student.current_display_revision_id != command.student_display_revision_id:
                    raise KakaoArchiveError("KAKAO_ARCHIVE_STUDENT_STALE")
                display = session.get(
                    KakaoStudentDisplayRevisionRecord, command.student_display_revision_id
                )
                if (
                    display is None
                    or display.student_id != student.student_id
                    or display.state != "ACTIVE"
                    or display.revision_number != student.resource_version
                    or display.sha256 != student_display_sha256(display.display_name, "ACTIVE")
                ):
                    raise KakaoArchiveError("KAKAO_ARCHIVE_STORED_STUDENT_INVALID")
                student_id, display_id = student.student_id, display.display_revision_id
            revision = KakaoRoomMappingRevisionRecord(
                mapping_revision_id="kakaomappingrev_" + uuid4().hex,
                room_id=room_id,
                owner_operator_id=owner,
                source_binding_id=source_binding_id,
                previous_revision_id=room.current_mapping_revision_id,
                revision_number=room.resource_version + 1,
                state="MAPPED" if student_id else "UNMAPPED",
                student_id=student_id,
                student_display_revision_id=display_id,
                reason=command.reason,
                sha256=room_mapping_sha256(
                    student_id=student_id,
                    student_display_revision_id=display_id,
                    reason=command.reason,
                ),
                idempotency_key=key,
                request_sha256=digest,
                created_by=owner,
                created_at=datetime.now(UTC),
            )
            session.add(revision)
            session.flush([revision])
            room.current_mapping_revision_id = revision.mapping_revision_id
            room.resource_version = revision.revision_number
            return KakaoRoomMutation(
                room=self._mapped_view(session, room, revision.mapping_revision_id), replayed=False
            )

    def get_room(
        self,
        actor: ActorContext,
        source_binding_id: str,
        room_id: str,
        *,
        mapping_revision_id: str | None = None,
    ) -> KakaoRoom:
        _identity(source_binding_id, "kakaobinding")
        _identity(room_id, "kakaoroom")
        if mapping_revision_id is not None:
            _identity(mapping_revision_id, "kakaomappingrev")
        with self._sessions.begin() as session:
            owner = self._authorize(session, actor, PermissionKey.KAKAO_ARCHIVE_READ)
            self._binding(session, owner, source_binding_id, mutate=False)
            room = self._room(session, owner, source_binding_id, room_id)
            return self._mapped_view(
                session, room, mapping_revision_id or room.current_mapping_revision_id
            )

    def list_rooms(
        self,
        actor: ActorContext,
        source_binding_id: str,
        *,
        limit: int = 50,
        cursor: str | None = None,
    ) -> KakaoRoomPage:
        _identity(source_binding_id, "kakaobinding")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise KakaoArchiveError("KAKAO_ARCHIVE_REQUEST_INVALID")
        if cursor is not None:
            _identity(cursor, "kakaoroom")
        with self._sessions.begin() as session:
            owner = self._authorize(session, actor, PermissionKey.KAKAO_ARCHIVE_READ)
            self._binding(session, owner, source_binding_id, mutate=False)
            statement = (
                select(
                    KakaoRoomRecord,
                    KakaoRoomMappingRevisionRecord,
                    KakaoStudentDisplayRevisionRecord,
                )
                .join(
                    KakaoRoomMappingRevisionRecord,
                    and_(
                        KakaoRoomMappingRevisionRecord.room_id == KakaoRoomRecord.room_id,
                        KakaoRoomMappingRevisionRecord.mapping_revision_id
                        == KakaoRoomRecord.current_mapping_revision_id,
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
                .where(
                    KakaoRoomRecord.owner_operator_id == owner,
                    KakaoRoomRecord.source_binding_id == source_binding_id,
                )
            )
            if cursor is not None:
                statement = statement.where(KakaoRoomRecord.room_id > cursor)
            rows = session.execute(
                statement.order_by(KakaoRoomRecord.room_id).limit(limit + 1)
            ).all()
            items = tuple(_view(row[0], row[1], row[2]) for row in rows[:limit])
            return KakaoRoomPage(
                items=items, next_cursor=items[-1].room_id if len(rows) > limit else None
            )
