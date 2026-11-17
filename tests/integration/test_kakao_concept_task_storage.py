"""Disposable source/question/Artifact ownership; no live Graph scope or model execution."""

import importlib.util
import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from eom_catalog_contracts.kakao_archive_binding import KakaoBindingRetire
from eom_catalog_contracts.kakao_concept_tasks import KakaoConceptCreate
from eom_catalog_service import kakao_concept_task_service as task_module
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_archive_service import KakaoArchiveService
from eom_catalog_service.kakao_concept_models import KakaoConceptPhaseRecord, KakaoConceptTaskRecord
from eom_catalog_service.kakao_concept_task_service import KakaoConceptTaskService
from eom_catalog_service.kakao_concept_workflow_submission import submit_kakao_concept_phase
from eom_catalog_service.kakao_question_service import KakaoQuestionService
from eom_identity_service.models import ApiSessionRecord, OperatorRecord
from eom_orchestrator.models import ArtifactRevisionRecord
from eom_protocol.general_chat_rag_knowledge import ChatRagScope
from eom_workflow.compiler import compile_definition
from eom_workflow.control_plane import ExecutionPresetRevision
from eom_workflow.kakao_concept_plan import KakaoConceptExecutionPlan
from eom_workflow.kakao_concept_request import validate_kakao_concept_request_bytes
from eom_workflow_runner import kakao_concept_start
from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowInstanceRecord
from eom_workflow_runner.repository import import_workflow_definition
from PIL import Image
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.integration.test_kakao_archive_storage import make_actor
from tests.integration.test_kakao_question_storage import change_command, create_question
from tests.integration.test_kakao_question_storage import question_store as question_store
from tests.integration.test_kakao_source_storage import source_store as source_store
from tests.unit.test_external_item_learning_execution_resolver import _published_preset
from tests.unit.test_kakao_concept_contracts import ROOT
from tests.unit.test_kakao_concept_tasks import scope_value
from tests.unit.test_kakao_concept_workflow_contracts import plan_value, rehash

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def concept_store(question_store):
    engine, actor, questions, _, sources, artifacts, binding = question_store
    created, _ = create_question(question_store)
    command = KakaoConceptCreate(
        source_binding_id=binding.source_binding_id,
        room_id=created.question.room_id,
        question_id=created.question.question_id,
        question_revision_id=created.question.question_revision_id,
        expected_question_version=created.question.resource_version,
        base_study_revision_id=None,
        additional_instructions="synthetic concept instruction",
    )
    # This scope port does not claim that the actual Graph/policy exists or was retrieved.
    service = KakaoConceptTaskService(
        engine,
        artifacts=artifacts,
        questions=questions,
        sources=sources,
        scope_provider=lambda *_: ChatRagScope.model_validate(scope_value()),
    )
    return service, actor, command, question_store


def prepared(store, *, key=None):
    service, actor, command, _ = store
    mutation = service.create_task(
        actor, command, idempotency_key=key or "concept-request-" + uuid4().hex
    )
    work = service.prepare_plan(actor, command.source_binding_id, mutation.task.task_id)
    return mutation, work


def test_real_question_intent_and_plan_survive_reconstruction_and_remain_pointer_only(
    concept_store,
):
    service, actor, command, store = concept_store
    key = "concept-reconstruction-" + uuid4().hex
    mutation, work = prepared(concept_store, key=key)
    _, intent = service.get_intent(actor, command.source_binding_id, mutation.task.task_id)
    assert intent.question_manifest == work.question_manifest
    engine, _, _, _, sources, artifacts, _ = store
    replacement = KakaoConceptTaskService(
        engine,
        artifacts=artifacts,
        questions=KakaoQuestionService(engine, artifacts=artifacts, sources=sources),
        sources=sources,
        scope_provider=lambda *_: pytest.fail("replay must not select latest Graph"),
    )
    replay = replacement.create_task(actor, command, idempotency_key=key)
    assert replay.replayed and replay.task == mutation.task
    assert replacement.prepare_plan(actor, command.source_binding_id, mutation.task.task_id) == work
    assert (
        replacement.get_intent(actor, command.source_binding_id, mutation.task.task_id)[1] == intent
    )
    with Session(engine) as session:
        authority = replacement.source_authority(
            actor, command.source_binding_id, mutation.task.task_id
        )
        assert authority.reauthorize(session, operator_id=actor.operator_id, work=work) == work
        task = session.get(KakaoConceptTaskRecord, work.task_id)
        phase = session.get(KakaoConceptPhaseRecord, (work.task_id, "PLAN"))
        for row in (task, phase):
            encoded = json.dumps(
                {column.name: getattr(row, column.name) for column in row.__table__.columns},
                default=str,
            )
            assert (
                "private question" not in encoded and "synthetic concept instruction" not in encoded
            )
            assert not any(
                isinstance(getattr(row, column.name), bytes) for column in row.__table__.columns
            )
        assert set(phase.work_input) == set(work.model_dump())


@pytest.mark.parametrize("phase", [False, True])
def test_concurrent_replay_has_one_task_request_and_one_plan(concept_store, phase):
    service, actor, command, store = concept_store
    key, barrier = "concept-same-" + uuid4().hex, Barrier(2)
    if phase:
        task = service.create_task(actor, command, idempotency_key=key).task

    def run():
        barrier.wait(timeout=20)
        return (
            service.prepare_plan(actor, command.source_binding_id, task.task_id)
            if phase
            else service.create_task(actor, command, idempotency_key=key)
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _: run(), range(2)))
    assert results[0] == results[1] if phase else results[0].task == results[1].task
    with Session(store[0]) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(KakaoConceptTaskRecord)
                .where(KakaoConceptTaskRecord.idempotency_key == key)
            )
            == 1
        )
        if phase:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(KakaoConceptPhaseRecord)
                    .where(KakaoConceptPhaseRecord.task_id == task.task_id)
                )
                == 1
            )


def test_same_key_conflict_and_wrong_owner_cannot_read_or_admit(concept_store):
    service, actor, command, store = concept_store
    key = "concept-conflict-" + uuid4().hex
    task = service.create_task(actor, command, idempotency_key=key).task
    with pytest.raises(KakaoArchiveError, match="IDEMPOTENCY_CONFLICT"):
        service.create_task(
            actor,
            command.model_copy(update={"additional_instructions": "changed"}),
            idempotency_key=key,
        )
    other = make_actor(store[0])
    with pytest.raises(KakaoArchiveError):
        service.get_task(other, command.source_binding_id, task.task_id)
    with pytest.raises(KakaoArchiveError):
        service.create_task(other, command, idempotency_key="other-concept-" + uuid4().hex)


@pytest.mark.parametrize("case", ["operator", "binding", "wrong-work", "wrong-owner"])
def test_actual_source_authority_detects_revocation_without_impersonating_an_actor(
    concept_store, case
):
    service, actor, command, store = concept_store
    mutation, work = prepared(concept_store)
    authority = service.source_authority(actor, command.source_binding_id, mutation.task.task_id)
    if case == "operator":
        with Session(store[0]) as session, session.begin():
            session.execute(
                update(OperatorRecord)
                .where(OperatorRecord.operator_id == actor.operator_id)
                .values(status="DISABLED")
            )
    elif case == "binding":
        bindings = KakaoArchiveService(store[0])
        current = bindings.get_binding(actor, command.source_binding_id)
        bindings.command_binding(
            actor,
            command.source_binding_id,
            KakaoBindingRetire(
                parent_policy_revision_id=current.policy_revision.policy_revision_id,
                expected_resource_version=current.resource_version,
            ),
            idempotency_key="concept-retire-" + uuid4().hex,
        )
    elif case == "wrong-work":
        work = work.model_copy(update={"request_bytes": work.request_bytes + 1})
    with Session(store[0]) as session, pytest.raises(KakaoArchiveError):
        authority.reauthorize(
            session,
            operator_id="operator_" + "0" * 32 if case == "wrong-owner" else actor.operator_id,
            work=work,
        )


def test_new_question_edit_never_retargets_an_old_recommendation(concept_store):
    service, actor, command, store = concept_store
    task, work = prepared(concept_store)
    old = (
        store[2]
        .get_question(
            actor,
            command.source_binding_id,
            command.room_id,
            command.question_id,
            revision_id=command.question_revision_id,
        )
        .stored
    )
    changed = store[2].change_question(
        actor, change_command(old), idempotency_key="concept-review-" + uuid4().hex
    )
    assert changed.question.question_revision_id != command.question_revision_id
    assert service.prepare_plan(actor, command.source_binding_id, task.task.task_id) == work
    with pytest.raises(KakaoArchiveError, match="PRECONDITION"):
        service.create_task(actor, command, idempotency_key="stale-concept-" + uuid4().hex)


def test_http_logout_does_not_cancel_exact_accepted_background_work_or_allow_public_reads(
    concept_store,
):
    service, actor, command, store = concept_store
    mutation, work = prepared(concept_store)
    authority = service.source_authority(actor, command.source_binding_id, mutation.task.task_id)
    with Session(store[0]) as session, session.begin():
        session.execute(
            update(ApiSessionRecord)
            .where(ApiSessionRecord.api_session_id == actor.session_id)
            .values(revoked_at=datetime.now(UTC))
        )
    with Session(store[0]) as session:
        assert authority.reauthorize(session, operator_id=actor.operator_id, work=work) == work
        with pytest.raises(KakaoArchiveError):
            authority.reauthorize(
                session,
                operator_id=actor.operator_id,
                work=work.model_copy(update={"task_id": "kakaoconcepttask_" + uuid4().hex}),
            )
    with pytest.raises(KakaoArchiveError):
        service.get_task(actor, command.source_binding_id, work.task_id)


def test_immutable_rows_and_phase_request_pins_are_enforced_by_postgresql(concept_store):
    _, _, _, store = concept_store
    mutation, work = prepared(concept_store)
    for cls, values in [
        (KakaoConceptTaskRecord, dict(request_sha256="sha256:" + "0" * 64)),
        (KakaoConceptPhaseRecord, dict(work_input={"task_id": work.task_id})),
    ]:
        with Session(store[0]) as session, pytest.raises(DBAPIError):
            session.execute(
                update(cls).where(cls.task_id == mutation.task.task_id).values(**values)
            )
            session.commit()


def test_actual_source_owner_submits_the_existing_workflow_and_replays_one_command(
    concept_store, monkeypatch
):
    service, actor, _, store = concept_store
    _, work = prepared(concept_store)
    compiled = compile_definition(ROOT / "config/workflows/kakao-concepts.v1.yaml", {"support"})
    with Session(store[0], expire_on_commit=False) as session, session.begin():
        definition, _ = import_workflow_definition(session, compiled)
        session.expunge(definition)

    def plan_port(_session, **kwargs):
        value = plan_value()
        value.update(
            workflow_id=kwargs["workflow_id"],
            workflow_definition_sha256=kwargs["workflow_definition_sha256"],
            work_input=kwargs["work"].model_dump(mode="json"),
        )
        return KakaoConceptExecutionPlan.model_validate(rehash(value))

    monkeypatch.setattr(kakao_concept_start, "resolve_kakao_concept_plan", plan_port)
    _, preset = _published_preset()
    args = dict(
        actor=actor,
        work=work,
        definition=definition,
        expected_preset=ExecutionPresetRevision.model_validate(preset.canonical_document),
    )
    first = submit_kakao_concept_phase(service, **args)
    second = submit_kakao_concept_phase(service, **args)
    assert first.workflow_id == second.workflow_id and first.command_id == second.command_id
    with Session(store[0]) as session:
        assert (
            session.get(KakaoConceptPhaseRecord, (work.task_id, "PLAN")).workflow_id
            == first.workflow_id
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowCommandRecord)
                .where(WorkflowCommandRecord.workflow_id == first.workflow_id)
            )
            == 1
        )
        assert (
            session.get(WorkflowInstanceRecord, first.workflow_id).created_actor_id
            == actor.operator_id
        )


@pytest.mark.parametrize("phase", ["intent", "plan"])
def test_stop_after_publication_recovers_same_identity_without_rewriting_history(
    concept_store, monkeypatch, phase
):
    service, actor, command, store = concept_store
    key = "concept-interrupted-" + uuid4().hex
    original = (
        task_module.publish_kakao_concept_input
        if phase == "intent"
        else task_module.prepare_kakao_concept_plan
    )
    saved = []

    def stopped(*args, **kwargs):
        saved.append(original(*args, **kwargs))
        raise RuntimeError("stopped after publication")

    name = "publish_kakao_concept_input" if phase == "intent" else "prepare_kakao_concept_plan"
    if phase == "plan":
        task = service.create_task(actor, command, idempotency_key=key).task
    monkeypatch.setattr(task_module, name, stopped)
    with pytest.raises(RuntimeError, match="stopped after publication"):
        if phase == "intent":
            service.create_task(actor, command, idempotency_key=key)
        else:
            service.prepare_plan(actor, command.source_binding_id, task.task_id)
    monkeypatch.setattr(task_module, name, original)
    if phase == "intent":
        repaired = service.create_task(actor, command, idempotency_key=key)
        assert repaired.replayed and repaired.task.intent == saved[0]
    else:
        repaired = service.prepare_plan(actor, command.source_binding_id, task.task_id)
        assert repaired == saved[0]
    pointer = saved[0] if phase == "intent" else saved[0].request_member
    with Session(store[0]) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ArtifactRevisionRecord)
                .where(ArtifactRevisionRecord.content_hash == pointer.sha256)
            )
            == 1
        )


def test_student_and_staff_photo_occurrences_share_original_binary_but_not_message_identity(
    question_store, source_store
):
    engine, actor, questions, initial, sources, artifacts, binding = question_store
    previous = sources.get_source(
        actor,
        initial.source_binding_id,
        initial.room_id,
        source_revision_id=initial.source_revision_id,
    ).resolution
    image = io.BytesIO()
    Image.new("RGB", (400, 300), "white").save(image, format="PNG")
    photo = image.getvalue()
    admission, _ = source_store[-1](
        previous=previous,
        texts=("photo question", "extra photo", "staff original answer"),
        roles=("student", "student", "staff"),
        photos={row: (photo, 400, 300) for row in (1, 2, 3)},
    )
    accepted = sources.admit_source(
        actor, admission, idempotency_key="concept-photo-source-" + uuid4().hex
    )
    created = questions.create_question(
        actor,
        initial.model_copy(update={"source_revision_id": accepted.resolution.source_revision_id}),
        idempotency_key="concept-photo-question-" + uuid4().hex,
    ).question
    service = KakaoConceptTaskService(
        engine,
        artifacts=artifacts,
        questions=questions,
        sources=sources,
        scope_provider=lambda *_: ChatRagScope.model_validate(scope_value()),
    )
    command = KakaoConceptCreate(
        source_binding_id=binding.source_binding_id,
        room_id=created.room_id,
        question_id=created.question_id,
        question_revision_id=created.question_revision_id,
        expected_question_version=created.resource_version,
        base_study_revision_id=None,
        additional_instructions="",
    )
    mutation = service.create_task(
        actor, command, idempotency_key="concept-photo-task-" + uuid4().hex
    )
    work = service.prepare_plan(actor, binding.source_binding_id, mutation.task.task_id)
    assert len(work.files) == 1
    pointer = work.request_member
    opened = artifacts.open_verified_member(
        artifact_id=pointer.artifact_id,
        revision_id=pointer.artifact_revision_id,
        member_path=pointer.member_path,
        sha256=pointer.sha256,
        schema_ref=pointer.schema_ref,
        media_type=pointer.media_type,
        max_bytes=262144,
    )
    with opened.stream as stream:
        request = validate_kakao_concept_request_bytes(work, stream.read())
    assert len(request.question.student.images) == 2
    assert len(request.question.staff.images) == 1
    assert (
        len(
            {
                image.source_occurrence_id
                for image in (*request.question.student.images, *request.question.staff.images)
            }
        )
        == 3
    )
    assert {
        image.value.member.relative_path
        for image in (*request.question.student.images, *request.question.staff.images)
    } == {work.files[0].relative_path}


def test_new_schema_roundtrip_is_empty_only_and_does_not_touch_existing_history(
    concept_store, monkeypatch
):
    service, actor, command, store = concept_store
    task = service.create_task(
        actor, command, idempotency_key="migration-proof-" + uuid4().hex
    ).task
    schema = "test_kakao_concept_" + uuid4().hex
    path = ROOT / "migrations/versions/20261117_0094_kakao_concept_tasks.py"
    spec = importlib.util.spec_from_file_location("concept_task_migration_test", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with store[0].connect() as connection:
        transaction = connection.begin()
        try:
            head = connection.scalar(text("SELECT version_num FROM app.alembic_version"))
            connection.execute(text(f"CREATE SCHEMA {schema}"))
            connection.execute(text(f"SET LOCAL search_path TO {schema}, app"))
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            migration.downgrade()
            assert (
                connection.scalar(
                    text("SELECT to_regclass(:name)"), {"name": schema + ".kakao_concept_tasks"}
                )
                is None
            )
            migration.upgrade()
            # Only synthetic metadata is cloned into this rollback-only schema, not app history.
            columns = (
                "task_id,owner_operator_id,identity_session_id,source_binding_id,room_id,"
                "question_id,question_revision_id,question_version,idempotency_key,"
                "request_sha256,scope,created_at"
            )
            connection.execute(
                text(
                    f"INSERT INTO {schema}.kakao_concept_tasks ({columns}) "
                    f"SELECT {columns} FROM app.kakao_concept_tasks WHERE task_id = :task"
                ),
                {"task": task.task_id},
            )
            with (
                pytest.raises(DBAPIError, match="HISTORY_REQUIRES_REVIEW"),
                connection.begin_nested(),
            ):
                migration.downgrade()
            assert connection.scalar(text("SELECT version_num FROM app.alembic_version")) == head
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM app.kakao_concept_tasks WHERE task_id = :task"),
                    {"task": task.task_id},
                )
                == 1
            )
        finally:
            transaction.rollback()
