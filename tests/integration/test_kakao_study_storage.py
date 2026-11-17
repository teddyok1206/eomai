"""Real saved-study/Artifact/packet storage; synthetic text only, no production or model."""

import importlib.util
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from eom_catalog_contracts.kakao_concept_knowledge import KakaoConceptResultPin
from eom_catalog_contracts.kakao_study_store import (
    KakaoStudyCreate,
    KakaoStudyQuestionEdit,
    KakaoStudyRevise,
)
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_study_models import (
    KakaoStudyCommandRecord,
    KakaoStudyRecord,
    KakaoStudyRevisionRecord,
)
from eom_catalog_service.kakao_study_service import KakaoStudyService
from eom_identity_service.models import ApiSessionRecord
from eom_kakao_archive_contracts.concepts import ConceptComposition
from eom_orchestrator.models import ArtifactRevisionRecord
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.integration.test_kakao_archive_storage import make_actor
from tests.integration.test_kakao_packet_storage import packet_store as packet_store
from tests.integration.test_kakao_question_storage import question_store as question_store
from tests.integration.test_kakao_source_storage import source_store as source_store
from tests.unit.test_kakao_concept_contracts import composed

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def study_store(packet_store):
    engine, actor, packets, pcommand, selected, _questions, sources, artifacts = packet_store
    packet = packets.save_packet(
        actor, pcommand, idempotency_key="study-packet-" + uuid4().hex
    ).packet
    concepts = Mock()
    service = KakaoStudyService(
        engine, artifacts=artifacts, packets=packets, sources=sources, concepts=concepts
    )
    command = KakaoStudyCreate(
        source_binding_id=packet.source_binding_id,
        packet_id=packet.packet_id,
        packet_revision_id=packet.packet_revision_id,
        student_id=selected[0].student.student_id,
        title="학생 질문의 개념 메모",
        questions=(
            KakaoStudyQuestionEdit(
                question_revision_id=selected[0].question_revision_id,
                concept_task_id=None,
                blocks=(),
                notes=(dict(title="복습 개념", text="원래 질문·답변은 그대로 보관합니다."),),
            ),
        ),
    )
    return engine, actor, service, command, concepts, selected


def save(store, *, key=None):
    _, actor, service, command, *_ = store
    key = key or "study-create-" + uuid4().hex
    return service.save_study(actor, command, idempotency_key=key), key


def revised(command, stored, *, title="수정한 개념 메모"):
    return KakaoStudyRevise(
        **command.model_dump(exclude={"schema_version", "title"}),
        title=title,
        study_id=stored.study_id,
        parent_revision_id=stored.study_revision_id,
        expected_resource_version=stored.resource_version,
    )


def test_saved_notes_restart_and_revision_replay_remain_pointer_only(study_store):
    engine, actor, service, command, concepts, _ = study_store
    first, key = save(study_store)
    assert not first.replayed
    restored = KakaoStudyService(
        engine,
        artifacts=service.artifacts,
        packets=service.packets,
        sources=service.sources,
        concepts=concepts,
    )
    original = restored.get_study(actor, command.source_binding_id, first.study.study_id)
    assert original.stored == first.study
    assert original.manifest.questions[0].edit == command.questions[0]
    assert original.manifest.questions[0].result is None
    assert restored.save_study(actor, command, idempotency_key=key).replayed
    assert restored.list_studies(actor, command.source_binding_id).items == (first.study,)
    edit = revised(command, first.study)
    next_key = "study-edit-" + uuid4().hex
    second = restored.save_study(actor, edit, idempotency_key=next_key)
    assert (
        second.study.resource_version == 2
        and second.study.previous_revision_id == first.study.study_revision_id
    )
    assert (
        restored.get_study(actor, command.source_binding_id, first.study.study_id).stored
        == second.study
    )
    assert (
        restored.get_study(
            actor,
            command.source_binding_id,
            first.study.study_id,
            revision_id=first.study.study_revision_id,
        )
        == original
    )
    assert restored.save_study(actor, edit, idempotency_key=next_key).study == second.study
    for table in (
        KakaoStudyRecord.__table__,
        KakaoStudyCommandRecord.__table__,
        KakaoStudyRevisionRecord.__table__,
    ):
        assert not any(
            str(column.type).upper() in {"JSON", "JSONB", "BYTEA", "BLOB"}
            for column in table.columns
        )
    concepts.source_authority.assert_not_called()


def test_manual_study_does_not_require_the_optional_concept_runtime(study_store):
    _, actor, service, command, *_ = study_store
    service.concepts = None
    saved, _ = save(study_store)
    assert (
        service.get_study(actor, command.source_binding_id, saved.study.study_id).stored
        == saved.study
    )
    body = command.model_dump(mode="json")
    body["questions"][0]["concept_task_id"] = "kakaoconcepttask_" + uuid4().hex
    with pytest.raises(KakaoArchiveError, match="CONCEPT_RUNTIME_UNAVAILABLE"):
        service.save_study(
            actor,
            KakaoStudyCreate.model_validate(body),
            idempotency_key="no-runtime-" + uuid4().hex,
        )


def test_same_key_changed_body_and_another_owner_are_rejected(study_store):
    engine, actor, service, command, *_ = study_store
    first, key = save(study_store)
    with pytest.raises(KakaoArchiveError, match="IDEMPOTENCY_CONFLICT"):
        service.save_study(
            actor, command.model_copy(update={"title": "다른 본문"}), idempotency_key=key
        )
    other = make_actor(engine)
    with pytest.raises(KakaoArchiveError):
        service.get_study(other, command.source_binding_id, first.study.study_id)
    wrong = command.model_dump(mode="json")
    wrong["questions"][0]["question_revision_id"] = study_store[-1][1].question_revision_id
    with pytest.raises(KakaoArchiveError, match="QUESTION_SET_MISMATCH"):
        service.save_study(
            actor,
            KakaoStudyCreate.model_validate(wrong),
            idempotency_key="other-student-" + uuid4().hex,
        )


@pytest.mark.parametrize("operation", ["create", "revise"])
def test_concurrent_same_request_has_one_revision(study_store, operation):
    engine, actor, service, command, *_ = study_store
    if operation == "revise":
        first, _ = save(study_store)
        command = revised(command, first.study)
    key = "concurrent-study-" + uuid4().hex
    barrier = Barrier(3)

    def call():
        barrier.wait()
        return service.save_study(actor, command, idempotency_key=key)

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = tuple(pool.map(lambda _: call(), range(3)))
    assert len({r.study.study_revision_id for r in results}) == 1
    assert sum(not r.replayed for r in results) == 1
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(KakaoStudyCommandRecord)
                .where(
                    KakaoStudyCommandRecord.owner_operator_id == actor.operator_id,
                    KakaoStudyCommandRecord.idempotency_key == key,
                )
            )
            == 1
        )


def test_competing_edits_cannot_overwrite_each_other(study_store):
    _, actor, service, command, *_ = study_store
    first, _ = save(study_store)
    barrier = Barrier(2)

    def edit(index):
        barrier.wait()
        try:
            return service.save_study(
                actor,
                revised(command, first.study, title=f"편집 {index}"),
                idempotency_key="competing-study-" + uuid4().hex,
            )
        except KakaoArchiveError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(edit, range(2)))
    assert sum(isinstance(r, KakaoArchiveError) for r in results) == 1
    assert (
        str(next(r for r in results if isinstance(r, KakaoArchiveError)))
        == "KAKAO_ARCHIVE_PRECONDITION_FAILED"
    )
    assert (
        service.get_study(
            actor, command.source_binding_id, first.study.study_id
        ).stored.resource_version
        == 2
    )


def test_publication_then_interruption_reuses_original_artifact(study_store, monkeypatch):
    engine, actor, service, command, *_ = study_store
    original = service._adopt
    monkeypatch.setattr(service, "_adopt", Mock(side_effect=RuntimeError("injected before CAS")))
    key = "interrupted-study-" + uuid4().hex
    with pytest.raises(RuntimeError, match="injected"):
        service.save_study(actor, command, idempotency_key=key)
    with Session(engine) as session:
        before = session.scalar(select(func.count()).select_from(ArtifactRevisionRecord))
        intent = session.scalar(
            select(KakaoStudyCommandRecord).where(
                KakaoStudyCommandRecord.owner_operator_id == actor.operator_id,
                KakaoStudyCommandRecord.idempotency_key == key,
            )
        )
        expected = intent.study_revision_id
    monkeypatch.setattr(service, "_adopt", original)
    completed = service.save_study(actor, command, idempotency_key=key)
    assert completed.study.study_revision_id == expected
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == before


def test_current_permission_and_database_immutability_are_enforced(study_store):
    engine, actor, service, command, *_ = study_store
    first, _ = save(study_store)
    for cls, condition, change in (
        (
            KakaoStudyRevisionRecord,
            KakaoStudyRevisionRecord.study_revision_id == first.study.study_revision_id,
            {"title": "overwrite"},
        ),
        (
            KakaoStudyRecord,
            KakaoStudyRecord.study_id == first.study.study_id,
            {"resource_version": 9},
        ),
    ):
        with pytest.raises(DBAPIError), Session(engine) as session, session.begin():
            session.execute(update(cls).where(condition).values(**change))
    with Session(engine) as session, session.begin():
        session.execute(
            update(ApiSessionRecord)
            .where(ApiSessionRecord.api_session_id == actor.session_id)
            .values(revoked_at=datetime.now(UTC))
        )
    with pytest.raises(KakaoArchiveError):
        service.get_study(actor, command.source_binding_id, first.study.study_id)


def test_owner_binding_history_uses_indexed_ordered_lookup(study_store):
    engine, actor, _service, command, *_ = study_store
    save(study_store)
    with Session(engine) as session, session.begin():
        session.execute(text("SET LOCAL enable_seqscan=off"))
        plan = session.execute(
            text(
                "EXPLAIN (FORMAT JSON) SELECT study_id FROM kakao_studies "
                "WHERE owner_operator_id=:owner AND source_binding_id=:binding "
                "ORDER BY study_id LIMIT 30"
            ),
            dict(owner=actor.operator_id, binding=command.source_binding_id),
        ).scalar_one()
    assert "ix_kakao_study_page" in str(plan) or "uq_kakao_study_owner" in str(plan)


@pytest.mark.parametrize("case", ["saved", "wrong-question", "missing-block", "missing-capture"])
def test_concept_selection_pins_the_existing_result_and_reauthorizes(
    study_store, monkeypatch, case
):
    """Actual study DB/Artifact/packet; the completed-concept owner is a synthetic test port."""
    import eom_catalog_service.kakao_study_service as module

    _, actor, service, command, concepts, _ = study_store
    _packet, selected = service.packets.resolve_student(
        actor,
        command.source_binding_id,
        command.packet_id,
        revision_id=command.packet_revision_id,
        student_id=command.student_id,
    )
    q = selected.questions[0].stored
    pin = KakaoConceptResultPin(
        workflow_id="workflow_" + uuid4().hex,
        step_run_id="steprun_" + uuid4().hex,
        job_id="job_" + uuid4().hex,
        artifact_id="artifact_" + uuid4().hex,
        artifact_revision_id="rev_" + uuid4().hex,
        sha256="sha256:" + "a" * 64,
    )
    result = SimpleNamespace(
        work=SimpleNamespace(
            question_revision_id=q.question_revision_id, question_manifest=q.manifest
        ),
        pin=pin,
        result=SimpleNamespace(
            output=SimpleNamespace(
                output=ConceptComposition.model_validate(composed(capture=False))
            )
        ),
    )
    reader = Mock(return_value=result)
    monkeypatch.setattr(module, "read_kakao_concept_phase_result", reader)
    body = command.model_dump(mode="json")
    edit = body["questions"][0]
    edit["concept_task_id"] = "kakaoconcepttask_" + uuid4().hex
    edit["blocks"] = [
        dict(
            block_index=0,
            title=None,
            relevance=None,
            explanation="편집한 설명",
            capture_indices=None,
        )
    ]
    if case == "wrong-question":
        result.work.question_revision_id = "kakaoquestionrev_" + uuid4().hex
    elif case == "missing-block":
        edit["blocks"][0]["block_index"] = 5
    elif case == "missing-capture":
        edit["blocks"][0]["capture_indices"] = [0]
    changed = KakaoStudyCreate.model_validate(body)
    if case != "saved":
        with pytest.raises(
            KakaoArchiveError,
            match=r"KAKAO_STUDY_(CONCEPT_QUESTION_MISMATCH|BLOCK_SELECTION_INVALID)",
        ):
            service.save_study(actor, changed, idempotency_key="invalid-selection-" + uuid4().hex)
        return
    saved = service.save_study(actor, changed, idempotency_key="concept-study-" + uuid4().hex)
    accepted = service.get_study(actor, command.source_binding_id, saved.study.study_id)
    assert accepted.manifest.questions[0].result == pin
    assert accepted.manifest.questions[0].edit.blocks[0].explanation == "편집한 설명"
    assert concepts.source_authority.call_args.args == (
        actor,
        command.source_binding_id,
        edit["concept_task_id"],
    )
    reader.side_effect = KakaoArchiveError("KAKAO_CONCEPT_KNOWLEDGE_FORBIDDEN")
    with pytest.raises(KakaoArchiveError, match="KNOWLEDGE_FORBIDDEN"):
        service.get_study(actor, command.source_binding_id, saved.study.study_id)


def test_study_migration_roundtrip_refuses_history_in_rollback_only_schema(
    study_store, monkeypatch
):
    engine = study_store[0]
    first, key = save(study_store)
    schema = "test_kakao_study_" + uuid4().hex
    path = (
        Path(__file__).resolve().parents[2]
        / "migrations/versions/20261117_0095_kakao_saved_studies.py"
    )
    spec = importlib.util.spec_from_file_location("saved_study_migration_test", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.connect() as connection:
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
                    text("SELECT to_regclass(:name)"), dict(name=schema + ".kakao_studies")
                )
                is None
            )
            migration.upgrade()
            columns = (
                "command_id,owner_operator_id,source_binding_id,idempotency_key,request_sha256,"
                "study_id,study_revision_id,previous_revision_id,expected_version,state,"
                "reserved_at,completed_at"
            )
            connection.execute(
                text(
                    f"INSERT INTO {schema}.kakao_study_commands ({columns}) "
                    f"SELECT {columns} FROM app.kakao_study_commands "
                    "WHERE owner_operator_id=:owner AND idempotency_key=:key"
                ),
                dict(owner=study_store[1].operator_id, key=key),
            )
            with (
                pytest.raises(DBAPIError, match="HISTORY_REQUIRES_REVIEW"),
                connection.begin_nested(),
            ):
                migration.downgrade()
            assert connection.scalar(text("SELECT version_num FROM app.alembic_version")) == head
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM app.kakao_studies WHERE study_id=:study"),
                    dict(study=first.study.study_id),
                )
                == 1
            )
        finally:
            transaction.rollback()
