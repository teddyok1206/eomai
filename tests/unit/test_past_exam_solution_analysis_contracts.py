from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from eom_catalog_contracts import (
    SOLUTION_REFERENCE_NODE_TYPES,
    ApprovedPastExamItemKnowledgeSourceV3,
    KnowledgeAnalysisProposalReceiptV9,
    KnowledgeAnalysisRequestV10,
    KnowledgeAnalysisResultV10,
    KnowledgeAnalysisWorkerProposalV8,
    ProposedKnowledgeNodeV2,
    validate_contract,
    validate_knowledge_solution_report_references,
)
from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.solution_evidence_resolution import (
    SolutionEvidenceResolutionError,
    _resolve_row,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.knowledge_analysis_artifact import stage_knowledge_analysis_proposal
from eom_workflow.models import (
    KnowledgeAnalysisProposalRoleResultV10,
    RoleWorkerInput,
    WorkflowRequest,
)
from eom_workflow.schemas import (
    WorkflowSchemaError,
    constrained_result_schema,
    load_codex_result_schema,
    validate_role_input,
    validate_role_result,
    validate_schema_message,
)
from pydantic import ValidationError

NOW = datetime(2026, 9, 12, 3, tzinfo=UTC)


def _sha(seed: str) -> str:
    return "sha256:" + seed * 64


def test_base_node_type_is_already_normalized_to_its_wire_string() -> None:
    node = ProposedKnowledgeNodeV2.model_validate(
        {
            "node_id": "knode_concept_motion",
            "node_type": "CONCEPT",
            "stable_key": "concept.motion",
            "label": "운동",
            "anchor_ids": ["anchor_problem"],
        }
    )

    assert node.node_type == "CONCEPT"
    assert isinstance(node.node_type, str)
    assert node.node_type in SOLUTION_REFERENCE_NODE_TYPES
    assert "ITEM_REVISION" not in SOLUTION_REFERENCE_NODE_TYPES


def test_solution_analysis_workflow_preserves_required_visual_input_mode() -> None:
    request = KnowledgeAnalysisRequestV10.model_validate(_request_value())

    workflow_request = WorkflowRequest(
        request_name="KNOWLEDGE_ANALYSIS_REQUEST",
        image_mode="required",
        analysis_request=request,
    )

    assert workflow_request.analysis_request == request
    with pytest.raises(ValidationError, match="matching image mode"):
        WorkflowRequest(
            request_name="KNOWLEDGE_ANALYSIS_REQUEST",
            image_mode="skip",
            analysis_request=request,
        )


def _pointer(seed: str, *, member_path: str, schema_ref: str, media_type: str) -> dict[str, object]:
    return {
        "artifact_id": "artifact_" + seed * 32,
        "artifact_revision_id": "rev_" + seed * 32,
        "member_path": member_path,
        "schema_ref": schema_ref,
        "media_type": media_type,
        "sha256": _sha(seed),
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
            "extraction_acceptance_sha256": _sha("2"),
            "extraction_acceptance_artifact": _pointer(
                "2",
                member_path="acceptance.json",
                schema_ref=(
                    "eom://schemas/legacy-assessment/legacy-item-extraction-acceptance/1.0"
                ),
                media_type="application/json",
            ),
            "extraction_result_id": "itemextractresult_" + "3" * 32,
            "extraction_result_sha256": _sha("3"),
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
                "bundle_manifest_sha256": _sha("9"),
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
                "observation_sha256": _sha("a"),
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


def _member(
    name: str,
    seed: str,
    *,
    member_path: str,
    schema_ref: str,
    media_type: str,
) -> dict[str, object]:
    return {
        "artifact_id": "artifact_" + "e" * 32,
        "artifact_revision_id": "rev_" + "e" * 32,
        "member_path": member_path,
        "sha256": _sha(seed),
        "bytes": 1,
        "schema_ref": schema_ref,
        "media_type": media_type,
        "logical_name": name,
    }


def _base_analysis() -> dict[str, object]:
    specifications = {
        "normalized_markdown": (
            "document.md",
            "1",
            "normalized/document.md",
            "eom://schemas/knowledge/normalized-markdown/1.0",
            "text/markdown",
        ),
        "anchors": (
            "anchors.jsonl",
            "2",
            "normalized/anchors.jsonl",
            "eom://schemas/knowledge/source-anchor/2.0",
            "application/x-ndjson",
        ),
        "nodes": (
            "nodes.jsonl",
            "3",
            "normalized/nodes.jsonl",
            "eom://schemas/knowledge/proposed-node/4.0",
            "application/x-ndjson",
        ),
        "edges": (
            "edges.jsonl",
            "4",
            "normalized/edges.jsonl",
            "eom://schemas/knowledge/proposed-edge/4.0",
            "application/x-ndjson",
        ),
        "claims": (
            "claims.jsonl",
            "5",
            "normalized/claims.jsonl",
            "eom://schemas/knowledge/proposed-claim/2.0",
            "application/x-ndjson",
        ),
        "component_observations": (
            "components.jsonl",
            "6",
            "normalized/components.jsonl",
            "eom://schemas/knowledge/component-observation/2.0",
            "application/x-ndjson",
        ),
        "unresolved_ambiguities": (
            "ambiguities.jsonl",
            "7",
            "normalized/ambiguities.jsonl",
            "eom://schemas/knowledge/ambiguity/3.0",
            "application/x-ndjson",
        ),
        "page_image_observations": (
            "page-images.jsonl",
            "8",
            "normalized/page-images.jsonl",
            "eom://schemas/knowledge/assessment-page-image-observation/2.0",
            "application/x-ndjson",
        ),
    }
    members = {
        field: _member(
            values[0],
            values[1],
            member_path=values[2],
            schema_ref=values[3],
            media_type=values[4],
        )
        for field, values in specifications.items()
    }
    descriptors = [
        {
            "member_path": member["member_path"],
            "sha256": member["sha256"],
            "bytes": member["bytes"],
            "schema_ref": member["schema_ref"],
            "media_type": member["media_type"],
        }
        for member in sorted(members.values(), key=lambda value: str(value["member_path"]))
    ]
    reference_index: dict[str, object] = {
        "anchor_ids": ["anchor_answer", "anchor_problem"],
        "problem_anchor_ids": ["anchor_problem"],
        "answer_explanation_anchor_ids": ["anchor_answer"],
        "nodes": [
            {"node_id": "knode_assessment_pattern_reason", "node_type": "ASSESSMENT_PATTERN"},
            {"node_id": "knode_concept_motion", "node_type": "CONCEPT"},
            {"node_id": "knode_item_element_stem", "node_type": "ITEM_ELEMENT"},
        ],
        "index_sha256": _sha("0"),
    }
    reference_index["index_sha256"] = content_sha256(
        {key: value for key, value in reference_index.items() if key != "index_sha256"}
    )
    return {
        "analysis_run_id": "analysisrun_" + "a" * 32,
        "analysis_result_id": "knowledgeanalysisresult_" + "a" * 32,
        "analysis_request_id": "knowledgeanalysis_" + "a" * 32,
        "accepted_result_sha256": _sha("9"),
        "accepted_result_artifact": {
            **_member(
                "accepted-result.json",
                "a",
                member_path="evidence/accepted-result.json",
                schema_ref="eom://schemas/knowledge/knowledge-analysis-result/9.0",
                media_type="application/json",
            ),
        },
        "proposal_receipt": _member(
            "proposal-receipt.json",
            "b",
            member_path="normalized/proposal-receipt.json",
            schema_ref="eom://schemas/knowledge/knowledge-analysis-proposal-receipt/8.0",
            media_type="application/json",
        ),
        "proposal_content_set_sha256": content_sha256(descriptors),
        "base_members": members,
        "base_counts": {
            "anchors": 2,
            "nodes": 3,
            "edges": 0,
            "claims": 1,
            "component_observations": 1,
            "ambiguities": 0,
            "page_image_observations": 2,
        },
        "reference_index": reference_index,
    }


def _request_value() -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "knowledge-analysis-request/10.0",
        "analysis_request_id": "knowledgeanalysis_" + "d" * 32,
        "execution_preset_id": "execpreset_" + "d" * 32,
        "execution_preset_revision_id": "execpresetrev_" + "d" * 32,
        "execution_preset_sha256": _sha("d"),
        "worker_proposal_schema_ref": (
            "eom://schemas/knowledge/knowledge-analysis-worker-proposal/8.0"
        ),
        "accepted_result_schema_ref": "eom://schemas/knowledge/knowledge-analysis-result/10.0",
        "source": _source().model_dump(mode="json"),
        "predecessor_analysis_run_id": "analysisrun_" + "a" * 32,
        "prior_graph_snapshot": None,
        "requested_outputs": ["SOLUTION_REPORT"],
        "general_knowledge_mode": "DISABLED",
        "risk_policy_revision_id": "analysisriskrev_" + "e" * 32,
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
        "base_analysis": _base_analysis(),
        "request_sha256": _sha("0"),
    }
    value["request_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "request_sha256"}
    )
    return value


def _proposal_value() -> dict[str, object]:
    report = {
        "schema_version": "knowledge-analysis-solution-report/1.0",
        "analysis_request_id": "knowledgeanalysis_" + "d" * 32,
        "base_analysis_result_id": "knowledgeanalysisresult_" + "a" * 32,
        "rationale_kind": "VERIFIABLE_SOLUTION_RATIONALE",
        "solution_steps": [
            {
                "step_id": "solutionstep_conclusion",
                "ordinal": 1,
                "operation": "CONCLUDE",
                "rationale": "문제 조건과 핵심 개념을 함께 적용한다.",
                "outcome": "요구된 답을 결정한다.",
                "depends_on_step_ids": [],
                "node_ids": ["knode_concept_motion"],
                "item_element_node_ids": ["knode_item_element_stem"],
                "anchor_ids": ["anchor_problem"],
            }
        ],
        "concept_assessment_links": [
            {
                "concept_node_id": "knode_concept_motion",
                "role": "ANSWER_CRITERION",
                "reasoning_step_ids": ["solutionstep_conclusion"],
                "assessment_pattern_node_ids": ["knode_assessment_pattern_reason"],
                "item_element_node_ids": ["knode_item_element_stem"],
                "summary": "핵심 개념을 정답 판단 기준에 연결한다.",
            }
        ],
        "choice_diagnostics": [],
        "official_explanation_comparison": {
            "status": "CONSISTENT",
            "summary": "공식 해설의 결론과 일치한다.",
            "answer_explanation_anchor_ids": ["anchor_answer"],
        },
        "final_answer_summary": "정답 판단 결과",
        "solution_summary": "검증 가능한 풀이 단계 요약",
        "assessment_design_summary": "개념을 판단 기준으로 묻는 방식",
        "reusable_generation_guidance": "같은 개념을 다른 맥락에서 묻되 원문을 복제하지 않는다.",
        "unresolved_issues": [],
        "general_knowledge_used": False,
    }
    return {
        "schema_version": "knowledge-analysis-worker-proposal/8.0",
        "analysis_request_id": "knowledgeanalysis_" + "d" * 32,
        "base_analysis_result_id": "knowledgeanalysisresult_" + "a" * 32,
        "solution_report": report,
        "completed_at": NOW.isoformat().replace("+00:00", "Z"),
    }


def _role_input_value() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "protocol_version": "workflow-role/1.21.0",
        "job_id": "job_" + "1" * 32,
        "workflow_id": "workflow_" + "2" * 32,
        "step_run_id": "steprun_" + "3" * 32,
        "attempt": 1,
        "role": "support",
        "request": {
            "request_name": "KNOWLEDGE_ANALYSIS_REQUEST",
            "analysis_request": _request_value(),
        },
        "upstream_artifacts": [],
        "artifact": {
            "logical_artifact_id": "artifact_" + "4" * 32,
            "revision_id": "rev_" + "5" * 32,
            "file_name": "result.json",
            "media_type": "application/json",
        },
    }


def _role_result_value() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "protocol_version": "workflow-role/1.21.0",
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
        "output": {"proposal": _proposal_value()},
    }


def _solution_member() -> dict[str, object]:
    return _member(
        "solution-report.json",
        "f",
        member_path="normalized/solution-report.json",
        schema_ref="eom://schemas/knowledge/knowledge-analysis-solution-report/1.0",
        media_type="application/json",
    )


def _receipt_value() -> dict[str, object]:
    base = _base_analysis()
    base_members = base["base_members"]
    assert isinstance(base_members, dict)
    solution = _solution_member()
    values = [*base_members.values(), solution]
    descriptors = [
        {
            "artifact_id": value["artifact_id"],
            "artifact_revision_id": value["artifact_revision_id"],
            "member_path": value["member_path"],
            "sha256": value["sha256"],
            "bytes": value["bytes"],
            "schema_ref": value["schema_ref"],
            "media_type": value["media_type"],
        }
        for value in sorted(values, key=lambda member: str(member["member_path"]))
    ]
    return {
        "schema_version": "knowledge-analysis-proposal-receipt/9.0",
        "analysis_request_id": "knowledgeanalysis_" + "d" * 32,
        "source": _source().model_dump(mode="json"),
        "base_analysis": base,
        "status": "PROPOSED_VALIDATED",
        "solution_report": solution,
        "solution_counts": {
            "solution_steps": 1,
            "concept_assessment_links": 1,
            "choice_diagnostics": 0,
            "unresolved_issues": 0,
        },
        "general_knowledge_used": False,
        "content_set_sha256": content_sha256(descriptors),
        "completed_at": NOW.isoformat().replace("+00:00", "Z"),
    }


def _result_value() -> dict[str, object]:
    receipt = _receipt_value()
    value: dict[str, object] = {
        "schema_version": "knowledge-analysis-result/10.0",
        "analysis_result_id": "knowledgeanalysisresult_" + "d" * 32,
        "analysis_request_id": "knowledgeanalysis_" + "d" * 32,
        "analysis_request_sha256": _request_value()["request_sha256"],
        "status": "ACCEPTED",
        "source": _source().model_dump(mode="json"),
        "base_analysis": receipt["base_analysis"],
        "proposal_receipt": _member(
            "proposal-receipt.json",
            "c",
            member_path="normalized/proposal-receipt.json",
            schema_ref="eom://schemas/knowledge/knowledge-analysis-proposal-receipt/9.0",
            media_type="application/json",
        ),
        "proposal_content_set_sha256": receipt["content_set_sha256"],
        "risk_policy_revision_id": "analysisriskrev_" + "e" * 32,
        "acceptance_mode": "AUTO_POLICY",
        "review_decision": None,
        "counts": _base_analysis()["base_counts"],
        "solution_counts": receipt["solution_counts"],
        "general_knowledge_used": False,
        "minimum_confidence_milli": None,
        "blocking_ambiguity_count": 0,
        "accepted_at": NOW.isoformat().replace("+00:00", "Z"),
        "result_sha256": _sha("0"),
    }
    value["result_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "result_sha256"}
    )
    return value


def test_v10_additive_contracts_validate_in_json_schema_and_pydantic() -> None:
    request = KnowledgeAnalysisRequestV10.model_validate(_request_value())
    proposal = KnowledgeAnalysisWorkerProposalV8.model_validate(_proposal_value())
    receipt = KnowledgeAnalysisProposalReceiptV9.model_validate(_receipt_value())
    result = KnowledgeAnalysisResultV10.model_validate(_result_value())

    for schema_name, value in (
        ("knowledge-analysis-request-v10", request.model_dump(mode="json")),
        ("knowledge-analysis-worker-proposal-v8", proposal.model_dump(mode="json")),
        ("knowledge-analysis-proposal-receipt-v9", receipt.model_dump(mode="json")),
        ("knowledge-analysis-result-v10", result.model_dump(mode="json")),
    ):
        validate_contract(schema_name, value)
    validate_knowledge_solution_report_references(request, proposal)
    assert (
        request.base_analysis.accepted_result_sha256
        != request.base_analysis.accepted_result_artifact.sha256
    )


def test_v10_staging_commits_only_new_report_and_composite_receipt(tmp_path: Path) -> None:
    request = KnowledgeAnalysisRequestV10.model_validate(_request_value())
    proposal = KnowledgeAnalysisWorkerProposalV8.model_validate(_proposal_value())

    staged, receipt = stage_knowledge_analysis_proposal(
        proposal=proposal,
        request=request,
        job_id="job_" + "1" * 32,
        logical_artifact_id="artifact_" + "4" * 32,
        revision_id="rev_" + "5" * 32,
        staging=tmp_path,
    )

    assert isinstance(receipt, KnowledgeAnalysisProposalReceiptV9)
    assert {member.relative_path for member in staged.files} == {
        "normalized/proposal-receipt.json",
        "normalized/solution-report.json",
    }
    assert receipt.base_analysis == request.base_analysis
    assert receipt.solution_report.artifact_revision_id == "rev_" + "5" * 32
    assert receipt.solution_counts.solution_steps == 1
    assert not (staged.directory / "normalized/nodes.jsonl").exists()
    validate_contract("knowledge-analysis-proposal-receipt-v9", receipt.model_dump(mode="json"))


def test_v10_staging_rejects_reference_outside_base_before_writing(tmp_path: Path) -> None:
    request = KnowledgeAnalysisRequestV10.model_validate(_request_value())
    proposal_value = _proposal_value()
    report = cast(dict[str, Any], proposal_value["solution_report"])
    steps = cast(list[dict[str, Any]], report["solution_steps"])
    steps[0]["anchor_ids"] = ["anchor_unknown"]
    proposal = KnowledgeAnalysisWorkerProposalV8.model_validate(proposal_value)

    with pytest.raises(Exception, match="does not resolve"):
        stage_knowledge_analysis_proposal(
            proposal=proposal,
            request=request,
            job_id="job_" + "1" * 32,
            logical_artifact_id="artifact_" + "4" * 32,
            revision_id="rev_" + "5" * 32,
            staging=tmp_path,
        )
    assert not (tmp_path / "knowledge-proposal-source").exists()


def test_v10_role_schema_and_request_projection_are_closed() -> None:
    worker_input = validate_role_input(_role_input_value(), "support", "workflow-role/1.21.0")
    assert isinstance(worker_input, RoleWorkerInput)
    result = _role_result_value()
    validate_schema_message(
        constrained_result_schema("knowledge-analysis-proposal-result@10.0", worker_input),
        result,
        "constrained-v10",
    )
    parsed = validate_role_result(result, "support", "knowledge-analysis-proposal-result@10.0")
    assert isinstance(parsed, KnowledgeAnalysisProposalRoleResultV10)
    assert parsed.output.proposal.base_analysis_result_id == "knowledgeanalysisresult_" + "a" * 32
    assert len(load_codex_result_schema("knowledge-analysis-proposal-result@10.0")["$defs"]) == 4


def test_v10_constrained_schema_rejects_reference_outside_exact_base_index() -> None:
    worker_input = validate_role_input(_role_input_value(), "support", "workflow-role/1.21.0")
    assert isinstance(worker_input, RoleWorkerInput)
    constrained = constrained_result_schema("knowledge-analysis-proposal-result@10.0", worker_input)
    result = _role_result_value()
    output = cast(dict[str, Any], result["output"])
    proposal = cast(dict[str, Any], output["proposal"])
    report = cast(dict[str, Any], proposal["solution_report"])
    steps = cast(list[dict[str, Any]], report["solution_steps"])
    steps[0]["node_ids"] = ["knode_formula_item3_none"]

    with pytest.raises(WorkflowSchemaError, match="is not one of"):
        validate_schema_message(constrained, result, "constrained-v10")


def test_v10_constrained_schema_binds_every_semantic_reference_family() -> None:
    worker_input = validate_role_input(_role_input_value(), "support", "workflow-role/1.21.0")
    assert isinstance(worker_input, RoleWorkerInput)
    constrained = constrained_result_schema("knowledge-analysis-proposal-result@10.0", worker_input)
    definitions = cast(dict[str, Any], constrained["$defs"])
    report = cast(dict[str, Any], definitions["SolutionV1_solutionReport"])
    properties = cast(dict[str, Any], report["properties"])

    def item_properties(field_name: str) -> dict[str, Any]:
        field = cast(dict[str, Any], properties[field_name])
        items = cast(dict[str, Any], field["items"])
        return cast(dict[str, Any], items["properties"])

    steps = item_properties("solution_steps")
    assert steps["node_ids"]["items"]["enum"] == [
        "knode_assessment_pattern_reason",
        "knode_concept_motion",
        "knode_item_element_stem",
    ]
    assert steps["item_element_node_ids"]["items"]["enum"] == ["knode_item_element_stem"]
    assert steps["anchor_ids"]["items"]["enum"] == ["anchor_problem"]

    links = item_properties("concept_assessment_links")
    assert links["concept_node_id"]["enum"] == ["knode_concept_motion"]
    assert links["assessment_pattern_node_ids"]["items"]["enum"] == [
        "knode_assessment_pattern_reason"
    ]
    assert links["item_element_node_ids"]["items"]["enum"] == ["knode_item_element_stem"]

    choices = item_properties("choice_diagnostics")
    assert choices["node_ids"]["items"]["enum"] == [
        "knode_assessment_pattern_reason",
        "knode_concept_motion",
        "knode_item_element_stem",
    ]
    assert choices["anchor_ids"]["items"]["enum"] == [
        "anchor_answer",
        "anchor_problem",
    ]

    comparison = cast(dict[str, Any], properties["official_explanation_comparison"])
    comparison_properties = cast(dict[str, Any], comparison["properties"])
    assert comparison_properties["answer_explanation_anchor_ids"]["items"]["enum"] == [
        "anchor_answer"
    ]
    issues = item_properties("unresolved_issues")
    assert issues["anchor_ids"]["items"]["enum"] == ["anchor_answer", "anchor_problem"]


def test_v10_constrained_schema_closes_empty_optional_reference_family() -> None:
    input_value = _role_input_value()
    request_wrapper = cast(dict[str, Any], input_value["request"])
    request = cast(dict[str, Any], request_wrapper["analysis_request"])
    base = cast(dict[str, Any], request["base_analysis"])
    reference_index = cast(dict[str, Any], base["reference_index"])
    reference_index["answer_explanation_anchor_ids"] = []
    reference_index["index_sha256"] = content_sha256(
        {key: value for key, value in reference_index.items() if key != "index_sha256"}
    )
    request["request_sha256"] = content_sha256(
        {key: value for key, value in request.items() if key != "request_sha256"}
    )
    worker_input = validate_role_input(input_value, "support", "workflow-role/1.21.0")
    assert isinstance(worker_input, RoleWorkerInput)

    constrained = constrained_result_schema("knowledge-analysis-proposal-result@10.0", worker_input)
    definitions = cast(dict[str, Any], constrained["$defs"])
    report = cast(dict[str, Any], definitions["SolutionV1_solutionReport"])
    properties = cast(dict[str, Any], report["properties"])
    comparison = cast(dict[str, Any], properties["official_explanation_comparison"])
    comparison_properties = cast(dict[str, Any], comparison["properties"])
    answer_anchors = cast(dict[str, Any], comparison_properties["answer_explanation_anchor_ids"])

    assert answer_anchors["maxItems"] == 0
    assert "enum" not in answer_anchors["items"]


def _change_reference_index_hash(value: dict[str, object]) -> None:
    base = cast(dict[str, Any], value["base_analysis"])
    reference_index = cast(dict[str, object], base["reference_index"])
    reference_index["index_sha256"] = _sha("f")


def _change_base_node_path(value: dict[str, object]) -> None:
    base = cast(dict[str, Any], value["base_analysis"])
    members = cast(dict[str, Any], base["base_members"])
    nodes = cast(dict[str, object], members["nodes"])
    nodes["member_path"] = "normalized/wrong.jsonl"


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            _change_reference_index_hash,
            "reference index hash differs",
        ),
        (
            _change_base_node_path,
            "base proposal member contract differs",
        ),
    ],
)
def test_v10_request_rejects_stale_or_changed_base_pointer(
    mutator: Callable[[dict[str, object]], None], message: str
) -> None:
    value = _request_value()
    mutator(value)
    value["request_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "request_sha256"}
    )
    with pytest.raises(ValidationError, match=message):
        KnowledgeAnalysisRequestV10.model_validate(value)


@pytest.mark.parametrize(
    ("path", "replacement", "message"),
    [
        (
            ("solution_report", "solution_steps", 0, "node_ids"),
            ["knode_concept_missing"],
            "unresolved or wrong-type",
        ),
        (
            ("solution_report", "solution_steps", 0, "anchor_ids"),
            ["anchor_answer"],
            "unresolved or wrong-type",
        ),
        (
            (
                "solution_report",
                "official_explanation_comparison",
                "answer_explanation_anchor_ids",
            ),
            ["anchor_problem"],
            "non-answer evidence",
        ),
    ],
)
def test_v10_reference_validation_rejects_wrong_base_identity_or_source_role(
    path: tuple[str | int, ...], replacement: object, message: str
) -> None:
    proposal_value = deepcopy(_proposal_value())
    target: Any = proposal_value
    for part in path[:-1]:
        target = target[part]
    assert isinstance(target, dict)
    target[path[-1]] = replacement
    proposal = KnowledgeAnalysisWorkerProposalV8.model_validate(proposal_value)
    request = KnowledgeAnalysisRequestV10.model_validate(_request_value())

    with pytest.raises(ValueError, match=message):
        validate_knowledge_solution_report_references(request, proposal)


def test_v10_report_rejects_non_contiguous_or_unmapped_reasoning_steps() -> None:
    proposal = deepcopy(_proposal_value())
    report = proposal["solution_report"]
    assert isinstance(report, dict)
    steps = report["solution_steps"]
    assert isinstance(steps, list)
    duplicate = deepcopy(steps[0])
    duplicate["step_id"] = "solutionstep_second"
    duplicate["ordinal"] = 3
    steps.append(duplicate)

    with pytest.raises(ValidationError, match="contiguous ordinals"):
        KnowledgeAnalysisWorkerProposalV8.model_validate(proposal)


class _SolutionReportReader:
    def __init__(self, report_bytes: bytes) -> None:
        self.report_bytes = report_bytes

    def read_member(self, **_: object) -> bytes:
        return self.report_bytes


def _solution_resolution_records() -> tuple[object, object, object, object, object, bytes]:
    request = _request_value()
    receipt = _receipt_value()
    report_value = _proposal_value()["solution_report"]
    assert isinstance(report_value, dict)
    report_bytes = canonical_json_bytes(report_value)
    report_hash = sha256_bytes(report_bytes)

    solution_member = receipt["solution_report"]
    assert isinstance(solution_member, dict)
    solution_member.update(
        {
            "artifact_id": "artifact_" + "c" * 32,
            "artifact_revision_id": "rev_" + "c" * 32,
            "sha256": report_hash,
            "bytes": len(report_bytes),
        }
    )
    base = receipt["base_analysis"]
    assert isinstance(base, dict)
    base_members = base["base_members"]
    assert isinstance(base_members, dict)
    descriptors = [*base_members.values(), solution_member]
    receipt["content_set_sha256"] = content_sha256(
        sorted(
            (
                {
                    key: member[key]
                    for key in (
                        "artifact_id",
                        "artifact_revision_id",
                        "member_path",
                        "sha256",
                        "bytes",
                        "schema_ref",
                        "media_type",
                    )
                }
                for member in descriptors
                if isinstance(member, dict)
            ),
            key=lambda value: str(value["member_path"]),
        )
    )
    receipt_model = KnowledgeAnalysisProposalReceiptV9.model_validate(receipt)
    receipt_bytes = canonical_json_bytes(receipt_model)
    receipt_hash = sha256_bytes(receipt_bytes)

    result = _result_value()
    result["proposal_content_set_sha256"] = receipt_model.content_set_sha256
    result["proposal_receipt"] = {
        "artifact_id": "artifact_" + "c" * 32,
        "artifact_revision_id": "rev_" + "c" * 32,
        "member_path": "normalized/proposal-receipt.json",
        "sha256": receipt_hash,
        "bytes": len(receipt_bytes),
        "schema_ref": ("eom://schemas/knowledge/knowledge-analysis-proposal-receipt/9.0"),
        "media_type": "application/json",
        "logical_name": "proposal-receipt.json",
    }
    result["result_sha256"] = content_sha256(
        {key: value for key, value in result.items() if key != "result_sha256"}
    )
    result_model = KnowledgeAnalysisResultV10.model_validate(result)
    result_bytes = canonical_json_bytes(result_model)
    result_hash = sha256_bytes(result_bytes)

    run = type(
        "Run",
        (),
        {
            "state": "ACCEPTED",
            "analysis_run_id": "analysisrun_" + "d" * 32,
            "analysis_request_id": request["analysis_request_id"],
            "request_sha256": request["request_sha256"],
            "canonical_request": request,
            "predecessor_analysis_run_id": "analysisrun_" + "a" * 32,
            "accepted_result_artifact_id": "artifact_" + "d" * 32,
            "accepted_result_artifact_revision_id": "rev_" + "d" * 32,
            "accepted_result_sha256": result_hash,
            "proposal_artifact_id": "artifact_" + "c" * 32,
            "proposal_artifact_revision_id": "rev_" + "c" * 32,
            "proposal_content_set_sha256": receipt_model.content_set_sha256,
        },
    )()
    accepted_revision = type(
        "Revision",
        (),
        {
            "revision_id": "rev_" + "d" * 32,
            "logical_artifact_id": "artifact_" + "d" * 32,
            "content_hash": result_hash,
            "content_bytes": len(result_bytes),
            "approved": True,
            "result": result_model.model_dump(mode="json"),
            "manifest": {
                "artifact_type": "knowledge-analysis-accepted-result",
                "primary_file": "evidence/accepted-result.json",
                "files": [
                    {
                        "file_name": "evidence/accepted-result.json",
                        "sha256": result_hash,
                        "bytes": len(result_bytes),
                        "schema_ref": ("eom://schemas/knowledge/knowledge-analysis-result/10.0"),
                        "media_type": "application/json",
                    }
                ],
            },
        },
    )()
    accepted_artifact = type(
        "Artifact",
        (),
        {"logical_artifact_id": "artifact_" + "d" * 32, "approved": True},
    )()
    proposal_revision = type(
        "Revision",
        (),
        {
            "revision_id": "rev_" + "c" * 32,
            "logical_artifact_id": "artifact_" + "c" * 32,
            "content_hash": receipt_hash,
            "content_bytes": len(receipt_bytes),
            "approved": True,
            "result": receipt_model.model_dump(mode="json"),
            "manifest": {
                "artifact_type": "knowledge-analysis-proposal",
                "primary_file": "normalized/proposal-receipt.json",
                "files": [
                    {
                        "file_name": "normalized/proposal-receipt.json",
                        "sha256": receipt_hash,
                        "bytes": len(receipt_bytes),
                        "schema_ref": (
                            "eom://schemas/knowledge/knowledge-analysis-proposal-receipt/9.0"
                        ),
                        "media_type": "application/json",
                    },
                    {
                        "file_name": "normalized/solution-report.json",
                        "sha256": report_hash,
                        "bytes": len(report_bytes),
                        "schema_ref": (
                            "eom://schemas/knowledge/knowledge-analysis-solution-report/1.0"
                        ),
                        "media_type": "application/json",
                    },
                ],
            },
        },
    )()
    proposal_artifact = type(
        "Artifact",
        (),
        {"logical_artifact_id": "artifact_" + "c" * 32, "approved": True},
    )()
    return (
        run,
        accepted_revision,
        accepted_artifact,
        proposal_revision,
        proposal_artifact,
        report_bytes,
    )


def test_solution_evidence_resolver_reconstructs_exact_pointer_and_report() -> None:
    *records, report_bytes = _solution_resolution_records()
    resolved = _resolve_row(
        cast(CatalogArtifactService, _SolutionReportReader(report_bytes)),
        cast(Any, tuple(records)),
    )
    assert resolved.pointer.base_analysis_run_id == "analysisrun_" + "a" * 32
    assert resolved.pointer.solution_analysis_run_id == "analysisrun_" + "d" * 32
    assert resolved.pointer.solution_report.sha256 == sha256_bytes(report_bytes)
    assert resolved.report.assessment_design_summary == "개념을 판단 기준으로 묻는 방식"


def test_solution_evidence_resolver_rejects_report_content_drift() -> None:
    *records, report_bytes = _solution_resolution_records()
    with pytest.raises(SolutionEvidenceResolutionError, match="solution evidence is invalid"):
        _resolve_row(
            cast(CatalogArtifactService, _SolutionReportReader(report_bytes + b"\n")),
            cast(Any, tuple(records)),
        )
