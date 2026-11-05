"""Map is bounded metadata exploration, never a parallel graph or model query."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts import validate_contract
from eom_catalog_contracts.knowledge_map import KnowledgeMapView
from eom_catalog_service.knowledge_graph_models import (
    KnowledgeGraphSnapshotRecord,
    KnowledgeNodeRecord,
)
from eom_catalog_service.knowledge_map_read import (
    KnowledgeMapReadError,
    KnowledgeMapReadService,
    neighborhood_edges,
    source_layer,
)
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

SNAPSHOT = "graphrev_" + "a" * 32
HASH = "sha256:" + "b" * 64
NODE = "knode_" + "c" * 32


def view_document():
    return dict(
        schema_version="knowledge-map-view/1.0",
        graph_snapshot_revision_id=SNAPSHOT,
        snapshot_sha256=HASH,
        nodes=[
            dict(
                node_id=NODE,
                node_type="CONCEPT",
                label="전자기 유도",
                layers=["PAST_EXAM", "TEXTBOOK"],
            )
        ],
        edges=[],
        sources=[],
        focus_node_id=NODE,
        selected_edge_id=None,
        truncated=False,
        total_nodes=1,
        total_edges=0,
    )


def test_map_contract_is_schema_first_mirrored_and_bounded():
    root = Path(__file__).resolve().parents[2]
    assert (root / "schemas/knowledge/knowledge-map-view-v1.schema.json").read_bytes() == (
        root
        / "packages/catalog_contracts/eom_catalog_contracts/resources/knowledge"
        / "knowledge-map-view-v1.schema.json"
    ).read_bytes()
    document = KnowledgeMapView.model_validate(view_document()).model_dump(mode="json")
    validate_contract("knowledge-map-view-v1", document)
    for mutate in (
        lambda value: value["nodes"].append(deepcopy(value["nodes"][0])),
        lambda value: value.update(focus_node_id="knode_" + "d" * 32),
        lambda value: value["nodes"][0].update(layers=["TEXTBOOK", "TEXTBOOK"]),
        lambda value: value.update(
            edges=[
                dict(
                    edge_id="kedge_" + "e" * 32,
                    from_node_id=NODE,
                    to_node_id="knode_" + "f" * 32,
                    edge_type="EXPLAINS",
                )
            ]
        ),
    ):
        invalid = deepcopy(document)
        mutate(invalid)
        with pytest.raises(ValidationError):
            KnowledgeMapView.model_validate(invalid)


@pytest.mark.parametrize(
    ("source", "domain", "workflow", "expected"),
    [
        ("TEXTBOOK", None, None, "TEXTBOOK"),
        ("PAST_EXAM", None, None, "PAST_EXAM"),
        ("APPROVED_ITEM", "INTERNAL_EOM", None, "AI"),
        ("APPROVED_ITEM", "EXTERNAL_INDIVIDUAL", None, "CREATIVE"),
        ("APPROVED_ITEM", None, "external-item-learning", "CREATIVE"),
        ("APPROVED_ITEM", None, "generic-item-development", "AI"),
        ("APPROVED_ITEM", None, "unknown", "UNKNOWN"),
    ],
)
def test_layers_do_not_confuse_creative_approval_with_ai(source, domain, workflow, expected):
    assert source_layer(source, domain, workflow) == expected


def test_adjacency_is_snapshot_scoped_stable_and_bounded():
    sql = str(
        neighborhood_edges(SNAPSHOT, {NODE}).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert SNAPSHOT in sql and NODE in sql
    assert "from_node_id IN" in sql and "to_node_id IN" in sql
    assert "ORDER BY knowledge_edges.edge_id" in sql and "LIMIT 241" in sql


def reader():
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    service = object.__new__(KnowledgeMapReadService)
    service.sessions = Mock(return_value=session)
    service.snapshots = Mock()
    snapshot = SimpleNamespace(snapshot_sha256=HASH, node_count=10, edge_count=20)
    session.get.side_effect = lambda model, key, **kw: (
        snapshot if model is KnowledgeGraphSnapshotRecord else None
    )
    return service, session


def test_expansion_requires_exact_graph_and_hash_before_query():
    service, session = reader()
    for pins in (
        dict(node_id=NODE),
        dict(graph_snapshot_revision_id=SNAPSHOT),
        dict(snapshot_sha256=HASH),
    ):
        with pytest.raises(KnowledgeMapReadError, match="PIN_REQUIRED"):
            service.read(**pins)
    session.execute.assert_not_called()
    with pytest.raises(KnowledgeMapReadError, match="STALE"):
        service.read(graph_snapshot_revision_id=SNAPSHOT, snapshot_sha256="sha256:" + "c" * 64)
    assert "READ ONLY" in str(session.execute.call_args_list[0].args[0])


def test_missing_node_does_not_substitute_latest_or_create_work():
    service, session = reader()
    with pytest.raises(KnowledgeMapReadError, match="NODE_NOT_FOUND"):
        service.read(graph_snapshot_revision_id=SNAPSHOT, snapshot_sha256=HASH, node_id=NODE)
    service.snapshots.resolve_snapshot_pointer.assert_called_once_with(session, SNAPSHOT)
    assert session.get.call_args_list[-1].args == (KnowledgeNodeRecord, (SNAPSHOT, NODE))
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_empty_search_remains_empty_no_full_graph_fallback():
    service, session = reader()
    session.scalars.return_value = ()
    value = service.read(
        graph_snapshot_revision_id=SNAPSHOT, snapshot_sha256=HASH, query="없는개념"
    )
    assert not value.nodes and not value.edges and value.total_nodes == 10
    assert session.scalars.call_count == 1
    session.add.assert_not_called()
    session.commit.assert_not_called()


@pytest.mark.parametrize(
    "unavailable_index,value",
    [(4, "FAILED"), (8, False), (9, False), (12, "RETIRED"), (13, "RETIRED")],
)
def test_source_revocation_is_explicit_without_erasing_its_pointer(unavailable_index, value):
    session = Mock()
    pointer = SimpleNamespace(
        source_revision_id="itemrev_" + "1" * 32,
        source_class="APPROVED_ITEM",
        analysis_run_id="analysisrun_" + "2" * 32,
        source_artifact_id="artifact_" + "3" * 32,
        artifact_revision_id="rev_" + "4" * 32,
        source_sha256=HASH,
        anchor_id="source-anchor",
        excerpt_sha256=HASH,
    )
    row = [
        pointer,
        "APPROVED_ITEM_REVISION",
        "rev_" + "5" * 32,
        HASH,
        "ACCEPTED",
        "rev_" + "5" * 32,
        HASH,
        pointer.source_artifact_id,
        True,
        True,
        "item_" + "6" * 32,
        HASH,
        "APPROVED",
        "ACTIVE",
        None,
        "external-item-learning",
        None,
        None,
        None,
    ]
    row[unavailable_index] = value
    session.execute.return_value = [tuple(row)]
    sources, more = KnowledgeMapReadService._sources(session, SNAPSHOT, NODE, None)
    assert len(sources) == 1 and not more and not sources[0].available
    assert sources[0].source_revision_id == pointer.source_revision_id
    assert sources[0].source_sha256 == HASH and sources[0].layer == "CREATIVE"
    session.commit.assert_not_called()
