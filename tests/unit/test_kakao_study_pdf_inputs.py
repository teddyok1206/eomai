"""Saved edit projection and real local crop staging, never a model or live textbook run."""

from dataclasses import replace

import pytest
from eom_catalog_contracts.kakao_concept_knowledge import KakaoConceptResultPin
from eom_catalog_contracts.kakao_study_store import KakaoStudyQuestion, KakaoStudyQuestionEdit
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_concept_study import KakaoPreparedConceptStudy
from eom_catalog_service.kakao_study_pdf_inputs import (
    _stage_supplements,
    select_kakao_study_supplements,
)
from eom_identifiers import sha256_bytes

from tests.unit.test_kakao_concept_study import inputs, project
from tests.unit.test_kakao_study_store import identity


def prepared(tmp_path):
    value = inputs(tmp_path, blocks=2, captures=2)
    pin = KakaoConceptResultPin(
        workflow_id=identity("workflow"),
        step_run_id=identity("steprun"),
        job_id=identity("job"),
        artifact_id=identity("artifact"),
        artifact_revision_id=identity("rev"),
        sha256="sha256:" + "a" * 64,
    )
    draft = KakaoPreparedConceptStudy(
        value[3].task_id,
        value[3].question.question_revision_id,
        pin,
        project(value),
        value[5],
        value[2],
    )
    selected = KakaoStudyQuestion(
        edit=KakaoStudyQuestionEdit(
            question_revision_id=draft.question_revision_id,
            concept_task_id=draft.task_id,
            blocks=(
                dict(
                    block_index=1,
                    title="선택한 개념",
                    relevance="수정한 연결",
                    explanation="직접 수정한 설명",
                    capture_indices=(1, 0),
                ),
            ),
            notes=(dict(title="추가 메모", text="교사가 작성한 설명입니다."),),
        ),
        result=pin,
    )
    return draft, selected


def test_saved_reordering_edits_and_notes_preserve_original_source_citations(tmp_path):
    draft, selected = prepared(tmp_path)
    original = tuple(block.model_dump(mode="json") for block in draft.supplements)
    values = select_kakao_study_supplements(selected, draft)
    block = values[0]
    assert block.supplement_id == "concept-1" and block.title == "선택한 개념"
    assert block.origin == "USER_NOTE"
    assert [t.text for t in block.text_blocks][:2] == [
        "질문과의 연결: 수정한 연결",
        "직접 수정한 설명",
    ]
    source = draft.supplements[1]
    assert block.citations == source.citations
    assert block.images == (source.images[1], source.images[0])
    assert not any(p.quality_accepted for p in block.images)
    assert values[-1].supplement_id == "note-0" and values[-1].origin == "USER_NOTE"
    assert tuple(b.model_dump(mode="json") for b in draft.supplements) == original


def test_manual_notes_need_no_model_or_fabricated_citation():
    selected = KakaoStudyQuestion(
        edit=KakaoStudyQuestionEdit(
            question_revision_id=identity("kakaoquestionrev"),
            concept_task_id=None,
            blocks=(),
            notes=(dict(title="직접 쓴 개념", text="메모"),),
        ),
        result=None,
    )
    values = select_kakao_study_supplements(selected, None)
    assert len(values) == 1 and not values[0].citations and not values[0].images


@pytest.mark.parametrize(
    "field", ["task_id", "question_revision_id", "result", "missing-draft", "block", "capture"]
)
def test_a_different_source_or_missing_selection_is_not_substituted(tmp_path, field):
    draft, selected = prepared(tmp_path)
    if field == "missing-draft":
        draft = None
    elif field == "result":
        draft = replace(
            draft, result=draft.result.model_copy(update={"sha256": "sha256:" + "b" * 64})
        )
    elif field in {"task_id", "question_revision_id"}:
        draft = replace(
            draft,
            **{
                field: identity(
                    "kakaoconcepttask" if field == "task_id" else "kakaoquestionrev", 99
                )
            },
        )
    else:
        data = selected.model_dump(mode="json")
        data["edit"]["blocks"][0]["block_index" if field == "block" else "capture_indices"] = (
            5 if field == "block" else [3]
        )
        selected = KakaoStudyQuestion.model_validate(data)
    with pytest.raises(
        KakaoArchiveError, match=r"KAKAO_STUDY_(SOURCE_CHANGED|BLOCK_SELECTION_INVALID)"
    ):
        select_kakao_study_supplements(selected, draft)


def test_only_selected_crop_bytes_are_staged_once_across_question_uses(tmp_path):
    draft, selected = prepared(tmp_path)
    values = select_kakao_study_supplements(selected, draft)
    target = tmp_path / "final-input"
    target.mkdir(mode=0o700)
    staged = {}
    first, remaining = _stage_supplements(
        values,
        source_root=draft.source_root,
        target_root=target,
        staged=staged,
        available_bytes=100000,
    )
    second, same = _stage_supplements(
        values,
        source_root=draft.source_root,
        target_root=target,
        staged=staged,
        available_bytes=remaining,
    )
    assert first == second and same == remaining
    assert len(staged) == 1 and len(list(target.rglob("*.png"))) == 1
    member = first[0].images[0].member
    assert member.relative_path.startswith("study-images/")
    assert sha256_bytes((target / member.relative_path).read_bytes()) == member.sha256
    assert remaining == 100000 - member.size_bytes


def test_input_budget_rejects_before_copying_a_new_image(tmp_path):
    draft, selected = prepared(tmp_path)
    target = tmp_path / "final-input"
    target.mkdir(mode=0o700)
    with pytest.raises(KakaoArchiveError, match="INPUT_TOO_LARGE"):
        _stage_supplements(
            select_kakao_study_supplements(selected, draft),
            source_root=draft.source_root,
            target_root=target,
            staged={},
            available_bytes=0,
        )
    assert not list(target.iterdir())
