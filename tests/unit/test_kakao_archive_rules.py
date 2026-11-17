"""Anonymous source fixtures: no Kakao account, model, network or runtime credentials."""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from eom_catalog_contracts.kakao_archive import (
    KakaoAttachmentObservation,
    KakaoMessageNormalization,
    KakaoMessageObservation,
    MessageRole,
)
from eom_catalog_contracts.validation import validate_contract
from eom_catalog_service.kakao_csv_parser import parse_kakao_csv
from eom_catalog_service.kakao_message_alignment import align_kakao_snapshots
from eom_catalog_service.kakao_question_rules import (
    build_question_candidates,
    question_period_utc,
    select_question_period,
)
from pydantic import ValidationError


def csv_bytes(
    rows: list[list[str]], columns: tuple[str, ...] = ("DATE", "USER", "MESSAGE")
) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(columns)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def normalize(source: bytes, **overrides: object) -> KakaoMessageNormalization:
    arguments = {
        "source_binding_id": "kakaobinding_" + "1" * 32,
        "room_id": "kakaoroom_" + "2" * 32,
        "snapshot_revision_id": "kakaosnapshotrev_" + "3" * 32,
        "normalization_revision_id": "kakaonormalizationrev_" + "4" * 32,
        "observed_at_utc": datetime(2026, 11, 16, tzinfo=UTC),
        "source_order": "ascending",
        "source_timezone": "Asia/Seoul",
        "context_start_verified": True,
        "context_end_verified": True,
    }
    arguments.update(overrides)
    return parse_kakao_csv(source, **arguments)  # type: ignore[arg-type]


def role(row: int, value: MessageRole, **kwargs: object) -> KakaoMessageObservation:
    return KakaoMessageObservation.model_validate(
        {
            "row_ordinal": row,
            "role": value,
            "role_evidence_id": "synthetic-dom-evidence" if value != "unknown" else None,
            **kwargs,
        }
    )


def test_csv_preserves_bom_multiline_duplicate_messages_and_extra_columns() -> None:
    source = b"\xef\xbb\xbf" + csv_bytes(
        [
            ["2026-10-31 23:59:59", "학생 A", '  쉼표, "인용"\r\n추가  ', "extra"],
            ["2026-10-31 23:59:59", "학생 A", '  쉼표, "인용"\r\n추가  ', "extra"],
        ],
        ("DATE", "USER", "MESSAGE", "NEW_COLUMN"),
    )
    parsed = normalize(source)
    assert parsed.source_sha256 == "sha256:" + hashlib.sha256(source).hexdigest()
    assert parsed.source_bytes == len(source)
    assert len(parsed.messages) == 2
    assert tuple(m.row_ordinal for m in parsed.messages) == (1, 2)
    assert parsed.messages[0].text == '  쉼표, "인용"\r\n추가  '
    assert parsed.messages[0].extra_values == ("extra",)
    assert parsed.messages[0].sent_at_utc == datetime(2026, 10, 31, 14, 59, 59, tzinfo=UTC)
    assert parsed.messages[0].role == "unknown"
    validate_contract("kakao-message-normalization-v1", parsed.model_dump(mode="json"))


@pytest.mark.parametrize(
    "source,code",
    [
        (b"", "SIZE"),
        (b"DATE,USER,MESSAGE\n\xff", "ENCODING"),
        (b"DATE,USER,USER,MESSAGE\n", "COLUMNS"),
        (b"DATE,USER\n", "COLUMNS"),
        (b"DATE,USER,MESSAGE\n2026-11-15 01:02:03,name\n", "WIDTH"),
        (b"DATE,USER,MESSAGE\n2026-11-15 01:02:03,name,text,unexpected\n", "WIDTH"),
        (b'DATE,USER,MESSAGE\n2026-11-15 01:02:03,name,"unterminated', "MALFORMED"),
        (b"DATE,USER,MESSAGE\n2026-99-99 01:02:03,name,text\n", "DATE"),
        (b"DATE,USER,MESSAGE\n2026-1-1 1:2:3,name,text\n", "DATE"),
        (b"DATE,USER,MESSAGE\n2026-11-15 01:02:03,name,bad\x00\n", "OBSERVATION"),
    ],
)
def test_csv_rejects_invalid_without_silent_correction(source: bytes, code: str) -> None:
    with pytest.raises(ValueError, match=code):
        normalize(source)


def test_unknown_timezone_keeps_raw_date_and_blocks_period_selection() -> None:
    parsed = normalize(
        csv_bytes([["2026-10-31 23:59:59", "student", "질문"]]),
        source_timezone="unknown",
        observations=(role(1, "student"),),
    )
    assert parsed.messages[0].sent_at_utc is None
    candidates = build_question_candidates(parsed)
    assert "TIMEZONE_UNVERIFIED" in candidates.candidates[0].review_reasons
    with pytest.raises(ValueError, match="TIMEZONE_UNVERIFIED"):
        select_question_period(candidates, date(2026, 10, 1), date(2026, 10, 31))


def test_order_must_be_verified_not_timestamp_sorted() -> None:
    source = csv_bytes(
        [["2026-10-31 23:59:59", "A", "last"], ["2026-10-31 23:59:58", "A", "first"]]
    )
    with pytest.raises(ValueError, match="ORDER_INVALID"):
        normalize(source)
    unknown = normalize(source, source_order="unknown")
    with pytest.raises(ValueError, match="ORDER_UNVERIFIED"):
        build_question_candidates(unknown)
    descending = normalize(
        source, source_order="descending", observations=(role(1, "student"), role(2, "student"))
    )
    assert build_question_candidates(descending).candidates[0].student_rows == (2, 1)


def test_month_boundary_and_delayed_reply_do_not_split_question() -> None:
    parsed = normalize(
        csv_bytes(
            [
                ["2026-10-31 23:59:59", "A", "질문"],
                ["2026-11-01 00:00:01", "A", "추가 설명"],
                ["2026-11-05 09:00:00", "B", "답변"],
                ["2026-11-05 09:01:00", "A", "감사합니다"],
            ]
        ),
        observations=tuple(
            role(i, r) for i, r in enumerate(("student", "student", "staff", "student"), 1)
        ),
    )
    candidates = build_question_candidates(parsed)
    assert len(candidates.candidates) == 2
    selected = select_question_period(candidates, date(2026, 10, 1), date(2026, 10, 31))
    assert selected[0].student_rows == (1, 2)
    assert selected[0].reply_rows == (3,)
    assert candidates.candidates[1].student_rows == (4,)
    assert not selected[0].reviewed


def test_unknown_sender_forms_uncertain_barrier_not_silent_merge() -> None:
    parsed = normalize(
        csv_bytes([["2026-11-01 00:00:00", "same-name", str(i)] for i in range(4)]),
        observations=(role(1, "student"), role(3, "student"), role(4, "staff")),
    )
    candidates = build_question_candidates(parsed)
    assert [c.student_rows for c in candidates.candidates] == [(1,), (3,)]
    assert candidates.unresolved_rows == (2,)
    assert all(c.boundary_uncertain for c in candidates.candidates)


def test_turn_v1_acknowledgement_can_precede_a_later_question_in_one_candidate() -> None:
    # Historical turn_v1 is not a semantic question detector. Preserve its meaning
    # and expose this automation gap; a successor must not inherit the wrong date.
    parsed = normalize(
        csv_bytes(
            [
                ["2026-11-01 09:00:00", "A", "사진"],
                ["2026-11-01 09:01:00", "A", "첫 질문"],
                ["2026-11-01 10:00:00", "B", "첫 답변"],
                ["2026-11-01 11:00:00", "A", "감사합니다"],
                ["2026-11-06 09:00:00", "A", "사진"],
                ["2026-11-06 09:01:00", "A", "다른 질문"],
                ["2026-11-06 10:00:00", "B", "두 번째 답변"],
            ]
        ),
        observations=tuple(
            role(i, r)
            for i, r in enumerate(
                ("student", "student", "staff", "student", "student", "student", "staff"), 1
            )
        ),
    )
    candidates = build_question_candidates(parsed)
    assert [candidate.student_rows for candidate in candidates.candidates] == [(1, 2), (4, 5, 6)]
    assert candidates.candidates[1].first_student_at_utc == parsed.messages[3].sent_at_utc
    assert select_question_period(candidates, date(2026, 11, 6), date(2026, 11, 6)) == ()


def test_missing_and_multiple_images_remain_required_refs() -> None:
    attachments = tuple(
        KakaoAttachmentObservation(
            attachment_id="kakaoattachment_" + str(i) * 32,
            attachment_revision_id="kakaoattachmentrev_" + str(i) * 32,
            album_ordinal=i,
            availability="available" if i == 1 else "expired",
            association="SOURCE_VERIFIED",
        )
        for i in (1, 2)
    )
    parsed = normalize(
        csv_bytes([["2026-11-01 00:00:00", "A", "사진"]]),
        observations=(role(1, "student", kind="attachment", attachments=attachments),),
    )
    candidate = build_question_candidates(parsed).candidates[0]
    assert candidate.attachments == attachments
    assert candidate.review_reasons == ("ATTACHMENT_UNAVAILABLE",)


def test_photo_text_is_not_invented_attachment() -> None:
    parsed = normalize(
        csv_bytes([["2026-11-01 00:00:00", "A", "사진"]]), observations=(role(1, "student"),)
    )
    candidate = build_question_candidates(parsed).candidates[0]
    assert candidate.attachments == ()
    assert "PHOTO_MARKER_UNVERIFIED" in candidate.review_reasons


def test_deleted_only_and_system_rows_are_not_questions() -> None:
    parsed = normalize(
        csv_bytes([["2026-11-01 00:00:00", "A", str(i)] for i in (1, 2)]),
        observations=(role(1, "system", kind="system"), role(2, "student", kind="deleted")),
    )
    result = build_question_candidates(parsed)
    assert result.candidates == ()
    assert result.unresolved_rows == (2,)


@pytest.mark.parametrize(
    "observations", [(role(1, "student"), role(1, "staff")), (role(2, "student"),)]
)
def test_observations_cannot_overwrite_or_escape_snapshot(
    observations: tuple[KakaoMessageObservation, ...],
) -> None:
    with pytest.raises(ValueError, match="EVIDENCE"):
        normalize(csv_bytes([["2026-11-01 00:00:00", "A", "x"]]), observations=observations)


def test_known_role_requires_explicit_evidence() -> None:
    with pytest.raises(ValidationError, match="ROLE_EVIDENCE"):
        KakaoMessageObservation(row_ordinal=1, role="student")


def test_same_snapshot_alignment_preserves_repeated_multiplicity() -> None:
    source = csv_bytes([["2026-11-01 00:00:00", "A", "same"]] * 3)
    previous = normalize(source)
    current = normalize(source, snapshot_revision_id="kakaosnapshotrev_" + "5" * 32)
    result = align_kakao_snapshots(previous, current)
    assert [(m.previous_row, m.current_row) for m in result.matches] == [(1, 1), (2, 2), (3, 3)]
    assert all(m.level == "SEQUENCE_INFERRED" for m in result.matches)


def test_ambiguous_duplicate_window_is_not_merged_or_deleted() -> None:
    previous = normalize(csv_bytes([["2026-11-01 00:00:00", "A", "same"]] * 3))
    current = normalize(csv_bytes([["2026-11-01 00:00:00", "A", "same"]] * 2))
    result = align_kakao_snapshots(previous, current)
    assert result.matches == ()
    assert result.previous_unmatched == (1, 2, 3)
    assert result.current_unresolved == (1, 2)


def test_bounded_anchor_window_preserves_equal_repeats() -> None:
    def source(texts: list[str]) -> bytes:
        return csv_bytes([["2026-11-01 00:00:00", "A", text] for text in texts])

    previous = normalize(source(["anchor-a", "same", "same", "anchor-b"]))
    current = normalize(source(["prefix", "anchor-a", "same", "same", "anchor-b", "suffix"]))
    result = align_kakao_snapshots(previous, current)
    assert [(m.previous_row, m.current_row) for m in result.matches] == [
        (1, 2),
        (2, 3),
        (3, 4),
        (4, 5),
    ]
    assert result.current_unresolved == (1, 6)
    assert align_kakao_snapshots(previous, current, max_overlap_window=3).matches == ()


def test_provider_id_change_is_not_overwritten_and_scope_is_checked() -> None:
    source = csv_bytes([["2026-11-01 00:00:00", "A", "old"]])
    previous = normalize(source, observations=(role(1, "student", source_message_id="stable-1"),))
    current = normalize(
        source.replace(b"old", b"new"),
        observations=(role(1, "student", source_message_id="stable-1"),),
    )
    result = align_kakao_snapshots(previous, current)
    assert result.matches[0].source_content_changed
    assert result.matches[0].level == "SOURCE_VERIFIED"
    other = normalize(source, room_id="kakaoroom_" + "9" * 32)
    with pytest.raises(ValueError, match="SCOPE_MISMATCH"):
        align_kakao_snapshots(previous, other)


def test_period_is_half_open_and_invalid_dates_fail() -> None:
    assert question_period_utc(date(2026, 10, 1), date(2026, 10, 31)) == (
        datetime(2026, 9, 30, 15, tzinfo=UTC),
        datetime(2026, 10, 31, 15, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="PERIOD_INVALID"):
        question_period_utc(date(2026, 11, 1), date(2026, 10, 31))


def test_alignment_evidence_change_marks_reviewed_content_stale() -> None:
    source = csv_bytes([["2026-11-01 00:00:00", "A", "same"]])
    previous = normalize(source, observations=(role(1, "student"),))
    current = normalize(source, observations=(role(1, "staff"),))
    match = align_kakao_snapshots(previous, current).matches[0]
    assert not match.source_content_changed
    assert match.evidence_changed


def test_provider_anchors_reordering_disables_inferred_matches() -> None:
    source = csv_bytes([["2026-11-01 00:00:00", "A", str(i)] for i in range(4)])
    previous = normalize(
        source,
        observations=(
            role(1, "student", source_message_id="a"),
            role(4, "student", source_message_id="b"),
        ),
    )
    current = normalize(
        source,
        observations=(
            role(1, "student", source_message_id="b"),
            role(4, "student", source_message_id="a"),
        ),
    )
    result = align_kakao_snapshots(previous, current)
    assert [(m.previous_row, m.current_row) for m in result.matches] == [(4, 1), (1, 4)]
    assert result.current_unresolved == (2, 3)
    assert all(m.level == "SOURCE_VERIFIED" for m in result.matches)


def test_changed_attachment_observation_invalidates_same_csv_review() -> None:
    source = csv_bytes([["2026-11-01 00:00:00", "A", "사진"]])
    attachment = KakaoAttachmentObservation(
        attachment_id="kakaoattachment_" + "1" * 32,
        attachment_revision_id="kakaoattachmentrev_" + "1" * 32,
        album_ordinal=1,
        availability="available",
        association="SOURCE_VERIFIED",
    )
    previous = normalize(source, observations=(role(1, "student"),))
    current = normalize(
        source, observations=(role(1, "student", kind="attachment", attachments=(attachment,)),)
    )
    assert align_kakao_snapshots(previous, current).matches[0].evidence_changed


def test_duplicate_source_identity_and_controls_in_extras_rejected() -> None:
    source = csv_bytes([["2026-11-01 00:00:00", "A", "text"]] * 2)
    with pytest.raises(ValueError, match="OBSERVATION_INVALID"):
        normalize(
            source, observations=tuple(role(i, "student", source_message_id="same") for i in (1, 2))
        )
    with pytest.raises(ValueError, match="OBSERVATION_INVALID"):
        normalize(
            csv_bytes(
                [["2026-11-01 00:00:00", "A", "text", "bad\x00"]],
                ("DATE", "USER", "MESSAGE", "EXTRA"),
            )
        )


def test_resource_schema_mirrors_match() -> None:
    root = Path(__file__).resolve().parents[2]
    for name in ("message-normalization-v1", "question-candidates-v1"):
        canonical = root / "schemas" / "kakao-archive" / f"{name}.schema.json"
        mirror = (
            root
            / "packages/catalog_contracts/eom_catalog_contracts/resources/kakao-archive"
            / f"{name}.schema.json"
        )
        assert canonical.read_bytes() == mirror.read_bytes()


def test_linear_large_repeat_snapshot_preserves_multiplicity() -> None:
    # 10k repeated rows make global LCS inappropriate. Instrument signature visits
    # rather than a wall-clock threshold sensitive to host background load.
    source = csv_bytes([["2026-11-01 00:00:00", "A", "same"]] * 10000)
    previous = normalize(source)
    current = normalize(source, snapshot_revision_id="kakaosnapshotrev_" + "5" * 32)
    assert len(align_kakao_snapshots(previous, current).matches) == 10000


def test_row_and_byte_limits_are_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    import eom_catalog_service.kakao_csv_parser as parser

    source = csv_bytes([["2026-11-01 00:00:00", "A", "same"]] * 3)
    monkeypatch.setattr(parser, "MAX_CSV_ROWS", 2)
    with pytest.raises(ValueError, match="ROW_LIMIT"):
        normalize(source)
    monkeypatch.setattr(parser, "MAX_CSV_BYTES", len(source) - 1)
    with pytest.raises(ValueError, match="SIZE_INVALID"):
        normalize(source)
