"""Deterministic question editing and packet selection, with no persistence or AI.

Resolved input indexes are built once in O(source rows). Editing costs O(selected
blocks); span-overlap/split validation uses O(blocks log blocks), never all-history
pairwise matching. The caller owns current ACL/mapping/lifecycle and Artifact reads.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from itertools import pairwise
from types import MappingProxyType
from typing import Literal, cast

from eom_catalog_contracts.kakao_archive import (
    KakaoAttachmentObservation,
    KakaoMessageNormalization,
    KakaoNormalizedMessage,
    KakaoQuestionCandidate,
    ReviewReason,
)
from eom_catalog_contracts.kakao_question import (
    NORMALIZATION_REF,
    QUESTION_REF,
    FinalBlocker,
    KakaoNormalizationRef,
    KakaoPacketQuestion,
    KakaoPacketStudentSubset,
    KakaoQuestionBlock,
    KakaoQuestionConfirm,
    KakaoQuestionEditCommand,
    KakaoQuestionExclude,
    KakaoQuestionImage,
    KakaoQuestionManifest,
    KakaoQuestionPacket,
    KakaoQuestionProvenance,
    KakaoQuestionReviewDecision,
    KakaoQuestionStudentPin,
    KakaoQuestionText,
    question_period_utc,
)
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer

from eom_catalog_service.kakao_question_rules import build_question_candidates


@dataclass(frozen=True, slots=True)
class KakaoAttachmentSource:
    """Already owner-resolved image association; no local file or inline image bytes."""

    attachment_revision_id: str
    pointer: ArtifactMemberPointer
    quality: Literal["ORIGINAL", "BEST_AVAILABLE", "UNKNOWN"]


@dataclass(frozen=True, slots=True)
class ResolvedKakaoQuestionSource:
    normalization: KakaoMessageNormalization
    pointer: ArtifactMemberPointer
    occurrence_ids: Mapping[int, str]
    attachments: Mapping[str, KakaoAttachmentSource]
    messages: Mapping[int, KakaoNormalizedMessage] = field(init=False, repr=False)
    candidates: Mapping[int, KakaoQuestionCandidate] = field(init=False, repr=False)
    unresolved_rows: tuple[int, ...] = field(init=False, repr=False)
    observations: Mapping[str, tuple[int, KakaoAttachmentObservation]] = field(
        init=False, repr=False
    )
    text_hashes: Mapping[int, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if (
            self.pointer.schema_ref != NORMALIZATION_REF
            or self.pointer.media_type != "application/json"
        ):
            raise ValueError("KAKAO_ARCHIVE_NORMALIZATION_POINTER_INVALID")
        if self.pointer.sha256 != sha256_bytes(
            canonical_json_bytes(self.normalization.model_dump(mode="json"))
        ):
            raise ValueError("KAKAO_ARCHIVE_NORMALIZATION_HASH_MISMATCH")
        occurrences = dict(self.occurrence_ids)
        rows = {message.row_ordinal: message for message in self.normalization.messages}
        if set(occurrences) != set(rows) or len(set(occurrences.values())) != len(occurrences):
            raise ValueError("KAKAO_ARCHIVE_OCCURRENCE_INDEX_INVALID")
        if any(
            not re.fullmatch(r"kakaomessage_[0-9a-f]{32}", value) for value in occurrences.values()
        ):
            raise ValueError("KAKAO_ARCHIVE_OCCURRENCE_INDEX_INVALID")
        object.__setattr__(self, "occurrence_ids", MappingProxyType(occurrences))
        object.__setattr__(self, "attachments", MappingProxyType(dict(self.attachments)))
        object.__setattr__(self, "messages", MappingProxyType(rows))
        object.__setattr__(
            self,
            "text_hashes",
            MappingProxyType(
                {row: sha256_bytes(message.text.encode("utf-8")) for row, message in rows.items()}
            ),
        )
        object.__setattr__(
            self,
            "observations",
            MappingProxyType(
                {
                    attachment.attachment_id: (message.row_ordinal, attachment)
                    for message in self.normalization.messages
                    for attachment in message.attachments
                }
            ),
        )
        candidates = build_question_candidates(self.normalization)
        object.__setattr__(self, "unresolved_rows", candidates.unresolved_rows)
        object.__setattr__(
            self,
            "candidates",
            MappingProxyType(
                {candidate.candidate_ordinal: candidate for candidate in candidates.candidates}
            ),
        )

    @property
    def reference(self) -> KakaoNormalizationRef:
        return KakaoNormalizationRef(
            normalization_revision_id=self.normalization.normalization_revision_id,
            snapshot_revision_id=self.normalization.snapshot_revision_id,
            pointer=self.pointer,
        )


@dataclass(frozen=True, slots=True)
class PublishedKakaoQuestion:
    question: KakaoQuestionManifest
    pointer: ArtifactMemberPointer

    def __post_init__(self) -> None:
        if self.pointer.schema_ref != QUESTION_REF or self.pointer.media_type != "application/json":
            raise ValueError("KAKAO_ARCHIVE_QUESTION_POINTER_INVALID")
        if self.pointer.sha256 != sha256_bytes(
            canonical_json_bytes(self.question.model_dump(mode="json"))
        ):
            raise ValueError("KAKAO_ARCHIVE_QUESTION_HASH_MISMATCH")


def _hangul_kind(char: str) -> str:
    code = ord(char)
    if 0x1100 <= code <= 0x115F or 0xA960 <= code <= 0xA97C:
        return "L"
    if 0x1160 <= code <= 0x11A7 or 0xD7B0 <= code <= 0xD7C6:
        return "V"
    if 0x11A8 <= code <= 0x11FF or 0xD7CB <= code <= 0xD7FB:
        return "T"
    if 0xAC00 <= code <= 0xD7A3:
        return "LV" if (code - 0xAC00) % 28 == 0 else "LVT"
    return ""


def _boundary(text: str, offset: int) -> bool:
    if offset in (0, len(text)):
        return True
    previous, following = text[offset - 1], text[offset]
    code = ord(following)
    if (
        unicodedata.category(following) in {"Mn", "Mc", "Me"}
        or 0xFE00 <= code <= 0xFE0F
        or 0xE0100 <= code <= 0xE01EF
        or 0x1F3FB <= code <= 0x1F3FF
        or "\u200d" in (previous, following)
        or (previous == "\r" and following == "\n")
    ):
        return False
    left, right = _hangul_kind(previous), _hangul_kind(following)
    if (
        (left == "L" and right in {"L", "V", "LV", "LVT"})
        or (left in {"LV", "V"} and right in {"V", "T"})
        or (left in {"LVT", "T"} and right == "T")
    ):
        return False
    if 0x1F1E6 <= ord(previous) <= 0x1F1FF and 0x1F1E6 <= code <= 0x1F1FF:
        run = 0
        for char in reversed(text[:offset]):
            if not 0x1F1E6 <= ord(char) <= 0x1F1FF:
                break
            run += 1
        return run % 2 == 0
    return True


def validate_codepoint_span(text: str, start: int, end: int) -> str:
    if any(0xD800 <= ord(char) <= 0xDFFF for char in text):
        raise ValueError("KAKAO_ARCHIVE_TEXT_SPAN_INVALID")
    return _checked_source_span(text, start, end)


def _checked_source_span(text: str, start: int, end: int) -> str:
    if (
        type(start) is not int
        or type(end) is not int
        or not 0 <= start < end <= len(text)
        or not _boundary(text, start)
        or not _boundary(text, end)
    ):
        raise ValueError("KAKAO_ARCHIVE_TEXT_SPAN_INVALID")
    return text[start:end]


def utf16_offset_to_codepoint(text: str, offset: int) -> int:
    """Convert browser UTF-16 once; never store JS offsets as source codepoint spans."""
    if type(offset) is not int or offset < 0 or any(0xD800 <= ord(char) <= 0xDFFF for char in text):
        raise ValueError("KAKAO_ARCHIVE_TEXT_SPAN_INVALID")
    consumed = 0
    for position, char in enumerate(text):
        if consumed == offset:
            if not _boundary(text, position):
                raise ValueError("KAKAO_ARCHIVE_TEXT_SPAN_INVALID")
            return position
        consumed += 2 if ord(char) > 0xFFFF else 1
        if consumed > offset:
            raise ValueError("KAKAO_ARCHIVE_TEXT_SPAN_INVALID")
    if consumed == offset:
        return len(text)
    raise ValueError("KAKAO_ARCHIVE_TEXT_SPAN_INVALID")


def _contexts(
    question: KakaoQuestionManifest, sources: tuple[ResolvedKakaoQuestionSource, ...]
) -> dict[str, ResolvedKakaoQuestionSource]:
    result = {source.normalization.normalization_revision_id: source for source in sources}
    if len(result) != len(sources):
        raise ValueError("KAKAO_ARCHIVE_SOURCE_DUPLICATED")
    for reference in question.sources:
        source = result.get(reference.normalization_revision_id)
        if source is None or source.reference != reference:
            raise ValueError("KAKAO_ARCHIVE_SOURCE_REFERENCE_INVALID")
    if any(
        source.normalization.source_binding_id != question.source_binding_id
        or source.normalization.room_id != question.room_id
        for source in sources
    ):
        raise ValueError("KAKAO_ARCHIVE_SOURCE_SCOPE_INVALID")
    return result


def _validate_blocks(
    blocks: tuple[KakaoQuestionBlock, ...], sources: Mapping[str, ResolvedKakaoQuestionSource]
) -> None:
    spans: dict[tuple[str, str], list[tuple[int, int]]] = {}
    occurrence_normalizations: dict[str, str] = {}
    for block in blocks:
        if (
            occurrence_normalizations.setdefault(
                block.source_occurrence_id, block.normalization_revision_id
            )
            != block.normalization_revision_id
        ):
            raise ValueError("KAKAO_ARCHIVE_OCCURRENCE_REVISION_CONFLICT")
        source = sources.get(block.normalization_revision_id)
        message = source.messages.get(block.row_ordinal) if source else None
        if (
            source is None
            or message is None
            or source.occurrence_ids[block.row_ordinal] != block.source_occurrence_id
            or message.role != block.role
            or message.sent_at_utc != block.sent_at_utc
        ):
            raise ValueError("KAKAO_ARCHIVE_BLOCK_SOURCE_MISMATCH")
        if isinstance(block, KakaoQuestionText):
            if block.source_text_sha256 != source.text_hashes[block.row_ordinal]:
                raise ValueError("KAKAO_ARCHIVE_TEXT_HASH_MISMATCH")
            _checked_source_span(message.text, block.start_codepoint, block.end_codepoint)
            spans.setdefault(
                (block.normalization_revision_id, block.source_occurrence_id), []
            ).append((block.start_codepoint, block.end_codepoint))
        else:
            observed = source.observations.get(block.attachment_id)
            attachment = observed[1] if observed and observed[0] == block.row_ordinal else None
            if attachment is None or (
                attachment.attachment_revision_id != block.attachment_revision_id
                or attachment.availability != block.availability
                or attachment.association != block.association
            ):
                raise ValueError("KAKAO_ARCHIVE_ATTACHMENT_SOURCE_MISMATCH")
            materialized = source.attachments.get(block.attachment_id)
            if block.availability == "available" and (
                materialized is None
                or materialized.attachment_revision_id != block.attachment_revision_id
                or materialized.pointer != block.source_pointer
                or materialized.quality != block.source_quality
            ):
                raise ValueError("KAKAO_ARCHIVE_IMAGE_POINTER_INVALID")
    for ranges in spans.values():
        ordered = sorted(ranges)
        if any(left[1] > right[0] for left, right in pairwise(ordered)):
            raise ValueError("KAKAO_ARCHIVE_TEXT_SPAN_OVERLAP")


def validate_question_sources(
    question: KakaoQuestionManifest, sources: tuple[ResolvedKakaoQuestionSource, ...]
) -> None:
    """Validate exact content before publication; current ACL/mapping stays with the owner."""
    contexts = _contexts(question, sources)
    _validate_blocks(question.ordered_blocks, contexts)
    if question.review_reasons != _reasons(
        question.ordered_blocks, contexts, boundary_uncertain=question.boundary_uncertain
    ):
        raise ValueError("KAKAO_ARCHIVE_REVIEW_REASONS_MISMATCH")


def resolve_question_text(block: KakaoQuestionText, source: ResolvedKakaoQuestionSource) -> str:
    """Materialize only an exact selected span (or its explicit override) for output."""
    _validate_blocks((block,), {source.normalization.normalization_revision_id: source})
    return (
        block.display_override.text
        if block.display_override
        else source.messages[block.row_ordinal].text[block.start_codepoint : block.end_codepoint]
    )


def _first_student(blocks: tuple[KakaoQuestionBlock, ...]) -> datetime | None:
    values = [block.sent_at_utc for block in blocks if block.role == "student"]
    if not values:
        raise ValueError("KAKAO_ARCHIVE_STUDENT_SELECTION_EMPTY")
    return min(cast(list[datetime], values)) if all(value is not None for value in values) else None


def _reasons(
    blocks: tuple[KakaoQuestionBlock, ...],
    sources: Mapping[str, ResolvedKakaoQuestionSource],
    *,
    boundary_uncertain: bool,
) -> tuple[ReviewReason, ...]:
    reasons: set[ReviewReason] = {"UNKNOWN_SENDER"} if boundary_uncertain else set()
    rows = {
        (block.normalization_revision_id, block.row_ordinal)
        for block in blocks
        if block.role == "student"
    }
    for normalization_id, row in rows:
        source = sources[normalization_id]
        message = source.messages[row]
        if message.sent_at_utc is None:
            reasons.add("TIMEZONE_UNVERIFIED")
        if (
            not source.normalization.context_start_verified
            or not source.normalization.context_end_verified
        ):
            reasons.add("SOURCE_SCOPE_UNVERIFIED")
        if message.kind == "deleted":
            reasons.add("SOURCE_DELETION")
        if message.kind == "unknown" and message.text == "사진":
            reasons.add("PHOTO_MARKER_UNVERIFIED")
        if message.kind == "attachment" and not message.attachments:
            reasons.add("ATTACHMENT_UNAVAILABLE")
    return tuple(sorted(reasons))


def question_from_candidate(
    source: ResolvedKakaoQuestionSource,
    candidate: KakaoQuestionCandidate,
    *,
    question_id: str,
    question_revision_id: str,
    student: KakaoQuestionStudentPin | None,
    actor_id: str,
    created_at: datetime,
) -> KakaoQuestionManifest:
    if source.candidates.get(candidate.candidate_ordinal) != candidate:
        raise ValueError("KAKAO_ARCHIVE_CANDIDATE_MISMATCH")
    blocks: list[KakaoQuestionBlock] = []
    for row in (*candidate.student_rows, *candidate.reply_rows):
        message = source.messages[row]
        occurrence = source.occurrence_ids[row]
        common = {
            "source_occurrence_id": occurrence,
            "normalization_revision_id": source.normalization.normalization_revision_id,
            "row_ordinal": row,
            "role": message.role,
            "sent_at_utc": message.sent_at_utc,
        }
        if message.text:
            blocks.append(
                KakaoQuestionText.model_validate(
                    {
                        **common,
                        "block_id": f"{occurrence}:text:0:{len(message.text)}",
                        "source_text_sha256": sha256_bytes(message.text.encode("utf-8")),
                        "start_codepoint": 0,
                        "end_codepoint": len(message.text),
                    }
                )
            )
        for attachment in message.attachments:
            materialized = source.attachments.get(attachment.attachment_id)
            blocks.append(
                KakaoQuestionImage.model_validate(
                    {
                        **common,
                        "block_id": attachment.attachment_id,
                        "attachment_id": attachment.attachment_id,
                        "attachment_revision_id": attachment.attachment_revision_id,
                        "availability": attachment.availability,
                        "association": attachment.association,
                        "source_pointer": materialized.pointer
                        if materialized and attachment.availability == "available"
                        else None,
                        "source_quality": materialized.quality
                        if materialized and attachment.availability == "available"
                        else "UNKNOWN",
                    }
                )
            )
    selected = tuple(blocks)
    contexts = {source.normalization.normalization_revision_id: source}
    _validate_blocks(selected, contexts)
    return KakaoQuestionManifest(
        question_id=question_id,
        question_revision_id=question_revision_id,
        previous_revision_id=None,
        source_binding_id=source.normalization.source_binding_id,
        room_id=source.normalization.room_id,
        student=student,
        sources=(source.reference,),
        ordered_blocks=selected,
        first_student_at_utc=_first_student(selected),
        review_reasons=_reasons(
            selected, contexts, boundary_uncertain=candidate.boundary_uncertain
        ),
        boundary_uncertain=candidate.boundary_uncertain,
        created_by=actor_id,
        created_at=created_at,
    )


def question_final_blockers(
    question: KakaoQuestionManifest, *, include_replies: bool = False
) -> tuple[FinalBlocker, ...]:
    blockers: set[FinalBlocker] = set()
    if question.review_state != "CONFIRMED":
        blockers.add("EXCLUDED" if question.review_state == "EXCLUDED" else "NOT_REVIEWED")
    if question.student is None:
        blockers.add("STUDENT_UNMAPPED")
    if question.first_student_at_utc is None:
        blockers.add("TIMEZONE_UNVERIFIED")
    if (
        question.boundary_uncertain or "SOURCE_SCOPE_UNVERIFIED" in question.review_reasons
    ) and not (question.review_decision and question.review_decision.boundary_confirmed):
        blockers.add("BOUNDARY_UNCONFIRMED")
    if question.source_stale:
        blockers.add("STALE_SOURCE")
    for reason in ("PHOTO_MARKER_UNVERIFIED", "SOURCE_DELETION"):
        if reason in question.review_reasons:
            blockers.add(cast(FinalBlocker, reason))
    if "ATTACHMENT_UNAVAILABLE" in question.review_reasons:
        blockers.add("MISSING_ATTACHMENT")
    for block in question.ordered_blocks:
        if not isinstance(block, KakaoQuestionImage) or (
            block.role == "staff" and not include_replies
        ):
            continue
        if block.availability != "available":
            blockers.add("MISSING_ATTACHMENT")
        if block.association not in {"SOURCE_VERIFIED", "MANUAL_CONFIRMED"}:
            blockers.add("ATTACHMENT_UNRESOLVED")
        if block.source_quality != "ORIGINAL" and not block.quality_acceptance:
            blockers.add("IMAGE_QUALITY_UNCONFIRMED")
    return tuple(sorted(blockers))


def mark_question_source_stale(
    question: KakaoQuestionManifest,
    *,
    expected_revision_id: str,
    question_revision_id: str,
    actor_id: str,
    created_at: datetime,
) -> KakaoQuestionManifest:
    """Owner-detected source change creates an unreviewed successor, not a historical rewrite.

    This records invalidation only. Rebinding revised source occurrences needs a new
    validated selection; callers cannot recover review by clearing a boolean.
    """
    if expected_revision_id != question.question_revision_id:
        raise ValueError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
    if question_revision_id == question.question_revision_id or created_at < question.created_at:
        raise ValueError("KAKAO_ARCHIVE_REVISION_REUSED")
    if question.source_stale:
        raise ValueError("KAKAO_ARCHIVE_STALE_SOURCE")
    return KakaoQuestionManifest.model_validate(
        {
            **question.model_dump(mode="json"),
            "question_revision_id": question_revision_id,
            "previous_revision_id": question.question_revision_id,
            "source_stale": True,
            "review_state": "UNREVIEWED",
            "review_decision": None,
            "created_by": actor_id,
            "created_at": created_at,
        }
    )


def edit_question(
    question: KakaoQuestionManifest,
    command: KakaoQuestionEditCommand,
    *,
    question_revision_id: str,
    actor_id: str,
    created_at: datetime,
    sources: tuple[ResolvedKakaoQuestionSource, ...],
) -> KakaoQuestionManifest:
    validate_contract("kakao-question-edit-v1", command.model_dump(mode="json"))
    if command.parent_revision_id != question.question_revision_id:
        raise ValueError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
    if question_revision_id == question.question_revision_id or created_at < question.created_at:
        raise ValueError("KAKAO_ARCHIVE_REVISION_REUSED")
    contexts = _contexts(question, sources)
    _validate_blocks(question.ordered_blocks, contexts)
    changes: dict[str, object] = {
        "question_revision_id": question_revision_id,
        "previous_revision_id": question.question_revision_id,
        "created_by": actor_id,
        "created_at": created_at,
    }
    if isinstance(command, (KakaoQuestionConfirm, KakaoQuestionExclude)):
        if isinstance(command, KakaoQuestionConfirm) and question.source_stale:
            raise ValueError("KAKAO_ARCHIVE_STALE_SOURCE")
        changes.update(
            review_state="CONFIRMED" if isinstance(command, KakaoQuestionConfirm) else "EXCLUDED",
            review_decision=KakaoQuestionReviewDecision(
                actor_id=actor_id,
                decided_at=created_at,
                reason=command.reason,
                boundary_confirmed=command.boundary_confirmed
                if isinstance(command, KakaoQuestionConfirm)
                else False,
            ).model_dump(mode="json"),
        )
    else:
        _validate_blocks(command.ordered_blocks, contexts)
        old = {block.block_id: block for block in question.ordered_blocks}
        new = {block.block_id: block for block in command.ordered_blocks}
        removed = set(old) - set(new)
        if {exclusion.block_id for exclusion in command.selection_exclusions} != removed:
            raise ValueError("KAKAO_ARCHIVE_REMOVAL_REASON_REQUIRED")
        for block in command.ordered_blocks:
            previous = old.get(block.block_id)
            if isinstance(block, KakaoQuestionImage):
                old_image = previous if isinstance(previous, KakaoQuestionImage) else None
                if (
                    block.quality_acceptance
                    != (old_image.quality_acceptance if old_image else None)
                    and block.quality_acceptance
                    and (
                        block.quality_acceptance.accepted_by != actor_id
                        or block.quality_acceptance.accepted_at != created_at
                    )
                ):
                    raise ValueError("KAKAO_ARCHIVE_IMAGE_QUALITY_DECISION_INVALID")
                if (
                    block.transform
                    and old_image
                    and old_image.transform
                    and (
                        block.transform.transform_revision_id
                        == old_image.transform.transform_revision_id
                        and block.transform != old_image.transform
                    )
                ):
                    raise ValueError("KAKAO_ARCHIVE_REVISION_REUSED")
        changes.update(
            student=command.student.model_dump(mode="json") if command.student else None,
            ordered_blocks=[block.model_dump(mode="json") for block in command.ordered_blocks],
            selection_exclusions=[
                entry.model_dump(mode="json") for entry in command.selection_exclusions
            ],
            first_student_at_utc=_first_student(command.ordered_blocks),
            review_state="UNREVIEWED",
            review_decision=None,
            review_reasons=_reasons(
                command.ordered_blocks, contexts, boundary_uncertain=question.boundary_uncertain
            ),
        )
    return KakaoQuestionManifest.model_validate({**question.model_dump(mode="json"), **changes})


def _composed(
    template: KakaoQuestionManifest,
    blocks: tuple[KakaoQuestionBlock, ...],
    *,
    question_id: str,
    question_revision_id: str,
    inputs: tuple[KakaoQuestionManifest, ...],
    actor_id: str,
    created_at: datetime,
    sources: tuple[ResolvedKakaoQuestionSource, ...],
) -> KakaoQuestionManifest:
    if question_id in {item.question_id for item in inputs} or question_revision_id in {
        item.question_revision_id for item in inputs
    }:
        raise ValueError("KAKAO_ARCHIVE_REVISION_REUSED")
    references = {
        source.normalization_revision_id: source for item in inputs for source in item.sources
    }
    contexts = {source.normalization.normalization_revision_id: source for source in sources}
    for item in inputs:
        _contexts(item, sources)
        if created_at < item.created_at:
            raise ValueError("KAKAO_ARCHIVE_TIME_INVALID")
    _validate_blocks(blocks, contexts)
    uncertain = any(item.boundary_uncertain for item in inputs)
    return KakaoQuestionManifest(
        question_id=question_id,
        question_revision_id=question_revision_id,
        previous_revision_id=None,
        source_binding_id=template.source_binding_id,
        room_id=template.room_id,
        student=template.student,
        sources=tuple(references.values()),
        ordered_blocks=blocks,
        first_student_at_utc=_first_student(blocks),
        review_reasons=_reasons(blocks, contexts, boundary_uncertain=uncertain),
        boundary_uncertain=uncertain,
        source_stale=any(item.source_stale for item in inputs),
        provenance=tuple(
            KakaoQuestionProvenance(
                question_id=item.question_id, question_revision_id=item.question_revision_id
            )
            for item in inputs
        ),
        created_by=actor_id,
        created_at=created_at,
    )


def split_question(
    question: KakaoQuestionManifest,
    partitions: tuple[tuple[KakaoQuestionBlock, ...], ...],
    *,
    expected_revision_id: str,
    new_ids: tuple[tuple[str, str], ...],
    actor_id: str,
    created_at: datetime,
    sources: tuple[ResolvedKakaoQuestionSource, ...],
) -> tuple[KakaoQuestionManifest, ...]:
    if expected_revision_id != question.question_revision_id:
        raise ValueError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
    if question.student is None:
        raise ValueError("KAKAO_ARCHIVE_COMPOSITION_SCOPE_INVALID")
    if (
        not 2 <= len(partitions) <= 100
        or len(partitions) != len(new_ids)
        or any(not part for part in partitions)
    ):
        raise ValueError("KAKAO_ARCHIVE_SPLIT_INVALID")
    if len({pair[0] for pair in new_ids}) != len(new_ids) or len(
        {pair[1] for pair in new_ids}
    ) != len(new_ids):
        raise ValueError("KAKAO_ARCHIVE_REVISION_REUSED")
    contexts = _contexts(question, sources)
    flattened = tuple(block for part in partitions for block in part)
    _validate_blocks(flattened, contexts)
    originals = {block.block_id: block for block in question.ordered_blocks}
    seen_images: set[str] = set()
    spans: dict[tuple[str, str], list[KakaoQuestionText]] = {}
    for block in flattened:
        if isinstance(block, KakaoQuestionImage):
            if originals.get(block.block_id) != block or block.block_id in seen_images:
                raise ValueError("KAKAO_ARCHIVE_SPLIT_COVERAGE_INVALID")
            seen_images.add(block.block_id)
        else:
            spans.setdefault(
                (block.normalization_revision_id, block.source_occurrence_id), []
            ).append(block)
    expected_images = {
        block.block_id for block in question.ordered_blocks if isinstance(block, KakaoQuestionImage)
    }
    if seen_images != expected_images:
        raise ValueError("KAKAO_ARCHIVE_SPLIT_COVERAGE_INVALID")
    original_spans: dict[tuple[str, str], list[KakaoQuestionText]] = {}
    for original in question.ordered_blocks:
        if isinstance(original, KakaoQuestionText):
            original_spans.setdefault(
                (original.normalization_revision_id, original.source_occurrence_id), []
            ).append(original)
    if set(original_spans) != set(spans):
        raise ValueError("KAKAO_ARCHIVE_SPLIT_COVERAGE_INVALID")
    for source_key, originals_for_source in original_spans.items():
        pieces = sorted(spans[source_key], key=lambda block: block.start_codepoint)
        position = 0
        for original in sorted(originals_for_source, key=lambda block: block.start_codepoint):
            edge = original.start_codepoint
            while (
                position < len(pieces) and pieces[position].start_codepoint < original.end_codepoint
            ):
                piece = pieces[position]
                if (
                    piece.start_codepoint != edge
                    or piece.end_codepoint > original.end_codepoint
                    or (original.display_override and piece != original)
                    or piece.display_override != original.display_override
                ):
                    raise ValueError("KAKAO_ARCHIVE_SPLIT_COVERAGE_INVALID")
                position += 1
                edge = piece.end_codepoint
            if edge != original.end_codepoint:
                raise ValueError("KAKAO_ARCHIVE_SPLIT_COVERAGE_INVALID")
        if position != len(pieces):
            raise ValueError("KAKAO_ARCHIVE_SPLIT_COVERAGE_INVALID")
    return tuple(
        _composed(
            question,
            partition,
            question_id=ids[0],
            question_revision_id=ids[1],
            inputs=(question,),
            actor_id=actor_id,
            created_at=created_at,
            sources=sources,
        )
        for partition, ids in zip(partitions, new_ids, strict=True)
    )


def merge_questions(
    questions: tuple[KakaoQuestionManifest, ...],
    *,
    expected_revision_ids: tuple[str, ...],
    question_id: str,
    question_revision_id: str,
    actor_id: str,
    created_at: datetime,
    sources: tuple[ResolvedKakaoQuestionSource, ...],
) -> KakaoQuestionManifest:
    if not 2 <= len(questions) <= 100 or len(
        {question.question_id for question in questions}
    ) != len(questions):
        raise ValueError("KAKAO_ARCHIVE_MERGE_INVALID")
    if tuple(question.question_revision_id for question in questions) != expected_revision_ids:
        raise ValueError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
    first = questions[0]
    if first.student is None or any(
        question.source_binding_id != first.source_binding_id
        or question.room_id != first.room_id
        or question.student != first.student
        for question in questions
    ):
        raise ValueError("KAKAO_ARCHIVE_COMPOSITION_SCOPE_INVALID")
    blocks = tuple(block for question in questions for block in question.ordered_blocks)
    return _composed(
        first,
        blocks,
        question_id=question_id,
        question_revision_id=question_revision_id,
        inputs=questions,
        actor_id=actor_id,
        created_at=created_at,
        sources=sources,
    )


def build_question_packet(
    questions: tuple[PublishedKakaoQuestion, ...],
    *,
    packet_id: str,
    packet_revision_id: str,
    previous_revision_id: str | None,
    start_date: date,
    end_date_inclusive: date,
    mode: Literal["DRAFT", "FINAL"],
    include_replies: bool,
    actor_id: str,
    created_at: datetime,
    collection_coverage: Literal["UNKNOWN", "PARTIAL", "COMPLETE"] = "UNKNOWN",
) -> KakaoQuestionPacket:
    if not questions:
        raise ValueError("KAKAO_ARCHIVE_EMPTY_SELECTION")
    binding_id = questions[0].question.source_binding_id
    entries: list[KakaoPacketQuestion] = []
    for published in questions:
        question = published.question
        if question.source_binding_id != binding_id:
            raise ValueError("KAKAO_ARCHIVE_PACKET_SCOPE_INVALID")
        if question.student is None:
            raise ValueError("KAKAO_ARCHIVE_STUDENT_UNMAPPED")
        if question.review_state == "EXCLUDED":
            raise ValueError("KAKAO_ARCHIVE_QUESTION_EXCLUDED")
        if created_at < question.created_at:
            raise ValueError("KAKAO_ARCHIVE_TIME_INVALID")
        entries.append(
            KakaoPacketQuestion(
                question_id=question.question_id,
                question_revision_id=question.question_revision_id,
                room_id=question.room_id,
                student=question.student,
                manifest=published.pointer,
                first_student_at_utc=question.first_student_at_utc,
                final_blockers=question_final_blockers(question, include_replies=include_replies),
            )
        )
    start, end = question_period_utc(start_date, end_date_inclusive)
    return KakaoQuestionPacket(
        packet_id=packet_id,
        packet_revision_id=packet_revision_id,
        previous_revision_id=previous_revision_id,
        source_binding_id=binding_id,
        mode=mode,
        include_replies=include_replies,
        display_start_date=start_date,
        display_end_date_inclusive=end_date_inclusive,
        range_start_utc=start,
        range_end_utc_exclusive=end,
        collection_coverage=collection_coverage,
        questions=tuple(entries),
        created_by=actor_id,
        created_at=created_at,
    )


def packet_student_subset(packet: KakaoQuestionPacket, student_id: str) -> KakaoPacketStudentSubset:
    questions = tuple(
        question for question in packet.questions if question.student.student_id == student_id
    )
    if not questions:
        raise ValueError("KAKAO_ARCHIVE_STUDENT_NOT_IN_PACKET")
    student = questions[0].student
    return KakaoPacketStudentSubset(
        packet_revision_id=packet.packet_revision_id,
        student_id=student_id,
        student_display_revision_id=student.student_display_revision_id,
        display_name=student.display_name,
        questions=questions,
        subset_sha256=sha256_bytes(
            canonical_json_bytes(tuple(question.question_revision_id for question in questions))
        ),
    )
