"""Catalog-owned Graph/Registry pointer resolution for a curated Item placement."""

from __future__ import annotations

from eom_api_contracts.curated_document_assembly import (
    PastExamItemPlacement,
    RegisteredItemPlacement,
)
from eom_catalog_contracts import (
    INTEGRATED_SCIENCE_TEXTBOOK_CORPUS_KEY,
    CuratedPastExamItemPlacement,
    CuratedRegisteredItemPlacement,
)
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from eom_catalog_service.knowledge_graph_models import (
    AssessmentItemOccurrenceReferenceRecord,
    KnowledgeCorpusRecord,
    KnowledgeGraphSnapshotRecord,
    KnowledgeNodeRecord,
    KnowledgeNodeSourcePointerRecord,
    KnowledgeSnapshotAnalysisRecord,
)
from eom_catalog_service.models import ItemRecord, ItemRevisionRecord


class CuratedDocumentAssemblyItemError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def resolve_curated_registered_item(
    session: Session,
    selection: RegisteredItemPlacement | PastExamItemPlacement,
) -> CuratedRegisteredItemPlacement | CuratedPastExamItemPlacement:
    """Pin one approved revision with its exact current Graph source class.

    HWPX content eligibility is a later Builder-admission decision; this
    selection manifest must not claim that a render has succeeded.
    """

    corpus = session.scalar(
        select(KnowledgeCorpusRecord).where(
            KnowledgeCorpusRecord.corpus_key == INTEGRATED_SCIENCE_TEXTBOOK_CORPUS_KEY,
            KnowledgeCorpusRecord.lifecycle_state == "ACTIVE",
        )
    )
    if (
        corpus is None
        or corpus.current_graph_snapshot_revision_id != selection.graph_snapshot_revision_id
    ):
        raise CuratedDocumentAssemblyItemError("CURATED_GRAPH_SNAPSHOT_STALE")
    snapshot = session.get(KnowledgeGraphSnapshotRecord, selection.graph_snapshot_revision_id)
    if (
        snapshot is None
        or snapshot.state != "PUBLISHED"
        or snapshot.graph_id != corpus.graph_id
        or snapshot.snapshot_sha256 != selection.graph_snapshot_sha256
        or snapshot.ontology_version != "education-knowledge-graph/1.1"
    ):
        raise CuratedDocumentAssemblyItemError("CURATED_GRAPH_SNAPSHOT_INVALID")

    revision = session.get(ItemRevisionRecord, selection.item_revision_id)
    item = session.get(ItemRecord, selection.item_id)
    if (
        revision is None
        or item is None
        or revision.item_id != item.item_id
        or revision.manifest_sha256 != selection.item_manifest_sha256
        or revision.revision_state not in {"APPROVED", "SUPERSEDED"}
        or item.lifecycle_state != "ACTIVE"
    ):
        raise CuratedDocumentAssemblyItemError("CURATED_ITEM_REVISION_INVALID")

    is_past_exam = isinstance(selection, PastExamItemPlacement)
    source_class = "PAST_EXAM" if is_past_exam else "APPROVED_ITEM"
    source_rows = session.execute(
        select(
            KnowledgeNodeSourcePointerRecord.source_class,
            KnowledgeNodeSourcePointerRecord.analysis_run_id,
        )
        .join(
            KnowledgeNodeRecord,
            and_(
                KnowledgeNodeRecord.graph_snapshot_revision_id
                == KnowledgeNodeSourcePointerRecord.graph_snapshot_revision_id,
                KnowledgeNodeRecord.node_id == KnowledgeNodeSourcePointerRecord.node_id,
            ),
        )
        .join(
            KnowledgeSnapshotAnalysisRecord,
            and_(
                KnowledgeSnapshotAnalysisRecord.graph_snapshot_revision_id
                == KnowledgeNodeSourcePointerRecord.graph_snapshot_revision_id,
                KnowledgeSnapshotAnalysisRecord.analysis_run_id
                == KnowledgeNodeSourcePointerRecord.analysis_run_id,
            ),
        )
        .where(
            KnowledgeNodeSourcePointerRecord.graph_snapshot_revision_id
            == selection.graph_snapshot_revision_id,
            KnowledgeNodeSourcePointerRecord.source_revision_id == selection.item_revision_id,
            KnowledgeNodeRecord.node_type == "ITEM_REVISION",
            KnowledgeNodeRecord.stable_key == "item-revision:" + selection.item_revision_id,
            KnowledgeSnapshotAnalysisRecord.source_kind == "APPROVED_ITEM_REVISION",
            KnowledgeSnapshotAnalysisRecord.source_revision_id == selection.item_revision_id,
        )
        .distinct()
    ).all()
    if not source_rows or {row_source_class for row_source_class, _run_id in source_rows} != {
        source_class
    }:
        raise CuratedDocumentAssemblyItemError("CURATED_ITEM_GRAPH_SOURCE_INVALID")

    analysis_run_ids = {run_id for _row_source_class, run_id in source_rows}
    occurrences = set(
        session.scalars(
            select(AssessmentItemOccurrenceReferenceRecord.analysis_run_id).where(
                AssessmentItemOccurrenceReferenceRecord.graph_snapshot_revision_id
                == selection.graph_snapshot_revision_id,
                AssessmentItemOccurrenceReferenceRecord.analysis_run_id.in_(analysis_run_ids),
            )
        )
    )
    if (source_class == "PAST_EXAM" and occurrences != analysis_run_ids) or (
        source_class == "APPROVED_ITEM" and occurrences
    ):
        raise CuratedDocumentAssemblyItemError("CURATED_ITEM_GRAPH_SOURCE_CONTEXT_INVALID")

    values = selection.model_dump(mode="json")
    if source_class == "PAST_EXAM":
        return CuratedPastExamItemPlacement.model_validate(values)
    return CuratedRegisteredItemPlacement.model_validate(values)
