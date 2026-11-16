"""Conservative O(n+m) snapshot correspondence, not destructive deduplication.

The result is a small internal proposal. Only the acceptance owner may persist its
decisions and canonical occurrence IDs. No source deletion is inferred here.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import pairwise

from eom_catalog_contracts.kakao_archive import (
    AssociationLevel,
    KakaoMessageNormalization,
    KakaoNormalizedMessage,
)


@dataclass(frozen=True)
class KakaoRowMatch:
    previous_row: int
    current_row: int
    level: AssociationLevel
    source_content_changed: bool = False
    evidence_changed: bool = False


@dataclass(frozen=True)
class KakaoAlignmentProposal:
    matches: tuple[KakaoRowMatch, ...]
    previous_unmatched: tuple[int, ...]
    current_unresolved: tuple[int, ...]


def _fingerprint(message: KakaoNormalizedMessage) -> tuple[str, str, str, tuple[str, ...]]:
    return message.raw_date, message.raw_sender, message.text, message.extra_values


def _evidence_changed(old: KakaoNormalizedMessage, new: KakaoNormalizedMessage) -> bool:
    # Corrected directions/attachments can invalidate reviewed questions even when
    # the provider's CSV bytes are identical. This is not a new message identity.
    return (old.role, old.role_evidence_id, old.kind, old.attachments, old.sent_at_utc) != (
        new.role,
        new.role_evidence_id,
        new.kind,
        new.attachments,
        new.sent_at_utc,
    )


def align_kakao_snapshots(
    previous: KakaoMessageNormalization,
    current: KakaoMessageNormalization,
    *,
    max_overlap_window: int = 2048,
) -> KakaoAlignmentProposal:
    """Verified IDs first; unique ordered anchors only within a bounded overlap.

    Repeated values inside two anchors match only with equal sequence/multiplicity.
    An unmatched old row is not a deletion. An unresolved new row is not silently
    an insertion: the caller may expose a complete snapshot-only projection.
    """
    if (previous.source_binding_id, previous.room_id) != (
        current.source_binding_id,
        current.room_id,
    ):
        raise ValueError("KAKAO_ARCHIVE_ALIGNMENT_SCOPE_MISMATCH")
    if type(max_overlap_window) is not int or not 1 <= max_overlap_window <= 2048:
        raise ValueError("KAKAO_ARCHIVE_ALIGNMENT_WINDOW_INVALID")
    old_ids = {m.source_message_id: m for m in previous.messages if m.source_message_id is not None}
    matches: dict[int, KakaoRowMatch] = {}
    used: set[int] = set()
    for message in current.messages:
        old = (
            old_ids.get(message.source_message_id)
            if message.source_message_id is not None
            else None
        )
        if old is not None:
            matches[message.row_ordinal] = KakaoRowMatch(
                old.row_ordinal,
                message.row_ordinal,
                "SOURCE_VERIFIED",
                _fingerprint(old) != _fingerprint(message),
                _evidence_changed(old, message),
            )
            used.add(old.row_ordinal)

    def infer(old: KakaoNormalizedMessage, new: KakaoNormalizedMessage) -> None:
        if new.row_ordinal in matches or old.row_ordinal in used:
            return
        # An observed different provider ID contradicts an inferred correspondence.
        if old.source_message_id is not None or new.source_message_id is not None:
            return
        matches[new.row_ordinal] = KakaoRowMatch(
            old.row_ordinal,
            new.row_ordinal,
            "SEQUENCE_INFERRED",
            evidence_changed=_evidence_changed(old, new),
        )
        used.add(old.row_ordinal)

    if previous.source_sha256 == current.source_sha256 and previous.columns == current.columns:
        if len(previous.messages) != len(current.messages):
            raise ValueError("KAKAO_ARCHIVE_ALIGNMENT_SOURCE_INCONSISTENT")
        for old, new in zip(previous.messages, current.messages, strict=True):
            if _fingerprint(old) != _fingerprint(new):
                raise ValueError("KAKAO_ARCHIVE_ALIGNMENT_SOURCE_INCONSISTENT")
            infer(old, new)
    elif previous.source_order != "unknown" and current.source_order != "unknown":
        old_rows = (
            previous.messages
            if previous.source_order == "ascending"
            else tuple(reversed(previous.messages))
        )
        new_rows = (
            current.messages
            if current.source_order == "ascending"
            else tuple(reversed(current.messages))
        )
        old_counts = Counter(_fingerprint(m) for m in old_rows)
        new_counts = Counter(_fingerprint(m) for m in new_rows)
        positions = {
            _fingerprint(m): i for i, m in enumerate(old_rows) if old_counts[_fingerprint(m)] == 1
        }
        anchors = [
            (positions[key], i)
            for i, message in enumerate(new_rows)
            if (key := _fingerprint(message)) in positions and new_counts[key] == 1
        ]
        for (old_start, new_start), (old_end, new_end) in pairwise(anchors):
            old_size, new_size = old_end - old_start + 1, new_end - new_start + 1
            if old_size != new_size or not 2 <= old_size <= max_overlap_window:
                continue
            old_window = old_rows[old_start : old_end + 1]
            new_window = new_rows[new_start : new_end + 1]
            if all(
                _fingerprint(old) == _fingerprint(new)
                for old, new in zip(old_window, new_window, strict=True)
            ):
                for old, new in zip(old_window, new_window, strict=True):
                    infer(old, new)
    # A source-ID anchor and an inferred sequence must not contradict each other.
    # Source identity remains valid even across observed order changes; discard all
    # inferred proposals in that case instead of quietly manufacturing one order.
    old_sequence = (
        previous.messages
        if previous.source_order != "descending"
        else tuple(reversed(previous.messages))
    )
    new_sequence = (
        current.messages
        if current.source_order != "descending"
        else tuple(reversed(current.messages))
    )
    old_position = {message.row_ordinal: i for i, message in enumerate(old_sequence)}
    matched_positions = [
        old_position[matches[m.row_ordinal].previous_row]
        for m in new_sequence
        if m.row_ordinal in matches
    ]
    if any(first >= second for first, second in pairwise(matched_positions)):
        matches = {row: match for row, match in matches.items() if match.level == "SOURCE_VERIFIED"}
        used = {match.previous_row for match in matches.values()}
    return KakaoAlignmentProposal(
        matches=tuple(matches[m.row_ordinal] for m in current.messages if m.row_ordinal in matches),
        previous_unmatched=tuple(
            m.row_ordinal for m in previous.messages if m.row_ordinal not in used
        ),
        current_unresolved=tuple(
            m.row_ordinal for m in current.messages if m.row_ordinal not in matches
        ),
    )
