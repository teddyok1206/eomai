"""Anonymous immutable-question fixtures; no browser, DB, model, network or NAS."""

from __future__ import annotations

import csv
import io
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from eom_catalog_contracts.kakao_archive import KakaoAttachmentObservation, KakaoMessageObservation
from eom_catalog_contracts.kakao_question import (
    NORMALIZATION_REF,
    QUESTION_REF,
    KakaoDisplayOverride,
    KakaoImageCrop,
    KakaoImageQualityAcceptance,
    KakaoImageTransform,
    KakaoPacketStudentSubset,
    KakaoQuestionConfirm,
    KakaoQuestionEdit,
    KakaoQuestionExclude,
    KakaoQuestionImage,
    KakaoQuestionManifest,
    KakaoQuestionPacket,
    KakaoQuestionStudentPin,
    KakaoQuestionText,
    KakaoSelectionExclusion,
    question_period_utc,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, validate_contract
from eom_catalog_service.kakao_csv_parser import parse_kakao_csv
from eom_catalog_service.kakao_question_editing import (
    KakaoAttachmentSource,
    PublishedKakaoQuestion,
    ResolvedKakaoQuestionSource,
    build_question_packet,
    edit_question,
    mark_question_source_stale,
    merge_questions,
    packet_student_subset,
    question_final_blockers,
    question_from_candidate,
    resolve_question_text,
    split_question,
    utf16_offset_to_codepoint,
    validate_codepoint_span,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer

NOW = datetime(2026, 11, 16, tzinfo=UTC)
ACTOR = "operator_" + "a" * 32
ROOT = Path(__file__).resolve().parents[2]


def identity(prefix: str, number: int) -> str:
    return f"{prefix}_{number:032x}"


def pointer(schema: str, content: bytes, number: int = 1, media: str = "application/json"):
    return ArtifactMemberPointer(
        artifact_id=identity("artifact", number),
        artifact_revision_id=identity("rev", number),
        member_path="source.json" if media == "application/json" else "photo.png",
        schema_ref=schema,
        media_type=media,
        sha256=sha256_bytes(content),
    )


def student(number: int = 1, *, mapping: int | None = None):
    return KakaoQuestionStudentPin(
        student_id=identity("kakaostudent", number),
        student_display_revision_id=identity("kakaostudentrev", number),
        room_mapping_revision_id=identity("kakaomappingrev", mapping or number),
        display_name=f"학생 {number}",
    )


def source(
    texts: tuple[str, ...] = ("첫 질문", "추가 질문", "답변"),
    roles: tuple[str, ...] = ("student", "student", "staff"),
    *,
    number: int = 1,
    binding: int = 1,
    room: int = 1,
    timezone: str = "Asia/Seoul",
    attachments: dict[int, tuple[KakaoAttachmentObservation, ...]] | None = None,
    quality: str = "ORIGINAL",
    kinds: dict[int, str] | None = None,
    context_verified: bool = True,
) -> ResolvedKakaoQuestionSource:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(("DATE", "USER", "MESSAGE"))
    for row, text in enumerate(texts, 1):
        writer.writerow((f"2026-10-31 23:59:{row:02}", "익명", text))
    observations = tuple(
        KakaoMessageObservation.model_validate(
            {
                "row_ordinal": row,
                "role": role,
                "role_evidence_id": "fixture-direction" if role != "unknown" else None,
                "kind": (kinds or {}).get(row, "text"),
                "attachments": (attachments or {}).get(row, ()),
            }
        )
        for row, role in enumerate(roles, 1)
    )
    parsed = parse_kakao_csv(
        output.getvalue().encode(),
        source_binding_id=identity("kakaobinding", binding),
        room_id=identity("kakaoroom", room),
        snapshot_revision_id=identity("kakaosnapshotrev", number),
        normalization_revision_id=identity("kakaonormalizationrev", number),
        observed_at_utc=NOW,
        source_timezone=timezone,
        source_order="ascending",
        context_start_verified=context_verified,
        context_end_verified=context_verified,
        observations=observations,
    )
    images = {
        image.attachment_id: KakaoAttachmentSource(
            image.attachment_revision_id,
            pointer("eom://schemas/kakao-archive/media/1.0", b"fixture-pixels", index, "image/png"),
            quality,
        )
        for index, image in enumerate(
            (image for row in observations for image in row.attachments), 1
        )
        if image.availability == "available"
    }
    return ResolvedKakaoQuestionSource(
        parsed,
        pointer(NORMALIZATION_REF, canonical_json_bytes(parsed.model_dump(mode="json")), number),
        {row: identity("kakaomessage", number * 100 + row) for row in range(1, len(texts) + 1)},
        images,
    )


def question(resolved=None, number=1, ordinal=1, mapping=None):
    resolved = resolved or source()
    return question_from_candidate(
        resolved,
        resolved.candidates[ordinal],
        question_id=identity("kakaoquestion", number),
        question_revision_id=identity("kakaoquestionrev", number),
        student=mapping or student(),
        actor_id=ACTOR,
        created_at=NOW,
    )


def confirmed(value, sources, number=10, *, boundary=True):
    return edit_question(
        value,
        KakaoQuestionConfirm(
            parent_revision_id=value.question_revision_id,
            reason="질문 범위 확인",
            boundary_confirmed=boundary,
        ),
        question_revision_id=identity("kakaoquestionrev", number),
        actor_id=ACTOR,
        created_at=NOW + timedelta(minutes=1),
        sources=sources,
    )


def published(value):
    return PublishedKakaoQuestion(
        value, pointer(QUESTION_REF, canonical_json_bytes(value.model_dump(mode="json")), 90)
    )


def packet(values, **updates):
    args = dict(
        packet_id=identity("kakaopacket", 1),
        packet_revision_id=identity("kakaopacketrev", 1),
        previous_revision_id=None,
        start_date=date(2026, 10, 1),
        end_date_inclusive=date(2026, 10, 31),
        mode="FINAL",
        include_replies=False,
        actor_id=ACTOR,
        created_at=NOW + timedelta(hours=1),
    )
    args.update(updates)
    return build_question_packet(tuple(published(value) for value in values), **args)


def image(number=1, *, available=True, association="SOURCE_VERIFIED"):
    return KakaoAttachmentObservation(
        attachment_id=identity("kakaoattachment", number),
        attachment_revision_id=identity("kakaoattachmentrev", number),
        album_ordinal=number,
        availability="available" if available else "expired",
        association=association,
    )


@pytest.mark.parametrize("name", ["manifest", "edit", "packet"])
def test_question_schema_canonical_mirror(name: str):
    resource = CATALOG_SCHEMA_RESOURCES[f"kakao-question-{name}-v1"]
    raw = (ROOT / resource.canonical_path).read_bytes()
    assert sha256_bytes(raw) == resource.sha256
    assert (
        raw
        == (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )


def test_candidate_conversion_has_pointers_not_raw_text_and_keeps_reply_context():
    resolved = source()
    value = question(resolved)
    assert [block.role for block in value.ordered_blocks] == ["student", "student", "staff"]
    assert "첫 질문" not in value.model_dump_json()
    assert value.sources[0].pointer == resolved.pointer
    assert value.review_state == "UNREVIEWED"
    assert question_final_blockers(value) == ("NOT_REVIEWED",)
    assert resolve_question_text(value.ordered_blocks[0], resolved) == "첫 질문"
    validate_contract("kakao-question-manifest-v1", value.model_dump(mode="json"))


def test_source_hash_occurrence_index_and_candidate_are_verified():
    resolved = source()
    with pytest.raises(ValueError, match="NORMALIZATION_HASH_MISMATCH"):
        replace(
            resolved, pointer=resolved.pointer.model_copy(update={"sha256": "sha256:" + "0" * 64})
        )
    with pytest.raises(ValueError, match="OCCURRENCE_INDEX_INVALID"):
        replace(resolved, occurrence_ids={1: identity("kakaomessage", 1)})
    tampered = resolved.candidates[1].model_copy(update={"boundary_uncertain": True})
    with pytest.raises(ValueError, match="CANDIDATE_MISMATCH"):
        question_from_candidate(
            resolved,
            tampered,
            question_id=identity("kakaoquestion", 1),
            question_revision_id=identity("kakaoquestionrev", 1),
            student=student(),
            actor_id=ACTOR,
            created_at=NOW,
        )


def test_confirmation_and_exclusion_are_successors_and_preserve_source():
    resolved = source()
    original = question(resolved)
    approved = confirmed(original, (resolved,))
    assert original.review_state == "UNREVIEWED" and approved.review_state == "CONFIRMED"
    assert approved.previous_revision_id == original.question_revision_id
    assert approved.ordered_blocks == original.ordered_blocks and not question_final_blockers(
        approved
    )
    excluded = edit_question(
        approved,
        KakaoQuestionExclude(
            parent_revision_id=approved.question_revision_id,
            reason="학습 질문이 아닌 공지",
        ),
        question_revision_id=identity("kakaoquestionrev", 11),
        actor_id=ACTOR,
        created_at=NOW + timedelta(minutes=2),
        sources=(resolved,),
    )
    assert (
        excluded.review_state == "EXCLUDED" and excluded.ordered_blocks == original.ordered_blocks
    )
    with pytest.raises(ValueError, match="QUESTION_EXCLUDED"):
        packet((excluded,), mode="DRAFT")


def test_stale_review_and_reused_revision_cannot_be_confirmed():
    resolved = source()
    original = question(resolved)
    with pytest.raises(ValueError, match="PRECONDITION_FAILED"):
        edit_question(
            original,
            KakaoQuestionConfirm(
                parent_revision_id=identity("kakaoquestionrev", 999),
                reason="확인",
                boundary_confirmed=True,
            ),
            question_revision_id=identity("kakaoquestionrev", 2),
            actor_id=ACTOR,
            created_at=NOW,
            sources=(resolved,),
        )
    with pytest.raises(ValueError, match="REVISION_REUSED"):
        confirmed(original, (resolved,), number=1)
    stale = original.model_copy(update={"source_stale": True})
    with pytest.raises(ValueError, match="STALE_SOURCE"):
        confirmed(stale, (resolved,))


def test_unknown_sender_barrier_needs_explicit_boundary_review():
    resolved = source(("앞 질문", "미확인", "뒤 질문"), ("student", "unknown", "student"))
    value = question(resolved)
    unconfirmed_boundary = confirmed(value, (resolved,), boundary=False)
    assert "BOUNDARY_UNCONFIRMED" in question_final_blockers(unconfirmed_boundary)
    assert not question_final_blockers(confirmed(value, (resolved,), boundary=True))
    assert len(resolved.candidates) == 2


def test_unknown_timezone_and_missing_attachment_stay_final_blockers():
    resolved = source(timezone="unknown", attachments={1: (image(available=False),)})
    value = confirmed(question(resolved), (resolved,))
    blockers = question_final_blockers(value)
    assert "TIMEZONE_UNVERIFIED" in blockers and "MISSING_ATTACHMENT" in blockers
    draft = packet((value,), mode="DRAFT")
    assert draft.questions[0].final_blockers == blockers
    with pytest.raises(ValueError, match="FINAL_BLOCKED"):
        packet((value,))


@pytest.mark.parametrize(
    "text,start,end",
    [
        ("A\u0301B", 0, 1),
        ("A\u0301B", 1, 2),
        ("👩\u200d🔬!", 0, 1),
        ("👍🏽!", 0, 1),
        ("🇰🇷!", 0, 1),
        ("가!", 0, 1),
        ("가\r\n나", 0, 2),
        ("\ud800x", 0, 1),
        ("한글", -1, 1),
        ("한글", 0, 3),
    ],
)
def test_codepoint_spans_never_cut_surrogates_or_combining_sequences(text, start, end):
    with pytest.raises(ValueError, match="TEXT_SPAN_INVALID"):
        validate_codepoint_span(text, start, end)


def test_utf16_selection_conversion_and_unicode_span_preserves_exact_text():
    text = "가😀A\u0301나"
    assert utf16_offset_to_codepoint(text, 3) == 2
    assert validate_codepoint_span(text, 1, 2) == "😀"
    assert validate_codepoint_span(text, 2, 4) == "A\u0301"
    with pytest.raises(ValueError, match="TEXT_SPAN_INVALID"):
        utf16_offset_to_codepoint(text, 2)
    with pytest.raises(ValueError, match="TEXT_SPAN_INVALID"):
        utf16_offset_to_codepoint(text, 4)


def test_edit_order_override_and_explicit_removal_do_not_change_original():
    resolved = source(attachments={1: (image(1), image(2))})
    value = confirmed(question(resolved), (resolved,))
    first_text = value.ordered_blocks[0]
    assert isinstance(first_text, KakaoQuestionText)
    override = first_text.model_copy(
        update={
            "display_override": KakaoDisplayOverride(
                text="확인된 표시 문구", reason="원문은 별도로 보존"
            )
        }
    )
    images = tuple(block for block in value.ordered_blocks if isinstance(block, KakaoQuestionImage))
    kept = (override, images[1], images[0], value.ordered_blocks[-1])
    removed = tuple(
        KakaoSelectionExclusion(block_id=block.block_id, reason="별도 질문으로 분리 예정")
        for block in value.ordered_blocks
        if block.block_id not in {entry.block_id for entry in kept}
    )
    command = KakaoQuestionEdit(
        parent_revision_id=value.question_revision_id,
        student=value.student,
        ordered_blocks=kept,
        selection_exclusions=removed,
    )
    edited = edit_question(
        value,
        command,
        question_revision_id=identity("kakaoquestionrev", 11),
        actor_id=ACTOR,
        created_at=NOW + timedelta(minutes=2),
        sources=(resolved,),
    )
    assert edited.review_state == "UNREVIEWED" and value.review_state == "CONFIRMED"
    assert resolve_question_text(edited.ordered_blocks[0], resolved) == "확인된 표시 문구"
    assert resolve_question_text(first_text, resolved) == "첫 질문"
    assert [
        block.attachment_id
        for block in edited.ordered_blocks
        if isinstance(block, KakaoQuestionImage)
    ] == [images[1].attachment_id, images[0].attachment_id]
    with pytest.raises(ValueError, match="REMOVAL_REASON_REQUIRED"):
        edit_question(
            value,
            command.model_copy(update={"selection_exclusions": ()}),
            question_revision_id=identity("kakaoquestionrev", 12),
            actor_id=ACTOR,
            created_at=NOW + timedelta(minutes=2),
            sources=(resolved,),
        )


def test_best_available_image_acceptance_is_exact_and_manual_transform_survives():
    resolved = source(attachments={1: (image(),)}, quality="BEST_AVAILABLE")
    value = question(resolved)
    original = next(
        block for block in value.ordered_blocks if isinstance(block, KakaoQuestionImage)
    )
    assert "IMAGE_QUALITY_UNCONFIRMED" in question_final_blockers(value)
    now = NOW + timedelta(minutes=2)
    transformed = original.model_copy(
        update={
            "quality_acceptance": KakaoImageQualityAcceptance(
                attachment_revision_id=original.attachment_revision_id,
                source_sha256=original.source_pointer.sha256,
                accepted_by=ACTOR,
                accepted_at=now,
                reason="미리보기 가독성 확인",
            ),
            "transform": KakaoImageTransform(
                transform_revision_id=identity("kakaotransformrev", 1),
                rotate_clockwise=90,
                crop=KakaoImageCrop(left_ppm=0, top_ppm=0, right_ppm=900000, bottom_ppm=1000000),
                reason="사용자가 지정한 여백 제외",
            ),
        }
    )
    edited = edit_question(
        value,
        KakaoQuestionEdit(
            parent_revision_id=value.question_revision_id,
            student=value.student,
            ordered_blocks=tuple(
                transformed if block.block_id == original.block_id else block
                for block in value.ordered_blocks
            ),
            selection_exclusions=(),
        ),
        question_revision_id=identity("kakaoquestionrev", 11),
        actor_id=ACTOR,
        created_at=now,
        sources=(resolved,),
    )
    assert "IMAGE_QUALITY_UNCONFIRMED" not in question_final_blockers(edited)
    new_image = next(
        block for block in edited.ordered_blocks if isinstance(block, KakaoQuestionImage)
    )
    assert new_image.source_pointer == original.source_pointer and original.transform is None
    assert new_image.transform.operation_order == "EXIF_THEN_ROTATE_THEN_CROP"


def test_split_single_message_codepoint_spans_covers_source_once_then_merge():
    resolved = source(("질문A 질문B",), ("student",))
    value = question(resolved)
    original = value.ordered_blocks[0]
    left = original.model_copy(update={"block_id": "left-span", "end_codepoint": 4})
    right = original.model_copy(update={"block_id": "right-span", "start_codepoint": 4})
    parts = split_question(
        value,
        ((left,), (right,)),
        expected_revision_id=value.question_revision_id,
        new_ids=(
            (identity("kakaoquestion", 2), identity("kakaoquestionrev", 2)),
            (identity("kakaoquestion", 3), identity("kakaoquestionrev", 3)),
        ),
        actor_id=ACTOR,
        created_at=NOW,
        sources=(resolved,),
    )
    assert all(
        part.provenance[0].question_revision_id == value.question_revision_id for part in parts
    )
    assert [resolve_question_text(part.ordered_blocks[0], resolved) for part in parts] == [
        "질문A ",
        "질문B",
    ]
    merged = merge_questions(
        parts,
        expected_revision_ids=tuple(part.question_revision_id for part in parts),
        question_id=identity("kakaoquestion", 4),
        question_revision_id=identity("kakaoquestionrev", 4),
        actor_id=ACTOR,
        created_at=NOW,
        sources=(resolved,),
    )
    assert merged.review_state == "UNREVIEWED" and len(merged.provenance) == 2
    assert merged.ordered_blocks == (left, right)


@pytest.mark.parametrize("second_start", [3, 5])
def test_split_rejects_overlapping_or_lost_text(second_start):
    resolved = source(("질문A 질문B",), ("student",))
    value = question(resolved)
    block = value.ordered_blocks[0]
    with pytest.raises(ValueError, match=r"OVERLAP|COVERAGE_INVALID"):
        split_question(
            value,
            (
                (block.model_copy(update={"block_id": "left", "end_codepoint": 4}),),
                (block.model_copy(update={"block_id": "right", "start_codepoint": second_start}),),
            ),
            expected_revision_id=value.question_revision_id,
            new_ids=(
                (identity("kakaoquestion", 2), identity("kakaoquestionrev", 2)),
                (identity("kakaoquestion", 3), identity("kakaoquestionrev", 3)),
            ),
            actor_id=ACTOR,
            created_at=NOW,
            sources=(resolved,),
        )


@pytest.mark.parametrize("difference", ["room", "binding", "student"])
def test_cross_scope_merge_is_not_permitted(difference):
    first_source = source(number=1)
    second_source = source(
        number=2, room=2 if difference == "room" else 1, binding=2 if difference == "binding" else 1
    )
    first = question(first_source)
    second = question(second_source, number=2, mapping=student(2 if difference == "student" else 1))
    with pytest.raises(ValueError, match="COMPOSITION_SCOPE_INVALID"):
        merge_questions(
            (first, second),
            expected_revision_ids=(first.question_revision_id, second.question_revision_id),
            question_id=identity("kakaoquestion", 3),
            question_revision_id=identity("kakaoquestionrev", 3),
            actor_id=ACTOR,
            created_at=NOW,
            sources=(first_source, second_source),
        )


def test_multiple_students_packet_preserves_order_and_subset_identity():
    first_source, second_source, third_source = (
        source(number=1),
        source(number=2, room=2),
        source(number=3),
    )
    first = confirmed(question(first_source), (first_source,), number=11)
    second = confirmed(
        question(second_source, number=2, mapping=student(2)), (second_source,), number=12
    )
    third = confirmed(question(third_source, number=3), (third_source,), number=13)
    result = packet((third, second, first), collection_coverage="PARTIAL")
    assert [entry.question_revision_id for entry in result.questions] == [
        third.question_revision_id,
        second.question_revision_id,
        first.question_revision_id,
    ]
    subset = packet_student_subset(result, student().student_id)
    assert [entry.question_revision_id for entry in subset.questions] == [
        third.question_revision_id,
        first.question_revision_id,
    ]
    assert subset.subset_sha256 == sha256_bytes(
        canonical_json_bytes((third.question_revision_id, first.question_revision_id))
    )
    assert result.range_start_utc == datetime(2026, 9, 30, 15, tzinfo=UTC)
    assert result.range_end_utc_exclusive == datetime(2026, 10, 31, 15, tzinfo=UTC)
    validate_contract("kakao-question-packet-v1", result.model_dump(mode="json"))
    with pytest.raises(ValueError, match="STUDENT_NOT_IN_PACKET"):
        packet_student_subset(result, identity("kakaostudent", 99))


def test_packet_rejects_empty_duplicate_outside_period_and_wrong_manifest_hash():
    resolved = source()
    value = confirmed(question(resolved), (resolved,))
    with pytest.raises(ValueError, match="EMPTY_SELECTION"):
        packet(())
    with pytest.raises(ValueError, match="QUESTION_DUPLICATED"):
        packet((value, value))
    with pytest.raises(ValueError, match="OUTSIDE_PERIOD"):
        packet((value,), start_date=date(2026, 9, 1), end_date_inclusive=date(2026, 9, 30))
    with pytest.raises(ValueError, match="QUESTION_HASH_MISMATCH"):
        PublishedKakaoQuestion(value, pointer(QUESTION_REF, b"another revision"))


def test_staff_missing_photo_only_blocks_when_reply_is_requested():
    resolved = source(attachments={3: (image(available=False),)})
    value = confirmed(question(resolved), (resolved,))
    assert not question_final_blockers(value)
    assert "MISSING_ATTACHMENT" in question_final_blockers(value, include_replies=True)
    assert packet((value,)).include_replies is False
    with pytest.raises(ValueError, match="FINAL_BLOCKED"):
        packet((value,), include_replies=True)


def test_source_role_or_hash_cannot_be_rewritten_by_edit_command():
    resolved = source()
    value = question(resolved)
    original = value.ordered_blocks[0]
    for updates, code in (
        ({"role": "staff"}, "BLOCK_SOURCE_MISMATCH"),
        ({"source_text_sha256": "sha256:" + "0" * 64}, "TEXT_HASH_MISMATCH"),
    ):
        changed = original.model_copy(update=updates)
        with pytest.raises(ValueError, match=code):
            edit_question(
                value,
                KakaoQuestionEdit(
                    parent_revision_id=value.question_revision_id,
                    student=value.student,
                    ordered_blocks=(changed, *value.ordered_blocks[1:]),
                    selection_exclusions=(),
                ),
                question_revision_id=identity("kakaoquestionrev", 2),
                actor_id=ACTOR,
                created_at=NOW,
                sources=(resolved,),
            )


def test_question_student_display_uses_shared_maximum_128_without_truncation():
    resolved = source()
    pin = student().model_copy(update={"display_name": "가" * 128})
    value = question(resolved, mapping=pin)
    assert (
        len(
            KakaoQuestionManifest.model_validate(value.model_dump(mode="json")).student.display_name
        )
        == 128
    )


def test_changed_source_creates_unreviewed_successor_without_rewriting_review():
    resolved = source()
    approved = confirmed(question(resolved), (resolved,))
    updated = mark_question_source_stale(
        approved,
        expected_revision_id=approved.question_revision_id,
        question_revision_id=identity("kakaoquestionrev", 20),
        actor_id=ACTOR,
        created_at=NOW + timedelta(hours=1),
    )
    assert approved.review_state == "CONFIRMED" and approved.source_stale is False
    assert updated.review_state == "UNREVIEWED" and updated.review_decision is None
    assert updated.source_stale is True
    assert updated.previous_revision_id == approved.question_revision_id
    assert updated.sources == approved.sources and updated.ordered_blocks == approved.ordered_blocks
    assert "STALE_SOURCE" in question_final_blockers(updated)
    with pytest.raises(ValueError, match="STALE_SOURCE"):
        edit_question(
            updated,
            KakaoQuestionConfirm(
                parent_revision_id=updated.question_revision_id,
                reason="원본 변경 후 이전 검토 재사용 거부",
                boundary_confirmed=True,
            ),
            question_revision_id=identity("kakaoquestionrev", 21),
            actor_id=ACTOR,
            created_at=NOW + timedelta(hours=2),
            sources=(resolved,),
        )
    with pytest.raises(ValueError, match="PRECONDITION_FAILED"):
        mark_question_source_stale(
            approved,
            expected_revision_id=updated.question_revision_id,
            question_revision_id=identity("kakaoquestionrev", 22),
            actor_id=ACTOR,
            created_at=NOW + timedelta(hours=1),
        )


def test_packet_utc_window_cannot_disagree_with_displayed_dates():
    resolved = source()
    value = packet((confirmed(question(resolved), (resolved,)),))
    wire = value.model_dump(mode="json")
    wire["range_start_utc"] = "2026-09-30T14:00:00Z"
    with pytest.raises(ValueError, match="PERIOD_INVALID"):
        KakaoQuestionPacket.model_validate(wire)
    for start, end in ((date.min, date.min), (date.max, date.max)):
        with pytest.raises(ValueError, match="PERIOD_INVALID"):
            question_period_utc(start, end)


def test_subset_cannot_mix_students_or_forge_revision_sequence_hash():
    first_source, second_source = source(number=1), source(number=2, room=2)
    first = confirmed(question(first_source), (first_source,), number=11)
    second = confirmed(
        question(second_source, number=2, mapping=student(2)), (second_source,), number=12
    )
    value = packet((first, second))
    subset = packet_student_subset(value, student().student_id)
    with pytest.raises(ValueError, match="SUBSET_HASH_MISMATCH"):
        KakaoPacketStudentSubset.model_validate(
            {**subset.model_dump(mode="json"), "subset_sha256": "sha256:" + "0" * 64}
        )
    with pytest.raises(ValueError, match="SUBSET_MISMATCH"):
        KakaoPacketStudentSubset.model_validate(
            {
                **subset.model_dump(mode="json"),
                "questions": [entry.model_dump(mode="json") for entry in value.questions],
            }
        )
