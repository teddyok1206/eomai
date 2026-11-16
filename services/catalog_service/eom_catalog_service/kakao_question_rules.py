"""Linear turn_v1 candidates with explicit uncertainty; never educational AI inference."""

from __future__ import annotations

from datetime import date

from eom_catalog_contracts.kakao_archive import (
    KakaoMessageNormalization,
    KakaoNormalizedMessage,
    KakaoQuestionCandidate,
    KakaoQuestionCandidates,
    ReviewReason,
)
from eom_catalog_contracts.kakao_question import question_period_utc as question_period_utc


def build_question_candidates(source: KakaoMessageNormalization) -> KakaoQuestionCandidates:
    """Return source-row references, preserving all observed student attachments.

    Unknown senders are barriers, not permission to merge surrounding turns. Rules
    do not overwrite a reviewed question: the acceptance owner issues its revisions.
    """
    if source.source_order == "unknown":
        raise ValueError("KAKAO_ARCHIVE_SOURCE_ORDER_UNVERIFIED")
    ordered = (
        source.messages if source.source_order == "ascending" else tuple(reversed(source.messages))
    )
    groups: list[tuple[list[KakaoNormalizedMessage], list[KakaoNormalizedMessage], bool]] = []
    unresolved: list[int] = []
    students: list[KakaoNormalizedMessage] = []
    replies: list[KakaoNormalizedMessage] = []
    uncertain = False
    for message in ordered:
        if message.role == "system":
            continue
        if message.role == "unknown":
            unresolved.append(message.row_ordinal)
            if students:
                groups.append((students, replies, True))
                students, replies = [], []
            uncertain = True
        elif message.role == "student":
            if students and replies:
                groups.append((students, replies, uncertain))
                students, replies, uncertain = [], [], False
            students.append(message)
        elif students:
            replies.append(message)
    if students:
        groups.append((students, replies, uncertain))

    candidates: list[KakaoQuestionCandidate] = []
    for student_messages, staff_messages, boundary_uncertain in groups:
        if all(m.kind == "deleted" and not m.attachments for m in student_messages):
            unresolved.extend(m.row_ordinal for m in (*student_messages, *staff_messages))
            continue
        reasons: set[ReviewReason] = set()
        if boundary_uncertain:
            reasons.add("UNKNOWN_SENDER")
        if source.source_timezone == "unknown":
            reasons.add("TIMEZONE_UNVERIFIED")
        if not source.context_start_verified or not source.context_end_verified:
            reasons.add("SOURCE_SCOPE_UNVERIFIED")
        attachments = tuple(a for m in student_messages for a in m.attachments)
        if any(a.availability != "available" for a in attachments):
            reasons.add("ATTACHMENT_UNAVAILABLE")
        if any(a.association not in {"SOURCE_VERIFIED", "MANUAL_CONFIRMED"} for a in attachments):
            reasons.add("ATTACHMENT_ASSOCIATION_UNRESOLVED")
        if any(m.text == "사진" and m.kind == "unknown" for m in student_messages):
            reasons.add("PHOTO_MARKER_UNVERIFIED")
        if any(m.kind == "attachment" and not m.attachments for m in student_messages):
            reasons.add("ATTACHMENT_UNAVAILABLE")
        if any(m.kind == "deleted" for m in student_messages):
            reasons.add("SOURCE_DELETION")
        candidates.append(
            KakaoQuestionCandidate(
                candidate_ordinal=len(candidates) + 1,
                student_rows=tuple(m.row_ordinal for m in student_messages),
                reply_rows=tuple(m.row_ordinal for m in staff_messages),
                attachments=attachments,
                first_student_at_utc=student_messages[0].sent_at_utc,
                boundary_uncertain=boundary_uncertain,
                review_reasons=tuple(sorted(reasons)),
            )
        )
    return KakaoQuestionCandidates(
        source_binding_id=source.source_binding_id,
        room_id=source.room_id,
        normalization_revision_id=source.normalization_revision_id,
        candidates=tuple(candidates),
        unresolved_rows=tuple(unresolved),
    )


def select_question_period(
    candidates: KakaoQuestionCandidates, start_date: date, end_date_inclusive: date
) -> tuple[KakaoQuestionCandidate, ...]:
    """Filter *after* grouping; never silently exclude an unknown timestamp."""
    start, end = question_period_utc(start_date, end_date_inclusive)
    if any(candidate.first_student_at_utc is None for candidate in candidates.candidates):
        raise ValueError("KAKAO_ARCHIVE_TIMEZONE_UNVERIFIED")
    return tuple(
        candidate
        for candidate in candidates.candidates
        if candidate.first_student_at_utc is not None
        and start <= candidate.first_student_at_utc < end
    )
