"""Reusable role/metadata projection, not hand-picked CSV rows or a live Kakao claim."""

from dataclasses import replace
from pathlib import Path

import pytest
from eom_catalog_service.kakao_render_projection import KakaoRenderImageInput
from eom_catalog_service.kakao_study_projection import project_kakao_student_study
from eom_kakao_archive_contracts import LocalMember, canonical_bytes, sha256, study_validation

from tests.unit.test_kakao_question_editing import (
    confirmed,
    image,
    packet,
    published,
    question,
    source,
    student,
)
from tests.unit.test_kakao_render_projection import prepare


def two_photo_inputs(*, shared_member=False):
    resolved = source(attachments={1: (image(1),), 3: (image(2),)})
    selected = confirmed(question(resolved), (resolved,))
    materialized = tuple(
        KakaoRenderImageInput(
            value.pointer,
            LocalMember(
                relative_path="shared.png" if shared_member else f"image-{index}.png",
                sha256=value.pointer.sha256,
                size_bytes=len(b"fixture-pixels"),
                media_type="image/png",
            ),
        )
        for index, value in enumerate(resolved.attachments.values(), 1)
    )
    return dict(
        packet=packet((selected,), include_replies=True),
        student_id=student().student_id,
        questions=(published(selected),),
        sources=(resolved,),
        images=materialized,
    )


def test_student_and_staff_photos_are_separate_without_filename_inference():
    args = two_photo_inputs(shared_member=True)
    result = project_kakao_student_study(**args)
    value = result.questions[0]
    assert (
        value.student.images[0].value.attachment_occurrence_id
        != value.staff.images[0].value.attachment_occurrence_id
    )
    assert value.student.images[0].value.member == value.staff.images[0].value.member
    assert [block.value.text for block in value.student.text_blocks] == ["첫 질문", "추가 질문"]
    assert [block.value.text for block in value.staff.text_blocks] == ["답변"]
    assert len(value.messages) == 3  # A message's text+photo has one metadata record.
    assert [message.role for message in value.messages] == ["student", "student", "staff"]
    assert [message.raw_date for message in value.messages] == [
        "2026-10-31 23:59:01",
        "2026-10-31 23:59:02",
        "2026-10-31 23:59:03",
    ]
    assert all(message.source_timezone == "Asia/Seoul" for message in value.messages)
    assert (
        value.staff.text_blocks[0].value.text == args["sources"][0].normalization.messages[2].text
    )
    assert canonical_bytes(result.model_dump(mode="json")) == canonical_bytes(
        project_kakao_student_study(**args).model_dump(mode="json")
    )


@pytest.mark.parametrize("include_replies", [False, True])
def test_reply_selection_preserves_existing_packet_policy(include_replies):
    args = two_photo_inputs()
    if not include_replies:
        args["packet"] = packet(
            tuple(value.question for value in args["questions"]), include_replies=False
        )
        args["images"] = args["images"][:1]
    result = project_kakao_student_study(**args).questions[0]
    assert (result.staff is not None) is include_replies
    assert len(result.messages) == (3 if include_replies else 2)
    assert (
        not any(message.role == "staff" for message in result.messages)
        if not include_replies
        else True
    )


def test_staff_without_a_photo_has_no_invented_photo_slot():
    value = project_kakao_student_study(**prepare(photo=True, replies=True)).questions[0]
    assert len(value.student.images) == 1 and value.staff.images == ()


def test_unknown_timezone_retains_raw_dates_without_inventing_utc():
    resolved = source(timezone="unknown")
    value = question(resolved)
    result = project_kakao_student_study(
        packet=packet((value,), mode="DRAFT", include_replies=True),
        student_id=student().student_id,
        questions=(published(value),),
        sources=(resolved,),
        images=(),
    )
    assert result.questions[0].header_date is None
    assert all(
        message.sent_at_utc is None and message.source_timezone == "unknown"
        for message in result.questions[0].messages
    )
    assert result.questions[0].messages[0].raw_date == "2026-10-31 23:59:01"


def test_only_the_exact_selected_students_questions_and_metadata_are_projected():
    first, second = source(number=1), source(number=2)
    q1 = confirmed(question(first, number=1), (first,), number=11)
    q2 = confirmed(question(second, number=2, mapping=student(2)), (second,), number=22)
    bundle = packet((q1, q2), include_replies=True)
    value = project_kakao_student_study(
        packet=bundle,
        student_id=student(2).student_id,
        questions=(published(q2),),
        sources=(second,),
        images=(),
    )
    assert (
        len(value.questions) == 1
        and value.questions[0].question_revision_id == q2.question_revision_id
    )
    assert {message.source_occurrence_id for message in value.questions[0].messages} == set(
        second.occurrence_ids.values()
    )
    with pytest.raises(ValueError, match="QUESTION_SET_MISMATCH"):
        project_kakao_student_study(
            packet=bundle,
            student_id=student(2).student_id,
            questions=(published(q1), published(q2)),
            sources=(first, second),
            images=(),
        )


@pytest.mark.parametrize("field", ["questions", "sources", "images"])
def test_missing_pins_never_resolve_to_latest(field):
    args = two_photo_inputs()
    args[field] = ()
    with pytest.raises(ValueError, match="KAKAO_ARCHIVE_RENDER_"):
        project_kakao_student_study(**args)


def test_duplicate_or_unrelated_image_input_is_rejected():
    args = two_photo_inputs()
    args["images"] += args["images"][:1]
    with pytest.raises(ValueError, match="IMAGE_DUPLICATED"):
        project_kakao_student_study(**args)
    args = two_photo_inputs()
    args["images"] = args["images"][:1]
    with pytest.raises(ValueError, match="IMAGE_MISSING"):
        project_kakao_student_study(**args)


def test_local_image_bytes_cannot_claim_a_different_hash():
    args = two_photo_inputs()
    with pytest.raises(ValueError, match="IMAGE_PIN_MISMATCH"):
        replace(
            args["images"][0],
            member=args["images"][0].member.model_copy(update={"sha256": sha256(b"unrelated")}),
        )


def test_source_projection_has_no_unsaved_notes_or_citation_input():
    args = prepare()
    value = project_kakao_student_study(**args)
    assert value.study_revision_id is None and value.questions[0].supplements == ()
    with pytest.raises(TypeError):
        project_kakao_student_study(**args, supplements={})


def test_projection_reads_only_its_pinned_schema_resources_not_content_paths(monkeypatch):
    args = prepare(photo=True, replies=True)

    # Fixture construction occurs first; the actual projection must stay pure.
    allowed = {
        Path(study_validation.__file__).parent / "schemas" / name
        for name in ("worker-question-render-v1.schema.json", "worker-study-render-v1.schema.json")
    }
    original = Path.open

    def guarded(path, *args, **kwargs):
        assert path in allowed, "PROJECTION_READ_CONTENT_PATH"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    assert len(project_kakao_student_study(**args).questions) == 1
