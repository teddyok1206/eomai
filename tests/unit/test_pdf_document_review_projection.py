from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

import pytest
from eom_api.errors import ApiError
from eom_api.pdf_document_review_models import PdfDocumentReviewUploadIntentRecord
from eom_api.services.query_adapter import QueryAdapter
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.models import (
    ArtifactRecord,
    ArtifactRevisionRecord,
    JobEventRecord,
    JobRecord,
)
from eom_protocol import ArtifactManifest
from eom_workflow import ArtifactPointer, PdfDocumentReviewRoleResult, WorkflowRequest
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord

from tests.unit.test_pdf_document_review_protocol import (
    ARTIFACT_ID,
    JOB_ID,
    REVISION_ID,
    STEP_RUN_ID,
    WORKFLOW_ID,
    _input,
    _request,
    _result,
)

NOW = datetime(2026, 9, 22, tzinfo=UTC)


def _records() -> tuple[
    WorkflowStepRunRecord,
    ArtifactPointer,
    JobRecord,
    ArtifactRecord,
    ArtifactRevisionRecord,
    JobEventRecord,
]:
    result = PdfDocumentReviewRoleResult.model_validate(_result()).model_dump(mode="json")
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
        step_key="review_document",
        attempt=1,
        job_id=JOB_ID,
        logical_artifact_id=ARTIFACT_ID,
        revision_id=REVISION_ID,
        content_hash=content_hash,
        result_schema="pdf-document-review-result@1.0",
    )
    step = WorkflowStepRunRecord(
        step_run_id=STEP_RUN_ID,
        workflow_id=WORKFLOW_ID,
        step_key="review_document",
        attempt=1,
        step_type="agent",
        worker_role="support",
        result_schema="pdf-document-review-result@1.0",
        state="SUCCEEDED",
        platform_job_id=JOB_ID,
        input_pointer_manifest={},
        output_pointer_manifest=pointer.model_dump(mode="json"),
        started_at=NOW,
        finished_at=NOW,
    )
    worker_input = _input()
    job = JobRecord(
        job_id=JOB_ID,
        protocol_version="workflow-role/1.25.0",
        idempotency_key="pdf-document-review-projection-test",
        request_hash=content_sha256(
            {
                "protocol_version": "workflow-role/1.25.0",
                "task_type": "workflow_support",
                "request": worker_input,
            }
        ),
        task_type="workflow_support",
        request=worker_input,
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


def _workflow(state: Literal["RUNNING", "COMPLETED"] = "COMPLETED") -> WorkflowInstanceRecord:
    request = WorkflowRequest(
        request_name="PDF_DOCUMENT_REVIEW_REQUEST",
        image_mode="skip",
        execution_preset_key="pdf-document-review",
        pdf_document_review_request=_request(),
    ).model_dump(mode="json")
    return WorkflowInstanceRecord(
        workflow_id=WORKFLOW_ID,
        definition_id="wfdef_" + "a" * 32,
        definition_key="pdf-document-review",
        definition_version="1.0.0",
        definition_hash="sha256:" + "b" * 64,
        protocol_version="1.0.1",
        role_schema_version="workflow-role/1.25.0",
        state=state,
        stage="KNOWLEDGE_ANALYSIS",
        current_step_key="review_document",
        request_payload=request,
        initial_request=request,
        runtime_context={},
        idempotency_key="pdf-document-review-projection-workflow",
        request_hash="sha256:" + "c" * 64,
        lock_version=7,
        rework_cycle_count=0,
        created_actor_type="human",
        created_actor_id="operator_" + "d" * 32,
        created_at=NOW,
        updated_at=NOW,
    )


def test_pdf_review_projection_resolves_exact_worker_request_and_artifact() -> None:
    step, pointer, job, artifact, revision, event = _records()
    result = QueryAdapter._validated_pdf_document_review_result(
        workflow_id=WORKFLOW_ID,
        review_request=_request(),
        step=step,
        pointer=pointer,
        job=job,
        artifact=artifact,
        revision=revision,
        event=event,
    )
    view = QueryAdapter._pdf_document_review(_workflow(), result)

    assert view.state == "COMPLETED"
    assert view.result is not None
    assert view.result_artifact is not None
    assert view.pages[0].image_url.endswith("/pages/1/image")


def test_office_review_projection_uses_original_upload_identity() -> None:
    source = PdfDocumentReviewUploadIntentRecord(
        original_filename="검토 문서.hwpx",
        source_format="HWPX",
    )

    view = QueryAdapter._pdf_document_review(_workflow("RUNNING"), None, source)

    assert view.original_filename == "검토 문서.hwpx"
    assert view.source_format == "HWPX"
    assert view.source_pdf_sha256 == _request().document.source_pdf.sha256


def test_pdf_review_projection_recovers_legacy_omitted_nullable_text_layer() -> None:
    workflow = _workflow("RUNNING")
    del workflow.initial_request["pdf_document_review_request"]["document"]["pages"][0][
        "text_layer"
    ]

    review_request = QueryAdapter._pdf_document_review_request(workflow)

    assert review_request.document.pages[0].text_layer is None


def test_pdf_review_projection_withholds_committed_result_until_terminal() -> None:
    result = PdfDocumentReviewRoleResult.model_validate(_result())
    view = QueryAdapter._pdf_document_review(_workflow("RUNNING"), result)

    assert view.state == "REVIEWING"
    assert view.result is None
    assert view.result_artifact is None


@pytest.mark.parametrize(
    "drift",
    (
        "job_request",
        "request_hash",
        "job_lifecycle",
        "artifact_lifecycle",
        "content_hash",
        "terminal_event",
    ),
)
def test_pdf_review_projection_rejects_stale_or_cross_workflow_data(
    drift: Literal[
        "job_request",
        "request_hash",
        "job_lifecycle",
        "artifact_lifecycle",
        "content_hash",
        "terminal_event",
    ],
) -> None:
    step, pointer, job, artifact, revision, event = _records()
    if drift == "job_request":
        job.request = {**job.request, "workflow_id": "workflow_" + "e" * 32}
    elif drift == "request_hash":
        job.request_hash = "sha256:" + "f" * 64
    elif drift == "job_lifecycle":
        job.status = "FAILED"
    elif drift == "artifact_lifecycle":
        artifact.approved = False
    elif drift == "content_hash":
        revision.content_hash = "sha256:" + "0" * 64
    else:
        event.data = {**event.data, "revision_id": "rev_" + "1" * 32}

    with pytest.raises(ApiError) as captured:
        QueryAdapter._validated_pdf_document_review_result(
            workflow_id=WORKFLOW_ID,
            review_request=_request(),
            step=step,
            pointer=pointer,
            job=job,
            artifact=artifact,
            revision=revision,
            event=event,
        )

    assert captured.value.error_code == "PDF_DOCUMENT_REVIEW_RESULT_INVALID"
