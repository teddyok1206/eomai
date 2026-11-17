"""Real PNG/crop and PDF tests with synthetic concepts, not live textbook/slot evidence."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pymupdf
import pytest
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_concept_pages import prepare_kakao_concept_captures
from eom_catalog_service.kakao_concept_study import (
    prepare_kakao_concept_study,
    project_kakao_concept_supplements,
)
from eom_kakao_archive_contracts import LocalMember, canonical_bytes, sha256
from eom_kakao_archive_contracts.concepts import (
    ConceptEvidenceContext,
    parse_concept_request,
    validate_concept_result,
)
from eom_kakao_archive_contracts.render import subset_sha256
from eom_kakao_archive_contracts.study import StudyRenderManifest
from eom_kakao_archive_contracts.study_layout import StudyLayoutReceipt, check_study_layout
from eom_kakao_archive_worker.study_pdf import render_study

from tests.unit.test_kakao_concept_contracts import composed, plan, plan_request, result
from tests.unit.test_kakao_concept_pages import compose, prepared
from tests.unit.test_kakao_question_render import local_file
from tests.unit.test_kakao_study_render_contract import command, manifest


def inputs(tmp_path, **kwargs):
    artifacts, staged, outputs, authorize = prepared(tmp_path)
    request, output = compose(staged, **kwargs)
    captures = prepare_kakao_concept_captures(
        artifacts,
        prepared=staged,
        request=request,
        result=output,
        output_root=outputs,
        authorize=authorize,
    )
    return artifacts, staged, outputs, request, output, captures


def project(values, *, captures=None):
    _, staged, _, request, output, actual = values
    return project_kakao_concept_supplements(
        prepared=staged,
        request=request,
        result=output,
        captures=actual if captures is None else captures,
    )


def test_real_crop_and_explanation_have_separate_truthful_source_labels(tmp_path):
    values = inputs(tmp_path)
    supplements = project(values)
    block, *notes = supplements
    assert block.title == values[4].output.blocks[0].title
    assert block.origin == "MODEL_DRAFT"
    assert block.text_blocks[0].text.startswith("질문과의 연결: ")
    assert block.text_blocks[1].text == values[4].output.blocks[0].explanation
    assert len(block.images) == 1 and not block.images[0].quality_accepted
    assert block.images[0].member == values[5][0].member
    assert [c.source_title for c in block.citations] == ["검증 교과서", "검증 교과서"]
    assert "원문 인용 아님" in block.citations[0].page_label
    assert (
        block.citations[0].source_sha256
        == values[1].knowledge.materials[0].analysis.accepted_result.sha256
    )
    assert "물리 페이지 1" in block.citations[1].page_label
    assert "인쇄 쪽수 미확인" in block.citations[1].page_label
    assert block.citations[1].source_sha256 == values[5][0].original.sha256
    assert notes[-1].supplement_id == "limitations"
    assert any("분석 텍스트" in t.text for t in notes[-1].text_blocks)
    assert project(values) == supplements
    values[0].commit_file_set.assert_not_called()


def test_repeated_crop_has_one_member_and_separate_display_uses(tmp_path):
    values = inputs(tmp_path, blocks=6, captures=4)
    supplements = project(values)
    images = [p for block in supplements for p in block.images]
    assert len(images) == 24 and len({p.member for p in images}) == 1
    assert len({p.attachment_occurrence_id for p in images}) == 24
    assert len(list(values[2].rglob("*.png"))) == 1
    assert len(supplements) <= 8


def test_staff_notes_keep_their_actual_evidence_separate_from_original_answer(tmp_path):
    values = list(inputs(tmp_path))
    body = values[4].output.model_dump(mode="json")
    body["staff_checks"] = [
        dict(
            observation="설명에 적용 범위를 덧붙이면 좋습니다.",
            reason="관련 기초 개념만 제공됨",
            evidence_keys=["E1"],
        )
    ] * 6
    values[4] = validate_concept_result(values[3], result(values[3], body))
    blocks = project(values)
    note = next(block for block in blocks if block.supplement_id == "staff-checks")
    assert "원래 답변은 변경하지 않음" in note.title
    assert len(note.text_blocks) == 6 and len(note.citations) == 1
    assert note.citations[0].evidence_id == "E1"
    assert note.origin == "MODEL_DRAFT"


@pytest.mark.parametrize("family", ["V3", "V4", "V5"])
def test_text_only_recommendation_does_not_invent_textbook_pictures(tmp_path, family):
    _artifacts, staged, _outputs, _authorize = prepared(tmp_path, family=family)
    request = parse_concept_request(
        plan_request().model_dump(mode="json")
        | dict(phase="COMPOSE", plan=plan(), context=staged.context.model_dump(mode="json"))
    )
    body = composed()
    body["blocks"][0].update(
        captures=[], citations=[dict(evidence_key="E1", passage_key=None, quote=None)]
    )
    output = validate_concept_result(request, result(request, body))
    values = project_kakao_concept_supplements(
        prepared=staged, request=request, result=output, captures=()
    )
    assert not any(block.images for block in values)
    assert values[0].citations[0].page_label == "승인된 분석 근거 · 교재 원문 인용 아님"
    if family == "V3":
        assert any("PNG가 없는" in t.text for block in values for t in block.text_blocks)


def test_no_matching_material_is_a_limitation_not_a_fake_source(tmp_path):
    _artifacts, staged, _outputs, _authorize = prepared(tmp_path, count=0)
    request = parse_concept_request(
        plan_request().model_dump(mode="json")
        | dict(phase="COMPOSE", plan=plan(), context=staged.context.model_dump(mode="json"))
    )
    body = composed() | dict(status="NO_MATCH", blocks=[], staff_checks=[])
    output = validate_concept_result(request, result(request, body))
    values = project_kakao_concept_supplements(
        prepared=staged, request=request, result=output, captures=()
    )
    assert len(values) == 1 and values[0].supplement_id == "limitations"
    assert not values[0].images and not values[0].citations
    assert any("찾지 못" in text.text for text in values[0].text_blocks)


@pytest.mark.parametrize(
    "change", ["missing", "extra", "page", "original", "bounds", "profile", "media"]
)
def test_capture_metadata_cannot_be_replaced_by_an_unrelated_image(tmp_path, change):
    values = inputs(tmp_path)
    capture = values[5][0]
    captures = (capture,)
    if change == "missing":
        captures = ()
    elif change == "extra":
        captures = (capture, capture)
    else:
        changes = {
            "page": {"page_key": "E1P2"},
            "original": {"original": capture.original.model_copy(update={"sha256": sha256(b"x")})},
            "bounds": {"pixel_bounds": (0, 0, 1, 1)},
            "profile": {"profile": "other/1.0"},
            "media": {"member": capture.member.model_copy(update={"media_type": "image/jpeg"})},
        }
        captures = (replace(capture, **changes[change]),)
    with pytest.raises(KakaoArchiveError, match="KAKAO_CONCEPT_CAPTURE_"):
        project(values, captures=captures)


def test_different_analysis_body_is_not_the_same_evidence(tmp_path):
    values = inputs(tmp_path)
    request = values[3]
    context = request.context.model_dump(mode="json", exclude={"context_sha256"})
    context["evidence"][0]["analysis_text"] += " 다른 본문"
    changed = ConceptEvidenceContext.model_validate(
        context | dict(context_sha256=sha256(canonical_bytes(context)))
    )
    with pytest.raises(KakaoArchiveError, match="EVIDENCE_TEXT_CHANGED"):
        replace(values[1], context=changed)
    # The projection protects the boundary even if a caller bypasses the frozen DTO constructor.
    altered = SimpleNamespace(
        knowledge=values[1].knowledge, context=changed, sources=values[1].sources
    )
    with pytest.raises(KakaoArchiveError, match="EVIDENCE_TEXT_CHANGED"):
        project_kakao_concept_supplements(
            prepared=altered,
            request=request.model_copy(update={"context": changed}),
            result=values[4].model_copy(
                update={
                    "request_sha256": sha256(
                        canonical_bytes(
                            request.model_copy(update={"context": changed}).model_dump(mode="json")
                        )
                    )
                }
            ),
            captures=values[5],
        )


def test_actual_pdf_contains_crop_and_citations_after_the_original_reply(tmp_path):
    values = inputs(tmp_path)
    source = values[2]
    body = manifest().model_dump(mode="json")
    body["mode"] = "DRAFT"
    body["study_revision_id"] = "kakaostudyrev_" + "9" * 32  # Synthetic saved-owner fixture.
    question = body["questions"][0]
    question["question_revision_id"] = values[3].question.question_revision_id
    question["student"]["images"] = []
    question["student"]["ordered_blocks"] = [
        ref for ref in question["student"]["ordered_blocks"] if ref["kind"] == "TEXT"
    ]
    question["supplements"] = [s.model_dump(mode="json") for s in project(values)]
    body["subset_sha256"] = subset_sha256((question["question_revision_id"],))
    document = StudyRenderManifest.model_validate(body)
    raw = canonical_bytes(document.model_dump(mode="json"))
    request = command(document).model_copy(
        update={
            "manifest": LocalMember.model_validate(
                local_file(source, "manifest.json", raw, "application/json")
            ),
            "font": LocalMember.model_validate(
                local_file(source, "font.otf", pymupdf.Font("korea").buffer, "font/otf")
            ),
        }
    )
    output = tmp_path / "pdf"
    output.mkdir()
    rendered = render_study(
        request,
        input_root=source,
        output_root=output,
        renderer_release_sha256=request.renderer_release_sha256,
    )
    assert rendered.status == "COMPLETED"
    layout = StudyLayoutReceipt.model_validate_json((output / "layout.json").read_bytes())
    check_study_layout(request, document, layout)
    sections = [p.section for p in layout.pages]
    assert sections[:2] == ["STUDENT", "STAFF"]
    assert all(value == "SUPPLEMENT" for value in sections[2:])
    with pymupdf.open(output / "report.pdf") as pdf:
        text = "\n".join(page.get_text() for page in pdf)
        assert "출처:" in text and "검증 교과서" in text
        assert "AI 작성 초안" in text and "인쇄 쪽수 미확인" in text
        assert sum(len(page.get_image_info()) for page in pdf) == 1
        crop = values[5][0]
        assert next(image for page in pdf for image in page.get_images())[2:4] == (
            crop.pixel_bounds[2] - crop.pixel_bounds[0],
            crop.pixel_bounds[3] - crop.pixel_bounds[1],
        )


def test_saved_phase_adapter_reuses_result_and_calls_current_authority(tmp_path, monkeypatch):
    import eom_catalog_service.kakao_concept_composition as composition
    import eom_catalog_service.kakao_concept_study as study

    values = inputs(tmp_path)
    _artifacts, staged, outputs, request, output, captures = values
    authority = MagicMock()
    service = authority.service
    completed = SimpleNamespace(
        request=request,
        work=SimpleNamespace(source_binding_id="binding"),
        pin=Mock(),
        result=SimpleNamespace(output=output),
    )
    monkeypatch.setattr(study, "read_kakao_concept_phase_result", Mock(return_value=completed))
    monkeypatch.setattr(
        study, "read_kakao_concept_composition", Mock(return_value=(request, Mock()))
    )
    monkeypatch.setattr(
        composition, "authorize_kakao_concept_composition", Mock(return_value=staged.knowledge)
    )
    reader = service.knowledge_reader
    reader.prepare_pages.return_value = staged
    reader.prepare_captures.return_value = captures
    result = prepare_kakao_concept_study(
        authority, source_root=staged.source_root, output_root=outputs
    )
    assert result.supplements == project(values)
    assert result.question_revision_id == request.question.question_revision_id
    assert result.result is completed.pin and result.source_root == outputs
    reader.prepare_pages.call_args.kwargs["reauthorize_question"]()
    reader.prepare_captures.call_args.kwargs["reauthorize_question"]()
    assert authority.reauthorize.call_count == 3
    service.artifacts.commit_file_set.assert_not_called()
