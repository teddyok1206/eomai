"""Durable private PDF requests, single-winner claims and current-authority reads.

Rendering and NAS publication remain in the existing execution/publication adapters.
No read or request replay starts a process. Unknown RUNNING work is never reclaimed
solely because a clock or HTTP request expired.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from eom_catalog_contracts.kakao_export_store import (
    KakaoExport,
    KakaoExportCreate,
    KakaoExportMutation,
    KakaoExportPage,
    KakaoExportProfile,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_kakao_archive_contracts import RenderCommand, RenderExecution
from eom_operator_identity import ActorContext, PermissionKey
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.models import JobRecord
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from .artifacts import CatalogArtifactService, VerifiedArtifactMemberStream
from .kakao_archive_authorization import KakaoArchiveError, authorize_kakao_binding_scope
from .kakao_archive_commands import (
    kakao_command_sha256,
    lock_kakao_intent,
    validate_kakao_idempotency_key,
)
from .kakao_export_models import (
    KakaoExportAttemptRecord,
    KakaoExportRecord,
    KakaoExportRequestRecord,
)
from .kakao_packet_service import AcceptedKakaoPacket, KakaoPacketService
from .kakao_pdf_publication import LAYOUT_REF, PDF_REF, KakaoPdfPublication
from .kakao_question_editing import packet_student_subset
from .kakao_question_service import ResolvedKakaoQuestions
from .kakao_source_pointers import validate_source_pointer_metadata_batch
from .kakao_source_service import KakaoSourceService


@dataclass(frozen=True, slots=True)
class KakaoExportClaim:
    export: KakaoExport
    execution: RenderExecution
    acquired: bool


def _execution(attempt: KakaoExportAttemptRecord) -> RenderExecution:
    return RenderExecution(
        command_id=attempt.command_id,
        task_id=attempt.task_id,
        attempt_id=attempt.attempt_id,
        attempt_number=attempt.attempt_number,
        fence=attempt.attempt_number,
    )


def _view(row: KakaoExportRecord, attempt: KakaoExportAttemptRecord | None) -> KakaoExport:
    def pointer(
        name: str, media: str, schema: str, digest: str | None
    ) -> ArtifactMemberPointer | None:
        if attempt is None or digest is None:
            return None
        return ArtifactMemberPointer(
            artifact_id=cast(str, attempt.artifact_id),
            artifact_revision_id=cast(str, attempt.artifact_revision_id),
            member_path=name,
            media_type=media,
            schema_ref=schema,
            sha256=digest,
        )

    return KakaoExport.model_validate(
        dict(
            source_binding_id=row.source_binding_id,
            packet_id=row.packet_id,
            packet_revision_id=row.packet_revision_id,
            student_id=row.student_id,
            export_id=row.export_id,
            profile=row.profile,
            subset_sha256=row.subset_sha256,
            mode=row.mode,
            state="PENDING" if attempt is None else attempt.state,
            created_at=row.created_at,
            completed_at=None if attempt is None else attempt.completed_at,
            export_revision_id=None if attempt is None else attempt.export_revision_id,
            page_count=0 if attempt is None else attempt.page_count,
            pdf=pointer(
                "report.pdf",
                "application/pdf",
                PDF_REF,
                None if attempt is None else attempt.pdf_sha256,
            ),
            layout=pointer(
                "layout.json",
                "application/json",
                LAYOUT_REF,
                None if attempt is None else attempt.layout_sha256,
            ),
            error_code=None if attempt is None else attempt.error_code,
        )
    )


class KakaoExportService:
    def __init__(
        self,
        engine: Engine,
        *,
        artifacts: CatalogArtifactService,
        packets: KakaoPacketService,
        sources: KakaoSourceService,
        profile: KakaoExportProfile,
    ) -> None:
        self._sessions = build_session_factory(engine)
        self._artifacts, self._packets, self._sources = artifacts, packets, sources
        self._profile = KakaoExportProfile.model_validate(profile.model_dump(mode="json"))

    @staticmethod
    def _row(
        session: Session,
        actor: ActorContext,
        binding: str,
        export_id: str,
        permission: PermissionKey,
        *,
        lock: bool = False,
    ) -> tuple[KakaoExportRecord, KakaoExportAttemptRecord | None]:
        owner, _ = authorize_kakao_binding_scope(session, actor, binding, permission, lock=lock)
        query = select(KakaoExportRecord).where(
            KakaoExportRecord.owner_operator_id == owner,
            KakaoExportRecord.source_binding_id == binding,
            KakaoExportRecord.export_id == export_id,
        )
        row = session.scalar(query.with_for_update() if lock else query)
        if row is None:
            raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
        attempt = (
            session.get(KakaoExportAttemptRecord, row.current_attempt_id)
            if row.current_attempt_id
            else None
        )
        if row.current_attempt_id and (
            attempt is None
            or attempt.export_id != row.export_id
            or attempt.attempt_number != row.attempt_number
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_STORED_EXPORT_INVALID")
        return row, attempt

    def _source_check(
        self,
        session: Session,
        actor: ActorContext,
        row: KakaoExportRecord,
        packet: AcceptedKakaoPacket,
        selected: ResolvedKakaoQuestions,
    ) -> None:
        subset = packet_student_subset(packet.packet, row.student_id)
        if (
            packet.stored.packet_id != row.packet_id
            or packet.stored.packet_revision_id != row.packet_revision_id
            or packet.stored.source_binding_id != row.source_binding_id
            or packet.packet.mode != row.mode
            or subset.subset_sha256 != row.subset_sha256
            or len(subset.questions) != row.question_count
            or tuple(
                (q.question_id, q.question_revision_id, q.room_id, q.student, q.manifest)
                for q in subset.questions
            )
            != tuple(
                (
                    q.stored.question_id,
                    q.stored.question_revision_id,
                    q.stored.room_id,
                    q.stored.student,
                    q.stored.manifest,
                )
                for q in selected.questions
            )
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_STORED_EXPORT_INVALID")
        self._sources.validate_question_source_metadata(session, actor, selected.sources)
        validate_source_pointer_metadata_batch(
            session, (packet.stored.manifest, *(q.stored.manifest for q in selected.questions))
        )

    def resolve_inputs(
        self,
        actor: ActorContext,
        binding: str,
        export_id: str,
    ) -> tuple[KakaoExport, AcceptedKakaoPacket, ResolvedKakaoQuestions]:
        with self._sessions.begin() as session:
            row, attempt = self._row(
                session, actor, binding, export_id, PermissionKey.KAKAO_ARCHIVE_READ
            )
            view = _view(row, attempt)
        packet, selected = self._packets.resolve_student(
            actor,
            binding,
            view.packet_id,
            revision_id=view.packet_revision_id,
            student_id=view.student_id,
        )
        with self._sessions.begin() as session:
            row, attempt = self._row(
                session, actor, binding, export_id, PermissionKey.KAKAO_ARCHIVE_READ
            )
            self._source_check(session, actor, row, packet, selected)
            view = _view(row, attempt)
            if view.state == "COMPLETED":
                self._output_metadata(session, row, cast(KakaoExportAttemptRecord, attempt), view)
        return view, packet, selected

    def get_export(self, actor: ActorContext, binding: str, export_id: str) -> KakaoExport:
        return self.resolve_inputs(actor, binding, export_id)[0]

    def request_export(
        self,
        actor: ActorContext,
        command: KakaoExportCreate,
        *,
        idempotency_key: str,
    ) -> KakaoExportMutation:
        command = KakaoExportCreate.model_validate(command.model_dump(mode="json"))
        key, digest = validate_kakao_idempotency_key(idempotency_key), kakao_command_sha256(command)
        with self._sessions.begin() as session:
            owner, _ = authorize_kakao_binding_scope(
                session,
                actor,
                command.source_binding_id,
                PermissionKey.KAKAO_ARCHIVE_EXPORT,
                lock=False,
            )
            old = session.get(KakaoExportRequestRecord, (owner, command.source_binding_id, key))
            if old is not None and old.request_sha256 != digest:
                raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
            old_id = None if old is None else old.export_id
        if old_id is not None:
            return KakaoExportMutation(
                export=self.get_export(actor, command.source_binding_id, old_id), replayed=True
            )
        packet, selected = self._packets.resolve_student(
            actor,
            command.source_binding_id,
            command.packet_id,
            revision_id=command.packet_revision_id,
            student_id=command.student_id,
        )
        subset = packet_student_subset(packet.packet, command.student_id)
        build = sha256_bytes(
            canonical_json_bytes(
                dict(
                    request=command.model_dump(mode="json"),
                    profile=self._profile.model_dump(mode="json"),
                    subset_sha256=subset.subset_sha256,
                    mode=packet.packet.mode,
                )
            )
        )
        with self._sessions.begin() as session:
            owner, _ = authorize_kakao_binding_scope(
                session,
                actor,
                command.source_binding_id,
                PermissionKey.KAKAO_ARCHIVE_EXPORT,
                lock=True,
            )
            # Binding serializes its aliases; build-key lock also protects the unique cache key.
            lock_kakao_intent(session, owner, "export/build", build)
            old = session.get(KakaoExportRequestRecord, (owner, command.source_binding_id, key))
            if old is not None:
                if old.request_sha256 != digest:
                    raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
                export_id, replayed = old.export_id, True
            else:
                row = session.scalar(
                    select(KakaoExportRecord).where(
                        KakaoExportRecord.owner_operator_id == owner,
                        KakaoExportRecord.build_sha256 == build,
                    )
                )
                replayed = row is not None
                if row is None:
                    row = KakaoExportRecord(
                        export_id="kakaoexport_" + uuid4().hex,
                        owner_operator_id=owner,
                        source_binding_id=command.source_binding_id,
                        packet_id=command.packet_id,
                        packet_revision_id=command.packet_revision_id,
                        student_id=command.student_id,
                        build_sha256=build,
                        subset_sha256=subset.subset_sha256,
                        profile=self._profile.model_dump(mode="json"),
                        mode=packet.packet.mode,
                        question_count=len(subset.questions),
                        created_at=datetime.now(UTC),
                        current_attempt_id=None,
                        attempt_number=0,
                    )
                    self._source_check(session, actor, row, packet, selected)
                    session.add(row)
                    session.flush()
                else:
                    self._source_check(session, actor, row, packet, selected)
                export_id = row.export_id
                session.add(
                    KakaoExportRequestRecord(
                        owner_operator_id=owner,
                        source_binding_id=command.source_binding_id,
                        idempotency_key=key,
                        request_sha256=digest,
                        export_id=export_id,
                    )
                )
        return KakaoExportMutation(
            export=self.get_export(actor, command.source_binding_id, export_id), replayed=replayed
        )

    def claim_export(
        self,
        actor: ActorContext,
        binding: str,
        export_id: str,
        *,
        retry_failed_attempt_id: str | None = None,
    ) -> KakaoExportClaim:
        _, packet, selected = self.resolve_inputs(actor, binding, export_id)
        with self._sessions.begin() as session:
            row, old = self._row(
                session, actor, binding, export_id, PermissionKey.KAKAO_ARCHIVE_EXPORT, lock=True
            )
            self._source_check(session, actor, row, packet, selected)
            if row.profile != self._profile.model_dump(mode="json"):
                raise KakaoArchiveError("KAKAO_ARCHIVE_EXPORT_RUNTIME_MISMATCH")
            if old is not None:
                if (
                    retry_failed_attempt_id is None
                    or old.previous_attempt_id == retry_failed_attempt_id
                ):
                    return KakaoExportClaim(_view(row, old), _execution(old), False)
                if old.attempt_id != retry_failed_attempt_id or old.state != "FAILED":
                    raise KakaoArchiveError("KAKAO_ARCHIVE_EXPORT_RETRY_DENIED")
            elif retry_failed_attempt_id is not None:
                raise KakaoArchiveError("KAKAO_ARCHIVE_EXPORT_RETRY_DENIED")
            attempt = KakaoExportAttemptRecord(
                attempt_id="kakaoattempt_" + uuid4().hex,
                export_id=export_id,
                previous_attempt_id=None if old is None else old.attempt_id,
                command_id="kakaocommand_" + uuid4().hex,
                task_id="kakaotask_" + uuid4().hex,
                attempt_number=row.attempt_number + 1,
                state="RUNNING",
                started_at=datetime.now(UTC),
                page_count=0,
            )
            session.add(attempt)
            session.flush()
            row.current_attempt_id, row.attempt_number = attempt.attempt_id, attempt.attempt_number
            session.flush()
            return KakaoExportClaim(_view(row, attempt), _execution(attempt), True)

    @staticmethod
    def _command_matches(
        row: KakaoExportRecord, attempt: KakaoExportAttemptRecord, command: RenderCommand
    ) -> None:
        profile = KakaoExportProfile.model_validate(row.profile)
        if (
            command.execution != _execution(attempt)
            or command.export_id != row.export_id
            or command.source_binding_id != row.source_binding_id
            or command.packet_revision_id != row.packet_revision_id
            or command.student_id != row.student_id
            or command.subset_sha256 != row.subset_sha256
            or command.mode != row.mode
            or command.renderer_release_sha256 != profile.renderer_release_sha256
            or command.layout_policy != profile.layout_policy
            or command.font.sha256 != profile.font_sha256
            or command.font.size_bytes != profile.font_size_bytes
            or command.font.media_type != "font/otf"
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_EXPORT_EXECUTION_MISMATCH")

    def bind_command(
        self,
        actor: ActorContext,
        binding: str,
        export_id: str,
        command: RenderCommand,
    ) -> None:
        command = RenderCommand.model_validate(command.model_dump(mode="json"))
        _, packet, selected = self.resolve_inputs(actor, binding, export_id)
        with self._sessions.begin() as session:
            row, attempt = self._row(
                session, actor, binding, export_id, PermissionKey.KAKAO_ARCHIVE_EXPORT, lock=True
            )
            if attempt is None or attempt.state != "RUNNING":
                raise KakaoArchiveError("KAKAO_ARCHIVE_EXPORT_NOT_RUNNING")
            self._source_check(session, actor, row, packet, selected)
            self._command_matches(row, attempt, command)
            proposed = command.model_dump(mode="json")
            if attempt.command is not None and attempt.command != proposed:
                raise KakaoArchiveError("KAKAO_ARCHIVE_EXPORT_EXECUTION_MISMATCH")
            attempt.command = proposed

    def check_attempt(
        self,
        actor: ActorContext,
        binding: str,
        export_id: str,
        command: RenderCommand,
        packet: AcceptedKakaoPacket,
        selected: ResolvedKakaoQuestions,
    ) -> None:
        with self._sessions.begin() as session:
            row, attempt = self._row(
                session, actor, binding, export_id, PermissionKey.KAKAO_ARCHIVE_EXPORT
            )
            if (
                attempt is None
                or attempt.state != "RUNNING"
                or attempt.command != command.model_dump(mode="json")
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_EXPORT_NOT_RUNNING")
            self._source_check(session, actor, row, packet, selected)
            self._command_matches(row, attempt, command)

    @staticmethod
    def _output_metadata(
        session: Session,
        row: KakaoExportRecord,
        attempt: KakaoExportAttemptRecord,
        view: KakaoExport,
    ) -> None:
        if view.pdf is None or view.layout is None or attempt.command is None:
            raise KakaoArchiveError("KAKAO_ARCHIVE_STORED_EXPORT_INVALID")
        command = RenderCommand.model_validate(attempt.command)
        KakaoExportService._command_matches(row, attempt, command)
        metadata = validate_source_pointer_metadata_batch(session, (view.pdf, view.layout))
        logical, revision = metadata[(view.pdf.artifact_id, view.pdf.artifact_revision_id)]
        job = session.get(JobRecord, attempt.publication_job_id)
        expected = dict(
            export_id=row.export_id,
            source_binding_id=row.source_binding_id,
            packet_revision_id=row.packet_revision_id,
            student_id=row.student_id,
            subset_sha256=row.subset_sha256,
            mode=row.mode,
            execution=command.execution.model_dump(mode="json"),
            command_sha256=sha256_bytes(canonical_json_bytes(command.model_dump(mode="json"))),
            renderer_release_sha256=command.renderer_release_sha256,
        )
        if (
            logical.artifact_type != "kakao-question-pdf"
            or revision.job_id != attempt.publication_job_id
            or revision.content_hash != view.layout.sha256
            or job is None
            or any(job.request.get(key) != value for key, value in expected.items())
            or view.page_count != row.question_count
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_EVIDENCE_INVALID")

    def complete_export(
        self,
        actor: ActorContext,
        binding: str,
        export_id: str,
        command: RenderCommand,
        publication: KakaoPdfPublication,
    ) -> KakaoExport:
        _, packet, selected = self.resolve_inputs(actor, binding, export_id)
        with self._sessions.begin() as session:
            row, attempt = self._row(
                session, actor, binding, export_id, PermissionKey.KAKAO_ARCHIVE_EXPORT, lock=True
            )
            if attempt is None or attempt.command != command.model_dump(mode="json"):
                raise KakaoArchiveError("KAKAO_ARCHIVE_EXPORT_EXECUTION_MISMATCH")
            self._command_matches(row, attempt, command)
            self._source_check(session, actor, row, packet, selected)
            if publication.export_id != export_id:
                raise KakaoArchiveError("KAKAO_ARCHIVE_EXPORT_EXECUTION_MISMATCH")
            if attempt.state == "COMPLETED":
                view = _view(row, attempt)
                if (
                    view.pdf != publication.pdf
                    or view.layout != publication.layout
                    or attempt.publication_job_id != publication.publication_job_id
                ):
                    raise KakaoArchiveError("KAKAO_ARCHIVE_STORED_EXPORT_INVALID")
                self._output_metadata(session, row, attempt, view)
                return view
            if attempt.state != "RUNNING":
                raise KakaoArchiveError("KAKAO_ARCHIVE_EXPORT_NOT_RUNNING")
            attempt.state, attempt.completed_at = "COMPLETED", datetime.now(UTC)
            attempt.export_revision_id = "kakaoexportrev_" + uuid4().hex
            attempt.artifact_id, attempt.artifact_revision_id = (
                publication.pdf.artifact_id,
                publication.pdf.artifact_revision_id,
            )
            attempt.pdf_sha256, attempt.layout_sha256 = (
                publication.pdf.sha256,
                publication.layout.sha256,
            )
            attempt.publication_job_id, attempt.page_count = (
                publication.publication_job_id,
                row.question_count,
            )
            view = _view(row, attempt)
            if view.pdf != publication.pdf or view.layout != publication.layout:
                raise KakaoArchiveError("KAKAO_ARCHIVE_EXPORT_EXECUTION_MISMATCH")
            self._output_metadata(session, row, attempt, view)
            return view

    def fail_attempt(
        self,
        actor: ActorContext,
        binding: str,
        export_id: str,
        execution: RenderExecution,
        *,
        error_code: str,
        assert_stopped: Callable[[RenderExecution], None],
        layout_review: bool = False,
    ) -> KakaoExport:
        if not callable(assert_stopped):
            raise KakaoArchiveError("KAKAO_ARCHIVE_EXPORT_STOP_EVIDENCE_REQUIRED")
        # Must prove the actual process stopped, outside a transaction; timeouts are not proof.
        assert_stopped(execution)
        with self._sessions.begin() as session:
            row, attempt = self._row(
                session, actor, binding, export_id, PermissionKey.KAKAO_ARCHIVE_EXPORT, lock=True
            )
            if attempt is None or execution != _execution(attempt):
                raise KakaoArchiveError("KAKAO_ARCHIVE_EXPORT_EXECUTION_MISMATCH")
            state = "NEEDS_LAYOUT_REVIEW" if layout_review else "FAILED"
            if attempt.state != "RUNNING":
                if attempt.state != state or attempt.error_code != error_code:
                    raise KakaoArchiveError("KAKAO_ARCHIVE_EXPORT_NOT_RUNNING")
                return _view(row, attempt)
            attempt.state, attempt.error_code, attempt.completed_at = (
                state,
                error_code,
                datetime.now(UTC),
            )
            return _view(row, attempt)

    def list_exports(
        self, actor: ActorContext, binding: str, *, limit: int = 50, cursor: str | None = None
    ) -> KakaoExportPage:
        import re

        if (
            type(limit) is not int
            or not 1 <= limit <= 100
            or (cursor is not None and re.fullmatch(r"kakaoexport_[0-9a-f]{32}", cursor) is None)
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_REQUEST_INVALID")
        with self._sessions.begin() as session:
            owner, _ = authorize_kakao_binding_scope(
                session, actor, binding, PermissionKey.KAKAO_ARCHIVE_READ, lock=False
            )
            query = (
                select(KakaoExportRecord, KakaoExportAttemptRecord)
                .outerjoin(
                    KakaoExportAttemptRecord,
                    KakaoExportRecord.current_attempt_id == KakaoExportAttemptRecord.attempt_id,
                )
                .where(
                    KakaoExportRecord.owner_operator_id == owner,
                    KakaoExportRecord.source_binding_id == binding,
                )
            )
            if cursor is not None:
                query = query.where(KakaoExportRecord.export_id > cursor)
            rows = session.execute(
                query.order_by(KakaoExportRecord.export_id).limit(limit + 1)
            ).all()
            items = tuple(_view(row, attempt) for row, attempt in rows[:limit])
            return KakaoExportPage(
                items=items, next_cursor=items[-1].export_id if len(rows) > limit else None
            )

    def open_pdf(
        self, actor: ActorContext, binding: str, export_id: str, *, revision_id: str
    ) -> VerifiedArtifactMemberStream:
        view, packet, selected = self.resolve_inputs(actor, binding, export_id)
        with self._sessions.begin() as session:
            authorize_kakao_binding_scope(
                session, actor, binding, PermissionKey.KAKAO_ARCHIVE_EXPORT, lock=False
            )
        if view.state != "COMPLETED" or view.pdf is None or view.export_revision_id != revision_id:
            raise KakaoArchiveError("KAKAO_ARCHIVE_EXPORT_NOT_COMPLETED")
        pointer = view.pdf
        opened = self._artifacts.open_verified_member(
            artifact_id=pointer.artifact_id,
            revision_id=pointer.artifact_revision_id,
            member_path=pointer.member_path,
            sha256=pointer.sha256,
            media_type=pointer.media_type,
            schema_ref=pointer.schema_ref,
            max_bytes=128 * 1024 * 1024,
        )
        try:
            with self._sessions.begin() as session:
                row, attempt = self._row(
                    session, actor, binding, export_id, PermissionKey.KAKAO_ARCHIVE_EXPORT
                )
                self._source_check(session, actor, row, packet, selected)
                if _view(row, attempt) != view:
                    raise KakaoArchiveError("KAKAO_ARCHIVE_STORED_EXPORT_INVALID")
                self._output_metadata(session, row, cast(KakaoExportAttemptRecord, attempt), view)
        except BaseException:
            opened.stream.close()
            raise
        return opened
