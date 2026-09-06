from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest
from eom_catalog_contracts import (
    ApprovedItemKnowledgeSourceV2,
    ApprovedPastExamItemKnowledgeSourceV3,
    KnowledgeAnalysisRequestV9,
    KnowledgeAnalysisWorkerProposalV7,
    KnowledgeArtifactMemberPointer,
    validate_contract,
)
from eom_catalog_service.knowledge_graph_projection import (
    AcceptedAnalysisProposal,
    build_education_graph_projection,
)
from eom_catalog_service.knowledge_graph_publication_service import _snapshot_source_revision
from eom_identifiers import content_sha256
from pydantic import ValidationError

NOW = datetime(2026, 9, 6, 3, tzinfo=UTC)


def _pointer(seed: str, *, member_path: str, schema_ref: str, media_type: str) -> dict[str, str]:
    return {
        "artifact_id": "artifact_" + seed * 32,
        "artifact_revision_id": "rev_" + seed * 32,
        "member_path": member_path,
        "schema_ref": schema_ref,
        "media_type": media_type,
        "sha256": "sha256:" + seed * 64,
    }


def _source() -> ApprovedPastExamItemKnowledgeSourceV3:
    problem_source = _pointer(
        "4",
        member_path="sources/problem.pdf",
        schema_ref="eom://schemas/legacy-assessment/pdf-source/1.0",
        media_type="application/pdf",
    )
    answer_source = _pointer(
        "5",
        member_path="sources/answer.pdf",
        schema_ref="eom://schemas/legacy-assessment/pdf-source/1.0",
        media_type="application/pdf",
    )
    problem_image = _pointer(
        "6",
        member_path="pages/problem-000003.png",
        schema_ref="eom://schemas/legacy-assessment/page-image/1.0",
        media_type="image/png",
    )
    answer_image = _pointer(
        "7",
        member_path="pages/answer-000008.png",
        schema_ref="eom://schemas/legacy-assessment/page-image/1.0",
        media_type="image/png",
    )
    return ApprovedPastExamItemKnowledgeSourceV3.model_validate(
        {
            "source_kind": "APPROVED_ITEM_REVISION",
            "source_class": "PAST_EXAM",
            "item_id": "item_" + "1" * 32,
            "item_revision_id": "itemrev_" + "1" * 32,
            "lifecycle_state": "APPROVED",
            "artifact_member": {
                **_pointer(
                    "1",
                    member_path="assessment-item-content.json",
                    schema_ref="eom.assessment.item-content/1.0",
                    media_type="application/json",
                ),
                "materialized_path": "source/item-content.json",
                "bytes": 512,
                "logical_name": "item-content.json",
            },
            "extraction_acceptance_id": "itemacceptance_" + "2" * 32,
            "extraction_acceptance_sha256": "sha256:" + "2" * 64,
            "extraction_acceptance_artifact": _pointer(
                "2",
                member_path="acceptance.json",
                schema_ref=(
                    "eom://schemas/legacy-assessment/legacy-item-extraction-acceptance/1.0"
                ),
                media_type="application/json",
            ),
            "extraction_result_id": "itemextractresult_" + "3" * 32,
            "extraction_result_sha256": "sha256:" + "3" * 64,
            "extraction_result_artifact": _pointer(
                "3",
                member_path="result.json",
                schema_ref="eom://schemas/legacy-assessment/legacy-item-extraction-result/1.0",
                media_type="application/json",
            ),
            "item_proposal_id": "itemproposal_" + "8" * 32,
            "item_number": 4,
            "bundle": {
                "assessment_source_bundle_id": "assessbundle_" + "9" * 32,
                "assessment_source_bundle_revision_id": "assessbundlerev_" + "9" * 32,
                "bundle_manifest_sha256": "sha256:" + "9" * 64,
            },
            "layout_observation": {
                "assessment_layout_observation_id": "assessmentlayout_" + "a" * 32,
                "artifact": _pointer(
                    "a",
                    member_path="layout.json",
                    schema_ref=(
                        "eom://schemas/legacy-assessment/assessment-layout-observation/1.0"
                    ),
                    media_type="application/json",
                ),
                "workspace_relative_path": "source/layout-observation.json",
                "observation_sha256": "sha256:" + "a" * 64,
            },
            "page_inputs": [
                {
                    "page_input_id": "assessmentpage_" + "b" * 32,
                    "source_role": "PROBLEM_DOCUMENT",
                    "physical_page": 3,
                    "source": problem_source,
                    "image": problem_image,
                    "workspace_relative_path": ("source/pages/assessmentpage_" + "b" * 32 + ".png"),
                    "width_px": 1200,
                    "height_px": 1800,
                },
                {
                    "page_input_id": "assessmentpage_" + "c" * 32,
                    "source_role": "ANSWER_EXPLANATION_DOCUMENT",
                    "physical_page": 8,
                    "source": answer_source,
                    "image": answer_image,
                    "workspace_relative_path": ("source/pages/assessmentpage_" + "c" * 32 + ".png"),
                    "width_px": 1200,
                    "height_px": 1800,
                },
            ],
            "page_image_count": 2,
        }
    )


def _request(source: ApprovedPastExamItemKnowledgeSourceV3) -> KnowledgeAnalysisRequestV9:
    value = {
        "schema_version": "knowledge-analysis-request/9.0",
        "analysis_request_id": "knowledgeanalysis_" + "d" * 32,
        "execution_preset_id": "execpreset_" + "d" * 32,
        "execution_preset_revision_id": "execpresetrev_" + "d" * 32,
        "execution_preset_sha256": "sha256:" + "d" * 64,
        "worker_proposal_schema_ref": (
            "eom://schemas/knowledge/knowledge-analysis-worker-proposal/7.0"
        ),
        "accepted_result_schema_ref": ("eom://schemas/knowledge/knowledge-analysis-result/9.0"),
        "source": source.model_dump(mode="json"),
        "predecessor_analysis_run_id": None,
        "prior_graph_snapshot": None,
        "requested_outputs": [
            "NORMALIZED_MARKDOWN",
            "SOURCE_ANCHORS",
            "NODES",
            "EDGES",
            "CLAIMS",
            "COMPONENT_OBSERVATIONS",
            "PAGE_IMAGE_OBSERVATIONS",
            "UNRESOLVED_AMBIGUITIES",
        ],
        "general_knowledge_mode": "DISABLED",
        "risk_policy_revision_id": "analysisriskrev_" + "e" * 32,
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
        "request_sha256": "sha256:" + "0" * 64,
    }
    value["request_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "request_sha256"}
    )
    return KnowledgeAnalysisRequestV9.model_validate(value)


def _proposal(source: ApprovedPastExamItemKnowledgeSourceV3) -> KnowledgeAnalysisWorkerProposalV7:
    anchors = [
        {
            "anchor_id": "anchor_problem_page",
            "artifact_revision_id": source.page_inputs[0].image.artifact_revision_id,
            "member_path": source.page_inputs[0].image.member_path,
            "anchor_kind": "ITEM_ELEMENT",
            "locator": "physical_page=3;item=4",
            "excerpt_sha256": "sha256:" + "b" * 64,
        },
        {
            "anchor_id": "anchor_answer_page",
            "artifact_revision_id": source.page_inputs[1].image.artifact_revision_id,
            "member_path": source.page_inputs[1].image.member_path,
            "anchor_kind": "ITEM_ELEMENT",
            "locator": "physical_page=8;item=4",
            "excerpt_sha256": "sha256:" + "c" * 64,
        },
    ]
    return KnowledgeAnalysisWorkerProposalV7.model_validate(
        {
            "schema_version": "knowledge-analysis-worker-proposal/7.0",
            "analysis_request_id": "knowledgeanalysis_" + "d" * 32,
            "normalized_markdown": "# 4번 문항\n\n원본 PNG를 확인한 분석입니다.\n",
            "anchors": anchors,
            "nodes": [
                {
                    "node_id": "knode_concept_visual_evidence",
                    "node_type": "CONCEPT",
                    "stable_key": "concept:visual-evidence",
                    "label": "시각 근거",
                    "anchor_ids": ["anchor_problem_page", "anchor_answer_page"],
                }
            ],
            "edges": [],
            "claims": [],
            "component_observations": [],
            "page_image_observations": [
                {
                    "page_input_id": source.page_inputs[0].page_input_id,
                    "source_role": source.page_inputs[0].source_role,
                    "physical_page": source.page_inputs[0].physical_page,
                    "image_sha256": source.page_inputs[0].image.sha256,
                    "observation_state": "OBSERVED",
                    "anchor_ids": ["anchor_problem_page"],
                },
                {
                    "page_input_id": source.page_inputs[1].page_input_id,
                    "source_role": source.page_inputs[1].source_role,
                    "physical_page": source.page_inputs[1].physical_page,
                    "image_sha256": source.page_inputs[1].image.sha256,
                    "observation_state": "OBSERVED",
                    "anchor_ids": ["anchor_answer_page"],
                },
            ],
            "unresolved_ambiguities": [],
            "general_knowledge_used": False,
            "completed_at": NOW,
        }
    )


def test_v9_request_and_proposal_require_exact_ordered_page_observations() -> None:
    source = _source()
    request = _request(source)
    proposal = _proposal(source)

    validate_contract("knowledge-analysis-request-v9", request.model_dump(mode="json"))
    validate_contract("knowledge-analysis-worker-proposal-v7", proposal.model_dump(mode="json"))

    invalid = deepcopy(proposal.model_dump(mode="json"))
    invalid["page_image_observations"].reverse()
    with pytest.raises(ValidationError):
        KnowledgeAnalysisWorkerProposalV7.model_validate(invalid)


def test_visual_graph_source_pointer_retains_exact_png_revision_and_hash() -> None:
    source = _source()
    proposal = _proposal(source)
    analysis = AcceptedAnalysisProposal(
        analysis_run_id="analysisrun_" + "f" * 32,
        source=source,
        accepted_result=KnowledgeArtifactMemberPointer(
            artifact_id="artifact_" + "f" * 32,
            artifact_revision_id="rev_" + "f" * 32,
            sha256="sha256:" + "f" * 64,
            schema_ref="eom://schemas/knowledge/knowledge-analysis-result/9.0",
            media_type="application/json",
            logical_name="accepted-result.json",
            member_path="evidence/accepted-result.json",
        ),
        proposal=proposal,
    )

    projection = build_education_graph_projection((analysis,), None)
    pointers = projection.nodes[0].source_pointers
    expected = {
        (
            page.image.artifact_id,
            page.image.artifact_revision_id,
            page.image.member_path,
            page.image.sha256,
        )
        for page in source.page_inputs
    }
    assert {
        (
            pointer.source_artifact_id,
            pointer.source_artifact_revision_id,
            pointer.member_path,
            pointer.source_sha256,
        )
        for pointer in pointers
    } == expected

    snapshot_source = _snapshot_source_revision(source)
    assert isinstance(snapshot_source, ApprovedItemKnowledgeSourceV2)
    assert not isinstance(snapshot_source, ApprovedPastExamItemKnowledgeSourceV3)
    assert snapshot_source.item_revision_id == source.item_revision_id
