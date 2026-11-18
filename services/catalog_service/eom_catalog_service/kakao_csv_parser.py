"""Bounded strict CSV normalization; no I/O, provider requests, or name-based identity."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from eom_catalog_contracts.kakao_archive import (
    KakaoMessageNormalization,
    KakaoMessageObservation,
    KakaoNormalizedMessage,
    SourceOrder,
    SourceTimezone,
)
from pydantic import ValidationError

_REQUIRED_COLUMNS = frozenset({"DATE", "USER", "MESSAGE"})
_DATE_FORMAT = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$")
MAX_CSV_BYTES = 32 * 1024 * 1024
MAX_CSV_ROWS = 100000


@dataclass(frozen=True, slots=True)
class KakaoCsvMessages:
    """Original row-ordered messages, not a normalized or admitted source."""

    source_sha256: str
    source_bytes: int
    messages: tuple[str, ...] = field(repr=False)


def _read_rows(source: bytes) -> tuple[tuple[str, ...], Iterator[tuple[datetime, list[str]]]]:
    if not source or len(source) > MAX_CSV_BYTES:
        raise ValueError("KAKAO_ARCHIVE_CSV_SIZE_INVALID")
    try:
        decoded = source.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        raise ValueError("KAKAO_ARCHIVE_CSV_ENCODING_INVALID") from None
    reader = csv.reader(io.StringIO(decoded, newline=""), strict=True)
    try:
        columns = tuple(next(reader))
    except StopIteration:
        raise ValueError("KAKAO_ARCHIVE_CSV_COLUMNS_INVALID") from None
    except csv.Error:
        raise ValueError("KAKAO_ARCHIVE_CSV_MALFORMED") from None
    if (
        len(columns) > 35
        or len(set(columns)) != len(columns)
        or not _REQUIRED_COLUMNS.issubset(columns)
    ):
        raise ValueError("KAKAO_ARCHIVE_CSV_COLUMNS_INVALID")
    date_index = columns.index("DATE")

    def rows() -> Iterator[tuple[datetime, list[str]]]:
        try:
            for ordinal, fields in enumerate(reader, 1):
                if ordinal > MAX_CSV_ROWS:
                    raise ValueError("KAKAO_ARCHIVE_CSV_ROW_LIMIT")
                if len(fields) != len(columns):
                    raise ValueError("KAKAO_ARCHIVE_CSV_ROW_WIDTH_INVALID")
                raw_date = fields[date_index]
                if _DATE_FORMAT.fullmatch(raw_date) is None:
                    raise ValueError("KAKAO_ARCHIVE_CSV_DATE_INVALID")
                try:
                    local_date = datetime.strptime(raw_date, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    raise ValueError("KAKAO_ARCHIVE_CSV_DATE_INVALID") from None
                yield local_date, fields
        except csv.Error:
            raise ValueError("KAKAO_ARCHIVE_CSV_MALFORMED") from None

    return columns, rows()


def read_kakao_csv_messages(source: bytes) -> KakaoCsvMessages:
    """Read row positions without inventing a destination revision or source order."""
    columns, rows = _read_rows(source)
    index = columns.index("MESSAGE")
    messages = tuple(fields[index] for _, fields in rows)
    return KakaoCsvMessages("sha256:" + hashlib.sha256(source).hexdigest(), len(source), messages)


def parse_kakao_csv(
    source: bytes,
    *,
    source_binding_id: str,
    room_id: str,
    snapshot_revision_id: str,
    normalization_revision_id: str,
    observed_at_utc: datetime,
    source_timezone: SourceTimezone = "unknown",
    source_order: SourceOrder = "unknown",
    context_start_verified: bool = False,
    context_end_verified: bool = False,
    observations: tuple[KakaoMessageObservation, ...] = (),
) -> KakaoMessageNormalization:
    """Keep raw cell values and row multiplicity; confirmed UI evidence is explicit input.

    O(bytes + rows + observations), one bounded in-memory Artifact materialization.
    Callers must preserve raw bytes separately and must not log Pydantic input payloads.
    """
    columns, rows = _read_rows(source)
    evidence = {observation.row_ordinal: observation for observation in observations}
    if len(evidence) != len(observations):
        raise ValueError("KAKAO_ARCHIVE_ROW_EVIDENCE_DUPLICATED")
    messages: list[KakaoNormalizedMessage] = []
    previous_date: datetime | None = None
    try:
        indexes = {name: position for position, name in enumerate(columns)}
        extra_indexes = tuple(i for i, name in enumerate(columns) if name not in _REQUIRED_COLUMNS)
        for ordinal, (local_date, fields) in enumerate(rows, 1):
            raw_date = fields[indexes["DATE"]]
            if previous_date is not None and (
                (source_order == "ascending" and local_date < previous_date)
                or (source_order == "descending" and local_date > previous_date)
            ):
                raise ValueError("KAKAO_ARCHIVE_CSV_ORDER_INVALID")
            previous_date = local_date
            observation = evidence.get(ordinal, KakaoMessageObservation(row_ordinal=ordinal))
            messages.append(
                KakaoNormalizedMessage(
                    **observation.model_dump(),
                    raw_date=raw_date,
                    raw_sender=fields[indexes["USER"]],
                    text=fields[indexes["MESSAGE"]],
                    extra_values=tuple(fields[i] for i in extra_indexes),
                    sent_at_utc=(
                        local_date.replace(tzinfo=ZoneInfo("Asia/Seoul")).astimezone(UTC)
                        if source_timezone == "Asia/Seoul"
                        else None
                    ),
                )
            )
        if any(ordinal > len(messages) for ordinal in evidence):
            raise ValueError("KAKAO_ARCHIVE_ROW_EVIDENCE_OUT_OF_RANGE")
        return KakaoMessageNormalization(
            source_binding_id=source_binding_id,
            room_id=room_id,
            snapshot_revision_id=snapshot_revision_id,
            normalization_revision_id=normalization_revision_id,
            source_sha256="sha256:" + hashlib.sha256(source).hexdigest(),
            source_bytes=len(source),
            observed_at_utc=observed_at_utc,
            source_timezone=source_timezone,
            source_order=source_order,
            context_start_verified=context_start_verified,
            context_end_verified=context_end_verified,
            columns=columns,
            messages=tuple(messages),
        )
    except ValidationError:
        raise ValueError("KAKAO_ARCHIVE_CSV_OBSERVATION_INVALID") from None
