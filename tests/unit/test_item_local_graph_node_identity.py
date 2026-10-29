"""Item-local names do not merge unrelated Items or rekey the historical corpus."""

from dataclasses import replace

import pytest
from eom_catalog_contracts import KnowledgeAnalysisWorkerProposal, KnowledgeGraphStructureManifest
from eom_catalog_service.knowledge_graph_projection import (
    ITEM_SCOPED_GRAPH_PUBLISHER_VERSION,
    KnowledgeGraphProjectionError,
    KnowledgeNodeIdentityPolicy,
    build_education_graph_projection,
    node_identity_policy_for_publisher,
    serialize_education_graph_projection,
)
from eom_identifiers import content_sha256

from tests.unit.test_creative_past_exam_graph_compatibility import _item
from tests.unit.test_curriculum_graph_structure import NOW, OPERATOR_ID

POLICY = KnowledgeNodeIdentityPolicy.ITEM_REVISION_SCOPED


def _local_item(ordinal: int, *, node_type: str = "ITEM_ELEMENT", past_exam: bool = False):
    analysis = _item(ordinal, past_exam=past_exam)
    value = analysis.proposal.model_dump(mode="json")
    value["nodes"].extend(
        [
            {
                "node_id": "knode_local_item",
                "node_type": "ITEM_REVISION",
                "stable_key": "item.1",
                "label": f"문항 {ordinal}",
                "anchor_ids": ["anchor_item_title"],
            },
            {
                "node_id": "knode_local_statement",
                "node_type": node_type,
                "stable_key": "item.1.statement.giyeok",
                "label": f"문항 {ordinal}의 ㄱ",
                "anchor_ids": ["anchor_item_title"],
            },
        ]
    )
    return replace(analysis, proposal=KnowledgeAnalysisWorkerProposal.model_validate(value))


def test_different_item_local_types_are_distinct_but_concepts_remain_shared():
    first, second = _local_item(1), _local_item(2, node_type="CLAIM")
    with pytest.raises(KnowledgeGraphProjectionError):
        build_education_graph_projection((first, second), None)
    projection = build_education_graph_projection(
        (first, second), None, node_identity_policy=POLICY
    )
    local = [node for node in projection.nodes if node.stable_key.startswith("item-source:")]
    assert len(local) == 4
    assert len({node.node_id for node in local}) == 4
    assert all(len(node.source_pointers) == 1 for node in local)
    concept = next(
        node for node in projection.nodes if node.stable_key == "concept.integrated-science"
    )
    assert len(concept.source_pointers) == 2
    assert {node.node_type for node in local} == {"ITEM_REVISION", "ITEM_ELEMENT", "CLAIM"}
    assert serialize_education_graph_projection(projection) == serialize_education_graph_projection(
        projection
    )


def test_same_revision_conflicting_type_still_fails_closed():
    first = _local_item(1)
    second = replace(_local_item(2, node_type="CLAIM"), source=first.source)
    with pytest.raises(KnowledgeGraphProjectionError, match="conflicting type"):
        build_education_graph_projection((first, second), None, node_identity_policy=POLICY)


def test_shared_concept_type_conflict_is_not_renamed_or_ignored():
    first, second = _local_item(1), _local_item(2)
    value = second.proposal.model_dump(mode="json")
    value["nodes"][0]["node_type"] = "CLAIM"
    second = replace(second, proposal=KnowledgeAnalysisWorkerProposal.model_validate(value))
    with pytest.raises(KnowledgeGraphProjectionError, match="conflicting type"):
        build_education_graph_projection((first, second), None, node_identity_policy=POLICY)


def test_historical_past_exam_nodes_and_edges_are_not_rekeyed():
    past, creative = _local_item(1, past_exam=True), _local_item(2, node_type="CLAIM")
    before = build_education_graph_projection((past,), None)
    after = build_education_graph_projection((past, creative), None, node_identity_policy=POLICY)
    new = {node.node_id: node for node in after.nodes}
    for old in before.nodes:
        assert old.node_id in new
        assert old.stable_key == new[old.node_id].stable_key
        assert set(old.source_pointers) <= set(new[old.node_id].source_pointers)
    assert {edge.edge_id for edge in before.edges} <= {edge.edge_id for edge in after.edges}
    assert (
        next(node for node in after.nodes if node.stable_key == "item.1")
        .source_pointers[0]
        .source_class
        == "PAST_EXAM"
    )


def test_only_explicit_new_publisher_changes_identity_and_old_replays_stay_equal():
    for version in ("1.6.0", "1.8.0", "1.9.0"):
        assert (
            node_identity_policy_for_publisher(version)
            == KnowledgeNodeIdentityPolicy.SHARED_STABLE_KEY
        )
    assert node_identity_policy_for_publisher(ITEM_SCOPED_GRAPH_PUBLISHER_VERSION) == POLICY
    analysis = _local_item(1)
    original = build_education_graph_projection((analysis,), None)
    replay = build_education_graph_projection(
        (analysis,), None, node_identity_policy=node_identity_policy_for_publisher("1.9.0")
    )
    assert serialize_education_graph_projection(original) == serialize_education_graph_projection(
        replay
    )


def test_type_qualified_item_local_claim_is_scoped_too():
    analysis = _local_item(1, node_type="CLAIM")
    value = analysis.proposal.model_dump(mode="json")
    value["nodes"][-1]["stable_key"] = "claim:item.1.statement.giyeok"
    analysis = replace(analysis, proposal=KnowledgeAnalysisWorkerProposal.model_validate(value))
    projection = build_education_graph_projection((analysis,), None, node_identity_policy=POLICY)
    claim = next(node for node in projection.nodes if node.node_type == "CLAIM")
    assert claim.stable_key.startswith("item-source:")


def test_item_edges_keep_their_own_endpoints_after_local_scoping():
    analyses = []
    for ordinal in (1, 2):
        analysis = _local_item(ordinal)
        value = analysis.proposal.model_dump(mode="json")
        value["edges"] = [
            {
                "edge_id": "kedge_item_concept",
                "edge_type": "ASSESSES_CONCEPT",
                "from_node_id": "knode_local_item",
                "to_node_id": value["nodes"][0]["node_id"],
                "confidence_milli": 900,
                "anchor_ids": ["anchor_item_title"],
            }
        ]
        analyses.append(
            replace(analysis, proposal=KnowledgeAnalysisWorkerProposal.model_validate(value))
        )
    projection = build_education_graph_projection(
        tuple(analyses), None, node_identity_policy=POLICY
    )
    assert len(projection.edges) == 2
    assert len({edge.from_node_id for edge in projection.edges}) == 2
    assert len({edge.to_node_id for edge in projection.edges}) == 1
    assert all(len(edge.source_pointers) == 1 for edge in projection.edges)


def test_explicit_item_binding_and_answer_bearing_follow_the_projected_node():
    analysis = _local_item(1)
    source = analysis.source
    value = {
        "structure_manifest_id": "graphstructure_" + "a" * 32,
        "source_analysis_run_ids": [analysis.analysis_run_id],
        "curriculum_units": [],
        "item_elements": [
            {
                "node_stable_key": "item.1.statement.giyeok",
                "item_id": source.item_id,
                "item_revision_id": source.item_revision_id,
                "item_content_artifact_id": source.artifact_member.artifact_id,
                "item_content_artifact_revision_id": source.artifact_member.artifact_revision_id,
                "item_content_sha256": source.artifact_member.sha256,
                "schema_ref": "eom.assessment.item-content/1.0",
                "element_kind": "statement",
                "element_id": "giyeok",
                "answer_bearing": True,
            }
        ],
        "reviewed_by_operator_id": OPERATOR_ID,
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    value["schema_version"] = "knowledge-graph-structure-manifest/1.0"
    value["manifest_sha256"] = content_sha256(value)
    structure = KnowledgeGraphStructureManifest.model_validate(value)
    projection = build_education_graph_projection(
        (analysis,), structure, node_identity_policy=POLICY
    )
    element = projection.item_elements[0]
    assert element.node_stable_key.startswith("item-source:")
    node = next(node for node in projection.nodes if node.stable_key == element.node_stable_key)
    assert node.answer_bearing
    assert structure.item_elements[0].node_stable_key == "item.1.statement.giyeok"
    assert analysis.proposal.nodes[-1].stable_key == "item.1.statement.giyeok"
