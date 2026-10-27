"""Bounded, read-only eligibility projection for the creative-item learning runner.

This does not create an Item, grant worker authority, or publish Graph evidence.
Every future claim must reauthorize the exact source and Artifact pointers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from eom_catalog_contracts import ExternalItemRowObservation, ExternalItemWorkbookMapping
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_catalog_service.external_item_models import (
    ExternalItemEditionDocumentRecord,
    ExternalItemImportRecord,
    ExternalItemSourceRecord,
    ExternalItemSourceRevisionRecord,
)
from eom_catalog_service.external_item_observations import (
    ExternalCreativeOriginKind,
    external_creative_origin_kind,
)
from eom_catalog_service.models import ContentIntakeSourceFileRecord

_MATCHED = ("MATCHED", "MATCHED_DETECTED_HWPX", "MATCHED_IDENTICAL_COPIES")
_MEDIA = frozenset({"application/vnd.hancom.hwp", "application/vnd.hancom.hwpx"})
_NUMBER = re.compile(r"^[0-9]{5}$")


class ExternalCreativeLearningTargetError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ExternalCreativeLearningTarget:
    import_id: str
    source_id: str
    source_revision_id: str
    external_number: str
    origin_kind: ExternalCreativeOriginKind
    observation_sha256: str
    selected_edition: int
    source_file_id: str
    artifact_id: str
    artifact_revision_id: str
    document_sha256: str
    document_media_type: str
    document_size_bytes: int


@dataclass(frozen=True)
class ExternalCreativeLearningTargetPage:
    entries: tuple[ExternalCreativeLearningTarget, ...]
    next_after_number: str | None


def list_external_creative_learning_targets(
    session: Session,
    *,
    import_id: str,
    after_number: str | None = None,
    limit: int = 25,
) -> ExternalCreativeLearningTargetPage:
    """Read one indexed U-keyset page from an exact completed import.

    The `(import_id, external_number)` unique index and source current-revision
    pointer make this O(log n + page size), with one additional batched edition
    lookup. It deliberately does not scan for an unpinned `latest` import.
    """

    if not 1 <= limit <= 25 or (
        after_number is not None and _NUMBER.fullmatch(after_number) is None
    ):
        raise ExternalCreativeLearningTargetError("EXTERNAL_CREATIVE_TARGET_QUERY_INVALID")
    imported = session.get(ExternalItemImportRecord, import_id)
    if imported is None or imported.state != "COMPLETED":
        raise ExternalCreativeLearningTargetError("EXTERNAL_CREATIVE_IMPORT_NOT_READY")
    try:
        mapping = ExternalItemWorkbookMapping.model_validate(imported.mapping_document)
    except ValueError as exc:
        raise ExternalCreativeLearningTargetError("EXTERNAL_CREATIVE_MAPPING_INVALID") from exc
    if (
        mapping.mapping_revision_id != imported.mapping_revision_id
        or mapping.mapping_sha256 != imported.mapping_sha256
        or mapping.source_namespace != imported.source_namespace
    ):
        raise ExternalCreativeLearningTargetError("EXTERNAL_CREATIVE_MAPPING_INVALID")

    statement = (
        select(
            ExternalItemSourceRecord,
            ExternalItemSourceRevisionRecord,
            ContentIntakeSourceFileRecord,
        )
        .join(
            ExternalItemSourceRevisionRecord,
            ExternalItemSourceRecord.current_revision_id
            == ExternalItemSourceRevisionRecord.revision_id,
        )
        .join(
            ContentIntakeSourceFileRecord,
            ExternalItemSourceRevisionRecord.selected_source_file_id
            == ContentIntakeSourceFileRecord.source_file_id,
        )
        .where(
            ExternalItemSourceRevisionRecord.import_id == import_id,
            ExternalItemSourceRecord.source_namespace == imported.source_namespace,
            ExternalItemSourceRevisionRecord.source_id == ExternalItemSourceRecord.source_id,
            ExternalItemSourceRevisionRecord.external_number
            == ExternalItemSourceRecord.external_number,
            ExternalItemSourceRevisionRecord.match_status.in_(_MATCHED),
        )
        .order_by(ExternalItemSourceRecord.external_number)
        .limit(limit + 1)
    )
    if after_number is not None:
        statement = statement.where(ExternalItemSourceRecord.external_number > after_number)
    rows = tuple(session.execute(statement).all())
    visible = rows[:limit]
    revision_ids = tuple(revision.revision_id for _, revision, _ in visible)
    editions = {
        (edition.source_revision_id, edition.edition): edition
        for edition in session.scalars(
            select(ExternalItemEditionDocumentRecord).where(
                ExternalItemEditionDocumentRecord.source_revision_id.in_(revision_ids)
            )
        )
    }

    result: list[ExternalCreativeLearningTarget] = []
    for source, revision, source_file in visible:
        try:
            observation = ExternalItemRowObservation.model_validate(
                {
                    "workbook_artifact_id": imported.workbook_artifact_id,
                    "workbook_artifact_revision_id": imported.workbook_artifact_revision_id,
                    "workbook_sha256": imported.workbook_sha256,
                    "mapping_revision_id": imported.mapping_revision_id,
                    "mapping_sha256": imported.mapping_sha256,
                    "source_namespace": imported.source_namespace,
                    "worksheet_name": revision.worksheet_name,
                    "row_number": revision.row_number,
                    "external_number": revision.external_number,
                    "cells": revision.cells,
                    "observation_sha256": revision.observation_sha256,
                }
            )
        except ValueError as exc:
            raise ExternalCreativeLearningTargetError(
                "EXTERNAL_CREATIVE_SOURCE_OBSERVATION_INVALID"
            ) from exc
        kind = external_creative_origin_kind(observation)
        # The importer already resolves blank/No/0 rejection values before a
        # revision can become MATCHED; do not add a narrower second policy here.
        if kind is None:
            raise ExternalCreativeLearningTargetError("EXTERNAL_CREATIVE_CLASSIFICATION_INVALID")
        selected_edition = (
            3 if observation.cells[13].raw_text else 2 if observation.cells[12].raw_text else None
        )
        edition = (
            editions.get((revision.revision_id, selected_edition))
            if selected_edition is not None
            else None
        )
        if (
            selected_edition is None
            or edition is None
            or edition.match_status != revision.match_status
            or edition.source_file_id != revision.selected_source_file_id
            or edition.document_sha256 != source_file.sha256
            or source_file.media_type not in _MEDIA
            or source_file.size_bytes <= 0
        ):
            raise ExternalCreativeLearningTargetError("EXTERNAL_CREATIVE_DOCUMENT_POINTER_INVALID")
        result.append(
            ExternalCreativeLearningTarget(
                import_id=import_id,
                source_id=source.source_id,
                source_revision_id=revision.revision_id,
                external_number=source.external_number,
                origin_kind=kind,
                observation_sha256=revision.observation_sha256,
                selected_edition=selected_edition,
                source_file_id=source_file.source_file_id,
                artifact_id=source_file.artifact_id,
                artifact_revision_id=source_file.artifact_revision_id,
                document_sha256=source_file.sha256,
                document_media_type=source_file.media_type,
                document_size_bytes=source_file.size_bytes,
            )
        )
    return ExternalCreativeLearningTargetPage(
        entries=tuple(result),
        next_after_number=(result[-1].external_number if len(rows) > limit else None),
    )
