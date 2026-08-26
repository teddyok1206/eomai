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
    EvidenceBundleManifestV3,
    EvidenceBundlePublicationResultV3,
    KnowledgeAnalysisProposalReceiptV2,
    KnowledgeAnalysisProposalReceiptV3,
    KnowledgeAnalysisRequestV2,
    KnowledgeAnalysisRequestV3,
    KnowledgeAnalysisRequestV4,
    KnowledgeAnalysisResultV3,
    KnowledgeAnalysisResultV4,
    KnowledgeAnalysisWorkerProposal,
    KnowledgeAnalysisWorkerProposalV2,
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


@pytest.mark.parametrize(
    ("schema", "value", "model"),
    [
        ("knowledge-analysis-request-v3", request_v3(), KnowledgeAnalysisRequestV3),
        ("knowledge-analysis-request-v4", request_v4(), KnowledgeAnalysisRequestV4),
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
        ("knowledge-analysis-result-v3", result_v3(), KnowledgeAnalysisResultV3),
        ("knowledge-analysis-result-v4", result_v4(), KnowledgeAnalysisResultV4),
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
