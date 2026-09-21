from __future__ import annotations

import hashlib
from pathlib import Path

from eom_catalog_service.content_pack_files import compile_pack
from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_workflow import WORKFLOW_ADMISSION_BY_IDENTITY, ArtifactPointer, compile_definition
from eom_workflow.models import WorkflowRequest

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "content/packs/generated-knowledge-item/1.17.0"
WORKFLOW = ROOT / "config/workflows/generic-item-development.v1.11.yaml"


def test_graph_review_pack_and_workflow_pin_exact_successor_family() -> None:
    compiled = compile_pack(PACK)
    definition = compile_definition(
        WORKFLOW,
        {"authoring", "image", "review", "item_management"},
    ).definition

    assert compiled.manifest.pack.version == "1.17.0"
    assert compiled.source_tree_sha256 == (
        "sha256:f319718e94708606be9e36e2b0b685fe9343e5e8ceeaf54d2e1e5664aa8268ed"
    )
    assert compiled.manifest.compatibility.protocol.minimum == "1.23.0"
    assert compiled.manifest.compatibility.protocol.maximum_exclusive == "1.24.0"
    assert definition.definition_version == "1.11.0"
    assert (
        WORKFLOW_ADMISSION_BY_IDENTITY[("generic-item-development", "1.11.0")].role_protocol_version
        == "workflow-role/1.23.0"
    )


def test_graph_review_pack_requires_independent_solution_enriched_review() -> None:
    authoring = (PACK / "prompt-templates/authoring.md").read_text(encoding="utf-8")
    review_path = PACK / "prompt-templates/review.md"
    review = review_path.read_text(encoding="utf-8")

    assert "authoring-result@11.0" in authoring
    assert "authoring-result@10.0" not in authoring
    for required in (
        "independent_review_report",
        "solution_evidence",
        "assessment_design_summary",
        "reusable_generation_guidance",
        "SCIENTIFIC_VALIDATION",
        "①~⑤",
        "ㄱ/ㄴ/ㄷ",
        "INDEPENDENT_ANSWER_MISMATCH",
        "EXPLANATION_INCONSISTENT",
        "CURRICULUM_SCOPE_INVALID",
        "ORIGINALITY_RISK",
        "VISUAL_CONTENT_INCONSISTENT",
    ):
        assert required in review
    assert hashlib.sha256(review_path.read_bytes()).hexdigest() == (
        "19baf1db0524b911ee2e8d5365115818d09d171c44a43b8d92e951262e806e55"
    )


def test_catalog_admits_v117_only_for_material_v4_content_team_request() -> None:
    from eom_workflow import ContentTeamItemBriefV4

    request = WorkflowRequest.model_validate_json(
        (PACK / "fixtures/smoke-request.json").read_text(encoding="utf-8")
    )
    assert isinstance(request.item_brief, ContentTeamItemBriefV4)
    WorkflowCatalogService._require_item_brief_release(
        "generated-knowledge-item",
        "1.17.0",
        request,
    )


def test_catalog_registration_rejects_mixed_v10_v11_result_family() -> None:
    request = WorkflowRequest.model_validate_json(
        (PACK / "fixtures/smoke-request.json").read_text(encoding="utf-8")
    )
    artifacts = (
        ArtifactPointer(
            step_key="authoring",
            attempt=1,
            job_id="job_" + "1" * 32,
            logical_artifact_id="artifact_" + "2" * 32,
            revision_id="rev_" + "3" * 32,
            content_hash="sha256:" + "4" * 64,
            result_schema="authoring-result@11.0",
        ),
        ArtifactPointer(
            step_key="review",
            attempt=1,
            job_id="job_" + "5" * 32,
            logical_artifact_id="artifact_" + "6" * 32,
            revision_id="rev_" + "7" * 32,
            content_hash="sha256:" + "8" * 64,
            result_schema="review-result@10.0",
        ),
    )
    service = object.__new__(WorkflowCatalogService)

    import pytest

    with pytest.raises(ValueError, match="cannot mix result families"):
        service._require_evidence_usage_receipts(request=request, artifacts=artifacts)
