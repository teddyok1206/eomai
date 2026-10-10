"""Synthetic protocol fixtures, never accepted exam data or educational evaluation evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from eom_catalog_contracts.item_inference_transfer import (
    InferenceTransferProfile,
    InferenceTransferProfilePointer,
    InferenceTransferSourceBasis,
    LocalEmbeddingModelSpec,
    PairComparisonRequest,
    PairComparisonResult,
)
from eom_catalog_contracts.knowledge import KnowledgeAnalysisSolutionReport
from eom_identifiers import content_sha256

NOW = datetime(2026, 10, 10, 9, tzinfo=UTC)


def sha(seed: str = "a") -> str:
    return "sha256:" + seed * 64


def source_basis() -> InferenceTransferSourceBasis:
    def member(seed: str, name: str, path: str, schema: str) -> dict[str, str]:
        return {
            "artifact_id": "artifact_" + seed * 32,
            "artifact_revision_id": "rev_" + seed * 32,
            "sha256": sha(seed),
            "schema_ref": schema,
            "media_type": "application/json",
            "logical_name": name,
            "member_path": path,
        }

    solution: dict[str, Any] = {
        "schema_version": "knowledge-solution-evidence-pointer/1.0",
        "base_analysis_run_id": "analysisrun_" + "3" * 32,
        "base_analysis_result_id": "knowledgeanalysisresult_" + "4" * 32,
        "solution_analysis_run_id": "analysisrun_" + "5" * 32,
        "solution_analysis_result_id": "knowledgeanalysisresult_" + "6" * 32,
        "solution_result_sha256": sha("6"),
        "accepted_result_artifact": member(
            "6",
            "accepted-result.json",
            "evidence/accepted-result.json",
            "eom://schemas/knowledge/knowledge-analysis-result/10.0",
        ),
        "proposal_receipt": member(
            "7",
            "proposal-receipt.json",
            "normalized/proposal-receipt.json",
            "eom://schemas/knowledge/knowledge-analysis-proposal-receipt/9.0",
        ),
        "solution_report": member(
            "7",
            "solution-report.json",
            "normalized/solution-report.json",
            "eom://schemas/knowledge/knowledge-analysis-solution-report/1.0",
        ),
        "proposal_content_set_sha256": sha("8"),
    }
    solution["pointer_sha256"] = content_sha256(solution)
    return InferenceTransferSourceBasis.model_validate(
        {
            "source": {
                "source_kind": "APPROVED_ITEM_REVISION",
                "source_class": "PAST_EXAM",
                "item_id": "item_" + "b" * 32,
                "item_revision_id": "itemrev_" + "c" * 32,
                "lifecycle_state": "APPROVED",
                "artifact_member": member(
                    "c", "item.json", "source/item.json", "eom.assessment.item-content/1.0"
                )
                | {
                    "materialized_path": "source/item.json",
                    "bytes": 1,
                },
            },
            "graph_snapshot": {
                "graph_id": "graph_" + "e" * 32,
                "graph_snapshot_revision_id": "graphrev_" + "e" * 32,
                "manifest_artifact": member(
                    "e",
                    "graph.json",
                    "evidence/graph.json",
                    "eom://schemas/knowledge/graph-snapshot-manifest/9.0",
                ),
                "manifest_sha256": sha("e"),
            },
            "solution_evidence": solution,
        }
    )


def report(
    condition: str = "마찰이 없고 속력은 36 km/h이다.",
    inference: str = "외력이 한 일이 없으므로 역학적 에너지의 합이 일정하다.",
) -> KnowledgeAnalysisSolutionReport:
    value: dict[str, Any] = {
        "schema_version": "knowledge-analysis-solution-report/1.0",
        "analysis_request_id": "knowledgeanalysis_" + "5" * 32,
        "base_analysis_result_id": "knowledgeanalysisresult_" + "4" * 32,
        "rationale_kind": "VERIFIABLE_SOLUTION_RATIONALE",
        "choice_diagnostics": [],
        "official_explanation_comparison": {
            "status": "CONSISTENT",
            "summary": "합성 해설 비교",
            "answer_explanation_anchor_ids": ["anchor_answer"],
        },
        "final_answer_summary": "합성 정답",
        "solution_summary": "합성 풀이 요약",
        "assessment_design_summary": "합성 출제 요소",
        "reusable_generation_guidance": "합성 비교 지침",
        "unresolved_issues": [],
        "general_knowledge_used": False,
    }
    step = {
        "depends_on_step_ids": [],
        "node_ids": ["knode_concept_motion"],
        "item_element_node_ids": ["knode_item_element_stem"],
        "anchor_ids": ["anchor_problem"],
    }
    value["solution_steps"] = [
        step
        | {
            "step_id": "solutionstep_condition",
            "ordinal": 1,
            "operation": "INTERPRET_GIVEN",
            "rationale": condition,
            "outcome": "보존 조건과 속력의 단위를 확인한다.",
        },
        step
        | {
            "step_id": "solutionstep_decisive",
            "ordinal": 2,
            "operation": "CONCLUDE",
            "rationale": inference,
            "outcome": "에너지 관계로 요구된 판단을 한다.",
            "depends_on_step_ids": ["solutionstep_condition"],
        },
    ]
    link = {
        "concept_node_id": "knode_concept_motion",
        "assessment_pattern_node_ids": [],
        "item_element_node_ids": ["knode_item_element_stem"],
        "summary": "합성 개념 연결",
    }
    value["concept_assessment_links"] = [
        link | {"role": "GIVEN_INTERPRETATION", "reasoning_step_ids": ["solutionstep_condition"]},
        link | {"role": "INFERENCE_OPERATION", "reasoning_step_ids": ["solutionstep_decisive"]},
    ]
    return KnowledgeAnalysisSolutionReport.model_validate(value)


def profile(
    seed: str = "a", *, condition: str | None = None, inference: str | None = None
) -> InferenceTransferProfile:
    basis = source_basis()
    resolved = report() if condition is None else report(condition, inference or "조건에 따른 추론")
    claims = []
    for name, facet, step in zip(
        ("condition", "decisive"),
        ("GIVEN_CONDITION", "DECISIVE_INFERENCE"),
        resolved.solution_steps,
        strict=True,
    ):
        claims.append(
            {
                "claim_id": "transferclaim_" + name,
                "facet": facet,
                "text": step.rationale,
                "reasoning_step_ids": [step.step_id],
                "node_ids": list(step.node_ids),
                "anchor_ids": list(step.anchor_ids),
                "inferred": name == "decisive",
            }
        )
    value: dict[str, Any] = {
        "schema_version": "item-inference-transfer-profile/1.0",
        "profile_id": "inferenceprofile_" + seed * 32,
        "profile_revision_id": "inferenceprofilerev_" + seed * 32,
        "source_basis": basis.model_dump(mode="json"),
        "claims": claims,
        "limitations": ["핵심 착상의 후보이며 사람의 전이 평가는 수행하지 않았다."],
        "extraction": {
            "method": "DETERMINISTIC_REPORT_PROJECTION",
            "extractor_version": "synthetic-fixture/1.0",
            "prompt_sha256": None,
            "model_id": None,
            "runtime_sha256": None,
        },
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    value["profile_sha256"] = content_sha256(value)
    return InferenceTransferProfile.model_validate(value)


def request(
    left: InferenceTransferProfile | None = None, right: InferenceTransferProfile | None = None
) -> PairComparisonRequest:
    a, b = left or profile("a"), right or profile("b")
    value: dict[str, Any] = {
        "schema_version": "item-inference-transfer-pair-request/1.0",
        "request_id": "transferrequest_" + "1" * 32,
        "left_profile": InferenceTransferProfilePointer.from_profile(a).model_dump(mode="json"),
        "right_profile": InferenceTransferProfilePointer.from_profile(b).model_dump(mode="json"),
        "direction": "A_TO_B",
        "rubric": {
            "rubric_id": "transferrubric_" + "2" * 32,
            "rubric_revision_id": "transferrubricrev_" + "3" * 32,
            "rubric_sha256": sha("4"),
        },
        "left_claim_ids": [claim.claim_id for claim in a.claims],
        "right_claim_ids": [claim.claim_id for claim in b.claims],
    }
    value["request_sha256"] = content_sha256(value)
    return PairComparisonRequest.model_validate(value)


def result(query: PairComparisonRequest | None = None) -> PairComparisonResult:
    value = (query or request()).model_dump(
        mode="json", exclude={"left_claim_ids", "right_claim_ids"}
    )
    value.update(
        {
            "schema_version": "item-inference-transfer-pair-result/1.0",
            "judgement": "STRUCTURAL_ANALOGY",
            "mappings": [
                {
                    "mapping_id": "transfermapping_condition",
                    "facet": "GIVEN_CONDITION",
                    "left_claim_ids": ["transferclaim_condition"],
                    "right_claim_ids": ["transferclaim_condition"],
                    "explanation": "보존 조건이 대응한다.",
                },
                {
                    "mapping_id": "transfermapping_decisive",
                    "facet": "DECISIVE_INFERENCE",
                    "left_claim_ids": ["transferclaim_decisive"],
                    "right_claim_ids": ["transferclaim_decisive"],
                    "explanation": "합이 일정한 관계를 쓴다.",
                },
            ],
            "shared_idea": "조건으로 보존되는 관계를 먼저 찾는다.",
            "differences": [],
            "new_reasoning": [],
            "limitations": ["합성 계약 테스트일 뿐 교육적 검증은 아니다."],
            "assessment_kind": "MACHINE_HYPOTHESIS_NOT_HUMAN_VERIFICATION",
        }
    )
    value["result_sha256"] = content_sha256(value)
    return PairComparisonResult.model_validate(value)


def embedding_model(repo: str = "BAAI/bge-m3") -> LocalEmbeddingModelSpec:
    dimensions = {
        "BAAI/bge-m3": 1024,
        "intfloat/multilingual-e5-small": 384,
        "intfloat/multilingual-e5-base": 768,
    }
    prefix = "" if repo == "BAAI/bge-m3" else "query: "
    value: dict[str, Any] = {
        "schema_version": "item-local-embedding-model-spec/1.0",
        "model_id": "embeddingmodel_" + "a" * 32,
        "model_revision_id": "embeddingmodelrev_" + "b" * 32,
        "provider_family": "transformers-local-dense/1.0",
        "upstream_repo": repo,
        "upstream_revision": "a" * 40,
        "license_id": "MIT",
        "dimension": dimensions[repo],
        "maximum_tokens": 8192 if repo == "BAAI/bge-m3" else 512,
        "pooling": "CLS" if repo == "BAAI/bge-m3" else "MEAN",
        "normalization": "L2",
        "dtype": "float32",
        "query_prefix": prefix,
        "document_prefix": prefix,
        "truncation": "REJECT_OVERFLOW",
        "files": [
            {"member_path": name, "sha256": sha(), "size_bytes": 1}
            for name in sorted(
                (
                    "config.json",
                    "model.safetensors",
                    "tokenizer.json",
                    "tokenizer_config.json",
                    "special_tokens_map.json",
                )
            )
        ],
        "runtime_versions": [
            {"name": name, "version": "1.0.0"}
            for name in sorted(("torch", "transformers", "safetensors", "tokenizers"))
        ],
    }
    value["manifest_sha256"] = content_sha256(value)
    return LocalEmbeddingModelSpec.model_validate(value)
