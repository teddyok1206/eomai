from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from eom_catalog_contracts import (
    KNOWLEDGE_EDGE_ENDPOINT_COMPATIBILITY,
    CatalogApplicationResponse,
    EducationalDocumentKnowledgeSourceV3,
    EducationalDocumentKnowledgeSourceV4,
    EvidenceBundleManifestV3,
    EvidenceBundleManifestV4,
    EvidenceBundlePublicationResultV3,
    EvidenceBundlePublicationResultV4,
    KnowledgeAnalysisProposalReceiptV2,
    KnowledgeAnalysisProposalReceiptV3,
    KnowledgeAnalysisProposalReceiptV4,
    KnowledgeAnalysisRequestV2,
    KnowledgeAnalysisRequestV3,
    KnowledgeAnalysisRequestV4,
    KnowledgeAnalysisRequestV5,
    KnowledgeAnalysisResultV3,
    KnowledgeAnalysisResultV4,
    KnowledgeAnalysisResultV5,
    KnowledgeAnalysisWorkerProposal,
    KnowledgeAnalysisWorkerProposalV2,
    KnowledgeAnalysisWorkerProposalV3,
    KnowledgeAnalysisWorkerProposalV4,
    KnowledgeProposalCountsV2,
    load_schema,
    validate_contract,
)
from eom_identifiers import content_sha256
from eom_orchestrator.errors import PlatformError
from eom_orchestrator.knowledge_analysis_artifact import stage_knowledge_analysis_proposal
from eom_workflow.models import ArtifactSpec, KnowledgeAnalysisWorkerRequest, RoleWorkerInput
from eom_workflow.schemas import constrained_result_schema, role_schema_bundle_hash
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 8, 25, tzinfo=UTC).isoformat().replace("+00:00", "Z")


def document_source() -> dict[str, object]:
    analysis_artifact = "artifact_" + "2" * 32
    analysis_revision = "rev_" + "2" * 32
    members = [
        {
            "member_kind": "INDEX",
            "physical_page": None,
            "artifact_id": analysis_artifact,
            "artifact_revision_id": analysis_revision,
            "member_path": "analysis/index.md",
            "materialized_path": "source/document/index.md",
            "sha256": "sha256:" + "a" * 64,
            "bytes": 10,
            "schema_ref": "eom://schemas/educational-document/extracted-markdown/1.0",
            "media_type": "text/markdown; charset=utf-8",
            "logical_name": "index.md",
        },
        *(
            {
                "member_kind": "PAGE",
                "physical_page": page,
                "artifact_id": analysis_artifact,
                "artifact_revision_id": analysis_revision,
                "member_path": f"analysis/pages/page-{page:06d}.md",
                "materialized_path": f"source/document/pages/page-{page:06d}.md",
                "sha256": "sha256:" + str(page) * 64,
                "bytes": page * 10,
                "schema_ref": "eom://schemas/educational-document/extracted-markdown/1.0",
                "media_type": "text/markdown; charset=utf-8",
                "logical_name": f"page-{page:06d}.md",
            }
            for page in (1, 2)
        ),
    ]
    return {
        "source_kind": "DOCUMENT_REVISION",
        "source_class": "TEXTBOOK",
        "document_id": "edudoc_" + "1" * 32,
        "document_revision_id": "edudocrev_" + "1" * 32,
        "lifecycle_state": "APPROVED",
        "artifact_member": {
            "artifact_id": "artifact_" + "1" * 32,
            "artifact_revision_id": "rev_" + "1" * 32,
            "member_path": "source/original.pdf",
            "sha256": "sha256:" + "1" * 64,
            "bytes": 1024,
            "schema_ref": "eom://schemas/educational-document/pdf-source/1.0",
            "media_type": "application/pdf",
            "logical_name": "original.pdf",
        },
        "analysis_bundle_manifest": {
            "artifact_id": analysis_artifact,
            "artifact_revision_id": analysis_revision,
            "member_path": "analysis/manifest.json",
            "sha256": "sha256:" + "2" * 64,
            "schema_ref": ("eom://schemas/legacy-knowledge/textbook-analysis-bundle-manifest/1.0"),
            "media_type": "application/json",
            "logical_name": "manifest.json",
        },
        "rights_attestation": {
            "artifact_id": "artifact_" + "3" * 32,
            "artifact_revision_id": "rev_" + "3" * 32,
            "member_path": "rights/attestation.json",
            "sha256": "sha256:" + "3" * 64,
            "schema_ref": "eom://schemas/educational-document/rights-attestation/1.0",
            "media_type": "application/json",
            "logical_name": "attestation.json",
        },
        "first_physical_page": 1,
        "last_physical_page": 2,
        "curriculum_unit_keys": ["1-(1)"],
        "materialization_members": members,
        "materialization_bytes": 40,
    }


def multimodal_document_source() -> dict[str, object]:
    value = deepcopy(document_source())
    members = value["materialization_members"]
    assert isinstance(members, list)
    multimodal_members: list[dict[str, object]] = []
    for member in members:
        assert isinstance(member, dict)
        converted = deepcopy(member)
        converted["member_kind"] = "INDEX" if member["member_kind"] == "INDEX" else "PAGE_TEXT"
        converted["width_pixels"] = None
        converted["height_pixels"] = None
        multimodal_members.append(converted)
    for page in (1, 2):
        multimodal_members.append(
            {
                "member_kind": "PAGE_IMAGE",
                "physical_page": page,
                "artifact_id": "artifact_" + "2" * 32,
                "artifact_revision_id": "rev_" + "2" * 32,
                "member_path": f"analysis/images/page-{page:06d}.png",
                "materialized_path": f"source/document/images/page-{page:06d}.png",
                "sha256": "sha256:" + str(page + 2) * 64,
                "bytes": 100,
                "schema_ref": "eom://schemas/educational-document/page-image/1.0",
                "media_type": "image/png",
                "logical_name": f"page-{page:06d}.png",
                "width_pixels": 1600,
                "height_pixels": 2200,
            }
        )
    value["materialization_members"] = multimodal_members
    value["materialization_bytes"] = 240
    value["page_image_count"] = 2
    dependency = value["analysis_bundle_manifest"]
    assert isinstance(dependency, dict)
    dependency["schema_ref"] = (
        "eom://schemas/legacy-knowledge/textbook-analysis-bundle-manifest/2.0"
    )
    return value


def request_v3() -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "knowledge-analysis-request/3.0",
        "analysis_request_id": "knowledgeanalysis_" + "4" * 32,
        "source": document_source(),
        "execution_preset_id": "execpreset_" + "4" * 32,
        "execution_preset_revision_id": "execpresetrev_" + "4" * 32,
        "execution_preset_sha256": "sha256:" + "4" * 64,
        "worker_proposal_schema_ref": (
            "eom://schemas/knowledge/knowledge-analysis-worker-proposal/1.0"
        ),
        "accepted_result_schema_ref": "eom://schemas/knowledge/knowledge-analysis-result/3.0",
        "predecessor_analysis_run_id": None,
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
        "risk_policy_revision_id": "analysisriskrev_" + "4" * 32,
        "created_at": NOW,
    }
    value["request_sha256"] = content_sha256(value)
    return value


def proposal_v3(request: KnowledgeAnalysisRequestV3) -> dict[str, object]:
    return {
        "schema_version": "knowledge-analysis-worker-proposal/1.0",
        "analysis_request_id": request.analysis_request_id,
        "normalized_markdown": "# 시간과 공간\n",
        "anchors": [
            {
                "anchor_id": "anchor_page_1",
                "artifact_revision_id": request.source.artifact_member.artifact_revision_id,
                "member_path": request.source.artifact_member.member_path,
                "anchor_kind": "PAGE",
                "locator": "physical_page=1;paragraph=1",
                "excerpt_sha256": "sha256:" + "9" * 64,
            }
        ],
        "nodes": [
            {
                "node_id": "knode_spacetime",
                "node_type": "CONCEPT",
                "stable_key": "science.spacetime",
                "label": "시간과 공간",
                "anchor_ids": ["anchor_page_1"],
            }
        ],
        "edges": [],
        "claims": [],
        "component_observations": [],
        "unresolved_ambiguities": [],
        "general_knowledge_used": False,
        "completed_at": NOW,
    }


def request_v4() -> dict[str, object]:
    value = request_v3()
    value["schema_version"] = "knowledge-analysis-request/4.0"
    value["worker_proposal_schema_ref"] = (
        "eom://schemas/knowledge/knowledge-analysis-worker-proposal/2.0"
    )
    value["accepted_result_schema_ref"] = "eom://schemas/knowledge/knowledge-analysis-result/4.0"
    value["request_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "request_sha256"}
    )
    return value


def proposal_v4(request: KnowledgeAnalysisRequestV4) -> dict[str, object]:
    value = proposal_v3(KnowledgeAnalysisRequestV3.model_validate(request_v3()))
    value["schema_version"] = "knowledge-analysis-worker-proposal/2.0"
    value["analysis_request_id"] = request.analysis_request_id
    value["nodes"] = [
        {
            "node_id": "knode_pattern",
            "node_type": "ASSESSMENT_PATTERN",
            "stable_key": "assessment.pattern.data_interpretation",
            "label": "자료 해석 유형",
            "anchor_ids": ["anchor_page_1"],
        },
        {
            "node_id": "knode_concept",
            "node_type": "CONCEPT",
            "stable_key": "science.spacetime",
            "label": "시간과 공간",
            "anchor_ids": ["anchor_page_1"],
        },
    ]
    value["edges"] = [
        {
            "edge_id": "kedge_pattern_requires_concept",
            "relationship": {
                "edge_type": "REQUIRES_CONCEPT",
                "from_node_type": "ASSESSMENT_PATTERN",
                "to_node_type": "CONCEPT",
            },
            "from_node_id": "knode_pattern",
            "to_node_id": "knode_concept",
            "confidence_milli": 900,
            "anchor_ids": ["anchor_page_1"],
        }
    ]
    return value


def request_v5() -> dict[str, object]:
    value = request_v4()
    value["schema_version"] = "knowledge-analysis-request/5.0"
    value["worker_proposal_schema_ref"] = (
        "eom://schemas/knowledge/knowledge-analysis-worker-proposal/3.0"
    )
    value["accepted_result_schema_ref"] = "eom://schemas/knowledge/knowledge-analysis-result/5.0"
    value["request_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "request_sha256"}
    )
    return value


def proposal_v5(request: KnowledgeAnalysisRequestV5) -> dict[str, object]:
    historical_request = KnowledgeAnalysisRequestV4.model_validate(request_v4())
    value = proposal_v4(historical_request)
    value["schema_version"] = "knowledge-analysis-worker-proposal/3.0"
    value["analysis_request_id"] = request.analysis_request_id
    value["claims"] = [
        {
            "claim_id": "claim_spacetime_scope",
            "text": "시간과 공간의 범위가 제시된다.",
            "confidence_milli": 880,
            "anchor_ids": ["anchor_page_1"],
            "general_knowledge_influenced": False,
        }
    ]
    value["component_observations"] = [
        {
            "component_id": "component_paragraph_1",
            "kind": "PARAGRAPH",
            "anchor_id": "anchor_page_1",
            "confidence_milli": 850,
        }
    ]
    value["unresolved_ambiguities"] = [
        {
            "category_code": "SOURCE_SCOPE_UNCLEAR",
            "description": "첫 번째 범위 경계가 명시되지 않았다.",
            "blocking": False,
            "anchor_ids": ["anchor_page_1"],
        },
        {
            "category_code": "SOURCE_SCOPE_UNCLEAR",
            "description": "두 번째 범위 경계가 명시되지 않았다.",
            "blocking": False,
            "anchor_ids": ["anchor_page_1"],
        },
    ]
    return value


def test_multimodal_proposal_accepts_honest_empty_content_without_relaxing_delivery() -> None:
    value = {
        "schema_version": "knowledge-analysis-worker-proposal/4.0",
        "analysis_request_id": "knowledgeanalysis_" + "4" * 32,
        "normalized_markdown": (
            "# 분석 결과\n\n선택 범위에서 그래프화할 수 있는 관련 과학 내용을 확인하지 못했다.\n"
        ),
        "anchors": [],
        "nodes": [],
        "edges": [],
        "claims": [],
        "component_observations": [],
        "page_image_observations": [
            {
                "physical_page": page,
                "image_sha256": "sha256:" + str(page) * 64,
                "observation_state": state,
                "anchor_ids": [],
            }
            for page, state in ((1, "NO_RELEVANT_CONTENT"), (2, "UNCLEAR"))
        ],
        "unresolved_ambiguities": [],
        "general_knowledge_used": False,
        "completed_at": NOW,
    }

    validate_contract("knowledge-analysis-worker-proposal-v4", value)
    proposal = KnowledgeAnalysisWorkerProposalV4.model_validate(value)
    assert proposal.anchors == ()
    assert proposal.nodes == ()
    assert (
        KnowledgeProposalCountsV2(
            anchors=0,
            nodes=0,
            edges=0,
            claims=0,
            component_observations=0,
            page_image_observations=2,
            ambiguities=0,
        ).page_image_observations
        == 2
    )

    incomplete = deepcopy(value)
    incomplete["page_image_observations"] = []
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("knowledge-analysis-worker-proposal-v4", incomplete)
    with pytest.raises(PydanticValidationError):
        KnowledgeAnalysisWorkerProposalV4.model_validate(incomplete)


def _member(name: str, seed: str, media_type: str) -> dict[str, object]:
    return {
        "artifact_id": "artifact_" + "5" * 32,
        "artifact_revision_id": "rev_" + "5" * 32,
        "member_path": f"normalized/{name}",
        "sha256": "sha256:" + seed * 64,
        "bytes": 100,
        "schema_ref": f"eom://schemas/knowledge/{name}/1.0",
        "media_type": media_type,
        "logical_name": name,
    }


def receipt_v2() -> dict[str, object]:
    members = {
        "normalized_markdown": _member("document.md", "1", "text/markdown"),
        "anchors": _member("anchors.jsonl", "2", "application/x-ndjson"),
        "nodes": _member("nodes.jsonl", "3", "application/x-ndjson"),
        "edges": _member("edges.jsonl", "4", "application/x-ndjson"),
        "claims": _member("claims.jsonl", "5", "application/x-ndjson"),
        "component_observations": _member("components.jsonl", "6", "application/x-ndjson"),
        "unresolved_ambiguities": _member("ambiguities.jsonl", "7", "application/x-ndjson"),
    }
    descriptors = [
        {
            "member_path": member["member_path"],
            "sha256": member["sha256"],
            "bytes": member["bytes"],
            "schema_ref": member["schema_ref"],
            "media_type": member["media_type"],
        }
        for member in sorted(members.values(), key=lambda item: str(item["member_path"]))
    ]
    return {
        "schema_version": "knowledge-analysis-proposal-receipt/2.0",
        "analysis_request_id": request_v3()["analysis_request_id"],
        "source": document_source(),
        "status": "PROPOSED_VALIDATED",
        "members": members,
        "counts": {
            "anchors": 1,
            "nodes": 1,
            "edges": 0,
            "claims": 0,
            "component_observations": 0,
            "ambiguities": 0,
        },
        "general_knowledge_used": False,
        "minimum_confidence_milli": None,
        "blocking_ambiguity_count": 0,
        "content_set_sha256": content_sha256(descriptors),
        "completed_at": NOW,
    }


def result_v3() -> dict[str, object]:
    request = request_v3()
    receipt = receipt_v2()
    value: dict[str, object] = {
        "schema_version": "knowledge-analysis-result/3.0",
        "analysis_result_id": "knowledgeanalysisresult_" + "6" * 32,
        "analysis_request_id": request["analysis_request_id"],
        "analysis_request_sha256": request["request_sha256"],
        "source": request["source"],
        "status": "ACCEPTED",
        "proposal_receipt": {
            **_member("proposal-receipt.json", "8", "application/json"),
            "schema_ref": "eom://schemas/knowledge/knowledge-analysis-proposal-receipt/2.0",
        },
        "proposal_content_set_sha256": receipt["content_set_sha256"],
        "risk_policy_revision_id": request["risk_policy_revision_id"],
        "acceptance_mode": "AUTO_POLICY",
        "review_decision": None,
        "counts": receipt["counts"],
        "general_knowledge_used": False,
        "minimum_confidence_milli": None,
        "blocking_ambiguity_count": 0,
        "accepted_at": NOW,
    }
    value["result_sha256"] = content_sha256(value)
    return value


def receipt_v3() -> dict[str, object]:
    value = receipt_v2()
    value["schema_version"] = "knowledge-analysis-proposal-receipt/3.0"
    members = value["members"]
    assert isinstance(members, dict)
    schema_refs = {
        "normalized_markdown": "eom://schemas/knowledge/normalized-markdown/1.0",
        "anchors": "eom://schemas/knowledge/source-anchor/2.0",
        "nodes": "eom://schemas/knowledge/proposed-node/2.0",
        "edges": "eom://schemas/knowledge/proposed-edge/3.0",
        "claims": "eom://schemas/knowledge/proposed-claim/2.0",
        "component_observations": "eom://schemas/knowledge/component-observation/2.0",
        "unresolved_ambiguities": "eom://schemas/knowledge/ambiguity/2.0",
    }
    for name, schema_ref in schema_refs.items():
        member = members[name]
        assert isinstance(member, dict)
        member["schema_ref"] = schema_ref
    descriptors = [
        {
            "member_path": member["member_path"],
            "sha256": member["sha256"],
            "bytes": member["bytes"],
            "schema_ref": member["schema_ref"],
            "media_type": member["media_type"],
        }
        for member in sorted(members.values(), key=lambda item: str(item["member_path"]))
        if isinstance(member, dict)
    ]
    value["content_set_sha256"] = content_sha256(descriptors)
    return value


def result_v4() -> dict[str, object]:
    request = request_v4()
    receipt = receipt_v3()
    value = result_v3()
    value["schema_version"] = "knowledge-analysis-result/4.0"
    value["analysis_request_id"] = request["analysis_request_id"]
    value["analysis_request_sha256"] = request["request_sha256"]
    value["source"] = request["source"]
    pointer = value["proposal_receipt"]
    assert isinstance(pointer, dict)
    pointer["schema_ref"] = "eom://schemas/knowledge/knowledge-analysis-proposal-receipt/3.0"
    value["proposal_content_set_sha256"] = receipt["content_set_sha256"]
    value["result_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "result_sha256"}
    )
    return value


def receipt_v4() -> dict[str, object]:
    value = receipt_v3()
    value["schema_version"] = "knowledge-analysis-proposal-receipt/4.0"
    members = value["members"]
    assert isinstance(members, dict)
    ambiguity = members["unresolved_ambiguities"]
    assert isinstance(ambiguity, dict)
    ambiguity["schema_ref"] = "eom://schemas/knowledge/ambiguity/3.0"
    descriptors = [
        {
            "member_path": member["member_path"],
            "sha256": member["sha256"],
            "bytes": member["bytes"],
            "schema_ref": member["schema_ref"],
            "media_type": member["media_type"],
        }
        for member in sorted(members.values(), key=lambda item: str(item["member_path"]))
        if isinstance(member, dict)
    ]
    value["content_set_sha256"] = content_sha256(descriptors)
    return value


def result_v5() -> dict[str, object]:
    request = request_v5()
    receipt = receipt_v4()
    value = result_v4()
    value["schema_version"] = "knowledge-analysis-result/5.0"
    value["analysis_request_id"] = request["analysis_request_id"]
    value["analysis_request_sha256"] = request["request_sha256"]
    value["source"] = request["source"]
    pointer = value["proposal_receipt"]
    assert isinstance(pointer, dict)
    pointer["schema_ref"] = "eom://schemas/knowledge/knowledge-analysis-proposal-receipt/4.0"
    value["proposal_content_set_sha256"] = receipt["content_set_sha256"]
    value["result_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "result_sha256"}
    )
    return value


@pytest.mark.parametrize(
    ("schema", "value", "model"),
    [
        ("knowledge-analysis-request-v3", request_v3(), KnowledgeAnalysisRequestV3),
        ("knowledge-analysis-request-v4", request_v4(), KnowledgeAnalysisRequestV4),
        ("knowledge-analysis-request-v5", request_v5(), KnowledgeAnalysisRequestV5),
        (
            "knowledge-analysis-proposal-receipt-v2",
            receipt_v2(),
            KnowledgeAnalysisProposalReceiptV2,
        ),
        (
            "knowledge-analysis-proposal-receipt-v3",
            receipt_v3(),
            KnowledgeAnalysisProposalReceiptV3,
        ),
        (
            "knowledge-analysis-proposal-receipt-v4",
            receipt_v4(),
            KnowledgeAnalysisProposalReceiptV4,
        ),
        ("knowledge-analysis-result-v3", result_v3(), KnowledgeAnalysisResultV3),
        ("knowledge-analysis-result-v4", result_v4(), KnowledgeAnalysisResultV4),
        ("knowledge-analysis-result-v5", result_v5(), KnowledgeAnalysisResultV5),
    ],
)
def test_document_analysis_contracts_validate_at_schema_and_typed_boundaries(
    schema: str, value: dict[str, object], model: type[object]
) -> None:
    validate_contract(schema, value)
    assert model.model_validate(value)


def test_document_materialization_is_ordered_bounded_and_one_artifact() -> None:
    source = document_source()
    assert EducationalDocumentKnowledgeSourceV3.model_validate(source).materialization_bytes == 40

    reversed_members = deepcopy(source)
    members = reversed_members["materialization_members"]
    assert isinstance(members, list)
    members.reverse()
    with pytest.raises(PydanticValidationError, match="one index and every page"):
        EducationalDocumentKnowledgeSourceV3.model_validate(reversed_members)

    mixed = deepcopy(source)
    members = mixed["materialization_members"]
    assert isinstance(members, list)
    member = members[1]
    assert isinstance(member, dict)
    member["artifact_revision_id"] = "rev_" + "f" * 32
    with pytest.raises(PydanticValidationError, match="mixed or duplicated"):
        EducationalDocumentKnowledgeSourceV3.model_validate(mixed)


def test_document_source_is_preserved_in_v3_evidence_manifest_and_publication() -> None:
    graph_pointer = {
        "graph_id": "graph_" + "7" * 32,
        "graph_snapshot_revision_id": "graphrev_" + "7" * 32,
        "manifest_artifact": {
            "artifact_id": "artifact_" + "7" * 32,
            "artifact_revision_id": "rev_" + "7" * 32,
            "sha256": "sha256:" + "7" * 64,
            "schema_ref": "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/3.0",
            "media_type": "application/json",
            "logical_name": "manifest.json",
            "member_path": "projections/manifest.json",
        },
        "manifest_sha256": "sha256:" + "7" * 64,
    }
    context_pointer = {
        "artifact_id": "artifact_" + "8" * 32,
        "artifact_revision_id": "rev_" + "8" * 32,
        "sha256": "sha256:" + "8" * 64,
        "schema_ref": "eom://schemas/knowledge/evidence-bundle-context/1.0",
        "media_type": "text/markdown",
        "logical_name": "context.md",
        "member_path": "evidence/context.md",
    }
    budget = {
        "document_count": 1,
        "item_revision_count": 0,
        "graph_node_count": 1,
        "claim_count": 0,
        "estimated_context_tokens": 1000,
    }
    manifest_value: dict[str, object] = {
        "schema_version": "evidence-bundle-manifest/3.0",
        "evidence_bundle_id": "evidence_" + "9" * 32,
        "evidence_bundle_revision_id": "evidencerev_" + "9" * 32,
        "revision_number": 1,
        "retrieval_request_id": "retrieval_" + "9" * 32,
        "retrieval_request_sha256": "sha256:" + "9" * 64,
        "graph_snapshot": graph_pointer,
        "access_policy_revision_id": "accessrev_" + "9" * 32,
        "access_policy_sha256": "sha256:" + "9" * 64,
        "requester_permissions_sha256": "sha256:" + "9" * 64,
        "materials": {"context_markdown": context_pointer},
        "entries": [
            {
                "evidence_id": "evidenceitem_" + "9" * 32,
                "evidence_kind": "DOCUMENT",
                "use": "GROUNDING",
                "source": document_source(),
                "graph_node_ids": ["knode_document"],
                "anchor_ids": ["anchor_document"],
                "relevance_milli": 1000,
                "answer_bearing": False,
            }
        ],
        "budget": budget,
        "created_at": NOW,
    }
    manifest_value["manifest_sha256"] = content_sha256(manifest_value)
    validate_contract("evidence-bundle-manifest-v3", manifest_value)
    manifest = EvidenceBundleManifestV3.model_validate(manifest_value)
    assert manifest.entries[0].source.document_revision_id == "edudocrev_" + "1" * 32

    result_value: dict[str, object] = {
        "schema_version": "evidence-bundle-publication-result/3.0",
        "evidence_bundle_id": manifest.evidence_bundle_id,
        "evidence_bundle_revision_id": manifest.evidence_bundle_revision_id,
        "revision_number": 1,
        "state": "PUBLISHED",
        "retrieval_request_id": manifest.retrieval_request_id,
        "retrieval_request_sha256": manifest.retrieval_request_sha256,
        "graph_snapshot": graph_pointer,
        "access_policy_revision_id": manifest.access_policy_revision_id,
        "access_policy_sha256": manifest.access_policy_sha256,
        "requester_permissions_sha256": manifest.requester_permissions_sha256,
        "manifest_artifact": {
            "artifact_id": "artifact_" + "a" * 32,
            "artifact_revision_id": "rev_" + "a" * 32,
            "sha256": manifest.manifest_sha256,
            "schema_ref": "eom://schemas/knowledge/evidence-bundle-manifest/3.0",
            "media_type": "application/json",
            "logical_name": "manifest.json",
            "member_path": "evidence/manifest.json",
        },
        "manifest_sha256": manifest.manifest_sha256,
        "context_artifact": context_pointer,
        "budget": budget,
        "published_at": NOW,
    }
    result_value["result_sha256"] = content_sha256(result_value)
    validate_contract("evidence-bundle-publication-result-v3", result_value)
    result = EvidenceBundlePublicationResultV3.model_validate(result_value)
    assert result.state == "PUBLISHED"
    response = CatalogApplicationResponse(
        status="OK",
        operation="CREATE_ITEM_PRODUCTION_EVIDENCE",
        item_production_evidence=result,
    ).model_dump(mode="json", exclude_none=True)
    validate_contract("catalog-application-response-v6", response)


def test_multimodal_document_source_is_preserved_in_v4_evidence_contracts() -> None:
    source = multimodal_document_source()
    assert EducationalDocumentKnowledgeSourceV4.model_validate(source).page_image_count == 2
    graph_pointer = {
        "graph_id": "graph_" + "7" * 32,
        "graph_snapshot_revision_id": "graphrev_" + "7" * 32,
        "manifest_artifact": {
            "artifact_id": "artifact_" + "7" * 32,
            "artifact_revision_id": "rev_" + "7" * 32,
            "sha256": "sha256:" + "7" * 64,
            "schema_ref": "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/3.0",
            "media_type": "application/json",
            "logical_name": "manifest.json",
            "member_path": "projections/manifest.json",
        },
        "manifest_sha256": "sha256:" + "7" * 64,
    }
    context_pointer = {
        "artifact_id": "artifact_" + "8" * 32,
        "artifact_revision_id": "rev_" + "8" * 32,
        "sha256": "sha256:" + "8" * 64,
        "schema_ref": "eom://schemas/knowledge/evidence-bundle-context/1.0",
        "media_type": "text/markdown",
        "logical_name": "context.md",
        "member_path": "evidence/context.md",
    }
    budget = {
        "document_count": 1,
        "item_revision_count": 0,
        "graph_node_count": 1,
        "claim_count": 0,
        "estimated_context_tokens": 1000,
    }
    manifest_value: dict[str, object] = {
        "schema_version": "evidence-bundle-manifest/4.0",
        "evidence_bundle_id": "evidence_" + "9" * 32,
        "evidence_bundle_revision_id": "evidencerev_" + "9" * 32,
        "revision_number": 1,
        "retrieval_request_id": "retrieval_" + "9" * 32,
        "retrieval_request_sha256": "sha256:" + "9" * 64,
        "graph_snapshot": graph_pointer,
        "access_policy_revision_id": "accessrev_" + "9" * 32,
        "access_policy_sha256": "sha256:" + "9" * 64,
        "requester_permissions_sha256": "sha256:" + "9" * 64,
        "materials": {"context_markdown": context_pointer},
        "entries": [
            {
                "evidence_id": "evidenceitem_" + "9" * 32,
                "evidence_kind": "DOCUMENT",
                "use": "GROUNDING",
                "source": source,
                "graph_node_ids": ["knode_document"],
                "anchor_ids": ["anchor_document"],
                "relevance_milli": 1000,
                "answer_bearing": False,
            }
        ],
        "budget": budget,
        "created_at": NOW,
    }
    manifest_value["manifest_sha256"] = content_sha256(manifest_value)
    validate_contract("evidence-bundle-manifest-v4", manifest_value)
    manifest = EvidenceBundleManifestV4.model_validate(manifest_value)
    assert manifest.entries[0].source.document_revision_id == "edudocrev_" + "1" * 32

    result_value: dict[str, object] = {
        "schema_version": "evidence-bundle-publication-result/4.0",
        "evidence_bundle_id": manifest.evidence_bundle_id,
        "evidence_bundle_revision_id": manifest.evidence_bundle_revision_id,
        "revision_number": 1,
        "state": "PUBLISHED",
        "retrieval_request_id": manifest.retrieval_request_id,
        "retrieval_request_sha256": manifest.retrieval_request_sha256,
        "graph_snapshot": graph_pointer,
        "access_policy_revision_id": manifest.access_policy_revision_id,
        "access_policy_sha256": manifest.access_policy_sha256,
        "requester_permissions_sha256": manifest.requester_permissions_sha256,
        "manifest_artifact": {
            "artifact_id": "artifact_" + "a" * 32,
            "artifact_revision_id": "rev_" + "a" * 32,
            "sha256": manifest.manifest_sha256,
            "schema_ref": "eom://schemas/knowledge/evidence-bundle-manifest/4.0",
            "media_type": "application/json",
            "logical_name": "manifest.json",
            "member_path": "evidence/manifest.json",
        },
        "manifest_sha256": manifest.manifest_sha256,
        "context_artifact": context_pointer,
        "budget": budget,
        "published_at": NOW,
    }
    result_value["result_sha256"] = content_sha256(result_value)
    validate_contract("evidence-bundle-publication-result-v4", result_value)
    result = EvidenceBundlePublicationResultV4.model_validate(result_value)
    response = CatalogApplicationResponse(
        status="OK",
        operation="CREATE_ITEM_PRODUCTION_EVIDENCE",
        item_production_evidence=result,
    ).model_dump(mode="json", exclude_none=True)
    validate_contract("catalog-application-response-v8", response)
    retrieval_response = CatalogApplicationResponse(
        status="OK",
        operation="CREATE_EVIDENCE_BUNDLE",
        evidence=result,
    ).model_dump(mode="json", exclude_none=True)
    validate_contract("catalog-application-response-v9", retrieval_response)


def test_v3_schema_family_rejects_historical_v2_source() -> None:
    historical = {
        "source_kind": "CONTENT_INTAKE_FILE",
        "source_class": "TEXTBOOK",
        "intake_batch_id": "intake_" + "1" * 32,
        "source_file_id": "sourcefile_" + "1" * 32,
        "lifecycle_state": "ELIGIBLE",
        "artifact_member": {
            "artifact_id": "artifact_" + "1" * 32,
            "artifact_revision_id": "rev_" + "1" * 32,
            "member_path": "source/chapter.pdf",
            "materialized_path": "source/chapter.pdf",
            "sha256": "sha256:" + "1" * 64,
            "bytes": 10,
            "schema_ref": None,
            "media_type": "application/pdf",
            "logical_name": "chapter.pdf",
        },
    }
    value = request_v3()
    value["source"] = historical
    value["request_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "request_sha256"}
    )
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("knowledge-analysis-request-v3", value)
    with pytest.raises(PydanticValidationError):
        KnowledgeAnalysisRequestV3.model_validate(value)


def test_v3_result_requires_v2_receipt_pointer() -> None:
    value = result_v3()
    pointer = value["proposal_receipt"]
    assert isinstance(pointer, dict)
    pointer["schema_ref"] = "eom://schemas/knowledge/knowledge-analysis-proposal-receipt/1.0"
    value["result_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "result_sha256"}
    )
    with pytest.raises(PydanticValidationError, match="receipt V2"):
        KnowledgeAnalysisResultV3.model_validate(value)


def test_document_proposal_anchor_is_closed_to_selected_physical_pages(tmp_path: Path) -> None:
    request = KnowledgeAnalysisRequestV3.model_validate(request_v3())
    proposal_value = proposal_v3(request)
    proposal = KnowledgeAnalysisWorkerProposal.model_validate(proposal_value)
    _, receipt = stage_knowledge_analysis_proposal(
        proposal=proposal,
        request=request,
        job_id="job_" + "a" * 32,
        logical_artifact_id="artifact_" + "b" * 32,
        revision_id="rev_" + "b" * 32,
        staging=tmp_path,
    )
    assert isinstance(receipt, KnowledgeAnalysisProposalReceiptV2)

    invalid = deepcopy(proposal_value)
    anchors = invalid["anchors"]
    assert isinstance(anchors, list)
    anchor = anchors[0]
    assert isinstance(anchor, dict)
    anchor["locator"] = "physical_page=3"
    with pytest.raises(PlatformError, match="outside the selected physical-page range"):
        stage_knowledge_analysis_proposal(
            proposal=KnowledgeAnalysisWorkerProposal.model_validate(invalid),
            request=request,
            job_id="job_" + "c" * 32,
            logical_artifact_id="artifact_" + "d" * 32,
            revision_id="rev_" + "d" * 32,
            staging=tmp_path / "invalid",
        )


def test_document_worker_schema_binds_original_source_and_selected_pages() -> None:
    request = KnowledgeAnalysisRequestV3.model_validate(request_v3())
    worker_input = RoleWorkerInput(
        job_id="job_" + "a" * 32,
        workflow_id="workflow_" + "b" * 32,
        step_run_id="steprun_" + "c" * 32,
        attempt=1,
        role="support",
        request=KnowledgeAnalysisWorkerRequest(analysis_request=request),
        upstream_artifacts=(),
        artifact=ArtifactSpec(
            logical_artifact_id="artifact_" + "d" * 32,
            revision_id="rev_" + "d" * 32,
        ),
    )
    schema = constrained_result_schema("knowledge-analysis-proposal-result@2.0", worker_input)
    proposal_schema = schema["$defs"]["KnowledgeAnalysisWorkerProposal"]
    anchor_ref = proposal_schema["properties"]["anchors"]["items"]["$ref"]
    anchor_schema = schema["$defs"][anchor_ref.removeprefix("#/$defs/")]
    anchor_properties = anchor_schema["properties"]
    assert anchor_properties["artifact_revision_id"]["const"] == (
        request.source.artifact_member.artifact_revision_id
    )
    assert anchor_properties["member_path"]["const"] == (request.source.artifact_member.member_path)
    assert anchor_properties["member_path"]["type"] == "string"
    assert anchor_properties["member_path"]["pattern"] == r"^[A-Za-z0-9._()가-힣/-]+$"
    assert "$ref" not in anchor_properties["member_path"]
    assert anchor_properties["locator"]["pattern"] == (r"^physical_page=(?:1|2)(?:;.{1,220})?$")

    result = {
        "schema_version": "1.0",
        "protocol_version": "workflow-role/1.5.0",
        "job_id": worker_input.job_id,
        "workflow_id": worker_input.workflow_id,
        "step_run_id": worker_input.step_run_id,
        "role": "support",
        "status": "ok",
        "artifact": worker_input.artifact.model_dump(mode="json"),
        "output": {"proposal": proposal_v3(request)},
        "completed_at": NOW,
    }
    assert list(Draft202012Validator(schema).iter_errors(result)) == []

    staged_pointer = deepcopy(result)
    staged_pointer["output"]["proposal"]["anchors"][0]["artifact_revision_id"] = (  # type: ignore[index]
        request.source.analysis_bundle_manifest.artifact_revision_id
    )
    staged_pointer["output"]["proposal"]["anchors"][0]["member_path"] = (  # type: ignore[index]
        "analysis/index.md"
    )
    pointer_errors = list(Draft202012Validator(schema).iter_errors(staged_pointer))
    assert {
        tuple(error.absolute_path) for error in pointer_errors if error.validator == "const"
    } == {
        ("output", "proposal", "anchors", 0, "artifact_revision_id"),
        ("output", "proposal", "anchors", 0, "member_path"),
    }

    outside_page = deepcopy(result)
    outside_page["output"]["proposal"]["anchors"][0]["locator"] = "physical_page=3"  # type: ignore[index]
    page_errors = list(Draft202012Validator(schema).iter_errors(outside_page))
    assert any(
        tuple(error.absolute_path) == ("output", "proposal", "anchors", 0, "locator")
        and error.validator == "pattern"
        for error in page_errors
    )


def test_endpoint_typed_proposal_rejects_the_v5_invalid_edge_before_acceptance() -> None:
    request = KnowledgeAnalysisRequestV4.model_validate(request_v4())
    valid = proposal_v4(request)
    validate_contract("knowledge-analysis-worker-proposal-v2", valid)
    assert KnowledgeAnalysisWorkerProposalV2.model_validate(valid).edges[
        0
    ].relationship.edge_type == ("REQUIRES_CONCEPT")

    invalid = deepcopy(valid)
    relationship = invalid["edges"][0]["relationship"]  # type: ignore[index]
    relationship["edge_type"] = "ASSESSES_CONCEPT"  # type: ignore[index]
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("knowledge-analysis-worker-proposal-v2", invalid)
    with pytest.raises(PydanticValidationError, match="endpoint types are incompatible"):
        KnowledgeAnalysisWorkerProposalV2.model_validate(invalid)


def test_endpoint_typed_proposal_resolves_declared_types_to_exact_node_ids() -> None:
    request = KnowledgeAnalysisRequestV4.model_validate(request_v4())
    mismatch = proposal_v4(request)
    relationship = mismatch["edges"][0]["relationship"]  # type: ignore[index]
    relationship["edge_type"] = "ASSESSES_CONCEPT"  # type: ignore[index]
    relationship["from_node_type"] = "ITEM_REVISION"  # type: ignore[index]
    validate_contract("knowledge-analysis-worker-proposal-v2", mismatch)
    with pytest.raises(PydanticValidationError, match="endpoint type does not match its node"):
        KnowledgeAnalysisWorkerProposalV2.model_validate(mismatch)


def test_integrity_proposal_allows_repeated_ambiguity_categories_not_duplicate_values() -> None:
    request = KnowledgeAnalysisRequestV5.model_validate(request_v5())
    valid = proposal_v5(request)
    validate_contract("knowledge-analysis-worker-proposal-v3", valid)
    parsed = KnowledgeAnalysisWorkerProposalV3.model_validate(valid)
    assert [item.category_code for item in parsed.unresolved_ambiguities] == [
        "SOURCE_SCOPE_UNCLEAR",
        "SOURCE_SCOPE_UNCLEAR",
    ]

    exact_duplicate = deepcopy(valid)
    exact_duplicate["unresolved_ambiguities"][1] = deepcopy(  # type: ignore[index]
        exact_duplicate["unresolved_ambiguities"][0]  # type: ignore[index]
    )
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("knowledge-analysis-worker-proposal-v3", exact_duplicate)
    with pytest.raises(PydanticValidationError, match="ambiguity observations must be unique"):
        KnowledgeAnalysisWorkerProposalV3.model_validate(exact_duplicate)


def test_historical_endpoint_typed_proposal_keeps_ambiguity_code_identity() -> None:
    request = KnowledgeAnalysisRequestV4.model_validate(request_v4())
    historical = proposal_v4(request)
    historical["unresolved_ambiguities"] = [
        {
            "code": "SOURCE_SCOPE_UNCLEAR",
            "description": "첫 번째 범위 경계가 명시되지 않았다.",
            "blocking": False,
            "anchor_ids": ["anchor_page_1"],
        },
        {
            "code": "SOURCE_SCOPE_UNCLEAR",
            "description": "두 번째 범위 경계가 명시되지 않았다.",
            "blocking": False,
            "anchor_ids": ["anchor_page_1"],
        },
    ]
    validate_contract("knowledge-analysis-worker-proposal-v2", historical)
    with pytest.raises(PydanticValidationError, match="ambiguity code identities must be unique"):
        KnowledgeAnalysisWorkerProposalV2.model_validate(historical)


def test_integrity_proposal_stages_v4_receipt_and_v3_ambiguity_members(tmp_path: Path) -> None:
    request = KnowledgeAnalysisRequestV5.model_validate(request_v5())
    proposal = KnowledgeAnalysisWorkerProposalV3.model_validate(proposal_v5(request))
    staged, receipt = stage_knowledge_analysis_proposal(
        proposal=proposal,
        request=request,
        job_id="job_" + "8" * 32,
        logical_artifact_id="artifact_" + "9" * 32,
        revision_id="rev_" + "9" * 32,
        staging=tmp_path,
    )

    assert isinstance(receipt, KnowledgeAnalysisProposalReceiptV4)
    assert receipt.counts.ambiguities == 2
    assert receipt.members.unresolved_ambiguities.schema_ref == (
        "eom://schemas/knowledge/ambiguity/3.0"
    )
    files = {member.relative_path: member.path for member in staged.files}
    assert staged.primary_hash == (
        "sha256:" + sha256(files["normalized/proposal-receipt.json"].read_bytes()).hexdigest()
    )
    ambiguity_lines = files["normalized/ambiguities.jsonl"].read_text(encoding="utf-8").splitlines()
    assert len(ambiguity_lines) == 2


@pytest.mark.parametrize(
    ("collection", "identity", "replacement"),
    [
        ("anchors", "anchor_id", "anchor_page_1"),
        ("nodes", "node_id", "knode_pattern"),
        ("nodes", "stable_key", "assessment.pattern.data_interpretation"),
        ("edges", "edge_id", "kedge_pattern_requires_concept"),
        ("claims", "claim_id", "claim_spacetime_scope"),
        ("component_observations", "component_id", "component_paragraph_1"),
    ],
)
def test_integrity_proposal_rejects_every_duplicate_explicit_identity(
    collection: str, identity: str, replacement: str
) -> None:
    request = KnowledgeAnalysisRequestV5.model_validate(request_v5())
    invalid = proposal_v5(request)
    values = invalid[collection]
    assert isinstance(values, list) and values
    duplicate = deepcopy(values[0])
    assert isinstance(duplicate, dict)
    duplicate[identity] = replacement
    if identity != "stable_key":
        if "stable_key" in duplicate:
            duplicate["stable_key"] = f"{duplicate['stable_key']}.duplicate"
        if "label" in duplicate:
            duplicate["label"] = f"{duplicate['label']} 별도 관측"
        if "confidence_milli" in duplicate:
            duplicate["confidence_milli"] = int(duplicate["confidence_milli"]) - 1
        if "locator" in duplicate:
            duplicate["locator"] = "physical_page=1;paragraph=2"
    else:
        duplicate["node_id"] = "knode_distinct_identity"
    values.append(duplicate)
    validate_contract("knowledge-analysis-worker-proposal-v3", invalid)
    with pytest.raises(PydanticValidationError, match="identities must be unique"):
        KnowledgeAnalysisWorkerProposalV3.model_validate(invalid)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("duplicate_local_anchor", "local anchor pointers must be unique"),
        ("dangling_anchor", "anchor pointer does not resolve"),
        ("dangling_edge", "edge endpoint does not resolve"),
        ("self_edge", "self-edges are not allowed"),
        ("endpoint_type", "endpoint type does not match its node"),
        ("general_knowledge", "claim provenance requires general_knowledge_used"),
    ],
)
def test_integrity_proposal_rejects_cross_record_failures(mutation: str, message: str) -> None:
    request = KnowledgeAnalysisRequestV5.model_validate(request_v5())
    invalid = proposal_v5(request)
    if mutation == "duplicate_local_anchor":
        invalid["claims"][0]["anchor_ids"] = ["anchor_page_1", "anchor_page_1"]  # type: ignore[index]
    elif mutation == "dangling_anchor":
        invalid["claims"][0]["anchor_ids"] = ["anchor_missing"]  # type: ignore[index]
    elif mutation == "dangling_edge":
        invalid["edges"][0]["to_node_id"] = "knode_missing"  # type: ignore[index]
    elif mutation == "self_edge":
        invalid["edges"][0]["to_node_id"] = "knode_pattern"  # type: ignore[index]
    elif mutation == "endpoint_type":
        invalid["edges"][0]["relationship"]["from_node_type"] = "ITEM_REVISION"  # type: ignore[index]
    else:
        invalid["claims"][0]["general_knowledge_influenced"] = True  # type: ignore[index]
    with pytest.raises(PydanticValidationError, match=message):
        KnowledgeAnalysisWorkerProposalV3.model_validate(invalid)


def test_endpoint_contract_schema_exactly_matches_the_domain_compatibility_table() -> None:
    schema = load_schema("knowledge-analysis-worker-proposal-v2")
    alternatives = schema["$defs"]["edgeEndpointContract"]["anyOf"]
    projected: dict[str, set[tuple[str, str]]] = {}
    for alternative in alternatives:
        properties = alternative["properties"]
        edge_type = properties["edge_type"]["const"]
        projected[edge_type] = {
            (source, target)
            for source in properties["from_node_type"]["enum"]
            for target in properties["to_node_type"]["enum"]
        }
    canonical = {
        str(edge_type): {(str(source), str(target)) for source, target in pairs}
        for edge_type, pairs in KNOWLEDGE_EDGE_ENDPOINT_COMPATIBILITY.items()
    }
    assert projected == canonical


def test_v3_constrained_result_rejects_v5_invalid_edge_and_stages_v3_receipt(
    tmp_path: Path,
) -> None:
    request = KnowledgeAnalysisRequestV4.model_validate(request_v4())
    worker_input = RoleWorkerInput(
        protocol_version="workflow-role/1.6.0",
        job_id="job_" + "a" * 32,
        workflow_id="workflow_" + "b" * 32,
        step_run_id="steprun_" + "c" * 32,
        attempt=1,
        role="support",
        request=KnowledgeAnalysisWorkerRequest(analysis_request=request),
        upstream_artifacts=(),
        artifact=ArtifactSpec(
            logical_artifact_id="artifact_" + "d" * 32,
            revision_id="rev_" + "d" * 32,
        ),
    )
    schema = constrained_result_schema("knowledge-analysis-proposal-result@3.0", worker_input)
    result = {
        "schema_version": "1.0",
        "protocol_version": "workflow-role/1.6.0",
        "job_id": worker_input.job_id,
        "workflow_id": worker_input.workflow_id,
        "step_run_id": worker_input.step_run_id,
        "role": "support",
        "status": "ok",
        "artifact": worker_input.artifact.model_dump(mode="json"),
        "output": {"proposal": proposal_v4(request)},
        "completed_at": NOW,
    }
    assert list(Draft202012Validator(schema).iter_errors(result)) == []
    invalid = deepcopy(result)
    invalid["output"]["proposal"]["edges"][0]["relationship"]["edge_type"] = (  # type: ignore[index]
        "ASSESSES_CONCEPT"
    )
    assert any(
        tuple(error.absolute_path)[-1:] == ("relationship",)
        for error in Draft202012Validator(schema).iter_errors(invalid)
    )

    _, receipt = stage_knowledge_analysis_proposal(
        proposal=KnowledgeAnalysisWorkerProposalV2.model_validate(result["output"]["proposal"]),  # type: ignore[index]
        request=request,
        job_id=worker_input.job_id,
        logical_artifact_id=worker_input.artifact.logical_artifact_id,
        revision_id=worker_input.artifact.revision_id,
        staging=tmp_path,
    )
    assert isinstance(receipt, KnowledgeAnalysisProposalReceiptV3)
    assert receipt.members.edges.schema_ref == "eom://schemas/knowledge/proposed-edge/3.0"


def test_historical_v2_schema_bytes_are_pinned_and_packaged() -> None:
    expected = {
        "knowledge-analysis-types-v2.schema.json": (
            "74cf5efc429b70e0e500283a356da742a8c7beb50fccb1f1a46c07523599fa3f"
        ),
        "knowledge-analysis-request-v2.schema.json": (
            "bf77196f281dc8c2c22e850e576a9137acb7bc1fea3681400f8855dc1f63414f"
        ),
        "knowledge-analysis-proposal-receipt-v1.schema.json": (
            "9159e7ef26da33825052f6704d13b1ff80bb2c68afdbc0a9474fab19912e69a7"
        ),
        "knowledge-analysis-result-v2.schema.json": (
            "e017752dc52ca32cb18d5e671525d1415c76ce19df023ac33fd3a43e811c3d48"
        ),
    }
    for name, digest in expected.items():
        canonical = (ROOT / "schemas/knowledge" / name).read_bytes()
        packaged = (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources/knowledge" / name
        ).read_bytes()
        assert canonical == packaged
        assert sha256(canonical).hexdigest() == digest


def test_integrity_protocol_schema_bytes_are_pinned_and_packaged() -> None:
    expected = {
        "knowledge-analysis-worker-proposal-v3.schema.json": (
            "48353e07147aa97aff2b27c503a9c626d640a70bf728d77f1d7e166e88b07cf3"
        ),
        "knowledge-analysis-request-v5.schema.json": (
            "b5354e230d8c93061c6854ce8c74ab5b7fa289bb9c595f205c44f6edecdbbf70"
        ),
        "knowledge-analysis-proposal-receipt-v4.schema.json": (
            "e760b89bf97fcfa90c099b60b6bfa1c19628deaf950bd7a1a8dbaacdd055312d"
        ),
        "knowledge-analysis-result-v5.schema.json": (
            "bebe839c267ebb7e82bec5c21059e27e3b96135b8e68815beb49b42377c7fb44"
        ),
    }
    for name, digest in expected.items():
        canonical = (ROOT / "schemas/knowledge" / name).read_bytes()
        packaged = (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources/knowledge" / name
        ).read_bytes()
        assert canonical == packaged
        assert sha256(canonical).hexdigest() == digest


def test_multimodal_protocol_schema_bytes_are_pinned_and_packaged() -> None:
    expected = {
        "knowledge-analysis-types-v4.schema.json": (
            "02584fb9edb61c32a904c5ec5878f9f96ffe300f32796fab3cfe730ae531935f"
        ),
        "knowledge-analysis-request-v6.schema.json": (
            "8107f1e55d46901fb7ff6619872fbc5600b27c6e068cffb486155e627728e9d0"
        ),
        "knowledge-analysis-worker-proposal-v4.schema.json": (
            "1fd771c15c02d675bab6a8c73d7385814749633d02f12f7662c7cdd5f5851d79"
        ),
        "knowledge-analysis-proposal-receipt-v5.schema.json": (
            "e9a57008f855db5425651bafa98347f9868f7941f56e706dac46b6cf69da754f"
        ),
        "knowledge-analysis-result-v6.schema.json": (
            "6d019621da271e3ed286e113b277346475b2a166afa103b2b6fe85bbf101d9c5"
        ),
    }
    for name, digest in expected.items():
        canonical = (ROOT / "schemas/knowledge" / name).read_bytes()
        packaged = (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources/knowledge" / name
        ).read_bytes()
        assert canonical == packaged
        assert sha256(canonical).hexdigest() == digest

    workflow_expected = {
        "knowledge-analysis-input-v5.schema.json": (
            "1f806aa2befb65a79073abe3998102a3b4e3a16bd3817577abfb61f4cf413f2b"
        ),
        "knowledge-analysis-proposal-result-v5.schema.json": (
            "dda775b76b62f2c3b0caff136cd02543cdcf95869e1045e763feffdecb89e0a8"
        ),
    }
    for name, digest in workflow_expected.items():
        canonical = (ROOT / "schemas/workflow/roles" / name).read_bytes()
        packaged = (ROOT / "packages/workflow/eom_workflow/resources/roles" / name).read_bytes()
        assert canonical == packaged
        assert sha256(canonical).hexdigest() == digest


def test_analysis_workflow_protocol_versions_are_immutable_and_distinct() -> None:
    assert role_schema_bundle_hash("workflow-role/1.4.0") == (
        "sha256:c385885dc445cee96ae8f0c2a122678c3db68f9b10d8162c7695108fbcc47b4b"
    )
    assert role_schema_bundle_hash("workflow-role/1.5.0") == (
        "sha256:92bfb56d96282e622a008ce4216d7dc03badea391e33dd3fd9a89c1f6d3255c9"
    )
    assert role_schema_bundle_hash("workflow-role/1.6.0") == (
        "sha256:089f00931b2e32a39d472f9481bd50d1d641255c0bce9e9dd1c74a5c13df9878"
    )
    assert role_schema_bundle_hash("workflow-role/1.7.0") == (
        "sha256:c3c13aef2f797fe255d7ca141ad374069b0e2c000314292ba68b99479f525058"
    )
    assert role_schema_bundle_hash("workflow-role/1.8.0") == (
        "sha256:1b99d22abf59081d8843934571d33346d0d0083fcfb9a000c5683577dc8827cc"
    )
    expected_definitions = {
        "knowledge-analysis.v1.yaml": (
            "75d2a750632a8ddbd5d350d00f28ecbfd79aa6527f1fb26436f664eb47b810d8"
        ),
        "knowledge-analysis.v2.yaml": (
            "4cbbfe6c70ad340d008729594f09587f5ac074225a4691abb60f0d3b8b8188d6"
        ),
        "knowledge-analysis.v3.yaml": (
            "115c25e27fd5e130fb8758963d3a52e90e5576a486dcc74088a7f1f0990fc8bf"
        ),
        "knowledge-analysis.v4.yaml": (
            "a805042ff2f7c110e016d97dfaf56fd22300ce22003956ec0613c44145b6ddef"
        ),
        "knowledge-analysis.v5.yaml": (
            "953b68dc48baebc504651c5b9ea2662f54d2a7d57798abb10bbc3d26cf7204f3"
        ),
    }
    for name, digest in expected_definitions.items():
        assert sha256((ROOT / "config/workflows" / name).read_bytes()).hexdigest() == digest


def test_v2_model_still_rejects_document_source_without_reinterpretation() -> None:
    value = request_v3()
    value["schema_version"] = "knowledge-analysis-request/2.0"
    value["accepted_result_schema_ref"] = "eom://schemas/knowledge/knowledge-analysis-result/2.0"
    value["request_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "request_sha256"}
    )
    with pytest.raises(PydanticValidationError):
        KnowledgeAnalysisRequestV2.model_validate(value)
