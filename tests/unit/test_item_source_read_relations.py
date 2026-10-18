"""Synthetic current relational reads; no actual DB, NAS, auth or model execution."""

from __future__ import annotations

from collections import Counter
from types import SimpleNamespace

import pytest
from eom_catalog_service import knowledge_analysis_sources as sources
from eom_catalog_service import knowledge_retrieval_service as retrieval
from eom_catalog_service.legacy_assessment_models import (
    AssessmentLayoutObservationRecord,
    AssessmentSourceBundleRevisionRecord,
    LegacyItemExtractionAcceptanceRecord,
    LegacyItemExtractionDecisionRecord,
)
from eom_catalog_service.legacy_item_extraction_batch_models import (
    LegacyItemExtractionBatchRecord,
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
        self.get_counts = Counter()
        self.lineage = {
            model: [base.records[model]]
            for model in (
                LegacyItemExtractionAcceptanceRecord,
                LegacyItemExtractionBatchRecord,
                AssessmentSourceBundleRevisionRecord,
                AssessmentLayoutObservationRecord,
            )
        }
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
        self.get_counts[model] += 1
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
        if model in self.lineage:
            field, selected = next(iter(statement.compile().params.items()))
            return tuple(
                row
                for row in self.lineage[model]
                if getattr(row, field.removesuffix("_1")) in selected
            )
        raise AssertionError(model)


def relation_case(monkeypatch, count=1):
    base, reader, values = _source_fixture(monkeypatch)
    # Keep the real compatibility check and its supported components= seam.
    monkeypatch.setattr(
        sources, "expected_promoted_legacy_item_content", expected_promoted_legacy_item_content
    )
    return RelationSession(base, values, count), reader


def resolve_all(session, reader, relations):
    cache = session.provenance if relations is not None else PastExamSourceResolutionCache()
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


def capture(session, reader):
    session.provenance = PastExamSourceResolutionCache()
    return sources.read_item_source_relations(
        session,
        tuple(session.revisions),
        artifacts=reader,
        past_exam_cache=session.provenance,
    )


@pytest.mark.parametrize("count", [16, 545])
def test_full_resolver_has_no_per_item_extraction_metadata_gets(monkeypatch, count):
    session, reader = relation_case(monkeypatch, count)
    captured = capture(session, reader)
    assert len(resolve_all(session, reader, captured)) == count
    assert {
        model.__name__: session.get_counts[model]
        for model in (
            LegacyItemExtractionAcceptanceRecord,
            LegacyItemExtractionBatchRecord,
            AssessmentSourceBundleRevisionRecord,
            AssessmentLayoutObservationRecord,
        )
        if session.get_counts[model]
    } == {}


@pytest.mark.parametrize("count", [16, 545])
def test_four_fresh_captures_use_eight_queries_each_not_four_per_item(monkeypatch, count):
    session, reader = relation_case(monkeypatch, count)
    captures, results = [], []
    for _phase in range(4):
        captures.append(capture(session, reader))
        results.append(resolve_all(session, reader, captures[-1]))
    assert len({id(value) for value in captures}) == 4
    assert results.count(results[0]) == 4
    counts = Counter(statement.column_descriptions[0]["entity"] for statement in session.statements)
    assert counts == {
        ItemRevisionRecord: 4,
        ItemComponentRecord: 4,
        LegacyItemExtractionDecisionRecord: 4,
        LegacyItemExtractionBatchWorkUnitRecord: 4,
        LegacyItemExtractionAcceptanceRecord: 4,
        LegacyItemExtractionBatchRecord: 4,
        AssessmentSourceBundleRevisionRecord: 4,
        AssessmentLayoutObservationRecord: 4,
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
    captured = capture(session, reader)
    assert resolve_all(session, reader, captured) == legacy
    assert len(session.statements) == 8


def test_metadata_only_builder_keeps_only_legacy_layout_lookup(monkeypatch):
    session, reader = relation_case(monkeypatch, 16)
    session.provenance = PastExamSourceResolutionCache()
    relations = sources.read_item_source_relations(session, tuple(session.revisions))
    legacy = resolve_all(session, reader, relations)
    assert len(session.statements) == 7
    assert session.get_counts[AssessmentLayoutObservationRecord] == 16
    assert all(
        session.get_counts[model] == 0
        for model in (
            LegacyItemExtractionAcceptanceRecord,
            LegacyItemExtractionBatchRecord,
            AssessmentSourceBundleRevisionRecord,
        )
    )
    assert resolve_all(session, reader, capture(session, reader)) == legacy


def test_retained_lineage_is_independent_of_incidental_orm_reference_lifetime(monkeypatch):
    session, reader = relation_case(monkeypatch, 16)
    relations = capture(session, reader)
    for model in session.lineage:
        session.base.records.pop(model)
        session.lineage[model].clear()
    assert len(resolve_all(session, reader, relations)) == 16
    assert not any(session.get_counts[model] for model in session.lineage)


@pytest.mark.parametrize(
    "model",
    [
        LegacyItemExtractionAcceptanceRecord,
        LegacyItemExtractionBatchRecord,
        AssessmentSourceBundleRevisionRecord,
        AssessmentLayoutObservationRecord,
    ],
)
def test_missing_lineage_does_not_fall_back_to_still_present_orm_rows(monkeypatch, model):
    session, reader = relation_case(monkeypatch)
    session.lineage[model].clear()
    relations = capture(session, reader)
    with pytest.raises(sources.KnowledgeAnalysisSourceError):
        resolve_all(session, reader, relations)
    assert session.get_counts[model] == 0


@pytest.mark.parametrize(
    "model,field,value",
    [
        (LegacyItemExtractionAcceptanceRecord, "coverage_state", "INCOMPLETE"),
        (LegacyItemExtractionBatchRecord, "manifest_sha256", ""),
        (AssessmentSourceBundleRevisionRecord, "state", "DRAFT"),
        (AssessmentLayoutObservationRecord, "artifact_sha256", "sha256:" + "f" * 64),
    ],
)
def test_next_capture_observes_each_changed_lineage_family(monkeypatch, model, field, value):
    session, reader = relation_case(monkeypatch)
    assert resolve_all(session, reader, capture(session, reader))
    session.lineage[model] = [SimpleNamespace(**(vars(session.lineage[model][0]) | {field: value}))]
    with pytest.raises(sources.KnowledgeAnalysisSourceError):
        resolve_all(session, reader, capture(session, reader))
    assert session.get_counts[model] == 0


def test_exact_batch_layout_selection_and_existing_cache_are_shared(monkeypatch):
    session, reader = relation_case(monkeypatch, 16)
    actual = session.lineage[AssessmentLayoutObservationRecord][0]
    foreign_id = "layoutobservation_" + "f" * 32
    session.lineage[AssessmentLayoutObservationRecord].append(
        SimpleNamespace(**(vars(actual) | {"assessment_layout_observation_id": foreign_id}))
    )
    relations = capture(session, reader)
    assert relations.layout(session, foreign_id) is None
    assert len(resolve_all(session, reader, relations)) == 16
    layout_statement = session.statements[-1]
    assert tuple(layout_statement.compile().params.values()) == (
        [actual.assessment_layout_observation_id],
    )
    assert Counter(call["member_path"] for call in reader.calls)["batch.json"] == 1


def test_failed_batch_hint_preserves_canonical_eligibility_and_hash_failure(monkeypatch):
    session, reader = relation_case(monkeypatch)
    reader.payloads["batch.json"] = b"invalid immutable member"
    relations = capture(session, reader)
    assert relations._layouts == {}
    revision = next(iter(session.revisions.values()))
    revision.revision_state = "DRAFT"
    with pytest.raises(sources.KnowledgeAnalysisSourceError) as denied:
        resolve_all(session, reader, relations)
    assert denied.value.code == "KNOWLEDGE_ANALYSIS_SOURCE_INELIGIBLE"
    revision.revision_state = "APPROVED"
    with pytest.raises(sources.KnowledgeAnalysisSourceError) as invalid:
        resolve_all(session, reader, relations)
    assert invalid.value.code == "KNOWLEDGE_ANALYSIS_SOURCE_HASH_MISMATCH"


def test_snapshot_builder_passes_one_existing_reader_and_provenance_cache(monkeypatch):
    session, reader = relation_case(monkeypatch)
    revision = next(iter(session.revisions))
    run_id = "analysisrun_" + "1" * 32
    scope = SimpleNamespace(
        graph_snapshot=SimpleNamespace(graph_snapshot_revision_id="graph"),
        _artifacts=reader,
        _past_exam=PastExamSourceResolutionCache(),
    )
    scope._scope = scope
    scope._require_owner = lambda *_: None
    original_scalars = session.scalars

    def scalars(statement):
        model = statement.column_descriptions[0]["entity"]
        if model is retrieval.KnowledgeSnapshotAnalysisRecord:
            return (SimpleNamespace(analysis_run_id=run_id),)
        if model is retrieval.KnowledgeAnalysisRunRecord:
            return (SimpleNamespace(analysis_run_id=run_id),)
        return original_scalars(statement)

    session.scalars = scalars
    observed = []
    original_builder = sources.read_item_source_relations

    def build(session, selected, *, artifacts, past_exam_cache):
        observed.append((artifacts, past_exam_cache))
        return original_builder(
            session, selected, artifacts=artifacts, past_exam_cache=past_exam_cache
        )

    monkeypatch.setattr(retrieval, "read_item_source_relations", build)
    service = object.__new__(retrieval.KnowledgeRetrievalApplicationService)
    service.artifacts = reader
    cache = service._snapshot_source_resolution_cache(
        session,
        "graph",
        (SimpleNamespace(analysis_run_id=run_id),),
        reuse_context=scope,
        item_source_revision_ids=(revision,),
    )
    assert observed == [(cache.artifacts, cache.past_exam_provenance)]
    assert cache.artifacts is reader and cache.past_exam_provenance is scope._past_exam


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
    captured = capture(session, reader)
    with pytest.raises(sources.KnowledgeAnalysisSourceError):
        resolve_all(session, reader, captured)
    assert len(session.statements) <= 8


@pytest.mark.parametrize("fault", ["decision", "components", "units", "approval"])
def test_later_capture_reloads_current_withdrawals(monkeypatch, fault):
    session, reader = relation_case(monkeypatch)
    first = capture(session, reader)
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
    second = capture(session, reader)
    assert second is not first
    with pytest.raises(sources.KnowledgeAnalysisSourceError):
        resolve_all(session, reader, second)


@pytest.mark.parametrize("fault", ["session", "root", "thread", "selection"])
def test_current_relation_scope_cannot_cross_owner_or_root(monkeypatch, fault):
    session, reader = relation_case(monkeypatch)
    selected = tuple(session.revisions)
    captured = capture(session, reader)
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
