from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_catalog_contracts import EvidenceBundleManifestV5
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.evidence_usage_validation import (
    EvidenceUsageValidationError,
    _validate_independent_review_report,
    canonical_review_evidence_set_sha256,
    evidence_receipt_event_data,
    validate_evidence_usage_for_commit,
)
from eom_orchestrator.execution_materializer import ResolvedEvidenceMaterials
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_workflow import EvidenceResultArtifactPointerV2
from eom_workflow.control_plane import ReviewEvidenceUsageValidationReceiptV2
from eom_workflow.models import (
    ArtifactPointer,
    ArtifactSpec,
    ContentTeamAuthoringRoleResultV11,
    ContentTeamReviewRoleResultV11,
    RoleWorkerInput,
    WorkerRequest,
)
from eom_workflow.schemas import (
    WorkflowSchemaError,
    role_schema_bundle_hash,
    validate_role_result,
)
from pydantic import ValidationError

from tests.unit.test_content_team_v3_protocol import _content_v3
from tests.unit.test_execution_materializer import FakeSession, _knowledge_fixture

EVIDENCE_ID = "evidenceitem_" + "3" * 32
AUTHORING_JOB_ID = "job_" + "7" * 32
AUTHORING_ARTIFACT_ID = "artifact_" + "7" * 32
AUTHORING_REVISION_ID = "rev_" + "7" * 32


def test_graph_review_protocol_bundle_hash_is_immutable() -> None:
    assert role_schema_bundle_hash("workflow-role/1.23.0") == (
        "sha256:420f4372d91e48349e911cec42ad44c867e9f1a31e6190b44fc38100f9a4019c"
    )


def _review_document(fixture: dict[str, Any]) -> dict[str, Any]:
    citation = {
        "evidence_id": EVIDENCE_ID,
        "anchor_ids": ["anchor_item"],
        "application": "STRUCTURE_PATTERN",
        "application_description": "The pinned structure informed the authored stem.",
        "draft_json_paths": ["/stem"],
    }
    reference = {
        "evidence_id": EVIDENCE_ID,
        "anchor_ids": ["anchor_item"],
        "purposes": [
            "CURRICULUM_SCOPE",
            "ORIGINALITY_CHECK",
            "SCIENTIFIC_VALIDATION",
        ],
    }
    choices = [
        {
            "number": number,
            "verdict": "CORRECT" if number == "②" else "DISTRACTOR",
            "rationale": f"Choice {number} was checked against the bounded scientific evidence.",
            "draft_json_paths": [f"/choices/{index}/text"],
            "evidence_ids": [EVIDENCE_ID],
        }
        for index, number in enumerate(("①", "②", "③", "④", "⑤"))
    ]
    return {
        "schema_version": "1.0",
        "protocol_version": "workflow-role/1.23.0",
        "job_id": "job_" + "8" * 32,
        "workflow_id": "workflow_" + "8" * 32,
        "step_run_id": "steprun_" + "8" * 32,
        "role": "review",
        "status": "ok",
        "artifact": {
            "logical_artifact_id": "artifact_" + "8" * 32,
            "revision_id": "rev_" + "8" * 32,
            "file_name": "result.json",
            "media_type": "application/json",
        },
        "completed_at": datetime(2026, 9, 18, tzinfo=UTC).isoformat().replace("+00:00", "Z"),
        "output": {
            "review": {
                "decision": "ready_for_human",
                "findings": [],
                "summary": "Independent answer, choices, explanation, scope, and originality pass.",
            },
            "independent_review_report": {
                "schema_version": "independent-item-review/1.0",
                "evidence_references": [reference],
                "answer_review": {
                    "authored_answer_number": "②",
                    "derived_answer_number": "②",
                    "alignment": "MATCH",
                    "verification_summary": "The independent bounded derivation selects choice ②.",
                    "claims": [
                        {
                            "claim_key": "claim_answer",
                            "conclusion": "The stem conditions support the selected relation.",
                            "draft_json_paths": ["/stem"],
                            "evidence_ids": [EVIDENCE_ID],
                        }
                    ],
                },
                "choice_diagnostics": choices,
                "statement_diagnostics": [],
                "explanation_assessment": {
                    "status": "PASS",
                    "rationale": "The explanation is consistent with the selected answer.",
                    "draft_json_paths": ["/explanations/correct_answer"],
                    "evidence_ids": [EVIDENCE_ID],
                },
                "curriculum_assessment": {
                    "status": "IN_SCOPE",
                    "rationale": "The assessed concept is inside the pinned curriculum scope.",
                    "draft_json_paths": ["/stem"],
                    "evidence_ids": [EVIDENCE_ID],
                },
                "originality_assessment": {
                    "status": "DISTINCT",
                    "rationale": "The item uses a related pattern without copying the source item.",
                    "draft_json_paths": ["/stem"],
                    "evidence_ids": [EVIDENCE_ID],
                },
                "visual_assessment": {
                    "status": "NOT_APPLICABLE",
                    "rationale": "The authored item has no visual component.",
                    "draft_json_paths": [],
                    "evidence_ids": [],
                },
            },
            "evidence_usage_attestation": {
                "schema_version": "evidence-usage-review-attestation/2.0",
                "decision": "VERIFIED",
                "authoring_artifact": {
                    "logical_artifact_id": "artifact_" + "7" * 32,
                    "revision_id": "rev_" + "7" * 32,
                    "content_hash": "sha256:" + "7" * 64,
                    "result_schema": "authoring-result@11.0",
                },
                "citations": [citation],
            },
        },
    }


def _materials(fixture: dict[str, Any]) -> ResolvedEvidenceMaterials:
    return ResolvedEvidenceMaterials(
        manifest=EvidenceBundleManifestV5.model_validate(fixture["manifest"]),
        manifest_payload=fixture["manifest_payload"],
        context_payload=fixture["context_payload"],
    )


def _authoring_result(
    fixture: dict[str, Any], *, graph_grounded: bool = True
) -> ContentTeamAuthoringRoleResultV11:
    manifest = fixture["manifest"]
    return ContentTeamAuthoringRoleResultV11.model_validate(
        {
            "job_id": AUTHORING_JOB_ID,
            "workflow_id": "workflow_" + "8" * 32,
            "step_run_id": "steprun_" + "7" * 32,
            "role": "authoring",
            "artifact": ArtifactSpec(
                logical_artifact_id=AUTHORING_ARTIFACT_ID,
                revision_id=AUTHORING_REVISION_ID,
            ),
            "completed_at": datetime(2026, 9, 18, tzinfo=UTC),
            "output": {
                "draft": _content_v3().model_dump(mode="json"),
                "metadata": {
                    "subject": "통합과학",
                    "topic": "독립 검토",
                    "difficulty": "medium",
                    "knowledge_source_mode": (
                        "graph_grounded" if graph_grounded else "general_model_knowledge"
                    ),
                },
                "evidence_usage": (
                    {
                        "schema_version": "evidence-usage/1.0",
                        "evidence_bundle_id": manifest["evidence_bundle_id"],
                        "evidence_bundle_revision_id": manifest["evidence_bundle_revision_id"],
                        "retrieval_request_id": manifest["retrieval_request_id"],
                        "graph_snapshot_revision_id": manifest["graph_snapshot"][
                            "graph_snapshot_revision_id"
                        ],
                        "evidence_manifest_sha256": manifest["manifest_sha256"],
                        "evidence_context_sha256": sha256_bytes(fixture["context_payload"]),
                        "citations": [
                            {
                                "evidence_id": EVIDENCE_ID,
                                "anchor_ids": ["anchor_item"],
                                "application": "STRUCTURE_PATTERN",
                                "application_description": (
                                    "The pinned structure informed the authored stem."
                                ),
                                "draft_json_paths": ["/stem"],
                            }
                        ],
                    }
                    if graph_grounded
                    else None
                ),
            },
        }
    )


def _ungrounded_review_document(
    fixture: dict[str, Any], *, reported_answer: str = "②"
) -> dict[str, Any]:
    document = _review_document(fixture)
    report = document["output"]["independent_review_report"]
    report["evidence_references"] = []
    report["answer_review"].update(
        {
            "authored_answer_number": reported_answer,
            "derived_answer_number": reported_answer,
            "alignment": "MATCH",
        }
    )
    for claim in report["answer_review"]["claims"]:
        claim["evidence_ids"] = []
    for choice in report["choice_diagnostics"]:
        choice["verdict"] = "CORRECT" if choice["number"] == reported_answer else "DISTRACTOR"
        choice["evidence_ids"] = []
    for diagnostic in report["statement_diagnostics"]:
        diagnostic["evidence_ids"] = []
    for axis in (
        "explanation_assessment",
        "curriculum_assessment",
        "originality_assessment",
        "visual_assessment",
    ):
        report[axis]["evidence_ids"] = []
    document["output"]["evidence_usage_attestation"] = None
    return document


def _persist_authoring(
    fixture: dict[str, Any], result: ContentTeamAuthoringRoleResultV11
) -> ArtifactPointer:
    session = fixture["session"]
    assert isinstance(session, FakeSession)
    worker_input = RoleWorkerInput(
        protocol_version="workflow-role/1.23.0",
        job_id=result.job_id,
        workflow_id=result.workflow_id,
        step_run_id=result.step_run_id,
        attempt=1,
        role="authoring",
        request=WorkerRequest(request_name="GENERATED_KNOWLEDGE_ITEM_REQUEST", image_mode="skip"),
        upstream_artifacts=(),
        artifact=result.artifact,
    )
    document = result.model_dump(mode="json")
    payload = canonical_json_bytes(document)
    content_hash = sha256_bytes(payload)
    artifact_root = fixture["artifact_root"] / AUTHORING_ARTIFACT_ID / AUTHORING_REVISION_ID
    artifact_root.mkdir(parents=True)
    (artifact_root / "result.json").write_bytes(payload)
    manifest = {
        "job_id": AUTHORING_JOB_ID,
        "logical_artifact_id": AUTHORING_ARTIFACT_ID,
        "revision_id": AUTHORING_REVISION_ID,
        "content_hash": content_hash,
        "content_bytes": len(payload),
    }
    session.records[(ArtifactRecord, AUTHORING_ARTIFACT_ID)] = SimpleNamespace(
        approved=True, job_id=AUTHORING_JOB_ID
    )
    session.records[(ArtifactRevisionRecord, AUTHORING_REVISION_ID)] = SimpleNamespace(
        approved=True,
        job_id=AUTHORING_JOB_ID,
        logical_artifact_id=AUTHORING_ARTIFACT_ID,
        content_hash=content_hash,
        content_bytes=len(payload),
        nas_path=str(artifact_root),
        manifest=manifest,
        result=document,
    )
    session.records[(JobRecord, AUTHORING_JOB_ID)] = SimpleNamespace(
        job_id=AUTHORING_JOB_ID,
        protocol_version="workflow-role/1.23.0",
        logical_artifact_id=AUTHORING_ARTIFACT_ID,
        revision_id=AUTHORING_REVISION_ID,
        request=worker_input.model_dump(mode="json"),
    )
    return ArtifactPointer(
        step_key="authoring",
        attempt=1,
        job_id=AUTHORING_JOB_ID,
        logical_artifact_id=AUTHORING_ARTIFACT_ID,
        revision_id=AUTHORING_REVISION_ID,
        content_hash=content_hash,
        result_schema="authoring-result@11.0",
    )


def test_v11_review_schema_model_and_solution_grounded_validation_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _knowledge_fixture(
        tmp_path,
        monkeypatch,
        manifest_schema_version="5.0",
        workflow_definition_version="1.11.0",
    )
    document = _review_document(fixture)

    result = validate_role_result(document, "review", "review-result@11.0")

    assert isinstance(result, ContentTeamReviewRoleResultV11)
    _validate_independent_review_report(
        _materials(fixture), result, _content_v3().model_dump(mode="json")
    )
    expected_hash = content_sha256(
        {
            "schema_version": "independent-review-evidence-set/1.0",
            "evidence_references": document["output"]["independent_review_report"][
                "evidence_references"
            ],
        }
    )
    assert canonical_review_evidence_set_sha256(result) == expected_hash


def test_v11_review_rejects_missing_report_and_mismatched_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _knowledge_fixture(
        tmp_path,
        monkeypatch,
        manifest_schema_version="5.0",
        workflow_definition_version="1.11.0",
    )
    missing = _review_document(fixture)
    del missing["output"]["independent_review_report"]
    with pytest.raises(WorkflowSchemaError):
        validate_role_result(missing, "review", "review-result@11.0")

    mismatch = _review_document(fixture)
    mismatch["output"]["independent_review_report"]["answer_review"].update(
        {"derived_answer_number": "③", "alignment": "MISMATCH"}
    )
    choices = mismatch["output"]["independent_review_report"]["choice_diagnostics"]
    choices[1]["verdict"] = "DISTRACTOR"
    choices[2]["verdict"] = "CORRECT"
    with pytest.raises(ValidationError, match="INDEPENDENT_ANSWER_MISMATCH"):
        ContentTeamReviewRoleResultV11.model_validate(mismatch)


def test_v11_review_requires_solution_report_for_scientific_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _knowledge_fixture(
        tmp_path,
        monkeypatch,
        manifest_schema_version="5.0",
        workflow_definition_version="1.11.0",
    )
    result = ContentTeamReviewRoleResultV11.model_validate(_review_document(fixture))
    manifest_value = deepcopy(fixture["manifest"])
    manifest_value["entries"][0]["solution_evidence"] = None
    manifest_value["manifest_sha256"] = content_sha256(
        {key: value for key, value in manifest_value.items() if key != "manifest_sha256"}
    )
    materials = ResolvedEvidenceMaterials(
        manifest=EvidenceBundleManifestV5.model_validate(manifest_value),
        manifest_payload=fixture["manifest_payload"],
        context_payload=fixture["context_payload"],
    )

    with pytest.raises(EvidenceUsageValidationError) as captured:
        _validate_independent_review_report(
            materials, result, _content_v3().model_dump(mode="json")
        )

    assert captured.value.code == "EVIDENCE_REVIEW_SOLUTION_REPORT_UNUSED"


def test_v11_review_commit_reloads_authoring_and_emits_hashed_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _knowledge_fixture(
        tmp_path,
        monkeypatch,
        manifest_schema_version="5.0",
        workflow_definition_version="1.11.0",
    )
    plan_record = fixture["session"].records[(ResolvedExecutionPlanRecord, str(fixture["plan_id"]))]
    plan_document = deepcopy(plan_record.canonical_document)
    plan_document["retrieval_requirement"]["required_item_elements"] = ["statement_set"]
    plan_document["retrieval_requirement_sha256"] = content_sha256(
        plan_document["retrieval_requirement"]
    )
    plan_document["steps"].append(
        {
            **plan_document["steps"][0],
            "step_key": "review",
            "role": "review",
            "worker_pool_key": "review",
        }
    )
    plan_document["plan_sha256"] = content_sha256(
        {key: value for key, value in plan_document.items() if key != "plan_sha256"}
    )
    plan_record.canonical_document = plan_document
    plan_record.plan_sha256 = plan_document["plan_sha256"]

    authoring = _authoring_result(fixture)
    authoring_pointer = _persist_authoring(fixture, authoring)
    review_document = _review_document(fixture)
    review_document["output"]["evidence_usage_attestation"]["authoring_artifact"] = {
        "logical_artifact_id": authoring_pointer.logical_artifact_id,
        "revision_id": authoring_pointer.revision_id,
        "content_hash": authoring_pointer.content_hash,
        "result_schema": authoring_pointer.result_schema,
    }
    result = ContentTeamReviewRoleResultV11.model_validate(review_document)
    worker_input = RoleWorkerInput(
        protocol_version="workflow-role/1.23.0",
        job_id=result.job_id,
        workflow_id=result.workflow_id,
        step_run_id=result.step_run_id,
        attempt=1,
        role="review",
        request=WorkerRequest(request_name="GENERATED_KNOWLEDGE_ITEM_REQUEST", image_mode="skip"),
        upstream_artifacts=(authoring_pointer,),
        artifact=result.artifact,
    )
    content_hash = sha256_bytes(canonical_json_bytes(result.model_dump(mode="json")))
    result_pointer = EvidenceResultArtifactPointerV2(
        logical_artifact_id=result.artifact.logical_artifact_id,
        revision_id=result.artifact.revision_id,
        content_hash=content_hash,
        result_schema="review-result@11.0",
    )

    receipt = validate_evidence_usage_for_commit(
        fixture["session"],
        plan_id=str(fixture["plan_id"]),
        step_key="review",
        worker_input=worker_input,
        result=result,
        result_artifact=result_pointer,
        canonical_artifact_root=fixture["artifact_root"],
    )

    assert isinstance(receipt, ReviewEvidenceUsageValidationReceiptV2)
    assert receipt.independent_review_report_sha256 == content_sha256(
        result.output.independent_review_report.model_dump(mode="json")
    )
    assert receipt.review_evidence_set_sha256 == canonical_review_evidence_set_sha256(result)
    event = evidence_receipt_event_data(
        result,
        receipt,
        logical_artifact_id=result.artifact.logical_artifact_id,
        revision_id=result.artifact.revision_id,
        content_hash=content_hash,
    )
    assert event["evidence_usage_validation_receipt"] == receipt.model_dump(mode="json")


def test_v11_ungrounded_review_reloads_and_binds_exact_authoring_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _knowledge_fixture(
        tmp_path,
        monkeypatch,
        manifest_schema_version="5.0",
        workflow_definition_version="1.11.0",
    )
    plan_record = fixture["session"].records[(ResolvedExecutionPlanRecord, str(fixture["plan_id"]))]
    plan_record.canonical_document = {"schema_version": "resolved-execution-plan/1.0"}
    authoring = _authoring_result(fixture, graph_grounded=False)
    authoring_pointer = _persist_authoring(fixture, authoring)
    result = ContentTeamReviewRoleResultV11.model_validate(_ungrounded_review_document(fixture))
    worker_input = RoleWorkerInput(
        protocol_version="workflow-role/1.23.0",
        job_id=result.job_id,
        workflow_id=result.workflow_id,
        step_run_id=result.step_run_id,
        attempt=1,
        role="review",
        request=WorkerRequest(request_name="GENERATED_KNOWLEDGE_ITEM_REQUEST", image_mode="skip"),
        upstream_artifacts=(authoring_pointer,),
        artifact=result.artifact,
    )
    result_pointer = EvidenceResultArtifactPointerV2(
        logical_artifact_id=result.artifact.logical_artifact_id,
        revision_id=result.artifact.revision_id,
        content_hash=sha256_bytes(canonical_json_bytes(result.model_dump(mode="json"))),
        result_schema="review-result@11.0",
    )

    receipt = validate_evidence_usage_for_commit(
        fixture["session"],
        plan_id=str(fixture["plan_id"]),
        step_key="review",
        worker_input=worker_input,
        result=result,
        result_artifact=result_pointer,
        canonical_artifact_root=fixture["artifact_root"],
    )

    assert receipt is None


def test_v11_ungrounded_review_rejects_answer_not_bound_to_authoring_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _knowledge_fixture(
        tmp_path,
        monkeypatch,
        manifest_schema_version="5.0",
        workflow_definition_version="1.11.0",
    )
    authoring = _authoring_result(fixture, graph_grounded=False)
    authoring_pointer = _persist_authoring(fixture, authoring)
    result = ContentTeamReviewRoleResultV11.model_validate(
        _ungrounded_review_document(fixture, reported_answer="③")
    )
    worker_input = RoleWorkerInput(
        protocol_version="workflow-role/1.23.0",
        job_id=result.job_id,
        workflow_id=result.workflow_id,
        step_run_id=result.step_run_id,
        attempt=1,
        role="review",
        request=WorkerRequest(request_name="GENERATED_KNOWLEDGE_ITEM_REQUEST", image_mode="skip"),
        upstream_artifacts=(authoring_pointer,),
        artifact=result.artifact,
    )
    result_pointer = EvidenceResultArtifactPointerV2(
        logical_artifact_id=result.artifact.logical_artifact_id,
        revision_id=result.artifact.revision_id,
        content_hash=sha256_bytes(canonical_json_bytes(result.model_dump(mode="json"))),
        result_schema="review-result@11.0",
    )

    with pytest.raises(EvidenceUsageValidationError) as captured:
        validate_evidence_usage_for_commit(
            fixture["session"],
            plan_id=None,
            step_key="review",
            worker_input=worker_input,
            result=result,
            result_artifact=result_pointer,
            canonical_artifact_root=fixture["artifact_root"],
        )

    assert captured.value.code == "EVIDENCE_REVIEW_AUTHORED_ANSWER_MISMATCH"
