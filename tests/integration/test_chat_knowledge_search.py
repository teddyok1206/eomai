"""Real PostgreSQL metadata reads/plans in a guarded disposable DB's temporary tables.

No production/corpus/model/NAS writes. Shadow tables test SQL/read projections,
not Catalog persistence constraints, which keep their existing acceptance suite.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from eom_api.errors import ApiError
from eom_api.services.chat_knowledge_query_adapter import (
    ChatKnowledgeQueryAdapter,
    candidate_statement,
)
from eom_api.services.query_adapter import QueryAdapter
from eom_api_contracts.chat_knowledge import ChatKnowledgeRequest
from eom_catalog_contracts import INTEGRATED_SCIENCE_TEXTBOOK_CORPUS_KEY
from eom_orchestrator.database import build_engine
from sqlalchemy import event, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker

from scripts.api.testdb_guard import TestDatabaseManifest as DisposableManifest
from scripts.api.testdb_guard import validate_state_directory

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
HASH = "sha256:" + "a" * 64
CONTENT_HASH = "sha256:" + "b" * 64
SNAPSHOT = {"graph_snapshot_revision_id": "graphrev_" + "1" * 32, "snapshot_sha256": HASH}
TABLES = (
    "items",
    "item_revisions",
    "item_events",
    "item_components",
    "item_origin_profiles",
    "knowledge_corpora",
    "knowledge_graph_snapshots",
    "knowledge_snapshot_analyses",
    "assessment_item_occurrence_references",
    "knowledge_node_terms",
    "knowledge_node_source_pointers",
)
INDEXES = {
    "ix_items_keyset": ("items", "created_at,item_id"),
    "ix_chat_item_pk": ("items", "item_id"),
    "ix_chat_revision_pk": ("item_revisions", "item_revision_id"),
    "ix_knowledge_node_term_lookup": (
        "knowledge_node_terms",
        "graph_snapshot_revision_id,term,node_id",
    ),
    "ix_knowledge_node_source_class": (
        "knowledge_node_source_pointers",
        "graph_snapshot_revision_id,source_class,source_revision_id",
    ),
    "ix_assessment_item_ref_exam_lookup": (
        "assessment_item_occurrence_references",
        "graph_snapshot_revision_id,administration_year,target_school_level,target_grade,administration_month,subject_key,item_number",
    ),
    "ix_assessment_item_ref_item_revision": (
        "assessment_item_occurrence_references",
        "graph_snapshot_revision_id,item_revision_id",
    ),
    "ix_origin_revision": ("item_origin_profiles", "item_revision_id"),
    "ix_snapshot_source_revision": (
        "knowledge_snapshot_analyses",
        "source_kind,source_revision_id",
    ),
    "ix_component_revision": ("item_components", "item_revision_id"),
}


@pytest.fixture
def search_db():
    if os.environ.get("EOM_RUN_API_INTEGRATION") != "1":
        pytest.skip("use guarded testdb_run.sh chat-knowledge-tests; never production")
    state = validate_state_directory(Path(os.environ["EOM_CHAT_KNOWLEDGE_TEST_STATE"]))
    manifest = DisposableManifest.load(state / "manifest.json")
    parsed = urlsplit(os.environ["EOM_DATABASE_URL"])
    assert parsed.username == manifest.owner_role
    assert unquote(parsed.path.removeprefix("/")) == manifest.database
    engine = build_engine(os.environ["EOM_DATABASE_URL"])
    con = engine.connect().execution_options(isolation_level="REPEATABLE READ")
    try:
        assert con.scalar(text("SELECT current_database()")) == manifest.database
        for table in TABLES:
            # Fixed identifiers only. These writes target pg_temp, not app tables.
            con.exec_driver_sql(
                f"CREATE TEMP TABLE {table} AS SELECT * FROM app.{table} WITH NO DATA"
            )
        for name, (table, columns) in INDEXES.items():
            unique = "UNIQUE " if name in {"ix_chat_item_pk", "ix_chat_revision_pk"} else ""
            con.exec_driver_sql(f"CREATE {unique}INDEX {name} ON pg_temp.{table}({columns})")
        con.execute(
            text("""
            INSERT INTO pg_temp.items(item_id,current_revision_id,lifecycle_state,
                created_at,created_by,lock_version)
            SELECT 'item_'||md5(i::text),'itemrev_'||md5(i::text),'ACTIVE',
                TIMESTAMPTZ '2026-10-08 00:00:00+00' + i * INTERVAL '1 second','fixture',1
            FROM generate_series(1,10000) i
        """)
        )
        con.execute(
            text("""
            INSERT INTO pg_temp.item_revisions(item_revision_id,item_id,
                revision_number,revision_state,
                content_pack_release_id,workflow_id,workflow_definition_version,manifest_artifact_id,
                manifest_artifact_revision_id,manifest_sha256,item_type_key,lock_version,created_at)
            SELECT current_revision_id,item_id,1,'APPROVED','packrel_'||md5(item_id),
                'workflow_'||md5(item_id),'1.10.0','artifact_'||md5(item_id),'rev_'||md5(item_id),
                :hash,'integrated-science',1,created_at FROM pg_temp.items
        """),
            {"hash": HASH},
        )
        con.execute(
            text("""
            INSERT INTO pg_temp.item_origin_profiles(item_origin_profile_id,
                item_revision_id,item_id,source_domain,item_manifest_sha256)
            SELECT 'origin_'||md5(item_id),item_revision_id,item_id,'INTERNAL_EOM',
                manifest_sha256 FROM pg_temp.item_revisions
        """)
        )
        con.execute(
            text("""
            INSERT INTO pg_temp.item_components(item_component_id,item_revision_id,
                artifact_id,artifact_revision_id,sha256)
            SELECT 'itemcomponent_'||md5(item_id),item_revision_id,
                'artifact_'||md5(item_revision_id),
                'rev_'||md5(item_revision_id),:hash FROM pg_temp.item_revisions
        """),
            {"hash": CONTENT_HASH},
        )
        con.execute(
            text("""
            INSERT INTO pg_temp.knowledge_corpora(corpus_id,corpus_key,graph_id,
                current_graph_snapshot_revision_id,lifecycle_state)
            VALUES ('corpus_fixture',:key,'graph_fixture',:snapshot,'ACTIVE')
        """),
            {
                "key": INTEGRATED_SCIENCE_TEXTBOOK_CORPUS_KEY,
                "snapshot": SNAPSHOT["graph_snapshot_revision_id"],
            },
        )
        con.execute(
            text("""
            INSERT INTO pg_temp.knowledge_graph_snapshots(graph_snapshot_revision_id,
                graph_id,state,ontology_version,snapshot_sha256)
            VALUES (:snapshot,'graph_fixture','PUBLISHED','education-knowledge-graph/1.1',:hash)
        """),
            {"snapshot": SNAPSHOT["graph_snapshot_revision_id"], "hash": HASH},
        )
        con.execute(
            text("""
            INSERT INTO pg_temp.knowledge_snapshot_analyses(snapshot_analysis_id,
                graph_snapshot_revision_id,analysis_run_id,source_kind,
                source_revision_id,source_artifact_id,source_artifact_revision_id,source_sha256)
            SELECT row_number() OVER (),:snapshot,'analysis_'||md5(i.item_id),
                'APPROVED_ITEM_REVISION',i.current_revision_id,
                c.artifact_id,c.artifact_revision_id,c.sha256 FROM pg_temp.items i
            JOIN pg_temp.item_components c ON c.item_revision_id=i.current_revision_id
            ORDER BY i.created_at LIMIT 100
        """),
            {"snapshot": SNAPSHOT["graph_snapshot_revision_id"]},
        )
        con.execute(
            text("""
            INSERT INTO pg_temp.knowledge_node_terms(graph_snapshot_revision_id,node_id,term)
            VALUES (:snapshot,'node_fixture','전자기')
        """),
            {"snapshot": SNAPSHOT["graph_snapshot_revision_id"]},
        )
        con.execute(
            text("""
            INSERT INTO pg_temp.knowledge_node_terms(graph_snapshot_revision_id,node_id,term)
            SELECT :snapshot,'node_'||md5(i::text),'term'||md5(i::text)
            FROM generate_series(1,20000) i
        """),
            {"snapshot": SNAPSHOT["graph_snapshot_revision_id"]},
        )
        con.execute(
            text("""
            INSERT INTO pg_temp.knowledge_node_source_pointers(pointer_id,
                graph_snapshot_revision_id,node_id,source_revision_id,source_class)
            SELECT row_number() OVER (),graph_snapshot_revision_id,'node_fixture',
                source_revision_id,'APPROVED_ITEM'
            FROM pg_temp.knowledge_snapshot_analyses
        """)
        )
        for table in TABLES:
            con.exec_driver_sql(f"ANALYZE pg_temp.{table}")
        con.commit()
        reader = ChatKnowledgeQueryAdapter(
            engine, QueryAdapter(engine, b"fixture-key").item_revision_views
        )
        reader.sessions = sessionmaker(bind=con, expire_on_commit=False)
        yield reader, con
    finally:
        con.close()
        engine.dispose()  # pool must not retain shadow tables


def request(query, **kwargs):
    return ChatKnowledgeRequest(query=query, **kwargs)


def reference(card):
    return {key: getattr(card, key) for key in ("item_id", "item_revision_id", "manifest_sha256")}


def test_recent_unindexed_items_and_bounded_batch_queries(search_db):
    reader, con = search_db
    calls = []
    event.listen(con, "before_cursor_execute", lambda *args: calls.append(args[2]))
    one = reader.search(request({"kind": "RECENT"}, limit=1))
    count = len(calls)
    calls.clear()
    twenty = reader.search(request({"kind": "RECENT"}, limit=20))
    assert len(calls) == count
    assert one.truncated and twenty.truncated
    assert len(twenty.values) == 20 and twenty.model_calls == 0
    assert all(card.graph_membership == "NOT_INDEXED" for card in twenty.values)
    assert all(card.source_kind == "GENERATED" for card in twenty.values)
    assert one.values[0] == twenty.values[0]


def test_topic_exact_snapshot_and_component_not_manifest_hash(search_db):
    reader, _ = search_db
    answer = reader.search(request({"kind": "TOPIC", "terms": ["전자기"]}, snapshot=SNAPSHOT))
    assert len(answer.values) == 20 and answer.truncated
    assert answer.snapshot.model_dump(mode="json") == SNAPSHOT
    assert all(card.graph_membership == "INDEXED" for card in answer.values)
    assert HASH != CONTENT_HASH
    assert reader.search(request({"kind": "TOPIC", "terms": ["없는개념"]})).values == ()


@pytest.mark.parametrize(
    "pin,code",
    [
        (SNAPSHOT | {"snapshot_sha256": CONTENT_HASH}, "CHAT_KNOWLEDGE_HASH_MISMATCH"),
        (
            SNAPSHOT | {"graph_snapshot_revision_id": "graphrev_" + "f" * 32},
            "CHAT_KNOWLEDGE_SNAPSHOT_UNAVAILABLE",
        ),
    ],
)
def test_snapshot_never_falls_back_to_current(search_db, pin, code):
    reader, _ = search_db
    with pytest.raises(ApiError) as failure:
        reader.search(request({"kind": "RECENT"}, snapshot=pin))
    assert failure.value.error_code == code


def test_exact_hash_missing_and_item_identity_checks(search_db):
    reader, _ = search_db
    card = reader.search(request({"kind": "RECENT"}, limit=1)).values[0]
    ref = reference(card)
    assert reader.search(request({"kind": "EXACT", "references": [ref]})).values == (card,)
    for changed, code in (
        (ref | {"manifest_sha256": CONTENT_HASH}, "CHAT_KNOWLEDGE_HASH_MISMATCH"),
        (ref | {"item_id": "item_" + "f" * 32}, "CHAT_KNOWLEDGE_ITEM_UNAVAILABLE"),
        (ref | {"item_revision_id": "itemrev_" + "f" * 32}, "CHAT_KNOWLEDGE_ITEM_UNAVAILABLE"),
    ):
        with pytest.raises(ApiError) as failure:
            reader.search(request({"kind": "EXACT", "references": [changed]}))
        assert failure.value.error_code == code


def test_pending_and_deleted_projection(search_db):
    reader, con = search_db
    card = reader.search(request({"kind": "RECENT"}, limit=1)).values[0]
    con.execute(
        text(
            "UPDATE pg_temp.item_revisions SET revision_state='IN_REVIEW',"
            "workflow_definition_version='1.16.0' WHERE item_revision_id=:id"
        ),
        {"id": card.item_revision_id},
    )
    con.commit()
    pending = reader.search(request({"kind": "RECENT"}, limit=1)).values[0]
    assert pending.approval.status == "PENDING" and pending.approval.human_review_required
    con.execute(
        text("UPDATE pg_temp.items SET lifecycle_state='DELETED_SOFT' WHERE item_id=:id"),
        {"id": card.item_id},
    )
    con.commit()
    with pytest.raises(ApiError, match="CHAT_KNOWLEDGE_ITEM_UNAVAILABLE"):
        reader.search(request({"kind": "EXACT", "references": [reference(card)]}))
    assert reader.search(request({"kind": "RECENT"}, limit=1)).values[0].item_id != card.item_id


def test_invalid_graph_component_fails_explicitly(search_db):
    reader, con = search_db
    con.execute(
        text("UPDATE pg_temp.knowledge_snapshot_analyses SET source_sha256=:hash"), {"hash": HASH}
    )
    con.commit()
    with pytest.raises(ApiError, match="CHAT_KNOWLEDGE_POINTER_INVALID"):
        reader.search(request({"kind": "TOPIC", "terms": ["전자기"]}))


def test_dangling_topic_item_pointer_is_not_reinterpreted_as_no_match(search_db):
    reader, con = search_db
    con.execute(
        text("UPDATE pg_temp.knowledge_node_source_pointers SET source_revision_id=:revision"),
        {"revision": "itemrev_" + "f" * 32},
    )
    con.commit()
    with pytest.raises(ApiError, match="CHAT_KNOWLEDGE_POINTER_INVALID"):
        reader.search(request({"kind": "TOPIC", "terms": ["전자기"]}))


def test_registry_survives_no_graph_without_faking_grounding(search_db):
    reader, con = search_db
    con.execute(
        text("UPDATE pg_temp.knowledge_corpora SET current_graph_snapshot_revision_id=NULL")
    )
    con.commit()
    answer = reader.search(request({"kind": "RECENT"}))
    assert answer.snapshot is None
    assert all(card.graph_membership == "UNAVAILABLE" for card in answer.values)
    with pytest.raises(ApiError, match="CHAT_KNOWLEDGE_GRAPH_UNAVAILABLE"):
        reader.search(request({"kind": "TOPIC", "terms": ["전자기"]}))


def test_exact_exam_keeps_ambiguous_occurrences_and_rechecks_pinned_snapshot(search_db):
    reader, con = search_db
    revision_id, item_id = con.execute(
        text(
            "SELECT source_revision_id,r.item_id FROM pg_temp.knowledge_snapshot_analyses a "
            "JOIN pg_temp.item_revisions r ON r.item_revision_id=a.source_revision_id LIMIT 1"
        )
    ).one()
    for suffix in ("4", "5"):
        con.execute(
            text("""
            INSERT INTO pg_temp.assessment_item_occurrence_references(
                graph_snapshot_revision_id,placement_node_id,item_id,item_revision_id,
                assessment_occurrence_revision_id,occurrence_display_label,
                administration_year,administration_month,target_school_level,
                target_grade,subject_key,item_number)
            VALUES (:snapshot,:node,:item,:revision,:occurrence,:label,
                2025,6,'HIGH_SCHOOL',1,'integrated-science',17)
        """),
            {
                "snapshot": SNAPSHOT["graph_snapshot_revision_id"],
                "node": "placement_" + suffix,
                "item": item_id,
                "revision": revision_id,
                "occurrence": "occurrev_" + suffix * 32,
                "label": "공식 시험 " + suffix,
            },
        )
    con.commit()
    query = {
        "kind": "EXAM",
        "administration_year": 2025,
        "administration_month": 6,
        "target_school_level": "HIGH_SCHOOL",
        "target_grade": 1,
        "subject_key": "integrated-science",
        "item_number": 17,
    }
    answer = reader.search(request(query, snapshot=SNAPSHOT))
    assert len(answer.values) == 2  # no arbitrary selection of one official exam
    assert {card.exam.assessment_occurrence_revision_id for card in answer.values} == {
        "occurrev_" + suffix * 32 for suffix in ("4", "5")
    }
    assert all(
        card.source_kind == "PAST_EXAM" and "17번" in card.display_name for card in answer.values
    )
    assert reader.search(request(query | {"item_number": 18})).values == ()
    con.execute(
        text("UPDATE pg_temp.knowledge_corpora SET current_graph_snapshot_revision_id=NULL")
    )
    con.commit()
    assert reader.search(request(query, snapshot=SNAPSHOT)) == answer


def test_actual_reader_transaction_is_repeatable_read_and_read_only(search_db):
    reader, _ = search_db
    original = reader.project_revisions
    settings = []

    def project(session, revisions):
        settings.append(
            session.execute(
                text(
                    "SELECT current_setting('transaction_read_only'),"
                    "current_setting('transaction_isolation')"
                )
            ).one()
        )
        return original(session, revisions)

    reader.project_revisions = project
    reader.search(request({"kind": "RECENT"}))
    assert settings == [("on", "repeatable read")]


def test_current_revision_pointing_to_another_item_fails_before_projection(search_db):
    reader, con = search_db
    cards = reader.search(request({"kind": "RECENT"}, limit=2)).values
    con.execute(
        text("UPDATE pg_temp.items SET current_revision_id=:revision WHERE item_id=:item"),
        {"revision": cards[1].item_revision_id, "item": cards[0].item_id},
    )
    con.commit()
    with pytest.raises(ApiError, match="CHAT_KNOWLEDGE_POINTER_INVALID"):
        reader.search(request({"kind": "RECENT"}))


@pytest.mark.parametrize(
    "query,index",
    [
        ({"kind": "RECENT"}, "ix_items_keyset"),
        ({"kind": "TOPIC", "terms": ["없는개념"]}, "ix_knowledge_node_term_lookup"),
    ],
)
def test_ten_thousand_item_real_query_plan_uses_indexes(search_db, query, index):
    _, con = search_db
    sql = str(
        candidate_statement(request(query), SNAPSHOT["graph_snapshot_revision_id"]).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    plan = con.exec_driver_sql("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql).scalar_one()
    assert index in json.dumps(plan)
    assert plan[0]["Plan"]["Actual Rows"] <= 21
