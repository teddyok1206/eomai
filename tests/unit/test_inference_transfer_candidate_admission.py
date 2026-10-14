"""Candidate admission query/identity tests without PostgreSQL or artifacts."""

from __future__ import annotations

from collections import deque
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from eom_catalog_contracts import EvidenceBudget
from eom_catalog_service.inference_transfer_scope import InferenceTransferPopulationScope
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalApplicationService,
    KnowledgeRetrievalServiceError,
    ReadOnlyCandidatePoolScope,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from tests.unit.inference_transfer_fixtures import profile, sha


def admission_scope(
    *,
    maximum: int = 2,
    role: str = "ADMIN",
    population_scope: InferenceTransferPopulationScope = (
        InferenceTransferPopulationScope.ALL_ADMITTED_GRAPH_ITEMS
    ),
) -> ReadOnlyCandidatePoolScope:
    return ReadOnlyCandidatePoolScope(
        graph_snapshot=profile().source_basis.graph_snapshot,
        access_policy_revision_id="accessrev_" + "a" * 32,
        access_policy_sha256=sha(),
        requested_by="operator_" + "a" * 32,
        requester_role=cast(Any, role),
        requester_permission_keys=("knowledge_graph:retrieve",),
        source_classes=("PAST_EXAM",),
        evidence_budget=EvidenceBudget(
            max_documents=8,
            max_item_revisions=8,
            max_graph_nodes=256,
            max_claims=32,
            max_context_tokens=8000,
        ),
        maximum_candidates=maximum,
        population_scope=population_scope,
    )


class AdmissionSession:
    def __init__(self, runs: tuple[str, ...], rows: tuple[tuple[Any, Any], ...]) -> None:
        self.runs = runs
        self.rows = rows
        self.statements: list[Any] = []

    def scalars(self, statement: Any) -> tuple[str, ...]:
        self.statements.append(statement)
        return self.runs

    def execute(self, statement: Any) -> tuple[tuple[Any, Any], ...]:
        self.statements.append(statement)
        return self.rows


def source_rows(run_id: str, *, number: int = 2) -> tuple[tuple[Any, Any], ...]:
    return tuple(
        (
            SimpleNamespace(analysis_run_id=run_id, anchor_id=f"anchor_{index}"),
            SimpleNamespace(
                node_id=f"knode_{index}",
                label="조건의 구체적 내용",
                node_type="CONCEPT",
                answer_bearing=False,
            ),
        )
        for index in range(number)
    )


def admission_service(scope: ReadOnlyCandidatePoolScope) -> KnowledgeRetrievalApplicationService:
    service = object.__new__(KnowledgeRetrievalApplicationService)
    value = cast(Any, service)
    value.resolve_snapshot_pointer = Mock(return_value=scope.graph_snapshot)
    value.resolve_access_policy = Mock(
        return_value=SimpleNamespace(answer_bearing_roles=("ADMIN",))
    )
    value._authorize = Mock()
    value._snapshot_source_resolution_cache = Mock(return_value=None)
    value._resolve_snapshot_source = Mock(return_value=profile().source_basis.source)
    return service


def test_limit_counts_sources_not_pointer_rows_and_explicitly_marks_truncation() -> None:
    scope = admission_scope()
    runs = tuple("analysisrun_" + seed * 32 for seed in "abc")
    rows = (*source_rows(runs[0], number=20), *source_rows(runs[1], number=30))
    session = AdmissionSession(runs, rows)
    result = admission_service(scope).admit_read_only_candidate_pool(cast(Session, session), scope)
    assert len(result.candidates) == 2 and result.truncated
    assert all(
        candidate.relevance_milli == 0 and candidate.solution is None
        for candidate in result.candidates
    )
    assert {candidate.analysis_run_id for candidate in result.candidates} == set(runs[:2])


def test_source_class_lifecycle_answer_bearing_exists_precedes_source_limit() -> None:
    scope = admission_scope(role="EDITOR")
    session = AdmissionSession((), ())
    result = admission_service(scope).admit_read_only_candidate_pool(cast(Session, session), scope)
    assert result.candidates == () and not result.truncated
    sql = str(
        session.statements[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "knowledge_nodes.answer_bearing IS false" in sql
    assert "knowledge_node_source_pointers.source_class IN ('PAST_EXAM')" in sql
    assert "items.lifecycle_state = 'ACTIVE'" in sql
    assert "knowledge_analysis_runs.state = 'ACCEPTED'" in sql
    assert "GROUP BY" not in sql
    assert "EXISTS (SELECT knowledge_node_source_pointers.pointer_id" in sql
    assert sql.index("knowledge_nodes.answer_bearing IS false") < sql.index("LIMIT 3")
    assert "assessment_item_occurrence_references" not in sql


def test_exact_revision_selection_stays_in_official_prelimit_predicates():
    selected = ("itemrev_" + "a" * 32,)
    scope = replace(admission_scope(role="EDITOR"), source_revision_ids=selected)
    statement = KnowledgeRetrievalApplicationService.candidate_pool_analysis_statement(
        scope, allow_answer_bearing=False
    )
    sql = str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert "knowledge_snapshot_analyses.source_revision_id IN ('" + selected[0] + "')" in sql
    assert sql.index("knowledge_snapshot_analyses.source_revision_id IN") < sql.index("LIMIT")
    assert "knowledge_nodes.answer_bearing IS false" in sql
    assert "items.lifecycle_state = 'ACTIVE'" in sql
    assert "knowledge_analysis_runs.state = 'ACCEPTED'" in sql


def test_occurrence_membership_is_exact_and_prelimit_without_waiving_authority() -> None:
    scope = admission_scope(
        role="EDITOR",
        population_scope=InferenceTransferPopulationScope.OCCURRENCE_BACKED_PAST_EXAM,
    )
    session = AdmissionSession((), ())
    service = admission_service(scope)
    service.admit_read_only_candidate_pool(cast(Session, session), scope)
    cast(Any, service)._authorize.assert_called_once()
    sql = str(
        session.statements[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "EXISTS (SELECT assessment_item_occurrence_references.analysis_run_id" in sql
    assert (
        "assessment_item_occurrence_references.graph_snapshot_revision_id = "
        "knowledge_snapshot_analyses.graph_snapshot_revision_id"
    ) in sql
    assert (
        "assessment_item_occurrence_references.analysis_run_id = "
        "knowledge_snapshot_analyses.analysis_run_id"
    ) in sql
    assert (
        "assessment_item_occurrence_references.item_revision_id = "
        "knowledge_snapshot_analyses.source_revision_id"
    ) in sql
    assert "assessment_item_occurrence_references.item_id = item_revisions.item_id" in sql
    assert "knowledge_nodes.answer_bearing IS false" in sql
    assert "knowledge_node_source_pointers.source_class = 'PAST_EXAM'" in sql
    assert "GROUP BY" not in sql
    assert sql.index("EXISTS") < sql.index("LIMIT 3")
    assert "current_revision_id" not in sql


def test_occurrence_scope_also_restricts_materialized_pointer_classes() -> None:
    scope = replace(
        admission_scope(
            population_scope=InferenceTransferPopulationScope.OCCURRENCE_BACKED_PAST_EXAM
        ),
        source_classes=("APPROVED_ITEM", "PAST_EXAM"),
    )
    run_id = "analysisrun_" + "a" * 32
    session = AdmissionSession((run_id,), source_rows(run_id))
    admission_service(scope).admit_read_only_candidate_pool(cast(Session, session), scope)
    detail_sql = str(
        session.statements[1].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "knowledge_node_source_pointers.source_class = 'PAST_EXAM'" in detail_sql


@pytest.mark.parametrize("invalid_scope", ("OCCURRENCE_BACKED_PAST_EXAM", "ALL", None))
def test_population_scope_rejects_untyped_or_unknown_values(invalid_scope: Any) -> None:
    with pytest.raises(ValueError, match="population scope"):
        replace(admission_scope(), population_scope=invalid_scope)


def test_graph_and_policy_hashes_are_exact_not_current_references() -> None:
    scope = admission_scope()
    service = admission_service(scope)
    cast(Any, service).resolve_snapshot_pointer.return_value = scope.graph_snapshot.model_copy(
        update={"manifest_sha256": sha("b")}
    )
    session = AdmissionSession((), ())
    with pytest.raises(KnowledgeRetrievalServiceError, match="Graph pin"):
        service.admit_read_only_candidate_pool(cast(Session, session), scope)
    assert not session.statements


def test_pointer_budget_overflow_is_error_not_silent_population_truncation() -> None:
    scope = admission_scope(maximum=1)
    run_id = "analysisrun_" + "a" * 32
    session = AdmissionSession((run_id,), source_rows(run_id, number=257))
    with pytest.raises(KnowledgeRetrievalServiceError) as error:
        admission_service(scope).admit_read_only_candidate_pool(cast(Session, session), scope)
    assert error.value.code == "KNOWLEDGE_RETRIEVAL_CANDIDATE_POOL_BUDGET_EXCEEDED"


def test_exact_analysis_selection_does_not_reauthorize_implicit_latest() -> None:
    scope = admission_scope()
    run_id = "analysisrun_" + "a" * 32
    scope = ReadOnlyCandidatePoolScope(
        **{
            field: getattr(scope, field)
            for field in scope.__dataclass_fields__
            if field != "analysis_run_ids"
        },
        analysis_run_ids=(run_id,),
    )
    session = AdmissionSession((), ())
    admission_service(scope).admit_read_only_candidate_pool(cast(Session, session), scope)
    sql = str(
        session.statements[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert run_id in sql and "current_revision_id" not in sql


def test_changed_exact_pointer_resolution_blocks_entire_result() -> None:
    scope = admission_scope()
    run_id = "analysisrun_" + "a" * 32
    service = admission_service(scope)
    source = profile().source_basis.source
    altered = source.model_copy(update={"item_revision_id": "itemrev_" + "e" * 32})
    cast(Any, service)._resolve_snapshot_source.side_effect = deque((source, source, altered))
    session = AdmissionSession((run_id,), source_rows(run_id))
    with pytest.raises(KnowledgeRetrievalServiceError, match="identity differs"):
        service.admit_read_only_candidate_pool(cast(Session, session), scope)
