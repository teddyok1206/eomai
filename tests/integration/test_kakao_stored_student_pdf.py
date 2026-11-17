"""Real stored CSV/photos→question→packet→worker→Artifact, not a live Kakao/Studio claim."""

import os
import subprocess
from datetime import date
from pathlib import Path
from uuid import uuid4

import pymupdf
import pytest
from eom_catalog_contracts.kakao_packet_store import KakaoPacketCreate
from eom_catalog_contracts.kakao_question import KakaoQuestionProvenance
from eom_catalog_service.kakao_archive_authorization import (
    authorize_kakao_binding_scope,
)
from eom_catalog_service.kakao_packet_service import KakaoPacketService
from eom_catalog_service.kakao_pdf_inputs import prepare_kakao_pdf_inputs
from eom_catalog_service.kakao_pdf_publication import publish_kakao_pdf
from eom_catalog_service.kakao_source_pointers import validate_source_pointer_metadata_batch
from eom_catalog_service.kakao_study_projection import project_kakao_student_study
from eom_identity_service.models import ApiSessionRecord
from eom_kakao_archive_contracts import LocalMember, RenderCommand, canonical_bytes, sha256
from eom_kakao_archive_contracts.study import StudyRenderCommand, StudyRenderManifest
from eom_kakao_archive_contracts.study_layout import StudyLayoutReceipt
from eom_operator_identity import PermissionKey
from eom_orchestrator.kakao_pdf_execution import KakaoPdfExecutor
from sqlalchemy import update
from sqlalchemy.orm import Session

from tests.integration.test_kakao_packet_storage import packet_store as packet_store
from tests.integration.test_kakao_question_refresh_storage import refresh_case as refresh_case
from tests.integration.test_kakao_question_refresh_storage import refresh_command
from tests.integration.test_kakao_question_storage import change_command
from tests.integration.test_kakao_question_storage import question_store as question_store
from tests.integration.test_kakao_source_storage import source_store as source_store

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
RENDER_PYTHON = Path("/opt/eom/conda/envs/eom-kakao-pdf/bin/python")
RELEASE = "sha256:" + "a" * 64
ROOT = Path(__file__).resolve().parents[2]


class RenderProcess:
    """Same-user real subprocess. This is not privileged sandbox acceptance."""

    def __init__(self):
        self.calls = 0

    def run(self, command, workspace):
        self.calls += 1
        result = subprocess.run(
            [
                str(RENDER_PYTHON),
                "-B",
                "-m",
                "eom_kakao_archive_worker.cli",
                "--input-root",
                str(workspace / "input"),
                "--output-root",
                str(workspace / "output"),
                "--renderer-release-sha256",
                RELEASE,
            ],
            input=canonical_bytes(command.model_dump(mode="json")),
            capture_output=True,
            check=False,
            timeout=60,
            cwd=workspace,
            env={
                "PATH": "/usr/bin:/bin",
                "LANG": "C.UTF-8",
                "TZ": "UTC",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": ":".join(
                    str(ROOT / part)
                    for part in (
                        "packages/kakao_archive_contracts",
                        "services/kakao_archive_worker",
                    )
                ),
            },
        )
        assert result.returncode == 0, result.stderr.decode()
        (workspace / "output" / "result.json").write_bytes(result.stdout)
        (workspace / "output" / "result.json").chmod(0o640)


def font(tmp_path):
    raw = pymupdf.Font("korea").buffer
    path = tmp_path / "profile-font.otf"
    path.write_bytes(raw)
    path.chmod(0o640)
    return path, LocalMember(
        relative_path="font.otf", sha256=sha256(raw), size_bytes=len(raw), media_type="font/otf"
    )


def current_authorizer(engine, actor, sources, packet, selected):
    def authorize():
        with Session(engine) as session, session.begin():
            authorize_kakao_binding_scope(
                session,
                actor,
                packet.stored.source_binding_id,
                PermissionKey.KAKAO_ARCHIVE_EXPORT,
                lock=False,
            )
            sources.validate_question_source_metadata(session, actor, selected.sources)
            validate_source_pointer_metadata_batch(
                session, (packet.stored.manifest, *(q.stored.manifest for q in selected.questions))
            )

    return authorize


LAYOUTS = ("student-question-a4/1.0", "student-study-a4/1.0")


def test_refreshed_late_answer_photo_reaches_real_study_pdf(refresh_case, source_store, tmp_path):
    store, old, previous, _command = refresh_case
    engine, actor, questions, creation, sources, artifacts, _binding = store
    image = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 400, 300))
    image.clear_with(170)
    photo = image.tobytes("png")
    admission, _ = source_store[-1](
        previous=previous.resolution,
        texts=(
            "first unique question",
            "unique continuation",
            "later staff reply",
            "separate question",
        ),
        roles=("student", "student", "staff", "student"),
        photos={3: (photo, 400, 300)},
    )
    source = sources.admit_source(actor, admission, idempotency_key="late-photo-" + uuid4().hex)
    command = refresh_command(
        old, source.resolution.source_revision_id, creation.expected_mapping_revision_id
    )
    refreshed = questions.refresh_question_source(
        actor, command, idempotency_key="late-photo-question-" + uuid4().hex
    )
    reviewed = questions.change_question(
        actor,
        change_command(refreshed.question),
        idempotency_key="late-photo-review-" + uuid4().hex,
    ).question
    packets = KakaoPacketService(engine, artifacts=artifacts, questions=questions, sources=sources)
    packet = packets.save_packet(
        actor,
        KakaoPacketCreate(
            source_binding_id=command.source_binding_id,
            title="late answer and photo",
            questions=(
                KakaoQuestionProvenance(
                    question_id=reviewed.question_id,
                    question_revision_id=reviewed.question_revision_id,
                ),
            ),
            display_start_date=date(2026, 1, 1),
            display_end_date_inclusive=date(2026, 12, 31),
            mode="FINAL",
            include_replies=True,
        ),
        idempotency_key="late-photo-packet-" + uuid4().hex,
    )
    accepted, selected = packets.resolve_student(
        actor,
        command.source_binding_id,
        packet.packet.packet_id,
        revision_id=packet.packet.packet_revision_id,
        student_id=reviewed.student.student_id,
    )
    authorize = current_authorizer(engine, actor, sources, accepted, selected)
    prepared, render_command = staged(
        tmp_path,
        artifacts,
        accepted,
        selected,
        reviewed.student.student_id,
        authorize,
        LAYOUTS[1],
    )
    assert len(prepared.manifest.questions[0].staff.images) == 1
    assert len(prepared.manifest.questions[0].student.images) == 0
    launcher = RenderProcess()
    root = tmp_path / "late-photo-worker"
    root.mkdir(mode=0o700)
    output = KakaoPdfExecutor(
        root,
        os.getuid(),
        os.getgid(),
        launcher,
        lambda _: authorize(),
    ).execute(render_command, source_root=prepared.source_root)
    assert output.result.status == "COMPLETED" and launcher.calls == 1
    assert sum(len(page.layout.image_blocks) for page in output.layout.pages) == 1
    with pymupdf.open(output.staging_root / "report.pdf") as document:
        assert sum(len(page.get_image_info()) for page in document) == 1
        assert "later staff reply" in "".join(page.get_text() for page in document)
        assert "separate question" not in "".join(page.get_text() for page in document)
    published = publish_kakao_pdf(
        artifacts,
        command=render_command,
        manifest_bytes=(prepared.source_root / "manifest.json").read_bytes(),
        accepted=output,
        authorize=authorize,
    )
    assert published.pdf.sha256 == next(
        member.sha256 for member in output.result.outputs if member.relative_path == "report.pdf"
    )
    assert (
        questions.get_question(
            actor,
            old.source_binding_id,
            old.room_id,
            old.question_id,
            revision_id=old.question_revision_id,
        ).stored
        == old
    )


def staged(tmp_path, artifacts, packet, selection, student_id, authorize, layout_policy=LAYOUTS[0]):
    source = artifacts.settings.staging_root / ("input-" + uuid4().hex)
    source.mkdir(mode=0o700)
    font_path, member = font(tmp_path)
    prepared = prepare_kakao_pdf_inputs(
        artifacts,
        packet=packet,
        selection=selection,
        student_id=student_id,
        source_root=source,
        font_source=font_path,
        font=member,
        authorize=authorize,
        layout_policy=layout_policy,
    )
    fields = dict(
        execution=dict(
            command_id="kakaocommand_" + uuid4().hex,
            task_id="kakaotask_" + uuid4().hex,
            attempt_id="kakaoattempt_" + uuid4().hex,
            attempt_number=1,
            fence=1,
        ),
        export_id="kakaoexport_" + uuid4().hex,
        source_binding_id=prepared.manifest.source_binding_id,
        packet_revision_id=prepared.manifest.packet_revision_id,
        student_id=student_id,
        subset_sha256=prepared.manifest.subset_sha256,
        mode=prepared.manifest.mode,
        renderer_release_sha256=RELEASE,
        layout_policy=layout_policy,
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
    return prepared, command


def test_study_projection_reopens_exact_stored_student_selection_without_hand_picked_rows(
    packet_store, tmp_path
):
    engine, actor, packets, request, stored_questions, questions, sources, artifacts = packet_store
    request = request.model_copy(update={"include_replies": True})
    key = "study-packet-" + uuid4().hex
    saved = packets.save_packet(actor, request, idempotency_key=key)
    assert packets.save_packet(actor, request, idempotency_key=key).packet == saved.packet
    reopened = KakaoPacketService(engine, artifacts=artifacts, questions=questions, sources=sources)
    for stored in stored_questions:
        student_id = stored.student.student_id
        accepted, selection = reopened.resolve_student(
            actor,
            request.source_binding_id,
            saved.packet.packet_id,
            revision_id=saved.packet.packet_revision_id,
            student_id=student_id,
        )
        authorize = current_authorizer(engine, actor, sources, accepted, selection)
        prepared, _ = staged(tmp_path, artifacts, accepted, selection, student_id, authorize)
        arguments = dict(
            packet=accepted.packet,
            student_id=student_id,
            questions=tuple(value.published for value in selection.questions),
            sources=tuple(value.resolved for value in selection.sources),
            images=prepared.images,
        )
        projected = project_kakao_student_study(**arguments)
        assert projected.student_id == student_id
        assert tuple(value.question_revision_id for value in projected.questions) == (
            stored.question_revision_id,
        )
        assert len(projected.questions[0].messages) > 0
        assert all(message.raw_date for message in projected.questions[0].messages)
        assert projected.study_revision_id is None and not projected.questions[0].supplements
        # The new manifest is not written over the already-pinned v1 input.
        original = (prepared.source_root / "manifest.json").read_bytes()
        assert original == canonical_bytes(prepared.manifest.model_dump(mode="json"))
        assert canonical_bytes(projected.model_dump(mode="json")) == canonical_bytes(
            project_kakao_student_study(**arguments).model_dump(mode="json")
        )
        authorize()


@pytest.mark.parametrize("layout_policy", LAYOUTS)
def test_actual_two_students_are_separate_pdfs_and_replay_does_not_render(
    packet_store, tmp_path, layout_policy
):
    engine, actor, packets, request, stored_questions, _questions, sources, artifacts = packet_store
    saved = packets.save_packet(actor, request, idempotency_key="render-packet-" + uuid4().hex)
    launcher = RenderProcess()
    for stored in stored_questions:
        student_id = stored.student.student_id
        accepted, selected = packets.resolve_student(
            actor,
            request.source_binding_id,
            saved.packet.packet_id,
            revision_id=saved.packet.packet_revision_id,
            student_id=student_id,
        )
        authorize = current_authorizer(engine, actor, sources, accepted, selected)
        prepared, command = staged(
            tmp_path, artifacts, accepted, selected, student_id, authorize, layout_policy
        )
        assert str(prepared.source_root) not in repr(prepared)
        assert "private question" not in repr(prepared)
        root = tmp_path / ("worker-" + uuid4().hex)
        root.mkdir(mode=0o700)
        executor = KakaoPdfExecutor(
            root, os.getuid(), os.getgid(), launcher, lambda _, check=authorize: check()
        )
        output = executor.execute(command, source_root=prepared.source_root)
        assert output.result.page_count == 1
        assert isinstance(output.layout, StudyLayoutReceipt) == (layout_policy == LAYOUTS[1])
        published = publish_kakao_pdf(
            artifacts,
            command=command,
            manifest_bytes=(prepared.source_root / "manifest.json").read_bytes(),
            accepted=output,
            authorize=authorize,
        )
        again = publish_kakao_pdf(
            artifacts,
            command=command,
            manifest_bytes=(prepared.source_root / "manifest.json").read_bytes(),
            accepted=output,
            authorize=authorize,
        )
        assert published == again
        p = published.pdf
        opened = artifacts.open_verified_member(
            artifact_id=p.artifact_id,
            revision_id=p.artifact_revision_id,
            member_path=p.member_path,
            schema_ref=p.schema_ref,
            sha256=p.sha256,
            media_type=p.media_type,
            max_bytes=32 * 1024 * 1024,
        )
        with (
            opened.stream as stream,
            pymupdf.open(stream=stream.read(), filetype="pdf") as document,
        ):
            assert len(document) == 1
            text = document[0].get_text()
            assert ("second student" in text) == (stored == stored_questions[1])
        assert {q.question_revision_id for q in prepared.manifest.questions} == {
            stored.question_revision_id
        }
    assert launcher.calls == 2


@pytest.mark.parametrize("layout_policy", LAYOUTS)
@pytest.mark.parametrize("autosave", [False, True])
def test_csv_photo_occurrences_reach_real_pdf_without_duplicate_binary_stage(
    question_store, source_store, tmp_path, monkeypatch, layout_policy, autosave
):
    engine, actor, questions, initial, sources, artifacts, _binding = question_store
    previous = sources.get_source(
        actor,
        initial.source_binding_id,
        initial.room_id,
        source_revision_id=initial.source_revision_id,
    ).resolution
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 400, 300))
    pixmap.clear_with(180)
    photo = pixmap.tobytes("png")
    texts = ("학생이 올린 사진입니다.", "같은 사진의 별도 메시지입니다.")
    roles = ("student", "student")
    photos = {1: (photo, 400, 300), 2: (photo, 400, 300)}
    if layout_policy == LAYOUTS[1]:
        texts += ("조교의 원문 답변과 시각 기록입니다.\r\n" * 90,)
        roles += ("staff",)
        photos[3] = (photo, 400, 300)
    admission, _ = source_store[-1](
        previous=previous,
        texts=texts,
        photos=photos,
        roles=roles,
    )
    accepted_source = sources.admit_source(
        actor, admission, idempotency_key="photo-source-" + uuid4().hex
    )
    if autosave:
        saved = questions.create_source_candidates(
            actor,
            initial.source_binding_id,
            initial.room_id,
            source_revision_id=accepted_source.resolution.source_revision_id,
        )
        assert len(saved.saved) == 1 and saved.unresolved_rows == ()
        created = saved.saved[0]
    else:
        created = questions.create_question(
            actor,
            initial.model_copy(
                update={"source_revision_id": accepted_source.resolution.source_revision_id}
            ),
            idempotency_key="photo-question-" + uuid4().hex,
        )
    reviewed = questions.change_question(
        actor, change_command(created.question), idempotency_key="photo-review-" + uuid4().hex
    )
    packets = KakaoPacketService(engine, artifacts=artifacts, questions=questions, sources=sources)
    request = KakaoPacketCreate(
        source_binding_id=initial.source_binding_id,
        title="사진 질문",
        questions=(
            KakaoQuestionProvenance(
                question_id=reviewed.question.question_id,
                question_revision_id=reviewed.question.question_revision_id,
            ),
        ),
        display_start_date=date(2026, 1, 1),
        display_end_date_inclusive=date(2026, 12, 31),
        mode="FINAL",
        include_replies=layout_policy == LAYOUTS[1],
    )
    packet = packets.save_packet(actor, request, idempotency_key="photo-packet-" + uuid4().hex)
    accepted, selected = packets.resolve_student(
        actor,
        initial.source_binding_id,
        packet.packet.packet_id,
        revision_id=packet.packet.packet_revision_id,
        student_id=reviewed.question.student.student_id,
    )
    authorize = current_authorizer(engine, actor, sources, accepted, selected)
    opens = []
    original = artifacts.open_verified_member

    def observed(**kwargs):
        opens.append(kwargs["sha256"])
        return original(**kwargs)

    monkeypatch.setattr(artifacts, "open_verified_member", observed)
    prepared, command = staged(
        tmp_path,
        artifacts,
        accepted,
        selected,
        reviewed.question.student.student_id,
        authorize,
        layout_policy,
    )
    assert opens == [sha256(photo)]
    assert len(prepared.images) == 1
    if isinstance(prepared.manifest, StudyRenderManifest):
        q = prepared.manifest.questions[0]
        assert len(q.student.images) == 2 and len(q.staff.images) == 1
    else:
        assert len(prepared.manifest.questions[0].images) == 2
    assert (prepared.source_root / prepared.images[0].member.relative_path).read_bytes() == photo
    launcher = RenderProcess()
    work = tmp_path / "photo-worker"
    work.mkdir(mode=0o700)
    executor = KakaoPdfExecutor(work, os.getuid(), os.getgid(), launcher, lambda _: authorize())
    result = executor.execute(command, source_root=prepared.source_root)
    assert result.result.status == "COMPLETED"
    if isinstance(result.layout, StudyLayoutReceipt):
        assert result.result.page_count > 2
        assert len(result.layout.pages[0].layout.image_blocks) == 2
        assert sum(len(p.layout.image_blocks) for p in result.layout.pages) == 3
    else:
        assert result.result.page_count == 1
        assert len(result.layout.pages[0].image_blocks) == 2
    with pymupdf.open(result.staging_root / "report.pdf") as document:
        assert len(document[0].get_image_info()) == 2
        assert "학생이 올린 사진입니다" in document[0].get_text()
        if layout_policy == LAYOUTS[1]:
            assert "조교" in "".join(p.get_text() for p in document)
    published = publish_kakao_pdf(
        artifacts,
        command=command,
        manifest_bytes=(prepared.source_root / "manifest.json").read_bytes(),
        accepted=result,
        authorize=authorize,
    )
    assert published.pdf.sha256 == sha256((result.staging_root / "report.pdf").read_bytes())
    stopped = []
    recovered = executor.recover_finished(command, assert_stopped=lambda *a: stopped.append(a))
    assert stopped and recovered == result
    assert launcher.calls == 1


@pytest.mark.parametrize(
    "bad", ["other_student", "font_hash", "font_link", "directory_link", "nas_root", "nonempty"]
)
def test_materializer_fails_before_unrelated_binary_reads(packet_store, tmp_path, monkeypatch, bad):
    engine, actor, packets, request, questions, _qservice, sources, artifacts = packet_store
    packet = packets.save_packet(actor, request, idempotency_key="negative-input-" + uuid4().hex)
    accepted, selected = packets.resolve_student(
        actor,
        request.source_binding_id,
        packet.packet.packet_id,
        revision_id=packet.packet.packet_revision_id,
        student_id=questions[0].student.student_id,
    )
    if bad == "other_student":
        _, selected = packets.resolve_student(
            actor,
            request.source_binding_id,
            packet.packet.packet_id,
            revision_id=packet.packet.packet_revision_id,
            student_id=questions[1].student.student_id,
        )
    root = artifacts.settings.staging_root / "bad-input"
    if bad == "nas_root":
        root = artifacts.settings.nas_artifact_root / "invalid-local-stage"
    root.mkdir(mode=0o700)
    if bad == "directory_link":
        link = artifacts.settings.staging_root / "linked-input"
        link.symlink_to(root, target_is_directory=True)
        root = link
    font_path, member = font(tmp_path)
    if bad == "font_hash":
        member = member.model_copy(update={"sha256": "sha256:" + "0" * 64})
    elif bad == "font_link":
        link = tmp_path / "linked-font.otf"
        link.symlink_to(font_path)
        font_path = link
    elif bad == "nonempty":
        (root / "kept").write_bytes(b"must stay")

    def forbidden(**kwargs):
        raise AssertionError("invalid selection/profile must not read image data")

    monkeypatch.setattr(artifacts, "open_verified_member", forbidden)
    authorize = current_authorizer(engine, actor, sources, accepted, selected)
    with pytest.raises((ValueError, OSError)):
        prepare_kakao_pdf_inputs(
            artifacts,
            packet=accepted,
            student_id=questions[0].student.student_id,
            selection=selected,
            source_root=root,
            font_source=font_path,
            font=member,
            authorize=authorize,
        )
    if bad == "nonempty":
        assert (root / "kept").read_bytes() == b"must stay"
    else:
        assert tuple(root.iterdir()) == ()


def test_current_session_is_checked_after_materialization(packet_store, tmp_path):
    engine, actor, packets, request, questions, _qservice, sources, artifacts = packet_store
    saved = packets.save_packet(actor, request, idempotency_key="input-expiry-" + uuid4().hex)
    packet, selected = packets.resolve_student(
        actor,
        request.source_binding_id,
        saved.packet.packet_id,
        revision_id=saved.packet.packet_revision_id,
        student_id=questions[0].student.student_id,
    )
    current = current_authorizer(engine, actor, sources, packet, selected)
    calls = []

    def authorize():
        calls.append(True)
        if len(calls) == 2:
            from datetime import UTC, datetime

            with Session(engine) as session, session.begin():
                session.execute(
                    update(ApiSessionRecord)
                    .where(ApiSessionRecord.api_session_id == actor.session_id)
                    .values(revoked_at=datetime.now(UTC))
                )
        current()

    root = artifacts.settings.staging_root / "revoked-input"
    root.mkdir(mode=0o700)
    font_path, member = font(tmp_path)
    with pytest.raises(ValueError, match="PERMISSION_DENIED"):
        prepare_kakao_pdf_inputs(
            artifacts,
            packet=packet,
            selection=selected,
            student_id=questions[0].student.student_id,
            source_root=root,
            font_source=font_path,
            font=member,
            authorize=authorize,
        )
    assert len(calls) == 2 and (root / "manifest.json").exists()
