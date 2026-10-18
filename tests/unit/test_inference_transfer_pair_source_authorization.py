"""Catalog pair-source checks with mocked official reads, no DB/NAS/model calls."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, Mock

import eom_catalog_service.inference_transfer_catalog_adapter as adapter_module
import pytest
from eom_catalog_contracts import (
    ApprovedPastExamItemKnowledgeSourceV3,
    KnowledgeAnalysisResultV10,
    KnowledgeAnalysisSolutionReport,
)
from eom_catalog_contracts.item_inference_transfer import (
    InferenceTransferProfile,
    InferenceTransferSourceBasis,
)
from eom_catalog_service.inference_transfer_catalog_adapter import (
    CatalogInferenceTransferSourceAdapter,
)
from eom_catalog_service.inference_transfer_projection import project_accepted_solution_report
from eom_catalog_service.inference_transfer_scope import InferenceTransferPopulationScope
from eom_catalog_service.inference_transfer_service import (
    InferenceTransferSearchCommand,
    InferenceTransferServiceError,
)
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalCandidate,
    ReadOnlyKnowledgeCandidatePool,
)
from eom_catalog_service.solution_evidence_resolution import (
    ResolvedSolutionEvidence,
    SolutionEvidenceResolutionError,
)
from eom_identifiers import content_sha256
from eom_operator_identity import PermissionKey
from pydantic import ValidationError

from tests.unit.inference_transfer_fixtures import NOW, report, sha, source_basis


def member(seed: str, path: str, schema: str, media: str = "application/json") -> dict[str, Any]:
    value = {
        "artifact_id": "artifact_" + seed * 32,
        "artifact_revision_id": "rev_" + seed * 32,
        "member_path": path,
        "sha256": sha(seed),
        "schema_ref": "eom://schemas/" + schema,
        "media_type": media,
    }
    if schema.startswith("knowledge/"):
        value["logical_name"] = path.rsplit("/", 1)[-1]
    return value


def accepted_input(seed: str):
    """Self-contained valid V10 metadata; synthetic refs are never acceptance evidence."""
    raw = source_basis().source.model_dump(mode="json")
    raw.update(item_id="item_" + seed * 32, item_revision_id="itemrev_" + seed * 32)
    raw["artifact_member"].update(
        materialized_path="source/item-content.json", logical_name="item-content.json"
    )
    source = ApprovedPastExamItemKnowledgeSourceV3.model_validate(
        raw
        | {
            "extraction_acceptance_id": "itemacceptance_" + seed * 32,
            "extraction_acceptance_sha256": sha(seed),
            "extraction_acceptance_artifact": member(
                seed, "acceptance.json", "legacy-assessment/legacy-item-extraction-acceptance/1.0"
            ),
            "extraction_result_id": "itemextractresult_" + seed * 32,
            "extraction_result_sha256": sha(seed),
            "extraction_result_artifact": member(
                seed, "result.json", "legacy-assessment/legacy-item-extraction-result/1.0"
            ),
            "item_proposal_id": "itemproposal_" + seed * 32,
            "item_number": 1,
            "bundle": {
                "assessment_source_bundle_id": "assessbundle_" + seed * 32,
                "assessment_source_bundle_revision_id": "assessbundlerev_" + seed * 32,
                "bundle_manifest_sha256": sha(seed),
            },
            "layout_observation": {
                "assessment_layout_observation_id": "assessmentlayout_" + seed * 32,
                "artifact": member(
                    seed, "layout.json", "legacy-assessment/assessment-layout-observation/1.0"
                ),
                "workspace_relative_path": "source/layout-observation.json",
                "observation_sha256": sha(seed),
            },
            "page_inputs": [
                {
                    "page_input_id": "assessmentpage_" + seed * 32,
                    "source_role": "PROBLEM_DOCUMENT",
                    "physical_page": 1,
                    "source": member(
                        seed,
                        "sources/problem.pdf",
                        "legacy-assessment/pdf-source/1.0",
                        "application/pdf",
                    ),
                    "image": member(
                        seed, "pages/problem-1.png", "legacy-assessment/page-image/1.0", "image/png"
                    ),
                    "workspace_relative_path": "source/pages/assessmentpage_" + seed * 32 + ".png",
                    "width_px": 1200,
                    "height_px": 1800,
                }
            ],
            "page_image_count": 1,
        }
    )
    specs = {
        "normalized_markdown": ("document.md", "normalized-markdown/1.0", "text/markdown"),
        "anchors": ("anchors.jsonl", "source-anchor/2.0", "application/x-ndjson"),
        "nodes": ("nodes.jsonl", "proposed-node/4.0", "application/x-ndjson"),
        "edges": ("edges.jsonl", "proposed-edge/4.0", "application/x-ndjson"),
        "claims": ("claims.jsonl", "proposed-claim/2.0", "application/x-ndjson"),
        "component_observations": (
            "components.jsonl",
            "component-observation/2.0",
            "application/x-ndjson",
        ),
        "page_image_observations": (
            "page-images.jsonl",
            "assessment-page-image-observation/2.0",
            "application/x-ndjson",
        ),
        "unresolved_ambiguities": ("ambiguities.jsonl", "ambiguity/3.0", "application/x-ndjson"),
    }
    members = {
        name: member(seed, "normalized/" + path, "knowledge/" + schema, media) | {"bytes": 1}
        for name, (path, schema, media) in specs.items()
    }
    descriptors = [
        {key: value[key] for key in ("member_path", "sha256", "bytes", "schema_ref", "media_type")}
        for value in sorted(members.values(), key=lambda entry: entry["member_path"])
    ]
    counts = {
        "anchors": 2,
        "nodes": 2,
        "edges": 0,
        "claims": 0,
        "component_observations": 0,
        "ambiguities": 0,
        "page_image_observations": 1,
    }
    index = {
        "anchor_ids": ["anchor_answer", "anchor_problem"],
        "problem_anchor_ids": ["anchor_problem"],
        "answer_explanation_anchor_ids": ["anchor_answer"],
        "nodes": [
            {"node_id": "knode_concept_motion", "node_type": "CONCEPT"},
            {"node_id": "knode_item_element_stem", "node_type": "ITEM_ELEMENT"},
        ],
    }
    base = {
        "analysis_run_id": "analysisrun_" + seed * 32,
        "analysis_result_id": "knowledgeanalysisresult_" + seed * 32,
        "analysis_request_id": "knowledgeanalysis_" + "1" * 32,
        "accepted_result_sha256": sha(seed),
        "accepted_result_artifact": member(
            seed, "evidence/accepted-result.json", "knowledge/knowledge-analysis-result/9.0"
        )
        | {"bytes": 1},
        "proposal_receipt": member(
            seed,
            "normalized/proposal-receipt.json",
            "knowledge/knowledge-analysis-proposal-receipt/8.0",
        )
        | {"bytes": 1},
        "proposal_content_set_sha256": content_sha256(descriptors),
        "base_members": members,
        "base_counts": counts,
        "reference_index": index | {"index_sha256": content_sha256(index)},
    }
    body = {
        "schema_version": "knowledge-analysis-result/10.0",
        "analysis_result_id": "knowledgeanalysisresult_" + "6" * 32,
        "analysis_request_id": "knowledgeanalysis_" + seed * 32,
        "analysis_request_sha256": sha(seed),
        "status": "ACCEPTED",
        "source": source.model_dump(mode="json"),
        "base_analysis": base,
        "proposal_receipt": member(
            seed,
            "normalized/proposal-receipt.json",
            "knowledge/knowledge-analysis-proposal-receipt/9.0",
        )
        | {"bytes": 1},
        "proposal_content_set_sha256": sha(seed),
        "risk_policy_revision_id": "analysisriskrev_" + seed * 32,
        "acceptance_mode": "AUTO_POLICY",
        "review_decision": None,
        "counts": counts,
        "solution_counts": {
            "solution_steps": 2,
            "concept_assessment_links": 2,
            "choice_diagnostics": 0,
            "unresolved_issues": 0,
        },
        "general_knowledge_used": False,
        "minimum_confidence_milli": None,
        "blocking_ambiguity_count": 0,
        "accepted_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    accepted = KnowledgeAnalysisResultV10.model_validate(
        body | {"result_sha256": content_sha256(body)}
    )
    body = accepted.model_dump(mode="json")
    solution = source_basis().solution_evidence.model_dump(mode="json", exclude={"pointer_sha256"})
    solution.update(
        base_analysis_run_id=base["analysis_run_id"],
        base_analysis_result_id=base["analysis_result_id"],
        solution_result_sha256=accepted.result_sha256,
    )
    solution["accepted_result_artifact"].update(
        artifact_id="artifact_" + seed * 32,
        artifact_revision_id="rev_" + seed * 32,
        sha256=content_sha256(body),
    )
    basis = InferenceTransferSourceBasis.model_validate(
        {
            "source": raw,
            "graph_snapshot": source_basis().graph_snapshot.model_dump(mode="json"),
            "solution_evidence": solution | {"pointer_sha256": content_sha256(solution)},
        }
    )
    report_body = report().model_dump(mode="json")
    report_body.update(
        base_analysis_result_id=base["analysis_result_id"],
        analysis_request_id=accepted.analysis_request_id,
    )
    resolved_report = KnowledgeAnalysisSolutionReport.model_validate(report_body)
    solution_value = ResolvedSolutionEvidence(
        pointer=basis.solution_evidence,
        report=resolved_report,
        source=basis.source,
        base_accepted_result=accepted.base_analysis.accepted_result_artifact,
        accepted_at=accepted.accepted_at,
    )
    candidate = KnowledgeRetrievalCandidate(
        analysis_run_id=base["analysis_run_id"],
        source=source,
        node_ids=("knode_concept_motion",),
        anchor_ids=("anchor_problem",),
        node_labels=("운동",),
        node_types=("CONCEPT",),
        relevance_milli=0,
        answer_bearing=True,
    )
    revision = SimpleNamespace(
        revision_id=basis.solution_evidence.accepted_result_artifact.artifact_revision_id,
        content_hash=basis.solution_evidence.accepted_result_artifact.sha256,
        result=body,
    )
    profile = project_accepted_solution_report(
        source_basis=basis, report=resolved_report, created_at=NOW
    )
    return profile, candidate, solution_value, revision


@pytest.fixture
def pair_source(monkeypatch):
    left, right = accepted_input("a"), accepted_input("b")
    request = InferenceTransferSearchCommand(
        actor_id="operator_" + "f" * 32,
        graph_snapshot=left[0].source_basis.graph_snapshot,
        access_policy_revision_id="accessrev_" + "f" * 32,
        access_policy_sha256=sha("f"),
        query_item_revision_id=left[0].source_basis.source.item_revision_id,
        population_scope=InferenceTransferPopulationScope.OCCURRENCE_BACKED_PAST_EXAM,
    )
    adapter = object.__new__(CatalogInferenceTransferSourceAdapter)
    session, context = MagicMock(), MagicMock()
    context.__enter__.return_value = session
    adapter.sessions = Mock(return_value=context)
    adapter.retrieval = Mock()
    pool = ReadOnlyKnowledgeCandidatePool(request.graph_snapshot, (left[1], right[1]), False)
    adapter.retrieval.admit_read_only_candidate_pool.return_value = pool
    scope = Mock(population_scope=request.population_scope)
    monkeypatch.setattr(adapter, "_scope", Mock(return_value=scope))
    resolution = Mock(return_value={row[1].analysis_run_id: row[2] for row in (left, right)})
    monkeypatch.setattr(adapter_module, "resolve_solution_evidence_by_base_run", resolution)
    session.scalars.return_value = (left[3], right[3])
    return SimpleNamespace(
        adapter=adapter,
        session=session,
        request=request,
        left=left,
        right=right,
        pool=pool,
        resolution=resolution,
    )


def test_authorization_replays_exact_two_profiles_without_full_corpus_or_lexical_reads(pair_source):
    value = pair_source
    value.adapter.authorize_pair(value.request, value.left[0], value.right[0])
    expected_ids = tuple(sorted((value.left[1].analysis_run_id, value.right[1].analysis_run_id)))
    value.adapter._scope.assert_called_once_with(
        value.session, value.request, analysis_run_ids=expected_ids
    )
    value.adapter.retrieval.admit_read_only_candidate_pool.assert_called_once()
    assert value.resolution.call_args.kwargs["base_analysis_run_ids"] == expected_ids
    value.adapter.retrieval.retrieve_read_only.assert_not_called()
    value.session.scalars.assert_not_called()


def test_corpus_load_and_pair_use_the_same_accepted_timestamp_projection(pair_source):
    value = pair_source
    corpus = value.adapter.load(value.request)
    assert corpus.profiles == (value.left[0], value.right[0])
    assert corpus.missing_solution_reports == 0
    value.adapter.authorize_pair(value.request, *corpus.profiles)
    assert value.resolution.call_count == 2


def rehashed(profile: InferenceTransferProfile, **updates: Any) -> InferenceTransferProfile:
    body = profile.model_dump(mode="json", exclude={"profile_sha256"}) | updates
    return InferenceTransferProfile.model_validate(body | {"profile_sha256": content_sha256(body)})


def test_correct_hash_cannot_authorize_invented_claim_or_old_timestamp(pair_source):
    value = pair_source
    left = value.left[0]
    altered_claims = [claim.model_dump(mode="json") for claim in left.claims]
    altered_claims[0]["text"] = "출처 보고서에는 없는 주장"
    forged = rehashed(left, claims=altered_claims)
    with pytest.raises(InferenceTransferServiceError, match="SOURCE_PIN_MISMATCH"):
        value.adapter.authorize_pair(value.request, forged, value.right[0])
    old_timestamp = (NOW - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    with pytest.raises(InferenceTransferServiceError, match="SOURCE_PIN_MISMATCH"):
        value.adapter.authorize_pair(
            value.request, rehashed(left, created_at=old_timestamp), value.right[0]
        )


def test_model_copy_hash_forgery_is_revalidated_before_resolution(pair_source):
    value = pair_source
    forged = value.left[0].model_copy(update={"profile_sha256": sha("0")})
    with pytest.raises(ValidationError):
        value.adapter.authorize_pair(value.request, forged, value.right[0])
    value.resolution.assert_not_called()


def test_codex_derived_profile_requires_future_accepted_artifact_boundary(pair_source):
    value = pair_source
    unsupported = rehashed(
        value.left[0],
        extraction={
            "method": "CODEX_DERIVED",
            "extractor_version": "candidate/1.0",
            "prompt_sha256": sha("a"),
            "model_id": "synthetic-codex",
            "runtime_sha256": sha("b"),
        },
    )
    with pytest.raises(InferenceTransferServiceError, match="PRODUCER_UNAVAILABLE"):
        value.adapter.authorize_pair(value.request, unsupported, value.right[0])
    value.adapter.retrieval.admit_read_only_candidate_pool.assert_not_called()


def test_duplicate_base_run_and_wrong_graph_are_not_implicitly_replaced(pair_source):
    value = pair_source
    with pytest.raises(InferenceTransferServiceError, match="PAIR_SOURCE_INVALID"):
        value.adapter.authorize_pair(value.request, value.left[0], value.left[0])
    graph = value.left[0].source_basis.graph_snapshot.model_dump(mode="json")
    graph["graph_snapshot_revision_id"] = "graphrev_" + "f" * 32
    basis = value.left[0].source_basis.model_dump(mode="json") | {"graph_snapshot": graph}
    with pytest.raises(InferenceTransferServiceError, match="GRAPH_PIN_MISMATCH"):
        value.adapter.authorize_pair(
            value.request, rehashed(value.left[0], source_basis=basis), value.right[0]
        )
    value.resolution.assert_not_called()


@pytest.mark.parametrize("defect", ("missing", "duplicate", "truncated"))
def test_exact_source_pool_must_contain_both_requested_ids_once(pair_source, defect):
    value = pair_source
    candidates = (value.left[1],) if defect == "missing" else (value.left[1], value.left[1])
    if defect == "truncated":
        candidates = value.pool.candidates
    value.adapter.retrieval.admit_read_only_candidate_pool.return_value = (
        ReadOnlyKnowledgeCandidatePool(
            value.request.graph_snapshot, candidates, defect == "truncated"
        )
    )
    with pytest.raises(InferenceTransferServiceError, match="SOURCE_PIN_MISMATCH"):
        value.adapter.authorize_pair(value.request, value.left[0], value.right[0])
    value.resolution.assert_not_called()


@pytest.mark.parametrize(
    "defect",
    (
        "missing_report",
        "changed_source",
        "changed_report",
        "accepted_hash",
        "accepted_missing",
        "accepted_timestamp",
        "accepted_timestamp_naive",
        "invalid_accepted_metadata",
        "resolver_failure",
    ),
)
def test_current_report_source_and_accepted_metadata_must_match_exact_profile(pair_source, defect):
    value = pair_source
    right = value.right[2]
    if defect == "missing_report":
        del value.resolution.return_value[value.right[1].analysis_run_id]
    elif defect == "changed_source":
        altered = right.source.model_copy(update={"item_revision_id": "itemrev_" + "f" * 32})
        value.resolution.return_value[value.right[1].analysis_run_id] = replace(
            right, source=altered
        )
    elif defect == "changed_report":
        body = right.report.model_dump(mode="json")
        body["solution_steps"][0]["rationale"] = "검증된 보고서의 다른 조건"
        value.resolution.return_value[value.right[1].analysis_run_id] = replace(
            right, report=KnowledgeAnalysisSolutionReport.model_validate(body)
        )
    elif defect in {"accepted_hash", "accepted_missing", "invalid_accepted_metadata"}:
        # Current accepted-row checks belong to the official resolver, exercised
        # with real metadata in its own suite, not a second adapter-side SQL read.
        value.resolution.side_effect = SolutionEvidenceResolutionError(defect)
    elif defect == "accepted_timestamp":
        value.resolution.return_value[value.right[1].analysis_run_id] = replace(
            right, accepted_at=NOW + timedelta(days=1)
        )
    elif defect == "accepted_timestamp_naive":
        value.resolution.return_value[value.right[1].analysis_run_id] = replace(
            right, accepted_at=NOW.replace(tzinfo=None)
        )
    else:
        value.resolution.side_effect = SolutionEvidenceResolutionError(
            "synthetic stale report chain"
        )
    with pytest.raises(InferenceTransferServiceError, match="SOURCE_PIN_MISMATCH"):
        value.adapter.authorize_pair(value.request, value.left[0], value.right[0])


def test_revoked_actor_or_policy_scope_fails_before_report_resolution(pair_source):
    value = pair_source
    value.adapter._scope.side_effect = InferenceTransferServiceError("INFERENCE_TRANSFER_FORBIDDEN")
    with pytest.raises(InferenceTransferServiceError, match="FORBIDDEN"):
        value.adapter.authorize_pair(value.request, value.left[0], value.right[0])
    value.resolution.assert_not_called()
    value.adapter.retrieval.admit_read_only_candidate_pool.assert_not_called()


def test_pair_scope_uses_real_actor_permission_guard_without_impersonation(
    pair_source, monkeypatch
):
    value = pair_source
    value.adapter = object.__new__(CatalogInferenceTransferSourceAdapter)
    value.adapter.sessions = Mock(return_value=MagicMock())
    value.adapter.sessions.return_value.__enter__.return_value = value.session
    value.adapter.retrieval = Mock()
    value.session.get.return_value = SimpleNamespace(
        status="ACTIVE", deleted_at=None, must_change_password=False
    )
    monkeypatch.setattr(
        adapter_module,
        "effective_permissions",
        Mock(return_value=frozenset({PermissionKey.ITEM_READ})),
    )
    with pytest.raises(InferenceTransferServiceError, match="FORBIDDEN"):
        value.adapter.authorize_pair(value.request, value.left[0], value.right[0])
    value.adapter.retrieval.resolve_access_policy.assert_not_called()
    value.adapter.retrieval.admit_read_only_candidate_pool.assert_not_called()
