"""Save exact student study selections with immutable manifests and short revision CAS."""

import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

from eom_catalog_contracts.kakao_study_store import (
    MAX_STUDY_BYTES,
    STUDY_REF,
    KakaoStoredStudy,
    KakaoStudyCommand,
    KakaoStudyManifest,
    KakaoStudyMutation,
    KakaoStudyPage,
    KakaoStudyQuestion,
    KakaoStudyQuestionEdit,
    KakaoStudyRevise,
    StudyId,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_operator_identity import ActorContext, PermissionKey
from eom_orchestrator.database import build_session_factory
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import TypeAdapter
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from .artifacts import CatalogArtifactService
from .kakao_archive_authorization import KakaoArchiveError, authorize_kakao_binding_scope
from .kakao_archive_commands import (
    kakao_command_sha256,
    lock_kakao_intent,
    validate_kakao_idempotency_key,
)
from .kakao_concept_task_service import KakaoConceptTaskService
from .kakao_packet_service import AcceptedKakaoPacket, KakaoPacketService
from .kakao_question_editing import packet_student_subset
from .kakao_question_service import ResolvedKakaoQuestions
from .kakao_source_pointers import validate_source_pointer_metadata_batch
from .kakao_source_service import KakaoSourceService
from .kakao_study_models import (
    KakaoStudyCommandRecord,
    KakaoStudyRecord,
    KakaoStudyRevisionRecord,
)

_COMMAND: TypeAdapter[KakaoStudyCommand] = TypeAdapter(KakaoStudyCommand)
_STUDY_ID: TypeAdapter[str] = TypeAdapter(StudyId)


@dataclass(frozen=True, slots=True)
class AcceptedKakaoStudy:
    stored: KakaoStoredStudy
    manifest: KakaoStudyManifest
    packet: AcceptedKakaoPacket
    selected: ResolvedKakaoQuestions


@dataclass(frozen=True, slots=True)
class _Reservation:
    command_id: str
    study_id: str
    revision_id: str
    at: datetime
    completed: bool


def _view(head: KakaoStudyRecord, revision: KakaoStudyRevisionRecord) -> KakaoStoredStudy:
    return KakaoStoredStudy(
        study_id=head.study_id,
        study_revision_id=revision.study_revision_id,
        previous_revision_id=revision.previous_revision_id,
        resource_version=revision.resource_version,
        source_binding_id=head.source_binding_id,
        packet_id=head.packet_id,
        packet_revision_id=head.packet_revision_id,
        student_id=head.student_id,
        title=revision.title,
        question_count=revision.question_count,
        created_at=revision.created_at,
        manifest=ArtifactMemberPointer(
            artifact_id=revision.manifest_artifact_id,
            artifact_revision_id=revision.manifest_artifact_revision_id,
            member_path="study.json",
            schema_ref=STUDY_REF,
            media_type="application/json",
            sha256=revision.manifest_sha256,
        ),
    )


def _manifest_metadata(session: Session, pointer: ArtifactMemberPointer) -> None:
    values = validate_source_pointer_metadata_batch(session, (pointer,))
    logical, revision = values[pointer.artifact_id, pointer.artifact_revision_id]
    if (
        logical.artifact_type != "kakao-study-manifest"
        or revision.content_hash != pointer.sha256
        or revision.manifest.get("primary_file") != "study.json"
    ):
        raise KakaoArchiveError("KAKAO_STUDY_MANIFEST_INVALID")


class KakaoStudyService:
    def __init__(
        self,
        engine: Engine,
        *,
        artifacts: CatalogArtifactService,
        packets: KakaoPacketService,
        sources: KakaoSourceService,
        concepts: KakaoConceptTaskService | None = None,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.artifacts, self.packets, self.sources, self.concepts = (
            artifacts,
            packets,
            sources,
            concepts,
        )

    @staticmethod
    def _parent(
        session: Session, owner: str, command: KakaoStudyCommand
    ) -> KakaoStudyRecord | None:
        if not isinstance(command, KakaoStudyRevise):
            return None
        head = session.scalar(
            select(KakaoStudyRecord)
            .where(
                KakaoStudyRecord.study_id == command.study_id,
                KakaoStudyRecord.owner_operator_id == owner,
                KakaoStudyRecord.source_binding_id == command.source_binding_id,
            )
            .with_for_update()
        )
        if head is None:
            raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
        if (head.packet_id, head.packet_revision_id, head.student_id) != (
            command.packet_id,
            command.packet_revision_id,
            command.student_id,
        ):
            raise KakaoArchiveError("KAKAO_STUDY_PACKET_CHANGED")
        if (head.current_revision_id, head.resource_version) != (
            command.parent_revision_id,
            command.expected_resource_version,
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
        return head

    def _reserve(self, actor: ActorContext, command: KakaoStudyCommand, key: str) -> _Reservation:
        with self.sessions.begin() as session:
            owner, _ = authorize_kakao_binding_scope(
                session,
                actor,
                command.source_binding_id,
                PermissionKey.KAKAO_ARCHIVE_EDIT,
                lock=False,
            )
            lock_kakao_intent(session, owner, "study", key)
            old = session.scalar(
                select(KakaoStudyCommandRecord).where(
                    KakaoStudyCommandRecord.owner_operator_id == owner,
                    KakaoStudyCommandRecord.idempotency_key == key,
                )
            )
            if old is not None:
                if old.request_sha256 != kakao_command_sha256(command):
                    raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
                return _Reservation(
                    old.command_id,
                    old.study_id,
                    old.study_revision_id,
                    old.reserved_at,
                    old.state == "COMPLETED",
                )
            self._parent(session, owner, command)
            reserved = _Reservation(
                "kakaocommand_" + uuid4().hex,
                command.study_id
                if isinstance(command, KakaoStudyRevise)
                else "kakaostudy_" + uuid4().hex,
                "kakaostudyrev_" + uuid4().hex,
                datetime.now(UTC),
                False,
            )
            session.add(
                KakaoStudyCommandRecord(
                    command_id=reserved.command_id,
                    owner_operator_id=owner,
                    source_binding_id=command.source_binding_id,
                    idempotency_key=key,
                    request_sha256=kakao_command_sha256(command),
                    study_id=reserved.study_id,
                    study_revision_id=reserved.revision_id,
                    previous_revision_id=command.parent_revision_id
                    if isinstance(command, KakaoStudyRevise)
                    else None,
                    expected_version=command.expected_resource_version
                    if isinstance(command, KakaoStudyRevise)
                    else 0,
                    state="RESERVED",
                    reserved_at=reserved.at,
                    completed_at=None,
                )
            )
            return reserved

    def _resolve(
        self,
        actor: ActorContext,
        binding: str,
        packet_id: str,
        packet_revision: str,
        student_id: str,
        edits: tuple[KakaoStudyQuestionEdit, ...],
    ) -> tuple[AcceptedKakaoPacket, ResolvedKakaoQuestions, tuple[KakaoStudyQuestion, ...]]:
        packet, selected = self.packets.resolve_student(
            actor, binding, packet_id, revision_id=packet_revision, student_id=student_id
        )
        if tuple(q.question_revision_id for q in edits) != tuple(
            q.stored.question_revision_id for q in selected.questions
        ):
            raise KakaoArchiveError("KAKAO_STUDY_QUESTION_SET_MISMATCH")
        questions = []
        for edit, question in zip(edits, selected.questions, strict=True):
            if edit.concept_task_id is None:
                questions.append(KakaoStudyQuestion(edit=edit, result=None))
                continue
            if self.concepts is None:
                raise KakaoArchiveError("KAKAO_CONCEPT_RUNTIME_UNAVAILABLE")
            from eom_kakao_archive_contracts.concepts import ConceptComposition

            from .kakao_concept_phase_results import read_kakao_concept_phase_result

            authority = self.concepts.source_authority(actor, binding, edit.concept_task_id)
            completed = read_kakao_concept_phase_result(authority, "COMPOSE")
            if (
                completed.work.question_revision_id != edit.question_revision_id
                or completed.work.question_manifest != question.stored.manifest
                or not isinstance(completed.result.output.output, ConceptComposition)
            ):
                raise KakaoArchiveError("KAKAO_STUDY_CONCEPT_QUESTION_MISMATCH")
            composition = completed.result.output.output
            count = len(edit.blocks) + len(edit.notes) + 1 + bool(composition.staff_checks)
            if count > 8 or any(
                b.block_index >= len(composition.blocks)
                or (
                    b.capture_indices is not None
                    and any(
                        c >= len(composition.blocks[b.block_index].captures)
                        for c in b.capture_indices
                    )
                )
                for b in edit.blocks
            ):
                raise KakaoArchiveError("KAKAO_STUDY_BLOCK_SELECTION_INVALID")
            questions.append(KakaoStudyQuestion(edit=edit, result=completed.pin))
        return packet, selected, tuple(questions)

    def _check(
        self,
        actor: ActorContext,
        command: KakaoStudyCommand,
        reserved: _Reservation,
        packet: AcceptedKakaoPacket,
        selected: ResolvedKakaoQuestions,
    ) -> None:
        with self.sessions() as session:
            owner, _ = authorize_kakao_binding_scope(
                session,
                actor,
                command.source_binding_id,
                PermissionKey.KAKAO_ARCHIVE_EDIT,
                lock=False,
            )
            intent = session.get(KakaoStudyCommandRecord, reserved.command_id)
            if (
                intent is None
                or intent.owner_operator_id != owner
                or intent.request_sha256 != kakao_command_sha256(command)
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
            self.sources.validate_question_source_metadata(session, actor, selected.sources)
            validate_source_pointer_metadata_batch(
                session, (packet.stored.manifest, *(q.stored.manifest for q in selected.questions))
            )

    def save_study(
        self, actor: ActorContext, command: KakaoStudyCommand, *, idempotency_key: str
    ) -> KakaoStudyMutation:
        command = _COMMAND.validate_python(command.model_dump(mode="json"))
        reserved = self._reserve(actor, command, validate_kakao_idempotency_key(idempotency_key))
        if reserved.completed:
            return KakaoStudyMutation(
                study=self.get_study(
                    actor,
                    command.source_binding_id,
                    reserved.study_id,
                    revision_id=reserved.revision_id,
                ).stored,
                replayed=True,
            )
        packet, selected, questions = self._resolve(
            actor,
            command.source_binding_id,
            command.packet_id,
            command.packet_revision_id,
            command.student_id,
            command.questions,
        )
        manifest = KakaoStudyManifest(
            study_id=reserved.study_id,
            study_revision_id=reserved.revision_id,
            previous_revision_id=command.parent_revision_id
            if isinstance(command, KakaoStudyRevise)
            else None,
            resource_version=command.expected_resource_version + 1
            if isinstance(command, KakaoStudyRevise)
            else 1,
            source_binding_id=command.source_binding_id,
            packet_id=command.packet_id,
            packet_revision_id=command.packet_revision_id,
            student_id=command.student_id,
            title=command.title,
            packet_manifest=packet.stored.manifest,
            subset_sha256=packet_student_subset(packet.packet, command.student_id).subset_sha256,
            questions=questions,
            created_at=reserved.at,
            created_by=cast(str, actor.operator_id),
        )
        raw = canonical_json_bytes(manifest)
        digest = sha256_bytes(raw)
        with tempfile.TemporaryDirectory(
            prefix="kakao-study.", dir=self.artifacts.settings.staging_root
        ) as folder:
            path = Path(folder) / "study.json"
            path.write_bytes(raw)
            self._check(actor, command, reserved, packet, selected)
            artifact = self.artifacts.commit_file_set(
                files={"study.json": path},
                primary_file="study.json",
                artifact_type="kakao-study-manifest",
                idempotency_key=f"kakao:study:{reserved.study_id}:{reserved.revision_id}",
                request=dict(
                    study_id=reserved.study_id,
                    revision_id=reserved.revision_id,
                    manifest_sha256=digest,
                ),
                result=dict(manifest_sha256=digest, question_count=len(questions)),
                file_metadata={
                    "study.json": dict(schema_ref=STUDY_REF, media_type="application/json")
                },
                expected_file_sha256={"study.json": digest},
            )
        if artifact.content_hash != digest or artifact.content_bytes != len(raw):
            raise KakaoArchiveError("KAKAO_STUDY_PUBLICATION_MISMATCH")
        pointer = ArtifactMemberPointer(
            artifact_id=artifact.artifact_id,
            artifact_revision_id=artifact.revision_id,
            member_path="study.json",
            schema_ref=STUDY_REF,
            media_type="application/json",
            sha256=digest,
        )
        # Long resolution/publication has ended; only metadata and the parent CAS are locked below.
        self._check(actor, command, reserved, packet, selected)
        replayed = self._adopt(actor, command, reserved, manifest, pointer)
        saved = self.get_study(
            actor, command.source_binding_id, reserved.study_id, revision_id=reserved.revision_id
        )
        return KakaoStudyMutation(study=saved.stored, replayed=replayed)

    def _adopt(
        self,
        actor: ActorContext,
        command: KakaoStudyCommand,
        reserved: _Reservation,
        manifest: KakaoStudyManifest,
        pointer: ArtifactMemberPointer,
    ) -> bool:
        with self.sessions.begin() as session:
            owner, _ = authorize_kakao_binding_scope(
                session,
                actor,
                command.source_binding_id,
                PermissionKey.KAKAO_ARCHIVE_EDIT,
                lock=False,
            )
            intent = session.scalar(
                select(KakaoStudyCommandRecord)
                .where(KakaoStudyCommandRecord.command_id == reserved.command_id)
                .with_for_update()
            )
            if (
                intent is None
                or intent.owner_operator_id != owner
                or intent.request_sha256 != kakao_command_sha256(command)
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
            validate_source_pointer_metadata_batch(session, (pointer, manifest.packet_manifest))
            _manifest_metadata(session, pointer)
            if intent.state == "COMPLETED":
                old = session.get(KakaoStudyRevisionRecord, reserved.revision_id)
                if (
                    old is None
                    or old.manifest_sha256 != pointer.sha256
                    or (old.manifest_artifact_id, old.manifest_artifact_revision_id)
                    != (pointer.artifact_id, pointer.artifact_revision_id)
                ):
                    raise KakaoArchiveError("KAKAO_STUDY_MANIFEST_INVALID")
                return True
            head = self._parent(session, owner, command)
            if head is None:
                head = KakaoStudyRecord(
                    study_id=reserved.study_id,
                    owner_operator_id=owner,
                    source_binding_id=command.source_binding_id,
                    packet_id=command.packet_id,
                    packet_revision_id=command.packet_revision_id,
                    student_id=command.student_id,
                    current_revision_id=reserved.revision_id,
                    resource_version=1,
                )
                session.add(head)
                session.flush()
            else:
                head.current_revision_id, head.resource_version = (
                    reserved.revision_id,
                    manifest.resource_version,
                )
            session.add(
                KakaoStudyRevisionRecord(
                    study_revision_id=reserved.revision_id,
                    study_id=reserved.study_id,
                    owner_operator_id=owner,
                    source_binding_id=command.source_binding_id,
                    command_id=reserved.command_id,
                    previous_revision_id=manifest.previous_revision_id,
                    resource_version=manifest.resource_version,
                    title=manifest.title,
                    question_count=len(manifest.questions),
                    manifest_artifact_id=pointer.artifact_id,
                    manifest_artifact_revision_id=pointer.artifact_revision_id,
                    manifest_sha256=pointer.sha256,
                    created_at=reserved.at,
                )
            )
            intent.state, intent.completed_at = "COMPLETED", datetime.now(UTC)
            session.flush()
            return False

    def read_revision_metadata(
        self,
        session: Session,
        actor: ActorContext,
        binding: str,
        study_id: str,
        *,
        revision_id: str | None = None,
    ) -> KakaoStoredStudy:
        """Current private ownership and immutable publication metadata, without source byte I/O."""
        owner, _ = authorize_kakao_binding_scope(
            session, actor, binding, PermissionKey.KAKAO_ARCHIVE_READ, lock=False
        )
        head = session.get(KakaoStudyRecord, study_id)
        if head is None or (head.owner_operator_id, head.source_binding_id) != (owner, binding):
            raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
        revision = session.get(KakaoStudyRevisionRecord, revision_id or head.current_revision_id)
        if revision is None or (
            revision.study_id,
            revision.owner_operator_id,
            revision.source_binding_id,
        ) != (study_id, owner, binding):
            raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
        view = _view(head, revision)
        command = session.get(KakaoStudyCommandRecord, revision.command_id)
        if command is None or (
            command.state,
            command.study_id,
            command.study_revision_id,
            command.expected_version + 1,
            command.previous_revision_id,
        ) != (
            "COMPLETED",
            study_id,
            revision.study_revision_id,
            revision.resource_version,
            revision.previous_revision_id,
        ):
            raise KakaoArchiveError("KAKAO_STUDY_MANIFEST_INVALID")
        _manifest_metadata(session, view.manifest)
        return view

    def get_study(
        self, actor: ActorContext, binding: str, study_id: str, *, revision_id: str | None = None
    ) -> AcceptedKakaoStudy:
        with self.sessions() as session:
            view = self.read_revision_metadata(
                session, actor, binding, study_id, revision_id=revision_id
            )
            owner = cast(str, actor.operator_id)
        p = view.manifest
        raw = self.artifacts.read_member(
            artifact_id=p.artifact_id,
            revision_id=p.artifact_revision_id,
            member_path=p.member_path,
            schema_ref=p.schema_ref,
            media_type=p.media_type,
            sha256=p.sha256,
            max_bytes=MAX_STUDY_BYTES,
        )
        manifest = KakaoStudyManifest.model_validate_json(raw)
        if (
            canonical_json_bytes(manifest) != raw
            or manifest.created_by != owner
            or any(
                getattr(manifest, key) != getattr(view, key)
                for key in (
                    "study_id",
                    "study_revision_id",
                    "previous_revision_id",
                    "resource_version",
                    "source_binding_id",
                    "packet_id",
                    "packet_revision_id",
                    "student_id",
                    "title",
                    "created_at",
                )
            )
            or len(manifest.questions) != view.question_count
        ):
            raise KakaoArchiveError("KAKAO_STUDY_MANIFEST_INVALID")
        packet, selected, questions = self._resolve(
            actor,
            binding,
            view.packet_id,
            view.packet_revision_id,
            view.student_id,
            tuple(q.edit for q in manifest.questions),
        )
        if (
            questions != manifest.questions
            or packet.stored.manifest != manifest.packet_manifest
            or packet_student_subset(packet.packet, view.student_id).subset_sha256
            != manifest.subset_sha256
        ):
            raise KakaoArchiveError("KAKAO_STUDY_SOURCE_CHANGED")
        return AcceptedKakaoStudy(view, manifest, packet, selected)

    def list_studies(
        self, actor: ActorContext, binding: str, *, after: str | None = None, limit: int = 30
    ) -> KakaoStudyPage:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise KakaoArchiveError("KAKAO_ARCHIVE_REQUEST_INVALID")
        if after is not None:
            try:
                _STUDY_ID.validate_python(after)
            except ValueError:
                raise KakaoArchiveError("KAKAO_ARCHIVE_REQUEST_INVALID") from None
        with self.sessions() as session:
            owner, _ = authorize_kakao_binding_scope(
                session, actor, binding, PermissionKey.KAKAO_ARCHIVE_READ, lock=False
            )
            query = (
                select(KakaoStudyRecord, KakaoStudyRevisionRecord)
                .join(
                    KakaoStudyRevisionRecord,
                    KakaoStudyRevisionRecord.study_revision_id
                    == KakaoStudyRecord.current_revision_id,
                )
                .where(
                    KakaoStudyRecord.owner_operator_id == owner,
                    KakaoStudyRecord.source_binding_id == binding,
                )
            )
            if after is not None:
                query = query.where(KakaoStudyRecord.study_id > after)
            rows = session.execute(query.order_by(KakaoStudyRecord.study_id).limit(limit + 1)).all()
            items = tuple(_view(*row) for row in rows[:limit])
        return KakaoStudyPage(
            items=items, next_cursor=items[-1].study_id if len(rows) > limit else None
        )
