"""Study input → actual subprocess → existing stopped acceptance and Artifact publisher."""

import json
from dataclasses import replace

import pymupdf
import pytest
from eom_catalog_service.kakao_pdf_inputs import prepare_kakao_pdf_inputs
from eom_catalog_service.kakao_pdf_publication import STUDY_LAYOUT_REF, publish_kakao_pdf
from eom_kakao_archive_contracts import RenderManifest, canonical_bytes, sha256
from eom_kakao_archive_contracts.pdf_contracts import (
    parse_pdf_command,
    parse_pdf_manifest,
    parse_pdf_result,
    pdf_input_members,
)
from eom_kakao_archive_contracts.study_layout import StudyLayoutReceipt
from eom_orchestrator.kakao_pdf_files import KakaoPdfExecutionError

from tests.unit.test_kakao_archive_intake import _publisher
from tests.unit.test_kakao_pdf_execution import LocalProcess, _result_edit, executor
from tests.unit.test_kakao_question_render import RELEASE, identity
from tests.unit.test_kakao_study_pdf import add_role_photos
from tests.unit.test_kakao_study_pdf import prepared as prepared


def command(prepared, change=None):
    value, request = prepared[2](change)
    return value, request.model_copy(update={"renderer_release_sha256": RELEASE})


def test_invalid_materialization_policy_is_rejected_before_any_source_or_file_access(prepared):
    _, request = command(prepared)
    checks = []
    with pytest.raises(ValueError, match="LAYOUT_POLICY_INVALID"):
        prepare_kakao_pdf_inputs(
            None,
            packet=None,
            student_id=request.student_id,
            selection=None,
            source_root=prepared[0],
            font_source=prepared[0] / "font.otf",
            font=request.font,
            authorize=lambda: checks.append(True),
            layout_policy="unsupported policy",
        )
    assert checks == [True]


def test_actual_study_subprocess_and_publication_replay_reuse_original_files(prepared, tmp_path):
    value, request = command(prepared, lambda v: add_role_photos(v, prepared[0], shared=True))
    launcher = LocalProcess()
    execution = executor(tmp_path, launcher)
    accepted = execution.execute(request, source_root=prepared[0])
    assert accepted.result.status == "COMPLETED" and accepted.result.page_count == 2
    assert isinstance(accepted.layout, StudyLayoutReceipt)
    assert len(value.questions) == 1  # A study PDF is not constrained to one page per question.
    publisher, commits = _publisher(tmp_path)
    arguments = dict(
        command=request,
        manifest_bytes=(prepared[0] / "manifest.json").read_bytes(),
        accepted=accepted,
        authorize=lambda: None,
    )
    first = publish_kakao_pdf(publisher, **arguments)
    again = publish_kakao_pdf(publisher, **arguments)
    assert first == again and launcher.calls == 1
    assert len(first.previews) == 2 and first.layout.schema_ref == STUDY_LAYOUT_REF
    assert first.layout.artifact_id == first.pdf.artifact_id
    assert first.layout.artifact_revision_id == first.pdf.artifact_revision_id
    for fields, payloads in commits:
        assert fields["request"]["schema_version"] == "kakao-study-render/1.0"
        assert fields["request"]["study_revision_id"] is None
        assert fields["request"]["layout_policy"] == "student-study-a4/1.0"
        assert "원문" not in json.dumps(fields["request"], ensure_ascii=False)
        assert payloads["report.pdf"] == (accepted.staging_root / "report.pdf").read_bytes()
    with pymupdf.open(accepted.staging_root / "report.pdf") as pdf:
        assert len(pdf[0].get_image_info()) == len(pdf[1].get_image_info()) == 1
    stopped = []
    recovered = execution.recover_finished(request, assert_stopped=lambda *a: stopped.append(a))
    assert stopped and recovered == accepted and launcher.calls == 1


def test_stopped_study_output_survives_authority_loss_without_second_dispatch(prepared, tmp_path):
    _, request = command(prepared)
    calls, valid = [], False

    def current(value):
        calls.append(value)
        if len(calls) == 3 and not valid:
            raise KakaoPdfExecutionError("KAKAO_PDF_CLAIM_STALE")

    launcher = LocalProcess()
    execution = executor(tmp_path, launcher, current)
    with pytest.raises(KakaoPdfExecutionError, match="CLAIM_STALE"):
        execution.execute(request, source_root=prepared[0])
    assert launcher.calls == 1
    valid = True
    result = execution.recover_finished(request, assert_stopped=lambda *a: None)
    assert result.result.status == "COMPLETED" and launcher.calls == 1
    with pytest.raises(KakaoPdfExecutionError, match="ALREADY_STAGED"):
        execution.execute(request, source_root=prepared[0])
    assert launcher.calls == 1


@pytest.mark.parametrize("case", ["result-family", "layout-family", "study-pin", "missing-staff"])
def test_forged_study_output_never_reaches_acceptance(prepared, tmp_path, case):
    _, request = command(prepared)

    def mutate(_command, workspace):
        if case == "result-family":
            _result_edit(
                workspace,
                lambda value: value.update(schema_version="kakao-question-render-result/1.0"),
            )
            return
        layout_path = workspace / "output" / "layout.json"
        value = json.loads(layout_path.read_bytes())
        if case == "layout-family":
            value["schema_version"] = "kakao-question-layout-receipt/1.0"
        elif case == "study-pin":
            value["study_revision_id"] = identity("studyrev", 9)
        else:
            value["pages"].pop()
        raw = canonical_bytes(value)
        layout_path.write_bytes(raw)
        _result_edit(
            workspace,
            lambda value: value.update(
                outputs=[
                    member | dict(sha256=sha256(raw), size_bytes=len(raw))
                    if member["relative_path"] == "layout.json"
                    else member
                    for member in value["outputs"]
                ]
            ),
        )

    execution = executor(tmp_path, LocalProcess(mutate))
    with pytest.raises(KakaoPdfExecutionError):
        execution.execute(request, source_root=prepared[0])
    assert not (execution.workspace_root / request.execution.attempt_id / "accepted").exists()


def test_publication_rejects_wrong_study_layout_even_if_model_was_copied(prepared, tmp_path):
    _, request = command(prepared)
    accepted = executor(tmp_path).execute(request, source_root=prepared[0])
    publisher, calls = _publisher(tmp_path)
    forged = accepted.layout.model_copy(update={"student_id": identity("student", 9)})
    with pytest.raises(ValueError, match="PINS_MISMATCH"):
        publish_kakao_pdf(
            publisher,
            command=request,
            manifest_bytes=(prepared[0] / "manifest.json").read_bytes(),
            accepted=replace(accepted, layout=forged),
            authorize=lambda: None,
        )
    assert not calls


def test_contract_family_is_input_selected_and_no_unknown_latest_fallback(prepared):
    value, request = command(prepared)
    assert parse_pdf_command(request.model_dump(mode="json")) == request
    assert parse_pdf_manifest(request, value.model_dump(mode="json")) == value
    with pytest.raises(ValueError, match="SCHEMA_INVALID"):
        parse_pdf_command(
            request.model_dump(mode="json") | dict(schema_version="kakao-study-render/99.0")
        )
    with pytest.raises(ValueError):
        parse_pdf_manifest(
            request,
            value.model_dump(mode="json")
            | dict(schema_version="kakao-question-render-manifest/1.0"),
        )
    with pytest.raises(ValueError, match="FAMILY_MISMATCH"):
        pdf_input_members(request, RenderManifest.model_construct())
    with pytest.raises(ValueError):
        parse_pdf_result(request, dict(schema_version="kakao-question-render-result/1.0"))
