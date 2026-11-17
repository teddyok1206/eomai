"""Actual persisted export/claim/download; synthetic sources, not live Kakao."""

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from uuid import uuid4

import pymupdf
import pytest
from eom_catalog_contracts.kakao_export_store import KakaoExportCreate, KakaoExportProfile
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_export_models import (
    KakaoExportAttemptRecord,
    KakaoExportRecord,
    KakaoExportRequestRecord,
)
from eom_catalog_service.kakao_export_service import KakaoExportService
from eom_catalog_service.kakao_pdf_inputs import prepare_kakao_pdf_inputs
from eom_catalog_service.kakao_pdf_publication import publish_kakao_pdf
from eom_identity_service.models import ApiSessionRecord
from eom_kakao_archive_contracts import RenderCommand, canonical_bytes
from eom_kakao_archive_contracts.study import StudyRenderCommand, StudyRenderManifest
from eom_orchestrator.kakao_pdf_execution import KakaoPdfExecutor
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.integration.test_kakao_archive_storage import make_actor
from tests.integration.test_kakao_packet_storage import packet_store as packet_store
from tests.integration.test_kakao_question_storage import question_store as question_store
from tests.integration.test_kakao_source_storage import source_store as source_store
from tests.integration.test_kakao_stored_student_pdf import (
    RELEASE,
    RenderProcess,
    current_authorizer,
    font,
)

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture(params=("student-question-a4/1.0", "student-study-a4/1.0"))
def export_store(request, packet_store, tmp_path):
    layout_policy = request.param
    engine, actor, packets, packet_request, selected, _questions, sources, artifacts = packet_store
    saved = packets.save_packet(
        actor, packet_request, idempotency_key="export-packet-" + uuid4().hex
    )
    font_path, member = font(tmp_path)
    profile = KakaoExportProfile(
        renderer_release_sha256=RELEASE,
        font_sha256=member.sha256,
        font_size_bytes=member.size_bytes,
        layout_policy=layout_policy,
    )
    service = KakaoExportService(
        engine, artifacts=artifacts, packets=packets, sources=sources, profile=profile
    )
    command = KakaoExportCreate(
        source_binding_id=packet_request.source_binding_id,
        packet_id=saved.packet.packet_id,
        packet_revision_id=saved.packet.packet_revision_id,
        student_id=selected[0].student.student_id,
    )
    return engine, actor, service, command, packets, sources, artifacts, profile, font_path, member


def render_export(store, tmp_path):
    engine, actor, service, request, _packets, sources, artifacts, _profile, font_path, member = (
        store
    )
    accepted = service.request_export(
        actor, request, idempotency_key="render-export-" + uuid4().hex
    ).export
    claim = service.claim_export(actor, request.source_binding_id, accepted.export_id)
    assert claim.acquired
    _, packet, selected = service.resolve_inputs(
        actor, request.source_binding_id, accepted.export_id
    )
    root = artifacts.settings.staging_root / ("export-input-" + uuid4().hex)
    root.mkdir(mode=0o700)
    prepared = prepare_kakao_pdf_inputs(
        artifacts,
        packet=packet,
        selection=selected,
        student_id=request.student_id,
        source_root=root,
        font_source=font_path,
        font=member,
        authorize=current_authorizer(engine, actor, sources, packet, selected),
        layout_policy=claim.export.profile.layout_policy,
    )
    fields = dict(
        execution=claim.execution.model_dump(mode="json"),
        export_id=accepted.export_id,
        source_binding_id=request.source_binding_id,
        packet_revision_id=request.packet_revision_id,
        student_id=request.student_id,
        subset_sha256=prepared.manifest.subset_sha256,
        mode=accepted.mode,
        renderer_release_sha256=RELEASE,
        layout_policy=claim.export.profile.layout_policy,
        manifest=prepared.manifest_member,
        font=prepared.font_member,
    )
    if isinstance(prepared.manifest, StudyRenderManifest):
        command = StudyRenderCommand.model_validate(
            fields | dict(schema_version="kakao-study-render/1.0", study_revision_id=None)
        )
    else:
        command = RenderCommand.model_validate(
            fields | dict(schema_version="kakao-question-render/1.0")
        )
    service.bind_command(actor, request.source_binding_id, accepted.export_id, command)

    def authorize():
        service.check_attempt(
            actor, request.source_binding_id, accepted.export_id, command, packet, selected
        )

    worker_root = tmp_path / ("export-worker-" + uuid4().hex)
    worker_root.mkdir(mode=0o700)
    launcher = RenderProcess()
    executor = KakaoPdfExecutor(
        worker_root, os.getuid(), os.getgid(), launcher, lambda _: authorize()
    )
    output = executor.execute(command, source_root=root)
    publication = publish_kakao_pdf(
        artifacts,
        command=command,
        manifest_bytes=(root / "manifest.json").read_bytes(),
        accepted=output,
        authorize=authorize,
    )
    return accepted, command, publication, launcher


def test_request_alias_restart_and_profile_change(export_store):
    engine, actor, service, command, packets, sources, artifacts, profile, *_ = export_store
    key = "export-request-" + uuid4().hex
    first = service.request_export(actor, command, idempotency_key=key)
    assert first.export.state == "PENDING" and not first.replayed
    restarted = KakaoExportService(
        engine, artifacts=artifacts, packets=packets, sources=sources, profile=profile
    )
    assert restarted.request_export(actor, command, idempotency_key=key).export == first.export
    alias = restarted.request_export(actor, command, idempotency_key="alias-" + uuid4().hex)
    assert alias.replayed and alias.export == first.export
    changed = KakaoExportService(
        engine,
        artifacts=artifacts,
        packets=packets,
        sources=sources,
        profile=profile.model_copy(update={"renderer_release_sha256": "sha256:" + "b" * 64}),
    )
    assert changed.request_export(actor, command, idempotency_key=key).export == first.export
    assert (
        changed.request_export(
            actor, command, idempotency_key="new-runtime-" + uuid4().hex
        ).export.export_id
        != first.export.export_id
    )
    with pytest.raises(KakaoArchiveError, match="RUNTIME_MISMATCH"):
        changed.claim_export(actor, command.source_binding_id, first.export.export_id)
    with pytest.raises(KakaoArchiveError, match="IDEMPOTENCY_CONFLICT"):
        service.request_export(
            actor,
            command.model_copy(update={"student_id": "kakaostudent_" + uuid4().hex}),
            idempotency_key=key,
        )


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_request_and_claim_single_winner(export_store, same_key):
    engine, actor, service, command, *_ = export_store
    barrier, key = Barrier(2), "concurrent-export-" + uuid4().hex

    def request(index):
        barrier.wait(timeout=20)
        return service.request_export(
            actor, command, idempotency_key=key if same_key else key + str(index)
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        one, two = list(pool.map(request, range(2)))
    assert one.export == two.export and sum(value.replayed for value in (one, two)) == 1
    barrier = Barrier(2)

    def claim(_):
        barrier.wait(timeout=20)
        return service.claim_export(actor, command.source_binding_id, one.export.export_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(claim, range(2)))
    assert sum(value.acquired for value in claimed) == 1
    assert claimed[0].execution == claimed[1].execution
    with Session(engine) as session:
        assert (
            len(
                session.scalars(
                    select(KakaoExportAttemptRecord).where(
                        KakaoExportAttemptRecord.export_id == one.export.export_id
                    )
                ).all()
            )
            == 1
        )


def test_actual_pdf_adoption_restart_authorized_download_no_rerender(export_store, tmp_path):
    engine, actor, _service, request, packets, sources, artifacts, profile, *_ = export_store
    accepted, command, publication, launcher = render_export(export_store, tmp_path)
    restarted = KakaoExportService(
        engine, artifacts=artifacts, packets=packets, sources=sources, profile=profile
    )
    # Resume only adoption after committed publication, not another render.
    result = restarted.complete_export(
        actor, request.source_binding_id, accepted.export_id, command, publication
    )
    assert result.state == "COMPLETED" and result.page_count == 1
    assert (
        restarted.complete_export(
            actor, request.source_binding_id, result.export_id, command, publication
        )
        == result
    )
    assert restarted.get_export(actor, request.source_binding_id, result.export_id) == result
    assert restarted.list_exports(actor, request.source_binding_id).items == (result,)
    replay = restarted.request_export(
        actor, request, idempotency_key="after-completed-" + uuid4().hex
    )
    assert replay.replayed and replay.export == result
    assert not restarted.claim_export(actor, request.source_binding_id, result.export_id).acquired
    for _ in range(2):
        opened = restarted.open_pdf(
            actor,
            request.source_binding_id,
            result.export_id,
            revision_id=result.export_revision_id,
        )
        with opened.stream as stream:
            raw = stream.read()
        with pymupdf.open(stream=raw, filetype="pdf") as pdf:
            assert len(pdf) == 1 and "second student" not in pdf[0].get_text()
    assert launcher.calls == 1
    with pytest.raises(KakaoArchiveError, match="NOT_COMPLETED"):
        restarted.open_pdf(
            actor,
            request.source_binding_id,
            result.export_id,
            revision_id="kakaoexportrev_" + uuid4().hex,
        )
    with pytest.raises(KakaoArchiveError, match="RESOURCE_NOT_FOUND"):
        restarted.get_export(make_actor(engine), request.source_binding_id, result.export_id)
    with Session(engine) as session, session.begin():
        session.execute(
            update(ApiSessionRecord)
            .where(ApiSessionRecord.api_session_id == actor.session_id)
            .values(revoked_at=result.completed_at)
        )
    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        restarted.open_pdf(
            actor,
            request.source_binding_id,
            result.export_id,
            revision_id=result.export_revision_id,
        )


def test_failure_is_immutable_retry_explicit_and_uncertain_process_never_reclaimed(export_store):
    engine, actor, service, request, *_ = export_store
    requested = service.request_export(
        actor, request, idempotency_key="failed-export-" + uuid4().hex
    ).export
    claim = service.claim_export(actor, request.source_binding_id, requested.export_id)
    with pytest.raises(KakaoArchiveError, match="RETRY_DENIED"):
        service.claim_export(
            actor,
            request.source_binding_id,
            requested.export_id,
            retry_failed_attempt_id=claim.execution.attempt_id,
        )

    def uncertain(_):
        raise RuntimeError("stopping not confirmed")

    with pytest.raises(RuntimeError, match="not confirmed"):
        service.fail_attempt(
            actor,
            request.source_binding_id,
            requested.export_id,
            claim.execution,
            error_code="KAKAO_PDF_WORKER_FAILED",
            assert_stopped=uncertain,
        )
    assert (
        service.get_export(actor, request.source_binding_id, requested.export_id).state == "RUNNING"
    )
    failed = service.fail_attempt(
        actor,
        request.source_binding_id,
        requested.export_id,
        claim.execution,
        error_code="KAKAO_PDF_WORKER_FAILED",
        assert_stopped=lambda _: None,
    )
    assert failed.state == "FAILED"
    assert not service.claim_export(actor, request.source_binding_id, requested.export_id).acquired
    retry = service.claim_export(
        actor,
        request.source_binding_id,
        requested.export_id,
        retry_failed_attempt_id=claim.execution.attempt_id,
    )
    assert retry.acquired and retry.execution.fence == 2
    assert not service.claim_export(
        actor,
        request.source_binding_id,
        requested.export_id,
        retry_failed_attempt_id=claim.execution.attempt_id,
    ).acquired
    with Session(engine) as session:
        old = session.get(KakaoExportAttemptRecord, claim.execution.attempt_id)
        assert old.state == "FAILED" and old.completed_at == failed.completed_at
    with Session(engine) as session, pytest.raises(DBAPIError, match="ATTEMPT_IMMUTABLE"):
        session.execute(
            update(KakaoExportAttemptRecord)
            .where(KakaoExportAttemptRecord.attempt_id == claim.execution.attempt_id)
            .values(state="RUNNING", completed_at=None, error_code=None)
        )
        session.commit()


def test_changed_command_and_forged_publication_rejected(export_store, tmp_path):
    _, actor, service, request, *_ = export_store
    accepted, command, publication, launcher = render_export(export_store, tmp_path)
    with pytest.raises(KakaoArchiveError, match="EXECUTION_MISMATCH"):
        service.bind_command(
            actor,
            request.source_binding_id,
            accepted.export_id,
            command.model_copy(update={"student_id": "kakaostudent_" + uuid4().hex}),
        )
    bad = replace(
        publication, pdf=publication.pdf.model_copy(update={"sha256": "sha256:" + "0" * 64})
    )
    with pytest.raises(KakaoArchiveError, match="ADMISSION_EVIDENCE_INVALID"):
        service.complete_export(actor, request.source_binding_id, accepted.export_id, command, bad)
    assert (
        service.get_export(actor, request.source_binding_id, accepted.export_id).state == "RUNNING"
    )
    assert (
        service.complete_export(
            actor, request.source_binding_id, accepted.export_id, command, publication
        ).state
        == "COMPLETED"
    )
    assert launcher.calls == 1


def test_revocation_during_file_open_closes_descriptor(export_store, tmp_path, monkeypatch):
    engine, actor, service, request, _packets, _sources, artifacts, *_ = export_store
    accepted, command, publication, _ = render_export(export_store, tmp_path)
    done = service.complete_export(
        actor, request.source_binding_id, accepted.export_id, command, publication
    )
    original, descriptors = artifacts.open_verified_member, []

    def revoked(**kwargs):
        opened = original(**kwargs)
        if kwargs.get("media_type") == "application/pdf":
            descriptors.append(opened)
            with Session(engine) as session, session.begin():
                session.execute(
                    update(ApiSessionRecord)
                    .where(ApiSessionRecord.api_session_id == actor.session_id)
                    .values(revoked_at=done.completed_at)
                )
        return opened

    monkeypatch.setattr(artifacts, "open_verified_member", revoked)
    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        service.open_pdf(
            actor,
            request.source_binding_id,
            accepted.export_id,
            revision_id=done.export_revision_id,
        )
    assert len(descriptors) == 1 and descriptors[0].stream.closed


def test_no_large_payloads_and_immutable_request_alias(export_store):
    engine, actor, service, command, *_ = export_store
    key = "small-request-" + uuid4().hex
    result = service.request_export(actor, command, idempotency_key=key)
    with Session(engine) as session:
        row = session.get(KakaoExportRecord, result.export.export_id)
        assert len(canonical_bytes(row.profile)) < 1024
        assert not {"text", "body", "photos", "pdf", "messages", "question_content"} & set(
            row.__table__.columns.keys()
        )
    with Session(engine) as session, pytest.raises(DBAPIError):
        session.execute(
            update(KakaoExportRequestRecord)
            .where(KakaoExportRequestRecord.idempotency_key == key)
            .values(request_sha256="sha256:" + "0" * 64)
        )
        session.commit()


def test_export_page_and_build_lookup_have_dedicated_btree_access(export_store):
    engine, actor, service, command, *_ = export_store
    saved = service.request_export(actor, command, idempotency_key="plan-" + uuid4().hex).export
    with Session(engine) as session, session.begin():
        row = session.get(KakaoExportRecord, saved.export_id)
        session.execute(text("SET LOCAL enable_seqscan = off"))
        page_plan = (
            session.execute(
                text(
                    "EXPLAIN SELECT export_id FROM kakao_exports WHERE owner_operator_id = :owner "
                    "AND source_binding_id = :binding ORDER BY export_id LIMIT 51"
                ),
                {"owner": actor.operator_id, "binding": command.source_binding_id},
            )
            .scalars()
            .all()
        )
        build_plan = (
            session.execute(
                text(
                    "EXPLAIN SELECT export_id FROM kakao_exports WHERE owner_operator_id = :owner "
                    "AND build_sha256 = :build"
                ),
                {"owner": actor.operator_id, "build": row.build_sha256},
            )
            .scalars()
            .all()
        )
        build_index = session.scalar(
            text(
                "SELECT indexdef FROM pg_indexes WHERE schemaname = current_schema() "
                "AND indexname = 'uq_kakao_export_build'"
            )
        )
    assert any("uq_kakao_export_owner" in line for line in page_plan)
    # Tiny per-owner fixtures may make the owner index cheaper than the build index.
    # Verify actual indexed lookup and the exact unique build index, not a forced planner choice.
    assert any("Index" in line for line in build_plan)
    assert not any("Seq Scan" in line for line in build_plan)
    assert "USING btree (owner_operator_id, build_sha256)" in build_index


def test_changed_output_policy_preserves_old_intent_and_reads_mixed_history(export_store):
    engine, actor, service, command, packets, sources, artifacts, profile, *_ = export_store
    key = "exact-policy-export-" + uuid4().hex
    old = service.request_export(actor, command, idempotency_key=key).export
    opposite = (
        "student-study-a4/1.0"
        if profile.layout_policy == "student-question-a4/1.0"
        else "student-question-a4/1.0"
    )
    next_service = KakaoExportService(
        engine,
        artifacts=artifacts,
        packets=packets,
        sources=sources,
        profile=profile.model_copy(update={"layout_policy": opposite}),
    )
    assert next_service.request_export(actor, command, idempotency_key=key).export == old
    new = next_service.request_export(
        actor, command, idempotency_key="new-policy-" + uuid4().hex
    ).export
    assert new.export_id != old.export_id and new.schema_version != old.schema_version
    page = next_service.list_exports(actor, command.source_binding_id)
    assert page.schema_version == "kakao-export-page/2.0" and set(page.items) == {old, new}
    with pytest.raises(KakaoArchiveError, match="RUNTIME_MISMATCH"):
        next_service.claim_export(actor, command.source_binding_id, old.export_id)


@pytest.mark.parametrize("export_store", ["student-study-a4/1.0"], indirect=True)
def test_unsaved_study_revision_cannot_be_bound_to_original_question_export(export_store):
    engine, actor, service, request, _, _, _, profile, _, font = export_store
    saved = service.request_export(
        actor, request, idempotency_key="unbound-study-" + uuid4().hex
    ).export
    claim = service.claim_export(actor, request.source_binding_id, saved.export_id)
    command = StudyRenderCommand.model_validate(
        dict(
            schema_version="kakao-study-render/1.0",
            execution=claim.execution,
            export_id=saved.export_id,
            source_binding_id=saved.source_binding_id,
            packet_revision_id=saved.packet_revision_id,
            student_id=saved.student_id,
            study_revision_id="kakaostudyrev_" + uuid4().hex,
            subset_sha256=saved.subset_sha256,
            mode=saved.mode,
            renderer_release_sha256=profile.renderer_release_sha256,
            layout_policy=profile.layout_policy,
            font=font,
            manifest=dict(
                relative_path="manifest.json",
                sha256="sha256:" + "a" * 64,
                size_bytes=1,
                media_type="application/json",
            ),
        )
    )
    with pytest.raises(KakaoArchiveError, match="EXECUTION_MISMATCH"):
        service.bind_command(actor, request.source_binding_id, saved.export_id, command)
    with Session(engine) as session:
        assert session.get(KakaoExportAttemptRecord, claim.execution.attempt_id).command is None
