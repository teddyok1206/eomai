"""Durable private concept source intents; execution stays with the existing Workflow owner."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast
from uuid import uuid4

from eom_catalog_contracts.kakao_concept_tasks import (
    CONCEPT_TASK_REF,
    MAX_CONCEPT_INTENT_BYTES,
    KakaoConceptCreate,
    KakaoConceptIntent,
    KakaoConceptMutation,
    KakaoConceptSourcePin,
    KakaoConceptTask,
)
from eom_catalog_contracts.kakao_question import KakaoQuestionProvenance
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_operator_identity import ActorContext, PermissionKey
from eom_orchestrator.database import build_session_factory
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.general_chat_rag_knowledge import ChatRagScope
from eom_workflow.kakao_concept_request import KakaoConceptWork
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from .artifacts import CatalogArtifactService
from .kakao_archive_authorization import (
    KakaoArchiveError,
    authorize_kakao_actor,
    authorize_kakao_binding_scope,
    authorize_kakao_current_operator,
    authorize_kakao_room_scope,
)
from .kakao_archive_commands import (
    kakao_command_sha256,
    lock_kakao_intent,
    validate_kakao_idempotency_key,
)
from .kakao_archive_models import KakaoChannelBindingRecord
from .kakao_concept_models import KakaoConceptPhaseRecord, KakaoConceptTaskRecord
from .kakao_question_models import KakaoQuestionRecord, KakaoQuestionRevisionRecord
from .kakao_question_service import KakaoQuestionService, ResolvedKakaoQuestions
from .kakao_room_models import KakaoRoomRecord
from .kakao_source_models import KakaoSourceRevisionRecord
from .kakao_source_pointers import validate_source_pointer_metadata_batch
from .kakao_source_service import KakaoSourceService, source_admission_pointers

if TYPE_CHECKING:
    from .kakao_concept_knowledge import KakaoConceptKnowledgeReader


def _intent_pointer(row: KakaoConceptTaskRecord) -> ArtifactMemberPointer | None:
    if row.intent_artifact_id is None:
        return None
    return ArtifactMemberPointer(
        artifact_id=row.intent_artifact_id,
        artifact_revision_id=cast(str, row.intent_artifact_revision_id),
        member_path="intent.json",
        schema_ref=CONCEPT_TASK_REF,
        media_type="application/json",
        sha256=cast(str, row.intent_sha256),
    )


def _view(row: KakaoConceptTaskRecord) -> KakaoConceptTask:
    pointer = _intent_pointer(row)
    return KakaoConceptTask(
        task_id=row.task_id,
        source_binding_id=row.source_binding_id,
        room_id=row.room_id,
        question_id=row.question_id,
        question_revision_id=row.question_revision_id,
        request_sha256=row.request_sha256,
        state="RESERVED" if pointer is None else "PREPARED",
        intent=pointer,
        created_at=row.created_at,
    )


@dataclass(frozen=True, slots=True)
class KakaoConceptSourceAuthority:
    """Verified immutable intent pins, not a serialized worker or HTTP authority claim."""

    service: "KakaoConceptTaskService"
    intent: KakaoConceptIntent
    owner_operator_id: str

    def reauthorize(
        self, session: Session, *, operator_id: str, work: KakaoConceptWork
    ) -> KakaoConceptWork:
        if operator_id != self.owner_operator_id:
            raise KakaoArchiveError("KAKAO_ARCHIVE_PERMISSION_DENIED")
        row = self.service.accepted_intent_row(session, self.intent, operator_id=operator_id)
        stored = session.get(
            KakaoConceptPhaseRecord, (row.task_id, work.phase), populate_existing=True
        )
        if (
            stored is None
            or stored.work_sha256 != content_sha256(work)
            or stored.work_input != work.model_dump(mode="json")
            or (stored.request_artifact_id, stored.request_artifact_revision_id)
            != (work.request_member.artifact_id, work.request_member.artifact_revision_id)
        ):
            raise KakaoArchiveError("KAKAO_CONCEPT_WORK_NOT_ACCEPTED")
        if (
            work.task_id,
            work.source_binding_id,
            work.question_revision_id,
            work.question_manifest,
        ) != (
            row.task_id,
            row.source_binding_id,
            row.question_revision_id,
            self.intent.question_manifest,
        ):
            raise KakaoArchiveError("KAKAO_CONCEPT_WORK_NOT_ACCEPTED")
        validate_source_pointer_metadata_batch(
            session, (work.request_member, *(file.source for file in work.files))
        )
        if work.phase == "COMPOSE":
            from .kakao_concept_composition import authorize_kakao_concept_composition

            if self.service.knowledge_reader is None:
                raise KakaoArchiveError("KAKAO_CONCEPT_KNOWLEDGE_NOT_CONFIGURED")
            authorize_kakao_concept_composition(self.service.knowledge_reader, self, work)
        return work


class KakaoConceptTaskService:
    def __init__(
        self,
        engine: Engine,
        *,
        artifacts: CatalogArtifactService,
        questions: KakaoQuestionService,
        sources: KakaoSourceService,
        scope_provider: Callable[[Session, ActorContext, str], ChatRagScope] | None = None,
        authorize_study: Callable[[Session, ActorContext, KakaoConceptCreate], None] | None = None,
        knowledge_reader: "KakaoConceptKnowledgeReader | None" = None,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.artifacts, self.questions = artifacts, questions
        self.sources = sources
        self.scope_provider, self.authorize_study = scope_provider, authorize_study
        self.knowledge_reader = knowledge_reader

    @staticmethod
    def _row(
        session: Session, actor: ActorContext, binding: str, task_id: str, *, lock: bool = False
    ) -> KakaoConceptTaskRecord:
        owner, _ = authorize_kakao_binding_scope(
            session, actor, binding, PermissionKey.KAKAO_ARCHIVE_EDIT, lock=False
        )
        query = select(KakaoConceptTaskRecord).where(
            KakaoConceptTaskRecord.task_id == task_id,
            KakaoConceptTaskRecord.owner_operator_id == owner,
            KakaoConceptTaskRecord.source_binding_id == binding,
        )
        row = session.scalar(query.with_for_update() if lock else query)
        if row is None:
            raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
        authorize_kakao_room_scope(
            session, actor, binding, row.room_id, PermissionKey.KAKAO_ARCHIVE_READ, lock=False
        )
        return row

    def _reserve(
        self, actor: ActorContext, command: KakaoConceptCreate, key: str
    ) -> tuple[KakaoConceptTask, ChatRagScope, bool]:
        with self.sessions.begin() as session:
            owner = authorize_kakao_actor(
                session, actor, PermissionKey.KAKAO_ARCHIVE_EDIT, now=datetime.now(UTC)
            )
            lock_kakao_intent(session, owner, "concept", key)
            authorize_kakao_room_scope(
                session,
                actor,
                command.source_binding_id,
                command.room_id,
                PermissionKey.KAKAO_ARCHIVE_EDIT,
                lock=False,
            )
            authorize_kakao_room_scope(
                session,
                actor,
                command.source_binding_id,
                command.room_id,
                PermissionKey.KAKAO_ARCHIVE_READ,
                lock=False,
            )
            old = session.scalar(
                select(KakaoConceptTaskRecord).where(
                    KakaoConceptTaskRecord.owner_operator_id == owner,
                    KakaoConceptTaskRecord.idempotency_key == key,
                )
            )
            if old is not None:
                if old.request_sha256 != kakao_command_sha256(command):
                    raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
                return _view(old), ChatRagScope.model_validate(old.scope), True
            head = session.get(KakaoQuestionRecord, command.question_id)
            if head is None or (head.owner_operator_id, head.source_binding_id, head.room_id) != (
                owner,
                command.source_binding_id,
                command.room_id,
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
            if head.superseded_by_composition_id is not None or (
                head.current_revision_id,
                head.resource_version,
            ) != (command.question_revision_id, command.expected_question_version):
                raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
            if command.base_study_revision_id is not None:
                if self.authorize_study is None:
                    raise KakaoArchiveError("KAKAO_CONCEPT_STUDY_NOT_AVAILABLE")
                self.authorize_study(session, actor, command)
            if self.scope_provider is None:
                raise KakaoArchiveError("KAKAO_CONCEPT_SCOPE_NOT_CONFIGURED")
            scope = self.scope_provider(session, actor, command.source_binding_id)
            row = KakaoConceptTaskRecord(
                task_id="kakaoconcepttask_" + uuid4().hex,
                owner_operator_id=owner,
                identity_session_id=cast(str, actor.session_id),
                source_binding_id=command.source_binding_id,
                room_id=command.room_id,
                question_id=command.question_id,
                question_revision_id=command.question_revision_id,
                question_version=command.expected_question_version,
                idempotency_key=key,
                request_sha256=kakao_command_sha256(command),
                scope=scope.model_dump(mode="json"),
                created_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            return _view(row), scope, False

    def _selected(self, actor: ActorContext, command: KakaoConceptCreate) -> ResolvedKakaoQuestions:
        return self.questions.resolve_questions(
            actor,
            command.source_binding_id,
            (
                KakaoQuestionProvenance(
                    question_id=command.question_id,
                    question_revision_id=command.question_revision_id,
                ),
            ),
            room_id=command.room_id,
        )

    def create_task(
        self, actor: ActorContext, command: KakaoConceptCreate, *, idempotency_key: str
    ) -> KakaoConceptMutation:
        key = validate_kakao_idempotency_key(idempotency_key)
        task, scope, replayed = self._reserve(actor, command, key)
        if task.intent is not None:
            return KakaoConceptMutation(
                task=self.get_task(actor, command.source_binding_id, task.task_id), replayed=True
            )
        selected = self._selected(actor, command)
        if selected.questions[0].stored.review_state == "EXCLUDED":
            raise KakaoArchiveError("KAKAO_CONCEPT_QUESTION_EXCLUDED")
        intent = KakaoConceptIntent(
            task_id=task.task_id,
            request=command,
            question_manifest=selected.questions[0].stored.manifest,
            scope=scope,
            sources=tuple(
                KakaoConceptSourcePin(
                    source_revision_id=source.accepted.resolution.source_revision_id,
                    normalization_revision_id=source.resolved.normalization.normalization_revision_id,
                    manifest=source.accepted.manifest,
                    closure=source_admission_pointers(source.accepted.resolution.admission),
                )
                for source in selected.sources
            ),
        )

        def authorize() -> None:
            with self.sessions.begin() as session:
                row = self._row(session, actor, command.source_binding_id, task.task_id)
                self.sources.validate_question_source_metadata(session, actor, selected.sources)
                self._validate_intent(session, row, intent, require_adopted=False)

        from .kakao_concept_publication import publish_kakao_concept_input

        pointer = publish_kakao_concept_input(
            self.artifacts, task_id=task.task_id, value=intent, authorize=authorize
        )
        with self.sessions.begin() as session:
            row = self._row(session, actor, command.source_binding_id, task.task_id, lock=True)
            self._validate_intent(session, row, intent, require_adopted=False)
            validate_source_pointer_metadata_batch(session, (pointer,))
            if row.intent_artifact_id is None:
                row.intent_artifact_id, row.intent_artifact_revision_id, row.intent_sha256 = (
                    pointer.artifact_id,
                    pointer.artifact_revision_id,
                    pointer.sha256,
                )
                row.prepared_at = datetime.now(UTC)
                session.flush()
            elif _intent_pointer(row) != pointer:
                raise KakaoArchiveError("KAKAO_CONCEPT_INTENT_CHANGED")
            return KakaoConceptMutation(task=_view(row), replayed=replayed)

    @staticmethod
    def _validate_intent(
        session: Session,
        row: KakaoConceptTaskRecord,
        intent: KakaoConceptIntent,
        *,
        require_adopted: bool = True,
    ) -> None:
        if (
            row.task_id != intent.task_id
            or row.request_sha256 != kakao_command_sha256(intent.request)
            or row.scope != intent.scope.model_dump(mode="json")
            or (
                row.source_binding_id,
                row.room_id,
                row.question_id,
                row.question_revision_id,
                row.question_version,
            )
            != (
                intent.request.source_binding_id,
                intent.request.room_id,
                intent.request.question_id,
                intent.request.question_revision_id,
                intent.request.expected_question_version,
            )
        ):
            raise KakaoArchiveError("KAKAO_CONCEPT_INTENT_CHANGED")
        if require_adopted and row.intent_sha256 != sha256_bytes(canonical_json_bytes(intent)):
            raise KakaoArchiveError("KAKAO_CONCEPT_INTENT_CHANGED")
        revision = session.get(
            KakaoQuestionRevisionRecord, row.question_revision_id, populate_existing=True
        )
        if revision is None or (
            revision.question_id,
            revision.room_id,
            revision.resource_version,
            revision.manifest_artifact_id,
            revision.manifest_artifact_revision_id,
            revision.manifest_sha256,
        ) != (
            row.question_id,
            row.room_id,
            row.question_version,
            intent.question_manifest.artifact_id,
            intent.question_manifest.artifact_revision_id,
            intent.question_manifest.sha256,
        ):
            raise KakaoArchiveError("KAKAO_CONCEPT_QUESTION_PIN_MISMATCH")
        if revision.review_state == "EXCLUDED":
            raise KakaoArchiveError("KAKAO_CONCEPT_QUESTION_EXCLUDED")
        pins = {source.source_revision_id: source for source in intent.sources}
        sources = tuple(
            session.scalars(
                select(KakaoSourceRevisionRecord)
                .where(KakaoSourceRevisionRecord.source_revision_id.in_(tuple(pins)))
                .execution_options(populate_existing=True)
            )
        )
        if len(sources) != len(pins):
            raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
        for source in sources:
            pin = pins[source.source_revision_id]
            if (
                source.owner_operator_id,
                source.source_binding_id,
                source.room_id,
                source.normalization_revision_id,
                source.manifest_artifact_id,
                source.manifest_artifact_revision_id,
                source.manifest_sha256,
            ) != (
                row.owner_operator_id,
                row.source_binding_id,
                row.room_id,
                pin.normalization_revision_id,
                pin.manifest.artifact_id,
                pin.manifest.artifact_revision_id,
                pin.manifest.sha256,
            ):
                raise KakaoArchiveError("KAKAO_CONCEPT_SOURCE_PIN_INVALID")
        pointers = {
            intent.question_manifest,
            *(pointer for pin in intent.sources for pointer in (pin.manifest, *pin.closure)),
        }
        if require_adopted:
            pointers.add(cast(ArtifactMemberPointer, _intent_pointer(row)))
        validate_source_pointer_metadata_batch(session, tuple(pointers))

    def accepted_intent_row(
        self, session: Session, intent: KakaoConceptIntent, *, operator_id: str
    ) -> KakaoConceptTaskRecord:
        """Authority starts only at this owner's persisted task, never worker-supplied IDs."""
        row = session.get(KakaoConceptTaskRecord, intent.task_id, populate_existing=True)
        if row is None or row.owner_operator_id != operator_id:
            raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
        for permission in (PermissionKey.KAKAO_ARCHIVE_EDIT, PermissionKey.KAKAO_ARCHIVE_READ):
            # A bounded accepted task is background work, not an impersonated HTTP session.
            # The original session is audit provenance only; logout does not create a new grant.
            authorize_kakao_current_operator(
                session,
                operator_id=row.owner_operator_id,
                permission=permission,
            )
        binding = session.get(
            KakaoChannelBindingRecord, row.source_binding_id, populate_existing=True
        )
        room = session.get(KakaoRoomRecord, row.room_id, populate_existing=True)
        if (
            binding is None
            or room is None
            or binding.owner_operator_id != row.owner_operator_id
            or binding.state == "RETIRED"
            or (room.owner_operator_id, room.source_binding_id, room.state)
            != (row.owner_operator_id, row.source_binding_id, "ACTIVE")
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_PERMISSION_DENIED")
        self._validate_intent(session, row, intent)
        return row

    def get_intent(
        self, actor: ActorContext, binding: str, task_id: str
    ) -> tuple[KakaoConceptTask, KakaoConceptIntent]:
        with self.sessions.begin() as session:
            row = self._row(session, actor, binding, task_id)
            pointer, task = _intent_pointer(row), _view(row)
            if pointer is None:
                raise KakaoArchiveError("KAKAO_CONCEPT_INPUT_NOT_PREPARED")
        intent = self._read_intent(pointer)
        with self.sessions.begin() as session:
            row = self._row(session, actor, binding, task_id)
            if _intent_pointer(row) != pointer:
                raise KakaoArchiveError("KAKAO_CONCEPT_INTENT_CHANGED")
            self._validate_intent(session, row, intent)
        return task, intent

    def _read_intent(self, pointer: ArtifactMemberPointer) -> KakaoConceptIntent:
        opened = self.artifacts.open_verified_member(
            artifact_id=pointer.artifact_id,
            revision_id=pointer.artifact_revision_id,
            member_path=pointer.member_path,
            schema_ref=pointer.schema_ref,
            media_type=pointer.media_type,
            sha256=pointer.sha256,
            max_bytes=MAX_CONCEPT_INTENT_BYTES,
        )
        with opened.stream as stream:
            raw = stream.read(MAX_CONCEPT_INTENT_BYTES + 1)
        if len(raw) != opened.content_length or sha256_bytes(raw) != pointer.sha256:
            raise KakaoArchiveError("KAKAO_CONCEPT_INTENT_CHANGED")
        intent = KakaoConceptIntent.model_validate_json(raw)
        if canonical_json_bytes(intent) != raw:
            raise KakaoArchiveError("KAKAO_CONCEPT_INTENT_CHANGED")
        return intent

    def accepted_source_authority(
        self, *, task_id: str, operator_id: str
    ) -> KakaoConceptSourceAuthority:
        """Read a persisted intent outside write locks; never manufacture an API session."""
        with self.sessions.begin() as session:
            row = session.get(KakaoConceptTaskRecord, task_id)
            if row is None or row.owner_operator_id != operator_id:
                raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
            for permission in (PermissionKey.KAKAO_ARCHIVE_READ, PermissionKey.KAKAO_ARCHIVE_EDIT):
                authorize_kakao_current_operator(
                    session, operator_id=operator_id, permission=permission
                )
            pointer = _intent_pointer(row)
            if pointer is None:
                raise KakaoArchiveError("KAKAO_CONCEPT_INPUT_NOT_PREPARED")
        intent = self._read_intent(pointer)
        with self.sessions.begin() as session:
            row = self.accepted_intent_row(session, intent, operator_id=operator_id)
            if _intent_pointer(row) != pointer:
                raise KakaoArchiveError("KAKAO_CONCEPT_INTENT_CHANGED")
        return KakaoConceptSourceAuthority(self, intent, operator_id)

    def get_task(self, actor: ActorContext, binding: str, task_id: str) -> KakaoConceptTask:
        with self.sessions.begin() as session:
            view = _view(self._row(session, actor, binding, task_id))
        return view if view.intent is None else self.get_intent(actor, binding, task_id)[0]

    def prepare_plan(self, actor: ActorContext, binding: str, task_id: str) -> KakaoConceptWork:
        _, intent = self.get_intent(actor, binding, task_id)

        def authorize() -> None:
            with self.sessions.begin() as session:
                self._row(session, actor, binding, task_id)
                self.accepted_intent_row(session, intent, operator_id=cast(str, actor.operator_id))

        with self.sessions.begin() as session:
            authority = KakaoConceptSourceAuthority(self, intent, cast(str, actor.operator_id))
            self.accepted_intent_row(session, intent, operator_id=cast(str, actor.operator_id))
            old = session.get(KakaoConceptPhaseRecord, (task_id, "PLAN"))
            if old is not None:
                work = KakaoConceptWork.model_validate(old.work_input)
                return authority.reauthorize(
                    session, operator_id=cast(str, actor.operator_id), work=work
                )
        from .kakao_concept_publication import prepare_kakao_concept_plan

        selected = self._selected(actor, intent.request)
        work = prepare_kakao_concept_plan(
            self.artifacts, intent=intent, selected=selected, authorize=authorize
        )
        return self.adopt_phase(actor, binding, task_id, work)

    def adopt_phase(
        self, actor: ActorContext, binding: str, task_id: str, work: KakaoConceptWork
    ) -> KakaoConceptWork:
        """Adopt one already-published exact input with the existing unique phase identity."""
        _, intent = self.get_intent(actor, binding, task_id)
        authority = KakaoConceptSourceAuthority(self, intent, cast(str, actor.operator_id))
        return self.adopt_accepted_phase(authority, work)

    def adopt_accepted_phase(
        self, authority: KakaoConceptSourceAuthority, work: KakaoConceptWork
    ) -> KakaoConceptWork:
        """Accepted background work uses its actual saved owner, never an invented HTTP actor."""
        if authority.service is not self:
            raise KakaoArchiveError("KAKAO_CONCEPT_WORK_NOT_ACCEPTED")
        intent = authority.intent
        task_id, binding = intent.task_id, intent.request.source_binding_id
        if (
            work.task_id,
            work.source_binding_id,
            work.question_revision_id,
            work.question_manifest,
        ) != (task_id, binding, intent.request.question_revision_id, intent.question_manifest):
            raise KakaoArchiveError("KAKAO_CONCEPT_WORK_NOT_ACCEPTED")
        if work.phase == "COMPOSE":
            from .kakao_concept_composition import authorize_kakao_concept_composition

            if self.knowledge_reader is None:
                raise KakaoArchiveError("KAKAO_CONCEPT_KNOWLEDGE_NOT_CONFIGURED")
            # Retrieval, original reads, decode and input publication precede the adoption lock.
            authorize_kakao_concept_composition(self.knowledge_reader, authority, work)
        with self.sessions.begin() as session:
            row = session.scalar(
                select(KakaoConceptTaskRecord)
                .where(
                    KakaoConceptTaskRecord.task_id == task_id,
                    KakaoConceptTaskRecord.owner_operator_id == authority.owner_operator_id,
                )
                .with_for_update()
            )
            if row is None:
                raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
            self.accepted_intent_row(session, intent, operator_id=row.owner_operator_id)
            validate_source_pointer_metadata_batch(
                session, (work.request_member, *(file.source for file in work.files))
            )
            phase = session.get(KakaoConceptPhaseRecord, (task_id, work.phase))
            if phase is None:
                phase = KakaoConceptPhaseRecord(
                    task_id=task_id,
                    phase=work.phase,
                    work_input=work.model_dump(mode="json"),
                    work_sha256=content_sha256(work),
                    request_artifact_id=work.request_member.artifact_id,
                    request_artifact_revision_id=work.request_member.artifact_revision_id,
                    created_at=datetime.now(UTC),
                )
                session.add(phase)
                session.flush()
            elif phase.work_sha256 != content_sha256(work) or phase.work_input != work.model_dump(
                mode="json"
            ):
                raise KakaoArchiveError("KAKAO_CONCEPT_PHASE_INPUT_CHANGED")
        with self.sessions() as session:
            return authority.reauthorize(
                session, operator_id=authority.owner_operator_id, work=work
            )

    def prepare_compose(self, actor: ActorContext, binding: str, task_id: str) -> KakaoConceptWork:
        from .kakao_concept_composition import prepare_kakao_concept_composition

        if self.knowledge_reader is None:
            raise KakaoArchiveError("KAKAO_CONCEPT_KNOWLEDGE_NOT_CONFIGURED")
        return prepare_kakao_concept_composition(
            self, self.knowledge_reader, actor=actor, binding_id=binding, task_id=task_id
        )

    def prepare_accepted_compose(self, authority: KakaoConceptSourceAuthority) -> KakaoConceptWork:
        from .kakao_concept_composition import prepare_kakao_concept_composition

        if self.knowledge_reader is None or authority.service is not self:
            raise KakaoArchiveError("KAKAO_CONCEPT_KNOWLEDGE_NOT_CONFIGURED")
        return prepare_kakao_concept_composition(
            self,
            self.knowledge_reader,
            actor=authority,
            binding_id=authority.intent.request.source_binding_id,
            task_id=authority.intent.task_id,
        )

    def source_authority(
        self, actor: ActorContext, binding: str, task_id: str
    ) -> KakaoConceptSourceAuthority:
        return KakaoConceptSourceAuthority(
            self, self.get_intent(actor, binding, task_id)[1], cast(str, actor.operator_id)
        )
