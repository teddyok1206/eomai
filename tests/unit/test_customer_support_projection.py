from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

import pytest
from eom_api.errors import ApiError
from eom_api.services.query_adapter import QueryAdapter
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.models import (
    ArtifactRecord,
    ArtifactRevisionRecord,
    JobEventRecord,
    JobRecord,
)
from eom_protocol import ArtifactManifest
from eom_workflow import (
    ArtifactPointer,
    CustomerSupportCase,
    CustomerSupportDiagnostics,
    CustomerSupportRoleResult,
    WorkflowRequest,
)
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord

NOW = datetime(2026, 9, 17, tzinfo=UTC)
JOB_ID = "job_" + "1" * 32
WORKFLOW_ID = "workflow_" + "2" * 32
STEP_RUN_ID = "steprun_" + "3" * 32
ARTIFACT_ID = "artifact_" + "4" * 32
REVISION_ID = "rev_" + "5" * 32


def _result_document() -> dict[str, object]:
    return CustomerSupportRoleResult.model_validate(
        {
            "schema_version": "1.0",
            "protocol_version": "workflow-role/1.22.0",
            "job_id": JOB_ID,
            "workflow_id": WORKFLOW_ID,
            "step_run_id": STEP_RUN_ID,
            "status": "ok",
            "artifact": {
                "logical_artifact_id": ARTIFACT_ID,
                "revision_id": REVISION_ID,
                "file_name": "result.json",
                "media_type": "application/json",
            },
            "completed_at": "2026-09-17T00:00:00Z",
            "role": "support",
            "output": {
                "classification": "USAGE_GUIDANCE",
                "answer_text": "현재 화면을 새로고침한 뒤 상태를 다시 확인해주세요.",
                "recommended_actions": [],
                "needs_operator": False,
                "operator_summary": None,
                "confidence": "MEDIUM",
                "mutation_performed": False,
            },
        }
    ).model_dump(mode="json")


def _records() -> tuple[
    WorkflowStepRunRecord,
    ArtifactPointer,
    JobRecord,
    ArtifactRecord,
    ArtifactRevisionRecord,
    JobEventRecord,
]:
    result = _result_document()
    content_hash = content_sha256(result)
    content_bytes = len(canonical_json_bytes(result))
    manifest = ArtifactManifest(
        job_id=JOB_ID,
        logical_artifact_id=ARTIFACT_ID,
        revision_id=REVISION_ID,
        content_hash=content_hash,
        content_bytes=content_bytes,
        worker_slot="06",
        created_at=NOW,
    ).model_dump(mode="json")
    pointer = ArtifactPointer(
        step_key="diagnose",
        attempt=1,
        job_id=JOB_ID,
        logical_artifact_id=ARTIFACT_ID,
        revision_id=REVISION_ID,
        content_hash=content_hash,
        result_schema="customer-support-result@1.0",
    )
    step = WorkflowStepRunRecord(
        step_run_id=STEP_RUN_ID,
        workflow_id=WORKFLOW_ID,
        step_key="diagnose",
        attempt=1,
        step_type="agent",
        worker_role="support",
        result_schema="customer-support-result@1.0",
        state="SUCCEEDED",
        platform_job_id=JOB_ID,
        input_pointer_manifest={},
        output_pointer_manifest=pointer.model_dump(mode="json"),
        started_at=NOW,
        finished_at=NOW,
    )
    job = JobRecord(
        job_id=JOB_ID,
        protocol_version="workflow-role/1.22.0",
        idempotency_key="customer-support-projection-test",
        request_hash="sha256:" + "6" * 64,
        task_type="workflow_support",
        request={},
        status="SUCCEEDED",
        logical_artifact_id=ARTIFACT_ID,
        revision_id=REVISION_ID,
        worker_slot_id="06",
        completed_at=NOW,
    )
    artifact = ArtifactRecord(
        logical_artifact_id=ARTIFACT_ID,
        job_id=JOB_ID,
        artifact_type="workflow_support",
        approved=True,
    )
    revision = ArtifactRevisionRecord(
        revision_id=REVISION_ID,
        logical_artifact_id=ARTIFACT_ID,
        job_id=JOB_ID,
        content_hash=content_hash,
        manifest_hash=content_sha256(manifest),
        content_bytes=content_bytes,
        nas_path=f"/canonical/{ARTIFACT_ID}/{REVISION_ID}",
        manifest=manifest,
        result=result,
        approved=True,
    )
    event = JobEventRecord(
        event_id=1,
        job_id=JOB_ID,
        sequence=8,
        from_state="COMMITTING",
        to_state="SUCCEEDED",
        event="ARTIFACT_COMMITTED",
        data={
            "logical_artifact_id": ARTIFACT_ID,
            "revision_id": REVISION_ID,
            "content_hash": content_hash,
        },
        created_at=NOW,
    )
    return step, pointer, job, artifact, revision, event


def test_customer_support_projection_resolves_exact_approved_artifact() -> None:
    step, pointer, job, artifact, revision, event = _records()

    result = QueryAdapter._validated_customer_support_result(
        workflow_id=WORKFLOW_ID,
        step=step,
        pointer=pointer,
        job=job,
        artifact=artifact,
        revision=revision,
        event=event,
    )

    assert result.output.answer_text.startswith("현재 화면")


def test_customer_support_projection_withholds_answer_until_workflow_completes() -> None:
    request = WorkflowRequest(
        request_name="CUSTOMER_SUPPORT_REQUEST",
        image_mode="skip",
        execution_preset_key="customer-support",
        customer_support_case=CustomerSupportCase(
            category="HOW_TO",
            subject="상태 표시 확인",
            question="답변이 완료되기 전에는 어떤 상태로 표시되는지 알려주세요.",
            diagnostics=CustomerSupportDiagnostics(observed_at=NOW),
        ),
    ).model_dump(mode="json")
    workflow = WorkflowInstanceRecord(
        workflow_id=WORKFLOW_ID,
        definition_id="wfdef_" + "6" * 32,
        definition_key="customer-support",
        definition_version="1.0.0",
        definition_hash="sha256:" + "7" * 64,
        protocol_version="1.0.1",
        role_schema_version="workflow-role/1.22.0",
        state="RUNNING",
        stage="KNOWLEDGE_ANALYSIS",
        current_step_key="diagnose",
        request_payload=request,
        initial_request=request,
        runtime_context={},
        idempotency_key="customer-support-running-projection",
        request_hash="sha256:" + "8" * 64,
        lock_version=3,
        rework_cycle_count=0,
        created_actor_type="human",
        created_actor_id="operator_" + "9" * 32,
        created_at=NOW,
        updated_at=NOW,
    )

    projected = QueryAdapter._customer_support_case(
        workflow,
        CustomerSupportRoleResult.model_validate(_result_document()),
    )

    assert projected.state == "DIAGNOSING"
    assert projected.answer_text is None
    assert projected.classification is None


@pytest.mark.parametrize(
    "drift",
    (
        "job_lifecycle",
        "artifact_lifecycle",
        "task_artifact_type",
        "content_hash",
        "manifest_media",
        "terminal_event",
    ),
)
def test_customer_support_projection_rejects_stale_or_unapproved_pointer(
    drift: Literal[
        "job_lifecycle",
        "artifact_lifecycle",
        "task_artifact_type",
        "content_hash",
        "manifest_media",
        "terminal_event",
    ],
) -> None:
    step, pointer, job, artifact, revision, event = _records()
    if drift == "job_lifecycle":
        job.status = "FAILED"
    elif drift == "artifact_lifecycle":
        artifact.approved = False
    elif drift == "task_artifact_type":
        job.task_type = "workflow_diagnose"
        artifact.artifact_type = "workflow_diagnose"
    elif drift == "content_hash":
        revision.content_hash = "sha256:" + "9" * 64
    elif drift == "manifest_media":
        revision.manifest = {**revision.manifest, "media_type": "text/plain"}
    else:
        event.data = {**event.data, "revision_id": "rev_" + "a" * 32}

    with pytest.raises(ApiError) as captured:
        QueryAdapter._validated_customer_support_result(
            workflow_id=WORKFLOW_ID,
            step=step,
            pointer=pointer,
            job=job,
            artifact=artifact,
            revision=revision,
            event=event,
        )

    assert captured.value.error_code == "CUSTOMER_SUPPORT_RESULT_INVALID"
