"""Candidate admission query/identity tests without PostgreSQL or artifacts."""

from __future__ import annotations

from collections import deque
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from eom_catalog_contracts import EvidenceBudget
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalApplicationService,
    KnowledgeRetrievalServiceError,
    ReadOnlyCandidatePoolScope,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from tests.unit.inference_transfer_fixtures import profile, sha


def admission_scope(*, maximum: int = 2, role: str = "ADMIN") -> ReadOnlyCandidatePoolScope:
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


def test_source_class_lifecycle_answer_bearing_filter_precedes_grouped_limit() -> None:
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
    assert "GROUP BY knowledge_snapshot_analyses.analysis_run_id" in sql
    assert sql.index("WHERE") < sql.index("GROUP BY") < sql.index("LIMIT 3")


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
