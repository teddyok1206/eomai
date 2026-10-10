"""Guarded disposable PostgreSQL SQL admission checks, not NAS/corpus acceptance.

Only pg_temp shadow tables are written. Canonical source materialization keeps
its existing resolver tests; this suite executes the new DISTINCT-source and
pre-LIMIT policy/lifecycle/answer-bearing queries in real PostgreSQL.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock
from urllib.parse import unquote, urlsplit

import pytest
from eom_catalog_service.knowledge_retrieval_service import KnowledgeRetrievalApplicationService
from eom_orchestrator.database import build_engine
from sqlalchemy import text
from sqlalchemy.orm import Session

from scripts.api.testdb_guard import TestDatabaseManifest as DisposableManifest
from scripts.api.testdb_guard import validate_state_directory
from tests.unit.inference_transfer_fixtures import profile
from tests.unit.test_inference_transfer_candidate_admission import admission_scope

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
TABLES = (
    "items",
    "item_revisions",
    "knowledge_analysis_runs",
    "knowledge_snapshot_analyses",
    "knowledge_nodes",
    "knowledge_node_source_pointers",
)


@pytest.fixture
def pool_database():
    if os.environ.get("EOM_RUN_API_INTEGRATION") != "1":
        pytest.skip("use guarded testdb_run.sh; never production")
    state = validate_state_directory(Path(os.environ["EOM_CHAT_KNOWLEDGE_TEST_STATE"]))
    manifest = DisposableManifest.load(state / "manifest.json")
    parsed = urlsplit(os.environ["EOM_DATABASE_URL"])
    assert parsed.username == manifest.owner_role
    assert unquote(parsed.path.removeprefix("/")) == manifest.database
    engine = build_engine(os.environ["EOM_DATABASE_URL"])
    connection = engine.connect()
    try:
        assert connection.scalar(text("SELECT current_database()")) == manifest.database
        for table in TABLES:
            connection.exec_driver_sql(
                f"CREATE TEMP TABLE {table} AS SELECT * FROM app.{table} WITH NO DATA"
            )
        connection.execute(
            text("""
            INSERT INTO pg_temp.items(item_id,lifecycle_state)
            SELECT 'item_'||lpad(i::text,32,'0'), CASE WHEN i=3 THEN 'RETIRED' ELSE 'ACTIVE' END
            FROM generate_series(1,8) i;
        """)
        )
        connection.execute(
            text("""
            INSERT INTO pg_temp.item_revisions(item_revision_id,item_id,revision_state)
            SELECT 'itemrev_'||lpad(i::text,32,'0'),'item_'||lpad(i::text,32,'0'),
                   CASE WHEN i=4 THEN 'DRAFT' WHEN i=8 THEN 'SUPERSEDED' ELSE 'APPROVED' END
            FROM generate_series(1,8) i;
        """)
        )
        connection.execute(
            text("""
            INSERT INTO pg_temp.knowledge_analysis_runs(analysis_run_id,state)
            SELECT 'analysisrun_'||lpad(i::text,32,'0'),
                   CASE WHEN i=5 THEN 'FAILED' ELSE 'ACCEPTED' END
            FROM generate_series(1,8) i;
        """)
        )
        connection.execute(
            text("""
            INSERT INTO pg_temp.knowledge_snapshot_analyses(
                snapshot_analysis_id,graph_snapshot_revision_id,
                analysis_run_id,source_kind,source_revision_id)
            SELECT i,:snapshot,'analysisrun_'||lpad(i::text,32,'0'),
                'APPROVED_ITEM_REVISION','itemrev_'||lpad(i::text,32,'0')
            FROM generate_series(1,8) i
        """),
            {"snapshot": admission_scope().graph_snapshot.graph_snapshot_revision_id},
        )
        connection.execute(
            text("""
            INSERT INTO pg_temp.knowledge_nodes(
                graph_snapshot_revision_id,node_id,node_type,label,answer_bearing)
            SELECT :snapshot,'knode_'||i||'_'||p,'CONCEPT','synthetic condition',i=2
            FROM generate_series(1,8) i CROSS JOIN generate_series(1,4) p
        """),
            {"snapshot": admission_scope().graph_snapshot.graph_snapshot_revision_id},
        )
        connection.execute(
            text("""
            INSERT INTO pg_temp.knowledge_node_source_pointers(
                pointer_id,graph_snapshot_revision_id,
                analysis_run_id,node_id,anchor_id,source_class)
            SELECT (i-1)*4+p,:snapshot,'analysisrun_'||lpad(i::text,32,'0'),
                'knode_'||i||'_'||p,'anchor_'||i||'_'||p,
                CASE WHEN i=1 THEN 'APPROVED_ITEM' ELSE 'PAST_EXAM' END
            FROM generate_series(1,8) i CROSS JOIN generate_series(1,4) p
        """),
            {"snapshot": admission_scope().graph_snapshot.graph_snapshot_revision_id},
        )
        connection.commit()
        with Session(bind=connection) as session:
            yield session
    finally:
        connection.close()
        engine.dispose()


def service(scope):
    result = object.__new__(KnowledgeRetrievalApplicationService)
    value = cast(Any, result)
    value.resolve_snapshot_pointer = Mock(return_value=scope.graph_snapshot)
    value.resolve_access_policy = Mock(
        return_value=SimpleNamespace(answer_bearing_roles=("ADMIN",))
    )
    value._authorize = Mock()
    value._snapshot_source_resolution_cache = Mock(return_value=None)
    value._resolve_snapshot_source = Mock(return_value=profile().source_basis.source)
    return result


def test_real_postgres_filters_ineligible_sources_before_distinct_limit(pool_database):
    scope = admission_scope(maximum=2, role="EDITOR")
    result = service(scope).admit_read_only_candidate_pool(pool_database, scope)
    assert tuple(candidate.analysis_run_id for candidate in result.candidates) == tuple(
        "analysisrun_" + str(i).zfill(32) for i in (6, 7)
    )
    assert (
        result.truncated
    )  # exact historical superseded #8 remains eligible, not a latest substitution
    assert len(result.candidates) == 2
    assert all(len(candidate.node_ids) == 4 for candidate in result.candidates)
    assert all(not candidate.answer_bearing for candidate in result.candidates)


def test_real_postgres_answer_authority_and_exact_history_scope(pool_database):
    scope = admission_scope(maximum=8, role="ADMIN")
    result = service(scope).admit_read_only_candidate_pool(pool_database, scope)
    assert tuple(candidate.analysis_run_id for candidate in result.candidates) == tuple(
        "analysisrun_" + str(i).zfill(32) for i in (2, 6, 7, 8)
    )
    assert not result.truncated
    assert result.candidates[0].answer_bearing
