"""Stored edits→real child renderer→Artifact/download. Synthetic chats, not live acceptance."""

import importlib.util
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pymupdf
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from eom_catalog_contracts.kakao_concept_knowledge import KakaoConceptResultPin
from eom_catalog_contracts.kakao_export_store import KakaoExportCreate, KakaoExportProfile
from eom_catalog_contracts.kakao_study_export import KakaoStudyExportCreate, KakaoStudyExportPin
from eom_catalog_contracts.kakao_study_store import KakaoStudyCreate
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_delivery_application import KakaoDeliveryApplication
from eom_catalog_service.kakao_export_models import KakaoExportStudyRecord
from eom_catalog_service.kakao_export_service import KakaoExportService
from eom_catalog_service.kakao_pdf_delivery import KakaoPdfDelivery
from eom_identifiers import sha256_bytes
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.integration.test_kakao_packet_storage import packet_store as packet_store
from tests.integration.test_kakao_question_storage import question_store as question_store
from tests.integration.test_kakao_source_storage import source_store as source_store
from tests.integration.test_kakao_stored_student_pdf import RELEASE, RenderProcess, font
from tests.integration.test_kakao_study_storage import revised
from tests.integration.test_kakao_study_storage import study_store as study_store

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


class FinishedRenderProcess(RenderProcess):
    def __init__(self):
        super().__init__()
        self.finished = set()

    def run(self, command, workspace):
        super().run(command, workspace)  # Returns only after the real child was reaped.
        self.finished.add(command.execution.attempt_id)

    def assert_stopped(self, command, _workspace):
        assert command.execution.attempt_id in self.finished


@pytest.fixture
def study_export_store(study_store, tmp_path):
    engine, actor, studies, original, *_ = study_store
    saved = studies.save_study(actor, original, idempotency_key="export-study-" + uuid4().hex).study
    font_path, member = font(tmp_path)
    profile = KakaoExportProfile(
        renderer_release_sha256=RELEASE,
        font_sha256=member.sha256,
        font_size_bytes=member.size_bytes,
        layout_policy="student-study-a4/1.0",
    )
    exports = KakaoExportService(
        engine,
        artifacts=studies.artifacts,
        packets=studies.packets,
        sources=studies.sources,
        profile=profile,
        studies=studies,
    )
    request = KakaoStudyExportCreate(
        source_binding_id=saved.source_binding_id,
        study=KakaoStudyExportPin(
            study_id=saved.study_id,
            study_revision_id=saved.study_revision_id,
            manifest_sha256=saved.manifest.sha256,
        ),
    )
    inputs = studies.artifacts.settings.staging_root / ("study-pdf-" + uuid4().hex)
    inputs.mkdir(mode=0o700)
    workspaces = tmp_path / "workspaces"
    workspaces.mkdir(mode=0o700)
    launcher = FinishedRenderProcess()
    delivery = KakaoPdfDelivery(
        exports,
        studies.artifacts,
        inputs,
        workspaces,
        font_path,
        member,
        os.geteuid(),
        os.getgid(),
        launcher,
        launcher.assert_stopped,
        studies,
    )
    return engine, actor, studies, exports, delivery, request, saved, original, launcher


def test_saved_edit_to_real_pdf_reopen_download_and_completed_replay(
    study_export_store, monkeypatch
):
    engine, actor, studies, exports, delivery, request, saved, original, launcher = (
        study_export_store
    )
    wakeup = Mock()
    application = KakaoDeliveryApplication(studies.packets, exports, wakeup, studies)
    key = "study-pdf-build-" + uuid4().hex
    accepted = application.request_study_export(actor, request, idempotency_key=key)
    export_id = accepted.result.export.export_id
    assert accepted.result.study == request.study and not accepted.replayed
    assert wakeup.call_args.args == (actor, request.source_binding_id, export_id)
    completed = delivery.run(actor, request.source_binding_id, export_id)
    assert completed.state == "COMPLETED" and completed.page_count >= 2 and launcher.calls == 1
    view = exports.read_study_export(actor, request.source_binding_id, export_id)
    assert view.study == request.study and view.export == completed
    opened = exports.open_pdf(
        actor, request.source_binding_id, export_id, revision_id=completed.export_revision_id
    )
    with opened.stream as stream:
        raw = stream.read()
    assert sha256_bytes(raw) == completed.pdf.sha256
    with pymupdf.open(stream=raw, filetype="pdf") as pdf:
        text = "\n".join(page.get_text() for page in pdf)
        assert "복습 개념" in text and "원래 질문·답변은 그대로 보관합니다." in text
        assert "직접 작성한 설명" in text
    import eom_catalog_service.kakao_pdf_delivery as module

    monkeypatch.setattr(
        module, "prepare_kakao_pdf_inputs", Mock(side_effect=AssertionError("must not re-render"))
    )
    wakeup.reset_mock()
    assert (
        application.request_study_export(actor, request, idempotency_key=key).result.export
        == completed
    )
    wakeup.assert_not_called()
    assert delivery.run(actor, request.source_binding_id, export_id) == completed
    assert launcher.calls == 1
    changed = studies.save_study(
        actor, revised(original, saved), idempotency_key="next-study-version-" + uuid4().hex
    ).study
    assert changed.study_revision_id != saved.study_revision_id
    assert (
        exports.read_study_export(actor, request.source_binding_id, export_id).study
        == request.study
    )
    with Session(engine) as session:
        link = session.get(KakaoExportStudyRecord, export_id)
        assert link.study_revision_id == saved.study_revision_id


def test_concurrent_aliases_share_one_study_export_and_claim(study_export_store):
    engine, actor, _studies, exports, _delivery, request, *_ = study_export_store
    barrier = Barrier(2)

    def create(_):
        barrier.wait()
        return exports.request_study_export(
            actor, request, idempotency_key="alias-study-" + uuid4().hex
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(create, range(2)))
    ids = {result.result.export.export_id for result in results}
    assert len(ids) == 1
    export_id = next(iter(ids))
    barrier = Barrier(2)

    def claim(_):
        barrier.wait()
        return exports.claim_export(actor, request.source_binding_id, export_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = tuple(pool.map(claim, range(2)))
    assert sum(claim.acquired for claim in claims) == 1
    assert claims[0].execution == claims[1].execution
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(KakaoExportStudyRecord)
                .where(KakaoExportStudyRecord.export_id == export_id)
            )
            == 1
        )


def test_changed_hash_conflict_and_link_immutability(study_export_store):
    engine, actor, _studies, exports, _delivery, request, *_ = study_export_store
    bad = request.model_copy(
        update={"study": request.study.model_copy(update={"manifest_sha256": "sha256:" + "b" * 64})}
    )
    with pytest.raises(KakaoArchiveError, match="SOURCE_CHANGED"):
        exports.request_study_export(actor, bad, idempotency_key="bad-hash-" + uuid4().hex)
    key = "original-study-export-" + uuid4().hex
    accepted = exports.request_study_export(actor, request, idempotency_key=key)
    with pytest.raises(KakaoArchiveError, match="IDEMPOTENCY_CONFLICT"):
        exports.request_study_export(actor, bad, idempotency_key=key)
    with pytest.raises(DBAPIError), Session(engine) as session, session.begin():
        session.execute(
            update(KakaoExportStudyRecord)
            .where(KakaoExportStudyRecord.export_id == accepted.result.export.export_id)
            .values(manifest_sha256="sha256:" + "c" * 64)
        )


def test_selected_textbook_crop_survives_full_saved_pdf_pipeline(study_export_store, monkeypatch):
    """Actual crop/child/PDF/Artifact; completed concept and Graph source reader are synthetic."""
    import eom_catalog_service.kakao_study_pdf_inputs as adapter
    import eom_catalog_service.kakao_study_service as owner
    from eom_catalog_service.kakao_concept_pages import (
        prepare_kakao_concept_captures,
        prepare_kakao_concept_pages,
    )
    from eom_catalog_service.kakao_concept_study import (
        KakaoPreparedConceptStudy,
        project_kakao_concept_supplements,
    )
    from eom_kakao_archive_contracts.concepts import (
        ConceptComposition,
        parse_concept_request,
        validate_concept_result,
    )

    from tests.unit.test_kakao_concept_contracts import composed, plan, plan_request, result
    from tests.unit.test_kakao_concept_pages import knowledge

    _engine, actor, studies, exports, delivery, _request, _saved, original, launcher = (
        study_export_store
    )
    _packet, selection = studies.packets.resolve_student(
        actor,
        original.source_binding_id,
        original.packet_id,
        revision_id=original.packet_revision_id,
        student_id=original.student_id,
    )
    question = selection.questions[0].stored
    task = "kakaoconcepttask_" + uuid4().hex
    pin = KakaoConceptResultPin(
        workflow_id="workflow_" + uuid4().hex,
        step_run_id="steprun_" + uuid4().hex,
        job_id="job_" + uuid4().hex,
        artifact_id="artifact_" + uuid4().hex,
        artifact_revision_id="rev_" + uuid4().hex,
        sha256="sha256:" + "d" * 64,
    )
    body = composed()
    body["blocks"][0]["citations"] = [dict(evidence_key="E1", passage_key=None, quote=None)]
    body["blocks"][0]["captures"][0]["page_key"] = "E1P1"
    completed = SimpleNamespace(
        work=SimpleNamespace(
            question_revision_id=question.question_revision_id, question_manifest=question.manifest
        ),
        pin=pin,
        result=SimpleNamespace(
            output=SimpleNamespace(output=ConceptComposition.model_validate(body))
        ),
    )
    monkeypatch.setattr(owner, "read_kakao_concept_phase_result", Mock(return_value=completed))
    command = original.model_dump(mode="json")
    command["questions"][0].update(
        concept_task_id=task,
        blocks=[
            dict(block_index=0, title=None, relevance=None, explanation=None, capture_indices=[0])
        ],
    )
    saved = studies.save_study(
        actor, KakaoStudyCreate.model_validate(command), idempotency_key="crop-study-" + uuid4().hex
    ).study
    request = KakaoStudyExportCreate(
        source_binding_id=saved.source_binding_id,
        study=KakaoStudyExportPin(
            study_id=saved.study_id,
            study_revision_id=saved.study_revision_id,
            manifest_sha256=saved.manifest.sha256,
        ),
    )
    source, png = knowledge()

    def prepare(_authority, *, source_root, output_root):
        # Only the textbook reader is a fixture port. The worker still reads staged local files.
        reader = Mock()
        reader.settings = studies.artifacts.settings
        reader.read_member.return_value = png

        def authorize():
            studies.get_study(
                actor, saved.source_binding_id, saved.study_id, revision_id=saved.study_revision_id
            )

        pages = prepare_kakao_concept_pages(
            reader, knowledge=source, source_root=source_root, authorize=authorize
        )
        value = plan_request().model_dump(mode="json")
        value.update(
            task_id=task,
            phase="COMPOSE",
            plan=plan(),
            context=pages.context.model_dump(mode="json"),
        )
        value["question"].update(
            question_revision_id=question.question_revision_id,
            question_manifest_sha256=question.manifest.sha256,
        )
        asked = parse_concept_request(value)
        answer = validate_concept_result(asked, result(asked, body))
        captures = prepare_kakao_concept_captures(
            reader,
            prepared=pages,
            request=asked,
            result=answer,
            output_root=output_root,
            authorize=authorize,
        )
        supplements = project_kakao_concept_supplements(
            prepared=pages, request=asked, result=answer, captures=captures
        )
        return KakaoPreparedConceptStudy(
            task, question.question_revision_id, pin, supplements, captures, output_root
        )

    prepare_spy = Mock(side_effect=prepare)
    monkeypatch.setattr(adapter, "prepare_kakao_concept_study", prepare_spy)
    accepted = exports.request_study_export(
        actor, request, idempotency_key="crop-export-" + uuid4().hex
    )
    done = delivery.run(actor, request.source_binding_id, accepted.result.export.export_id)
    assert done.state == "COMPLETED" and launcher.calls == 1 and prepare_spy.call_count == 1
    opened = exports.open_pdf(
        actor, request.source_binding_id, done.export_id, revision_id=done.export_revision_id
    )
    with opened.stream as stream:
        raw = stream.read()
    with pymupdf.open(stream=raw, filetype="pdf") as pdf:
        text = "\n".join(page.get_text() for page in pdf)
        assert "검증 교과서" in text and "물리 페이지 1" in text and "AI 작성 초안" in text
        assert sum(len(page.get_image_info()) for page in pdf) == 1
    worker_images = [
        path
        for path in delivery.workspace_root.rglob("*.png")
        if path.parent.name == "study-images"
    ]
    assert len(worker_images) == 1
    assert not any(path.name == "pages" for path in delivery.workspace_root.rglob("*"))
    assert delivery.run(actor, request.source_binding_id, done.export_id) == done
    assert launcher.calls == 1 and prepare_spy.call_count == 1


def test_current_study_source_rejection_blocks_download_not_history(
    study_export_store, monkeypatch
):
    _, actor, studies, exports, delivery, request, *_rest, launcher = study_export_store
    accepted = exports.request_study_export(
        actor, request, idempotency_key="permission-pdf-" + uuid4().hex
    )
    completed = delivery.run(actor, request.source_binding_id, accepted.result.export.export_id)
    assert completed.state == "COMPLETED"
    with monkeypatch.context() as scoped:
        scoped.setattr(
            studies,
            "get_study",
            Mock(side_effect=KakaoArchiveError("KAKAO_CONCEPT_KNOWLEDGE_FORBIDDEN")),
        )
        with pytest.raises(KakaoArchiveError, match="KNOWLEDGE_FORBIDDEN"):
            exports.open_pdf(
                actor,
                request.source_binding_id,
                completed.export_id,
                revision_id=completed.export_revision_id,
            )
    assert exports.get_export(actor, request.source_binding_id, completed.export_id) == completed
    assert launcher.calls == 1


def test_another_student_export_cannot_receive_this_study_link(study_export_store):
    engine, actor, studies, exports, _delivery, request, saved, original, _launcher = (
        study_export_store
    )
    packet = studies.packets.get_packet(
        actor,
        original.source_binding_id,
        original.packet_id,
        revision_id=original.packet_revision_id,
    )
    other = next(
        q.student.student_id
        for q in packet.packet.questions
        if q.student.student_id != original.student_id
    )
    plain = exports.request_export(
        actor,
        KakaoExportCreate(
            source_binding_id=original.source_binding_id,
            packet_id=original.packet_id,
            packet_revision_id=original.packet_revision_id,
            student_id=other,
        ),
        idempotency_key="other-student-output-" + uuid4().hex,
    ).export
    with (
        pytest.raises(DBAPIError, match="STUDY_EXPORT_INITIAL_INVALID"),
        Session(engine) as session,
        session.begin(),
    ):
        session.add(
            KakaoExportStudyRecord(
                export_id=plain.export_id,
                owner_operator_id=actor.operator_id,
                source_binding_id=request.source_binding_id,
                study_id=saved.study_id,
                study_revision_id=saved.study_revision_id,
                manifest_sha256=saved.manifest.sha256,
            )
        )
        session.flush()
    assert exports.study_reference(actor, request.source_binding_id, plain.export_id) is None


def test_link_migration_empty_roundtrip_and_history_refusal(study_export_store, monkeypatch):
    engine, actor, _studies, exports, _delivery, request, *_ = study_export_store
    accepted = exports.request_study_export(
        actor, request, idempotency_key="link-migration-" + uuid4().hex
    )
    schema = "test_kakao_export_study_" + uuid4().hex
    path = (
        Path(__file__).resolve().parents[2]
        / "migrations/versions/20261117_0096_kakao_study_exports.py"
    )
    spec = importlib.util.spec_from_file_location("study_export_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            head = connection.scalar(text("SELECT version_num FROM app.alembic_version"))
            connection.execute(text(f"CREATE SCHEMA {schema}"))
            connection.execute(text(f"SET LOCAL search_path TO {schema},app"))
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            migration.downgrade()
            migration.upgrade()
            connection.execute(
                text(
                    f"INSERT INTO {schema}.kakao_export_studies "
                    "SELECT * FROM app.kakao_export_studies WHERE export_id=:export"
                ),
                dict(export=accepted.result.export.export_id),
            )
            with (
                pytest.raises(DBAPIError, match="HISTORY_REQUIRES_REVIEW"),
                connection.begin_nested(),
            ):
                migration.downgrade()
            assert connection.scalar(text("SELECT version_num FROM app.alembic_version")) == head
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM app.kakao_export_studies WHERE export_id=:export"),
                    dict(export=accepted.result.export.export_id),
                )
                == 1
            )
        finally:
            transaction.rollback()
