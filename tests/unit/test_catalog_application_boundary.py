from __future__ import annotations

import hashlib
import json
import os
import socket
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import eom_api.services.catalog_application_client as catalog_application_client_module
import pytest
from eom_api.services.catalog_application_client import (
    ASSEMBLY_RESPONSE_TIMEOUT_SECONDS,
    EVIDENCE_RESPONSE_TIMEOUT_SECONDS,
    RESPONSE_TIMEOUT_SECONDS,
    CatalogApplicationClient,
    CatalogApplicationClientError,
)
from eom_api.services.idempotency_service import DEFAULT_IDEMPOTENCY_LEASE_SECONDS
from eom_catalog_contracts import (
    AssessmentItemContent,
    AssessmentItemContentV2,
    AssessmentItemContentV3,
    AssessmentPageImagePointer,
    CatalogApplicationErrorCode,
    CatalogApplicationRequest,
    CatalogApplicationResponse,
    CatalogItemComponentMediaResponse,
    CatalogItemMediaResponse,
    CreateEvidenceBundleCommand,
    CreateItemProductionEvidenceCommand,
    CreateKnowledgeAnalysisBatchCommand,
    CreateKnowledgeAnalysisCommand,
    CreateKnowledgeSolutionAnalysisCommand,
    CreateMockExamAssemblyCommand,
    CreatePlannedMockExamAssemblyCommand,
    EvidenceBundlePublicationResult,
    EvidenceBundlePublicationResultV2,
    InspectMockExamAssemblyQuery,
    InspectMockExamReviewEligibilityQuery,
    ItemComponentMediaQuery,
    ItemMediaQuery,
    KnowledgeAnalysisApplicationResult,
    KnowledgeAnalysisBatchApplicationResult,
    MockExamAssemblyManifestV3,
    MockExamAssemblyPlanV2,
    MockExamAssemblySelection,
    MockExamEligibilityFindingCounts,
    MockExamItemReviewPublicationResultV2,
    MockExamReviewEligibilityResultV2,
    MockExamReviewFindingCounts,
    OfficeDocumentReviewMemberPointerV2,
    PdfDocumentReviewIntakeCommand,
    PdfDocumentReviewIntakeResponse,
    PdfDocumentReviewPageMediaQuery,
    PdfDocumentReviewPageMediaResponse,
    PreviewMockExamAssemblyPlanCommand,
    PublishMockExamItemReviewCommand,
    ReviewedItemContentImportCommand,
    build_mock_exam_assembly_plan,
    load_integrated_science_mock_exam_layout_policy,
    load_integrated_science_mock_exam_policy,
    load_integrated_science_mock_exam_rating_policy,
    validate_contract,
)
from eom_catalog_service.application_server import CatalogApplicationServer
from eom_catalog_service.office_document_review_intake import OfficeDocumentReviewIntakeError
from eom_identifiers import content_sha256
from eom_workflow import (
    PdfReviewArtifactMemberPointer,
    PdfReviewDocumentPointer,
    PdfReviewPagePointer,
)
from jsonschema import ValidationError as JsonSchemaValidationError

from tests.unit.test_assessment_item_content import item_content
from tests.unit.test_content_team_item_protocol import _content as content_team_item
from tests.unit.test_mock_exam_assembly_contracts import (
    _identifier,
    _planning_candidates_v2,
    _usage_snapshot,
)


class FakeImports:
    def import_reviewed(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            item_id="item_" + "1" * 32,
            item_revision_id="itemrev_" + "2" * 32,
            resource_version=1,
            content_artifact_id="artifact_" + "3" * 32,
            content_artifact_revision_id="rev_" + "4" * 32,
            content_sha256="sha256:" + "5" * 64,
        )


class FakeRegistry:
    def load_item_content(self, _revision_id: str) -> AssessmentItemContent:
        return AssessmentItemContent.model_validate(item_content())

    def load_item_media(self, _revision_id: str, block_id: str) -> SimpleNamespace:
        assert block_id == "block_image"
        content = b"\x89PNG\r\n\x1a\nCATALOG_MEDIA"

        def iter_chunks() -> object:
            yield content

        return SimpleNamespace(
            media_type="image/png",
            content_length=len(content),
            sha256="sha256:" + hashlib.sha256(content).hexdigest(),
            iter_chunks=iter_chunks,
        )

    def load_item_component_media(
        self, _revision_id: str, component_type: str, ordinal: int
    ) -> SimpleNamespace:
        assert component_type == "IMAGE"
        assert ordinal == 1
        content = b"\x89PNG\r\n\x1a\nCATALOG_COMPONENT_MEDIA"

        def iter_chunks() -> object:
            yield content

        return SimpleNamespace(
            media_type="image/png",
            content_length=len(content),
            sha256="sha256:" + hashlib.sha256(content).hexdigest(),
            iter_chunks=iter_chunks,
        )

    def assessment_pages(self, batch_id: str, occurrence_revision_id: str) -> SimpleNamespace:
        assert batch_id == "legacybatch_" + "1" * 32
        assert occurrence_revision_id == "occurrev_" + "2" * 32
        return SimpleNamespace(
            pages=(
                AssessmentPageImagePointer(
                    page_input_id="assessmentpage_" + "3" * 32,
                    source_role="PROBLEM_DOCUMENT",
                    physical_page=1,
                    artifact_id="artifact_" + "4" * 32,
                    artifact_revision_id="rev_" + "5" * 32,
                    member_path="pages/problem-1.png",
                    sha256="sha256:"
                    + hashlib.sha256(b"\x89PNG\r\n\x1a\nASSESSMENT_PAGE").hexdigest(),
                    content_length=len(b"\x89PNG\r\n\x1a\nASSESSMENT_PAGE"),
                    width_px=1240,
                    height_px=1754,
                ),
            )
        )

    def load_assessment_page_media(
        self, batch_id: str, occurrence_revision_id: str, page_input_id: str
    ) -> SimpleNamespace:
        assert batch_id == "legacybatch_" + "1" * 32
        assert occurrence_revision_id == "occurrev_" + "2" * 32
        assert page_input_id == "assessmentpage_" + "3" * 32
        content = b"\x89PNG\r\n\x1a\nASSESSMENT_PAGE"

        def iter_chunks() -> object:
            yield content

        return SimpleNamespace(
            media_type="image/png",
            content_length=len(content),
            sha256="sha256:" + hashlib.sha256(content).hexdigest(),
            iter_chunks=iter_chunks,
        )

    def load_pdf_document_review_page_media(
        self,
        request: PdfDocumentReviewPageMediaQuery,
    ) -> SimpleNamespace:
        document = _pdf_review_document_pointer()
        assert request.document_id == document.document_id
        assert request.document_revision_id == document.document_revision_id
        assert request.page_number == 1
        assert request.page_image == document.pages[0].page_image

        def iter_chunks() -> object:
            yield PDF_REVIEW_PAGE

        return SimpleNamespace(
            media_type="image/png",
            content_length=len(PDF_REVIEW_PAGE),
            sha256="sha256:" + hashlib.sha256(PDF_REVIEW_PAGE).hexdigest(),
            iter_chunks=iter_chunks,
        )


PDF_REVIEW_PAGE = b"\x89PNG\r\n\x1a\nPDF_REVIEW_PAGE"


class FakeOfficeDocumentReviewIntake:
    def __init__(self, staging_root: Path) -> None:
        staging_root.mkdir(mode=0o700)
        self.settings = SimpleNamespace(staging_root=staging_root)
        self.calls: list[tuple[bytes, str, str, str, str, bool]] = []
        self.retained_source = OfficeDocumentReviewMemberPointerV2(
            artifact_id="artifact_" + "7" * 32,
            artifact_revision_id="rev_" + "8" * 32,
            member_path="source/original.hwpx",
            sha256="sha256:" + "9" * 64,
            content_length=16,
            media_type="application/vnd.hancom.hwpx",
            schema_ref="eom://schemas/document-review/editable-hwpx/1.0",
        )

    def ingest(
        self,
        source: Path,
        *,
        original_filename: str,
        source_format: str,
        actor_id: str,
        idempotency_key: str,
        durable_source: bool,
    ) -> object:
        self.calls.append(
            (
                source.read_bytes(),
                original_filename,
                source_format,
                actor_id,
                idempotency_key,
                durable_source,
            )
        )
        raise OfficeDocumentReviewIntakeError(
            "OFFICE_DOCUMENT_CONVERSION_RETURNED_FAILURE",
            "typed converter failure",
            retained_source=self.retained_source,
        )


def _pdf_review_document_pointer() -> PdfReviewDocumentPointer:
    artifact_id = "artifact_" + "a" * 32
    revision_id = "rev_" + "b" * 32
    return PdfReviewDocumentPointer(
        document_id="document_" + "c" * 32,
        document_revision_id="documentrev_" + "d" * 32,
        original_filename="review.pdf",
        source_pdf=PdfReviewArtifactMemberPointer(
            artifact_id=artifact_id,
            artifact_revision_id=revision_id,
            member_path="source/original.pdf",
            sha256="sha256:" + "e" * 64,
            schema_ref="eom://schemas/document-review/pdf-source/1.0",
            media_type="application/pdf",
            content_length=16,
        ),
        page_count=1,
        pages=(
            PdfReviewPagePointer(
                page_number=1,
                width_px=1200,
                height_px=1600,
                rotation_degrees=0,
                page_image=PdfReviewArtifactMemberPointer(
                    artifact_id=artifact_id,
                    artifact_revision_id=revision_id,
                    member_path="pages/page-0001.png",
                    sha256="sha256:" + hashlib.sha256(PDF_REVIEW_PAGE).hexdigest(),
                    schema_ref="eom://schemas/document-review/pdf-page-render/1.0",
                    media_type="image/png",
                    content_length=len(PDF_REVIEW_PAGE),
                ),
                text_layer=None,
            ),
        ),
    )


class FakePdfDocumentReviewIntake:
    def __init__(self, staging_root: Path) -> None:
        staging_root.mkdir(mode=0o700)
        self.settings = SimpleNamespace(staging_root=staging_root)
        self.calls: list[tuple[bytes, str, str, str]] = []

    def ingest(
        self,
        source: Path,
        *,
        original_filename: str,
        actor_id: str,
        idempotency_key: str,
    ) -> PdfReviewDocumentPointer:
        self.calls.append((source.read_bytes(), original_filename, actor_id, idempotency_key))
        return _pdf_review_document_pointer()


class FakeContentTeamRegistry(FakeRegistry):
    def load_item_content(self, _revision_id: str) -> AssessmentItemContentV2:
        return content_team_item()


def _content_team_item_v3() -> AssessmentItemContentV3:
    value = content_team_item().model_dump(mode="json")
    value["schema_version"] = "3.0"
    return AssessmentItemContentV3.model_validate(value)


class FakeContentTeamV3Registry(FakeRegistry):
    def load_item_content(self, _revision_id: str) -> AssessmentItemContentV3:
        return _content_team_item_v3()


class FakeKnowledgeAnalysis:
    def create(self, _command: object) -> KnowledgeAnalysisApplicationResult:
        return KnowledgeAnalysisApplicationResult(
            analysis_run_id="analysisrun_" + "7" * 32,
            workflow_id="workflow_" + "8" * 32,
            state="QUEUED",
            resource_version=3,
        )

    def create_solution(self, _command: object) -> KnowledgeAnalysisApplicationResult:
        return KnowledgeAnalysisApplicationResult(
            analysis_run_id="analysisrun_" + "b" * 32,
            workflow_id="workflow_" + "c" * 32,
            state="QUEUED",
            resource_version=3,
        )

    reconcile = create
    review = create


class FakeKnowledgeAnalysisBatch:
    def create(self, _command: object) -> KnowledgeAnalysisBatchApplicationResult:
        return KnowledgeAnalysisBatchApplicationResult(
            batch_id="analysisbatch_" + "9" * 32,
            state="QUEUED",
            resource_version=1,
            total_range_count=1,
            accepted_range_count=0,
            failed_range_count=0,
        )


class FakeKnowledgeRetrieval:
    def create(self, command: object) -> EvidenceBundlePublicationResult:
        assert isinstance(command, CreateEvidenceBundleCommand)
        value = {
            "schema_version": "evidence-bundle-publication-result/1.0",
            "evidence_bundle_id": "evidence_" + "1" * 32,
            "evidence_bundle_revision_id": "evidencerev_" + "2" * 32,
            "revision_number": 1,
            "state": "PUBLISHED",
            "retrieval_request_id": "retrieval_" + "3" * 32,
            "retrieval_request_sha256": "sha256:" + "4" * 64,
            "graph_snapshot": {
                "graph_id": "graph_" + "5" * 32,
                "graph_snapshot_revision_id": command.graph_snapshot_revision_id,
                "manifest_artifact": {
                    "artifact_id": "artifact_" + "6" * 32,
                    "artifact_revision_id": "rev_" + "7" * 32,
                    "sha256": "sha256:" + "8" * 64,
                    "schema_ref": ("eom://schemas/knowledge/knowledge-graph-snapshot-manifest/2.0"),
                    "media_type": "application/json",
                    "logical_name": "manifest.json",
                    "member_path": "projections/manifest.json",
                },
                "manifest_sha256": "sha256:" + "8" * 64,
            },
            "access_policy_revision_id": command.access_policy_revision_id,
            "access_policy_sha256": "sha256:" + "9" * 64,
            "manifest_artifact": {
                "artifact_id": "artifact_" + "a" * 32,
                "artifact_revision_id": "rev_" + "b" * 32,
                "sha256": "sha256:" + "c" * 64,
                "schema_ref": "eom://schemas/knowledge/evidence-bundle-manifest/2.0",
                "media_type": "application/json",
                "logical_name": "manifest.json",
                "member_path": "evidence/manifest.json",
            },
            "manifest_sha256": "sha256:" + "d" * 64,
            "budget": {
                "document_count": 1,
                "item_revision_count": 0,
                "graph_node_count": 1,
                "claim_count": 0,
                "estimated_context_tokens": 128,
            },
            "published_at": "2026-08-24T00:00:00Z",
            "result_sha256": "sha256:" + "0" * 64,
        }
        value["result_sha256"] = content_sha256(
            {key: item for key, item in value.items() if key != "result_sha256"}
        )
        return EvidenceBundlePublicationResult.model_validate(value)

    def create_item_production(
        self, command: CreateItemProductionEvidenceCommand
    ) -> EvidenceBundlePublicationResultV2:
        legacy_command = _retrieval_command()
        base = self.create(legacy_command)
        value = {
            **base.model_dump(mode="json", exclude={"schema_version", "result_sha256"}),
            "schema_version": "evidence-bundle-publication-result/2.0",
            "access_policy_revision_id": command.access_policy_revision_id,
            "access_policy_sha256": command.access_policy_sha256,
            "requester_permissions_sha256": content_sha256(
                {"permission_keys": list(command.requester_permission_keys)}
            ),
            "context_artifact": {
                "artifact_id": "artifact_" + "e" * 32,
                "artifact_revision_id": "rev_" + "e" * 32,
                "sha256": "sha256:" + "e" * 64,
                "schema_ref": "eom://schemas/knowledge/evidence-bundle-context/1.0",
                "media_type": "text/markdown",
                "logical_name": "context.md",
                "member_path": "evidence/context.md",
            },
            "result_sha256": "sha256:" + "0" * 64,
        }
        value["result_sha256"] = content_sha256(
            {key: item for key, item in value.items() if key != "result_sha256"}
        )
        return EvidenceBundlePublicationResultV2.model_validate(value)


class FakeItemReviews:
    def publish(
        self,
        command: PublishMockExamItemReviewCommand,
    ) -> MockExamItemReviewPublicationResultV2:
        return MockExamItemReviewPublicationResultV2(
            item_review_record_id="itemreview_" + "1" * 32,
            item_revision_id=command.item_revision_id,
            workflow_id=command.expected_workflow_id,
            review_step_run_id="steprun_" + "2" * 32,
            human_approval_request_id="approval_" + "3" * 32,
            review_artifact_id="artifact_" + "4" * 32,
            review_artifact_revision_id="rev_" + "5" * 32,
            review_sha256="sha256:" + "6" * 64,
            decision_sha256="sha256:" + "7" * 64,
            review_result_schema="review-result@9.0",
            final_rating=command.final_rating,
            finding_counts=MockExamReviewFindingCounts(info=0, warning=0, blocking=0),
            reviewer_operator_id=command.reviewer_operator_id,
            rating_policy_revision_id=command.rating_policy_revision_id,
            rating_policy_sha256=command.rating_policy_sha256,
            created=True,
        )

    def inspect_eligibility(
        self,
        query: InspectMockExamReviewEligibilityQuery,
    ) -> MockExamReviewEligibilityResultV2:
        return MockExamReviewEligibilityResultV2(
            workflow_id=query.workflow_id,
            workflow_lock_version=1,
            approval_state="PENDING",
            approval_request_id="approval_" + "3" * 32,
            approval_lock_version=1,
            reviewer_operator_id=None,
            approved_at=None,
            review_step_run_id="steprun_" + "2" * 32,
            review_artifact_id="artifact_" + "4" * 32,
            review_artifact_revision_id="rev_" + "5" * 32,
            review_sha256="sha256:" + "6" * 64,
            review_result_schema="review-result@9.0",
            review_summary="V3 검토 결과를 사람 승인 전에 확인한다.",
            findings=(),
            finding_counts=MockExamEligibilityFindingCounts(info=0, warning=0, blocking=0),
            eligible=True,
            eligibility_reason="ELIGIBLE",
        )


def _assembly_plan() -> MockExamAssemblyPlanV2:
    planned_at = datetime(2026, 9, 14, 0, 0, tzinfo=UTC)
    candidates = _planning_candidates_v2()
    plan = build_mock_exam_assembly_plan(
        policy=load_integrated_science_mock_exam_policy(),
        layout_policy=load_integrated_science_mock_exam_layout_policy(),
        rating_policy=load_integrated_science_mock_exam_rating_policy(),
        graph_snapshot_revision_id=_identifier("graphrev_", 1),
        graph_snapshot_sha256="sha256:" + "1" * 64,
        usage_snapshot=_usage_snapshot(
            captured_at=planned_at,
            candidate_revision_count=len(candidates),
        ),
        resolved_candidate_count=len(candidates),
        candidates=candidates,
        planned_at=planned_at,
    )
    assert isinstance(plan, MockExamAssemblyPlanV2)
    return plan


def _assembly_manifest() -> MockExamAssemblyManifestV3:
    plan = _assembly_plan()
    value = {
        "schema_version": "mock-exam-assembly-manifest/3.0",
        "assessment_assembly_revision_id": _identifier("assemblyrev_", 1),
        "assessment_assembly_id": _identifier("assembly_", 2),
        "assessment_form_id": _identifier("form_", 3),
        "assessment_form_revision_id": _identifier("formrev_", 4),
        "deliverable_id": _identifier("deliverable_", 5),
        "deliverable_revision_id": _identifier("delivrev_", 6),
        "form_key": "main",
        "display_label": "본시험지",
        "plan": plan.model_dump(mode="json"),
        "revision_state": "RELEASED",
        "created_at": "2026-09-14T00:00:00Z",
        "created_by": _identifier("operator_", 7),
    }
    value["manifest_sha256"] = content_sha256(value)
    return MockExamAssemblyManifestV3.model_validate(value)


class FakeAssemblies:
    def preview(self, _command: object) -> MockExamAssemblyPlanV2:
        return _assembly_plan()

    def create(self, _command: object) -> MockExamAssemblyManifestV3:
        return _assembly_manifest()

    def create_planned(self, _command: object) -> MockExamAssemblyManifestV3:
        return _assembly_manifest()

    def inspect_revision(self, revision_id: str) -> MockExamAssemblyManifestV3:
        assert revision_id == _identifier("assemblyrev_", 1)
        return _assembly_manifest()


def _assembly_preview_command() -> PreviewMockExamAssemblyPlanCommand:
    plan = _assembly_plan()
    return PreviewMockExamAssemblyPlanCommand(
        policy_revision_id=plan.policy_revision_id,
        policy_sha256=plan.policy_sha256,
        graph_snapshot_revision_id=plan.graph_snapshot_revision_id,
        graph_snapshot_sha256=plan.graph_snapshot_sha256,
    )


def _assembly_create_command() -> CreateMockExamAssemblyCommand:
    manifest = _assembly_manifest()
    selections = tuple(
        MockExamAssemblySelection(
            position=row.position,
            item_id=row.item_id,
            item_revision_id=row.item_revision_id,
            item_manifest_sha256=row.item_manifest_sha256,
            graph_placement_node_id=row.graph_item_node_id,
            curriculum_unit_keys=row.curriculum_unit_keys,
            points_milli=row.points_milli,
            coverage_role=row.coverage_role,
            coverage_requirement_id=row.coverage_requirement_id,
            is_inquiry=row.is_inquiry,
            material_type=row.material_profile,
        )
        for row in manifest.plan.placements
    )
    return CreateMockExamAssemblyCommand(
        deliverable_id=manifest.deliverable_id,
        deliverable_revision_id=manifest.deliverable_revision_id,
        form_key=manifest.form_key,
        display_label=manifest.display_label,
        policy_revision_id=manifest.plan.policy_revision_id,
        policy_sha256=manifest.plan.policy_sha256,
        graph_snapshot_revision_id=manifest.plan.graph_snapshot_revision_id,
        graph_snapshot_sha256=manifest.plan.graph_snapshot_sha256,
        placements=selections,
        actor_id=manifest.created_by,
    )


def _assembly_create_planned_command() -> CreatePlannedMockExamAssemblyCommand:
    manifest = _assembly_manifest()
    return CreatePlannedMockExamAssemblyCommand(
        deliverable_id=manifest.deliverable_id,
        deliverable_revision_id=manifest.deliverable_revision_id,
        form_key=manifest.form_key,
        display_label=manifest.display_label,
        policy_revision_id=manifest.plan.policy_revision_id,
        policy_sha256=manifest.plan.policy_sha256,
        graph_snapshot_revision_id=manifest.plan.graph_snapshot_revision_id,
        graph_snapshot_sha256=manifest.plan.graph_snapshot_sha256,
        expected_plan_sha256=manifest.plan.plan_sha256,
        planned_at=manifest.plan.planned_at,
        actor_id=manifest.created_by,
    )


def _retrieval_command() -> CreateEvidenceBundleCommand:
    value = {
        "operation": "CREATE_EVIDENCE_BUNDLE",
        "graph_snapshot_revision_id": "graphrev_" + "e" * 32,
        "query_kind": "ITEM_PREPARATION",
        "curriculum_scope": None,
        "topic_keys": ["earth.plate-boundary"],
        "target_item_revision_id": None,
        "required_item_elements": [],
        "source_classes": ["TEXTBOOK"],
        "evidence_budget": {
            "max_documents": 2,
            "max_item_revisions": 0,
            "max_graph_nodes": 8,
            "max_claims": 2,
            "max_context_tokens": 2000,
        },
        "access_policy_revision_id": "accessrev_" + "f" * 32,
        "requester_role": "ADMIN",
        "requester_permission_keys": ["knowledge_graph:read", "knowledge_graph:retrieve"],
        "requested_by": "operator_" + "1" * 32,
        "idempotency_key": "knowledge-retrieval-round-trip",
        "submission_sha256": "sha256:" + "0" * 64,
    }
    value["submission_sha256"] = content_sha256(
        {
            key: item
            for key, item in value.items()
            if key not in {"idempotency_key", "submission_sha256"}
        }
    )
    return CreateEvidenceBundleCommand.model_validate(value)


def _item_evidence_command() -> CreateItemProductionEvidenceCommand:
    value = {
        "operation": "CREATE_ITEM_PRODUCTION_EVIDENCE",
        "requirement": {
            "schema_version": "educational-retrieval-requirement/1.0",
            "corpus_key": "science-core",
            "query_kind": "ITEM_PREPARATION",
            "curriculum_root_key": "earth.plate-boundary",
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
        "access_policy_revision_id": "accessrev_" + "f" * 32,
        "access_policy_sha256": "sha256:" + "f" * 64,
        "requester_role": "ADMIN",
        "requester_permission_keys": ["knowledge_graph:read", "knowledge_graph:retrieve"],
        "requested_by": "operator_" + "1" * 32,
        "solution_evidence_requirement": "NONE",
        "idempotency_key": "item-production-evidence-round-trip",
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


def _batch_command() -> CreateKnowledgeAnalysisBatchCommand:
    value = {
        "operation": "CREATE_KNOWLEDGE_ANALYSIS_BATCH",
        "request": {
            "schema_version": "knowledge-analysis-batch-request/1.0",
            "preset_key": "knowledge-analysis",
            "general_knowledge_mode": "AUXILIARY_UNATTRIBUTED",
            "risk_policy_revision_id": "analysisriskrev_" + "3" * 32,
            "review_policy": "PREAUTHORIZED_APPROVE_VALIDATED",
            "ranges": [
                {
                    "ordinal": 0,
                    "source": {
                        "source_kind": "DOCUMENT_REVISION",
                        "source_class": "TEXTBOOK",
                        "document_revision_id": "edudocrev_" + "4" * 32,
                        "first_physical_page": 1,
                        "last_physical_page": 4,
                        "curriculum_unit_keys": ["1-(1)"],
                    },
                    "execution": {
                        "mode": "EXECUTE",
                        "predecessor_analysis_run_id": None,
                    },
                }
            ],
        },
        "requested_by": "operator_" + "1" * 32,
        "authorized_at": "2026-08-26T00:00:00Z",
        "idempotency_key": "knowledge-analysis-batch-round-trip",
        "submission_sha256": "sha256:" + "0" * 64,
    }
    value["submission_sha256"] = content_sha256(
        {
            "request": value["request"],
            "requested_by": value["requested_by"],
        }
    )
    return CreateKnowledgeAnalysisBatchCommand.model_validate(value)


def _unmapped_batch_command() -> CreateKnowledgeAnalysisBatchCommand:
    value = _batch_command().model_dump(mode="json")
    value["request"]["schema_version"] = "knowledge-analysis-batch-request/1.1"
    value["request"]["ranges"][0]["source"]["curriculum_unit_keys"] = []
    value["submission_sha256"] = content_sha256(
        {"request": value["request"], "requested_by": value["requested_by"]}
    )
    return CreateKnowledgeAnalysisBatchCommand.model_validate(value)


def _continuing_batch_command() -> CreateKnowledgeAnalysisBatchCommand:
    value = _unmapped_batch_command().model_dump(mode="json")
    value["request"]["schema_version"] = "knowledge-analysis-batch-request/1.2"
    value["request"]["range_failure_policy"] = "CONTINUE_AND_COLLECT"
    value["submission_sha256"] = content_sha256(
        {"request": value["request"], "requested_by": value["requested_by"]}
    )
    return CreateKnowledgeAnalysisBatchCommand.model_validate(value)


def _server(
    tmp_path: Path,
    *,
    allowed_uid: int | None = None,
    registry: FakeRegistry | None = None,
    item_reviews: FakeItemReviews | None = None,
    knowledge_retrieval: FakeKnowledgeRetrieval | None = None,
    assemblies: FakeAssemblies | None = None,
    pdf_intake: FakePdfDocumentReviewIntake | None = None,
    office_intake: FakeOfficeDocumentReviewIntake | None = None,
) -> CatalogApplicationServer:
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o750)
    runtime.chmod(0o750)
    return CatalogApplicationServer(  # type: ignore[arg-type]
        FakeImports(),
        registry or FakeRegistry(),
        FakeKnowledgeAnalysis(),
        FakeKnowledgeAnalysisBatch(),
        knowledge_retrieval or FakeKnowledgeRetrieval(),
        mock_exam_item_reviews=item_reviews,  # type: ignore[arg-type]
        mock_exam_assemblies=assemblies or FakeAssemblies(),  # type: ignore[arg-type]
        pdf_document_review_intake=pdf_intake,  # type: ignore[arg-type]
        office_document_review_intake=office_intake,  # type: ignore[arg-type]
        socket_path=runtime / "manager.sock",
        allowed_uid=os.getuid() if allowed_uid is None else allowed_uid,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )


def _client(server: CatalogApplicationServer) -> CatalogApplicationClient:
    return CatalogApplicationClient(
        server.socket_path,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )


def test_catalog_evidence_generation_uses_its_bounded_response_window() -> None:
    assert EVIDENCE_RESPONSE_TIMEOUT_SECONDS == 120.0
    assert EVIDENCE_RESPONSE_TIMEOUT_SECONDS + 30 < DEFAULT_IDEMPOTENCY_LEASE_SECONDS
    assert (
        CatalogApplicationClient._response_timeout_seconds(_retrieval_command())
        == EVIDENCE_RESPONSE_TIMEOUT_SECONDS
    )
    assert (
        CatalogApplicationClient._response_timeout_seconds(_item_evidence_command())
        == EVIDENCE_RESPONSE_TIMEOUT_SECONDS
    )
    assert (
        CatalogApplicationClient._response_timeout_seconds(_batch_command())
        == RESPONSE_TIMEOUT_SECONDS
    )


def test_catalog_assembly_uses_its_bounded_response_window() -> None:
    command = _assembly_create_planned_command()
    assert ASSEMBLY_RESPONSE_TIMEOUT_SECONDS == 120.0
    assert (
        CatalogApplicationClient._response_timeout_seconds(command)
        == ASSEMBLY_RESPONSE_TIMEOUT_SECONDS
    )


def test_catalog_evidence_response_window_is_applied_to_the_unix_socket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SlowKnowledgeRetrieval(FakeKnowledgeRetrieval):
        def create_item_production(
            self, command: CreateItemProductionEvidenceCommand
        ) -> EvidenceBundlePublicationResultV2:
            time.sleep(0.1)
            return super().create_item_production(command)

    # Scale both bounds down while preserving their production ordering. If the client applies the
    # ordinary metadata timeout after send, this real AF_UNIX round trip deterministically fails.
    monkeypatch.setattr(catalog_application_client_module, "RESPONSE_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(catalog_application_client_module, "EVIDENCE_RESPONSE_TIMEOUT_SECONDS", 1.0)
    server = _server(tmp_path, knowledge_retrieval=SlowKnowledgeRetrieval())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = _client(server).create_item_production_evidence(_item_evidence_command())
        assert result.context_artifact.member_path == "evidence/context.md"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_pdf_document_review_intake_streams_exact_bytes_over_private_socket(
    tmp_path: Path,
) -> None:
    payload = b"%PDF-1.7\nEOM immutable review source\n"
    source = tmp_path / "source.pdf"
    source.write_bytes(payload)
    source.chmod(0o600)
    intake = FakePdfDocumentReviewIntake(tmp_path / "catalog-staging")
    server = _server(tmp_path, pdf_intake=intake)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = _client(server).ingest_pdf_document_review_source(
            source,
            actor_id="operator_test_admin",
            original_filename="review.pdf",
            idempotency_key="pdf-review-private-stream-round-trip",
        )
        assert result == _pdf_review_document_pointer()
        assert intake.calls == [
            (
                payload,
                "review.pdf",
                "operator_test_admin",
                "pdf-review-private-stream-round-trip",
            )
        ]
        assert not tuple((tmp_path / "catalog-staging").iterdir())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_pdf_document_review_intake_rejects_stream_hash_mismatch(tmp_path: Path) -> None:
    payload = b"%PDF-1.7\nwrong declared hash\n"
    intake = FakePdfDocumentReviewIntake(tmp_path / "catalog-staging")
    server = _server(tmp_path, pdf_intake=intake)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        connection.connect(str(server.socket_path))
        command = PdfDocumentReviewIntakeCommand(
            actor_id="operator_test_admin",
            original_filename="review.pdf",
            idempotency_key="pdf-review-private-stream-wrong-hash",
            content_length=len(payload),
            sha256="sha256:" + "0" * 64,
        )
        connection.sendall(
            json.dumps(
                command.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
            + b"\n"
            + payload
        )
        connection.shutdown(socket.SHUT_WR)
        response = PdfDocumentReviewIntakeResponse.model_validate(
            json.loads(CatalogApplicationClient._read_response(connection))
        )
        assert response.status == "ERROR"
        assert response.error_code == "PDF_DOCUMENT_REVIEW_UPLOAD_HASH_MISMATCH"
        assert intake.calls == []
        assert not tuple((tmp_path / "catalog-staging").iterdir())
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_office_document_review_v3_failure_returns_retained_source_pointer(
    tmp_path: Path,
) -> None:
    payload = b"PK\x03\x04EOM-HWPX-V3"
    source = tmp_path / "source.hwpx"
    source.write_bytes(payload)
    source.chmod(0o600)
    intake = FakeOfficeDocumentReviewIntake(tmp_path / "office-staging")
    intake.retained_source = intake.retained_source.model_copy(
        update={
            "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
            "content_length": len(payload),
        }
    )
    server = _server(tmp_path, office_intake=intake)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(CatalogApplicationClientError) as error:
            _client(server).ingest_office_document_review_source(
                source,
                actor_id="operator_test_admin",
                original_filename="review.hwpx",
                source_format="HWPX",
                media_type="application/vnd.hancom.hwpx",
                idempotency_key="office-review-v3-private-stream-failure",
            )
        assert error.value.code == "OFFICE_DOCUMENT_CONVERSION_RETURNED_FAILURE"
        assert error.value.retained_source == intake.retained_source
        assert intake.calls == [
            (
                payload,
                "review.hwpx",
                "HWPX",
                "operator_test_admin",
                "office-review-v3-private-stream-failure",
                True,
            )
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_pdf_document_review_client_rejects_hardlinked_upload(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.7\nhardlink\n")
    source.chmod(0o600)
    os.link(source, tmp_path / "alias.pdf")
    with pytest.raises(CatalogApplicationClientError) as error:
        CatalogApplicationClient(tmp_path / "absent.sock").ingest_pdf_document_review_source(
            source,
            actor_id="operator_test_admin",
            original_filename="review.pdf",
            idempotency_key="pdf-review-private-stream-hardlink",
        )
    assert error.value.code == str(CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE)


def test_pdf_document_review_page_streams_only_its_exact_pinned_member(
    tmp_path: Path,
) -> None:
    document = _pdf_review_document_pointer()
    page = document.pages[0]
    command = PdfDocumentReviewPageMediaQuery(
        document_id=document.document_id,
        document_revision_id=document.document_revision_id,
        page_number=page.page_number,
        page_image=page.page_image,
    )
    validate_contract(
        "pdf-document-review-page-media-request",
        command.model_dump(mode="json"),
    )
    success = PdfDocumentReviewPageMediaResponse(
        status="OK",
        media_type="image/png",
        content_length=len(PDF_REVIEW_PAGE),
        sha256=page.page_image.sha256,
    )
    validate_contract(
        "pdf-document-review-page-media-response",
        success.model_dump(mode="json", exclude_none=True),
    )

    server = _server(tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        media = _client(server).download_pdf_document_review_page(
            document_id=document.document_id,
            document_revision_id=document.document_revision_id,
            page_number=page.page_number,
            page_image=page.page_image,
        )
        assert b"".join(media.iter_chunks()) == PDF_REVIEW_PAGE
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_catalog_application_contract_validates_schema_and_typed_models() -> None:
    command = ReviewedItemContentImportCommand(
        base_revision_id="itemrev_" + "6" * 32,
        expected_version=1,
        reviewed_by="operator_test_admin",
        review_reason="검토된 구조화 문항과 모든 포인터를 승인합니다.",
        content=AssessmentItemContent.model_validate(item_content()),
    )
    request = CatalogApplicationRequest(root=command).model_dump(mode="json")
    validate_contract("catalog-application-request", request)
    response = CatalogApplicationResponse(
        status="OK",
        operation="GET_ITEM_CONTENT",
        content=AssessmentItemContent.model_validate(item_content()),
    ).model_dump(mode="json", exclude_none=True)
    validate_contract("catalog-application-response", response)

    pdf_command = PdfDocumentReviewIntakeCommand(
        actor_id="operator_test_admin",
        original_filename="review.pdf",
        idempotency_key="pdf-review-intake-contract-key",
        content_length=16,
        sha256="sha256:" + "1" * 64,
    )
    validate_contract(
        "pdf-document-review-intake-request",
        pdf_command.model_dump(mode="json"),
    )
    pdf_response = PdfDocumentReviewIntakeResponse(
        status="OK",
        document=_pdf_review_document_pointer(),
    )
    pdf_response_value = pdf_response.model_dump(mode="json")
    pdf_response_value.pop("error_code")
    validate_contract(
        "pdf-document-review-intake-response",
        pdf_response_value,
    )

    analysis_command = CreateKnowledgeAnalysisCommand(
        source={
            "source_kind": "CONTENT_INTAKE_FILE",
            "source_class": "TEXTBOOK",
            "intake_batch_id": "intake_" + "1" * 32,
            "source_file_id": "sourcefile_" + "2" * 32,
        },
        preset_key="knowledge-analysis",
        general_knowledge_mode="DISABLED",
        risk_policy_revision_id="analysisriskrev_" + "3" * 32,
        requested_by="operator_test_admin",
        idempotency_key="knowledge-analysis-contract-key",
    )
    analysis_request = CatalogApplicationRequest(root=analysis_command).model_dump(mode="json")
    validate_contract("catalog-application-request-v2", analysis_request)
    analysis_response = CatalogApplicationResponse(
        status="OK",
        operation="CREATE_KNOWLEDGE_ANALYSIS",
        analysis=FakeKnowledgeAnalysis().create(analysis_command),
    ).model_dump(mode="json", exclude_none=True)
    validate_contract("catalog-application-response-v2", analysis_response)

    solution_command = CreateKnowledgeSolutionAnalysisCommand(
        base_analysis_run_id="analysisrun_" + "a" * 32,
        requested_by="operator_test_admin",
        idempotency_key="knowledge-solution-analysis-contract-key",
    )
    solution_request = CatalogApplicationRequest(root=solution_command).model_dump(mode="json")
    validate_contract("catalog-application-request-v14", solution_request)
    solution_response = CatalogApplicationResponse(
        status="OK",
        operation="CREATE_KNOWLEDGE_SOLUTION_ANALYSIS",
        analysis=KnowledgeAnalysisApplicationResult(
            analysis_run_id="analysisrun_" + "b" * 32,
            workflow_id="workflow_" + "c" * 32,
            state="REQUESTED",
            resource_version=1,
        ),
    ).model_dump(mode="json", exclude_none=True)
    validate_contract("catalog-application-response-v14", solution_response)

    document_analysis_command = CreateKnowledgeAnalysisCommand(
        source={
            "source_kind": "DOCUMENT_REVISION",
            "source_class": "TEXTBOOK",
            "document_revision_id": "edudocrev_" + "4" * 32,
            "first_physical_page": 10,
            "last_physical_page": 11,
            "curriculum_unit_keys": ["1-(1)"],
        },
        preset_key="knowledge-analysis",
        general_knowledge_mode="AUXILIARY_UNATTRIBUTED",
        risk_policy_revision_id="analysisriskrev_" + "5" * 32,
        requested_by="operator_test_admin",
        idempotency_key="knowledge-analysis-document-contract-key",
    )
    document_analysis_request = CatalogApplicationRequest(
        root=document_analysis_command
    ).model_dump(mode="json")
    validate_contract("catalog-application-request-v5", document_analysis_request)

    batch_command = _batch_command()
    batch_request = CatalogApplicationRequest(root=batch_command).model_dump(mode="json")
    validate_contract("catalog-application-request-v6", batch_request)
    validate_contract("catalog-application-request-v7", batch_request)
    unmapped_batch_request = CatalogApplicationRequest(root=_unmapped_batch_command()).model_dump(
        mode="json"
    )
    validate_contract("catalog-application-request-v7", unmapped_batch_request)
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("catalog-application-request-v6", unmapped_batch_request)
    continuing_batch_request = CatalogApplicationRequest(
        root=_continuing_batch_command()
    ).model_dump(mode="json")
    validate_contract("catalog-application-request-v8", continuing_batch_request)
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("catalog-application-request-v7", continuing_batch_request)
    batch_response = CatalogApplicationResponse(
        status="OK",
        operation="CREATE_KNOWLEDGE_ANALYSIS_BATCH",
        analysis_batch=FakeKnowledgeAnalysisBatch().create(batch_command),
    ).model_dump(mode="json", exclude_none=True)
    validate_contract("catalog-application-response-v7", batch_response)

    retrieval_command = _retrieval_command()
    retrieval_request = CatalogApplicationRequest(root=retrieval_command).model_dump(mode="json")
    validate_contract("catalog-application-request-v3", retrieval_request)
    retrieval_response = CatalogApplicationResponse(
        status="OK",
        operation="CREATE_EVIDENCE_BUNDLE",
        evidence=FakeKnowledgeRetrieval().create(retrieval_command),
    ).model_dump(mode="json", exclude_none=True)
    validate_contract("catalog-application-response-v3", retrieval_response)
    validate_contract("catalog-application-response-v5", retrieval_response)
    item_command = _item_evidence_command()
    item_request = CatalogApplicationRequest(root=item_command).model_dump(mode="json")
    validate_contract("catalog-application-request-v16", item_request)
    invalid_item_request = dict(item_request)
    invalid_item_request.pop("solution_evidence_requirement")
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("catalog-application-request-v16", invalid_item_request)
    item_response = CatalogApplicationResponse(
        status="OK",
        operation="CREATE_ITEM_PRODUCTION_EVIDENCE",
        item_production_evidence=FakeKnowledgeRetrieval().create_item_production(item_command),
    ).model_dump(mode="json", exclude_none=True)
    validate_contract("catalog-application-response-v4", item_response)
    validate_contract("catalog-application-response-v6", item_response)
    media_request = ItemMediaQuery(
        item_revision_id="itemrev_" + "2" * 32,
        block_id="block_image",
    ).model_dump(mode="json")
    validate_contract("catalog-item-media-request", media_request)
    media_response = CatalogItemMediaResponse(
        status="OK",
        media_type="image/png",
        content_length=12,
        sha256="sha256:" + "a" * 64,
    ).model_dump(mode="json", exclude_none=True)
    validate_contract("catalog-item-media-response", media_response)
    component_media_request = ItemComponentMediaQuery(
        item_revision_id="itemrev_" + "2" * 32,
        ordinal=1,
    ).model_dump(mode="json")
    validate_contract("catalog-item-component-media-request", component_media_request)
    component_media_response = CatalogItemComponentMediaResponse(
        status="OK",
        media_type="image/png",
        content_length=12,
        sha256="sha256:" + "b" * 64,
    ).model_dump(mode="json", exclude_none=True)
    validate_contract("catalog-item-component-media-response", component_media_response)
    page_list_request = {
        "operation": "GET_ASSESSMENT_PAGE_IMAGES",
        "extraction_batch_id": "legacybatch_" + "1" * 32,
        "assessment_occurrence_revision_id": "occurrev_" + "2" * 32,
    }
    validate_contract("catalog-assessment-page-list-request", page_list_request)
    page_media_request = {
        **page_list_request,
        "operation": "GET_ASSESSMENT_PAGE_IMAGE",
        "page_input_id": "assessmentpage_" + "3" * 32,
    }
    validate_contract("catalog-assessment-page-media-request", page_media_request)

    for assembly_command in (
        _assembly_preview_command(),
        _assembly_create_command(),
        _assembly_create_planned_command(),
        InspectMockExamAssemblyQuery(
            assessment_assembly_revision_id=_identifier("assemblyrev_", 1)
        ),
    ):
        assembly_request = CatalogApplicationRequest(root=assembly_command).model_dump(mode="json")
        validate_contract("catalog-application-request-v15", assembly_request)
    assembly_plan_response = {
        key: value
        for key, value in CatalogApplicationResponse(
            status="OK",
            operation="PREVIEW_MOCK_EXAM_ASSEMBLY_PLAN",
            assembly_plan=_assembly_plan(),
        )
        .model_dump(mode="json")
        .items()
        if value is not None
    }
    validate_contract("catalog-application-response-v16", assembly_plan_response)
    assembly_response = {
        key: value
        for key, value in CatalogApplicationResponse(
            status="OK",
            operation="CREATE_PLANNED_MOCK_EXAM_ASSEMBLY",
            assembly=_assembly_manifest(),
        )
        .model_dump(mode="json")
        .items()
        if value is not None
    }
    validate_contract("catalog-application-response-v16", assembly_response)


def test_catalog_socket_round_trip_preserves_typed_content_and_import_result(
    tmp_path: Path,
) -> None:
    server = _server(tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = _client(server)
        imported = client.import_reviewed(
            ReviewedItemContentImportCommand(
                base_revision_id="itemrev_" + "6" * 32,
                expected_version=1,
                reviewed_by="operator_test_admin",
                review_reason="검토된 구조화 문항과 모든 포인터를 승인합니다.",
                content=AssessmentItemContent.model_validate(item_content()),
            )
        )
        assert imported.item_revision_id == "itemrev_" + "2" * 32
        loaded = client.load_item_content("itemrev_" + "2" * 32)
        assert loaded == AssessmentItemContent.model_validate(item_content())
        media = client.download_item_media("itemrev_" + "2" * 32, "block_image")
        media_bytes = b"".join(media.iter_chunks())
        assert media_bytes == b"\x89PNG\r\n\x1a\nCATALOG_MEDIA"
        assert media.media_type == "image/png"
        component_media = client.download_item_component_media(
            "itemrev_" + "2" * 32,
            "IMAGE",
            1,
        )
        assert b"".join(component_media.iter_chunks()) == (
            b"\x89PNG\r\n\x1a\nCATALOG_COMPONENT_MEDIA"
        )
        assert component_media.media_type == "image/png"
        pages = client.assessment_pages(
            "legacybatch_" + "1" * 32,
            "occurrev_" + "2" * 32,
        )
        assert len(pages) == 1
        assert pages[0].page_input_id == "assessmentpage_" + "3" * 32
        page_media = client.download_assessment_page(
            "legacybatch_" + "1" * 32,
            "occurrev_" + "2" * 32,
            "assessmentpage_" + "3" * 32,
        )
        assert b"".join(page_media.iter_chunks()) == b"\x89PNG\r\n\x1a\nASSESSMENT_PAGE"
        analysis = client.create_knowledge_analysis(
            CreateKnowledgeAnalysisCommand(
                source={
                    "source_kind": "CONTENT_INTAKE_FILE",
                    "source_class": "TEXTBOOK",
                    "intake_batch_id": "intake_" + "1" * 32,
                    "source_file_id": "sourcefile_" + "2" * 32,
                },
                preset_key="knowledge-analysis",
                general_knowledge_mode="DISABLED",
                risk_policy_revision_id="analysisriskrev_" + "3" * 32,
                requested_by="operator_test_admin",
                idempotency_key="knowledge-analysis-round-trip",
            )
        )
        assert analysis.analysis_run_id == "analysisrun_" + "7" * 32
        solution = client.create_knowledge_solution_analysis(
            CreateKnowledgeSolutionAnalysisCommand(
                base_analysis_run_id="analysisrun_" + "a" * 32,
                requested_by="operator_test_admin",
                idempotency_key="knowledge-solution-analysis-round-trip",
            )
        )
        assert solution.analysis_run_id == "analysisrun_" + "b" * 32
        batch = client.create_knowledge_analysis_batch(_batch_command())
        assert batch.batch_id == "analysisbatch_" + "9" * 32
        evidence = client.create_evidence_bundle(_retrieval_command())
        assert evidence.evidence_bundle_revision_id == "evidencerev_" + "2" * 32
        assert evidence.graph_snapshot.graph_snapshot_revision_id == "graphrev_" + "e" * 32
        item_evidence = client.create_item_production_evidence(_item_evidence_command())
        assert item_evidence.context_artifact.member_path == "evidence/context.md"
        plan = client.preview_mock_exam_assembly_plan(_assembly_preview_command())
        assert plan == _assembly_plan()
        created = client.create_mock_exam_assembly(_assembly_create_command())
        assert created == _assembly_manifest()
        planned = client.create_planned_mock_exam_assembly(_assembly_create_planned_command())
        assert planned == _assembly_manifest()
        inspected = client.inspect_mock_exam_assembly(
            InspectMockExamAssemblyQuery(
                assessment_assembly_revision_id=_identifier("assemblyrev_", 1)
            )
        )
        assert inspected == _assembly_manifest()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_catalog_socket_round_trip_uses_v10_for_content_team_items(tmp_path: Path) -> None:
    server = _server(tmp_path, registry=FakeContentTeamRegistry())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = _client(server)
        imported = client.import_reviewed(
            ReviewedItemContentImportCommand(
                base_revision_id="itemrev_" + "6" * 32,
                expected_version=1,
                reviewed_by="operator_test_admin",
                review_reason="콘텐츠팀 구조화 문항의 검토된 표현 정규화를 승인합니다.",
                content=content_team_item(),
            )
        )
        assert imported.item_revision_id == "itemrev_" + "2" * 32
        assert client.load_item_content("itemrev_" + "2" * 32) == content_team_item()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_catalog_socket_round_trip_uses_v12_for_content_team_v3_items(tmp_path: Path) -> None:
    server = _server(tmp_path, registry=FakeContentTeamV3Registry())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = _client(server)
        imported = client.import_reviewed(
            ReviewedItemContentImportCommand(
                base_revision_id="itemrev_" + "6" * 32,
                expected_version=1,
                reviewed_by="operator_test_admin",
                review_reason="콘텐츠팀 V3 구조화 문항의 검토된 표현 정규화를 승인합니다.",
                content=_content_team_item_v3(),
            )
        )
        assert imported.item_revision_id == "itemrev_" + "2" * 32
        assert client.load_item_content("itemrev_" + "2" * 32) == _content_team_item_v3()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_catalog_socket_round_trip_selects_v12_for_review_result_9(tmp_path: Path) -> None:
    server = _server(tmp_path, item_reviews=FakeItemReviews())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = _client(server)
        published = client.publish_mock_exam_item_review(
            PublishMockExamItemReviewCommand(
                item_revision_id="itemrev_" + "1" * 32,
                expected_workflow_id="workflow_" + "2" * 32,
                final_rating="A",
                reviewer_operator_id="operator_" + "3" * 32,
                rating_policy_revision_id="ratingpolicyrev_" + "4" * 32,
                rating_policy_sha256="sha256:" + "5" * 64,
                idempotency_key="catalog-v12-review-result-9",
            )
        )
        eligibility = client.inspect_mock_exam_review_eligibility(
            InspectMockExamReviewEligibilityQuery(workflow_id="workflow_" + "2" * 32)
        )
        assert isinstance(published, MockExamItemReviewPublicationResultV2)
        assert published.schema_version == "mock-exam-item-review-publication-result/2.0"
        assert isinstance(eligibility, MockExamReviewEligibilityResultV2)
        assert eligibility.schema_version == "mock-exam-review-eligibility-result/2.0"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_catalog_socket_rejects_wrong_peer_and_unsafe_socket_metadata(tmp_path: Path) -> None:
    server = _server(tmp_path, allowed_uid=os.getuid() + 1)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(CatalogApplicationClientError) as raised:
            _client(server).load_item_content("itemrev_" + "2" * 32)
        assert (
            raised.value.code == CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE.value
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    regular = tmp_path / "not-a-socket"
    regular.write_bytes(b"")
    client = CatalogApplicationClient(
        regular,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    with pytest.raises(CatalogApplicationClientError) as raised:
        client.load_item_content("itemrev_" + "2" * 32)
    assert raised.value.code == CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE.value


def test_catalog_client_preserves_stable_graph_concurrency_error() -> None:
    with pytest.raises(CatalogApplicationClientError) as raised:
        CatalogApplicationClient._raise_remote_error("KNOWLEDGE_GRAPH_STALE_CURRENT")

    assert raised.value.code == "KNOWLEDGE_GRAPH_STALE_CURRENT"


def test_catalog_client_preserves_stable_assembly_error() -> None:
    with pytest.raises(CatalogApplicationClientError) as raised:
        CatalogApplicationClient._raise_remote_error("ASSEMBLY_CANDIDATE_SHORTAGE")

    assert raised.value.code == "ASSEMBLY_CANDIDATE_SHORTAGE"


def test_catalog_client_preserves_stable_office_conversion_error() -> None:
    with pytest.raises(CatalogApplicationClientError) as raised:
        CatalogApplicationClient._raise_remote_error("OFFICE_DOCUMENT_CONVERSION_FAILED")

    assert raised.value.code == "OFFICE_DOCUMENT_CONVERSION_FAILED"


def test_catalog_application_systemd_boundary_keeps_api_away_from_nas() -> None:
    unit = Path("infra/systemd/eom-catalog-application-runner.service").read_text(encoding="utf-8")
    assert "User=eom-catalog-manager" in unit
    assert "Group=eom-api" in unit
    assert "SupplementaryGroups=eom" in unit
    assert "Environment=EOM_CATALOG_STAGING_ROOT=/var/lib/eom-catalog-api/staging" in unit
    assert "ExecStartPre=/usr/bin/install -d -m 0750 " in unit
    assert "/var/lib/eom-catalog-api/staging/registry" in unit
    assert "ReadWritePaths=/srv/eom/staging/catalog" not in unit
    assert "InaccessiblePaths=/srv/eom/staging/catalog" in unit
    assert "ReadWritePaths=/mnt/nas/eom/artifacts" in unit
    assert "InaccessiblePaths=/etc/eom/secrets/api.env" in unit
    assert "NoNewPrivileges=true" in unit
    assert "CapabilityBoundingSet=\n" in unit
    api_unit = Path("infra/systemd/eom-api.service").read_text(encoding="utf-8")
    assert (
        "After=network-online.target docker.service eom-catalog-application-runner.service"
        in api_unit
    )
    assert "Wants=network-online.target eom-catalog-application-runner.service" in api_unit
    assert "ReadWritePaths=/mnt/nas" not in api_unit
    assert "ReadWritePaths=/srv/eom/staging/catalog" not in api_unit
    assert "InaccessiblePaths=/etc/eom/secrets/catalog-manager.env" in api_unit


def test_workflow_runner_uses_its_own_catalog_staging_identity() -> None:
    unit = Path("infra/systemd/eom-workflow-runner.service").read_text(encoding="utf-8")
    composition = Path("services/workflow_runner/eom_workflow_runner/composition.py").read_text(
        encoding="utf-8"
    )

    private_root = "/var/lib/eom-workflow-runner/catalog-staging"
    assert f"Environment=EOM_CATALOG_STAGING_ROOT={private_root}" in unit
    assert f"ExecStartPre=/usr/bin/install -d -m 0750 {private_root}" in unit
    assert f"{private_root}/content-packs" in unit
    assert f"{private_root}/registry" in unit
    assert f"{private_root}/workflow-prompts" in unit
    assert "InaccessiblePaths=/srv/eom/staging" in unit
    assert 'runner_user="eom-workflow-runner"' in composition


def test_application_api_catalog_client_depends_on_protocol_not_server_implementation() -> None:
    client_source = Path(
        "apps/application_api/eom_api/services/catalog_application_client.py"
    ).read_text(encoding="utf-8")
    problem_source = Path("apps/application_api/eom_api/problem_details.py").read_text(
        encoding="utf-8"
    )
    query_source = Path("apps/application_api/eom_api/services/query_adapter.py").read_text(
        encoding="utf-8"
    )
    command_source = Path("apps/application_api/eom_api/services/command_adapter.py").read_text(
        encoding="utf-8"
    )

    assert "eom_catalog_contracts" in client_source
    assert "eom_catalog_service" not in client_source
    assert "eom_catalog_service" not in problem_source
    assert "MockExamAssemblyService" not in query_source
    assert "MockExamAssemblyService" not in command_source
    assert "mock_exam_assembly_service" not in query_source
    assert "mock_exam_assembly_service" not in command_source
