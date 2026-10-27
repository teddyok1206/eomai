"""Catalog-owned batched Graph/Registry resolution for curated Item placements."""

from __future__ import annotations

from collections import defaultdict

from eom_catalog_contracts import (
    INTEGRATED_SCIENCE_TEXTBOOK_CORPUS_KEY,
    CuratedPastExamItemPlacement,
    CuratedRegisteredItemPlacement,
)
from eom_catalog_contracts.curated_document_assembly_draft import (
    PastExamItemPlacement,
    RegisteredItemPlacement,
)
from sqlalchemy import and_, literal, select
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


def resolve_curated_registered_items(
    session: Session,
    selections: tuple[RegisteredItemPlacement | PastExamItemPlacement, ...],
) -> tuple[CuratedRegisteredItemPlacement | CuratedPastExamItemPlacement, ...]:
    """Pin at most 200 approved Items with one Graph and bounded indexed reads.

    The caller owns operator permission and the enclosing transaction. Corpus and
    Item rows are read-locked while a persistent assembly is committed. HWPX
    eligibility remains a separate Builder-admission decision.
    """

    if not selections:
        return ()
    revisions = {row.item_revision_id for row in selections}
    snapshot_ids = {row.graph_snapshot_revision_id for row in selections}
    if len(selections) > 200 or len(revisions) != len(selections) or len(snapshot_ids) != 1:
        raise CuratedDocumentAssemblyItemError("CURATED_ITEM_SELECTION_INVALID")
    revision_ids = tuple(sorted(revisions))
    node_keys = tuple("item-revision:" + revision_id for revision_id in revision_ids)
    snapshot_id = next(iter(snapshot_ids))
    corpus = session.scalar(
        select(KnowledgeCorpusRecord)
        .where(
            KnowledgeCorpusRecord.corpus_key == INTEGRATED_SCIENCE_TEXTBOOK_CORPUS_KEY,
            KnowledgeCorpusRecord.lifecycle_state == "ACTIVE",
        )
        .with_for_update(read=True, of=KnowledgeCorpusRecord)
    )
    if corpus is None or corpus.current_graph_snapshot_revision_id != snapshot_id:
        raise CuratedDocumentAssemblyItemError("CURATED_GRAPH_SNAPSHOT_STALE")
    snapshot = session.get(KnowledgeGraphSnapshotRecord, snapshot_id)
    if (
        snapshot is None
        or snapshot.state != "PUBLISHED"
        or snapshot.graph_id != corpus.graph_id
        or snapshot.ontology_version != "education-knowledge-graph/1.1"
        or any(row.graph_snapshot_sha256 != snapshot.snapshot_sha256 for row in selections)
    ):
        raise CuratedDocumentAssemblyItemError("CURATED_GRAPH_SNAPSHOT_INVALID")

    item_rows = session.execute(
        select(ItemRevisionRecord, ItemRecord)
        .join(ItemRecord, ItemRecord.item_id == ItemRevisionRecord.item_id)
        .where(ItemRevisionRecord.item_revision_id.in_(revision_ids))
        .order_by(ItemRecord.item_id)
        .with_for_update(read=True, of=ItemRecord)
    ).all()
    by_revision = {revision.item_revision_id: (revision, item) for revision, item in item_rows}
    if len(by_revision) != len(revisions):
        raise CuratedDocumentAssemblyItemError("CURATED_ITEM_REVISION_INVALID")
    for selection in selections:
        revision, item = by_revision[selection.item_revision_id]
        if (
            revision.item_id != selection.item_id
            or revision.item_id != item.item_id
            or revision.manifest_sha256 != selection.item_manifest_sha256
            or revision.revision_state not in {"APPROVED", "SUPERSEDED"}
            or item.lifecycle_state != "ACTIVE"
        ):
            raise CuratedDocumentAssemblyItemError("CURATED_ITEM_REVISION_INVALID")

    source_rows = session.execute(
        select(
            KnowledgeNodeSourcePointerRecord.source_revision_id,
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
            KnowledgeNodeSourcePointerRecord.graph_snapshot_revision_id == snapshot_id,
            KnowledgeNodeSourcePointerRecord.source_revision_id.in_(revision_ids),
            KnowledgeNodeRecord.node_type == "ITEM_REVISION",
            KnowledgeNodeRecord.stable_key.in_(node_keys),
            KnowledgeNodeRecord.stable_key
            == literal("item-revision:") + KnowledgeNodeSourcePointerRecord.source_revision_id,
            KnowledgeSnapshotAnalysisRecord.source_kind == "APPROVED_ITEM_REVISION",
            KnowledgeSnapshotAnalysisRecord.source_revision_id
            == KnowledgeNodeSourcePointerRecord.source_revision_id,
        )
        .distinct()
    ).all()
    classes: dict[str, set[str]] = defaultdict(set)
    runs: dict[str, set[str]] = defaultdict(set)
    for revision_id, source_class, run_id in source_rows:
        classes[revision_id].add(source_class)
        runs[revision_id].add(run_id)
    all_runs = {run_id for item_runs in runs.values() for run_id in item_runs}
    occurrence_runs = set(
        session.scalars(
            select(AssessmentItemOccurrenceReferenceRecord.analysis_run_id).where(
                AssessmentItemOccurrenceReferenceRecord.graph_snapshot_revision_id == snapshot_id,
                AssessmentItemOccurrenceReferenceRecord.analysis_run_id.in_(all_runs),
            )
        )
    )
    result: list[CuratedRegisteredItemPlacement | CuratedPastExamItemPlacement] = []
    for selection in selections:
        revision_id = selection.item_revision_id
        is_past_exam = isinstance(selection, PastExamItemPlacement)
        expected_class = "PAST_EXAM" if is_past_exam else "APPROVED_ITEM"
        if classes[revision_id] != {expected_class}:
            raise CuratedDocumentAssemblyItemError("CURATED_ITEM_GRAPH_SOURCE_INVALID")
        linked_occurrences = occurrence_runs.intersection(runs[revision_id])
        if (is_past_exam and linked_occurrences != runs[revision_id]) or (
            not is_past_exam and linked_occurrences
        ):
            raise CuratedDocumentAssemblyItemError("CURATED_ITEM_GRAPH_SOURCE_CONTEXT_INVALID")
        values = selection.model_dump(mode="json")
        result.append(
            CuratedPastExamItemPlacement.model_validate(values)
            if is_past_exam
            else CuratedRegisteredItemPlacement.model_validate(values)
        )
    return tuple(result)


def resolve_curated_registered_item(
    session: Session,
    selection: RegisteredItemPlacement | PastExamItemPlacement,
) -> CuratedRegisteredItemPlacement | CuratedPastExamItemPlacement:
    """Single-placement convenience wrapper over the same batched invariant."""

    return resolve_curated_registered_items(session, (selection,))[0]
