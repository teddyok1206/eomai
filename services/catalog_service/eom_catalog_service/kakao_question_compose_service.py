"""Atomic question split/merge use case inside the existing private question owner.

Only exact small reservations live in PostgreSQL. Existing source resolution and
Artifact publication run outside write transactions; no collection or worker call.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from eom_catalog_contracts.kakao_question import KakaoQuestionProvenance, KakaoQuestionStudentPin
from eom_catalog_contracts.kakao_question_composition import (
    KakaoCompositionInput,
    KakaoQuestionComposition,
    KakaoQuestionMerge,
)
from eom_catalog_contracts.kakao_question_composition_result import KakaoQuestionCompositionResult
from eom_catalog_contracts.kakao_question_store import KakaoStoredQuestion
from eom_operator_identity.contracts import ActorContext, PermissionKey
from eom_orchestrator.database import build_session_factory
from pydantic import TypeAdapter
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.kakao_archive_authorization import (
    KakaoArchiveError,
    authorize_kakao_actor,
    authorize_kakao_room_scope,
)
from eom_catalog_service.kakao_archive_commands import (
    kakao_command_sha256,
    lock_kakao_intent,
    validate_kakao_idempotency_key,
)
from eom_catalog_service.kakao_question_composition_models import (
    KakaoQuestionCompositionInputRecord as InputRecord,
)
from eom_catalog_service.kakao_question_composition_models import (
    KakaoQuestionCompositionOutputRecord as OutputRecord,
)
from eom_catalog_service.kakao_question_composition_models import (
    KakaoQuestionCompositionRecord as CompositionRecord,
)
from eom_catalog_service.kakao_question_models import (
    KakaoQuestionRecord,
    KakaoQuestionRevisionRecord,
)
from eom_catalog_service.kakao_question_publication import (
    KakaoQuestionPublication,
    publish_kakao_question,
)
from eom_catalog_service.kakao_question_selections import (
    ResolvedKakaoCompositionQuestion,
    prepare_question_composition,
)
from eom_catalog_service.kakao_question_service import KakaoQuestionService, ResolvedKakaoQuestions
from eom_catalog_service.kakao_source_pointers import validate_source_pointer_metadata_batch
from eom_catalog_service.kakao_source_service import KakaoSourceService

_COMMAND: TypeAdapter[KakaoQuestionComposition] = TypeAdapter(KakaoQuestionComposition)
_SCOPE = "question-composition"


@dataclass(frozen=True, slots=True)
class _Reservation:
    composition_id: str
    mapping_id: str
    at: datetime
    outputs: tuple[tuple[str, str], ...]
    completed: bool


def _inputs(command: KakaoQuestionComposition) -> tuple[KakaoCompositionInput, ...]:
    return command.inputs if isinstance(command, KakaoQuestionMerge) else (command.input,)


def _provenance(pins: tuple[KakaoCompositionInput, ...]) -> tuple[KakaoQuestionProvenance, ...]:
    return tuple(
        KakaoQuestionProvenance(
            question_id=p.question_id, question_revision_id=p.question_revision_id
        )
        for p in pins
    )


class KakaoQuestionComposeService:
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

    @staticmethod
    def _heads(
        session: Session, owner: str, command: KakaoQuestionComposition
    ) -> tuple[KakaoQuestionRecord, ...]:
        expected = _inputs(command)
        rows = tuple(
            session.scalars(
                select(KakaoQuestionRecord)
                .where(
                    KakaoQuestionRecord.owner_operator_id == owner,
                    KakaoQuestionRecord.source_binding_id == command.source_binding_id,
                    KakaoQuestionRecord.room_id == command.room_id,
                    KakaoQuestionRecord.question_id.in_(tuple(pin.question_id for pin in expected)),
                )
                .order_by(KakaoQuestionRecord.question_id)
                .with_for_update()
            )
        )
        by_id = {row.question_id: row for row in rows}
        if len(by_id) != len(expected):
            raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
        if any(
            by_id[pin.question_id].superseded_by_composition_id is not None
            or (by_id[pin.question_id].current_revision_id, by_id[pin.question_id].resource_version)
            != (pin.question_revision_id, pin.resource_version)
            for pin in expected
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
        return rows

    @staticmethod
    def _reserved(
        session: Session, record: CompositionRecord, command: KakaoQuestionComposition
    ) -> _Reservation:
        inputs = tuple(
            session.scalars(
                select(InputRecord)
                .where(InputRecord.composition_id == record.composition_id)
                .order_by(InputRecord.ordinal)
            )
        )
        outputs = tuple(
            session.scalars(
                select(OutputRecord)
                .where(OutputRecord.composition_id == record.composition_id)
                .order_by(OutputRecord.ordinal)
            )
        )
        expected = _inputs(command)
        count = 1 if isinstance(command, KakaoQuestionMerge) else len(command.partitions)
        if (
            len(outputs) != count
            or len(inputs) != len(expected)
            or tuple(row.ordinal for row in outputs) != tuple(range(1, count + 1))
            or tuple(
                (row.ordinal, row.question_id, row.question_revision_id, row.resource_version)
                for row in inputs
            )
            != tuple(
                (i, pin.question_id, pin.question_revision_id, pin.resource_version)
                for i, pin in enumerate(expected, 1)
            )
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_STORED_QUESTION_INVALID")
        return _Reservation(
            record.composition_id,
            record.mapping_revision_id,
            record.reserved_at,
            tuple((r.question_id, r.question_revision_id) for r in outputs),
            record.state == "COMPLETED",
        )

    def _reserve(
        self, actor: ActorContext, command: KakaoQuestionComposition, key: str
    ) -> _Reservation:
        digest = kakao_command_sha256(command)
        with self._sessions.begin() as session:
            owner = authorize_kakao_actor(
                session, actor, PermissionKey.KAKAO_ARCHIVE_EDIT, now=datetime.now(UTC)
            )
            lock_kakao_intent(session, owner, _SCOPE, key)
            _, room = authorize_kakao_room_scope(
                session,
                actor,
                command.source_binding_id,
                command.room_id,
                PermissionKey.KAKAO_ARCHIVE_EDIT,
                lock=True,
            )
            old = session.scalar(
                select(CompositionRecord).where(
                    CompositionRecord.owner_operator_id == owner,
                    CompositionRecord.idempotency_key == key,
                )
            )
            if old is not None:
                if old.request_sha256 != digest:
                    raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
                return self._reserved(session, old, command)
            self._heads(session, owner, command)
            mapping = room.current_mapping_revision_id
            if self._questions.current_student_pin(session, room, mapping) is None:
                raise KakaoArchiveError("KAKAO_ARCHIVE_COMPOSITION_SCOPE_INVALID")
            record = CompositionRecord(
                composition_id="kakaocomposition_" + uuid4().hex,
                owner_operator_id=owner,
                source_binding_id=command.source_binding_id,
                room_id=command.room_id,
                mapping_revision_id=mapping,
                idempotency_key=key,
                request_sha256=digest,
                operation=command.operation,
                state="RESERVED",
                reserved_at=datetime.now(UTC),
                completed_at=None,
            )
            session.add(record)
            session.flush()
            for i, pin in enumerate(_inputs(command), 1):
                session.add(
                    InputRecord(
                        composition_id=record.composition_id,
                        ordinal=i,
                        room_id=command.room_id,
                        question_id=pin.question_id,
                        question_revision_id=pin.question_revision_id,
                        resource_version=pin.resource_version,
                    )
                )
            count = 1 if isinstance(command, KakaoQuestionMerge) else len(command.partitions)
            for ordinal in range(1, count + 1):
                session.add(
                    OutputRecord(
                        composition_id=record.composition_id,
                        ordinal=ordinal,
                        question_id="kakaoquestion_" + uuid4().hex,
                        question_revision_id="kakaoquestionrev_" + uuid4().hex,
                    )
                )
            session.flush()
            return self._reserved(session, record, command)

    def _authorize_sources(
        self,
        actor: ActorContext,
        command: KakaoQuestionComposition,
        resolved: ResolvedKakaoQuestions,
    ) -> None:
        with self._sessions.begin() as session:
            authorize_kakao_room_scope(
                session,
                actor,
                command.source_binding_id,
                command.room_id,
                PermissionKey.KAKAO_ARCHIVE_EDIT,
                lock=False,
            )
            self._sources.validate_question_source_metadata(session, actor, resolved.sources)
            validate_source_pointer_metadata_batch(
                session, tuple(q.stored.manifest for q in resolved.questions)
            )

    def compose_questions(
        self, actor: ActorContext, command: KakaoQuestionComposition, *, idempotency_key: str
    ) -> KakaoQuestionCompositionResult:
        command = _COMMAND.validate_python(command.model_dump(mode="json"))
        key = validate_kakao_idempotency_key(idempotency_key)
        reserved = self._reserve(actor, command, key)
        if reserved.completed:
            resolved = self._questions.resolve_questions(
                actor,
                command.source_binding_id,
                tuple(
                    KakaoQuestionProvenance(question_id=q, question_revision_id=r)
                    for q, r in reserved.outputs
                ),
                room_id=command.room_id,
            )
            return self._result(
                command, reserved, tuple(q.stored for q in resolved.questions), True
            )
        resolved = self._questions.resolve_questions(
            actor, command.source_binding_id, _provenance(_inputs(command)), room_id=command.room_id
        )
        sources = tuple(item.resolved for item in resolved.sources)
        manifests = prepare_question_composition(
            command,
            tuple(
                ResolvedKakaoCompositionQuestion(q.published.question, q.stored.resource_version)
                for q in resolved.questions
            ),
            new_ids=reserved.outputs,
            actor_id=cast(str, actor.operator_id),
            created_at=reserved.at,
            sources=sources,
        )

        def authorize() -> None:
            self._authorize_sources(actor, command, resolved)

        publications = tuple(
            publish_kakao_question(
                self._artifacts, question=value, sources=sources, authorize=authorize
            )
            for value in manifests
        )
        return self._adopt(actor, command, key, reserved, resolved, publications)

    def _adopt(
        self,
        actor: ActorContext,
        command: KakaoQuestionComposition,
        key: str,
        reserved: _Reservation,
        resolved: ResolvedKakaoQuestions,
        publications: tuple[KakaoQuestionPublication, ...],
    ) -> KakaoQuestionCompositionResult:
        with self._sessions.begin() as session:
            owner = authorize_kakao_actor(
                session, actor, PermissionKey.KAKAO_ARCHIVE_EDIT, now=datetime.now(UTC)
            )
            lock_kakao_intent(session, owner, _SCOPE, key)
            _, room = authorize_kakao_room_scope(
                session,
                actor,
                command.source_binding_id,
                command.room_id,
                PermissionKey.KAKAO_ARCHIVE_EDIT,
                lock=True,
            )
            intent = session.get(CompositionRecord, reserved.composition_id)
            if (
                intent is None
                or intent.owner_operator_id != owner
                or intent.idempotency_key != key
                or intent.request_sha256 != kakao_command_sha256(command)
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
            current = self._reserved(session, intent, command)
            if (current.outputs, current.mapping_id, current.at) != (
                reserved.outputs,
                reserved.mapping_id,
                reserved.at,
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_STORED_QUESTION_INVALID")
            self._sources.validate_question_source_metadata(session, actor, resolved.sources)
            metadata = validate_source_pointer_metadata_batch(
                session,
                (
                    *(q.stored.manifest for q in resolved.questions),
                    *(p.published.pointer for p in publications),
                ),
            )
            if (
                tuple(
                    (p.published.question.question_id, p.published.question.question_revision_id)
                    for p in publications
                )
                != reserved.outputs
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_STORED_QUESTION_INVALID")
            pin = publications[0].published.question.student
            for p in publications:
                manifest, pointer = p.published.question, p.published.pointer
                logical, revision = metadata[(pointer.artifact_id, pointer.artifact_revision_id)]
                if (
                    logical.artifact_type != "kakao-question-manifest"
                    or revision.job_id != p.publication_job_id
                    or revision.content_hash != pointer.sha256
                    or manifest.student != pin
                    or manifest.source_binding_id != command.source_binding_id
                    or manifest.room_id != command.room_id
                    or manifest.created_at != reserved.at
                    or manifest.created_by != owner
                    or manifest.previous_revision_id is not None
                    or manifest.review_state != "UNREVIEWED"
                    or manifest.provenance != _provenance(_inputs(command))
                ):
                    raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_EVIDENCE_INVALID")
            if current.completed:
                self._check_adopted(session, publications)
            else:
                if pin is None or pin != self._questions.current_student_pin(
                    session, room, reserved.mapping_id
                ):
                    raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
                heads = self._heads(session, owner, command)
                for p in publications:
                    self._insert_output(session, owner, reserved, p, pin)
                session.flush()
                for head in heads:
                    head.superseded_by_composition_id = reserved.composition_id
                # Receipt validation must observe every output and every input transition.
                session.flush()
                intent.state, intent.completed_at = "COMPLETED", datetime.now(UTC)
                session.flush()
            stored = tuple(
                KakaoStoredQuestion(
                    source_binding_id=command.source_binding_id,
                    room_id=command.room_id,
                    question_id=p.published.question.question_id,
                    question_revision_id=p.published.question.question_revision_id,
                    previous_revision_id=None,
                    resource_version=1,
                    manifest=p.published.pointer,
                    review_state="UNREVIEWED",
                    first_student_at_utc=p.published.question.first_student_at_utc,
                    student=p.published.question.student,
                    created_at=reserved.at,
                )
                for p in publications
            )
            return self._result(command, reserved, stored, current.completed)

    @staticmethod
    def _check_adopted(
        session: Session, publications: tuple[KakaoQuestionPublication, ...]
    ) -> None:
        rows = {
            r.question_revision_id: r
            for r in session.scalars(
                select(KakaoQuestionRevisionRecord).where(
                    KakaoQuestionRevisionRecord.question_revision_id.in_(
                        tuple(p.published.question.question_revision_id for p in publications)
                    )
                )
            )
        }
        if len(rows) != len(publications) or any(
            (
                rows[p.published.question.question_revision_id].manifest_artifact_id,
                rows[p.published.question.question_revision_id].manifest_artifact_revision_id,
                rows[p.published.question.question_revision_id].manifest_sha256,
            )
            != (
                p.published.pointer.artifact_id,
                p.published.pointer.artifact_revision_id,
                p.published.pointer.sha256,
            )
            for p in publications
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_STORED_QUESTION_INVALID")

    @staticmethod
    def _insert_output(
        session: Session,
        owner: str,
        reserved: _Reservation,
        publication: KakaoQuestionPublication,
        pin: KakaoQuestionStudentPin,
    ) -> None:
        question, pointer = publication.published.question, publication.published.pointer
        session.add(
            KakaoQuestionRecord(
                question_id=question.question_id,
                owner_operator_id=owner,
                source_binding_id=question.source_binding_id,
                room_id=question.room_id,
                origin_source_revision_id=None,
                origin_candidate_ordinal=None,
                origin_occurrence_id=None,
                origin_composition_id=reserved.composition_id,
                superseded_by_composition_id=None,
                current_revision_id=question.question_revision_id,
                resource_version=1,
                created_at=reserved.at,
            )
        )
        session.flush()
        session.add(
            KakaoQuestionRevisionRecord(
                question_revision_id=question.question_revision_id,
                question_id=question.question_id,
                room_id=question.room_id,
                command_id=None,
                composition_id=reserved.composition_id,
                previous_revision_id=None,
                resource_version=1,
                mapping_revision_id=pin.room_mapping_revision_id,
                review_state=question.review_state,
                first_student_at_utc=question.first_student_at_utc,
                manifest_artifact_id=pointer.artifact_id,
                manifest_artifact_revision_id=pointer.artifact_revision_id,
                manifest_sha256=pointer.sha256,
                publication_job_id=publication.publication_job_id,
                created_at=reserved.at,
            )
        )

    @staticmethod
    def _result(
        command: KakaoQuestionComposition,
        reserved: _Reservation,
        outputs: tuple[KakaoStoredQuestion, ...],
        replayed: bool,
    ) -> KakaoQuestionCompositionResult:
        return KakaoQuestionCompositionResult(
            composition_id=reserved.composition_id,
            operation=command.operation,
            source_binding_id=command.source_binding_id,
            room_id=command.room_id,
            inputs=_inputs(command),
            outputs=outputs,
            replayed=replayed,
        )
