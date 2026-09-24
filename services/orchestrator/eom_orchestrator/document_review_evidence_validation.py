"""Trusted Graph-evidence validation for exhaustive paired document review."""

from __future__ import annotations

from pathlib import Path

from eom_catalog_contracts import EvidenceBundleManifestV5
from eom_identifiers import content_sha256
from eom_workflow import (
    DocumentReviewEvidenceValidationReceipt,
    PairedDocumentReviewRoleResultV3,
    PairedDocumentReviewWorkerRequestV2,
    ResolvedExecutionPlanV15,
    RoleWorkerInput,
    validate_control_contract,
)
from pydantic import ValidationError
from sqlalchemy.orm import Session

from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.evidence_usage_validation import EvidenceUsageValidationError
from eom_orchestrator.execution_materializer import (
    authorized_execution_artifact_revisions,
    resolve_evidence_materials,
)


def _resolve_json_pointer(document: object, pointer: str) -> object:
    value = document
    for raw_token in pointer.removeprefix("/").split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict):
            if token not in value:
                raise EvidenceUsageValidationError(
                    "DOCUMENT_REVIEW_EVIDENCE_PATH_MISSING",
                    "document review evidence path is absent",
                )
            value = value[token]
        elif isinstance(value, list) and token.isdigit() and int(token) < len(value):
            value = value[int(token)]
        else:
            raise EvidenceUsageValidationError(
                "DOCUMENT_REVIEW_EVIDENCE_PATH_MISSING",
                "document review evidence path cannot be resolved",
            )
    if value is None or isinstance(value, (dict, list)):
        raise EvidenceUsageValidationError(
            "DOCUMENT_REVIEW_EVIDENCE_PATH_NOT_LEAF",
            "document review evidence path must end at a non-null primitive",
        )
    return value


def validate_document_review_evidence_for_commit(
    session: Session,
    *,
    plan_id: str | None,
    worker_input: RoleWorkerInput,
    result: PairedDocumentReviewRoleResultV3,
    result_artifact_id: str,
    result_artifact_revision_id: str,
    result_content_sha256: str,
    canonical_artifact_root: Path,
) -> DocumentReviewEvidenceValidationReceipt:
    """Validate citations against exact plan and manifest before NAS commit."""

    if plan_id is None or not isinstance(worker_input.request, PairedDocumentReviewWorkerRequestV2):
        raise EvidenceUsageValidationError(
            "DOCUMENT_REVIEW_EVIDENCE_PLAN_MISSING",
            "Graph-grounded document review requires its exact typed plan",
        )
    record = session.get(ResolvedExecutionPlanRecord, plan_id)
    if record is None:
        raise EvidenceUsageValidationError(
            "DOCUMENT_REVIEW_EVIDENCE_PLAN_MISSING",
            "Graph-grounded document review plan is missing",
        )
    try:
        plan = ResolvedExecutionPlanV15.model_validate(record.canonical_document)
    except ValueError as exc:
        raise EvidenceUsageValidationError(
            "DOCUMENT_REVIEW_EVIDENCE_PLAN_INVALID",
            "Graph-grounded document review plan is invalid",
        ) from exc
    request = worker_input.request.review_request
    if (
        record.plan_sha256 != plan.plan_sha256
        or plan.workflow_id != worker_input.workflow_id
        or plan.workflow_id != result.workflow_id
        or plan.review_request_sha256 != request.request_sha256
        or plan.evidence_plan_sha256 != request.evidence_plan.plan_sha256
        or worker_input.protocol_version != "workflow-role/1.27.0"
        or worker_input.role != "support"
        or result.protocol_version != "workflow-role/1.27.0"
        or result.role != "support"
        or result.job_id != worker_input.job_id
        or result.step_run_id != worker_input.step_run_id
    ):
        raise EvidenceUsageValidationError(
            "DOCUMENT_REVIEW_EVIDENCE_BINDING_MISMATCH",
            "document review evidence identities differ",
        )
    try:
        authorized = authorized_execution_artifact_revisions(
            session,
            plan_id=plan.plan_id,
            step_key="review_document",
        )
        materials = resolve_evidence_materials(
            session,
            plan=plan,
            canonical_artifact_root=canonical_artifact_root,
            authorized_artifact_revision_ids=authorized,
        )
    except (ControlPlaneError, ValidationError) as exc:
        raise EvidenceUsageValidationError(
            "DOCUMENT_REVIEW_EVIDENCE_MATERIAL_INVALID",
            "document review Evidence Bundle could not be resolved",
        ) from exc
    usage = result.output.evidence_usage
    if (
        usage.evidence_bundle_id != plan.evidence_bundle_id
        or usage.evidence_bundle_revision_id != plan.evidence_bundle_revision_id
        or usage.retrieval_request_id != plan.retrieval_request_id
        or usage.graph_snapshot_revision_id != plan.graph_snapshot.graph_snapshot_revision_id
        or usage.manifest_sha256 != plan.evidence_manifest_sha256
        or usage.context_sha256 != plan.evidence_context_artifact.sha256
    ):
        raise EvidenceUsageValidationError(
            "DOCUMENT_REVIEW_EVIDENCE_USAGE_MISMATCH",
            "document review evidence usage differs from the immutable plan",
        )
    if not isinstance(materials.manifest, EvidenceBundleManifestV5):
        raise EvidenceUsageValidationError(
            "DOCUMENT_REVIEW_EVIDENCE_MANIFEST_INVALID",
            "document review requires a solution-enriched Evidence Bundle V5 manifest",
        )
    entries = {entry.evidence_id: entry for entry in materials.manifest.entries}
    output_document = result.output.model_dump(mode="json")
    for citation in usage.citations:
        entry = entries.get(citation.evidence_id)
        if entry is None or not set(citation.anchor_ids).issubset(entry.anchor_ids):
            raise EvidenceUsageValidationError(
                "DOCUMENT_REVIEW_EVIDENCE_CITATION_INVALID",
                "document review citation is absent from the manifest",
            )
        if citation.application == "SOLUTION_VERIFICATION" and entry.solution_evidence is None:
            raise EvidenceUsageValidationError(
                "DOCUMENT_REVIEW_SOLUTION_EVIDENCE_MISSING",
                "solution verification requires accepted solution evidence",
            )
        if citation.application == "ORIGINALITY_COMPARISON" and entry.use not in {
            "REFERENCE_PATTERN",
            "AVOID_COPY",
        }:
            raise EvidenceUsageValidationError(
                "DOCUMENT_REVIEW_ORIGINALITY_EVIDENCE_INVALID",
                "originality comparison requires reference-pattern or avoid-copy evidence",
            )
        if citation.application == "AVOID_COPY_CHECK" and entry.use != "AVOID_COPY":
            raise EvidenceUsageValidationError(
                "DOCUMENT_REVIEW_ORIGINALITY_EVIDENCE_INVALID",
                "avoid-copy review requires avoid-copy evidence",
            )
        for pointer in citation.review_json_paths:
            _resolve_json_pointer(output_document, pointer)
    citation_set_sha256 = content_sha256(
        {
            "schema_version": "document-review-evidence-citation-set/1.0",
            "citations": [value.model_dump(mode="json") for value in usage.citations],
        }
    )
    receipt_document: dict[str, object] = {
        "schema_version": "document-review-evidence-validation-receipt/1.0",
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "workflow_id": worker_input.workflow_id,
        "step_run_id": worker_input.step_run_id,
        "job_id": worker_input.job_id,
        "attempt": worker_input.attempt,
        "review_request_sha256": request.request_sha256,
        "evidence_plan_sha256": plan.evidence_plan_sha256,
        "retrieval_request_id": plan.retrieval_request_id,
        "graph_snapshot_revision_id": plan.graph_snapshot.graph_snapshot_revision_id,
        "evidence_bundle_id": plan.evidence_bundle_id,
        "evidence_bundle_revision_id": plan.evidence_bundle_revision_id,
        "evidence_manifest_artifact": plan.evidence_manifest_artifact.model_dump(mode="json"),
        "evidence_manifest_sha256": plan.evidence_manifest_sha256,
        "evidence_context_artifact": plan.evidence_context_artifact.model_dump(mode="json"),
        "result_artifact_id": result_artifact_id,
        "result_artifact_revision_id": result_artifact_revision_id,
        "result_content_sha256": result_content_sha256,
        "citation_set_sha256": citation_set_sha256,
        "receipt_sha256": "sha256:" + "0" * 64,
    }
    receipt_document["receipt_sha256"] = content_sha256(
        {key: value for key, value in receipt_document.items() if key != "receipt_sha256"}
    )
    try:
        validate_control_contract(
            "document-review-evidence-validation-receipt",
            receipt_document,
        )
        return DocumentReviewEvidenceValidationReceipt.model_validate(receipt_document)
    except ValueError as exc:
        raise EvidenceUsageValidationError(
            "DOCUMENT_REVIEW_EVIDENCE_RECEIPT_INVALID",
            "document review evidence receipt is invalid",
        ) from exc
