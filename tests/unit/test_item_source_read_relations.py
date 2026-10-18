"""Synthetic current relational reads; no actual DB, NAS, auth or model execution."""

from __future__ import annotations

from collections import Counter
from types import SimpleNamespace

import pytest
from eom_catalog_service import knowledge_analysis_sources as sources
from eom_catalog_service.legacy_assessment_models import LegacyItemExtractionDecisionRecord
from eom_catalog_service.legacy_item_extraction_batch_models import (
    LegacyItemExtractionBatchWorkUnitRecord,
)
from eom_catalog_service.legacy_item_media_compatibility_service import (
    expected_promoted_legacy_item_content,
)
from eom_catalog_service.models import ItemComponentRecord, ItemRevisionRecord
from eom_catalog_service.past_exam_source_provenance import PastExamSourceResolutionCache

from tests.unit.test_past_exam_source_provenance import _source_fixture


class RelationSession:
    def __init__(self, base, values, count):
        self.base, self.root = base, SimpleNamespace(is_active=True)
        self.statements = []
        self.revisions, self.components = {}, []
        for index in range(count):
            revision_id = f"itemrev_{index:032x}"
            self.revisions[revision_id] = SimpleNamespace(
                **(vars(values["revision"]) | {"item_revision_id": revision_id})
            )
            self.components.append(
                SimpleNamespace(
                    **(
                        vars(base.component)
                        | {
                            "item_revision_id": revision_id,
                            "component_type": "ITEM_CONTENT",
                            "ordinal": 0,
                        }
                    )
                )
            )
        self.decisions = [
            SimpleNamespace(
                **(
                    vars(base.decision)
                    | {
                        "acceptance_id": values["acceptance"].acceptance_id,
                        "item_proposal_id": values["revision"].metadata_json["item_proposal_id"],
                        "item_number": values["revision"].metadata_json["item_number"],
                    }
                )
            )
        ]
        self.units = [
            SimpleNamespace(
                **(
                    vars(base.unit)
                    | {
                        "acceptance_id": values["acceptance"].acceptance_id,
                        "extraction_result_id": values["acceptance"].extraction_result_id,
                        "state": "ACCEPTED",
                    }
                )
            )
        ]

    def get_transaction(self):
        return self.root

    def get(self, model, identity):
        return (
            self.revisions.get(identity)
            if model is ItemRevisionRecord
            else self.base.get(model, identity)
        )

    def scalars(self, statement):
        self.statements.append(statement)
        model = statement.column_descriptions[0]["entity"]
        if model is ItemRevisionRecord:
            return tuple(self.revisions.values())
        if model is ItemComponentRecord:
            params = statement.compile().params
            selected = params["item_revision_id_1"]
            selected = (selected,) if isinstance(selected, str) else selected
            return tuple(row for row in self.components if row.item_revision_id in selected)
        if model is LegacyItemExtractionDecisionRecord:
            return tuple(self.decisions)
        if model is LegacyItemExtractionBatchWorkUnitRecord:
            return tuple(row for row in self.units if row.state == "ACCEPTED")
        raise AssertionError(model)


def relation_case(monkeypatch, count=1):
    base, reader, values = _source_fixture(monkeypatch)
    # Keep the real compatibility check and its supported components= seam.
    monkeypatch.setattr(
        sources, "expected_promoted_legacy_item_content", expected_promoted_legacy_item_content
    )
    return RelationSession(base, values, count), reader


def resolve_all(session, reader, relations):
    cache = PastExamSourceResolutionCache()
    return tuple(
        sources.resolve_historically_approved_item_source(
            session,
            artifacts=reader,
            item_revision_id=revision_id,
            source_class="PAST_EXAM",
            past_exam_cache=cache,
            read_relations=relations,
        )
        for revision_id in session.revisions
    )


@pytest.mark.parametrize("count", [16, 545])
def test_four_fresh_captures_use_four_queries_each_not_four_per_item(monkeypatch, count):
    session, reader = relation_case(monkeypatch, count)
    captures, results = [], []
    for _phase in range(4):
        captures.append(sources.read_item_source_relations(session, tuple(session.revisions)))
        results.append(resolve_all(session, reader, captures[-1]))
    assert len({id(value) for value in captures}) == 4
    assert results.count(results[0]) == 4
    counts = Counter(statement.column_descriptions[0]["entity"] for statement in session.statements)
    assert counts == {
        ItemRevisionRecord: 4,
        ItemComponentRecord: 4,
        LegacyItemExtractionDecisionRecord: 4,
        LegacyItemExtractionBatchWorkUnitRecord: 4,
    }
    assert all(
        statement.get_execution_options()["populate_existing"] for statement in session.statements
    )
    work_sql = str(session.statements[3])
    assert "ORDER BY" in work_sql and "created_at" in work_sql and "work_unit_id" in work_sql


def test_legacy_fallback_matches_batched_output_and_keeps_original_queries(monkeypatch):
    session, reader = relation_case(monkeypatch, 16)
    legacy = resolve_all(session, reader, None)
    assert len(session.statements) == 4 * 16
    session.statements.clear()
    captured = sources.read_item_source_relations(session, tuple(session.revisions))
    assert resolve_all(session, reader, captured) == legacy
    assert len(session.statements) == 4


@pytest.mark.parametrize(
    "fault",
    ["missing_component", "duplicate_component", "duplicate_decision", "missing_unit", "lineage"],
)
def test_missing_duplicate_or_ambiguous_current_rows_fail_without_fallback(monkeypatch, fault):
    session, reader = relation_case(monkeypatch)
    if fault == "missing_component":
        session.components.clear()
    elif fault == "duplicate_component":
        session.components.append(session.components[0])
    elif fault == "duplicate_decision":
        session.decisions.append(session.decisions[0])
    elif fault == "missing_unit":
        session.units.clear()
    else:
        session.units.append(
            SimpleNamespace(**(vars(session.units[0]) | {"request_sha256": "sha256:" + "f" * 64}))
        )
    captured = sources.read_item_source_relations(session, tuple(session.revisions))
    with pytest.raises(sources.KnowledgeAnalysisSourceError):
        resolve_all(session, reader, captured)
    assert len(session.statements) == 4


@pytest.mark.parametrize("fault", ["decision", "components", "units", "approval"])
def test_later_capture_reloads_current_withdrawals(monkeypatch, fault):
    session, reader = relation_case(monkeypatch)
    first = sources.read_item_source_relations(session, tuple(session.revisions))
    resolve_all(session, reader, first)
    if fault == "decision":
        session.decisions = [
            SimpleNamespace(**(vars(session.decisions[0]) | {"decision": "REJECT"}))
        ]
    elif fault == "components":
        session.components.clear()
    elif fault == "units":
        session.units.clear()
    else:
        next(iter(session.revisions.values())).revision_state = "DRAFT"
    second = sources.read_item_source_relations(session, tuple(session.revisions))
    assert second is not first
    with pytest.raises(sources.KnowledgeAnalysisSourceError):
        resolve_all(session, reader, second)


@pytest.mark.parametrize("fault", ["session", "root", "thread", "selection"])
def test_current_relation_scope_cannot_cross_owner_or_root(monkeypatch, fault):
    session, _ = relation_case(monkeypatch)
    selected = tuple(session.revisions)
    captured = sources.read_item_source_relations(session, selected)
    if fault == "session":
        session = SimpleNamespace(get_transaction=lambda: captured._root)
    elif fault == "root":
        session.root = SimpleNamespace(is_active=True)
    elif fault == "thread":
        monkeypatch.setattr(sources, "get_ident", lambda: -1)
    else:
        selected = ("foreign",)
    with pytest.raises(sources.KnowledgeAnalysisSourceError):
        captured.components(session, selected[0])
