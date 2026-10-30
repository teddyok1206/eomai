"""Publisher 1.11 preserves protected nodes and separates unlike creative meanings."""

from dataclasses import replace

import pytest
from eom_catalog_contracts import KnowledgeAnalysisWorkerProposal
from eom_catalog_service.knowledge_graph_projection import (
    CURRENT_ITEM_GRAPH_PUBLISHER_VERSION,
    KnowledgeGraphProjectionError,
    KnowledgeNodeIdentityPolicy,
    build_education_graph_projection,
    node_identity_policy_for_publisher,
    serialize_education_graph_projection,
)
from eom_identifiers import canonical_json_bytes, content_sha256

from tests.unit.test_creative_past_exam_graph_compatibility import _item
from tests.unit.test_curriculum_graph_structure import _complete_analyses
from tests.unit.test_item_local_graph_node_identity import _local_item

POLICY = KnowledgeNodeIdentityPolicy.ITEM_SCOPED_TYPED_SHARED


def with_type(analysis, node_type, *, key=None):
    value = analysis.proposal.model_dump(mode="json")
    value["nodes"][0]["node_type"] = node_type
    if key is not None:
        value["nodes"][0]["stable_key"] = key
    return replace(analysis, proposal=KnowledgeAnalysisWorkerProposal.model_validate(value))


def project(*analyses):
    return build_education_graph_projection(
        tuple(sorted(analyses, key=lambda row: row.analysis_run_id)),
        None,
        node_identity_policy=POLICY,
    )


def test_only_explicit_successor_selects_typed_shared_identity():
    assert node_identity_policy_for_publisher(CURRENT_ITEM_GRAPH_PUBLISHER_VERSION) == POLICY
    assert node_identity_policy_for_publisher("1.10.0") != POLICY
    assert node_identity_policy_for_publisher("1.9.0") != POLICY


def test_creative_concept_and_process_keep_distinct_types_and_exact_source_provenance():
    first = _item(1, past_exam=False)
    second = with_type(_item(2, past_exam=False), "PROCESS")
    result = project(first, second)
    variants = [node for node in result.nodes if node.stable_key.startswith("shared-type:")]
    assert len(variants) == 2
    assert {node.node_type for node in variants} == {"CONCEPT", "PROCESS"}
    assert all(len(node.source_pointers) == 1 for node in variants)
    assert {p.analysis_run_id for node in variants for p in node.source_pointers} == {
        first.analysis_run_id,
        second.analysis_run_id,
    }
    assert serialize_education_graph_projection(result) == serialize_education_graph_projection(
        project(second, first)
    )
    assert result.edges == ()  # no invented equivalence or scientific relationship


@pytest.mark.parametrize("protected_class", ["PAST_EXAM", "TEXTBOOK"])
def test_protected_original_key_id_and_edges_are_preserved(protected_class):
    protected = (
        _item(1, past_exam=True) if protected_class == "PAST_EXAM" else _complete_analyses()[0]
    )
    original = build_education_graph_projection((protected,), None)
    selected = protected.proposal.nodes[0]
    other_type = "PROCESS" if selected.node_type != "PROCESS" else "CONCEPT"
    creative = with_type(_item(2, past_exam=False), other_type, key=selected.stable_key)
    combined = project(protected, creative)
    after = {node.node_id: node for node in combined.nodes}
    for node in original.nodes:
        assert (after[node.node_id].stable_key, after[node.node_id].node_type) == (
            node.stable_key,
            node.node_type,
        )
        assert set(node.source_pointers) <= set(after[node.node_id].source_pointers)
    assert {edge.edge_id for edge in original.edges} <= {edge.edge_id for edge in combined.edges}
    variant = next(node for node in combined.nodes if node.stable_key.startswith("shared-type:"))
    assert variant.node_type == other_type
    assert variant.source_pointers[0].source_class == "APPROVED_ITEM"


def test_same_type_still_merges_across_different_creative_items():
    first, second = _item(1, past_exam=False), _item(2, past_exam=False)
    combined = project(first, second)
    shared = [
        node for node in combined.nodes if node.stable_key == first.proposal.nodes[0].stable_key
    ]
    assert len(shared) == 1 and len(shared[0].source_pointers) == 2
    assert not any(node.stable_key.startswith("shared-type:") for node in combined.nodes)


def test_competing_type_does_not_split_same_type_sources_from_each_other():
    first, second = _item(1, past_exam=False), _item(2, past_exam=False)
    third = with_type(_item(3, past_exam=False), "PROCESS")
    combined = project(first, second, third)
    assert len([node for node in combined.nodes if node.stable_key.startswith("shared-type:")]) == 2
    assert (
        len(next(node for node in combined.nodes if node.node_type == "CONCEPT").source_pointers)
        == 2
    )


def test_conflicting_protected_corpus_types_still_fail_closed():
    first = _item(1, past_exam=True)
    second = with_type(_item(2, past_exam=True), "PROCESS")
    with pytest.raises(KnowledgeGraphProjectionError, match="protected corpus"):
        project(first, second)


def test_conflicting_types_in_same_immutable_item_still_fail_closed():
    first = _item(1, past_exam=False)
    second = replace(with_type(_item(2, past_exam=False), "PROCESS"), source=first.source)
    with pytest.raises(KnowledgeGraphProjectionError, match="immutable Item"):
        project(first, second)


def test_item_local_types_remain_scoped_in_successor():
    first, second = _local_item(1), _local_item(2, node_type="CLAIM")
    combined = project(first, second)
    assert len([node for node in combined.nodes if node.stable_key.startswith("item-source:")]) == 4
    assert (
        len([node for node in combined.nodes if node.stable_key == "concept.integrated-science"])
        == 1
    )


def test_edges_keep_their_proposal_local_typed_endpoints():
    analyses = []
    for ordinal, node_type in ((1, "CONCEPT"), (2, "PROCESS")):
        analysis = with_type(_local_item(ordinal), node_type)
        value = analysis.proposal.model_dump(mode="json")
        value["edges"] = [
            {
                "edge_id": "kedge_prerequisite",
                "edge_type": "REQUIRES_PREREQUISITE",
                "from_node_id": "knode_local_item",
                "to_node_id": value["nodes"][0]["node_id"],
                "confidence_milli": 900,
                "anchor_ids": ["anchor_item_title"],
            }
        ]
        analyses.append(
            replace(analysis, proposal=KnowledgeAnalysisWorkerProposal.model_validate(value))
        )
    combined = project(*analyses)
    nodes = {node.node_id: node for node in combined.nodes}
    assert len(combined.edges) == 2
    assert len({edge.to_node_id for edge in combined.edges}) == 2
    for edge in combined.edges:
        assert nodes[edge.from_node_id].stable_key.startswith("item-source:")
        assert nodes[edge.to_node_id].stable_key.startswith("shared-type:")
        assert edge.source_pointers[0] in nodes[edge.to_node_id].source_pointers


def test_node_variants_never_rewrite_accepted_proposals_or_report_hashes():
    first = _item(1, past_exam=False)
    second = with_type(_item(2, past_exam=False), "PROCESS")
    values = tuple(a.proposal.model_dump(mode="json") for a in (first, second))
    encoded = tuple(canonical_json_bytes(value) for value in values)
    hashes = tuple(content_sha256(value) for value in values)
    project(first, second)
    assert (
        tuple(canonical_json_bytes(a.proposal.model_dump(mode="json")) for a in (first, second))
        == encoded
    )
    assert (
        tuple(content_sha256(a.proposal.model_dump(mode="json")) for a in (first, second)) == hashes
    )
