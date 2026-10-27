"""Mixed assembly selection cannot mislabel or silently repin Graph Items."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from eom_api_contracts.curated_document_assembly import (
    PastExamItemPlacement,
    RegisteredItemPlacement,
)
from eom_catalog_service.curated_document_assembly_item import (
    CuratedDocumentAssemblyItemError,
    resolve_curated_registered_item,
)
from eom_catalog_service.knowledge_graph_models import KnowledgeGraphSnapshotRecord
from eom_catalog_service.models import ItemRecord, ItemRevisionRecord


def _selection(past_exam: bool = False) -> RegisteredItemPlacement | PastExamItemPlacement:
    values = {
        "placement_kind": "PAST_EXAM_ITEM_REVISION" if past_exam else "REGISTERED_ITEM_REVISION",
        "position": 2,
        "item_id": "item_" + "1" * 32,
        "item_revision_id": "itemrev_" + "2" * 32,
        "item_manifest_sha256": "sha256:" + "3" * 64,
        "graph_snapshot_revision_id": "graphrev_" + "4" * 32,
        "graph_snapshot_sha256": "sha256:" + "5" * 64,
    }
    if past_exam:
        return PastExamItemPlacement.model_validate(values)
    return RegisteredItemPlacement.model_validate(values)


class _Session:
    def __init__(self, selection: RegisteredItemPlacement | PastExamItemPlacement) -> None:
        self.corpus = SimpleNamespace(
            current_graph_snapshot_revision_id=selection.graph_snapshot_revision_id,
            graph_id="graph_" + "6" * 32,
        )
        self.snapshot = SimpleNamespace(
            state="PUBLISHED",
            graph_id=self.corpus.graph_id,
            snapshot_sha256=selection.graph_snapshot_sha256,
            ontology_version="education-knowledge-graph/1.1",
        )
        self.revision = SimpleNamespace(
            item_id=selection.item_id,
            manifest_sha256=selection.item_manifest_sha256,
            revision_state="APPROVED",
        )
        self.item = SimpleNamespace(item_id=selection.item_id, lifecycle_state="ACTIVE")
        source_class = (
            "PAST_EXAM" if isinstance(selection, PastExamItemPlacement) else "APPROVED_ITEM"
        )
        self.source_rows = [(source_class, "analysisrun_" + "7" * 32)]
        self.occurrence_runs = {"analysisrun_" + "7" * 32} if source_class == "PAST_EXAM" else set()
        self.source_statement: Any = None
        self.occurrence_statement: Any = None

    def scalar(self, _statement: Any) -> Any:
        return self.corpus

    def get(self, record_type: type[Any], _key: str) -> Any:
        return {
            KnowledgeGraphSnapshotRecord: self.snapshot,
            ItemRevisionRecord: self.revision,
            ItemRecord: self.item,
        }[record_type]

    def execute(self, statement: Any) -> _Session:
        self.source_statement = statement
        return self

    def all(self) -> list[tuple[str, str]]:
        return self.source_rows

    def scalars(self, statement: Any) -> set[str]:
        self.occurrence_statement = statement
        return self.occurrence_runs


@pytest.mark.parametrize("past_exam", [False, True])
def test_curated_item_resolves_exact_graph_class_and_exam_context(past_exam: bool) -> None:
    selection = _selection(past_exam)
    session = _Session(selection)

    resolved = resolve_curated_registered_item(session, selection)  # type: ignore[arg-type]

    assert resolved.placement_kind == selection.placement_kind
    assert resolved.item_revision_id == selection.item_revision_id
    assert resolved.graph_snapshot_sha256 == selection.graph_snapshot_sha256
    assert "knowledge_node_source_pointers" in str(session.source_statement)
    assert "assessment_item_occurrence_references" in str(session.occurrence_statement)


def test_curated_item_rejects_stale_graph_or_item() -> None:
    selection = _selection()
    session = _Session(selection)
    session.corpus.current_graph_snapshot_revision_id = "graphrev_" + "f" * 32
    with pytest.raises(CuratedDocumentAssemblyItemError) as stale:
        resolve_curated_registered_item(session, selection)  # type: ignore[arg-type]
    assert stale.value.code == "CURATED_GRAPH_SNAPSHOT_STALE"

    session = _Session(selection)
    session.revision.manifest_sha256 = "sha256:" + "f" * 64
    with pytest.raises(CuratedDocumentAssemblyItemError) as changed:
        resolve_curated_registered_item(session, selection)  # type: ignore[arg-type]
    assert changed.value.code == "CURATED_ITEM_REVISION_INVALID"


def test_curated_item_rejects_ambiguous_class_and_wrong_exam_context() -> None:
    selection = _selection()
    session = _Session(selection)
    session.source_rows.append(("PAST_EXAM", "analysisrun_" + "8" * 32))
    with pytest.raises(CuratedDocumentAssemblyItemError) as ambiguous:
        resolve_curated_registered_item(session, selection)  # type: ignore[arg-type]
    assert ambiguous.value.code == "CURATED_ITEM_GRAPH_SOURCE_INVALID"

    session = _Session(selection)
    session.occurrence_runs = {"analysisrun_" + "7" * 32}
    with pytest.raises(CuratedDocumentAssemblyItemError) as wrong_context:
        resolve_curated_registered_item(session, selection)  # type: ignore[arg-type]
    assert wrong_context.value.code == "CURATED_ITEM_GRAPH_SOURCE_CONTEXT_INVALID"

    selection = _selection(past_exam=True)
    session = _Session(selection)
    session.occurrence_runs = set()
    with pytest.raises(CuratedDocumentAssemblyItemError) as missing_context:
        resolve_curated_registered_item(session, selection)  # type: ignore[arg-type]
    assert missing_context.value.code == "CURATED_ITEM_GRAPH_SOURCE_CONTEXT_INVALID"
