"""Real SQL seed selection in isolated SQLite; this is not source authorization."""

from types import SimpleNamespace

import pytest
from eom_catalog_service import knowledge_retrieval_service as retrieval
from eom_catalog_service.knowledge_graph_models import KnowledgeNodeTermRecord
from sqlalchemy import Column, Index, Integer, MetaData, String, Table, create_engine, func, select
from sqlalchemy.orm import Session


class SeedSelectionObserved(Exception):
    pass


@pytest.fixture
def seed_database():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata = MetaData()
    Table(
        "knowledge_nodes",
        metadata,
        Column("graph_snapshot_revision_id", String),
        Column("node_id", String),
        Column("stable_key", String),
    )
    terms = Table(
        "knowledge_node_terms",
        metadata,
        Column("graph_snapshot_revision_id", String),
        Column("node_id", String),
        Column("term", String),
    )
    pointers = Table(
        "knowledge_node_source_pointers",
        metadata,
        Column("pointer_id", Integer, primary_key=True),
        Column("graph_snapshot_revision_id", String),
        Column("node_id", String),
        Column("source_class", String),
    )
    Index("seed_term_lookup", terms.c.graph_snapshot_revision_id, terms.c.term)
    Index("source_identity_prefix", pointers.c.graph_snapshot_revision_id, pointers.c.node_id)
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            terms.insert(),
            [
                {
                    "graph_snapshot_revision_id": "pinned",
                    "node_id": f"a{index:04d}",
                    "term": "match",
                }
                for index in range(1000)
            ]
            + [{"graph_snapshot_revision_id": "pinned", "node_id": "z_textbook", "term": "match"}],
        )
        connection.execute(
            pointers.insert(),
            [
                {
                    "graph_snapshot_revision_id": "pinned",
                    "node_id": f"a{index:04d}",
                    "source_class": "APPROVED_ITEM",
                }
                for index in range(1000)
            ]
            + [
                {
                    "graph_snapshot_revision_id": "pinned",
                    "node_id": "z_textbook",
                    "source_class": "TEXTBOOK",
                },
                {
                    "graph_snapshot_revision_id": "pinned",
                    "node_id": "z_textbook",
                    "source_class": "TEXTBOOK",
                },
                {
                    "graph_snapshot_revision_id": "another",
                    "node_id": "a0000",
                    "source_class": "TEXTBOOK",
                },
            ],
        )
    yield engine
    engine.dispose()


@pytest.mark.parametrize("source_classes", [("TEXTBOOK",), ("APPROVED_ITEM",), ("CURRICULUM",)])
def test_out_of_scope_nodes_cannot_fill_lexical_seed_budget(
    seed_database, monkeypatch, source_classes
):
    observed = []

    def ranked(rows, *, limit):
        observed.append((rows, limit))
        raise SeedSelectionObserved

    monkeypatch.setattr(retrieval, "_rank_lexical_seed_rows", ranked)
    command = SimpleNamespace(
        graph_snapshot_revision_id="pinned",
        target_item_revision_id=None,
        curriculum_scope=None,
        topic_keys=("topic.match",),
        source_classes=source_classes,
        evidence_budget=SimpleNamespace(max_graph_nodes=1),
    )
    service = object.__new__(retrieval.KnowledgeRetrievalApplicationService)
    with Session(seed_database) as session:
        if source_classes == ("TEXTBOOK",):
            # Reproduce the old unscoped SQL: both finite-budget rows are unrelated Items.
            old = tuple(
                session.execute(
                    select(
                        KnowledgeNodeTermRecord.node_id,
                        func.count().over(partition_by=KnowledgeNodeTermRecord.term),
                    )
                    .where(
                        KnowledgeNodeTermRecord.graph_snapshot_revision_id == "pinned",
                        KnowledgeNodeTermRecord.term == "match",
                    )
                    .order_by(KnowledgeNodeTermRecord.node_id)
                    .limit(2)
                )
            )
            assert old == (("a0000", 1001), ("a0001", 1001))
        with pytest.raises(SeedSelectionObserved):
            service._candidates(session, command, None)
    rows, limit = observed[0]
    assert limit == 1
    if source_classes == ("TEXTBOOK",):
        # Two pointers do not double the window frequency; another Graph cannot qualify a0000.
        assert rows == (("match", "z_textbook", 1),)
    elif source_classes == ("APPROVED_ITEM",):
        assert rows == (("match", "a0000", 1000), ("match", "a0001", 1000))
    else:
        assert rows == ()
