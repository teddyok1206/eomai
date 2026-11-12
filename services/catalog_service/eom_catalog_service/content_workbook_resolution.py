"""Five-digit source lookup, then existing pinned-document admission in batches."""

from __future__ import annotations

from collections import defaultdict
from typing import Literal

from eom_catalog_contracts.content_workbook_import import (
    ContentWorkbookDocument,
    ContentWorkbookResolution,
)
from eom_catalog_contracts.curated_document_assembly_draft import ExternalSourcePlacement
from eom_catalog_contracts.curated_document_slots import ExternalSlotTarget
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_catalog_service.curated_document_assembly_source import (
    CuratedDocumentAssemblySourceError,
    resolve_pinned_curated_external_documents,
)
from eom_catalog_service.external_item_models import (
    ExternalItemEditionDocumentRecord,
    ExternalItemSourceRecord,
    ExternalItemSourceRevisionRecord,
)
from eom_catalog_service.models import ContentIntakeSourceFileRecord

_MEDIA: dict[str, Literal["HWP", "HWPX"]] = {
    "application/vnd.hancom.hwp": "HWP",
    "application/vnd.hancom.hwpx": "HWPX",
}


def resolve_workbook_rows(
    session: Session, document: ContentWorkbookDocument
) -> tuple[ContentWorkbookResolution, ...]:
    """O(n) maps plus indexed namespace/number lookups; never match titles or guess IDs."""
    source, revision = ExternalItemSourceRecord, ExternalItemSourceRevisionRecord
    binding, file = ExternalItemEditionDocumentRecord, ContentIntakeSourceFileRecord
    numbers = sorted({row.external_number for row in document.rows})
    namespaces = tuple(session.scalars(select(source.source_namespace).distinct()))
    candidates: dict[str, dict[str, tuple[ExternalSlotTarget | None, str | None]]] = defaultdict(
        dict
    )
    for start in range(0, len(numbers), 200):
        rows = session.execute(
            select(
                source.external_number,
                source.source_id,
                revision.revision_id,
                revision.observation_sha256,
                binding.edition,
                file.media_type,
                file.original_filename,
            )
            .outerjoin(revision, source.current_revision_id == revision.revision_id)
            .outerjoin(
                binding,
                (binding.source_revision_id == revision.revision_id)
                & (binding.source_file_id == revision.selected_source_file_id),
            )
            .outerjoin(file, binding.source_file_id == file.source_file_id)
            .where(
                source.source_namespace.in_(namespaces),
                source.external_number.in_(numbers[start : start + 200]),
            )
        ).all()
        for row in rows:
            try:
                target = ExternalSlotTarget(
                    placement_kind="EXTERNAL_SOURCE_DOCUMENT",
                    source_id=row.source_id,
                    source_revision_id=row.revision_id,
                    observation_sha256=row.observation_sha256,
                    edition=row.edition,
                    source_format=_MEDIA[row.media_type],
                )
            except (ValueError, KeyError):
                candidates[row.external_number].setdefault(row.source_id, (None, None))
            else:
                previous = candidates[row.external_number].get(row.source_id)
                # The selected file may be shared by 2교/3교. That is one source,
                # not a number collision; retain the final edition of that same file.
                if previous is None or previous[0] is None or target.edition > previous[0].edition:
                    candidates[row.external_number][row.source_id] = (
                        target,
                        row.original_filename[:200],
                    )
    selected = {
        number: next(iter(values.values()))
        for number, values in candidates.items()
        if len(values) == 1 and next(iter(values.values()))[0] is not None
    }
    targets = tuple(value[0] for value in selected.values() if value[0] is not None)
    available: set[ExternalSlotTarget] = set()
    for start in range(0, len(targets), 200):
        _admit(session, targets[start : start + 200], available)
    result = []
    for workbook_row in document.rows:
        values = candidates.get(workbook_row.external_number, {})
        selected_target, title = next(iter(values.values())) if len(values) == 1 else (None, None)
        status: Literal["MISSING", "AMBIGUOUS", "MATCHED", "UNAVAILABLE"] = (
            "MISSING"
            if not values
            else "AMBIGUOUS"
            if len(values) > 1
            else "MATCHED"
            if selected_target in available
            else "UNAVAILABLE"
        )
        result.append(
            ContentWorkbookResolution(
                row_number=workbook_row.row_number,
                status=status,
                target=selected_target if status == "MATCHED" else None,
                title=title if status == "MATCHED" else None,
            )
        )
    return tuple(result)


def _admit(
    session: Session, targets: tuple[ExternalSlotTarget, ...], available: set[ExternalSlotTarget]
) -> None:
    if not targets:
        return
    try:
        resolve_pinned_curated_external_documents(
            session,
            tuple(
                ExternalSourcePlacement(position=i, **target.model_dump())
                for i, target in enumerate(targets, 1)
            ),
        )
    except (CuratedDocumentAssemblySourceError, ValueError):
        # Fault-only bisection isolates an unavailable source without hiding valid neighbours.
        if len(targets) > 1:
            middle = len(targets) // 2
            _admit(session, targets[:middle], available)
            _admit(session, targets[middle:], available)
    else:
        available.update(targets)
