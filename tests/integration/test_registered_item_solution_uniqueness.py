"""Real PostgreSQL uniqueness/concurrency, synthetic relational rows, no model.

These tests do not claim application/Graph admission or valid scientific content.
They require the existing marker-guarded disposable owner database and cannot use
production. Existing past-exam uniqueness and unsuccessful retry history survive.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from runpy import run_path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.integration.test_control_plane_persistence import _workflow
from tests.integration.test_embedding_registry_persistence import _binding_source_ids, _seed, sha
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def solution_rows(guarded_engine):
    with Session(guarded_engine) as session, session.begin():
        seed = _seed(session)
        _, _, base_id, source_id = _binding_source_ids(session, seed)
        template = session.get(KnowledgeAnalysisRunRecord, source_id)
        assert template is not None
        value = {
            column.name: getattr(template, column.name) for column in template.__table__.columns
        }
        workflows = tuple(_workflow(session).workflow_id for _ in range(4))
        rows = []
        for workflow_id in workflows:
            identity = uuid4().hex
            rows.append(
                value
                | dict(
                    analysis_run_id="analysisrun_" + identity,
                    analysis_request_id="knowledgeanalysis_" + identity,
                    idempotency_key="registered-solution-db:" + identity,
                    workflow_id=workflow_id,
                    predecessor_analysis_run_id=base_id,
                    canonical_request={
                        "schema_version": "knowledge-analysis-request/11.0",
                        "synthetic": True,
                    },
                    state="ACCEPTED",
                    accepted_result_artifact_id=seed["artifact"],
                    accepted_result_artifact_revision_id=seed["artifact_revision"],
                    accepted_result_sha256=sha(),
                    completed_at=datetime.now(UTC),
                )
            )
    return guarded_engine, base_id, rows


def test_v11_unique_btree_is_additive_to_the_original_v10_index(guarded_engine):
    with guarded_engine.connect() as connection:
        rows = dict(
            connection.execute(
                text(
                    "SELECT indexname,indexdef FROM pg_indexes WHERE schemaname='app' "
                    "AND indexname IN "
                    "('uq_knowledge_analysis_accepted_solution_predecessor',"
                    "'uq_knowledge_analysis_registered_solution_predecessor')"
                )
            ).all()
        )
    assert len(rows) == 2
    old = rows["uq_knowledge_analysis_accepted_solution_predecessor"]
    new = rows["uq_knowledge_analysis_registered_solution_predecessor"]
    assert "UNIQUE INDEX" in new and "USING btree (predecessor_analysis_run_id)" in new
    assert "knowledge-analysis-request/10.0" in old and "11.0" not in old
    assert "knowledge-analysis-request/11.0" in new and "10.0" not in new
    assert "ACCEPTED" in old and "ACCEPTED" in new


def test_concurrent_registered_solution_acceptance_has_one_winner(solution_rows):
    engine, base_id, values = solution_rows
    barrier = Barrier(2)

    def insert(row):
        try:
            with Session(engine) as session, session.begin():
                session.execute(text("SET LOCAL statement_timeout = '10s'"))
                barrier.wait(timeout=5)
                session.add(KnowledgeAnalysisRunRecord(**row))
                session.flush()
            return "ACCEPTED"
        except IntegrityError as exc:
            assert (
                exc.orig.diag.constraint_name
                == "uq_knowledge_analysis_registered_solution_predecessor"
            )
            return "UNIQUE_CONFLICT"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(insert, values[:2]))
    assert sorted(outcomes) == ["ACCEPTED", "UNIQUE_CONFLICT"]
    with Session(engine) as session:
        actual = session.scalars(
            select(KnowledgeAnalysisRunRecord).where(
                KnowledgeAnalysisRunRecord.predecessor_analysis_run_id == base_id,
                KnowledgeAnalysisRunRecord.state == "ACCEPTED",
            )
        ).all()
        assert len(actual) == 1


def test_failed_history_and_interrupted_transaction_do_not_consume_acceptance(solution_rows):
    engine, base_id, values = solution_rows
    failed = values[0] | dict(
        state="FAILED",
        accepted_result_artifact_id=None,
        accepted_result_artifact_revision_id=None,
        accepted_result_sha256=None,
    )
    with Session(engine) as session, session.begin():
        session.add(KnowledgeAnalysisRunRecord(**failed))
    with Session(engine) as session:
        session.add(KnowledgeAnalysisRunRecord(**values[1]))
        session.flush()
        session.rollback()
    with Session(engine) as session, session.begin():
        session.add(KnowledgeAnalysisRunRecord(**values[1]))
    with Session(engine) as session:
        assert session.get(KnowledgeAnalysisRunRecord, failed["analysis_run_id"]).state == "FAILED"
        actual = session.scalars(
            select(KnowledgeAnalysisRunRecord).where(
                KnowledgeAnalysisRunRecord.predecessor_analysis_run_id == base_id,
                KnowledgeAnalysisRunRecord.state == "ACCEPTED",
            )
        ).all()
        assert len(actual) == 1 and actual[0].analysis_run_id == values[1]["analysis_run_id"]


def test_downgrade_cannot_remove_the_v11_fence_while_history_exists(solution_rows):
    engine, _base_id, values = solution_rows
    with Session(engine) as session, session.begin():
        session.add(KnowledgeAnalysisRunRecord(**values[0]))
    migration = run_path(
        str(
            Path(__file__).resolve().parents[2]
            / "migrations/versions/20261031_0065_registered_item_solution_successor.py"
        )
    )
    with engine.begin() as connection:
        with (
            Operations.context(MigrationContext.configure(connection)),
            pytest.raises(RuntimeError, match="REGISTERED_ITEM_SOLUTION_HISTORY_EXISTS"),
        ):
            migration["downgrade"]()
        assert (
            connection.scalar(
                text(
                    "SELECT to_regclass("
                    "'app.uq_knowledge_analysis_registered_solution_predecessor')"
                )
            )
            is not None
        )
