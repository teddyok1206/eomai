"""Guarded disposable PostgreSQL SQL admission checks, not NAS/corpus acceptance.

Only pg_temp shadow tables are written. Canonical source materialization keeps
its existing resolver tests; this suite executes the new DISTINCT-source and
pre-LIMIT policy/lifecycle/answer-bearing queries in real PostgreSQL.
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock
from urllib.parse import unquote, urlsplit

import pytest
from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.inference_transfer_catalog_adapter import (
    CatalogInferenceTransferSourceAdapter,
)
from eom_catalog_service.inference_transfer_scope import InferenceTransferPopulationScope
from eom_catalog_service.inference_transfer_service import (
    AdmittedInferenceTransferCorpus,
    AdmittedInferenceTransferSource,
    InferenceTransferSearchCommand,
    InferenceTransferServiceError,
)
from eom_catalog_service.inference_transfer_snapshot_catalog_adapter import (
    CatalogInferenceTransferSnapshotSourceAdapter,
    population_membership_statement,
)
from eom_catalog_service.inference_transfer_snapshot_service import (
    InferenceTransferSnapshotApplicationService,
)
from eom_catalog_service.knowledge_analysis_sources import (
    KnowledgeAnalysisSourceError,
    read_item_source_relations,
)
from eom_catalog_service.knowledge_retrieval_service import KnowledgeRetrievalApplicationService
from eom_orchestrator.database import build_engine
from sqlalchemy import text
from sqlalchemy.orm import Session

from scripts.api.testdb_guard import TestDatabaseManifest as DisposableManifest
from scripts.api.testdb_guard import validate_state_directory
from tests.unit.inference_transfer_fixtures import profile
from tests.unit.inference_transfer_snapshot_fixtures import snapshot_prepare, snapshot_read_request
from tests.unit.test_inference_transfer_candidate_admission import admission_scope

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
TABLES = (
    "items",
    "item_revisions",
    "knowledge_analysis_runs",
    "knowledge_snapshot_analyses",
    "knowledge_nodes",
    "knowledge_node_source_pointers",
    "assessment_item_occurrence_references",
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
        # Preserve the production key lookup shape, especially for the 72k
        # pointer fixture. CREATE TABLE AS does not copy any source indexes.
        for table, columns in (
            ("knowledge_snapshot_analyses", "graph_snapshot_revision_id,analysis_run_id"),
            ("knowledge_nodes", "graph_snapshot_revision_id,node_id"),
            ("knowledge_analysis_runs", "analysis_run_id"),
            ("item_revisions", "item_revision_id"),
            ("items", "item_id"),
        ):
            connection.exec_driver_sql(f"CREATE UNIQUE INDEX ON pg_temp.{table} ({columns})")
        connection.exec_driver_sql(
            "CREATE INDEX ON pg_temp.knowledge_node_source_pointers "
            "(graph_snapshot_revision_id,node_id,analysis_run_id,source_revision_id,"
            "artifact_revision_id,member_path,anchor_id)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX ON pg_temp.knowledge_node_source_pointers "
            "(graph_snapshot_revision_id,source_class,source_revision_id)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX selected_source_revision_lookup ON pg_temp.knowledge_snapshot_analyses "
            "(source_kind,source_revision_id)"
        )
        connection.exec_driver_sql("SET statement_timeout='20s'")
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
            INSERT INTO pg_temp.item_revisions(item_revision_id,item_id,revision_state)
            VALUES ('itemrev_'||lpad('9',32,'0'),'item_'||lpad('8',32,'0'),'APPROVED')
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
            INSERT INTO pg_temp.assessment_item_occurrence_references(
                graph_snapshot_revision_id,placement_node_id,
                analysis_run_id,item_id,item_revision_id)
            SELECT :snapshot,'placement_'||i,'analysisrun_'||lpad(i::text,32,'0'),
                'item_'||lpad(i::text,32,'0'),
                'itemrev_'||lpad((CASE WHEN i=8 THEN 9 ELSE i END)::text,32,'0')
            FROM generate_series(1,8) i WHERE i<>2
        """),
            {"snapshot": admission_scope().graph_snapshot.graph_snapshot_revision_id},
        )
        # Temp shadows lose production indexes/constraints. Preserve the lookup
        # shape for EXPLAIN; a nonunique fixture index also lets EXISTS prove
        # robustness against duplicate placements that production rejects.
        connection.exec_driver_sql(
            "CREATE INDEX inference_transfer_occurrence_analysis ON "
            "pg_temp.assessment_item_occurrence_references"
            "(graph_snapshot_revision_id,analysis_run_id)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX inference_transfer_occurrence_revision ON "
            "pg_temp.assessment_item_occurrence_references"
            "(graph_snapshot_revision_id,item_revision_id)"
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
        for table in TABLES:
            connection.exec_driver_sql(f"ANALYZE pg_temp.{table}")
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
        return_value=SimpleNamespace(
            answer_bearing_roles=("ADMIN",), content_sha256=scope.access_policy_sha256
        )
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


def occurrence_scope(*, maximum: int = 8, role: str = "ADMIN"):
    return admission_scope(
        maximum=maximum,
        role=role,
        population_scope=InferenceTransferPopulationScope.OCCURRENCE_BACKED_PAST_EXAM,
    )


def test_real_postgres_prefetch_does_not_count_additive_reports_as_original_targets(pool_database):
    """SQL-only scale fixture; pg_temp metadata is NOT canonical source authority."""
    for table in TABLES:
        pool_database.execute(text(f"TRUNCATE pg_temp.{table}"))
    snapshot = admission_scope().graph_snapshot.graph_snapshot_revision_id
    statements = (
        "INSERT INTO pg_temp.items(item_id,lifecycle_state) "
        "SELECT 'item_'||lpad(i::text,32,'0'),'ACTIVE' FROM generate_series(1,520) i",
        "INSERT INTO pg_temp.item_revisions(item_revision_id,item_id,revision_state) "
        "SELECT 'itemrev_'||lpad(i::text,32,'0'),'item_'||lpad(i::text,32,'0'),'APPROVED' "
        "FROM generate_series(1,520) i",
        "INSERT INTO pg_temp.knowledge_analysis_runs(analysis_run_id,state) "
        "SELECT 'analysisrun_'||lpad(i::text,32,'0'),'ACCEPTED' FROM generate_series(1,1040) i",
        "INSERT INTO pg_temp.knowledge_snapshot_analyses(snapshot_analysis_id,"
        "graph_snapshot_revision_id,analysis_run_id,source_kind,source_revision_id) "
        "SELECT i,:snapshot,'analysisrun_'||lpad(i::text,32,'0'),'APPROVED_ITEM_REVISION',"
        "'itemrev_'||lpad(((i-1)%520+1)::text,32,'0') FROM generate_series(1,1040) i",
        "INSERT INTO pg_temp.knowledge_nodes(graph_snapshot_revision_id,node_id,"
        "node_type,label,answer_bearing) SELECT :snapshot,'knode_'||i,'CONCEPT','synthetic',false "
        "FROM generate_series(1,1040) i",
        "INSERT INTO pg_temp.knowledge_node_source_pointers(pointer_id,"
        "graph_snapshot_revision_id,analysis_run_id,node_id,anchor_id,source_class) "
        "SELECT i,:snapshot,'analysisrun_'||lpad(i::text,32,'0'),'knode_'||i,'anchor_'||i,"
        "'PAST_EXAM' FROM generate_series(1,1040) i",
        "INSERT INTO pg_temp.assessment_item_occurrence_references(graph_snapshot_revision_id,"
        "placement_node_id,analysis_run_id,item_id,item_revision_id) "
        "SELECT :snapshot,'placement_'||i,'analysisrun_'||lpad(i::text,32,'0'),"
        "'item_'||lpad(i::text,32,'0'),'itemrev_'||lpad(i::text,32,'0') "
        "FROM generate_series(1,520) i",
    )
    for statement in statements:
        pool_database.execute(text(statement), {"snapshot": snapshot})
    for table in TABLES:
        pool_database.execute(text(f"ANALYZE pg_temp.{table}"))
    scope = occurrence_scope(maximum=1024)
    selection = KnowledgeRetrievalApplicationService.candidate_pool_analysis_statement(
        scope, allow_answer_bearing=True
    )
    selected = tuple(pool_database.scalars(selection))
    members = tuple(pool_database.scalars(population_membership_statement(scope)))
    assert len(selected) == len(members) == 520
    assert tuple(row.analysis_run_id for row in members) == selected
    assert len({row.source_revision_id for row in members}) == 520
    # Many matching pointers must not multiply the outer source relation. This
    # fixture deliberately has no FK, so an orphan node must still be rejected.
    pool_database.execute(
        text(
            "INSERT INTO pg_temp.knowledge_node_source_pointers(pointer_id,"
            "graph_snapshot_revision_id,analysis_run_id,node_id,anchor_id,source_class) "
            "SELECT 1040+i,:snapshot,'analysisrun_'||lpad(((i-1)%520+1)::text,32,'0'),"
            "'knode_'||((i-1)%520+1),'duplicate_'||i,'PAST_EXAM' "
            "FROM generate_series(1,72800) i"
        ),
        {"snapshot": snapshot},
    )
    pool_database.execute(text("ANALYZE pg_temp.knowledge_node_source_pointers"))
    assert tuple(pool_database.scalars(selection)) == selected
    compiled = str(
        population_membership_statement(scope).compile(
            dialect=pool_database.get_bind().dialect, compile_kwargs={"literal_binds": True}
        )
    )
    plan = pool_database.scalar(text("EXPLAIN (ANALYZE, FORMAT JSON, TIMING FALSE) " + compiled))[0]
    pending = [plan["Plan"]]
    cte = []
    while pending:
        node = pending.pop()
        pending.extend(node.get("Plans", ()))
        if node.get("Subplan Name") == "CTE eligible_snapshot_analyses":
            cte.append(node)
    assert len(cte) == 1 and cte[0]["Actual Loops"] == 1
    assert cte[0]["Actual Rows"] == plan["Plan"]["Actual Rows"] == 520
    # This bounded metadata benchmark is not full source/Artifact acceptance.
    assert plan["Execution Time"] < 10000
    target = "itemrev_" + "1".zfill(32)
    selected_scope = replace(scope, source_revision_ids=(target,))
    narrowed = tuple(pool_database.scalars(population_membership_statement(selected_scope)))
    assert len(narrowed) == 1 and narrowed[0].source_revision_id == target
    assert narrowed[0].analysis_run_id == "analysisrun_" + "1".zfill(32)
    # Full population discovery remains unchanged after this target-local read.
    assert len(tuple(pool_database.scalars(population_membership_statement(scope)))) == 520
    # The full-scope limit still exposes the520th member as overflow.
    assert (
        len(
            tuple(
                pool_database.scalars(
                    population_membership_statement(replace(scope, maximum_candidates=519))
                )
            )
        )
        == 520
    )


@pytest.mark.parametrize("target", [1, 2, 3, 4, 5, 6, 7, 8, 99])
def test_revision_subset_keeps_occurrence_lifecycle_and_answer_predicates(pool_database, target):
    scope = replace(occurrence_scope(), source_revision_ids=("itemrev_" + str(target).zfill(32),))
    result = service(scope).admit_read_only_candidate_pool(pool_database, scope)
    expected = ("analysisrun_" + str(target).zfill(32),) if target in {6, 7} else ()
    assert tuple(value.analysis_run_id for value in result.candidates) == expected


@pytest.mark.parametrize("allow_answers", [False, True])
def test_pointer_exists_requires_same_eligible_node_not_just_source_class(
    pool_database, allow_answers
):
    scope = replace(occurrence_scope(maximum=8), analysis_run_ids=("analysisrun_" + "6".zfill(32),))
    statement = KnowledgeRetrievalApplicationService.candidate_pool_analysis_statement(
        scope, allow_answer_bearing=allow_answers
    )
    expected = ("analysisrun_" + "6".zfill(32),)
    assert tuple(pool_database.scalars(statement)) == expected
    pool_database.execute(
        text("DELETE FROM pg_temp.knowledge_nodes WHERE node_id LIKE 'knode_6_%'")
    )
    assert tuple(pool_database.scalars(statement)) == ()


def test_real_postgres_occurrence_scope_excludes_canary_and_wrong_historical_revision(
    pool_database,
):
    scope = occurrence_scope()
    result = service(scope).admit_read_only_candidate_pool(pool_database, scope)
    assert tuple(candidate.analysis_run_id for candidate in result.candidates) == tuple(
        "analysisrun_" + str(i).zfill(32) for i in (6, 7)
    )
    assert not result.truncated
    # #2 is a valid accepted answer-bearing canary but has no occurrence.
    # #8 has an occurrence of another exact historical Item revision.


def test_real_postgres_occurrence_scope_uses_exact_superseded_revision_not_current(pool_database):
    pool_database.execute(
        text(
            "UPDATE pg_temp.assessment_item_occurrence_references "
            "SET item_revision_id=:exact WHERE placement_node_id='placement_8'"
        ),
        {"exact": "itemrev_" + "8".zfill(32)},
    )
    scope = occurrence_scope()
    result = service(scope).admit_read_only_candidate_pool(pool_database, scope)
    assert tuple(candidate.analysis_run_id for candidate in result.candidates) == tuple(
        "analysisrun_" + str(i).zfill(32) for i in (6, 7, 8)
    )
    assert not result.truncated


def test_real_postgres_occurrence_filter_precedes_limit_and_does_not_waive_answer_policy(
    pool_database,
):
    pool_database.execute(
        text("""
        INSERT INTO pg_temp.assessment_item_occurrence_references(
            graph_snapshot_revision_id,placement_node_id,analysis_run_id,item_id,item_revision_id)
        VALUES (:snapshot,'placement_2',:run,:item,:revision)
        """),
        {
            "snapshot": admission_scope().graph_snapshot.graph_snapshot_revision_id,
            "run": "analysisrun_" + "2".zfill(32),
            "item": "item_" + "2".zfill(32),
            "revision": "itemrev_" + "2".zfill(32),
        },
    )
    scope = occurrence_scope(maximum=1, role="EDITOR")
    result = service(scope).admit_read_only_candidate_pool(pool_database, scope)
    assert tuple(candidate.analysis_run_id for candidate in result.candidates) == (
        "analysisrun_" + "6".zfill(32),
    )
    assert result.truncated  # #7, not the unauthorized #2, consumes the lookahead
    assert not result.candidates[0].answer_bearing


@pytest.mark.parametrize(
    "field,value",
    (
        ("graph_snapshot_revision_id", "graphrev_" + "f" * 32),
        ("analysis_run_id", "analysisrun_" + "8".zfill(32)),
        ("item_id", "item_" + "7".zfill(32)),
        ("item_revision_id", "itemrev_" + "7".zfill(32)),
    ),
)
def test_real_postgres_occurrence_must_match_all_exact_source_identities(
    pool_database, field, value
):
    # The parameterized field names are a fixed fixture allowlist, not input.
    pool_database.execute(
        text(
            f"UPDATE pg_temp.assessment_item_occurrence_references SET {field}=:value "
            "WHERE placement_node_id='placement_6'"
        ),
        {"value": value},
    )
    scope = occurrence_scope()
    result = service(scope).admit_read_only_candidate_pool(pool_database, scope)
    assert tuple(candidate.analysis_run_id for candidate in result.candidates) == (
        "analysisrun_" + "7".zfill(32),
    )


def test_real_postgres_duplicate_placements_do_not_duplicate_or_truncate_sources(pool_database):
    pool_database.execute(
        text("""
        INSERT INTO pg_temp.assessment_item_occurrence_references(
            graph_snapshot_revision_id,placement_node_id,analysis_run_id,item_id,item_revision_id)
        SELECT graph_snapshot_revision_id,placement_node_id||'_duplicate_'||i,
            analysis_run_id,item_id,item_revision_id
        FROM pg_temp.assessment_item_occurrence_references
        CROSS JOIN generate_series(1,4) i
        WHERE placement_node_id='placement_6'
        """)
    )
    scope = occurrence_scope(maximum=2)
    result = service(scope).admit_read_only_candidate_pool(pool_database, scope)
    assert len(result.candidates) == 2 and not result.truncated
    assert len({candidate.analysis_run_id for candidate in result.candidates}) == 2


def test_real_postgres_pair_exact_run_filter_does_not_substitute_other_eligible_sources(
    pool_database,
):
    requested = tuple("analysisrun_" + str(i).zfill(32) for i in (2, 6))
    scope = replace(occurrence_scope(maximum=2), analysis_run_ids=requested)
    result = service(scope).admit_read_only_candidate_pool(pool_database, scope)
    assert tuple(candidate.analysis_run_id for candidate in result.candidates) == (requested[1],)
    assert not result.truncated
    # Missing occurrence for requested canary #2 must not be filled by valid #7.


def test_real_postgres_occurrence_membership_uses_existing_index_shape(pool_database):
    scope = occurrence_scope()
    pool_database.execute(text("SET LOCAL enable_seqscan=off"))
    # Execute the owner's actual admission statement, then EXPLAIN the same
    # compiled query; do not substitute a more convenient probe query.
    statements: list[Any] = []
    original_scalars = pool_database.scalars

    def capture(statement, *args, **kwargs):
        statements.append(statement)
        return original_scalars(statement, *args, **kwargs)

    pool_database.scalars = capture
    try:
        service(scope).admit_read_only_candidate_pool(pool_database, scope)
    finally:
        pool_database.scalars = original_scalars
    compiled = statements[0].compile(
        dialect=pool_database.get_bind().dialect, compile_kwargs={"literal_binds": True}
    )
    plan = "\n".join(pool_database.scalars(text("EXPLAIN (COSTS OFF) " + str(compiled))).all())
    assert "inference_transfer_occurrence_" in plan


def test_real_postgres_final_reauthorization_reuses_scope_and_rejects_membership_drift(
    pool_database, monkeypatch
):
    scope = occurrence_scope()
    retrieval = service(scope)
    initial = retrieval.admit_read_only_candidate_pool(pool_database, scope)
    frozen = AdmittedInferenceTransferCorpus(
        profiles=(),
        graph_scores=(),
        truncated=initial.truncated,
        missing_solution_reports=len(initial.candidates),
        sources=tuple(
            AdmittedInferenceTransferSource(candidate.analysis_run_id, candidate.source)
            for candidate in initial.candidates
        ),
    )
    pool_database.execute(
        text(
            "UPDATE pg_temp.assessment_item_occurrence_references "
            "SET item_revision_id=:other WHERE placement_node_id='placement_6'"
        ),
        {"other": "itemrev_" + "7".zfill(32)},
    )
    pool_database.commit()
    adapter = object.__new__(CatalogInferenceTransferSourceAdapter)
    adapter.retrieval = retrieval
    adapter.sessions = lambda: Session(bind=pool_database.get_bind())
    observed_scopes = []

    def actual_scope(_session, request):
        observed_scopes.append(request.population_scope)
        return replace(scope, population_scope=request.population_scope)

    monkeypatch.setattr(adapter, "_scope", actual_scope)
    request = InferenceTransferSearchCommand(
        actor_id=scope.requested_by,
        graph_snapshot=scope.graph_snapshot,
        access_policy_revision_id=scope.access_policy_revision_id,
        access_policy_sha256=scope.access_policy_sha256,
        query_item_revision_id="itemrev_" + "6".zfill(32),
        top_k=2,
        population_scope=scope.population_scope,
    )
    with pytest.raises(InferenceTransferServiceError, match="SOURCE_PIN_MISMATCH"):
        adapter.reauthorize(request, frozen)
    assert observed_scopes == [InferenceTransferPopulationScope.OCCURRENCE_BACKED_PAST_EXAM]


def snapshot_owner(pool_database, monkeypatch):
    """Actual admission SQL/report absence, synthetic authority/source metadata only."""
    scope = occurrence_scope()
    retrieval = service(scope)
    # The SQL-only predecessor fixture bypasses __init__. Snapshot admission
    # also runs the real accepted-report resolver; its empty result must not
    # fail because the fixture omitted the normal Artifact owner adapter.
    retrieval.artifacts = CatalogArtifactService(pool_database.get_bind())
    synthetic = profile().source_basis.source

    def source(_session, _snapshot_id, source_pointer, **_kwargs):
        suffix = source_pointer.analysis_run_id.removeprefix("analysisrun_")
        return synthetic.model_copy(
            update={"item_id": "item_" + suffix, "item_revision_id": "itemrev_" + suffix}
        )

    monkeypatch.setattr(retrieval, "_resolve_snapshot_source", source)
    owner = object.__new__(CatalogInferenceTransferSnapshotSourceAdapter)
    owner.engine = pool_database.get_bind()
    owner.sources = object.__new__(CatalogInferenceTransferSourceAdapter)
    owner.sources.retrieval = retrieval
    owner.sources.sessions = lambda: Session(bind=pool_database.get_bind())
    monkeypatch.setattr(
        owner.sources,
        "_scope",
        lambda _session, command: replace(
            scope,
            requested_by=command.actor_id,
            maximum_candidates=command.maximum_candidates,
            population_scope=command.population_scope,
        ),
    )
    return InferenceTransferSnapshotApplicationService(owner)


def test_real_postgres_snapshot_preserves_full_missing_report_denominator(
    pool_database,
    monkeypatch,
):
    owner = snapshot_owner(pool_database, monkeypatch)
    prepared = owner.prepare("synthetic-operator", snapshot_prepare(query_item_revision_ids=()))
    assert (
        prepared.header.source_count,
        prepared.header.profile_count,
        prepared.header.missing_report_count,
    ) == (2, 0, 2)
    assert tuple(row.base_analysis_run_id for row in prepared.index) == tuple(
        "analysisrun_" + str(i).zfill(32) for i in (6, 7)
    )
    read = owner.read("synthetic-operator", snapshot_read_request(prepared))
    assert all(row.staged_entry is None for row in read.records)
    assert read.baselines == ()


def test_real_postgres_snapshot_rejects_nonselected_occurrence_drift_before_read(
    pool_database,
    monkeypatch,
):
    owner = snapshot_owner(pool_database, monkeypatch)
    prepared = owner.prepare("synthetic-operator", snapshot_prepare(query_item_revision_ids=()))
    pool_database.execute(
        text(
            "UPDATE pg_temp.assessment_item_occurrence_references "
            "SET item_revision_id=:other WHERE placement_node_id='placement_7'"
        ),
        {"other": "itemrev_" + "8".zfill(32)},
    )
    pool_database.commit()
    with pytest.raises(InferenceTransferServiceError, match="SNAPSHOT_CHANGED"):
        owner.read(
            "synthetic-operator",
            snapshot_read_request(
                prepared,
                selected_index_entries=prepared.index[:1],
            ),
        )


@pytest.fixture
def item_source_relation_database(pool_database):
    """Same guarded temporary database; only additional pg_temp shadows are written."""
    tables = (
        "item_components",
        "legacy_item_extraction_decisions",
        "legacy_item_extraction_batch_work_units",
    )
    for table in tables:
        pool_database.execute(
            text(f"CREATE TEMP TABLE {table} AS SELECT * FROM app.{table} WITH NO DATA")
        )
    # Preserve actual indexed lookup shapes without copying production uniqueness:
    # deliberately ambiguous temporary rows must survive the map's grouping.
    pool_database.execute(
        text(
            "CREATE INDEX item_relation_component_revision ON "
            "pg_temp.item_components(item_revision_id)"
        )
    )
    pool_database.execute(
        text(
            "CREATE INDEX item_relation_decision_acceptance_proposal ON "
            "pg_temp.legacy_item_extraction_decisions(acceptance_id,item_proposal_id)"
        )
    )
    pool_database.execute(text("TRUNCATE pg_temp.item_revisions"))
    pool_database.execute(
        text("""
        INSERT INTO pg_temp.item_revisions(item_revision_id,item_id,revision_state,metadata_json)
        SELECT 'itemrev_'||lpad(i::text,32,'0'),'item_'||lpad(i::text,32,'0'),'APPROVED',
            jsonb_build_object('source_kind','PAST_EXAM',
                'extraction_acceptance_id','itemacceptance_'||lpad(i::text,32,'0'),
                'extraction_result_id','itemextractresult_'||lpad(i::text,32,'0'),
                'item_proposal_id','itemproposal_'||lpad(i::text,32,'0'),'item_number',i)
        FROM generate_series(1,545) i
    """)
    )
    pool_database.execute(
        text("""
        INSERT INTO pg_temp.item_components(item_component_id,item_revision_id,component_type,
            ordinal,schema_ref,media_type,artifact_id,artifact_revision_id,sha256,logical_name,
            required,metadata_json)
        SELECT 'component_'||lpad(i::text,32,'0'),'itemrev_'||lpad(i::text,32,'0'),
            'ITEM_CONTENT',0,'eom.assessment.item-content/1.0','application/json',
            'artifact_'||lpad(i::text,32,'0'),'rev_'||lpad(i::text,32,'0'),
            'sha256:'||repeat('a',64),'item-content.json',true,'{}'::jsonb
        FROM generate_series(1,545) i
    """)
    )
    pool_database.execute(
        text("""
        INSERT INTO pg_temp.legacy_item_extraction_decisions(decision_id,acceptance_id,
            item_proposal_id,item_number,decision)
        SELECT i,'itemacceptance_'||lpad(i::text,32,'0'),
            'itemproposal_'||lpad(i::text,32,'0'),i,'ACCEPT'
        FROM generate_series(1,545) i
    """)
    )
    pool_database.execute(
        text("""
        INSERT INTO pg_temp.legacy_item_extraction_batch_work_units(work_unit_id,
            extraction_batch_id,state,acceptance_id,extraction_result_id,created_at)
        SELECT 'legacyworkunit_'||lpad(i::text,32,'0'),
            'legacybatch_'||lpad(i::text,32,'0'),'ACCEPTED',
            'itemacceptance_'||lpad(i::text,32,'0'),
            'itemextractresult_'||lpad(i::text,32,'0'),'2026-10-01T00:00:00Z'::timestamptz
        FROM generate_series(1,545) i
    """)
    )
    for table in (*tables, "item_revisions"):
        pool_database.execute(text(f"ANALYZE pg_temp.{table}"))
    return pool_database


def item_source_relation_keys(number):
    suffix = str(number).zfill(32)
    return (
        "itemrev_" + suffix,
        ("itemacceptance_" + suffix, "itemproposal_" + suffix, number),
        ("itemacceptance_" + suffix, "itemextractresult_" + suffix),
    )


def capture_item_source_relations(session, selected):
    """Capture actual ORM statements, not synthetic query-count expectations."""
    statements = []
    original = session.scalars
    selected_ids = frozenset(selected)

    def observed(statement, *args, **kwargs):
        statements.append(statement)
        return original(statement, *args, **kwargs)

    session.scalars = observed
    try:
        relations = read_item_source_relations(session, selected)
        # Per-Item map lookup must perform no additional SQL.
        for number in range(1, 546):
            revision, decision, unit = item_source_relation_keys(number)
            if revision in selected_ids:
                relations.components(session, revision)
                relations.decisions(session, decision)
                relations.work_units(session, unit)
    finally:
        session.scalars = original
    return relations, tuple(statements)


def test_real_postgres_item_relations_are_four_fresh_queries_not_per_item_or_authority_cache(
    item_source_relation_database,
):
    session = item_source_relation_database
    selected = tuple(item_source_relation_keys(number)[0] for number in range(1, 546))
    first_revision, first_decision, first_unit = item_source_relation_keys(1)
    captures = []
    for phase in range(4):
        if phase == 1:
            session.execute(
                text(
                    "UPDATE pg_temp.legacy_item_extraction_decisions "
                    "SET decision='REJECT' WHERE decision_id=1"
                )
            )
        elif phase == 2:
            session.execute(
                text("DELETE FROM pg_temp.item_components WHERE item_revision_id=:revision"),
                {"revision": first_revision},
            )
            session.execute(
                text(
                    "UPDATE pg_temp.legacy_item_extraction_batch_work_units "
                    "SET state='FAILED' WHERE acceptance_id=:acceptance"
                ),
                {"acceptance": first_unit[0]},
            )
        elif phase == 3:
            session.execute(
                text("DELETE FROM pg_temp.legacy_item_extraction_decisions WHERE decision_id=1")
            )
        relations, statements = capture_item_source_relations(session, selected)
        assert len(statements) == 4
        assert tuple(
            statement.column_descriptions[0]["entity"].__tablename__ for statement in statements
        ) == (
            "item_revisions",
            "item_components",
            "legacy_item_extraction_decisions",
            "legacy_item_extraction_batch_work_units",
        )
        assert len(relations.components(session, first_revision)) == (1 if phase < 2 else 0)
        decisions = relations.decisions(session, first_decision)
        assert len(decisions) == (1 if phase < 3 else 0)
        if decisions:
            assert decisions[0].decision == ("ACCEPT" if phase == 0 else "REJECT")
        assert len(relations.work_units(session, first_unit)) == (1 if phase < 2 else 0)
        # Unchanged sources remain present; none is silently substituted for a missing row.
        for number in (2, 545):
            revision, decision, unit = item_source_relation_keys(number)
            assert len(relations.components(session, revision)) == 1
            assert relations.decisions(session, decision)[0].decision == "ACCEPT"
            assert len(relations.work_units(session, unit)) == 1
        assert all(relations is not previous for previous in captures)
        captures.append(relations)
    # This proves fresh current relation reads, not a canonical source/Artifact grant.


def test_real_postgres_item_relations_preserve_ambiguity_and_original_work_unit_order(
    item_source_relation_database,
):
    session = item_source_relation_database
    revision, decision, unit = item_source_relation_keys(1)
    session.execute(
        text("""
        INSERT INTO pg_temp.legacy_item_extraction_decisions
            (decision_id,acceptance_id,item_proposal_id,item_number,decision)
        SELECT 999,acceptance_id,item_proposal_id,item_number,'REJECT'
        FROM pg_temp.legacy_item_extraction_decisions WHERE decision_id=1
    """)
    )
    for suffix, batch, created, state in (
        ("a", "a", "2026-09-30T00:00:00Z", "ACCEPTED"),
        ("b", "0", "2026-10-01T00:00:00Z", "ACCEPTED"),
        ("c", "0", "2026-10-01T00:00:00Z", "ACCEPTED"),
        ("d", "0", "2026-09-29T00:00:00Z", "FAILED"),
    ):
        session.execute(
            text("""
            INSERT INTO pg_temp.legacy_item_extraction_batch_work_units
                (work_unit_id,extraction_batch_id,state,acceptance_id,extraction_result_id,created_at)
            VALUES (:work,:batch,:state,:acceptance,:result,:created)
        """),
            {
                "work": "legacyworkunit_" + suffix * 32,
                "batch": "legacybatch_" + batch * 32,
                "state": state,
                "acceptance": unit[0],
                "result": unit[1],
                "created": created,
            },
        )
    relations, statements = capture_item_source_relations(session, (revision,))
    assert len(statements) == 4
    assert len(relations.decisions(session, decision)) == 2  # no set/dict last-row-wins
    assert {row.decision for row in relations.decisions(session, decision)} == {"ACCEPT", "REJECT"}
    assert tuple(row.work_unit_id for row in relations.work_units(session, unit)) == (
        "legacyworkunit_" + "a" * 32,
        "legacyworkunit_" + "b" * 32,
        "legacyworkunit_" + "c" * 32,
        "legacyworkunit_" + "1".zfill(32),
    )


def test_real_postgres_item_relations_keep_existing_component_and_decision_index_shapes(
    item_source_relation_database,
):
    session = item_source_relation_database
    session.execute(text("SET LOCAL enable_seqscan=off"))
    revision = item_source_relation_keys(1)[0]
    _relations, statements = capture_item_source_relations(session, (revision,))
    for statement, expected_index in (
        (statements[1], "item_relation_component_revision"),
        (statements[2], "item_relation_decision_acceptance_proposal"),
    ):
        compiled = statement.compile(
            dialect=session.get_bind().dialect, compile_kwargs={"literal_binds": True}
        )
        plan = "\n".join(session.scalars(text("EXPLAIN (COSTS OFF) " + str(compiled))))
        assert expected_index in plan
    # Work-unit pair has no corresponding production index today. Do not invent
    # one in this fixture or claim this gate proves an indexed work-unit lookup.


def test_real_postgres_item_relations_reject_different_session_and_finished_root(
    item_source_relation_database,
):
    session = item_source_relation_database
    revision, decision, unit = item_source_relation_keys(1)
    relations = read_item_source_relations(session, (revision,))
    with Session(bind=session.get_bind()) as other:
        for method, key in (
            (relations.components, revision),
            (relations.decisions, decision),
            (relations.work_units, unit),
        ):
            with pytest.raises(KnowledgeAnalysisSourceError, match="out of scope"):
                method(other, key)
    session.commit()
    for method, key in (
        (relations.components, revision),
        (relations.decisions, decision),
        (relations.work_units, unit),
    ):
        with pytest.raises(KnowledgeAnalysisSourceError, match="out of scope"):
            method(session, key)


@pytest.fixture
def population_observation_database(item_source_relation_database):
    """545 synthetic source lineages, pg_temp only; no Artifact bytes or authority."""
    session = item_source_relation_database
    tables = (
        "knowledge_graph_snapshots",
        "legacy_item_extraction_acceptances",
        "legacy_item_extraction_batches",
        "assessment_source_bundle_revisions",
        "assessment_layout_observations",
        "artifacts",
        "artifact_revisions",
        "jobs",
    )
    for table in tables:
        session.execute(
            text(f"CREATE TEMP TABLE {table} AS SELECT * FROM app.{table} WITH NO DATA")
        )
    for table in TABLES:
        if table != "item_revisions":
            session.execute(text(f"TRUNCATE pg_temp.{table}"))
    snapshot = occurrence_scope().graph_snapshot.graph_snapshot_revision_id
    statements = (
        "INSERT INTO pg_temp.knowledge_graph_snapshots(graph_snapshot_revision_id,graph_id,state,"
        "manifest_artifact_id,manifest_artifact_revision_id,manifest_sha256) "
        "VALUES (:snapshot,:graph,'PUBLISHED','artifact_'||lpad('4007',32,'0'),"
        "'rev_'||lpad('4007',32,'0'),'sha256:'||repeat('a',64))",
        "INSERT INTO pg_temp.items(item_id,lifecycle_state) "
        "SELECT 'item_'||lpad(i::text,32,'0'),'ACTIVE' FROM generate_series(1,545) i",
        "INSERT INTO pg_temp.knowledge_analysis_runs(analysis_run_id,state,canonical_request,"
        "accepted_result_artifact_id,accepted_result_artifact_revision_id,accepted_result_sha256) "
        "SELECT 'analysisrun_'||lpad(i::text,32,'0'),'ACCEPTED',"
        "jsonb_build_object('schema_version','knowledge-analysis-request/9.0','source',"
        "jsonb_build_object('source_class','PAST_EXAM',"
        "'layout_observation',jsonb_build_object('assessment_layout_observation_id','layout_1'),"
        "'artifact_member',jsonb_build_object('artifact_id','artifact_'||lpad(i::text,32,'0'),"
        "'artifact_revision_id','rev_'||lpad(i::text,32,'0')))),"
        "'artifact_'||lpad((1000+i)::text,32,'0'),'rev_'||lpad((1000+i)::text,32,'0'),"
        "'sha256:'||repeat('a',64) FROM generate_series(1,545) i",
        "INSERT INTO pg_temp.knowledge_snapshot_analyses(snapshot_analysis_id,"
        "graph_snapshot_revision_id,analysis_run_id,source_kind,source_revision_id,"
        "source_artifact_id,source_artifact_revision_id,source_sha256,"
        "accepted_result_artifact_id,accepted_result_artifact_revision_id,accepted_result_sha256) "
        "SELECT i,:snapshot,'analysisrun_'||lpad(i::text,32,'0'),'APPROVED_ITEM_REVISION',"
        "'itemrev_'||lpad(i::text,32,'0'),'artifact_'||lpad(i::text,32,'0'),"
        "'rev_'||lpad(i::text,32,'0'),'sha256:'||repeat('a',64),"
        "'artifact_'||lpad((1000+i)::text,32,'0'),'rev_'||lpad((1000+i)::text,32,'0'),"
        "'sha256:'||repeat('a',64) FROM generate_series(1,545) i",
        "INSERT INTO pg_temp.knowledge_nodes(graph_snapshot_revision_id,node_id,"
        "node_type,label,answer_bearing) SELECT :snapshot,'knode_'||i,"
        "'CONCEPT','synthetic bounded population',false FROM generate_series(1,545) i",
        "INSERT INTO pg_temp.knowledge_node_source_pointers(pointer_id,"
        "graph_snapshot_revision_id,analysis_run_id,node_id,anchor_id,source_class,"
        "source_revision_id,source_artifact_id,artifact_revision_id,source_sha256,member_path) "
        "SELECT i,:snapshot,'analysisrun_'||lpad(i::text,32,'0'),'knode_'||i,'anchor_'||i,"
        "'PAST_EXAM','itemrev_'||lpad(i::text,32,'0'),'artifact_'||lpad(i::text,32,'0'),"
        "'rev_'||lpad(i::text,32,'0'),'sha256:'||repeat('a',64),'item-content.json' "
        "FROM generate_series(1,545) i",
        "INSERT INTO pg_temp.assessment_item_occurrence_references(graph_snapshot_revision_id,"
        "placement_node_id,analysis_run_id,item_id,item_revision_id) "
        "SELECT :snapshot,'placement_'||i,'analysisrun_'||lpad(i::text,32,'0'),"
        "'item_'||lpad(i::text,32,'0'),'itemrev_'||lpad(i::text,32,'0') "
        "FROM generate_series(1,545) i",
        "INSERT INTO pg_temp.legacy_item_extraction_acceptances(acceptance_id,"
        "extraction_result_id,state,coverage_state,result_sha256,acceptance_sha256,"
        "acceptance_artifact_id,acceptance_artifact_revision_id,acceptance_artifact_member_path,"
        "acceptance_artifact_schema_ref,acceptance_artifact_media_type,acceptance_artifact_sha256,"
        "result_artifact_id,result_artifact_revision_id,result_artifact_member_path,"
        "result_artifact_schema_ref,result_artifact_media_type,result_artifact_sha256) "
        "SELECT 'itemacceptance_'||lpad(i::text,32,'0'),"
        "'itemextractresult_'||lpad(i::text,32,'0'),'ACCEPTED','COMPLETE',"
        "'sha256:'||repeat('a',64),'sha256:'||repeat('a',64),"
        "'artifact_'||lpad((2000+i)::text,32,'0'),'rev_'||lpad((2000+i)::text,32,'0'),"
        "'acceptance.json','synthetic-acceptance/1','application/json','sha256:'||repeat('a',64),"
        "'artifact_'||lpad((3000+i)::text,32,'0'),'rev_'||lpad((3000+i)::text,32,'0'),"
        "'result.json','synthetic-result/1','application/json','sha256:'||repeat('a',64) "
        "FROM generate_series(1,545) i",
        "UPDATE pg_temp.legacy_item_extraction_batch_work_units SET "
        "extraction_batch_id='legacybatch_1',assessment_source_bundle_id='sourcebundle_1',"
        "assessment_source_bundle_revision_id='sourcebundlerev_1',"
        "bundle_manifest_sha256='sha256:'||repeat('a',64),"
        "request_sha256='sha256:'||repeat('a',64),"
        "result_sha256='sha256:'||repeat('a',64),acceptance_sha256='sha256:'||repeat('a',64)",
        "INSERT INTO pg_temp.legacy_item_extraction_batches(extraction_batch_id,manifest_sha256,"
        "manifest_artifact_id,manifest_artifact_revision_id,manifest_artifact_member_path,"
        "manifest_artifact_schema_ref,manifest_artifact_media_type,manifest_artifact_sha256) "
        "VALUES ('legacybatch_1','sha256:'||repeat('a',64),"
        "'artifact_'||lpad('4001',32,'0'),'rev_'||lpad('4001',32,'0'),"
        "'batch.json','synthetic-batch/1','application/json','sha256:'||repeat('a',64))",
        "INSERT INTO pg_temp.assessment_source_bundle_revisions("
        "assessment_source_bundle_revision_id,assessment_source_bundle_id,state,"
        "bundle_manifest_sha256) VALUES ('sourcebundlerev_1','sourcebundle_1','REVIEWED',"
        "'sha256:'||repeat('a',64))",
        "INSERT INTO pg_temp.assessment_layout_observations(assessment_layout_observation_id,"
        "assessment_source_bundle_revision_id,artifact_id,artifact_revision_id,"
        "artifact_member_path,artifact_schema_ref,artifact_media_type,artifact_sha256) "
        "VALUES ('layout_1','sourcebundlerev_1',"
        "'artifact_'||lpad('4002',32,'0'),'rev_'||lpad('4002',32,'0'),"
        "'layout.json','synthetic-layout/1','application/json','sha256:'||repeat('a',64))",
        "INSERT INTO pg_temp.artifacts(logical_artifact_id,job_id,artifact_type,approved) "
        "SELECT 'artifact_'||lpad(i::text,32,'0'),'job_'||lpad(i::text,32,'0'),"
        "'synthetic-population',true FROM (SELECT generate_series(1,545) i UNION ALL "
        "SELECT generate_series(1001,1545) UNION ALL SELECT generate_series(2001,2545) "
        "UNION ALL SELECT generate_series(3001,3545) "
        "UNION ALL SELECT generate_series(4001,4007)) n",
        "INSERT INTO pg_temp.artifact_revisions(revision_id,logical_artifact_id,job_id,approved,"
        "content_hash,manifest_hash,content_bytes,nas_path,manifest,result) "
        "SELECT 'rev_'||right(logical_artifact_id,32),logical_artifact_id,job_id,true,"
        "'sha256:'||repeat('a',64),'sha256:'||repeat('a',64),1,"
        "'/synthetic/not-materialized',jsonb_build_object('files','[]'::jsonb),"
        "jsonb_build_object('synthetic',true) FROM pg_temp.artifacts",
        "INSERT INTO pg_temp.jobs(job_id,status,task_type,logical_artifact_id,revision_id) "
        "SELECT job_id,'SUCCEEDED',artifact_type,logical_artifact_id,"
        "'rev_'||right(logical_artifact_id,32) FROM pg_temp.artifacts",
    )
    for statement in statements:
        session.execute(
            text(statement),
            {"snapshot": snapshot, "graph": occurrence_scope().graph_snapshot.graph_id},
        )
    for table in (*TABLES, *tables):
        session.execute(text(f"ANALYZE pg_temp.{table}"))
    return session


def observe_population(session, *, maximum=1024, artifact_identities=()):
    from eom_catalog_service.inference_transfer_population_read_set import (
        observe_inference_transfer_population,
    )

    return observe_inference_transfer_population(
        session,
        occurrence_scope(maximum=maximum),
        artifact_identities=artifact_identities,
        layout_observation_ids=("layout_1",),
    )


@pytest.mark.parametrize(
    "statement",
    (
        "UPDATE pg_temp.items SET lifecycle_state='RETIRED' "
        "WHERE item_id='item_'||lpad('545',32,'0')",
        "UPDATE pg_temp.item_revisions SET "
        "metadata_json=metadata_json||jsonb_build_object('item_number',999) "
        "WHERE item_revision_id='itemrev_'||lpad('545',32,'0')",
        "UPDATE pg_temp.item_components SET required=false "
        "WHERE item_revision_id='itemrev_'||lpad('545',32,'0')",
        "UPDATE pg_temp.knowledge_snapshot_analyses SET source_sha256='sha256:'||repeat('b',64) "
        "WHERE analysis_run_id='analysisrun_'||lpad('545',32,'0')",
        "UPDATE pg_temp.knowledge_node_source_pointers SET member_path='changed-unranked.png' "
        "WHERE pointer_id=545",
        "UPDATE pg_temp.knowledge_nodes SET label='changed unranked node' "
        "WHERE node_id='knode_545'",
        "UPDATE pg_temp.knowledge_analysis_runs SET canonical_request=canonical_request||"
        "jsonb_build_object('fresh_source_input',true) "
        "WHERE analysis_run_id='analysisrun_'||lpad('545',32,'0')",
        "UPDATE pg_temp.legacy_item_extraction_acceptances SET coverage_state='INCOMPLETE' "
        "WHERE acceptance_id='itemacceptance_'||lpad('545',32,'0')",
        "UPDATE pg_temp.legacy_item_extraction_decisions SET decision='REJECT' "
        "WHERE decision_id=545",
        "UPDATE pg_temp.legacy_item_extraction_batch_work_units SET receipt_artifact_sha256="
        "'sha256:'||repeat('b',64) WHERE work_unit_id='legacyworkunit_'||lpad('545',32,'0')",
        "UPDATE pg_temp.legacy_item_extraction_batches SET manifest_artifact_sha256="
        "'sha256:'||repeat('b',64) WHERE extraction_batch_id='legacybatch_1'",
        "UPDATE pg_temp.assessment_source_bundle_revisions SET state='RETIRED' "
        "WHERE assessment_source_bundle_revision_id='sourcebundlerev_1'",
        "UPDATE pg_temp.assessment_layout_observations SET artifact_sha256="
        "'sha256:'||repeat('b',64) WHERE assessment_layout_observation_id='layout_1'",
        "UPDATE pg_temp.artifacts SET approved=false "
        "WHERE logical_artifact_id='artifact_'||lpad('545',32,'0')",
        "UPDATE pg_temp.artifact_revisions SET result=jsonb_build_object('changed',true) "
        "WHERE revision_id='rev_'||lpad('545',32,'0')",
        "UPDATE pg_temp.jobs SET status='FAILED' WHERE job_id='job_'||lpad('545',32,'0')",
        "DELETE FROM pg_temp.assessment_item_occurrence_references "
        "WHERE analysis_run_id='analysisrun_'||lpad('545',32,'0')",
    ),
)
def test_real_postgres_population_observation_covers_every_current_dependency_group(
    population_observation_database, statement
):
    session = population_observation_database
    initial = observe_population(session)
    session.execute(text(statement))
    assert observe_population(session) != initial


def test_real_postgres_population_observation_reads_scalars_past_a_stale_orm_identity(
    population_observation_database,
):
    from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord

    session = population_observation_database
    identity = "analysisrun_" + "545".zfill(32)
    retained = session.get(KnowledgeAnalysisRunRecord, identity)
    assert retained.canonical_request.get("fresh_source_input") is None
    initial = observe_population(session)
    session.execute(
        text(
            "UPDATE pg_temp.knowledge_analysis_runs SET canonical_request=canonical_request||"
            "jsonb_build_object('fresh_source_input',true) WHERE analysis_run_id=:identity"
        ),
        {"identity": identity},
    )
    assert retained.canonical_request.get("fresh_source_input") is None
    assert observe_population(session) != initial
    assert session.get(KnowledgeAnalysisRunRecord, identity) is retained


def test_real_postgres_population_observation_reads_snapshot_past_a_stale_orm_identity(
    population_observation_database,
):
    from eom_catalog_service.knowledge_graph_models import KnowledgeGraphSnapshotRecord

    session = population_observation_database
    identity = occurrence_scope().graph_snapshot.graph_snapshot_revision_id
    retained = session.get(KnowledgeGraphSnapshotRecord, identity)
    initial_graph_id = retained.graph_id
    initial = observe_population(session)
    session.execute(
        text(
            "UPDATE pg_temp.knowledge_graph_snapshots SET graph_id=:different "
            "WHERE graph_snapshot_revision_id=:identity"
        ),
        {"different": "graph_" + "f" * 32, "identity": identity},
    )
    assert retained.graph_id == initial_graph_id
    assert observe_population(session) != initial
    assert session.get(KnowledgeGraphSnapshotRecord, identity) is retained


def test_real_postgres_population_observation_detects_missing_to_accepted_report_and_withdrawal(
    population_observation_database,
):
    session = population_observation_database
    missing = observe_population(session)
    session.execute(
        text(
            "INSERT INTO pg_temp.knowledge_analysis_runs(analysis_run_id,state,"
            "predecessor_analysis_run_id,canonical_request,accepted_result_artifact_id,"
            "accepted_result_artifact_revision_id,proposal_artifact_id,"
            "proposal_artifact_revision_id) "
            "VALUES ('analysisrun_'||lpad('9999',32,'0'),'ACCEPTED',"
            "'analysisrun_'||lpad('545',32,'0'),"
            '\'{"schema_version":"knowledge-analysis-request/10.0"}\'::jsonb,'
            "'artifact_'||lpad('4004',32,'0'),'rev_'||lpad('4004',32,'0'),"
            "'artifact_'||lpad('4005',32,'0'),'rev_'||lpad('4005',32,'0'))"
        )
    )
    accepted = observe_population(session)
    assert accepted != missing
    session.execute(
        text(
            "UPDATE pg_temp.knowledge_analysis_runs SET state='REJECTED' "
            "WHERE analysis_run_id='analysisrun_'||lpad('9999',32,'0')"
        )
    )
    assert observe_population(session) != accepted


def test_real_postgres_population_observation_closes_noncanonical_graph_and_prefetched_artifacts(
    population_observation_database,
):
    session = population_observation_database
    session.execute(
        text(
            "UPDATE pg_temp.knowledge_node_source_pointers SET "
            "source_artifact_id='artifact_'||lpad('4006',32,'0'),"
            "artifact_revision_id='rev_'||lpad('4006',32,'0'),member_path='pages/pinned.png' "
            "WHERE pointer_id=545"
        )
    )
    # A page PNG can be an admitted Graph pointer distinct from the Item JSON.
    # Page source/PDF provenance can instead arrive in the root's exact prefetch set.
    identities = (("artifact_" + "4007".zfill(32), "rev_" + "4007".zfill(32)),)
    initial = observe_population(session, artifact_identities=identities)
    session.execute(
        text(
            "UPDATE pg_temp.artifacts SET approved=false "
            "WHERE logical_artifact_id='artifact_'||lpad('4006',32,'0')"
        )
    )
    graph_withdrawn = observe_population(session, artifact_identities=identities)
    assert graph_withdrawn != initial
    session.execute(
        text("UPDATE pg_temp.jobs SET status='FAILED' WHERE job_id='job_'||lpad('4007',32,'0')")
    )
    assert observe_population(session, artifact_identities=identities) != graph_withdrawn


def test_real_postgres_population_observation_closes_other_media_compatibility_component(
    population_observation_database,
):
    from eom_catalog_contracts import LEGACY_ITEM_MEDIA_COMPATIBILITY_SCHEMA_REF

    session = population_observation_database
    session.execute(
        text(
            "INSERT INTO pg_temp.item_components(item_component_id,item_revision_id,component_type,"
            "ordinal,schema_ref,media_type,artifact_id,artifact_revision_id,sha256,logical_name,"
            "required,metadata_json) VALUES ('compatibility-fixture',"
            "'itemrev_'||lpad('545',32,'0'),'OTHER',0,:schema,'application/json',"
            "'artifact_'||lpad('4003',32,'0'),'rev_'||lpad('4003',32,'0'),"
            "'sha256:'||repeat('a',64),'compatibility.json',true,'{}'::jsonb)"
        ),
        {"schema": LEGACY_ITEM_MEDIA_COMPATIBILITY_SCHEMA_REF},
    )
    initial = observe_population(session)
    session.execute(
        text(
            "UPDATE pg_temp.artifact_revisions SET manifest="
            "jsonb_build_object('changed_member',true) "
            "WHERE revision_id='rev_'||lpad('4003',32,'0')"
        )
    )
    assert observe_population(session) != initial


def test_real_postgres_population_observation_order_and_72800_pointer_scale(
    population_observation_database, record_property
):
    session = population_observation_database
    initial = observe_population(session)
    session.execute(
        text(
            "INSERT INTO pg_temp.knowledge_node_source_pointers("
            "pointer_id,graph_snapshot_revision_id,node_id,analysis_run_id,source_revision_id,"
            "source_class,source_artifact_id,artifact_revision_id,source_sha256,member_path,"
            "anchor_id,excerpt_sha256) SELECT "
            "545+g.i,p.graph_snapshot_revision_id,p.node_id,p.analysis_run_id,p.source_revision_id,"
            "p.source_class,p.source_artifact_id,p.artifact_revision_id,p.source_sha256,"
            "p.member_path,'duplicate_'||g.i,p.excerpt_sha256 "
            "FROM generate_series(1,72800) g(i) JOIN pg_temp.knowledge_node_source_pointers p "
            "ON p.pointer_id=(g.i-1)%545+1"
        )
    )
    session.execute(text("ANALYZE pg_temp.knowledge_node_source_pointers"))
    statements = []
    execute = session.execute

    def observed(statement, *args, **kwargs):
        statements.append(statement)
        return execute(statement, *args, **kwargs)

    session.execute = observed
    started = perf_counter()
    try:
        first = observe_population(session)
        first_query_count = len(statements)
        second = observe_population(session)
    finally:
        session.execute = execute
    elapsed = perf_counter() - started
    assert first == second and first != initial
    assert len(statements) == 2 * first_query_count
    assert first_query_count <= 20  # fixed dependency batches, not545 per-source reads
    groups = {group.group: group for group in first.groups}
    assert groups["membership"].row_count == 545
    assert groups["graph_pointers"].row_count == 73345
    # A fresh executor order cannot change an ordered primitive observation.
    session.execute(text("SET LOCAL enable_seqscan=off"))
    assert observe_population(session) == first
    record_property("population_observation_545_sources_73345_pointers_seconds", elapsed)
    record_property("population_observation_queries_per_capture", first_query_count)
    assert elapsed < 20  # bounded fixture only, not a production latency promise
