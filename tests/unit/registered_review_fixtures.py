"""Synthetic registered-review values, not storage/IAM or an actual approved Item."""

from __future__ import annotations

from dataclasses import dataclass

from eom_catalog_contracts.registered_item_review_solution import (
    RegisteredItemReviewSolutionEvidence,
)
from eom_catalog_contracts.registered_review_profile import (
    RegisteredReviewProfile,
    RegisteredReviewSourceBasis,
)
from eom_catalog_service.registered_review_projection import (
    AuthoringResult,
    ReviewResult,
    project_registered_review_solution,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_workflow.models import (
    ContentTeamAuthoringRoleResultV11,
    ContentTeamAuthoringRoleResultV12,
    ContentTeamReviewRoleResultV11,
    ContentTeamReviewRoleResultV12,
)

from tests.unit.inference_transfer_fixtures import NOW, source_basis
from tests.unit.test_graph_review_v11_protocol import (
    _authoring_result,
    _review_document,
    _v12_review_document,
)
from tests.unit.test_registered_item_review_solution_contract import evidence_body


@dataclass(frozen=True, slots=True)
class RegisteredReviewCase:
    basis: RegisteredReviewSourceBasis
    authoring: AuthoringResult
    review: ReviewResult


def registered_review_case(version: str = "11.0") -> RegisteredReviewCase:
    if version not in {"11.0", "12.0"}:
        raise ValueError("unsupported synthetic review version")
    evidence = evidence_body(version)
    fixture = {
        "manifest": {
            "evidence_bundle_id": "evidence_" + "1" * 32,
            "evidence_bundle_revision_id": "evidencerev_" + "1" * 32,
            "retrieval_request_id": "retrieval_" + "1" * 32,
            "graph_snapshot": {"graph_snapshot_revision_id": "graphrev_" + "1" * 32},
            "manifest_sha256": "sha256:" + "1" * 64,
        },
        "context_payload": b"synthetic review evidence, no production content",
    }
    authoring_body = _authoring_result(fixture).model_dump(mode="json")
    authoring_body.update(
        workflow_id=evidence["workflow_id"],
        job_id=evidence["authoring"]["job_id"],
        step_run_id=evidence["authoring"]["step_run_id"],
        protocol_version="workflow-role/1.24.0" if version == "12.0" else "workflow-role/1.23.0",
    )
    authoring_body["artifact"].update(
        logical_artifact_id=evidence["authoring"]["artifact"]["artifact_id"],
        revision_id=evidence["authoring"]["artifact"]["artifact_revision_id"],
    )
    authoring: AuthoringResult = (
        ContentTeamAuthoringRoleResultV12.model_validate(authoring_body)
        if version == "12.0"
        else ContentTeamAuthoringRoleResultV11.model_validate(authoring_body)
    )
    evidence["authoring"]["artifact"]["sha256"] = sha256_bytes(
        canonical_json_bytes(authoring.model_dump(mode="json"))
    )
    review_body = _v12_review_document(fixture) if version == "12.0" else _review_document(fixture)
    review_body.update(
        workflow_id=evidence["workflow_id"],
        job_id=evidence["review"]["job_id"],
        step_run_id=evidence["review"]["step_run_id"],
    )
    review_body["artifact"].update(
        logical_artifact_id=evidence["review"]["artifact"]["artifact_id"],
        revision_id=evidence["review"]["artifact"]["artifact_revision_id"],
    )
    review_body["output"]["evidence_usage_attestation"]["authoring_artifact"].update(
        logical_artifact_id=evidence["authoring"]["artifact"]["artifact_id"],
        revision_id=evidence["authoring"]["artifact"]["artifact_revision_id"],
        content_hash=evidence["authoring"]["artifact"]["sha256"],
    )
    review: ReviewResult = (
        ContentTeamReviewRoleResultV12.model_validate(review_body)
        if version == "12.0"
        else ContentTeamReviewRoleResultV11.model_validate(review_body)
    )
    evidence["review"]["artifact"]["sha256"] = sha256_bytes(
        canonical_json_bytes(review.model_dump(mode="json"))
    )
    evidence["evidence_sha256"] = content_sha256(
        {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    )
    checked = RegisteredItemReviewSolutionEvidence.model_validate(evidence)
    basis = RegisteredReviewSourceBasis(
        source=checked.source,
        graph_snapshot=source_basis().graph_snapshot,
        review_evidence=checked,
    )
    return RegisteredReviewCase(basis, authoring, review)


def registered_review_profile(version: str = "11.0") -> RegisteredReviewProfile:
    case = registered_review_case(version)
    return project_registered_review_solution(
        source_basis=case.basis,
        authoring=case.authoring,
        review=case.review,
        created_at=NOW,
    )
