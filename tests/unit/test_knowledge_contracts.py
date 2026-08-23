from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest
from eom_catalog_contracts import (
    EducationRetrievalRequest,
    EvidenceBundleManifest,
    KnowledgeAnalysisRequest,
    KnowledgeAnalysisResult,
    KnowledgeGraphSnapshotManifest,
    validate_contract,
)
from eom_identifiers import content_sha256
from jsonschema import ValidationError
from pydantic import ValidationError as PydanticValidationError

NOW = datetime(2026, 8, 23, 3, 4, 5, tzinfo=UTC)


def _artifact(
    seed: str,
    *,
    member_path: str,
    media_type: str = "application/json",
    logical_name: str = "result.json",
) -> dict[str, object]:
    return {
        "artifact_id": "artifact_" + seed * 32,
        "artifact_revision_id": "rev_" + seed * 32,
        "sha256": "sha256:" + seed * 64,
        "schema_ref": "eom://schemas/knowledge/projection/1.0",
        "media_type": media_type,
        "logical_name": logical_name,
        "member_path": member_path,
    }


def _source(seed: str = "1", source_class: str = "TEXTBOOK") -> dict[str, object]:
    return {
        "source_class": source_class,
        "logical_id": "document_" + seed * 32,
        "revision_id": "documentrev_" + seed * 32,
        "lifecycle_state": "APPROVED",
        "artifact_member": _artifact(
            seed,
            member_path="source/chapter-1.pdf",
            media_type="application/pdf",
            logical_name="chapter-1.pdf",
        ),
    }


def _graph_pointer(seed: str = "2") -> dict[str, object]:
    return {
        "graph_id": "graph_" + seed * 32,
        "graph_snapshot_revision_id": "graphrev_" + seed * 32,
        "manifest_artifact": _artifact(
            seed,
            member_path="projections/manifest.json",
            logical_name="manifest.json",
        ),
        "manifest_sha256": "sha256:" + seed * 64,
    }


def _analysis_request() -> dict[str, object]:
    return {
        "schema_version": "knowledge-analysis-request/1.0",
        "analysis_request_id": "knowledgeanalysis_" + "3" * 32,
        "source": _source(),
        "execution_preset_id": "execpreset_" + "3" * 32,
        "execution_preset_revision_id": "execpresetrev_" + "3" * 32,
        "execution_preset_sha256": "sha256:" + "3" * 64,
        "result_schema_ref": "eom://schemas/knowledge/knowledge-analysis-result/1.0",
        "prior_graph_snapshot": None,
        "requested_outputs": [
            "NORMALIZED_MARKDOWN",
            "SOURCE_ANCHORS",
            "NODES",
            "EDGES",
            "COMPONENT_OBSERVATIONS",
        ],
        "general_knowledge_mode": "AUXILIARY_UNATTRIBUTED",
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
    }


def _anchor() -> dict[str, object]:
    return {
        "anchor_id": "anchor_section_1",
        "source_revision_id": "documentrev_" + "1" * 32,
        "artifact_revision_id": "rev_" + "1" * 32,
        "member_path": "source/chapter-1.pdf",
        "anchor_kind": "SECTION",
        "locator": "section:1.2",
        "excerpt_sha256": "sha256:" + "4" * 64,
    }


def _analysis_result() -> dict[str, object]:
    return {
        "schema_version": "knowledge-analysis-result/1.0",
        "analysis_request_id": "knowledgeanalysis_" + "3" * 32,
        "source_revision_id": "documentrev_" + "1" * 32,
        "status": "PROPOSED",
        "normalized_markdown": _artifact(
            "4",
            member_path="normalized/chapter-1.md",
            media_type="text/markdown",
            logical_name="chapter-1.md",
        ),
        "anchors": [_anchor()],
        "nodes": [
            {
                "node_id": "knode_concept_density",
                "node_type": "CONCEPT",
                "stable_key": "science.density",
                "label": "Density",
                "anchor_ids": ["anchor_section_1"],
            },
            {
                "node_id": "knode_claim_density",
                "node_type": "CLAIM",
                "stable_key": "claim.density.ratio",
                "label": "Density is mass divided by volume",
                "anchor_ids": ["anchor_section_1"],
            },
        ],
        "edges": [
            {
                "edge_id": "kedge_density_explains",
                "edge_type": "EXPLAINS",
                "from_node_id": "knode_claim_density",
                "to_node_id": "knode_concept_density",
                "confidence_milli": 950,
                "anchor_ids": ["anchor_section_1"],
            }
        ],
        "claims": [
            {
                "claim_id": "claim_density_ratio",
                "text": "Density is the ratio of mass to volume.",
                "anchor_ids": ["anchor_section_1"],
            }
        ],
        "component_observations": [
            {
                "component_id": "component_paragraph_1",
                "kind": "PARAGRAPH",
                "anchor_id": "anchor_section_1",
                "artifact_member": None,
            }
        ],
        "unresolved_ambiguities": [],
        "completed_at": NOW.isoformat().replace("+00:00", "Z"),
        "result_sha256": "sha256:" + "4" * 64,
    }


def _snapshot_manifest() -> dict[str, object]:
    return {
        "schema_version": "knowledge-graph-snapshot-manifest/1.0",
        "graph_id": "graph_" + "2" * 32,
        "graph_snapshot_revision_id": "graphrev_" + "2" * 32,
        "revision_number": 1,
        "previous_graph_snapshot_revision_id": None,
        "state": "PUBLISHED",
        "ontology_version": "education-knowledge-graph/1.0",
        "publisher_version": "1.0.0",
        "source_revisions": [_source()],
        "analysis_results": [_artifact("5", member_path="projections/analysis-result.json")],
        "projections": {
            "nodes": _artifact("6", member_path="projections/nodes.jsonl"),
            "edges": _artifact("7", member_path="projections/edges.jsonl"),
            "curriculum_closure": None,
            "markdown": _artifact(
                "8",
                member_path="projections/graph.md",
                media_type="text/markdown",
                logical_name="graph.md",
            ),
            "lexical_index": _artifact(
                "9",
                member_path="projections/lexical-index.json",
                logical_name="lexical-index.json",
            ),
        },
        "counts": {"source_revisions": 1, "nodes": 2, "edges": 1, "anchors": 1},
        "snapshot_sha256": "sha256:" + "2" * 64,
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
    }


def _retrieval_request() -> dict[str, object]:
    return {
        "schema_version": "education-retrieval-request/1.0",
        "retrieval_request_id": "retrieval_" + "a" * 32,
        "graph_snapshot": _graph_pointer(),
        "query_kind": "APPROVED_ITEM_STRUCTURE",
        "curriculum_scope": {
            "framework_revision_id": "curriculumrev_" + "a" * 32,
            "root_unit_id": "currunit_" + "a" * 32,
            "include_descendants": True,
        },
        "topic_keys": [],
        "target_item_revision_id": None,
        "required_item_elements": ["table", "statement_set"],
        "source_classes": ["CURRICULUM", "APPROVED_ITEM"],
        "retrieval_mode": "HYBRID_LOCAL_MULTIHOP",
        "evidence_budget": {
            "max_documents": 8,
            "max_item_revisions": 12,
            "max_graph_nodes": 48,
            "max_claims": 24,
            "max_context_tokens": 18000,
        },
        "access_policy_revision_id": "accessrev_" + "a" * 32,
        "requester_role": "WORKER",
        "requested_at": NOW.isoformat().replace("+00:00", "Z"),
        "request_sha256": "sha256:" + "a" * 64,
    }


def _evidence_manifest() -> dict[str, object]:
    source = _source("b", "APPROVED_ITEM")
    source["logical_id"] = "item_" + "b" * 32
    source["revision_id"] = "itemrev_" + "b" * 32
    return {
        "schema_version": "evidence-bundle-manifest/1.0",
        "evidence_bundle_id": "evidence_" + "b" * 32,
        "evidence_bundle_revision_id": "evidencerev_" + "b" * 32,
        "revision_number": 1,
        "retrieval_request_id": "retrieval_" + "a" * 32,
        "retrieval_request_sha256": "sha256:" + "a" * 64,
        "graph_snapshot": _graph_pointer(),
        "access_policy_revision_id": "accessrev_" + "a" * 32,
        "entries": [
            {
                "evidence_id": "evidenceitem_" + "b" * 32,
                "evidence_kind": "ITEM_REVISION",
                "use": "REFERENCE_PATTERN",
                "source": source,
                "anchor_ids": ["anchor_section_1"],
                "relevance_milli": 900,
                "answer_bearing": True,
            }
        ],
        "budget": {
            "document_count": 0,
            "item_revision_count": 1,
            "graph_node_count": 4,
            "claim_count": 0,
            "estimated_context_tokens": 1200,
        },
        "manifest_sha256": "sha256:" + "b" * 64,
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
    }


@pytest.mark.parametrize(
    ("name", "value", "model"),
    [
        ("knowledge-analysis-request", _analysis_request(), KnowledgeAnalysisRequest),
        ("knowledge-analysis-result", _analysis_result(), KnowledgeAnalysisResult),
        (
            "knowledge-graph-snapshot-manifest",
            _snapshot_manifest(),
            KnowledgeGraphSnapshotManifest,
        ),
        ("education-retrieval-request", _retrieval_request(), EducationRetrievalRequest),
        ("evidence-bundle-manifest", _evidence_manifest(), EvidenceBundleManifest),
    ],
)
def test_knowledge_contracts_validate_at_schema_and_typed_boundaries(
    name: str, value: dict[str, object], model: type[object]
) -> None:
    validate_contract(name, value)
    validator = model.model_validate
    assert validator(value)


def test_knowledge_contracts_forbid_secrets_raw_source_and_unknown_fields() -> None:
    for forbidden in ("credential", "access_token", "raw_source", "nas_path", "session_id"):
        value = {**_analysis_request(), forbidden: "<redacted>"}
        with pytest.raises(ValidationError):
            validate_contract("knowledge-analysis-request", value)
        with pytest.raises(PydanticValidationError):
            KnowledgeAnalysisRequest.model_validate(value)


def test_source_and_projection_paths_fail_closed() -> None:
    value = _analysis_request()
    source = value["source"]
    assert isinstance(source, dict)
    artifact = source["artifact_member"]
    assert isinstance(artifact, dict)
    artifact["member_path"] = "../../etc/passwd"
    with pytest.raises(ValidationError):
        validate_contract("knowledge-analysis-request", value)
    with pytest.raises(PydanticValidationError):
        KnowledgeAnalysisRequest.model_validate(value)


def test_analysis_result_rejects_dangling_graph_and_anchor_pointers() -> None:
    dangling_edge = _analysis_result()
    edges = dangling_edge["edges"]
    assert isinstance(edges, list)
    edges[0]["to_node_id"] = "knode_missing"
    with pytest.raises(PydanticValidationError, match="edge endpoint does not resolve"):
        KnowledgeAnalysisResult.model_validate(dangling_edge)

    dangling_anchor = _analysis_result()
    nodes = dangling_anchor["nodes"]
    assert isinstance(nodes, list)
    nodes[0]["anchor_ids"] = ["anchor_missing"]
    with pytest.raises(PydanticValidationError, match="anchor pointer does not resolve"):
        KnowledgeAnalysisResult.model_validate(dangling_anchor)


def test_analysis_result_rejects_unpinned_general_knowledge_as_citation() -> None:
    value = _analysis_result()
    anchors = value["anchors"]
    assert isinstance(anchors, list)
    anchors[0]["source_revision_id"] = "documentrev_" + "f" * 32
    with pytest.raises(PydanticValidationError, match="does not match analyzed source"):
        KnowledgeAnalysisResult.model_validate(value)


def test_snapshot_requires_exact_unique_sources_and_counts() -> None:
    value = _snapshot_manifest()
    counts = value["counts"]
    assert isinstance(counts, dict)
    counts["source_revisions"] = 2
    with pytest.raises(PydanticValidationError, match="source count does not match"):
        KnowledgeGraphSnapshotManifest.model_validate(value)

    duplicate = _snapshot_manifest()
    sources = duplicate["source_revisions"]
    assert isinstance(sources, list)
    sources.append(deepcopy(sources[0]))
    duplicate_counts = duplicate["counts"]
    assert isinstance(duplicate_counts, dict)
    duplicate_counts["source_revisions"] = 2
    with pytest.raises(PydanticValidationError, match="source revisions must be unique"):
        KnowledgeGraphSnapshotManifest.model_validate(duplicate)


def test_retrieval_is_typed_bounded_and_does_not_invent_phase_six_usage_contract() -> None:
    missing_scope = _retrieval_request()
    missing_scope["curriculum_scope"] = None
    with pytest.raises(PydanticValidationError, match="requires a pinned curriculum scope"):
        EducationRetrievalRequest.model_validate(missing_scope)

    unknown_future_query = _retrieval_request()
    unknown_future_query["query_kind"] = "ITEM_USAGE_HISTORY"
    with pytest.raises(ValidationError):
        validate_contract("education-retrieval-request", unknown_future_query)

    unbounded = _retrieval_request()
    budget = unbounded["evidence_budget"]
    assert isinstance(budget, dict)
    budget["max_context_tokens"] = 1000000
    with pytest.raises(ValidationError):
        validate_contract("education-retrieval-request", unbounded)


def test_evidence_bundle_deduplicates_pointers_and_verifies_counts() -> None:
    mismatch = _evidence_manifest()
    budget = mismatch["budget"]
    assert isinstance(budget, dict)
    budget["item_revision_count"] = 0
    with pytest.raises(PydanticValidationError, match="counts do not match"):
        EvidenceBundleManifest.model_validate(mismatch)

    duplicate = _evidence_manifest()
    entries = duplicate["entries"]
    assert isinstance(entries, list)
    second = deepcopy(entries[0])
    second["evidence_id"] = "evidenceitem_" + "c" * 32
    entries.append(second)
    duplicate_budget = duplicate["budget"]
    assert isinstance(duplicate_budget, dict)
    duplicate_budget["item_revision_count"] = 2
    with pytest.raises(PydanticValidationError, match="duplicate an immutable source"):
        EvidenceBundleManifest.model_validate(duplicate)


def test_knowledge_contracts_have_canonical_float_free_hashes() -> None:
    result = KnowledgeAnalysisResult.model_validate(_analysis_result())
    evidence = EvidenceBundleManifest.model_validate(_evidence_manifest())

    assert content_sha256(result).startswith("sha256:")
    assert content_sha256(evidence).startswith("sha256:")
