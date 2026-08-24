from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from eom_catalog_contracts import (
    ContentIntakeKnowledgeSourceV2,
    KnowledgeAnalysisWorkerProposal,
    KnowledgeArtifactMemberPointer,
    KnowledgeGraphStructureManifest,
    validate_contract,
)
from eom_catalog_service.knowledge_graph_projection import (
    AcceptedAnalysisProposal,
    KnowledgeGraphProjectionError,
    build_education_graph_projection,
    serialize_education_graph_projection,
)
from eom_identifiers import content_sha256

NOW = datetime(2026, 8, 24, 3, tzinfo=UTC)


def _source(seed: str) -> ContentIntakeKnowledgeSourceV2:
    return ContentIntakeKnowledgeSourceV2.model_validate(
        {
            "source_kind": "CONTENT_INTAKE_FILE",
            "source_class": "CURRICULUM",
            "intake_batch_id": "intake_" + seed * 32,
            "source_file_id": "sourcefile_" + seed * 32,
            "lifecycle_state": "ELIGIBLE",
            "artifact_member": {
                "artifact_id": "artifact_" + seed * 32,
                "artifact_revision_id": "rev_" + seed * 32,
                "member_path": "curriculum.md",
                "materialized_path": "source/curriculum.md",
                "sha256": "sha256:" + seed * 64,
                "bytes": 100,
                "schema_ref": None,
                "media_type": "text/markdown",
                "logical_name": "curriculum.md",
            },
        }
    )


def _proposal(seed: str, *, confidence: int = 900) -> KnowledgeAnalysisWorkerProposal:
    return KnowledgeAnalysisWorkerProposal.model_validate(
        {
            "schema_version": "knowledge-analysis-worker-proposal/1.0",
            "analysis_request_id": "knowledgeanalysis_" + seed * 32,
            "normalized_markdown": "# Curriculum\n",
            "anchors": [
                {
                    "anchor_id": "anchor_section_1",
                    "artifact_revision_id": "rev_" + seed * 32,
                    "member_path": "curriculum.md",
                    "anchor_kind": "SECTION",
                    "locator": "section=1",
                    "excerpt_sha256": "sha256:" + seed * 64,
                }
            ],
            "nodes": [
                {
                    "node_id": "knode_major",
                    "node_type": "CURRICULUM_UNIT",
                    "stable_key": "curriculum.major",
                    "label": "Integrated Science",
                    "anchor_ids": ["anchor_section_1"],
                },
                {
                    "node_id": "knode_middle",
                    "node_type": "CURRICULUM_UNIT",
                    "stable_key": "curriculum.major.matter",
                    "label": "Matter",
                    "anchor_ids": ["anchor_section_1"],
                },
                {
                    "node_id": "knode_item_table",
                    "node_type": "ITEM_ELEMENT",
                    "stable_key": "item.example.table-1",
                    "label": "Example data table",
                    "anchor_ids": ["anchor_section_1"],
                },
                {
                    "node_id": "knode_claim",
                    "node_type": "CLAIM",
                    "stable_key": "claim.density",
                    "label": "Density relates mass and volume",
                    "anchor_ids": ["anchor_section_1"],
                },
                {
                    "node_id": "knode_concept",
                    "node_type": "CONCEPT",
                    "stable_key": "concept.density",
                    "label": "Density",
                    "anchor_ids": ["anchor_section_1"],
                },
            ],
            "edges": [
                {
                    "edge_id": "kedge_explains",
                    "edge_type": "EXPLAINS",
                    "from_node_id": "knode_claim",
                    "to_node_id": "knode_concept",
                    "confidence_milli": confidence,
                    "anchor_ids": ["anchor_section_1"],
                }
            ],
            "claims": [],
            "component_observations": [],
            "unresolved_ambiguities": [],
            "general_knowledge_used": False,
            "completed_at": NOW,
        }
    )


def _analysis(seed: str, *, confidence: int = 900) -> AcceptedAnalysisProposal:
    return AcceptedAnalysisProposal(
        analysis_run_id="analysisrun_" + seed * 32,
        source=_source(seed),
        accepted_result=KnowledgeArtifactMemberPointer(
            artifact_id="artifact_" + seed * 32,
            artifact_revision_id="rev_" + seed * 32,
            sha256="sha256:" + seed * 64,
            schema_ref="eom://schemas/knowledge/knowledge-analysis-result/2.0",
            media_type="application/json",
            logical_name="accepted-result.json",
            member_path="evidence/accepted-result.json",
        ),
        proposal=_proposal(seed, confidence=confidence),
    )


def _structure() -> KnowledgeGraphStructureManifest:
    value = {
        "schema_version": "knowledge-graph-structure-manifest/1.0",
        "structure_manifest_id": "graphstructure_" + "1" * 32,
        "source_analysis_run_ids": ["analysisrun_" + "1" * 32, "analysisrun_" + "2" * 32],
        "curriculum_units": [
            {
                "framework_revision_id": "curriculumrev_" + "1" * 32,
                "curriculum_unit_id": "currunit_" + "1" * 32,
                "node_stable_key": "curriculum.major",
                "parent_unit_id": None,
                "unit_level": "MAJOR",
                "ordinal": 1,
            },
            {
                "framework_revision_id": "curriculumrev_" + "1" * 32,
                "curriculum_unit_id": "currunit_" + "2" * 32,
                "node_stable_key": "curriculum.major.matter",
                "parent_unit_id": "currunit_" + "1" * 32,
                "unit_level": "MIDDLE",
                "ordinal": 1,
            },
        ],
        "item_elements": [
            {
                "node_stable_key": "item.example.table-1",
                "item_id": "item_" + "1" * 32,
                "item_revision_id": "itemrev_" + "1" * 32,
                "item_content_artifact_id": "artifact_" + "3" * 32,
                "item_content_artifact_revision_id": "rev_" + "3" * 32,
                "item_content_sha256": "sha256:" + "3" * 64,
                "schema_ref": "eom.assessment.item-content/1.0",
                "element_kind": "table",
                "element_id": "table-1",
                "answer_bearing": True,
            }
        ],
        "reviewed_by_operator_id": "operator_" + "1" * 32,
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
        "manifest_sha256": "sha256:" + "0" * 64,
    }
    value["manifest_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "manifest_sha256"}
    )
    return KnowledgeGraphStructureManifest.model_validate(value)


def test_projection_deduplicates_by_stable_identity_and_serializes_deterministically() -> None:
    projection = build_education_graph_projection(
        (_analysis("1", confidence=900), _analysis("2", confidence=800)), _structure()
    )
    assert len(projection.nodes) == 5
    assert len(projection.edges) == 1
    assert projection.edges[0].confidence_milli == 800
    assert len(projection.edges[0].source_pointers) == 2
    assert len(projection.curriculum_closure) == 3
    item_node = next(item for item in projection.nodes if item.stable_key.startswith("item."))
    assert item_node.answer_bearing

    first = serialize_education_graph_projection(projection)
    second = serialize_education_graph_projection(projection)
    assert first == second
    assert first.snapshot_sha256.startswith("sha256:")
    assert first.members["projections/nodes.jsonl"].endswith(b"\n")
    assert "projections/curriculum-closure.jsonl" in first.members
    for path, metadata in first.metadata.items():
        if path != "projections/graph.md":
            assert metadata["schema_ref"] == (
                "eom://schemas/knowledge/knowledge-graph-projection/1.0"
            )
    for path in (
        "projections/nodes.jsonl",
        "projections/edges.jsonl",
        "projections/curriculum-closure.jsonl",
    ):
        for line in first.members[path].splitlines():
            validate_contract("knowledge-graph-projection", json.loads(line))
    validate_contract(
        "knowledge-graph-projection",
        json.loads(first.members["projections/lexical-index.json"]),
    )


def test_projection_fails_closed_on_conflicts_incompatible_edges_and_source_set() -> None:
    conflicting = _analysis("2")
    nodes = list(conflicting.proposal.nodes)
    nodes[0] = nodes[0].model_copy(update={"label": "Conflicting label"})
    conflicting = AcceptedAnalysisProposal(
        analysis_run_id=conflicting.analysis_run_id,
        source=conflicting.source,
        accepted_result=conflicting.accepted_result,
        proposal=conflicting.proposal.model_copy(update={"nodes": tuple(nodes)}),
    )
    with pytest.raises(KnowledgeGraphProjectionError) as conflict_info:
        build_education_graph_projection((_analysis("1"), conflicting), _structure())
    assert conflict_info.value.code == "KNOWLEDGE_GRAPH_NODE_CONFLICT"

    incompatible = _analysis("1")
    edges = list(incompatible.proposal.edges)
    edges[0] = edges[0].model_copy(update={"edge_type": "HAS_ITEM_ELEMENT"})
    incompatible = AcceptedAnalysisProposal(
        analysis_run_id=incompatible.analysis_run_id,
        source=incompatible.source,
        accepted_result=incompatible.accepted_result,
        proposal=incompatible.proposal.model_copy(update={"edges": tuple(edges)}),
    )
    with pytest.raises(KnowledgeGraphProjectionError) as edge_info:
        build_education_graph_projection((incompatible,), None)
    assert edge_info.value.code == "KNOWLEDGE_GRAPH_EDGE_INCOMPATIBLE"

    with pytest.raises(KnowledgeGraphProjectionError) as source_info:
        build_education_graph_projection((_analysis("1"),), _structure())
    assert source_info.value.code == "KNOWLEDGE_GRAPH_STRUCTURE_SOURCE_MISMATCH"
