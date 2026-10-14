"""Source plan/replay/Evidence compatibility; publication/source/model authority is synthetic."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts import EvidenceBundlePublicationResultV5
from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.control_models import (
    ExecutionBundleRevisionRecord,
    ResolvedExecutionPlanRecord,
)
from eom_orchestrator.control_service import ControlPlaneError, ResolvedPlanDependencyEvidence
from eom_orchestrator.evidence_usage_validation import validate_evidence_usage_for_commit
from eom_orchestrator.execution_materializer import (
    authorized_evidence_artifact_revisions,
    authorized_execution_artifact_revisions,
)
from eom_orchestrator.execution_resolver import (
    ExecutionStepRequirement,
    resolve_knowledge_backed_execution_plan,
)
from eom_orchestrator.orchestrator import (
    _plan_step_evidence_access,
    _resolved_evidence_plan_for_response,
)
from eom_workflow import (
    AuthoringEvidenceUsageValidationReceiptV3,
    EvidenceResultArtifactPointerV3,
    ExecutionPresetRevisionV2,
    ReviewEvidenceUsageValidationReceiptV3,
)
from eom_workflow.models import (
    ContentTeamAuthoringRoleResultV12,
    ContentTeamReviewRoleResultV12,
    RoleWorkerInput,
    WorkerRequest,
)
from eom_workflow.similarity_control import (
    PreparedSimilarityPlan,
    ResolvedExecutionPlanV23,
    parse_post_registration_grounded_plan,
)

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.similarity_plan_fixtures import similarity_case
from tests.unit.test_graph_review_v11_protocol import (
    _authoring_result,
    _persist_authoring,
    _v12_review_document,
)
from tests.unit.test_knowledge_backed_execution import _evidence, _Session, _verification_preset


def creation_arguments(case):
    base = case["base"]
    body = _verification_preset().model_dump(mode="json")
    body.update(
        preset_id=base.preset_id,
        preset_revision_id=base.preset_revision_id,
        capacity_policy_revision_id=base.capacity_policy_revision_id,
        role_policies=[
            {
                "role": step.role,
                "model_candidates": [
                    {"model": step.model, "reasoning_effort": step.reasoning_effort},
                    *(
                        []
                        if step.escalation_candidate is None
                        else [step.escalation_candidate.model_dump(mode="json")]
                    ),
                ],
                "instruction_bundle": step.instruction_bundle.model_dump(mode="json"),
                "reference_bundle": None
                if step.reference_bundle is None
                else step.reference_bundle.model_dump(mode="json"),
                "worker_pool_key": step.worker_pool_key,
                "timeout_seconds": step.timeout_seconds,
                "sandbox": step.sandbox,
                "network": step.network,
                "evidence_access": step.evidence_access,
            }
            for step in base.steps
        ],
    )
    body["retrieval_policy"].update(
        access_policy_revision_id=base.access_policy_revision_id,
        access_policy_sha256=base.access_policy_sha256,
        allowed_corpus_keys=[base.retrieval_requirement.corpus_key],
        allowed_source_classes=list(base.retrieval_requirement.source_classes),
    )
    preset = ExecutionPresetRevisionV2.model_validate(seal(body, "content_sha256"))
    evidence = _evidence(manifest_schema_version="5.0").model_dump(mode="json")
    evidence.update(
        evidence_bundle_id=base.evidence_bundle_id,
        evidence_bundle_revision_id=base.evidence_bundle_revision_id,
        retrieval_request_id=base.retrieval_request_id,
        retrieval_request_sha256=base.retrieval_request_sha256,
        graph_snapshot=base.graph_snapshot.model_dump(mode="json"),
        access_policy_revision_id=base.access_policy_revision_id,
        access_policy_sha256=base.access_policy_sha256,
        requester_permissions_sha256=base.requester_permissions_sha256,
        manifest_artifact=base.evidence_manifest_artifact.model_dump(mode="json"),
        manifest_sha256=base.evidence_manifest_sha256,
        context_artifact=base.evidence_context_artifact.model_dump(mode="json"),
    )
    return {
        "preset_revision_id": preset.preset_revision_id,
        "requirement": base.retrieval_requirement,
        "evidence": EvidenceBundlePublicationResultV5.model_validate(
            seal(evidence, "result_sha256")
        ),
        "dependencies": ResolvedPlanDependencyEvidence(
            workflow_id=base.workflow_id,
            workflow_definition_key=base.workflow_definition_key,
            workflow_definition_version=base.workflow_definition_version,
            workflow_definition_sha256=base.workflow_definition_sha256,
            workflow_role_schema_version="workflow-role/1.24.0",
            content_pack_release_id=base.content_pack_release_id,
            content_pack_sha256=base.content_pack_sha256,
            graph_snapshot_revision_id=base.graph_snapshot.graph_snapshot_revision_id,
            evidence_bundle_revision_id=base.evidence_bundle_revision_id,
        ),
        "steps": tuple(ExecutionStepRequirement(step.step_key, step.role) for step in base.steps),
        "resolved_at": base.resolved_at,
    }, preset


def test_new_context_is_bound_before_first_persistence_not_as_plan19_then_upgrade(
    tmp_path, monkeypatch
):
    case = similarity_case(tmp_path, monkeypatch)
    arguments, preset = creation_arguments(case)
    captured = []

    def record(session, *, document, dependencies):
        captured.append(document)
        assert document["schema_version"] == "resolved-execution-plan/23.0"
        return SimpleNamespace(canonical_document=document)

    monkeypatch.setattr(
        "eom_orchestrator.execution_resolver.record_knowledge_backed_execution_plan", record
    )
    result = resolve_knowledge_backed_execution_plan(
        _Session(preset),
        **arguments,
        similarity=PreparedSimilarityPlan(case["delivery"], case["context"]),
    )
    assert isinstance(result, ResolvedExecutionPlanV23)
    assert result.similarity_delivery == case["delivery"]
    assert result.retrieval_requirement == case["base"].retrieval_requirement
    assert result.evidence_manifest_artifact == case["base"].evidence_manifest_artifact
    assert len(captured) == 1
    assert case["base"].schema_version == "resolved-execution-plan/19.0"


@pytest.mark.parametrize("schema", ("base", "plan"))
def test_exact_stored_plan_replay_does_not_read_current_preset_or_publish_again(
    tmp_path, monkeypatch, schema
):
    case = similarity_case(tmp_path, monkeypatch)
    arguments, _preset = creation_arguments(case)
    original = case[schema]

    class ReplaySession:
        def scalar(self, statement):
            return SimpleNamespace(
                canonical_document=original.model_dump(mode="json"),
                plan_id=original.plan_id,
                workflow_id=original.workflow_id,
                plan_sha256=original.plan_sha256,
            )

        def get(self, *args):
            raise AssertionError("replay must not look up mutable current controls")

    assert resolve_knowledge_backed_execution_plan(ReplaySession(), **arguments) == original
    preparation = PreparedSimilarityPlan(case["delivery"], case["context"])
    if schema == "base":
        with pytest.raises(ControlPlaneError) as captured:
            resolve_knowledge_backed_execution_plan(
                ReplaySession(), **arguments, similarity=preparation
            )
        assert captured.value.code == "CONTROL_PLAN_CONFLICT"
    else:
        assert (
            resolve_knowledge_backed_execution_plan(
                ReplaySession(), **arguments, similarity=preparation
            )
            == original
        )
        foreign_pin = case["delivery"].model_copy(
            update={
                "context_member": case["delivery"].context_member.model_copy(
                    update={"artifact_id": "artifact_" + "0" * 32}
                )
            }
        )
        with pytest.raises(ControlPlaneError) as captured:
            resolve_knowledge_backed_execution_plan(
                ReplaySession(), **arguments, similarity=replace(preparation, delivery=foreign_pin)
            )
        assert captured.value.code == "CONTROL_PLAN_CONFLICT"


def bound_evidence_case(tmp_path, monkeypatch):
    case = similarity_case(tmp_path, monkeypatch)
    record = case["session"].records[(ResolvedExecutionPlanRecord, case["plan_id"])]
    record.canonical_document = case["plan"].model_dump(mode="json")
    record.plan_sha256 = case["plan"].plan_sha256
    record.workflow_id = case["plan"].workflow_id
    return case


def test_evidence_only_read_has_no_auxiliary_grant_and_execution_still_requires_current_reader(
    tmp_path, monkeypatch
):
    case = bound_evidence_case(tmp_path, monkeypatch)
    allowed = authorized_evidence_artifact_revisions(
        case["session"], plan_id=case["plan_id"], step_key="authoring"
    )
    assert case["plan"].evidence_manifest_artifact.artifact_revision_id in allowed
    assert case["plan"].evidence_context_artifact.artifact_revision_id in allowed
    assert case["delivery"].context_member.artifact_revision_id not in allowed
    with pytest.raises(ControlPlaneError) as captured:
        authorized_execution_artifact_revisions(
            case["session"], plan_id=case["plan_id"], step_key="authoring"
        )
    assert captured.value.code == "CONTROL_SIMILARITY_AUTHORITY_UNAVAILABLE"


def test_response_schema_and_full_review_receipt_use_exact_plan23_without_a_new_search(
    tmp_path, monkeypatch
):
    case = bound_evidence_case(tmp_path, monkeypatch)
    plan = case["plan"]
    raw = plan.model_dump(mode="json")
    assert parse_post_registration_grounded_plan(raw) == plan
    assert (
        _resolved_evidence_plan_for_response(
            raw, result_schema="review-result@12.0", evidence_access="EVIDENCE_CONTEXT"
        )
        == plan
    )
    assert _plan_step_evidence_access(raw, raw["steps"][0]) == "EVIDENCE_CONTEXT"
    authoring_raw = _authoring_result(case).model_dump(mode="json")
    authoring_raw["protocol_version"] = "workflow-role/1.24.0"
    authoring = ContentTeamAuthoringRoleResultV12.model_validate(authoring_raw)
    authoring_input = RoleWorkerInput(
        protocol_version="workflow-role/1.24.0",
        job_id=authoring.job_id,
        workflow_id=authoring.workflow_id,
        step_run_id=authoring.step_run_id,
        attempt=1,
        role="authoring",
        request=WorkerRequest(request_name="GENERATED_KNOWLEDGE_ITEM_REQUEST", image_mode="skip"),
        upstream_artifacts=(),
        artifact=authoring.artifact,
    )
    authoring_receipt = validate_evidence_usage_for_commit(
        case["session"],
        plan_id=case["plan_id"],
        step_key="authoring",
        worker_input=authoring_input,
        result=authoring,
        result_artifact=EvidenceResultArtifactPointerV3(
            logical_artifact_id=authoring.artifact.logical_artifact_id,
            revision_id=authoring.artifact.revision_id,
            content_hash=sha256_bytes(canonical_json_bytes(authoring.model_dump(mode="json"))),
            result_schema="authoring-result@12.0",
        ),
        canonical_artifact_root=case["artifact_root"],
    )
    assert isinstance(authoring_receipt, AuthoringEvidenceUsageValidationReceiptV3)
    assert authoring_receipt.plan_sha256 == plan.plan_sha256
    pointer = _persist_authoring(case, authoring)
    review_raw = _v12_review_document(case)
    for target in review_raw["output"]["independent_review_report"]["verification_targets"]:
        target["required_source_classes"] = [
            "PAST_EXAM" if value == "APPROVED_ITEM" else value
            for value in target["required_source_classes"]
        ]
    review_raw["output"]["evidence_usage_attestation"]["authoring_artifact"] = {
        "logical_artifact_id": pointer.logical_artifact_id,
        "revision_id": pointer.revision_id,
        "content_hash": pointer.content_hash,
        "result_schema": pointer.result_schema,
    }
    review = ContentTeamReviewRoleResultV12.model_validate(review_raw)
    worker_input = RoleWorkerInput(
        protocol_version="workflow-role/1.24.0",
        job_id=review.job_id,
        workflow_id=review.workflow_id,
        step_run_id=review.step_run_id,
        attempt=1,
        role="review",
        request=WorkerRequest(request_name="GENERATED_KNOWLEDGE_ITEM_REQUEST", image_mode="skip"),
        upstream_artifacts=(pointer,),
        artifact=review.artifact,
    )
    receipt = validate_evidence_usage_for_commit(
        case["session"],
        plan_id=case["plan_id"],
        step_key="review",
        worker_input=worker_input,
        result=review,
        result_artifact=EvidenceResultArtifactPointerV3(
            logical_artifact_id=review.artifact.logical_artifact_id,
            revision_id=review.artifact.revision_id,
            content_hash=sha256_bytes(canonical_json_bytes(review.model_dump(mode="json"))),
            result_schema="review-result@12.0",
        ),
        canonical_artifact_root=case["artifact_root"],
    )
    assert isinstance(receipt, ReviewEvidenceUsageValidationReceiptV3)
    assert receipt.plan_sha256 == plan.plan_sha256
    assert receipt.evidence_manifest_sha256 == plan.evidence_manifest_sha256

    @contextmanager
    def sessions():
        yield case["session"]

    original = case["original_source"]
    member = original["artifact_member"]
    registry = Mock()
    registry.resolve_past_exam_variation_content.return_value = SimpleNamespace(
        item_id=original["item_id"],
        item_revision_id=original["item_revision_id"],
        artifact_id=member["artifact_id"],
        artifact_revision_id=member["artifact_revision_id"],
        schema_ref=member["schema_ref"],
        sha256=member["sha256"],
    )
    source = WorkflowCatalogService._past_exam_variation_source(
        SimpleNamespace(sessions=sessions, registry=registry),
        workflow=SimpleNamespace(workflow_id=plan.workflow_id),
        request=SimpleNamespace(educational_retrieval=plan.retrieval_requirement),
        evidence_receipts=SimpleNamespace(authoring=authoring_receipt, review=receipt),
    )
    assert source.plan_sha256 == plan.plan_sha256
    assert source.content_sha256 == member["sha256"]
    registry.resolve_past_exam_variation_content.assert_called_once_with(
        original["item_revision_id"]
    )


@pytest.mark.parametrize("field", ("plan_id", "workflow_id", "plan_sha256"))
def test_new_plan_replay_rejects_stale_record_header_without_preset_lookup(
    tmp_path, monkeypatch, field
):
    case = similarity_case(tmp_path, monkeypatch)
    arguments, _preset = creation_arguments(case)
    plan = case["plan"]
    values = {
        "canonical_document": plan.model_dump(mode="json"),
        "plan_id": plan.plan_id,
        "workflow_id": plan.workflow_id,
        "plan_sha256": plan.plan_sha256,
    }
    values[field] = {
        "plan_id": "execplan_" + "0" * 32,
        "workflow_id": "workflow_" + "0" * 32,
        "plan_sha256": "sha256:" + "0" * 64,
    }[field]

    class ReplaySession:
        def scalar(self, statement):
            return SimpleNamespace(**values)

        def get(self, *args):
            raise AssertionError("stale replay must not consult mutable controls")

    with pytest.raises(ControlPlaneError) as captured:
        resolve_knowledge_backed_execution_plan(ReplaySession(), **arguments)
    assert captured.value.code == "CONTROL_PLAN_INVALID"


@pytest.mark.parametrize("fault", ("hash", "extra", "bool"))
def test_response_plan_validation_does_not_accept_copied_or_coerced_plan23(
    tmp_path, monkeypatch, fault
):
    case = similarity_case(tmp_path, monkeypatch)
    raw = case["plan"].model_dump(mode="json")
    if fault == "hash":
        raw["plan_sha256"] = "sha256:" + "0" * 64
    elif fault == "extra":
        raw["operator_role"] = "ADMIN"
    else:
        raw["steps"][0]["timeout_seconds"] = True
    with pytest.raises(ControlPlaneError) as captured:
        _resolved_evidence_plan_for_response(
            raw, result_schema="authoring-result@12.0", evidence_access="EVIDENCE_CONTEXT"
        )
    assert captured.value.code == "CONTROL_EVIDENCE_PLAN_INVALID"


@pytest.mark.parametrize("fault", ("bundle", "step"))
def test_evidence_only_read_keeps_existing_released_bundle_and_step_checks(
    tmp_path, monkeypatch, fault
):
    case = bound_evidence_case(tmp_path, monkeypatch)
    if fault == "bundle":
        pointer = case["plan"].steps[0].instruction_bundle
        case["session"].records[
            (ExecutionBundleRevisionRecord, pointer.bundle_revision_id)
        ].state = "DRAFT"
    with pytest.raises(ControlPlaneError) as captured:
        authorized_evidence_artifact_revisions(
            case["session"],
            plan_id=case["plan_id"],
            step_key="image" if fault == "step" else "authoring",
        )
    assert captured.value.code == (
        "CONTROL_PLAN_STEP_MISSING" if fault == "step" else "CONTROL_BUNDLE_POINTER_INVALID"
    )
