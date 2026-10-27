"""Deterministic, read-only proposals linking workbook rows to archive members.

A match is not an Intake commit, human approval, or registered Item. Conflict
states retain the original link and all candidate members for later review.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import unquote

from eom_catalog_service.external_item_archive import (
    ExternalItemArchiveInventory,
    ExternalItemDocumentMember,
)
from eom_catalog_service.external_item_xlsx import DecodedExternalItemRow

_DOCUMENT_SUFFIX = re.compile(r"_([0-9]{5})\.(hwp|hwpx)$", re.IGNORECASE)
_OFFICE_EXTENSION = re.compile(r"\.(hwp|hwpx)$", re.IGNORECASE)
_EXPORT_COPY_SUFFIX = re.compile(r" (?:[1-9][0-9]*|\([1-9][0-9]*\))\.(hwp|hwpx)$", re.IGNORECASE)
_MAX_LINK_TEXT = 4096


class ExternalItemMatchStatus(StrEnum):
    MATCHED = "MATCHED"
    MATCHED_DETECTED_HWPX = "MATCHED_DETECTED_HWPX"
    MATCHED_IDENTICAL_COPIES = "MATCHED_IDENTICAL_COPIES"
    REJECTED = "REJECTED"
    REJECTION_AMBIGUOUS = "REJECTION_AMBIGUOUS"
    DRAFT_ONLY = "DRAFT_ONLY"
    LINK_UNSUPPORTED = "LINK_UNSUPPORTED"
    DOCUMENT_MISSING = "DOCUMENT_MISSING"
    NAME_MISMATCH = "NAME_MISMATCH"
    CONTENT_CONFLICT = "CONTENT_CONFLICT"
    FORMAT_MISMATCH = "FORMAT_MISMATCH"


@dataclass(frozen=True)
class ExternalItemLinkMatch:
    external_number: str
    row_number: int
    status: ExternalItemMatchStatus
    final_edition: int | None
    source_link: str | None
    display_filename: str | None
    selected_member: ExternalItemDocumentMember | None
    candidates: tuple[ExternalItemDocumentMember, ...]


def propose_external_item_links(
    rows: tuple[DecodedExternalItemRow, ...], inventory: ExternalItemArchiveInventory
) -> tuple[ExternalItemLinkMatch, ...]:
    """Join by U and normalized basename in O(rows + documents + candidates)."""

    documents_by_number: dict[str, list[ExternalItemDocumentMember]] = defaultdict(list)
    for document in inventory.documents:
        documents_by_number[document.external_number].append(document)
    return tuple(
        _propose_one(row, documents_by_number.get(row.external_number, [])) for row in rows
    )


def _propose_one(
    row: DecodedExternalItemRow, number_candidates: list[ExternalItemDocumentMember]
) -> ExternalItemLinkMatch:
    rejected = _rejection_state(row.cells[23].raw_text)
    if rejected is not None:
        return _unselected(row, rejected, None, None, number_candidates)
    third_link = row.cells[13].raw_text
    second_link = row.cells[12].raw_text
    if third_link:
        edition, source_link = 3, third_link
    elif second_link:
        edition, source_link = 2, second_link
    else:
        return _unselected(row, ExternalItemMatchStatus.DRAFT_ONLY, None, None, number_candidates)
    filename = _link_basename(source_link)
    if filename is None or _OFFICE_EXTENSION.search(filename) is None:
        return _unselected(
            row, ExternalItemMatchStatus.LINK_UNSUPPORTED, edition, source_link, number_candidates
        )
    matches = tuple(
        document
        for document in number_candidates
        if _comparison_basename(filename).casefold() in _candidate_basenames(document)
    )
    if not matches:
        status = (
            ExternalItemMatchStatus.NAME_MISMATCH
            if number_candidates
            else ExternalItemMatchStatus.DOCUMENT_MISSING
        )
        return ExternalItemLinkMatch(
            external_number=row.external_number,
            row_number=row.row_number,
            status=status,
            final_edition=edition,
            source_link=source_link,
            display_filename=filename,
            selected_member=None,
            candidates=tuple(number_candidates),
        )
    if any(
        document.detected_format == "UNKNOWN"
        or (document.declared_format == "HWPX" and document.detected_format != "HWPX_PACKAGE")
        for document in matches
    ):
        status = ExternalItemMatchStatus.FORMAT_MISMATCH
        selected = None
    elif len({document.sha256 for document in matches}) > 1:
        status = ExternalItemMatchStatus.CONTENT_CONFLICT
        selected = None
    elif len(matches) > 1:
        status = ExternalItemMatchStatus.MATCHED_IDENTICAL_COPIES
        selected = min(matches, key=lambda document: document.member_name)
    else:
        selected = matches[0]
        status = (
            ExternalItemMatchStatus.MATCHED_DETECTED_HWPX
            if selected.declared_format == "HWP" and selected.detected_format == "HWPX_PACKAGE"
            else ExternalItemMatchStatus.MATCHED
        )
    return ExternalItemLinkMatch(
        external_number=row.external_number,
        row_number=row.row_number,
        status=status,
        final_edition=edition,
        source_link=source_link,
        display_filename=filename,
        selected_member=selected,
        candidates=matches,
    )


def _unselected(
    row: DecodedExternalItemRow,
    status: ExternalItemMatchStatus,
    edition: int | None,
    source_link: str | None,
    candidates: list[ExternalItemDocumentMember],
) -> ExternalItemLinkMatch:
    return ExternalItemLinkMatch(
        external_number=row.external_number,
        row_number=row.row_number,
        status=status,
        final_edition=edition,
        source_link=source_link,
        display_filename=None,
        selected_member=None,
        candidates=tuple(candidates),
    )


def _rejection_state(raw: str) -> ExternalItemMatchStatus | None:
    value = unicodedata.normalize("NFC", raw).strip().casefold()
    if value in {"", "no", "0", "false", "아니오"}:
        return None
    if value in {"yes", "1", "true", "예", "반려"}:
        return ExternalItemMatchStatus.REJECTED
    return ExternalItemMatchStatus.REJECTION_AMBIGUOUS


def _link_basename(raw: str) -> str | None:
    if not 0 < len(raw) <= _MAX_LINK_TEXT or any(ord(char) < 32 for char in raw):
        return None
    decoded = raw
    for _ in range(2):
        try:
            unquoted = unquote(decoded, encoding="utf-8", errors="strict")
        except UnicodeDecodeError:
            return None
        if unquoted == decoded:
            break
        decoded = unquoted
    if "\\" in decoded or decoded.startswith(("/", "file:", "http:", "https:")):
        return None
    parts = decoded.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return None
    return unicodedata.normalize("NFC", parts[-1])


def _unnumbered_basename(document: ExternalItemDocumentMember) -> str:
    return _DOCUMENT_SUFFIX.sub(lambda match: "." + match.group(2), document.display_filename)


def _comparison_basename(filename: str) -> str:
    """Ignore Notion export's final copy counter only after exact U pairing."""

    return _EXPORT_COPY_SUFFIX.sub(lambda match: "." + match.group(1), filename)


def _candidate_basenames(document: ExternalItemDocumentMember) -> set[str]:
    """Return exact and legacy-copy names, always within the same five-digit U."""

    base = _unnumbered_basename(document)
    names = {_comparison_basename(base).casefold()}
    # Some ZIP copies append an older five-digit number before the authoritative
    # final U. The old number is a filename annotation, never a new identity.
    without_alias = _DOCUMENT_SUFFIX.sub(lambda match: "." + match.group(2), base)
    if without_alias != base:
        names.add(_comparison_basename(without_alias).casefold())
    return names
