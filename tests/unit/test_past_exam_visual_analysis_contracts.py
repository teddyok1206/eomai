from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest
from eom_catalog_contracts import (
    PAST_EXAM_VISUAL_ANALYSIS_REQUEST_SCHEMA_VERSION,
    ApprovedItemKnowledgeSourceV2,
    ApprovedPastExamItemKnowledgeSourceV3,
    KnowledgeAnalysisRequestV9,
    KnowledgeAnalysisWorkerProposalV7,
    KnowledgeArtifactMemberPointer,
    validate_assessment_page_observation_anchors,
    validate_contract,
)
from eom_catalog_service.knowledge_graph_projection import (
    AcceptedAnalysisProposal,
    build_education_graph_projection,
)
from eom_catalog_service.knowledge_graph_publication_service import _snapshot_source_revision
from eom_identifiers import content_sha256
from eom_workflow import WorkflowRequest
from eom_workflow.schemas import (
    WorkflowSchemaError,
    load_role_result_schema,
    validate_role_result,
    validate_schema_message,
)
from pydantic import ValidationError

NOW = datetime(2026, 9, 6, 3, tzinfo=UTC)


def test_visual_past_exam_protocol_identity_is_centralized() -> None:
    assert (
        KnowledgeAnalysisRequestV9.model_fields["schema_version"].default
    ) == PAST_EXAM_VISUAL_ANALYSIS_REQUEST_SCHEMA_VERSION


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


def _proposal_role_result(proposal: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "protocol_version": "workflow-role/1.18.0",
        "job_id": "job_" + "1" * 32,
        "workflow_id": "workflow_" + "2" * 32,
        "step_run_id": "steprun_" + "3" * 32,
        "status": "ok",
        "artifact": {
            "logical_artifact_id": "artifact_" + "4" * 32,
            "revision_id": "rev_" + "5" * 32,
            "file_name": "result.json",
            "media_type": "application/json",
        },
        "completed_at": NOW.isoformat().replace("+00:00", "Z"),
        "role": "support",
        "output": {"proposal": proposal},
    }


def _raw_proposal_with_two_nodes() -> dict[str, object]:
    proposal = _proposal(_source()).model_dump(mode="json")
    nodes = proposal["nodes"]
    assert isinstance(nodes, list)
    nodes.append(
        {
            "node_id": "knode_concept_secondary",
            "node_type": "CONCEPT",
            "stable_key": "concept:secondary",
            "label": "보조 개념",
            "anchor_ids": ["anchor_problem_page"],
        }
    )
    return proposal


def _edge(
    *,
    edge_id: str,
    from_node_id: str = "knode_concept_visual_evidence",
    to_node_id: str = "knode_concept_secondary",
    edge_type: str = "IS_A",
    from_node_type: str = "CONCEPT",
    to_node_type: str = "CONCEPT",
) -> dict[str, object]:
    return {
        "edge_id": edge_id,
        "relationship": {
            "edge_type": edge_type,
            "from_node_type": from_node_type,
            "to_node_type": to_node_type,
        },
        "from_node_id": from_node_id,
        "to_node_id": to_node_id,
        "confidence_milli": 900,
        "anchor_ids": ["anchor_problem_page"],
    }


@pytest.mark.parametrize(
    "invalid_edge",
    [
        _edge(
            edge_id="kedge_self",
            to_node_id="knode_concept_visual_evidence",
        ),
        _edge(
            edge_id="kedge_dangling",
            to_node_id="knode_concept_missing",
        ),
        _edge(
            edge_id="kedge_declared_type_mismatch",
            to_node_type="PROCESS",
        ),
    ],
    ids=("self", "dangling", "declared-endpoint-type-mismatch"),
)
def test_v9_role_validation_filters_only_invalid_edges_after_json_schema(
    invalid_edge: dict[str, object],
) -> None:
    proposal = _raw_proposal_with_two_nodes()
    edges = proposal["edges"]
    assert isinstance(edges, list)
    edges.extend((_edge(edge_id="kedge_valid"), invalid_edge))
    result = _proposal_role_result(proposal)
    unchanged = deepcopy(result)

    validate_schema_message(
        load_role_result_schema("knowledge-analysis-proposal-result@9.0"),
        result,
        "pre-normalization",
    )
    parsed = validate_role_result(
        result,
        "support",
        "knowledge-analysis-proposal-result@9.0",
    )

    assert [edge.edge_id for edge in parsed.output.proposal.edges] == ["kedge_valid"]
    assert result == unchanged
    assert (
        parsed.output.proposal.nodes
        == KnowledgeAnalysisWorkerProposalV7.model_validate(
            {**proposal, "edges": [_edge(edge_id="kedge_valid")]}
        ).nodes
    )
    assert (
        validate_role_result(
            result,
            "support",
            "knowledge-analysis-proposal-result@9.0",
        )
        == parsed
    )


def test_v9_role_validation_filters_edges_rejected_by_current_worker_ontology(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proposal = _raw_proposal_with_two_nodes()
    edges = proposal["edges"]
    assert isinstance(edges, list)
    edges.append(_edge(edge_id="kedge_now_incompatible"))
    result = _proposal_role_result(proposal)

    validate_schema_message(
        load_role_result_schema("knowledge-analysis-proposal-result@9.0"),
        result,
        "pre-normalization",
    )

    def reject_current_ontology(*_args: object) -> None:
        raise ValueError("simulated current worker-ontology rejection")

    monkeypatch.setattr(
        "eom_workflow.schemas.validate_worker_knowledge_edge_endpoint_types",
        reject_current_ontology,
    )

    parsed = validate_role_result(
        result,
        "support",
        "knowledge-analysis-proposal-result@9.0",
    )

    assert parsed.output.proposal.edges == ()


def test_v9_role_validation_rejects_malformed_edges_before_filtering() -> None:
    proposal = _raw_proposal_with_two_nodes()
    malformed = _edge(edge_id="kedge_malformed")
    malformed.pop("relationship")
    edges = proposal["edges"]
    assert isinstance(edges, list)
    edges.append(malformed)

    with pytest.raises(
        WorkflowSchemaError,
        match=r"knowledge-analysis-proposal-result@9\.0 at output\.proposal\.edges\.0",
    ):
        validate_role_result(
            _proposal_role_result(proposal),
            "support",
            "knowledge-analysis-proposal-result@9.0",
        )


def test_v9_role_validation_does_not_repair_duplicate_node_identities() -> None:
    proposal = _raw_proposal_with_two_nodes()
    nodes = proposal["nodes"]
    assert isinstance(nodes, list)
    duplicate = deepcopy(nodes[1])
    assert isinstance(duplicate, dict)
    duplicate["label"] = "중복 보조 개념"
    nodes.append(duplicate)

    result = _proposal_role_result(proposal)
    validate_schema_message(
        load_role_result_schema("knowledge-analysis-proposal-result@9.0"),
        result,
        "pre-normalization",
    )
    with pytest.raises(WorkflowSchemaError, match="node identities must be unique"):
        validate_role_result(
            result,
            "support",
            "knowledge-analysis-proposal-result@9.0",
        )


@pytest.mark.parametrize(
    "duplicate_edges",
    (
        (
            _edge(edge_id="kedge_duplicate_identity"),
            _edge(
                edge_id="kedge_duplicate_identity",
                to_node_id="knode_concept_visual_evidence",
            ),
        ),
        (
            _edge(
                edge_id="kedge_duplicate_identity",
                to_node_id="knode_concept_visual_evidence",
            ),
            _edge(
                edge_id="kedge_duplicate_identity",
                from_node_id="knode_concept_secondary",
                to_node_id="knode_concept_secondary",
            ),
        ),
    ),
    ids=("valid-and-filtered", "both-filtered"),
)
def test_v9_role_validation_does_not_repair_duplicate_edge_identities(
    duplicate_edges: tuple[dict[str, object], dict[str, object]],
) -> None:
    proposal = _raw_proposal_with_two_nodes()
    edges = proposal["edges"]
    assert isinstance(edges, list)
    edges.extend(duplicate_edges)

    result = _proposal_role_result(proposal)
    validate_schema_message(
        load_role_result_schema("knowledge-analysis-proposal-result@9.0"),
        result,
        "pre-normalization",
    )
    with pytest.raises(WorkflowSchemaError, match="edge identities must be unique"):
        validate_role_result(
            result,
            "support",
            "knowledge-analysis-proposal-result@9.0",
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


def test_assessment_page_observations_bind_anchors_to_the_exact_png_member() -> None:
    source = _source()
    proposal = _proposal(source)

    validate_assessment_page_observation_anchors(source, proposal)
    first, second = proposal.page_image_observations
    swapped = proposal.model_copy(
        update={
            "page_image_observations": (
                first.model_copy(update={"anchor_ids": second.anchor_ids}),
                second.model_copy(update={"anchor_ids": first.anchor_ids}),
            )
        }
    )

    with pytest.raises(ValueError, match="another source"):
        validate_assessment_page_observation_anchors(source, swapped)


def test_visual_analysis_workflow_requires_image_materialization_mode() -> None:
    request = _request(_source())

    workflow_request = WorkflowRequest(
        request_name="KNOWLEDGE_ANALYSIS_REQUEST",
        image_mode="required",
        analysis_request=request,
    )

    assert workflow_request.worker_request().analysis_request == request
    with pytest.raises(ValidationError, match="matching image mode"):
        WorkflowRequest(
            request_name="KNOWLEDGE_ANALYSIS_REQUEST",
            image_mode="skip",
            analysis_request=request,
        )


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
