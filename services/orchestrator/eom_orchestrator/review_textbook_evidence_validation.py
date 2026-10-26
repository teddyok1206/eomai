"""Trusted textbook usage admission for successor scientific document review."""

from __future__ import annotations

from pathlib import Path

from eom_catalog_contracts import EvidenceBundleManifestV3, EvidenceBundleManifestV4
from eom_identifiers import content_sha256
from eom_workflow import (
    PdfDocumentReviewRoleResultV5,
    PdfDocumentReviewWorkerRequestV5,
    ResolvedExecutionPlanV25,
    ReviewTextbookValidationReceipt,
    RoleWorkerInput,
    validate_control_contract,
    validate_single_document_review_textbook_usage,
)
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from sqlalchemy.orm import Session

from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.control_service import ControlPlaneError, compute_control_document_hash
from eom_orchestrator.evidence_usage_validation import EvidenceUsageValidationError
from eom_orchestrator.execution_materializer import (
    authorized_execution_artifact_revisions,
    resolve_textbook_review_materials,
)


def validate_single_document_textbook_for_commit(
    session: Session,
    *,
    plan_id: str | None,
    worker_input: RoleWorkerInput,
    result: PdfDocumentReviewRoleResultV5,
    result_artifact_id: str,
    result_artifact_revision_id: str,
    result_content_sha256: str,
    canonical_artifact_root: Path,
) -> ReviewTextbookValidationReceipt:
    """Reopen the exact pinned Graph bundle before admitting any result bytes."""

    if plan_id is None or not isinstance(worker_input.request, PdfDocumentReviewWorkerRequestV5):
        raise EvidenceUsageValidationError(
            "REVIEW_TEXTBOOK_PLAN_MISSING", "textbook review requires an exact typed request"
        )
    record = session.get(ResolvedExecutionPlanRecord, plan_id)
    if record is None:
        raise EvidenceUsageValidationError(
            "REVIEW_TEXTBOOK_PLAN_MISSING", "textbook review plan is missing"
        )
    try:
        plan = ResolvedExecutionPlanV25.model_validate(record.canonical_document)
    except ValueError as exc:
        raise EvidenceUsageValidationError(
            "REVIEW_TEXTBOOK_PLAN_INVALID", "textbook review plan is invalid"
        ) from exc
    request = worker_input.request
    binding = request.textbook_evidence
    if (
        record.plan_sha256 != plan.plan_sha256
        or compute_control_document_hash(record.canonical_document, "plan_sha256")
        != plan.plan_sha256
        or plan.workflow_id != worker_input.workflow_id
        or plan.workflow_id != result.workflow_id
        or plan.review_request_sha256 != request.review_request.request_sha256
        or plan.document != request.review_request.document
        or plan.textbook_evidence != binding
        or worker_input.protocol_version != "workflow-role/1.31.0"
        or worker_input.role != "support"
        or result.protocol_version != "workflow-role/1.31.0"
        or result.role != "support"
        or result.job_id != worker_input.job_id
        or result.step_run_id != worker_input.step_run_id
    ):
        raise EvidenceUsageValidationError(
            "REVIEW_TEXTBOOK_BINDING_MISMATCH", "textbook review result differs from its plan"
        )
    try:
        authorized = authorized_execution_artifact_revisions(
            session, plan_id=plan.plan_id, step_key="review_document"
        )
        materials = resolve_textbook_review_materials(
            session,
            binding=binding,
            canonical_artifact_root=canonical_artifact_root,
            authorized_artifact_revision_ids=authorized,
        )
        if not isinstance(materials.manifest, EvidenceBundleManifestV3 | EvidenceBundleManifestV4):
            raise ValueError("textbook review manifest family is unsupported")
        validate_single_document_review_textbook_usage(result.output, request, materials.manifest)
    except (ControlPlaneError, ValueError) as exc:
        raise EvidenceUsageValidationError(
            "REVIEW_TEXTBOOK_USAGE_INVALID",
            "textbook review result lacks verified exact-source scientific citations",
        ) from exc
    publication = binding.publication
    receipt_document: dict[str, object] = {
        "schema_version": "review-textbook-validation-receipt/1.0",
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "workflow_id": worker_input.workflow_id,
        "step_run_id": worker_input.step_run_id,
        "job_id": worker_input.job_id,
        "attempt": worker_input.attempt,
        "review_input_sha256": request.review_request.request_sha256,
        "binding_sha256": binding.binding_sha256,
        "graph_snapshot_revision_id": publication.graph_snapshot.graph_snapshot_revision_id,
        "evidence_bundle_revision_id": publication.evidence_bundle_revision_id,
        "evidence_manifest_artifact": publication.manifest_artifact.model_dump(mode="json"),
        "evidence_manifest_sha256": publication.manifest_sha256,
        "evidence_context_artifact": publication.context_artifact.model_dump(mode="json"),
        "usage_sha256": result.output.textbook_usage.usage_sha256,
        "result_artifact_id": result_artifact_id,
        "result_artifact_revision_id": result_artifact_revision_id,
        "result_content_sha256": result_content_sha256,
    }
    receipt_document["receipt_sha256"] = content_sha256(receipt_document)
    try:
        validate_control_contract("review-textbook-validation-receipt", receipt_document)
        return ReviewTextbookValidationReceipt.model_validate(receipt_document)
    except (ValueError, JsonSchemaValidationError) as exc:
        raise EvidenceUsageValidationError(
            "REVIEW_TEXTBOOK_RECEIPT_INVALID", "textbook review validation receipt is invalid"
        ) from exc
