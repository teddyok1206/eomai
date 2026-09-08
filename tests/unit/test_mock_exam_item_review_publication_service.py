from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock, patch

import pytest
from eom_catalog_contracts.assessment_assembly import (
    load_integrated_science_mock_exam_rating_policy,
)
from eom_catalog_contracts.item_review import (
    InspectMockExamReviewEligibilityQuery,
    MockExamReviewFindingCounts,
    PublishMockExamItemReviewCommand,
)
from eom_catalog_service.mock_exam_item_review_publication_service import (
    MockExamItemReviewPublicationError,
    MockExamItemReviewPublicationService,
    _PublicationEvidence,
    _ReviewChainEvidence,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_protocol import ArtifactManifest
from eom_workflow import ArtifactPointer
from eom_workflow.models import (
    ArtifactSpec,
    ContentTeamReviewRoleResultV8,
    KnowledgeReviewOutput,
    RoleWorkerInput,
    WorkerRequest,
)
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord

NOW = datetime(2026, 9, 8, 5, tzinfo=UTC)


def _id(prefix: str, digit: str) -> str:
    return prefix + digit * 32


class _RoleArtifactStore:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result

    def load_json_revision(self, **_kwargs: object) -> dict[str, Any]:
        return self.result


class _LookupSession:
    def __init__(self, *rows: object) -> None:
        self.rows = {
            (type(row), cast(Any, row).__dict__[cast(Any, row).__mapper__.primary_key[0].key]): row
            for row in rows
        }

    def get(self, model: type[object], identity: str) -> object | None:
        return self.rows.get((model, identity))


def _review_evidence() -> tuple[
    MockExamItemReviewPublicationService,
    _LookupSession,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
]:
    workflow_id = _id("workflow_", "1")
    step_id = _id("steprun_", "2")
    job_id = _id("job_", "3")
    artifact_id = _id("artifact_", "4")
    revision_id = _id("rev_", "5")
    artifact_spec = ArtifactSpec(logical_artifact_id=artifact_id, revision_id=revision_id)
    result = ContentTeamReviewRoleResultV8(
        job_id=job_id,
        workflow_id=workflow_id,
        step_run_id=step_id,
        role="review",
        artifact=artifact_spec,
        completed_at=NOW,
        output=KnowledgeReviewOutput.model_validate(
            {
                "review": {
                    "decision": "ready_for_human",
                    "findings": [
                        {"code": "STYLE_WARNING", "severity": "warning", "message": "표현 확인"}
                    ],
                    "summary": "차단 사유 없이 사람 검토가 가능하다.",
                }
            }
        ),
    ).model_dump(mode="json")
    content_hash = content_sha256(result)
    pointer = ArtifactPointer(
        step_key="review",
        attempt=1,
        job_id=job_id,
        logical_artifact_id=artifact_id,
        revision_id=revision_id,
        content_hash=content_hash,
        result_schema="review-result@8.0",
    )
    worker_input = RoleWorkerInput(
        protocol_version="workflow-role/1.17.0",
        job_id=job_id,
        workflow_id=workflow_id,
        step_run_id=step_id,
        attempt=1,
        role="review",
        request=WorkerRequest(
            request_name="GENERATED_KNOWLEDGE_ITEM_REQUEST",
            image_mode="required",
        ),
        upstream_artifacts=(),
        artifact=artifact_spec,
    ).model_dump(mode="json")
    manifest = ArtifactManifest(
        job_id=job_id,
        logical_artifact_id=artifact_id,
        revision_id=revision_id,
        content_hash=content_hash,
        content_bytes=len(canonical_json_bytes(result)),
        worker_slot="03",
        created_at=NOW,
    ).model_dump(mode="json")
    workflow = WorkflowInstanceRecord(
        workflow_id=workflow_id,
        role_schema_version="workflow-role/1.17.0",
    )
    step = WorkflowStepRunRecord(
        step_run_id=step_id,
        workflow_id=workflow_id,
        step_key="review",
        attempt=1,
        step_type="agent",
        worker_role="review",
        result_schema="review-result@8.0",
        state="SUCCEEDED",
        platform_job_id=job_id,
        input_pointer_manifest={"upstream_artifacts": []},
        output_pointer_manifest=pointer.model_dump(mode="json"),
    )
    job = JobRecord(
        job_id=job_id,
        protocol_version="workflow-role/1.17.0",
        idempotency_key="unit-review-role-result",
        request_hash=content_sha256(worker_input),
        task_type="workflow_review",
        request=worker_input,
        status="SUCCEEDED",
        logical_artifact_id=artifact_id,
        revision_id=revision_id,
        worker_slot_id="03",
    )
    artifact = ArtifactRecord(
        logical_artifact_id=artifact_id,
        job_id=job_id,
        artifact_type="workflow_review",
        approved=True,
    )
    revision = ArtifactRevisionRecord(
        revision_id=revision_id,
        logical_artifact_id=artifact_id,
        job_id=job_id,
        content_hash=content_hash,
        manifest_hash=content_sha256(manifest),
        content_bytes=len(canonical_json_bytes(result)),
        nas_path="/not-materialized-by-this-unit-test",
        manifest=manifest,
        result=result,
        approved=True,
    )
    service = object.__new__(MockExamItemReviewPublicationService)
    service.artifacts = cast(Any, _RoleArtifactStore(result))
    return service, _LookupSession(job, artifact, revision), workflow, step


def test_review_role_pointer_resolution_validates_exact_identity_and_hash() -> None:
    service, session, workflow, step = _review_evidence()
    pointer, result = service._resolve_review_result(
        cast(Any, session),
        workflow=workflow,
        step=step,
    )

    assert pointer.content_hash == content_sha256(result.model_dump(mode="json"))
    assert result.output.review.decision == "ready_for_human"

    step.output_pointer_manifest = {
        **cast(dict[str, Any], step.output_pointer_manifest),
        "content_hash": "sha256:" + "f" * 64,
    }
    with pytest.raises(MockExamItemReviewPublicationError) as raised:
        service._resolve_review_result(cast(Any, session), workflow=workflow, step=step)
    assert raised.value.code == "ITEM_REVIEW_ARTIFACT_POINTER_INVALID"


def test_decision_hash_uses_the_exact_json_timestamp_and_explicit_rating() -> None:
    policy = load_integrated_science_mock_exam_rating_policy()
    command = PublishMockExamItemReviewCommand(
        item_revision_id=_id("itemrev_", "1"),
        expected_workflow_id=_id("workflow_", "2"),
        final_rating="C",
        reviewer_operator_id=_id("operator_", "3"),
        rating_policy_revision_id=policy.rating_policy_revision_id,
        rating_policy_sha256=content_sha256(policy.model_dump(mode="json")),
        idempotency_key="explicit-human-rating-C",
    )
    evidence = _PublicationEvidence(
        item_revision_id=command.item_revision_id,
        workflow_id=command.expected_workflow_id,
        review_step_run_id=_id("steprun_", "4"),
        approval_request_id=_id("approval_", "5"),
        review_artifact_id=_id("artifact_", "6"),
        review_artifact_revision_id=_id("rev_", "7"),
        review_sha256="sha256:" + "8" * 64,
        review_result_schema="review-result@8.0",
        finding_counts=MockExamReviewFindingCounts(info=0, warning=0, blocking=0),
        approval_resolved_at=NOW,
    )
    record_id, key_hash = MockExamItemReviewPublicationService._idempotency_identity(command)
    decision = MockExamItemReviewPublicationService._decision(
        command,
        policy=policy,
        evidence=evidence,
        item_review_record_id=record_id,
        idempotency_key_sha256=key_hash,
    )

    assert decision.final_rating == "C"
    assert decision.decided_at == NOW
    assert sha256_bytes(canonical_json_bytes(decision)).startswith("sha256:")
    assert MockExamItemReviewPublicationService._idempotency_identity(command) == (
        record_id,
        key_hash,
    )


@pytest.mark.parametrize(
    ("workflow_state", "approval_state", "reviewer_operator_id", "approved_at"),
    (
        ("AWAITING_HUMAN_APPROVAL", "PENDING", None, None),
        ("COMPLETED", "APPROVED", _id("operator_", "9"), NOW),
    ),
)
def test_eligibility_preserves_review_evidence_before_and_after_approval(
    workflow_state: str,
    approval_state: str,
    reviewer_operator_id: str | None,
    approved_at: datetime | None,
) -> None:
    source_service, source_session, _, source_step = _review_evidence()
    review_pointer, review_result = source_service._resolve_review_result(
        cast(Any, source_session),
        workflow=WorkflowInstanceRecord(
            workflow_id=_id("workflow_", "1"),
            role_schema_version="workflow-role/1.17.0",
        ),
        step=source_step,
    )
    workflow = WorkflowInstanceRecord(
        workflow_id=_id("workflow_", "1"),
        state=workflow_state,
        lock_version=8,
    )
    chain = _ReviewChainEvidence(
        workflow=workflow,
        authoring_result=cast(Any, object()),
        review_step=source_step,
        review_pointer=review_pointer,
        review_result=review_result,
        gate_upstream_pointers=(review_pointer,),
    )
    approval = SimpleNamespace(
        approval_request_id=_id("approval_", "8"),
        lock_version=2 if approval_state == "APPROVED" else 1,
        resolved_actor_id=reviewer_operator_id,
        resolved_at=approved_at,
    )
    service = cast(Any, object.__new__(MockExamItemReviewPublicationService))
    session = Mock()
    session.get.return_value = workflow
    service.sessions = lambda: nullcontext(session)
    service._require_supported_workflow = Mock(
        return_value=(
            workflow,
            (
                "authoring-result@8.0",
                "image-result@8.0",
                "review-result@8.0",
                "registration-result@8.0",
                "workflow-role/1.17.0",
            ),
        )
    )
    service._resolve_review_chain = Mock(return_value=chain)
    service._resolve_pending_approval = Mock(return_value=approval)
    service._resolve_human_approval = Mock(return_value=approval)

    result = service.inspect_eligibility(
        InspectMockExamReviewEligibilityQuery(workflow_id=workflow.workflow_id)
    )

    assert result.approval_state == approval_state
    assert result.reviewer_operator_id == reviewer_operator_id
    assert result.approved_at == approved_at
    assert result.review_artifact_revision_id == review_pointer.revision_id
    assert result.review_sha256 == review_pointer.content_hash
    assert result.finding_counts.blocking == 0
    service._require_supported_workflow.assert_called_once_with(
        session,
        workflow,
        expected_state="INSPECTABLE",
    )


def test_eligibility_batch_bulk_loads_workflows_and_definitions_in_order() -> None:
    queries = tuple(
        InspectMockExamReviewEligibilityQuery(workflow_id=_id("workflow_", digit))
        for digit in ("1", "2")
    )
    workflows = tuple(
        SimpleNamespace(workflow_id=query.workflow_id, definition_id=_id("workflowdef_", digit))
        for query, digit in zip(queries, ("3", "4"), strict=True)
    )
    definitions = tuple(SimpleNamespace(definition_id=row.definition_id) for row in workflows)
    session = Mock()
    session.scalars.side_effect = [workflows, definitions]
    service = cast(Any, object.__new__(MockExamItemReviewPublicationService))
    service.sessions = lambda: nullcontext(session)
    service._inspect_eligibility_in_session = Mock(
        side_effect=lambda _session, workflow: workflow.workflow_id
    )

    results = service.inspect_eligibility_batch(queries)

    assert results == tuple(query.workflow_id for query in queries)
    assert session.scalars.call_count == 2
    assert tuple(
        call.args[1].workflow_id for call in service._inspect_eligibility_in_session.call_args_list
    ) == tuple(query.workflow_id for query in queries)


def test_completed_workflow_evidence_accepts_deactivated_exact_definition() -> None:
    definition_document = {"schema_version": "1.0", "test": "historical-review"}
    definition_sha256 = content_sha256(definition_document)
    request_document = {"immutable": "request"}
    workflow = SimpleNamespace(
        workflow_id=_id("workflow_", "1"),
        definition_id=_id("workflowdef_", "2"),
        definition_key="generic-item-development",
        definition_version="1.8.0",
        definition_hash=definition_sha256,
        role_schema_version="workflow-role/1.17.0",
        state="COMPLETED",
        stage="COMPLETED",
        current_step_key="complete",
        completed_at=NOW,
        initial_request=request_document,
        request_payload=request_document,
        request_hash=content_sha256(request_document),
    )
    definition = SimpleNamespace(
        definition_key=workflow.definition_key,
        definition_version=workflow.definition_version,
        definition_hash=definition_sha256,
        canonical_definition=definition_document,
        active=False,
    )
    session = Mock()
    session.get.return_value = definition

    class ExactBrief:
        mock_exam_slot = object()

    source_request = SimpleNamespace(
        request_name="GENERATED_KNOWLEDGE_ITEM_REQUEST",
        content_pack=SimpleNamespace(pack_key="generated-knowledge-item"),
        registry_intent=SimpleNamespace(mode="CREATE_ITEM"),
        item_brief=ExactBrief(),
        execution_preset_key="knowledge-grounded-item",
    )
    service = MockExamItemReviewPublicationService.__new__(
        MockExamItemReviewPublicationService
    )
    with (
        patch(
            "eom_catalog_service.mock_exam_item_review_publication_service."
            "ContentTeamItemBrief",
            ExactBrief,
        ),
        patch(
            "eom_catalog_service.mock_exam_item_review_publication_service."
            "WorkflowRequest.model_validate",
            return_value=source_request,
        ),
    ):
        resolved, _contracts = service._require_supported_workflow(
            session,
            workflow,
            expected_state="COMPLETED",
        )

    assert resolved is workflow
