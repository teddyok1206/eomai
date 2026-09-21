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
from eom_workflow import EvidenceResultArtifactPointerV2, EvidenceResultArtifactPointerV3
from eom_workflow.control_plane import (
    BundleRevisionPointer,
    ControlArtifactPointer,
    ModelCandidate,
    ResolvedStepExecutionV12,
    ReviewEvidenceUsageValidationReceiptV2,
    ReviewEvidenceUsageValidationReceiptV3,
)
from eom_workflow.models import (
    ArtifactPointer,
    ArtifactSpec,
    ContentTeamAuthoringRoleResultV11,
    ContentTeamAuthoringRoleResultV12,
    ContentTeamReviewRoleResultV11,
    ContentTeamReviewRoleResultV12,
    RoleWorkerInput,
    WorkerRequest,
)
from eom_workflow.review_escalation import (
    build_review_escalation_directive,
    structural_review_complexity,
    validate_escalated_review_against_source,
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


def test_v12_projected_authoring_restores_canonical_draft_fields() -> None:
    result = ContentTeamAuthoringRoleResultV12.model_validate(
        {
            "job_id": "job_" + "1" * 32,
            "workflow_id": "workflow_" + "2" * 32,
            "step_run_id": "steprun_" + "3" * 32,
            "role": "authoring",
            "artifact": ArtifactSpec(
                logical_artifact_id="artifact_" + "4" * 32,
                revision_id="rev_" + "5" * 32,
            ),
            "completed_at": datetime(2026, 9, 21, tzinfo=UTC),
            "output": {
                "draft": _content_v3(),
                "metadata": {
                    "subject": "통합과학",
                    "topic": "검토 계획 회귀",
                    "difficulty": "medium",
                    "knowledge_source_mode": "general_model_knowledge",
                },
                "evidence_usage": None,
            },
        }
    )
    projected: dict[str, Any] = result.model_dump(mode="json")
    projected["output"]["draft"].pop("visual_layout")

    parsed = validate_role_result(projected, "authoring", "authoring-result@12.0")

    assert isinstance(parsed, ContentTeamAuthoringRoleResultV12)
    assert parsed.output.draft.visual_layout == "NONE"
    assert parsed.output.draft.equation_sources == ()


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


def _v12_review_document(
    fixture: dict[str, Any],
    *,
    score: int = 0,
    candidate_disposition: str | None = None,
    review_pass: str = "PRIMARY",
    reasons: tuple[str, ...] = (),
    source_review: ArtifactPointer | None = None,
) -> dict[str, Any]:
    document = _review_document(fixture)
    document["protocol_version"] = "workflow-role/1.24.0"
    attestation = document["output"]["evidence_usage_attestation"]
    attestation["schema_version"] = "evidence-usage-review-attestation/3.0"
    attestation["authoring_artifact"]["result_schema"] = "authoring-result@12.0"
    report = document["output"]["independent_review_report"]
    report["schema_version"] = "independent-item-review/2.0"
    target_specs = (
        ("target_answer", "ANSWER_DERIVATION", "/choices/1/text"),
        ("target_choice_1", "CHOICE_DIAGNOSTIC", "/choices/0/text"),
        ("target_choice_2", "CHOICE_DIAGNOSTIC", "/choices/1/text"),
        ("target_choice_3", "CHOICE_DIAGNOSTIC", "/choices/2/text"),
        ("target_choice_4", "CHOICE_DIAGNOSTIC", "/choices/3/text"),
        ("target_choice_5", "CHOICE_DIAGNOSTIC", "/choices/4/text"),
        ("target_curriculum", "CURRICULUM_SCOPE", "/stem"),
        ("target_explanation", "EXPLANATION_CONSISTENCY", "/explanations/correct_answer"),
        ("target_originality", "ORIGINALITY", "/stem"),
        ("target_science", "SCIENTIFIC_CLAIM", "/stem"),
    )
    report["verification_targets"] = [
        {
            "target_id": target_id,
            "target_kind": target_kind,
            "draft_json_paths": [path],
            "verification_terms": [target_kind.lower()],
            "required_source_classes": ["APPROVED_ITEM"],
            "selected_evidence_ids": [EVIDENCE_ID],
            "evidence_status": "SUPPORTED",
            "conclusion": "The pinned evidence supports this bounded verification target.",
        }
        for target_id, target_kind, path in target_specs
    ]
    report["candidate_findings"] = (
        []
        if candidate_disposition is None
        else [
            {
                "candidate_id": "candidate_answer_check",
                "finding_code": "ANSWER_REQUIRES_CONFIRMATION",
                "axis": "ANSWER",
                "draft_json_paths": ["/choices/1/text"],
                "evidence_ids": [EVIDENCE_ID],
                "initial_observation": "The answer relation requires one independent recheck.",
                "disposition": candidate_disposition,
                "conclusion": "The bounded recheck records the candidate disposition.",
            }
        ]
    )
    report["escalation_assessment"] = {
        "review_pass": review_pass,
        "inspection_order": "CONTENT_FIRST",
        "structural_complexity_score": score,
        "reason_codes": list(reasons),
        "decision": "COMPLETED"
        if review_pass == "ESCALATED"
        else "REQUIRED"
        if reasons
        else "NOT_REQUIRED",
        "source_review_artifact": (
            None
            if source_review is None
            else {
                "logical_artifact_id": source_review.logical_artifact_id,
                "revision_id": source_review.revision_id,
                "content_hash": source_review.content_hash,
                "result_schema": source_review.result_schema,
            }
        ),
    }
    return document


def _v12_plan_review_step() -> ResolvedStepExecutionV12:
    artifact = ControlArtifactPointer(
        artifact_id="artifact_" + "1" * 32,
        artifact_revision_id="rev_" + "1" * 32,
        sha256="sha256:" + "1" * 64,
        schema_ref="eom://schemas/workflow/instruction-bundle-manifest/1.0",
        media_type="application/json",
        logical_name="instruction-manifest.json",
    )
    instruction = BundleRevisionPointer(
        bundle_id="instrbundle_" + "1" * 32,
        bundle_revision_id="instrrev_" + "1" * 32,
        manifest_artifact=artifact,
        manifest_sha256="sha256:" + "2" * 64,
    )
    return ResolvedStepExecutionV12(
        step_key="review",
        role="review",
        model="gpt-5.6-terra",
        reasoning_effort="high",
        escalation_candidate=ModelCandidate(model="gpt-5.6-terra", reasoning_effort="xhigh"),
        instruction_bundle=instruction,
        reference_bundle=None,
        worker_pool_key="review",
        timeout_seconds=1800,
        general_knowledge_mode="ALLOWED_WITH_PROVENANCE",
        evidence_access="EVIDENCE_CONTEXT",
    )


def _upgrade_fixture_plan_to_v12(fixture: dict[str, Any]) -> None:
    record = fixture["session"].records[(ResolvedExecutionPlanRecord, str(fixture["plan_id"]))]
    document = deepcopy(record.canonical_document)
    authoring_step = {
        **document["steps"][0],
        "step_key": "authoring",
        "role": "authoring",
        "worker_pool_key": "authoring",
        "evidence_access": "EVIDENCE_CONTEXT",
        "escalation_candidate": None,
    }
    review_step = {
        **authoring_step,
        "step_key": "review",
        "role": "review",
        "worker_pool_key": "review",
        "escalation_candidate": {
            "model": "gpt-5.6-terra",
            "reasoning_effort": "xhigh",
        },
    }
    document.update(
        {
            "schema_version": "resolved-execution-plan/12.0",
            "workflow_definition_version": "1.13.0",
            "steps": [authoring_step, review_step],
            "resolver_version": "5.0.0",
        }
    )
    document["retrieval_requirement"]["required_item_elements"] = ["statement_set"]
    document["retrieval_requirement_sha256"] = content_sha256(document["retrieval_requirement"])
    document["plan_sha256"] = content_sha256(
        {key: value for key, value in document.items() if key != "plan_sha256"}
    )
    record.canonical_document = document
    record.plan_sha256 = document["plan_sha256"]


def _persist_authoring(
    fixture: dict[str, Any],
    result: ContentTeamAuthoringRoleResultV11 | ContentTeamAuthoringRoleResultV12,
) -> ArtifactPointer:
    session = fixture["session"]
    assert isinstance(session, FakeSession)
    successor = isinstance(result, ContentTeamAuthoringRoleResultV12)
    worker_input = RoleWorkerInput(
        protocol_version=("workflow-role/1.24.0" if successor else "workflow-role/1.23.0"),
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
        protocol_version=("workflow-role/1.24.0" if successor else "workflow-role/1.23.0"),
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
        result_schema=("authoring-result@12.0" if successor else "authoring-result@11.0"),
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


def test_v12_review_commit_binds_verification_plan_and_emits_v3_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _knowledge_fixture(
        tmp_path,
        monkeypatch,
        manifest_schema_version="5.0",
        workflow_definition_version="1.13.0",
    )
    _upgrade_fixture_plan_to_v12(fixture)
    authoring_document = _authoring_result(fixture).model_dump(mode="json")
    authoring_document["protocol_version"] = "workflow-role/1.24.0"
    authoring = ContentTeamAuthoringRoleResultV12.model_validate(authoring_document)
    authoring_pointer = _persist_authoring(fixture, authoring)
    review_document = _v12_review_document(fixture)
    review_document["output"]["evidence_usage_attestation"]["authoring_artifact"] = {
        "logical_artifact_id": authoring_pointer.logical_artifact_id,
        "revision_id": authoring_pointer.revision_id,
        "content_hash": authoring_pointer.content_hash,
        "result_schema": authoring_pointer.result_schema,
    }
    result = ContentTeamReviewRoleResultV12.model_validate(review_document)
    worker_input = RoleWorkerInput(
        protocol_version="workflow-role/1.24.0",
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
    result_pointer = EvidenceResultArtifactPointerV3(
        logical_artifact_id=result.artifact.logical_artifact_id,
        revision_id=result.artifact.revision_id,
        content_hash=content_hash,
        result_schema="review-result@12.0",
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

    assert isinstance(receipt, ReviewEvidenceUsageValidationReceiptV3)
    assert receipt.result_artifact.result_schema == "review-result@12.0"
    assert receipt.authoring_artifact.result_schema == "authoring-result@12.0"
    assert receipt.independent_review_report_sha256 == content_sha256(
        result.output.independent_review_report.model_dump(mode="json")
    )
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


def test_v12_review_contract_requires_plan_before_verdict_and_candidate_disposition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _knowledge_fixture(
        tmp_path,
        monkeypatch,
        manifest_schema_version="5.0",
        workflow_definition_version="1.13.0",
    )
    document = _v12_review_document(fixture)

    result = validate_role_result(document, "review", "review-result@12.0")

    assert isinstance(result, ContentTeamReviewRoleResultV12)
    report = result.output.independent_review_report
    assert len(report.verification_targets) == 10
    assert [target.target_id for target in report.verification_targets] == sorted(
        target.target_id for target in report.verification_targets
    )
    assert report.candidate_findings == ()

    missing_visual_first = deepcopy(document)
    missing_visual_first["output"]["independent_review_report"]["visual_assessment"] = {
        "status": "CONSISTENT",
        "rationale": "A visual is present and must be checked first.",
        "draft_json_paths": ["/visuals/0/member_path"],
        "evidence_ids": [EVIDENCE_ID],
    }
    missing_visual_first["output"]["independent_review_report"]["evidence_references"][0][
        "purposes"
    ].append("VISUAL_VALIDATION")
    with pytest.raises(ValidationError, match="visual verification target coverage differs"):
        ContentTeamReviewRoleResultV12.model_validate(missing_visual_first)

    unconfirmed_block = _v12_review_document(
        fixture,
        candidate_disposition="CONFIRMED",
        reasons=("CANDIDATE_FINDING_PRESENT",),
    )
    with pytest.raises(ValidationError, match="blocking findings must exactly equal confirmed"):
        ContentTeamReviewRoleResultV12.model_validate(unconfirmed_block)


def test_v12_review_target_must_use_its_exact_pinned_source_class(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _knowledge_fixture(
        tmp_path,
        monkeypatch,
        manifest_schema_version="5.0",
        workflow_definition_version="1.13.0",
    )
    document = _v12_review_document(fixture)
    document["output"]["independent_review_report"]["verification_targets"][0][
        "required_source_classes"
    ] = ["PAST_EXAM"]
    result = ContentTeamReviewRoleResultV12.model_validate(document)

    with pytest.raises(EvidenceUsageValidationError) as captured:
        _validate_independent_review_report(
            _materials(fixture), result, _content_v3().model_dump(mode="json")
        )

    assert captured.value.code == "EVIDENCE_REVIEW_TARGET_SOURCE_INVALID"


def test_v12_review_escalation_is_plan_pinned_one_pass_and_closes_uncertainty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _knowledge_fixture(
        tmp_path,
        monkeypatch,
        manifest_schema_version="5.0",
        workflow_definition_version="1.13.0",
    )
    authoring_document = _authoring_result(fixture).model_dump(mode="json")
    authoring_document["protocol_version"] = "workflow-role/1.24.0"
    authoring = ContentTeamAuthoringRoleResultV12.model_validate(authoring_document)
    score = structural_review_complexity(authoring)
    reason_set = {"CANDIDATE_FINDING_PRESENT", "EVIDENCE_UNCERTAINTY"}
    if score >= 4:
        reason_set.add("COMPLEX_ITEM")
    reasons = tuple(sorted(reason_set))
    primary = ContentTeamReviewRoleResultV12.model_validate(
        _v12_review_document(
            fixture,
            score=score,
            candidate_disposition="UNCERTAIN",
            reasons=reasons,
        )
    )
    authoring_pointer = ArtifactPointer(
        step_key="authoring",
        attempt=1,
        job_id=authoring.job_id,
        logical_artifact_id=authoring.artifact.logical_artifact_id,
        revision_id=authoring.artifact.revision_id,
        content_hash="sha256:" + "a" * 64,
        result_schema="authoring-result@12.0",
    )
    source_pointer = ArtifactPointer(
        step_key="review",
        attempt=1,
        job_id=primary.job_id,
        logical_artifact_id=primary.artifact.logical_artifact_id,
        revision_id=primary.artifact.revision_id,
        content_hash="sha256:" + "b" * 64,
        result_schema="review-result@12.0",
    )

    directive = build_review_escalation_directive(
        workflow_id=primary.workflow_id,
        reviewed_authoring=authoring_pointer,
        source_review=source_pointer,
        authoring_result=authoring,
        review_result=primary,
        plan_step=_v12_plan_review_step(),
    )

    assert directive is not None
    assert directive.next_attempt == 2
    assert directive.escalation_reasoning_effort == "xhigh"
    escalated = ContentTeamReviewRoleResultV12.model_validate(
        _v12_review_document(
            fixture,
            score=score,
            candidate_disposition="DEMOTED",
            review_pass="ESCALATED",
            reasons=reasons,
            source_review=source_pointer,
        )
    )
    validate_escalated_review_against_source(
        directive=directive,
        source=primary,
        escalated=escalated,
    )

    retained_uncertainty = _v12_review_document(
        fixture,
        score=score,
        candidate_disposition="UNCERTAIN",
        review_pass="ESCALATED",
        reasons=reasons,
        source_review=source_pointer,
    )
    with pytest.raises(ValidationError, match="cannot retain uncertain candidates"):
        ContentTeamReviewRoleResultV12.model_validate(retained_uncertainty)


def test_v12_role_schema_bundle_hash_is_immutable() -> None:
    assert role_schema_bundle_hash("workflow-role/1.24.0") == (
        "sha256:dcd6cd56fd04f49897feead527ee08305f86e651268fee7915527a0b4f623035"
    )
