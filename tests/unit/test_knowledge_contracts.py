from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest
from eom_catalog_contracts import (
    EducationRetrievalRequest,
    EvidenceBundleManifest,
    KnowledgeAnalysisProposalReceipt,
    KnowledgeAnalysisRequest,
    KnowledgeAnalysisRequestV2,
    KnowledgeAnalysisResult,
    KnowledgeAnalysisResultV2,
    KnowledgeAnalysisReviewDecision,
    KnowledgeAnalysisWorkerProposal,
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


def _analysis_source_v2() -> dict[str, object]:
    return {
        "source_kind": "CONTENT_INTAKE_FILE",
        "source_class": "TEXTBOOK",
        "intake_batch_id": "intake_" + "1" * 32,
        "source_file_id": "sourcefile_" + "1" * 32,
        "lifecycle_state": "ELIGIBLE",
        "artifact_member": {
            "artifact_id": "artifact_" + "1" * 32,
            "artifact_revision_id": "rev_" + "1" * 32,
            "member_path": "source/chapter-1.pdf",
            "materialized_path": "source/chapter-1.pdf",
            "sha256": "sha256:" + "1" * 64,
            "bytes": 1024,
            "schema_ref": None,
            "media_type": "application/pdf",
            "logical_name": "chapter-1.pdf",
        },
    }


def _analysis_request_v2() -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "knowledge-analysis-request/2.0",
        "predecessor_analysis_run_id": None,
        "analysis_request_id": "knowledgeanalysis_" + "2" * 32,
        "source": _analysis_source_v2(),
        "execution_preset_id": "execpreset_" + "2" * 32,
        "execution_preset_revision_id": "execpresetrev_" + "2" * 32,
        "execution_preset_sha256": "sha256:" + "2" * 64,
        "worker_proposal_schema_ref": (
            "eom://schemas/knowledge/knowledge-analysis-worker-proposal/1.0"
        ),
        "accepted_result_schema_ref": "eom://schemas/knowledge/knowledge-analysis-result/2.0",
        "prior_graph_snapshot": None,
        "requested_outputs": [
            "NORMALIZED_MARKDOWN",
            "SOURCE_ANCHORS",
            "NODES",
            "EDGES",
            "CLAIMS",
            "COMPONENT_OBSERVATIONS",
            "UNRESOLVED_AMBIGUITIES",
        ],
        "general_knowledge_mode": "DISABLED",
        "risk_policy_revision_id": "analysisriskrev_" + "2" * 32,
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
        "request_sha256": "sha256:" + "0" * 64,
    }
    value["request_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "request_sha256"}
    )
    return value


def _worker_proposal() -> dict[str, object]:
    return {
        "schema_version": "knowledge-analysis-worker-proposal/1.0",
        "analysis_request_id": "knowledgeanalysis_" + "2" * 32,
        "normalized_markdown": "# Density\n\nDensity relates mass and volume.\n",
        "anchors": [
            {
                "anchor_id": "anchor_section_1",
                "artifact_revision_id": "rev_" + "1" * 32,
                "member_path": "source/chapter-1.pdf",
                "anchor_kind": "SECTION",
                "locator": "section:1.2",
                "excerpt_sha256": "sha256:" + "3" * 64,
            }
        ],
        "nodes": [
            {
                "node_id": "knode_density",
                "node_type": "CONCEPT",
                "stable_key": "science.density",
                "label": "Density",
                "anchor_ids": ["anchor_section_1"],
            }
        ],
        "edges": [],
        "claims": [
            {
                "claim_id": "claim_density",
                "text": "Density relates mass and volume.",
                "confidence_milli": 980,
                "anchor_ids": ["anchor_section_1"],
                "general_knowledge_influenced": False,
            }
        ],
        "component_observations": [
            {
                "component_id": "component_paragraph_1",
                "kind": "PARAGRAPH",
                "anchor_id": "anchor_section_1",
                "confidence_milli": 990,
            }
        ],
        "unresolved_ambiguities": [],
        "general_knowledge_used": False,
        "completed_at": NOW.isoformat().replace("+00:00", "Z"),
    }


def _proposal_member(name: str, seed: str, media_type: str) -> dict[str, object]:
    return {
        "artifact_id": "artifact_" + "4" * 32,
        "artifact_revision_id": "rev_" + "4" * 32,
        "member_path": f"normalized/{name}",
        "sha256": "sha256:" + seed * 64,
        "bytes": 100,
        "schema_ref": f"eom://schemas/knowledge/{name}/1.0",
        "media_type": media_type,
        "logical_name": name,
    }


def _proposal_receipt() -> dict[str, object]:
    members = {
        "normalized_markdown": _proposal_member("document.md", "1", "text/markdown"),
        "anchors": _proposal_member("anchors.jsonl", "2", "application/x-ndjson"),
        "nodes": _proposal_member("nodes.jsonl", "3", "application/x-ndjson"),
        "edges": _proposal_member("edges.jsonl", "4", "application/x-ndjson"),
        "claims": _proposal_member("claims.jsonl", "5", "application/x-ndjson"),
        "component_observations": _proposal_member("components.jsonl", "6", "application/x-ndjson"),
        "unresolved_ambiguities": _proposal_member(
            "ambiguities.jsonl", "7", "application/x-ndjson"
        ),
    }
    descriptors = [
        {
            "member_path": item["member_path"],
            "sha256": item["sha256"],
            "bytes": item["bytes"],
            "schema_ref": item["schema_ref"],
            "media_type": item["media_type"],
        }
        for item in sorted(members.values(), key=lambda entry: str(entry["member_path"]))
    ]
    return {
        "schema_version": "knowledge-analysis-proposal-receipt/1.0",
        "analysis_request_id": "knowledgeanalysis_" + "2" * 32,
        "source": _analysis_source_v2(),
        "status": "PROPOSED_VALIDATED",
        "members": members,
        "counts": {
            "anchors": 1,
            "nodes": 1,
            "edges": 0,
            "claims": 1,
            "component_observations": 1,
            "ambiguities": 0,
        },
        "general_knowledge_used": False,
        "minimum_confidence_milli": 980,
        "blocking_ambiguity_count": 0,
        "content_set_sha256": content_sha256(descriptors),
        "completed_at": NOW.isoformat().replace("+00:00", "Z"),
    }


def _review_decision() -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "knowledge-analysis-review-decision/1.0",
        "decision_id": "analysisdecision_" + "5" * 32,
        "analysis_request_id": "knowledgeanalysis_" + "2" * 32,
        "proposal_artifact_id": "artifact_" + "4" * 32,
        "proposal_artifact_revision_id": "rev_" + "4" * 32,
        "proposal_content_set_sha256": _proposal_receipt()["content_set_sha256"],
        "risk_policy_revision_id": "analysisriskrev_" + "2" * 32,
        "decision": "APPROVE",
        "decided_by_operator_id": "operator_" + "5" * 32,
        "notes": "Reviewed source anchors and approved the bounded proposal.",
        "decided_at": NOW.isoformat().replace("+00:00", "Z"),
        "decision_sha256": "sha256:" + "0" * 64,
    }
    value["decision_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "decision_sha256"}
    )
    return value


def _analysis_result_v2() -> dict[str, object]:
    request = _analysis_request_v2()
    receipt = _proposal_receipt()
    value: dict[str, object] = {
        "schema_version": "knowledge-analysis-result/2.0",
        "analysis_result_id": "knowledgeanalysisresult_" + "6" * 32,
        "analysis_request_id": request["analysis_request_id"],
        "analysis_request_sha256": request["request_sha256"],
        "source": request["source"],
        "status": "ACCEPTED",
        "proposal_receipt": {
            "artifact_id": "artifact_" + "4" * 32,
            "artifact_revision_id": "rev_" + "4" * 32,
            "member_path": "normalized/proposal-receipt.json",
            "sha256": "sha256:" + "8" * 64,
            "bytes": 100,
            "schema_ref": "eom://schemas/knowledge/knowledge-analysis-proposal-receipt/1.0",
            "media_type": "application/json",
            "logical_name": "proposal-receipt.json",
        },
        "proposal_content_set_sha256": receipt["content_set_sha256"],
        "risk_policy_revision_id": request["risk_policy_revision_id"],
        "acceptance_mode": "AUTO_POLICY",
        "review_decision": None,
        "counts": receipt["counts"],
        "general_knowledge_used": False,
        "minimum_confidence_milli": 980,
        "blocking_ambiguity_count": 0,
        "accepted_at": NOW.isoformat().replace("+00:00", "Z"),
        "result_sha256": "sha256:" + "0" * 64,
    }
    value["result_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "result_sha256"}
    )
    return value


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


@pytest.mark.parametrize(
    ("name", "value", "model"),
    [
        ("knowledge-analysis-request-v2", _analysis_request_v2(), KnowledgeAnalysisRequestV2),
        (
            "knowledge-analysis-worker-proposal",
            _worker_proposal(),
            KnowledgeAnalysisWorkerProposal,
        ),
        (
            "knowledge-analysis-proposal-receipt",
            _proposal_receipt(),
            KnowledgeAnalysisProposalReceipt,
        ),
        (
            "knowledge-analysis-review-decision",
            _review_decision(),
            KnowledgeAnalysisReviewDecision,
        ),
        ("knowledge-analysis-result-v2", _analysis_result_v2(), KnowledgeAnalysisResultV2),
    ],
)
def test_knowledge_analysis_v2_contracts_validate_at_both_boundaries(
    name: str, value: dict[str, object], model: type[object]
) -> None:
    validate_contract(name, value)
    assert model.model_validate(value)


def test_knowledge_analysis_v2_request_is_hashed_and_source_discriminated() -> None:
    stale_hash = _analysis_request_v2()
    stale_hash["general_knowledge_mode"] = "AUXILIARY_UNATTRIBUTED"
    with pytest.raises(PydanticValidationError, match="request hash does not match"):
        KnowledgeAnalysisRequestV2.model_validate(stale_hash)

    mixed_source = _analysis_request_v2()
    source = mixed_source["source"]
    assert isinstance(source, dict)
    source["source_kind"] = "APPROVED_ITEM_REVISION"
    with pytest.raises(ValidationError):
        validate_contract("knowledge-analysis-request-v2", mixed_source)
    with pytest.raises(PydanticValidationError):
        KnowledgeAnalysisRequestV2.model_validate(mixed_source)


def test_knowledge_analysis_worker_proposal_closes_references_and_provenance() -> None:
    dangling = _worker_proposal()
    components = dangling["component_observations"]
    assert isinstance(components, list)
    components[0]["anchor_id"] = "anchor_missing"
    with pytest.raises(PydanticValidationError, match="anchor pointer does not resolve"):
        KnowledgeAnalysisWorkerProposal.model_validate(dangling)

    unattributed = _worker_proposal()
    claims = unattributed["claims"]
    assert isinstance(claims, list)
    claims[0]["general_knowledge_influenced"] = True
    with pytest.raises(PydanticValidationError, match="general_knowledge_used"):
        KnowledgeAnalysisWorkerProposal.model_validate(unattributed)


def test_knowledge_analysis_receipt_is_one_pointer_oriented_artifact() -> None:
    mixed = _proposal_receipt()
    members = mixed["members"]
    assert isinstance(members, dict)
    nodes = members["nodes"]
    assert isinstance(nodes, dict)
    nodes["artifact_revision_id"] = "rev_" + "f" * 32
    with pytest.raises(PydanticValidationError, match="one Artifact Revision"):
        KnowledgeAnalysisProposalReceipt.model_validate(mixed)

    stale = _proposal_receipt()
    stale["content_set_sha256"] = "sha256:" + "f" * 64
    with pytest.raises(PydanticValidationError, match="content-set hash"):
        KnowledgeAnalysisProposalReceipt.model_validate(stale)


def test_knowledge_analysis_acceptance_requires_review_pointer_only_for_human_mode() -> None:
    missing_review = _analysis_result_v2()
    missing_review["acceptance_mode"] = "HUMAN_APPROVED"
    with pytest.raises(PydanticValidationError, match="requires one review decision"):
        KnowledgeAnalysisResultV2.model_validate(missing_review)

    stale_hash = _analysis_result_v2()
    stale_hash["blocking_ambiguity_count"] = 1
    with pytest.raises(PydanticValidationError, match="result hash does not match"):
        KnowledgeAnalysisResultV2.model_validate(stale_hash)
