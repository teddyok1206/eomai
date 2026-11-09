"""Small indexed delivery history; bytes and complete manifests stay at their owners."""

from eom_catalog_contracts.content_delivery import (
    ContentDeliveryEntry,
    ContentDeliveryList,
    ContentDeliveryPrepared,
    ReadContentDeliveries,
)
from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from eom_catalog_service.content_delivery_models import ContentDeliveryScopeRecord
from eom_catalog_service.content_planning_access import ContentPlanningError
from eom_catalog_service.content_planning_models import ContentEditionRevisionRecord
from eom_catalog_service.content_planning_storage import load_content_edition
from eom_catalog_service.curated_document_assembly_models import (
    CuratedDocumentAssemblyRevisionRecord,
)


def read_content_deliveries(session: Session, query: ReadContentDeliveries) -> ContentDeliveryList:
    """Caller has content read authority. Each build action reauthorizes exact source pins."""
    edition = load_content_edition(session, query.edition_id, include_archived=True)
    scope, revision, assembly = (
        ContentDeliveryScopeRecord,
        ContentEditionRevisionRecord,
        CuratedDocumentAssemblyRevisionRecord,
    )
    # Only three short labels and scalar pointers are projected, not the large scope JSON.
    forms = scope.canonical_scope["forms"]
    statement = (
        select(
            scope.assembly_id,
            scope.assembly_revision_id,
            scope.deliverable_revision_id,
            scope.scope_sha256,
            scope.created_at,
            revision.composition_sha256,
            assembly.manifest_sha256,
            func.jsonb_array_length(assembly.canonical_document["placements"]),
            func.jsonb_array_length(forms),
            *(forms[i]["path"][-1]["label"].astext for i in range(3)),
        )
        .join(revision, revision.deliverable_revision_id == scope.deliverable_revision_id)
        .join(
            assembly,
            assembly.assembly_revision_id == scope.assembly_revision_id,
        )
        .where(scope.edition_id == query.edition_id)
    )
    if query.before_id is not None:
        boundary = session.get(scope, query.before_id)
        if boundary is None or boundary.edition_id != query.edition_id:
            raise ContentPlanningError("CONTENT_DELIVERY_CURSOR_INVALID")
        statement = statement.where(
            tuple_(scope.created_at, scope.assembly_revision_id)
            < (boundary.created_at, boundary.assembly_revision_id)
        )
    candidates = session.execute(
        statement.order_by(
            scope.created_at.desc(),
            scope.assembly_revision_id.desc(),
        ).limit(query.limit + 1)
    ).all()
    rows = tuple(
        ContentDeliveryEntry(
            prepared=ContentDeliveryPrepared(
                edition_id=query.edition_id,
                revision_id=row[2],
                composition_sha256=row[5],
                scope_sha256=row[3],
                assembly_id=row[0],
                assembly_revision_id=row[1],
                manifest_sha256=row[6],
                placement_count=row[7],
                created_at=row[4],
                replayed=False,
            ),
            section_count=row[8],
            section_labels=tuple(label for label in row[9:] if label is not None),
            matches_current_revision=row[2] == edition.current_revision_id,
        )
        for row in candidates[: query.limit]
    )
    return ContentDeliveryList(
        edition_id=query.edition_id,
        rows=rows,
        next_id=rows[-1].prepared.assembly_revision_id if len(candidates) > query.limit else None,
    )
