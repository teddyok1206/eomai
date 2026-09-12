from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from typing import Any, cast

import eom_catalog_service.knowledge_retrieval_service as retrieval_module
import pytest
from eom_catalog_contracts import (
    ApprovedItemKnowledgeSourceV2,
    ApprovedPastExamItemKnowledgeSourceV3,
    ContentIntakeKnowledgeSourceV2,
    CreateItemProductionEvidenceCommand,
    EducationRetrievalRequestV2,
    EvidenceBundleManifestV5,
    EvidenceBundleMaterialsV2,
    EvidenceEntryV5,
    KnowledgeAnalysisRequestV2,
    KnowledgeAnalysisSolutionReport,
    KnowledgeAnalysisSourceArtifactMemberV2,
    KnowledgeArtifactMemberPointer,
    KnowledgeSolutionEvidencePointer,
    validate_contract,
)
from eom_catalog_service.knowledge_graph_projection import knowledge_node_terms
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalApplicationService,
    KnowledgeRetrievalServiceError,
    _ArtifactMemberValidationKey,
    _bounded_seed_scores,
    _Candidate,
    _ImmutableSourcePointerKey,
    _rank_lexical_seed_rows,
    _RequestScopedArtifactValidationCache,
    _SnapshotSourceResolutionCache,
)
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.solution_evidence_resolution import ResolvedSolutionEvidence
from eom_identifiers import content_sha256
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from sqlalchemy.orm import Session

NOW = "2026-08-24T00:00:00Z"


def test_lexical_seed_ranking_prefers_distinct_term_overlap() -> None:
    assert _rank_lexical_seed_rows(
        (
            ("lithium", "knode_specific", 4),
            ("lithium", "knode_specific", 4),
            ("concept", "knode_specific", 2000),
            ("concept", "knode_generic", 2000),
            ("assessment", "knode_generic", 1000),
            ("pattern", "knode_generic", 1000),
            ("periodicity", "knode_tie_a", 5),
            ("periodicity", "knode_tie_b", 5),
        ),
        limit=3,
    ) == (
        ("knode_specific", 751),
        ("knode_tie_a", 700),
        ("knode_tie_b", 700),
    )


def test_seed_budget_preserves_strongest_scores_before_node_id() -> None:
    assert _bounded_seed_scores({"knode_a": 700, "knode_z": 1000, "knode_b": 950}, limit=2) == {
        "knode_z": 1000,
        "knode_b": 950,
    }


def _member(
    seed: str, *, media_type: str, schema_ref: str | None
) -> KnowledgeAnalysisSourceArtifactMemberV2:
    return KnowledgeAnalysisSourceArtifactMemberV2.model_validate(
        {
            "artifact_id": "artifact_" + seed * 32,
            "artifact_revision_id": "rev_" + seed * 32,
            "member_path": "source/content.json"
            if media_type == "application/json"
            else "source/book.md",
            "materialized_path": "source/content.json"
            if media_type == "application/json"
            else "source/book.md",
            "sha256": "sha256:" + seed * 64,
            "bytes": 512,
            "schema_ref": schema_ref,
            "media_type": media_type,
            "logical_name": "content.json" if media_type == "application/json" else "book.md",
        }
    )


def _request() -> EducationRetrievalRequestV2:
    value: dict[str, object] = {
        "schema_version": "education-retrieval-request/2.0",
        "retrieval_request_id": "retrieval_" + "1" * 32,
        "graph_snapshot": {
            "graph_id": "graph_" + "2" * 32,
            "graph_snapshot_revision_id": "graphrev_" + "3" * 32,
            "manifest_artifact": {
                "artifact_id": "artifact_" + "4" * 32,
                "artifact_revision_id": "rev_" + "4" * 32,
                "sha256": "sha256:" + "4" * 64,
                "schema_ref": "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/2.0",
                "media_type": "application/json",
                "logical_name": "manifest.json",
                "member_path": "projections/manifest.json",
            },
            "manifest_sha256": "sha256:" + "4" * 64,
        },
        "query_kind": "ITEM_PREPARATION",
        "curriculum_scope": None,
        "topic_keys": ["earth.plate-boundary"],
        "target_item_revision_id": None,
        "required_item_elements": [],
        "source_classes": ["APPROVED_ITEM", "TEXTBOOK"],
        "retrieval_mode": "HYBRID_LOCAL_MULTIHOP",
        "evidence_budget": {
            "max_documents": 2,
            "max_item_revisions": 1,
            "max_graph_nodes": 8,
            "max_claims": 2,
            "max_context_tokens": 2000,
        },
        "access_policy_revision_id": "accessrev_" + "5" * 32,
        "access_policy_sha256": "sha256:" + "5" * 64,
        "requester_role": "ADMIN",
        "requester_operator_id": "operator_" + "6" * 32,
        "requester_permission_keys": ["knowledge_graph:read", "knowledge_graph:retrieve"],
        "requester_permissions_sha256": content_sha256(
            {"permission_keys": ["knowledge_graph:read", "knowledge_graph:retrieve"]}
        ),
        "requested_at": NOW,
        "request_sha256": "sha256:" + "0" * 64,
    }
    value["request_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "request_sha256"}
    )
    return EducationRetrievalRequestV2.model_validate(value)


def test_lexical_terms_are_deterministic_bounded_and_shared_with_publication() -> None:
    assert knowledge_node_terms("earth.plate-boundary", "판 경계 Plate") == (
        "boundary",
        "earth",
        "plate",
        "경계",
    )
    assert knowledge_node_terms("x", "a") == ()
    assert all(len(term) <= 128 for term in knowledge_node_terms("x", "가" * 140))


def test_ranked_context_is_bounded_pointer_oriented_and_marks_answers_avoid_copy() -> None:
    document = ContentIntakeKnowledgeSourceV2(
        source_class="TEXTBOOK",
        intake_batch_id="intake_" + "7" * 32,
        source_file_id="sourcefile_" + "8" * 32,
        artifact_member=_member("8", media_type="text/markdown", schema_ref=None),
    )
    item = ApprovedItemKnowledgeSourceV2(
        source_class="APPROVED_ITEM",
        item_id="item_" + "9" * 32,
        item_revision_id="itemrev_" + "a" * 32,
        artifact_member=_member(
            "a", media_type="application/json", schema_ref="eom.assessment.item-content/1.0"
        ),
    )
    entries, markdown = KnowledgeRetrievalApplicationService._rank_and_render(
        request=_request(),
        candidates=(
            _Candidate(
                analysis_run_id="analysisrun_" + "1" * 32,
                source=document,
                node_ids=("knode_plate",),
                anchor_ids=("anchor_plate",),
                node_labels=("plate boundary",),
                node_types=("CONCEPT",),
                relevance_milli=950,
                answer_bearing=False,
            ),
            _Candidate(
                analysis_run_id="analysisrun_" + "2" * 32,
                source=item,
                node_ids=("knode_item",),
                anchor_ids=("anchor_item",),
                node_labels=("approved item answer pattern",),
                node_types=("ITEM_REVISION",),
                relevance_milli=900,
                answer_bearing=True,
            ),
        ),
    )
    assert tuple(entry.relevance_milli for entry in entries) == (950, 900)
    assert entries[0].use == "GROUNDING"
    assert entries[1].use == "AVOID_COPY"
    assert "nas://" not in markdown
    assert "/mnt/" not in markdown
    assert len(markdown.encode("utf-8")) < 64 * 1024


def test_one_shot_context_exposes_past_exam_identity_without_copying_payload() -> None:
    item = ApprovedItemKnowledgeSourceV2(
        source_class="PAST_EXAM",
        item_id="item_" + "b" * 32,
        item_revision_id="itemrev_" + "c" * 32,
        artifact_member=_member(
            "c", media_type="application/json", schema_ref="eom.assessment.item-content/1.0"
        ),
    )
    request = _request().model_copy(
        update={"source_classes": ("APPROVED_ITEM", "PAST_EXAM", "TEXTBOOK")}
    )

    entries, markdown = KnowledgeRetrievalApplicationService._rank_and_render(
        request=request,
        candidates=(
            _Candidate(
                analysis_run_id="analysisrun_" + "3" * 32,
                source=item,
                node_ids=("knode_exam", "knode_placement", "knode_unit"),
                anchor_ids=("anchor_item",),
                node_labels=(
                    "2025학년도 고1 6월 통합과학 전국연합학력평가",
                    "2025학년도 고1 6월 통합과학 전국연합학력평가 7번 문항",
                    "생태계와 환경 변화",
                ),
                node_types=(
                    "ASSESSMENT_OCCURRENCE_REVISION",
                    "ASSESSMENT_ITEM_OCCURRENCE",
                    "CURRICULUM_UNIT",
                ),
                relevance_milli=850,
                answer_bearing=False,
            ),
        ),
    )

    assert len(entries) == 1
    assert entries[0].source.source_class == "PAST_EXAM"
    assert "class=PAST_EXAM" in markdown
    assert "2025학년도 고1 6월" in markdown
    assert "7번 문항" in markdown
    assert "생태계와 환경 변화" in markdown
    assert item.artifact_member.member_path not in markdown


def _solution_evidence() -> ResolvedSolutionEvidence:
    def pointer(
        seed: str, *, member_path: str, logical_name: str, schema_ref: str
    ) -> dict[str, str]:
        return {
            "artifact_id": "artifact_" + seed * 32,
            "artifact_revision_id": "rev_" + seed * 32,
            "sha256": "sha256:" + seed * 64,
            "schema_ref": schema_ref,
            "media_type": "application/json",
            "logical_name": logical_name,
            "member_path": member_path,
        }

    pointer_value: dict[str, object] = {
        "schema_version": "knowledge-solution-evidence-pointer/1.0",
        "base_analysis_run_id": "analysisrun_" + "3" * 32,
        "base_analysis_result_id": "knowledgeanalysisresult_" + "4" * 32,
        "solution_analysis_run_id": "analysisrun_" + "5" * 32,
        "solution_analysis_result_id": "knowledgeanalysisresult_" + "6" * 32,
        "solution_result_sha256": "sha256:" + "6" * 64,
        "accepted_result_artifact": pointer(
            "6",
            member_path="evidence/accepted-result.json",
            logical_name="accepted-result.json",
            schema_ref="eom://schemas/knowledge/knowledge-analysis-result/10.0",
        ),
        "proposal_receipt": pointer(
            "7",
            member_path="normalized/proposal-receipt.json",
            logical_name="proposal-receipt.json",
            schema_ref=("eom://schemas/knowledge/knowledge-analysis-proposal-receipt/9.0"),
        ),
        "solution_report": pointer(
            "7",
            member_path="normalized/solution-report.json",
            logical_name="solution-report.json",
            schema_ref="eom://schemas/knowledge/knowledge-analysis-solution-report/1.0",
        ),
        "proposal_content_set_sha256": "sha256:" + "8" * 64,
        "pointer_sha256": "sha256:" + "0" * 64,
    }
    pointer_value["pointer_sha256"] = content_sha256(
        {key: value for key, value in pointer_value.items() if key != "pointer_sha256"}
    )
    report = KnowledgeAnalysisSolutionReport.model_validate(
        {
            "schema_version": "knowledge-analysis-solution-report/1.0",
            "analysis_request_id": "knowledgeanalysis_" + "5" * 32,
            "base_analysis_result_id": "knowledgeanalysisresult_" + "4" * 32,
            "rationale_kind": "VERIFIABLE_SOLUTION_RATIONALE",
            "solution_steps": [
                {
                    "step_id": "solutionstep_conclusion",
                    "ordinal": 1,
                    "operation": "CONCLUDE",
                    "rationale": "ANSWER_BEARING_RATIONALE_MUST_NOT_LEAK",
                    "outcome": "conclusion",
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
                    "summary": "concept link",
                }
            ],
            "choice_diagnostics": [],
            "official_explanation_comparison": {
                "status": "CONSISTENT",
                "summary": "official comparison",
                "answer_explanation_anchor_ids": ["anchor_answer"],
            },
            "final_answer_summary": "FINAL_ANSWER_MUST_NOT_LEAK",
            "solution_summary": "SOLUTION_SUMMARY_MUST_NOT_LEAK",
            "assessment_design_summary": "판단 기준을 새로운 맥락에 적용한다.",
            "reusable_generation_guidance": "원문을 복제하지 않고 조건을 변형한다.",
            "unresolved_issues": [],
            "general_knowledge_used": False,
        }
    )
    return ResolvedSolutionEvidence(
        pointer=KnowledgeSolutionEvidencePointer.model_validate(pointer_value),
        report=report,
    )


def test_solution_enriched_context_exposes_only_reusable_design_projection() -> None:
    item = ApprovedItemKnowledgeSourceV2(
        source_class="PAST_EXAM",
        item_id="item_" + "b" * 32,
        item_revision_id="itemrev_" + "c" * 32,
        artifact_member=_member(
            "c", media_type="application/json", schema_ref="eom.assessment.item-content/1.0"
        ),
    )
    solution = _solution_evidence()
    entries, markdown = KnowledgeRetrievalApplicationService._rank_and_render(
        request=_request().model_copy(
            update={"source_classes": ("APPROVED_ITEM", "PAST_EXAM", "TEXTBOOK")}
        ),
        candidates=(
            _Candidate(
                analysis_run_id=solution.pointer.base_analysis_run_id,
                source=item,
                node_ids=("knode_exam",),
                anchor_ids=("anchor_item",),
                node_labels=("past exam structure",),
                node_types=("ASSESSMENT_PATTERN",),
                relevance_milli=900,
                answer_bearing=False,
                solution=solution,
            ),
        ),
    )
    assert len(entries) == 1
    assert isinstance(entries[0], EvidenceEntryV5)
    assert entries[0].solution_evidence == solution.pointer
    assert solution.report.assessment_design_summary in markdown
    assert solution.report.reusable_generation_guidance in markdown
    assert solution.report.final_answer_summary not in markdown
    assert solution.report.solution_summary not in markdown
    assert solution.report.solution_steps[0].rationale not in markdown

    materials = EvidenceBundleMaterialsV2(
        context_markdown=KnowledgeArtifactMemberPointer(
            artifact_id="artifact_" + "9" * 32,
            artifact_revision_id="rev_" + "9" * 32,
            sha256="sha256:" + "9" * 64,
            schema_ref="eom://schemas/knowledge/evidence-bundle-context/1.0",
            media_type="text/markdown",
            logical_name="context.md",
            member_path="evidence/context.md",
        )
    )
    request = _request()
    manifest_value: dict[str, object] = {
        "schema_version": "evidence-bundle-manifest/5.0",
        "evidence_bundle_id": "evidence_" + "a" * 32,
        "evidence_bundle_revision_id": "evidencerev_" + "a" * 32,
        "revision_number": 1,
        "retrieval_request_id": request.retrieval_request_id,
        "retrieval_request_sha256": request.request_sha256,
        "graph_snapshot": request.graph_snapshot.model_dump(mode="json"),
        "access_policy_revision_id": request.access_policy_revision_id,
        "access_policy_sha256": request.access_policy_sha256,
        "requester_permissions_sha256": request.requester_permissions_sha256,
        "materials": materials.model_dump(mode="json"),
        "entries": [entry.model_dump(mode="json") for entry in entries],
        "budget": {
            "document_count": 0,
            "item_revision_count": 1,
            "graph_node_count": 1,
            "claim_count": 0,
            "estimated_context_tokens": 100,
        },
        "manifest_sha256": "sha256:" + "0" * 64,
        "created_at": NOW,
    }
    manifest_value["manifest_sha256"] = content_sha256(
        {key: value for key, value in manifest_value.items() if key != "manifest_sha256"}
    )
    validate_contract("evidence-bundle-manifest-v5", manifest_value)
    assert EvidenceBundleManifestV5.model_validate(manifest_value).entries == entries


def test_solution_evidence_pointer_rejects_member_or_hash_drift() -> None:
    value = _solution_evidence().pointer.model_dump(mode="json")
    report_pointer = dict(value["solution_report"])
    report_pointer["member_path"] = "normalized/document.md"
    value["solution_report"] = report_pointer
    with pytest.raises(ValueError, match="solution evidence pointers"):
        KnowledgeSolutionEvidencePointer.model_validate(value)

    value = _solution_evidence().pointer.model_dump(mode="json")
    value["pointer_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="pointer hash"):
        KnowledgeSolutionEvidencePointer.model_validate(value)


def test_ranked_context_orders_equal_relevance_entries_by_evidence_id() -> None:
    first_candidate_second_id = ContentIntakeKnowledgeSourceV2(
        source_class="TEXTBOOK",
        intake_batch_id="intake_" + "7" * 32,
        source_file_id="sourcefile_" + "b" * 32,
        artifact_member=_member("b", media_type="text/markdown", schema_ref=None),
    )
    second_candidate_first_id = ContentIntakeKnowledgeSourceV2(
        source_class="TEXTBOOK",
        intake_batch_id="intake_" + "8" * 32,
        source_file_id="sourcefile_" + "a" * 32,
        artifact_member=_member("a", media_type="text/markdown", schema_ref=None),
    )

    entries, markdown = KnowledgeRetrievalApplicationService._rank_and_render(
        request=_request(),
        candidates=(
            _Candidate(
                analysis_run_id="analysisrun_" + "1" * 32,
                source=first_candidate_second_id,
                node_ids=("knode_plate_b",),
                anchor_ids=("anchor_plate_b",),
                node_labels=("second evidence id",),
                node_types=("CONCEPT",),
                relevance_milli=950,
                answer_bearing=False,
            ),
            _Candidate(
                analysis_run_id="analysisrun_" + "2" * 32,
                source=second_candidate_first_id,
                node_ids=("knode_plate_a",),
                anchor_ids=("anchor_plate_a",),
                node_labels=("first evidence id",),
                node_types=("CONCEPT",),
                relevance_milli=950,
                answer_bearing=False,
            ),
        ),
    )

    evidence_ids = tuple(entry.evidence_id for entry in entries)
    assert evidence_ids == tuple(sorted(evidence_ids))
    context_ids = tuple(
        line.split("`", 2)[1]
        for line in markdown.splitlines()
        if line.startswith("- `evidenceitem_")
    )
    assert context_ids == evidence_ids


def test_ranked_context_selects_one_exact_range_per_immutable_document() -> None:
    document = ContentIntakeKnowledgeSourceV2(
        source_class="TEXTBOOK",
        intake_batch_id="intake_" + "7" * 32,
        source_file_id="sourcefile_" + "8" * 32,
        artifact_member=_member("8", media_type="text/markdown", schema_ref=None),
    )
    same_artifact_from_another_revision = ContentIntakeKnowledgeSourceV2(
        source_class="TEXTBOOK",
        intake_batch_id="intake_" + "9" * 32,
        source_file_id="sourcefile_" + "a" * 32,
        artifact_member=_member("8", media_type="text/markdown", schema_ref=None),
    )
    entries, _ = KnowledgeRetrievalApplicationService._rank_and_render(
        request=_request(),
        candidates=(
            _Candidate(
                analysis_run_id="analysisrun_" + "1" * 32,
                source=same_artifact_from_another_revision,
                node_ids=("knode_first",),
                anchor_ids=("anchor_first",),
                node_labels=("first range",),
                node_types=("CONCEPT",),
                relevance_milli=950,
                answer_bearing=False,
            ),
            _Candidate(
                analysis_run_id="analysisrun_" + "2" * 32,
                source=document,
                node_ids=("knode_second",),
                anchor_ids=("anchor_second",),
                node_labels=("second range",),
                node_types=("CONCEPT",),
                relevance_milli=900,
                answer_bearing=False,
            ),
        ),
    )

    assert len(entries) == 1
    assert entries[0].graph_node_ids == ("knode_first",)
    assert entries[0].anchor_ids == ("anchor_first",)


class _SequenceSession:
    def __init__(self, scalar_values: list[object | None]) -> None:
        self.scalar_values = iter(scalar_values)

    def __enter__(self) -> _SequenceSession:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def scalar(self, _statement: object) -> object | None:
        return next(self.scalar_values)

    def get(self, _model: type[object], _identity: str) -> None:
        return None


def _item_production_command() -> CreateItemProductionEvidenceCommand:
    value = {
        "operation": "CREATE_ITEM_PRODUCTION_EVIDENCE",
        "requirement": {
            "schema_version": "educational-retrieval-requirement/1.0",
            "corpus_key": "science-core",
            "query_kind": "ITEM_PREPARATION",
            "curriculum_root_key": None,
            "topic_keys": ["earth.plate-boundary"],
            "required_item_elements": ["statement_set", "table"],
            "source_classes": ["APPROVED_ITEM", "TEXTBOOK"],
        },
        "evidence_budget": {
            "max_documents": 2,
            "max_item_revisions": 2,
            "max_graph_nodes": 8,
            "max_claims": 2,
            "max_context_tokens": 2000,
        },
        "access_policy_revision_id": "accessrev_" + "5" * 32,
        "access_policy_sha256": "sha256:" + "5" * 64,
        "requester_role": "ADMIN",
        "requester_permission_keys": ["knowledge_graph:read", "knowledge_graph:retrieve"],
        "requested_by": "operator_" + "6" * 32,
        "idempotency_key": "knowledge-backed-item-miss",
        "submission_sha256": "sha256:" + "0" * 64,
    }
    value["submission_sha256"] = content_sha256(
        {
            key: item
            for key, item in value.items()
            if key not in {"idempotency_key", "submission_sha256"}
        }
    )
    return CreateItemProductionEvidenceCommand.model_validate(value)


def test_item_production_graph_miss_fails_before_artifact_or_retrieval_creation() -> None:
    service = object.__new__(KnowledgeRetrievalApplicationService)
    cast(Any, service).sessions = lambda: _SequenceSession([None, None])
    created = False

    def create(_command: object) -> object:
        nonlocal created
        created = True
        raise AssertionError("graph miss must not create an Evidence Bundle")

    cast(Any, service).create = create
    with pytest.raises(KnowledgeRetrievalServiceError) as captured:
        service.create_item_production(_item_production_command())
    assert captured.value.code == "KNOWLEDGE_RETRIEVAL_CORPUS_UNAVAILABLE"
    assert not created


def test_item_production_private_idempotency_rejects_different_input() -> None:
    command = _item_production_command()
    base = _request().model_dump(mode="json")
    base["required_item_elements"] = list(command.requirement.required_item_elements)
    base["evidence_budget"] = command.evidence_budget.model_dump(mode="json")
    base["request_sha256"] = content_sha256(
        {key: item for key, item in base.items() if key != "request_sha256"}
    )
    request = EducationRetrievalRequestV2.model_validate(base)
    record = SimpleNamespace(canonical_request=request.model_dump(mode="json"))

    class ReplaySession:
        def scalar(self, _statement: object) -> object:
            return SimpleNamespace(graph_id=request.graph_snapshot.graph_id)

    KnowledgeRetrievalApplicationService._validate_item_production_replay(
        ReplaySession(),  # type: ignore[arg-type]
        command,
        record,  # type: ignore[arg-type]
    )
    changed = command.model_copy(
        update={
            "requirement": command.requirement.model_copy(update={"topic_keys": ("earth.volcano",)})
        }
    )
    with pytest.raises(KnowledgeRetrievalServiceError) as captured:
        KnowledgeRetrievalApplicationService._validate_item_production_replay(
            ReplaySession(),  # type: ignore[arg-type]
            changed,
            record,  # type: ignore[arg-type]
        )
    assert captured.value.code == "KNOWLEDGE_RETRIEVAL_IDEMPOTENCY_CONFLICT"


class _BulkSourceSession:
    def __init__(self, associations: tuple[object, ...], runs: tuple[object, ...]) -> None:
        self._responses = iter((associations, runs))
        self.query_count = 0

    def scalars(self, _statement: object) -> tuple[object, ...]:
        self.query_count += 1
        return next(self._responses)


def test_snapshot_source_preload_query_count_is_constant_for_repeated_pointers() -> None:
    run_ids = tuple(f"analysisrun_{index:032x}" for index in range(64))
    pointers = tuple(
        SimpleNamespace(analysis_run_id=run_ids[index % len(run_ids)]) for index in range(256)
    )
    associations = tuple(SimpleNamespace(analysis_run_id=run_id) for run_id in reversed(run_ids))
    runs = tuple(SimpleNamespace(analysis_run_id=run_id) for run_id in run_ids)
    session = _BulkSourceSession(associations, runs)
    delegate = SimpleNamespace()
    service = object.__new__(KnowledgeRetrievalApplicationService)
    cast(Any, service).artifacts = delegate

    cache = service._snapshot_source_resolution_cache(
        cast(Session, session),
        "graphrev_" + "a" * 32,
        cast(Any, pointers),
    )

    assert session.query_count == 2
    assert set(cache.associations_by_run_id) == set(run_ids)
    assert set(cache.runs_by_id) == set(run_ids)


class _CountingArtifactService:
    def __init__(self) -> None:
        self.settings = CatalogSettings()
        self.read_count = 0
        self.verify_count = 0
        self.fail_next_read = False

    def read_member(self, **_kwargs: object) -> bytes:
        self.read_count += 1
        if self.fail_next_read:
            self.fail_next_read = False
            raise ValueError("invalid immutable member")
        return b'{"validated":true}'

    def verify_member(self, **_kwargs: object) -> None:
        self.verify_count += 1


def test_past_exam_resolution_cache_preserves_artifact_settings_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delegate = _CountingArtifactService()
    cache = _SnapshotSourceResolutionCache(
        associations_by_run_id={},
        runs_by_id={},
        artifacts=_RequestScopedArtifactValidationCache(delegate),
    )
    source = ApprovedPastExamItemKnowledgeSourceV3.model_construct(
        source_class="PAST_EXAM",
        item_id="item_" + "1" * 32,
        item_revision_id="itemrev_" + "2" * 32,
        artifact_member=_member(
            "3",
            media_type="application/json",
            schema_ref="eom.assessment.item-content/1.0",
        ),
    )

    def resolve_past_exam(
        _session: Session,
        *,
        artifacts: Any,
        item_revision_id: str,
        source_class: str,
    ) -> ApprovedPastExamItemKnowledgeSourceV3:
        # Corrected legacy media resolution dereferences this exact storage boundary.
        assert artifacts.settings is delegate.settings
        assert item_revision_id == source.item_revision_id
        assert source_class == "PAST_EXAM"
        return source

    monkeypatch.setattr(
        retrieval_module,
        "resolve_historically_approved_item_source",
        resolve_past_exam,
    )

    assert (
        KnowledgeRetrievalApplicationService._resolve_declared_source(
            cast(Session, SimpleNamespace()),
            source,
            cache=cache,
        )
        is source
    )


def _artifact_member_arguments() -> dict[str, object]:
    return {
        "artifact_id": "artifact_" + "1" * 32,
        "revision_id": "rev_" + "2" * 32,
        "member_path": "evidence/result.json",
        "sha256": "sha256:" + "3" * 64,
        "media_type": "application/json",
        "schema_ref": "eom://schemas/test/result/1.0",
        "max_bytes": 1024,
    }


def test_artifact_validation_cache_is_exact_success_only_and_request_scoped() -> None:
    delegate = _CountingArtifactService()
    first_request = _RequestScopedArtifactValidationCache(cast(Any, delegate))
    arguments = _artifact_member_arguments()

    delegate.fail_next_read = True
    with pytest.raises(ValueError, match="invalid immutable member"):
        first_request.read_member(**arguments)  # type: ignore[arg-type]
    assert first_request.read_member(**arguments) == b'{"validated":true}'  # type: ignore[arg-type]
    assert first_request.read_member(**arguments) == b'{"validated":true}'  # type: ignore[arg-type]
    assert delegate.read_count == 2

    changed_limit = {**arguments, "max_bytes": 2048}
    assert first_request.read_member(**changed_limit) == b'{"validated":true}'  # type: ignore[arg-type]
    assert delegate.read_count == 3

    first_request.verify_member(**arguments)  # type: ignore[arg-type]
    first_request.verify_member(**arguments)  # type: ignore[arg-type]
    assert delegate.verify_count == 0

    second_request = _RequestScopedArtifactValidationCache(cast(Any, delegate))
    assert second_request.read_member(**arguments) == b'{"validated":true}'  # type: ignore[arg-type]
    assert delegate.read_count == 4


def _content_intake_analysis_request(
    source: ContentIntakeKnowledgeSourceV2,
) -> KnowledgeAnalysisRequestV2:
    value: dict[str, object] = {
        "schema_version": "knowledge-analysis-request/2.0",
        "predecessor_analysis_run_id": None,
        "analysis_request_id": "knowledgeanalysis_" + "4" * 32,
        "source": source.model_dump(mode="json"),
        "execution_preset_id": "execpreset_" + "5" * 32,
        "execution_preset_revision_id": "execpresetrev_" + "6" * 32,
        "execution_preset_sha256": "sha256:" + "7" * 64,
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
        "risk_policy_revision_id": "analysisriskrev_" + "8" * 32,
        "created_at": NOW,
        "request_sha256": "sha256:" + "0" * 64,
    }
    value["request_sha256"] = content_sha256(
        {key: member for key, member in value.items() if key != "request_sha256"}
    )
    return KnowledgeAnalysisRequestV2.model_validate(value)


def test_snapshot_source_cache_reuses_run_but_rejects_changed_exact_pointer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = ContentIntakeKnowledgeSourceV2(
        source_class="TEXTBOOK",
        intake_batch_id="intake_" + "9" * 32,
        source_file_id="sourcefile_" + "a" * 32,
        artifact_member=_member("b", media_type="text/markdown", schema_ref=None),
    )
    request = _content_intake_analysis_request(source)
    run_id = "analysisrun_" + "c" * 32
    run = SimpleNamespace(
        analysis_run_id=run_id,
        state="ACCEPTED",
        canonical_request=request.model_dump(mode="json"),
    )
    association = SimpleNamespace(
        analysis_run_id=run_id,
        source_revision_id=source.source_file_id,
    )
    pointer = SimpleNamespace(
        analysis_run_id=run_id,
        source_revision_id=source.source_file_id,
        source_class=source.source_class,
        source_artifact_id=source.artifact_member.artifact_id,
        artifact_revision_id=source.artifact_member.artifact_revision_id,
        source_sha256=source.artifact_member.sha256,
        member_path=source.artifact_member.member_path,
    )
    cache = _SnapshotSourceResolutionCache(
        associations_by_run_id={run_id: cast(Any, association)},
        runs_by_id={run_id: cast(KnowledgeAnalysisRunRecord, run)},
        artifacts=cast(Any, SimpleNamespace()),
    )
    calls = 0

    def resolve_source(_session: Session, **_kwargs: object) -> ContentIntakeKnowledgeSourceV2:
        nonlocal calls
        calls += 1
        return source

    monkeypatch.setattr(retrieval_module, "resolve_content_intake_source", resolve_source)
    service = object.__new__(KnowledgeRetrievalApplicationService)
    snapshot_id = "graphrev_" + "d" * 32

    first = service._resolve_snapshot_source(
        cast(Session, SimpleNamespace()),
        snapshot_id,
        cast(Any, pointer),
        cache=cache,
    )
    replay = service._resolve_snapshot_source(
        cast(Session, SimpleNamespace()),
        snapshot_id,
        cast(Any, pointer),
        cache=cache,
    )

    assert first == replay == source
    assert calls == 1
    assert len(cache.validated_sources_by_pointer) == 1
    assert next(iter(cache.validated_sources_by_pointer)) == _ImmutableSourcePointerKey.from_record(
        snapshot_id, cast(Any, pointer)
    )

    changed = SimpleNamespace(**{**vars(pointer), "source_sha256": "sha256:" + "e" * 64})
    with pytest.raises(KnowledgeRetrievalServiceError) as captured:
        service._resolve_snapshot_source(
            cast(Session, SimpleNamespace()),
            snapshot_id,
            cast(Any, changed),
            cache=cache,
        )
    assert captured.value.code == "KNOWLEDGE_RETRIEVAL_SOURCE_HASH_MISMATCH"
    assert calls == 1
    assert len(cache.validated_sources_by_pointer) == 1


def test_artifact_member_validation_key_separates_every_security_field() -> None:
    base = _ArtifactMemberValidationKey(
        artifact_id="artifact_" + "1" * 32,
        artifact_revision_id="rev_" + "2" * 32,
        member_path="result.json",
        sha256="sha256:" + "3" * 64,
        media_type="application/json",
        schema_ref="eom://schemas/test/result/1.0",
        max_bytes=1024,
    )
    assert (
        len(
            {
                base,
                dataclasses.replace(base, artifact_id="artifact_" + "4" * 32),
                dataclasses.replace(base, artifact_revision_id="rev_" + "4" * 32),
                dataclasses.replace(base, member_path="other.json"),
                dataclasses.replace(base, sha256="sha256:" + "4" * 64),
                dataclasses.replace(base, media_type="text/plain"),
                dataclasses.replace(base, schema_ref="eom://schemas/test/result/2.0"),
                dataclasses.replace(base, max_bytes=2048),
            }
        )
        == 8
    )
