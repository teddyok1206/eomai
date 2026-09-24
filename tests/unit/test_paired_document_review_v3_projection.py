from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from eom_api.errors import ApiError
from eom_api.services import query_adapter as query_module
from eom_api.services.query_adapter import QueryAdapter
from eom_catalog_contracts import KnowledgeArtifactMemberPointer
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
    DocumentReviewEvidenceValidationReceipt,
    PairedDocumentReviewRequestV2,
    PairedDocumentReviewRoleResultV3,
    PairedDocumentReviewWorkerRequestV2,
    RoleWorkerInput,
)
from eom_workflow.models import ArtifactSpec
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord

from tests.unit.test_document_review_v3_protocol import _result

NOW = datetime(2026, 9, 24, tzinfo=UTC)


def _evidence_pointer(seed: str, *, manifest: bool) -> KnowledgeArtifactMemberPointer:
    return KnowledgeArtifactMemberPointer(
        artifact_id="artifact_" + seed * 32,
        artifact_revision_id="rev_" + seed * 32,
        sha256="sha256:" + seed * 64,
        schema_ref=(
            "eom://schemas/knowledge/evidence-bundle-manifest/5.0"
            if manifest
            else "eom://schemas/knowledge/evidence-bundle-context/1.0"
        ),
        media_type="application/json" if manifest else "text/markdown",
        logical_name="manifest.json" if manifest else "context.md",
        member_path="evidence/manifest.json" if manifest else "evidence/context.md",
    )


def _projection_fixture(
    monkeypatch: pytest.MonkeyPatch,
    *,
    citation_hash: str | None = None,
) -> tuple[
    WorkflowInstanceRecord,
    PairedDocumentReviewRequestV2,
    WorkflowStepRunRecord,
    ArtifactPointer,
    JobRecord,
    ArtifactRecord,
    ArtifactRevisionRecord,
    JobEventRecord,
]:
    result = PairedDocumentReviewRoleResultV3.model_validate(_result())
    result_document = result.model_dump(mode="json")
    content_hash = content_sha256(result_document)
    content_bytes = len(canonical_json_bytes(result_document))
    usage = result.output.evidence_usage
    manifest_pointer = KnowledgeArtifactMemberPointer(
        **(
            _evidence_pointer("a", manifest=True).model_dump(mode="python")
            | {"sha256": usage.manifest_sha256}
        )
    )
    context_pointer = KnowledgeArtifactMemberPointer(
        **(
            _evidence_pointer("b", manifest=False).model_dump(mode="python")
            | {"sha256": usage.context_sha256}
        )
    )
    publication = SimpleNamespace(
        retrieval_request_id=usage.retrieval_request_id,
        graph_snapshot=SimpleNamespace(graph_snapshot_revision_id=usage.graph_snapshot_revision_id),
        evidence_bundle_id=usage.evidence_bundle_id,
        evidence_bundle_revision_id=usage.evidence_bundle_revision_id,
        manifest_artifact=manifest_pointer,
        manifest_sha256=usage.manifest_sha256,
        context_artifact=context_pointer,
    )
    evidence_plan = SimpleNamespace(
        plan_sha256="sha256:" + "c" * 64,
        publication=publication,
    )
    request = PairedDocumentReviewRequestV2.model_construct(
        request_sha256=result.output.review_request_sha256,
        evidence_plan=evidence_plan,
    )
    worker_request = PairedDocumentReviewWorkerRequestV2.model_construct(review_request=request)
    worker_input = RoleWorkerInput.model_construct(
        protocol_version="workflow-role/1.27.0",
        job_id=result.job_id,
        workflow_id=result.workflow_id,
        step_run_id=result.step_run_id,
        attempt=1,
        role="support",
        request=worker_request,
        upstream_artifacts=(),
        artifact=ArtifactSpec(
            logical_artifact_id=result.artifact.logical_artifact_id,
            revision_id=result.artifact.revision_id,
        ),
    )
    monkeypatch.setattr(
        query_module.RoleWorkerInput,
        "model_validate",
        lambda _value: worker_input,
    )
    monkeypatch.setattr(
        query_module,
        "validate_paired_document_review_v3_output_against_request",
        lambda *_args, **_kwargs: None,
    )
    pointer = ArtifactPointer(
        step_key="review_document",
        attempt=1,
        job_id=result.job_id,
        logical_artifact_id=result.artifact.logical_artifact_id,
        revision_id=result.artifact.revision_id,
        content_hash=content_hash,
        result_schema="pdf-document-review-result@3.0",
    )
    manifest = ArtifactManifest(
        job_id=result.job_id,
        logical_artifact_id=result.artifact.logical_artifact_id,
        revision_id=result.artifact.revision_id,
        content_hash=content_hash,
        content_bytes=content_bytes,
        worker_slot="06",
        created_at=NOW,
    )
    step = WorkflowStepRunRecord(
        step_run_id=result.step_run_id,
        workflow_id=result.workflow_id,
        step_key="review_document",
        attempt=1,
        step_type="agent",
        worker_role="support",
        result_schema="pdf-document-review-result@3.0",
        state="SUCCEEDED",
        platform_job_id=result.job_id,
        input_pointer_manifest={},
        output_pointer_manifest=pointer.model_dump(mode="json"),
        started_at=NOW,
        finished_at=NOW,
    )
    job_request = {"pinned": "worker-request"}
    job = JobRecord(
        job_id=result.job_id,
        protocol_version="workflow-role/1.27.0",
        idempotency_key="paired-v3-projection",
        request_hash=content_sha256(
            {
                "protocol_version": "workflow-role/1.27.0",
                "task_type": "workflow_support",
                "request": job_request,
            }
        ),
        task_type="workflow_support",
        request=job_request,
        status="SUCCEEDED",
        logical_artifact_id=result.artifact.logical_artifact_id,
        revision_id=result.artifact.revision_id,
        worker_slot_id="06",
        completed_at=NOW,
    )
    artifact = ArtifactRecord(
        logical_artifact_id=result.artifact.logical_artifact_id,
        job_id=result.job_id,
        artifact_type="workflow_support",
        approved=True,
    )
    manifest_document = manifest.model_dump(mode="json")
    revision = ArtifactRevisionRecord(
        revision_id=result.artifact.revision_id,
        logical_artifact_id=result.artifact.logical_artifact_id,
        job_id=result.job_id,
        content_hash=content_hash,
        manifest_hash=content_sha256(manifest_document),
        content_bytes=content_bytes,
        nas_path="/canonical/paired-v3",
        manifest=manifest_document,
        result=result_document,
        approved=True,
    )
    exact_citation_hash = content_sha256(
        {
            "schema_version": "document-review-evidence-citation-set/1.0",
            "citations": [
                value.model_dump(mode="json") for value in result.output.evidence_usage.citations
            ],
        }
    )
    receipt_document: dict[str, object] = {
        "schema_version": "document-review-evidence-validation-receipt/1.0",
        "plan_id": "execplan_" + "d" * 32,
        "plan_sha256": "sha256:" + "d" * 64,
        "workflow_id": result.workflow_id,
        "step_run_id": result.step_run_id,
        "job_id": result.job_id,
        "attempt": 1,
        "review_request_sha256": request.request_sha256,
        "evidence_plan_sha256": evidence_plan.plan_sha256,
        "retrieval_request_id": publication.retrieval_request_id,
        "graph_snapshot_revision_id": publication.graph_snapshot.graph_snapshot_revision_id,
        "evidence_bundle_id": publication.evidence_bundle_id,
        "evidence_bundle_revision_id": publication.evidence_bundle_revision_id,
        "evidence_manifest_artifact": manifest_pointer.model_dump(mode="json"),
        "evidence_manifest_sha256": publication.manifest_sha256,
        "evidence_context_artifact": context_pointer.model_dump(mode="json"),
        "result_artifact_id": result.artifact.logical_artifact_id,
        "result_artifact_revision_id": result.artifact.revision_id,
        "result_content_sha256": content_hash,
        "citation_set_sha256": citation_hash or exact_citation_hash,
        "receipt_sha256": "sha256:" + "0" * 64,
    }
    receipt_document["receipt_sha256"] = content_sha256(
        {key: value for key, value in receipt_document.items() if key != "receipt_sha256"}
    )
    receipt = DocumentReviewEvidenceValidationReceipt.model_validate(receipt_document)
    event = JobEventRecord(
        event_id=1,
        job_id=result.job_id,
        sequence=8,
        from_state="COMMITTING",
        to_state="SUCCEEDED",
        event="ARTIFACT_COMMITTED",
        data={
            "logical_artifact_id": result.artifact.logical_artifact_id,
            "revision_id": result.artifact.revision_id,
            "content_hash": content_hash,
            "document_review_evidence_validation_receipt": receipt.model_dump(mode="json"),
        },
        created_at=NOW,
    )
    workflow = WorkflowInstanceRecord(
        workflow_id=result.workflow_id,
        definition_id="wfdef_" + "e" * 32,
        definition_key="pdf-document-review",
        definition_version="1.2.0",
        definition_hash="sha256:" + "e" * 64,
        protocol_version="1.0.1",
        role_schema_version="workflow-role/1.27.0",
        state="COMPLETED",
        stage="KNOWLEDGE_ANALYSIS",
        current_step_key="review_document",
        request_payload={},
        initial_request={},
        runtime_context={
            "execution_plan": {
                "plan_id": receipt.plan_id,
                "plan_sha256": receipt.plan_sha256,
            }
        },
        idempotency_key="paired-v3-projection",
        request_hash="sha256:" + "f" * 64,
        lock_version=7,
        rework_cycle_count=0,
        created_actor_type="human",
        created_actor_id="operator_" + "f" * 32,
        created_at=NOW,
        updated_at=NOW,
    )
    return workflow, request, step, pointer, job, artifact, revision, event


def test_paired_v3_projection_revalidates_graph_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = _projection_fixture(monkeypatch)

    result = QueryAdapter._validated_paired_document_review_result(
        workflow=records[0],
        review_request=records[1],
        step=records[2],
        pointer=records[3],
        job=records[4],
        artifact=records[5],
        revision=records[6],
        event=records[7],
    )

    assert isinstance(result, PairedDocumentReviewRoleResultV3)


def test_paired_v3_projection_rejects_self_hashed_but_wrong_citation_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = _projection_fixture(monkeypatch, citation_hash="sha256:" + "0" * 64)

    with pytest.raises(ApiError) as captured:
        QueryAdapter._validated_paired_document_review_result(
            workflow=records[0],
            review_request=records[1],
            step=records[2],
            pointer=records[3],
            job=records[4],
            artifact=records[5],
            revision=records[6],
            event=records[7],
        )

    assert captured.value.error_code == "PAIRED_DOCUMENT_REVIEW_EVIDENCE_RECEIPT_INVALID"
