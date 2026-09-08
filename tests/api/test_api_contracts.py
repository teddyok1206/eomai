from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_api_contracts.assessment_assemblies import (
    CreatePlannedMockExamAssemblyRequest,
    PreviewMockExamAssemblyPlanRequest,
)
from eom_api_contracts.assessment_learning import (
    AssessmentLearningBatchView,
    AssessmentLearningExamView,
    AssessmentLearningItemCounts,
    AssessmentLearningPageView,
    AssessmentLearningWorkUnitCounts,
)
from eom_api_contracts.auth import LoginRequest
from eom_api_contracts.common import ArtifactPointer
from eom_api_contracts.control_plane import CreateExecutionPresetDraftRequest
from eom_api_contracts.curriculum import (
    AssessmentItemOccurrenceView,
    AssessmentItemOccurrenceViewV2,
)
from eom_api_contracts.item_bank import (
    ItemBankCurriculumUnitView,
    ItemBankEntryView,
    ProductionItemCandidateView,
    ProductionItemContentComponentView,
)
from eom_api_contracts.knowledge_analysis import (
    CreateKnowledgeAnalysisRequest,
    KnowledgeAnalysisReviewRequest,
)
from eom_api_contracts.knowledge_retrieval import CreateEvidenceBundleRequest
from eom_api_contracts.operators import CreateOperatorRequest
from eom_api_contracts.workflows import (
    WorkflowKnowledgeProvenanceView,
    WorkflowStartRequest,
)
from eom_catalog_contracts import build_mock_exam_assembly_cohort
from jsonschema import Draft202012Validator
from pydantic import ValidationError

SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas" / "api" / "v1"


def test_api_json_schemas_are_draft_2020_12() -> None:
    schemas = sorted(SCHEMA_ROOT.glob("*.schema.json"))
    assert schemas
    for path in schemas:
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        Draft202012Validator.check_schema(document)


def test_mock_exam_plan_api_schema_delegates_to_the_canonical_protocol() -> None:
    canonical_path = SCHEMA_ROOT / "mock-exam-assembly-plan-v1.schema.json"
    packaged_path = (
        Path(__file__).resolve().parents[2]
        / "packages/api_contracts/eom_api_contracts/schemas"
        / canonical_path.name
    )
    assert canonical_path.read_bytes() == packaged_path.read_bytes()
    schema = json.loads(canonical_path.read_text(encoding="utf-8"))
    assert schema["$ref"] == "eom://schemas/assessment-assembly/mock-exam-assembly-plan/1.0"
    cohort = build_mock_exam_assembly_cohort(
        tuple("itemrev_" + f"{index:032x}" for index in range(1, 26))
    )
    value = CreatePlannedMockExamAssemblyRequest(
        deliverable_id="deliverable_" + "1" * 32,
        deliverable_revision_id="delivrev_" + "2" * 32,
        form_key="main",
        display_label="본시험지",
        policy_revision_id="assemblypolicyrev_" + "3" * 32,
        policy_sha256="sha256:" + "4" * 64,
        graph_snapshot_revision_id="graphrev_" + "5" * 32,
        graph_snapshot_sha256="sha256:" + "6" * 64,
        cohort=cohort,
        expected_plan_sha256="sha256:" + "7" * 64,
        planned_at=datetime(2026, 9, 8, 0, 0, tzinfo=UTC),
    )
    assert value.expected_plan_sha256 == "sha256:" + "7" * 64
    assert value.cohort == cohort
    assert value.model_dump(mode="json")["cohort"]["cohort_sha256"] == cohort.cohort_sha256
    preview = PreviewMockExamAssemblyPlanRequest(
        policy_revision_id=value.policy_revision_id,
        policy_sha256=value.policy_sha256,
        graph_snapshot_revision_id=value.graph_snapshot_revision_id,
        graph_snapshot_sha256=value.graph_snapshot_sha256,
        cohort=cohort,
    )
    assert preview.cohort == cohort


def test_assessment_item_occurrence_schema_matches_typed_projection_and_excludes_march() -> None:
    canonical_path = SCHEMA_ROOT / "assessment-item-occurrence-v1.schema.json"
    packaged_path = (
        Path(__file__).resolve().parents[2]
        / "packages/api_contracts/eom_api_contracts/schemas"
        / canonical_path.name
    )
    assert canonical_path.read_bytes() == packaged_path.read_bytes()
    schema = json.loads(canonical_path.read_text(encoding="utf-8"))
    value = AssessmentItemOccurrenceView(
        graph_snapshot_revision_id="graphrev_" + "1" * 32,
        placement_node_id="knode_" + "2" * 64,
        occurrence_node_id="knode_" + "3" * 64,
        item_node_id="knode_" + "4" * 64,
        analysis_run_id="analysisrun_" + "5" * 32,
        assessment_occurrence_id="occurrence_" + "6" * 32,
        assessment_occurrence_revision_id="occurrev_" + "7" * 32,
        assessment_occurrence_revision_sha256="sha256:" + "8" * 64,
        occurrence_display_label="2025년 고1 6월 통합과학 12번",
        administration_year=2025,
        administration_month=6,
        target_school_level="HIGH_SCHOOL",
        target_grade=1,
        subject_key="integrated-science",
        item_number=12,
        item_id="item_" + "9" * 32,
        item_revision_id="itemrev_" + "a" * 32,
        curriculum_unit_ids=("currunit_" + "b" * 32,),
        placement_sha256="sha256:" + "c" * 64,
    ).model_dump(mode="json")
    validator = Draft202012Validator(schema)
    assert tuple(validator.iter_errors(value)) == ()
    assert tuple(validator.iter_errors(value | {"administration_month": 3}))


def test_assessment_item_occurrence_v2_matches_graph_node_identity_width() -> None:
    canonical_path = SCHEMA_ROOT / "assessment-item-occurrence-v2.schema.json"
    packaged_path = (
        Path(__file__).resolve().parents[2]
        / "packages/api_contracts/eom_api_contracts/schemas"
        / canonical_path.name
    )
    assert canonical_path.read_bytes() == packaged_path.read_bytes()
    value = AssessmentItemOccurrenceViewV2(
        graph_snapshot_revision_id="graphrev_" + "1" * 32,
        placement_node_id="knode_" + "2" * 32,
        occurrence_node_id="knode_" + "3" * 32,
        item_node_id="knode_" + "4" * 32,
        analysis_run_id="analysisrun_" + "5" * 32,
        assessment_occurrence_id="occurrence_" + "6" * 32,
        assessment_occurrence_revision_id="occurrev_" + "7" * 32,
        assessment_occurrence_revision_sha256="sha256:" + "8" * 64,
        occurrence_display_label="2025년 고1 6월 통합과학 12번",
        administration_year=2025,
        administration_month=6,
        target_school_level="HIGH_SCHOOL",
        target_grade=1,
        subject_key="integrated-science",
        item_number=12,
        item_id="item_" + "9" * 32,
        item_revision_id="itemrev_" + "a" * 32,
        curriculum_unit_ids=("currunit_" + "b" * 32,),
        placement_sha256="sha256:" + "c" * 64,
    ).model_dump(mode="json")
    validator = Draft202012Validator(json.loads(canonical_path.read_text(encoding="utf-8")))
    assert tuple(validator.iter_errors(value)) == ()
    with pytest.raises(ValidationError):
        AssessmentItemOccurrenceViewV2.model_validate(
            value | {"placement_node_id": "knode_" + "d" * 64}
        )


def test_item_bank_schema_matches_typed_graph_projection() -> None:
    canonical_path = SCHEMA_ROOT / "item-bank-entry-v1.schema.json"
    packaged_path = (
        Path(__file__).resolve().parents[2]
        / "packages/api_contracts/eom_api_contracts/schemas"
        / canonical_path.name
    )
    assert canonical_path.read_bytes() == packaged_path.read_bytes()
    value = ItemBankEntryView(
        graph_snapshot_revision_id="graphrev_" + "1" * 32,
        snapshot_sha256="sha256:" + "2" * 64,
        analysis_run_id="analysisrun_" + "3" * 32,
        graph_placement_node_id="knode_" + "d" * 32,
        assessment_occurrence_id="occurrence_" + "4" * 32,
        assessment_occurrence_revision_id="occurrev_" + "5" * 32,
        assessment_occurrence_revision_sha256="sha256:" + "6" * 64,
        occurrence_display_label="2025년 고1 6월 통합과학",
        administration_year=2025,
        administration_month=6,
        target_school_level="HIGH_SCHOOL",
        target_grade=1,
        subject_key="integrated-science",
        item_number=12,
        item_id="item_" + "7" * 32,
        item_revision_id="itemrev_" + "8" * 32,
        item_revision_state="APPROVED",
        item_type_key="multiple-choice",
        difficulty_band=None,
        item_manifest_sha256="sha256:" + "9" * 64,
        curriculum_units=(
            ItemBankCurriculumUnitView(
                curriculum_unit_id="currunit_" + "a" * 32,
                unit_key="eom.is.middle.3-3",
                unit_code="3-(3)",
                label="중력장 내의 운동",
                unit_level="MINOR",
                parent_unit_id="currunit_" + "b" * 32,
            ),
        ),
        placement_sha256="sha256:" + "c" * 64,
    ).model_dump(mode="json")
    assert (
        tuple(
            Draft202012Validator(
                json.loads(canonical_path.read_text(encoding="utf-8"))
            ).iter_errors(value)
        )
        == ()
    )
    with pytest.raises(ValidationError, match="sorted and unique"):
        ItemBankEntryView.model_validate(
            value | {"curriculum_units": [*value["curriculum_units"], *value["curriculum_units"]]}
        )


def test_production_item_candidate_schema_matches_structural_eligibility() -> None:
    canonical_path = SCHEMA_ROOT / "production-item-candidate-v1.schema.json"
    packaged_path = (
        Path(__file__).resolve().parents[2]
        / "packages/api_contracts/eom_api_contracts/schemas"
        / canonical_path.name
    )
    assert canonical_path.read_bytes() == packaged_path.read_bytes()
    value = ProductionItemCandidateView(
        graph_snapshot_revision_id="graphrev_" + "1" * 32,
        snapshot_sha256="sha256:" + "2" * 64,
        analysis_run_id="analysisrun_" + "3" * 32,
        graph_item_node_id="knode_" + "4" * 32,
        source_class="APPROVED_ITEM",
        source_display_label="검토 완료 문항 2026-001",
        past_exam_context=None,
        item_id="item_" + "5" * 32,
        item_revision_id="itemrev_" + "6" * 32,
        item_revision_state="APPROVED",
        item_lifecycle_state="ACTIVE",
        item_current_revision=True,
        item_type_key="multiple-choice",
        difficulty_band="MEDIUM",
        item_manifest_sha256="sha256:" + "7" * 64,
        curriculum_units=(
            ItemBankCurriculumUnitView(
                curriculum_unit_id="currunit_" + "8" * 32,
                unit_key="eom.is.middle.3-3",
                unit_code="3-(3)",
                label="중력장 내의 운동",
                unit_level="MINOR",
                parent_unit_id="currunit_" + "9" * 32,
            ),
        ),
        content_profile="CONTENT_TEAM_ITEM_CONTENT_V2",
        content_component=ProductionItemContentComponentView(
            item_component_id="itemcomponent_" + "a" * 32,
            artifact_id="artifact_" + "b" * 32,
            artifact_revision_id="rev_" + "c" * 32,
            sha256="sha256:" + "d" * 64,
            schema_ref="eom.assessment.item-content/2.0",
            media_type="application/json",
            logical_name="item-content.json",
            editorial_markdown_member="content-team-item.md",
            editorial_markdown_sha256="sha256:" + "e" * 64,
        ),
        mock_exam_assembly_eligible=True,
        hwpx_exam_eligible=True,
        ineligibility_reasons=(),
    ).model_dump(mode="json")
    schema = json.loads(canonical_path.read_text(encoding="utf-8"))
    assert tuple(Draft202012Validator(schema).iter_errors(value)) == ()

    with pytest.raises(ValidationError, match="eligibility differs"):
        ProductionItemCandidateView.model_validate(
            value
            | {
                "content_profile": "LEGACY_ITEM_CONTENT_V1",
                "content_component": value["content_component"]
                | {"schema_ref": "eom.assessment.item-content/1.0"},
            }
        )
    with pytest.raises(ValidationError, match="source class"):
        ProductionItemCandidateView.model_validate(value | {"source_class": "PAST_EXAM"})


def test_assessment_learning_schemas_match_typed_progress_and_exclude_march() -> None:
    packaged_root = (
        Path(__file__).resolve().parents[2] / "packages/api_contracts/eom_api_contracts/schemas"
    )
    for name in (
        "assessment-learning-batch-v1.schema.json",
        "assessment-learning-exam-v1.schema.json",
        "assessment-learning-page-v1.schema.json",
    ):
        assert (SCHEMA_ROOT / name).read_bytes() == (packaged_root / name).read_bytes()

    work_units = AssessmentLearningWorkUnitCounts(
        pending=107,
        claimed=0,
        submitted=0,
        awaiting_review=0,
        accepted=1,
        failed=0,
        cancelled=0,
    )
    items = AssessmentLearningItemCounts(
        expected=520,
        accepted=5,
        promoted=2,
        analysis_active=1,
        analysis_accepted=1,
        analysis_failed=0,
        graph_published=0,
    )
    now = datetime(2026, 9, 6, 14, 0, tzinfo=UTC)
    batch = AssessmentLearningBatchView(
        extraction_batch_id="legacybatch_" + "1" * 32,
        inventory_id="legacyinventory_" + "2" * 32,
        inventory_sha256="sha256:" + "3" * 64,
        state="RUNNING",
        exam_count=25,
        total_work_unit_count=108,
        image_required_work_unit_count=108,
        work_units=work_units,
        items=items,
        current_graph_snapshot_revision_id="graphrev_" + "4" * 32,
        resource_version=2,
        created_at=now,
        started_at=now,
        completed_at=None,
        updated_at=now,
    ).model_dump(mode="json")
    batch_schema = json.loads(
        (SCHEMA_ROOT / "assessment-learning-batch-v1.schema.json").read_text(encoding="utf-8")
    )
    assert tuple(Draft202012Validator(batch_schema).iter_errors(batch)) == ()

    exam = AssessmentLearningExamView(
        extraction_batch_id="legacybatch_" + "1" * 32,
        assessment_occurrence_id="occurrence_" + "5" * 32,
        assessment_occurrence_revision_id="occurrev_" + "6" * 32,
        assessment_occurrence_revision_sha256="sha256:" + "7" * 64,
        assessment_source_bundle_revision_id="assessbundlerev_" + "8" * 32,
        display_label="2025년 고1 6월 통합과학",
        administration_year=2025,
        administration_month=6,
        target_school_level="HIGH_SCHOOL",
        target_grade=1,
        subject_key="integrated-science",
        total_work_unit_count=4,
        image_required_work_unit_count=4,
        work_units=AssessmentLearningWorkUnitCounts(
            pending=3,
            claimed=0,
            submitted=0,
            awaiting_review=0,
            accepted=1,
            failed=0,
            cancelled=0,
        ),
        items=AssessmentLearningItemCounts(
            expected=20,
            accepted=5,
            promoted=2,
            analysis_active=1,
            analysis_accepted=1,
            analysis_failed=0,
            graph_published=0,
        ),
    ).model_dump(mode="json")
    exam_schema = json.loads(
        (SCHEMA_ROOT / "assessment-learning-exam-v1.schema.json").read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(exam_schema)
    assert tuple(validator.iter_errors(exam)) == ()
    assert tuple(validator.iter_errors(exam | {"administration_month": 3}))

    page = AssessmentLearningPageView(
        extraction_batch_id="legacybatch_" + "1" * 32,
        assessment_occurrence_revision_id="occurrev_" + "6" * 32,
        page_input_id="assessmentpage_" + "9" * 32,
        source_role="PROBLEM_DOCUMENT",
        physical_page=1,
        artifact_id="artifact_" + "a" * 32,
        artifact_revision_id="rev_" + "b" * 32,
        artifact_member="pages/problem-1.png",
        sha256="sha256:" + "c" * 64,
        content_length=1024,
        width_px=1240,
        height_px=1754,
    ).model_dump(mode="json")
    page_schema = json.loads(
        (SCHEMA_ROOT / "assessment-learning-page-v1.schema.json").read_text(encoding="utf-8")
    )
    assert tuple(Draft202012Validator(page_schema).iter_errors(page)) == ()

    with pytest.raises(ValidationError, match="monotonic"):
        AssessmentLearningItemCounts(
            expected=5,
            accepted=4,
            promoted=3,
            analysis_active=0,
            analysis_accepted=2,
            analysis_failed=0,
            graph_published=3,
        )


def test_request_contracts_forbid_unknown_fields_and_redact_secrets() -> None:
    login = LoginRequest(
        username="admin",
        password="TEST_ONLY valid password 42",
        client_name="contract-test",
    )
    assert "TEST_ONLY valid password 42" not in repr(login)
    with pytest.raises(ValidationError):
        LoginRequest.model_validate(
            {
                "username": "admin",
                "password": "TEST_ONLY valid password 42",
                "client_name": "contract-test",
                "unknown": True,
            }
        )


def test_operator_contract_never_serializes_temporary_password() -> None:
    request = CreateOperatorRequest(
        username="review01",
        display_name="검토자",
        temporary_password="TEST_ONLY temporary password 42",
        initial_roles=("REVIEWER",),
    )
    assert "TEST_ONLY temporary password 42" not in request.model_dump_json()


def test_pack_pinned_workflow_requires_valid_source_intake_pointer() -> None:
    base = {
        "definition_key": "generic-item-development",
        "definition_version": "1.1.0",
        "request_name": "PLACEHOLDER_REQUEST",
        "image_mode": "skip",
        "pack_key": "generic-placeholder",
    }
    with pytest.raises(ValidationError, match="source intake batch"):
        WorkflowStartRequest.model_validate({**base, "source_intake_batch_ids": []})
    with pytest.raises(ValidationError):
        WorkflowStartRequest.model_validate({**base, "source_intake_batch_ids": ["not-an-intake"]})
    value = WorkflowStartRequest.model_validate(
        {**base, "source_intake_batch_ids": ["intake_" + "0" * 32]}
    )
    assert value.source_intake_batch_ids == ("intake_" + "0" * 32,)


def test_knowledge_item_workflow_is_source_optional_but_template_constrained() -> None:
    request = {
        "definition_key": "generic-item-development",
        "definition_version": "1.2.0",
        "request_name": "KNOWLEDGE_ITEM_REQUEST",
        "image_mode": "required",
        "pack_key": "general-knowledge-item",
        "source_intake_batch_ids": [],
        "item_brief": {
            "subject": "일반 과학",
            "topic": "변인 사이의 선형 관계",
            "task_type": "data_interpretation",
            "difficulty": "medium",
            "choice_count": 5,
            "equation_required": True,
            "image_required": True,
            "quality_profile": "balanced",
            "original_request_sha256": "0" * 64,
        },
        "stimulus_asset_key": "eom-question-template-reference-v1",
    }
    parsed = WorkflowStartRequest.model_validate(request)
    assert parsed.source_intake_batch_ids == ()
    assert parsed.item_brief is not None and parsed.item_brief.choice_count == 5
    with pytest.raises(ValidationError, match="fixed workflow contract"):
        WorkflowStartRequest.model_validate(request | {"image_mode": "skip"})


@pytest.mark.parametrize("definition_version", ["1.3.0", "1.4.0", "1.5.0", "1.6.0"])
def test_generated_item_workflow_requires_image_role_without_a_prebuilt_stimulus(
    definition_version: str,
) -> None:
    request = {
        "definition_key": "generic-item-development",
        "definition_version": definition_version,
        "request_name": "GENERATED_KNOWLEDGE_ITEM_REQUEST",
        "image_mode": "required",
        "pack_key": "generated-knowledge-item",
        "source_intake_batch_ids": [],
        "item_brief": {
            "subject": "일반 과학",
            "topic": "변인 사이의 선형 관계",
            "task_type": "data_interpretation",
            "difficulty": "medium",
            "choice_count": 5,
            "equation_required": True,
            "image_required": True,
            "quality_profile": "balanced",
            "original_request_sha256": "0" * 64,
        },
        "stimulus_asset_key": None,
    }
    parsed = WorkflowStartRequest.model_validate(request)
    assert parsed.pack_key == "generated-knowledge-item"
    assert parsed.stimulus_asset_key is None
    with pytest.raises(ValidationError, match="generated item request"):
        WorkflowStartRequest.model_validate(
            request | {"source_intake_batch_ids": ["intake_" + "1" * 32]}
        )
    with pytest.raises(ValidationError, match="generated item request"):
        WorkflowStartRequest.model_validate(
            request | {"stimulus_asset_key": "eom-question-template-reference-v1"}
        )


def test_generated_item_accepts_bounded_educational_intent_not_graph_controls() -> None:
    request = {
        "definition_key": "generic-item-development",
        "definition_version": "1.5.0",
        "request_name": "GENERATED_KNOWLEDGE_ITEM_REQUEST",
        "image_mode": "required",
        "pack_key": "generated-knowledge-item",
        "execution_preset_key": "knowledge-grounded-item",
        "item_brief": {
            "subject": "통합과학",
            "topic": "판 경계와 지진 자료",
            "task_type": "data_interpretation",
            "difficulty": "hard",
            "choice_count": 5,
            "equation_required": True,
            "image_required": True,
            "quality_profile": "deep",
            "original_request_sha256": "0" * 64,
        },
        "educational_retrieval": {
            "schema_version": "educational-retrieval-requirement/1.0",
            "corpus_key": "science-core",
            "query_kind": "ITEM_PREPARATION",
            "curriculum_root_key": "earth.plate-boundary",
            "topic_keys": ["earth.plate-boundary"],
            "required_item_elements": ["statement_set", "table"],
            "source_classes": ["APPROVED_ITEM", "TEXTBOOK"],
        },
    }
    parsed = WorkflowStartRequest.model_validate(request)
    assert parsed.educational_retrieval is not None
    assert parsed.educational_retrieval.corpus_key == "science-core"
    with pytest.raises(ValidationError, match="execution preset"):
        WorkflowStartRequest.model_validate(request | {"execution_preset_key": None})
    with pytest.raises(ValidationError):
        WorkflowStartRequest.model_validate(
            request
            | {
                "educational_retrieval": {
                    **request["educational_retrieval"],
                    "graph_snapshot_revision_id": "graphrev_" + "1" * 32,
                }
            }
        )


def test_artifact_pointer_can_pin_one_safe_member_without_exposing_storage_path() -> None:
    pointer = ArtifactPointer(
        artifact_id="artifact_" + "1" * 32,
        artifact_revision_id="rev_" + "2" * 32,
        artifact_member="source/diagram.png",
        sha256="sha256:" + "3" * 64,
        schema_ref="urn:eom:schema:content-intake-source:1.0",
        media_type="image/png",
        logical_uri="nas://artifacts/artifact_1/rev_2",
    )
    assert pointer.artifact_member == "source/diagram.png"
    with pytest.raises(ValidationError, match="artifact member"):
        ArtifactPointer.model_validate(pointer.model_dump() | {"artifact_member": "../diagram.png"})


def test_workflow_knowledge_provenance_is_pointer_only_and_closed() -> None:
    value = {
        "schema_version": "workflow-knowledge-provenance/1.0",
        "plan_id": "execplan_" + "1" * 32,
        "plan_sha256": "sha256:" + "1" * 64,
        "preset_revision_id": "execpresetrev_" + "2" * 32,
        "corpus_key": "science-core",
        "query_kind": "ITEM_PREPARATION",
        "curriculum_root_key": "earth.plate-boundary",
        "required_item_elements": ["equation", "image", "statement_set", "table"],
        "source_classes": ["APPROVED_ITEM", "TEXTBOOK"],
        "graph_snapshot_revision_id": "graphrev_" + "3" * 32,
        "evidence_bundle_revision_id": "evidencerev_" + "4" * 32,
        "retrieval_request_id": "retrieval_" + "5" * 32,
        "retrieval_request_sha256": "sha256:" + "5" * 64,
        "access_policy_revision_id": "accessrev_" + "6" * 32,
        "access_policy_sha256": "sha256:" + "6" * 64,
        "evidence_manifest_sha256": "sha256:" + "7" * 64,
        "resolved_at": "2026-08-24T04:00:00Z",
    }
    projection = WorkflowKnowledgeProvenanceView.model_validate(value)
    assert projection.evidence_bundle_revision_id == "evidencerev_" + "4" * 32
    with pytest.raises(ValidationError):
        WorkflowKnowledgeProvenanceView.model_validate(
            value | {"context_path": "/srv/eom/private/context.md"}
        )


def test_execution_preset_draft_contract_keeps_v1_and_v2_families_exact() -> None:
    role = {
        "role": "authoring",
        "model_candidates": [{"model": "gpt-5.6-terra", "reasoning_effort": "high"}],
        "instruction_bundle": {
            "bundle_id": "instrbundle_" + "1" * 32,
            "bundle_revision_id": "instrrev_" + "1" * 32,
            "manifest_artifact": {
                "artifact_id": "artifact_" + "1" * 32,
                "artifact_revision_id": "rev_" + "1" * 32,
                "sha256": "sha256:" + "1" * 64,
                "schema_ref": "eom://schemas/workflow/instruction-bundle-manifest/1.0",
                "media_type": "application/json",
                "logical_name": "manifest.json",
            },
            "manifest_sha256": "sha256:" + "1" * 64,
        },
        "reference_bundle": None,
        "worker_pool_key": "authoring",
        "timeout_seconds": 1800,
        "sandbox": "read-only",
        "network": "disabled",
    }
    base = {
        "preset_key": "standard-item",
        "display_name": "Standard item",
        "description": "Reviewed fresh-session item policy.",
        "role_policies": [role],
        "capacity_policy_revision_id": "capacityrev_" + "2" * 32,
        "general_knowledge_policy": "DENY",
        "compatible_workflow_protocols": ["workflow-role/1.3.0"],
    }
    legacy = CreateExecutionPresetDraftRequest.model_validate(base)
    assert legacy.schema_version == "execution-preset-revision/1.0"
    with pytest.raises(ValidationError, match="cannot declare evidence access"):
        CreateExecutionPresetDraftRequest.model_validate(
            base | {"role_policies": [role | {"evidence_access": "EVIDENCE_CONTEXT"}]}
        )
    retrieval_policy = {
        "access_policy_revision_id": "accessrev_" + "3" * 32,
        "access_policy_sha256": "sha256:" + "3" * 64,
        "allowed_corpus_keys": ["science-core"],
        "allowed_query_kinds": ["ITEM_PREPARATION"],
        "allowed_source_classes": ["APPROVED_ITEM", "TEXTBOOK"],
        "maximum_budget": {
            "max_documents": 4,
            "max_item_revisions": 4,
            "max_graph_nodes": 32,
            "max_claims": 16,
            "max_context_tokens": 8000,
        },
    }
    grounded = CreateExecutionPresetDraftRequest.model_validate(
        base
        | {
            "schema_version": "execution-preset-revision/2.0",
            "role_policies": [role | {"evidence_access": "EVIDENCE_CONTEXT"}],
            "retrieval_policy": retrieval_policy,
        }
    )
    assert grounded.retrieval_policy is not None
    with pytest.raises(ValidationError):
        CreateExecutionPresetDraftRequest.model_validate(
            grounded.model_dump(mode="json")
            | {"retrieval_policy": retrieval_policy | {"allowed_corpus_keys": ["/srv/eom/private"]}}
        )


def test_knowledge_analysis_request_is_discriminated_and_retry_is_explicit() -> None:
    request: CreateKnowledgeAnalysisRequest = CreateKnowledgeAnalysisRequest.model_validate(
        {
            "source": {
                "source_kind": "APPROVED_ITEM_REVISION",
                "source_class": "APPROVED_ITEM",
                "item_revision_id": "itemrev_" + "1" * 32,
            },
            "preset_key": "knowledge-analysis",
            "general_knowledge_mode": "DISABLED",
            "risk_policy_revision_id": "analysisriskrev_" + "2" * 32,
            "predecessor_analysis_run_id": "analysisrun_" + "3" * 32,
        }
    )
    assert request.source.source_kind == "APPROVED_ITEM_REVISION"
    assert request.predecessor_analysis_run_id == "analysisrun_" + "3" * 32
    with pytest.raises(ValidationError):
        CreateKnowledgeAnalysisRequest.model_validate(
            request.model_dump(mode="json")
            | {
                "source": {
                    "source_kind": "APPROVED_ITEM_REVISION",
                    "source_class": "TEXTBOOK",
                    "item_revision_id": "itemrev_" + "1" * 32,
                }
            }
        )

    document_request = CreateKnowledgeAnalysisRequest.model_validate(
        {
            "source": {
                "source_kind": "DOCUMENT_REVISION",
                "source_class": "TEXTBOOK",
                "document_revision_id": "edudocrev_" + "4" * 32,
                "first_physical_page": 10,
                "last_physical_page": 12,
                "curriculum_unit_keys": ["1-(1)", "1-(2)"],
            },
            "preset_key": "knowledge-analysis",
            "general_knowledge_mode": "AUXILIARY_UNATTRIBUTED",
            "risk_policy_revision_id": "analysisriskrev_" + "5" * 32,
            "predecessor_analysis_run_id": None,
        }
    )
    assert document_request.source.source_kind == "DOCUMENT_REVISION"
    assert document_request.source.curriculum_unit_keys == ("1-(1)", "1-(2)")
    with pytest.raises(ValidationError):
        CreateKnowledgeAnalysisRequest.model_validate(
            document_request.model_dump(mode="json")
            | {
                "source": document_request.source.model_dump(mode="json")
                | {"last_physical_page": 42}
            }
        )


def test_knowledge_analysis_review_rejects_unsafe_or_empty_notes() -> None:
    assert KnowledgeAnalysisReviewRequest(decision="APPROVE", notes="Reviewed.").decision == (
        "APPROVE"
    )
    for notes in ("", "unsafe\x00note"):
        with pytest.raises(ValidationError):
            KnowledgeAnalysisReviewRequest(decision="REJECT", notes=notes)


def test_evidence_bundle_request_is_bounded_sorted_and_pointer_only() -> None:
    request = CreateEvidenceBundleRequest.model_validate(
        {
            "graph_snapshot_revision_id": "graphrev_" + "1" * 32,
            "query_kind": "ITEM_PREPARATION",
            "curriculum_scope": None,
            "topic_keys": ["earth.plate-boundary"],
            "target_item_revision_id": None,
            "required_item_elements": [],
            "source_classes": ["TEXTBOOK"],
            "evidence_budget": {
                "max_documents": 4,
                "max_item_revisions": 0,
                "max_graph_nodes": 32,
                "max_claims": 8,
                "max_context_tokens": 4000,
            },
            "access_policy_revision_id": "accessrev_" + "2" * 32,
        }
    )
    assert request.topic_keys == ("earth.plate-boundary",)
    with pytest.raises(ValidationError, match="sorted and unique"):
        CreateEvidenceBundleRequest.model_validate(
            request.model_dump(mode="json") | {"source_classes": ["TEXTBOOK", "CURRICULUM"]}
        )


def test_assessment_item_occurrence_view_is_pinned_and_excludes_grade_one_march() -> None:
    value = {
        "graph_snapshot_revision_id": "graphrev_" + "1" * 32,
        "placement_node_id": "knode_" + "2" * 64,
        "occurrence_node_id": "knode_" + "3" * 64,
        "item_node_id": "knode_" + "4" * 64,
        "analysis_run_id": "analysisrun_" + "5" * 32,
        "assessment_occurrence_id": "occurrence_" + "6" * 32,
        "assessment_occurrence_revision_id": "occurrev_" + "7" * 32,
        "assessment_occurrence_revision_sha256": "sha256:" + "7" * 64,
        "occurrence_display_label": "2025학년도 고1 6월 통합과학 전국연합학력평가",
        "administration_year": 2025,
        "administration_month": 6,
        "target_school_level": "HIGH_SCHOOL",
        "target_grade": 1,
        "subject_key": "integrated-science",
        "item_number": 7,
        "item_id": "item_" + "8" * 32,
        "item_revision_id": "itemrev_" + "9" * 32,
        "curriculum_unit_ids": ["currunit_" + "a" * 32],
        "placement_sha256": "sha256:" + "b" * 64,
    }

    assert AssessmentItemOccurrenceView.model_validate(value).item_number == 7
    with pytest.raises(ValidationError, match="grade 1 March"):
        AssessmentItemOccurrenceView.model_validate(value | {"administration_month": 3})
