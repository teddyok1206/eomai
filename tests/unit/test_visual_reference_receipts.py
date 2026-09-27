from __future__ import annotations

from datetime import UTC, datetime

import pytest
from eom_catalog_service.visual_reference_receipts import (
    OrchestratorVisualReferenceReceiptResolver,
    VisualReferenceReceiptResolutionError,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_image_contracts import (
    LocalImageVisualReferencePointer,
    LocalImageVisualReferencePublicationReceipt,
    VisualReferenceBundleManifestPointer,
    VisualReferenceImageResultArtifactPointer,
    VisualReferencePngArtifactPointer,
    VisualReferencePublicationEntry,
)
from eom_orchestrator.models import (
    ArtifactRecord,
    ArtifactRevisionRecord,
    JobEventRecord,
    JobRecord,
)
from eom_protocol import ArtifactManifest
from eom_workflow import ArtifactPointer, RoleWorkerInput, WorkerRequest
from eom_workflow.models import ArtifactSpec

from tests.unit.test_workflow_catalog_generated import (
    IMAGE_V12,
    WORKFLOW_ID,
    _content_team_image_result_v12,
)

NOW = datetime(2026, 9, 27, 18, 0, tzinfo=UTC)


def _sha(character: str) -> str:
    return "sha256:" + character * 64


def _receipt(image_result: ArtifactPointer) -> LocalImageVisualReferencePublicationReceipt:
    reference = LocalImageVisualReferencePointer(
        bundle_id="imgrefbundle_" + "1" * 32,
        bundle_revision_id="imgrefbundlerev_" + "2" * 32,
        bundle_manifest=VisualReferenceBundleManifestPointer(
            artifact_id="artifact_" + "3" * 32,
            artifact_revision_id="rev_" + "4" * 32,
            sha256=_sha("5"),
            size_bytes=123,
        ),
        primary_reference_id="imgref_" + "6" * 32,
        reference_member=VisualReferencePngArtifactPointer(
            artifact_id="artifact_" + "3" * 32,
            artifact_revision_id="rev_" + "4" * 32,
            sha256=_sha("7"),
            size_bytes=456,
        ),
    )
    entry = VisualReferencePublicationEntry(
        visual_ordinal=0,
        drawing_sha256=_sha("8"),
        subject_sha256=_sha("9"),
        discovery_command_sha256=_sha("a"),
        discovery_result_sha256=_sha("b"),
        intent_sha256=_sha("c"),
        acquisition_command_sha256=_sha("d"),
        acquisition_result_sha256=_sha("e"),
        visual_reference=reference,
    )
    body = {
        "schema_version": "local-image-visual-reference-publication-receipt/1.0",
        "image_result_artifact": VisualReferenceImageResultArtifactPointer(
            logical_artifact_id=image_result.logical_artifact_id,
            revision_id=image_result.revision_id,
            content_hash=image_result.content_hash,
        ).model_dump(mode="json"),
        "entries": [entry.model_dump(mode="json")],
        "published_at": "2026-09-27T18:00:00Z",
    }
    return LocalImageVisualReferencePublicationReceipt.model_validate(
        {**body, "receipt_sha256": content_sha256(body)}
    )


def _records() -> tuple[
    ArtifactPointer,
    JobRecord,
    ArtifactRecord,
    ArtifactRevisionRecord,
    JobEventRecord,
]:
    result = _content_team_image_result_v12()
    content_hash = content_sha256(result)
    pointer = IMAGE_V12.model_copy(update={"content_hash": content_hash})
    worker_input = RoleWorkerInput(
        protocol_version="workflow-role/1.24.0",
        job_id=pointer.job_id,
        workflow_id=WORKFLOW_ID,
        step_run_id=str(result["step_run_id"]),
        attempt=pointer.attempt,
        role="image",
        request=WorkerRequest(
            request_name="GENERATED_KNOWLEDGE_ITEM_REQUEST",
            image_mode="required",
        ),
        upstream_artifacts=(),
        artifact=ArtifactSpec(
            logical_artifact_id=pointer.logical_artifact_id,
            revision_id=pointer.revision_id,
        ),
    )
    request = worker_input.model_dump(mode="json")
    job = JobRecord(
        job_id=pointer.job_id,
        protocol_version="workflow-role/1.24.0",
        idempotency_key="visual-reference-image-result-unit",
        request_hash=content_sha256(
            {
                "protocol_version": "workflow-role/1.24.0",
                "task_type": "workflow_image",
                "request": request,
            }
        ),
        task_type="workflow_image",
        request=request,
        status="SUCCEEDED",
        logical_artifact_id=pointer.logical_artifact_id,
        revision_id=pointer.revision_id,
        completed_at=NOW,
    )
    manifest = ArtifactManifest(
        job_id=pointer.job_id,
        logical_artifact_id=pointer.logical_artifact_id,
        revision_id=pointer.revision_id,
        content_hash=pointer.content_hash,
        content_bytes=len(canonical_json_bytes(result)),
        worker_slot="03",
        created_at=NOW,
    ).model_dump(mode="json")
    artifact = ArtifactRecord(
        logical_artifact_id=pointer.logical_artifact_id,
        job_id=pointer.job_id,
        artifact_type="workflow_image",
        approved=True,
    )
    revision = ArtifactRevisionRecord(
        revision_id=pointer.revision_id,
        logical_artifact_id=pointer.logical_artifact_id,
        job_id=pointer.job_id,
        content_hash=pointer.content_hash,
        manifest_hash=content_sha256(manifest),
        content_bytes=len(canonical_json_bytes(result)),
        nas_path="/not-read-by-this-validation-test",
        manifest=manifest,
        result=result,
        approved=True,
    )
    event = JobEventRecord(
        job_id=pointer.job_id,
        sequence=8,
        from_state="COMMITTING",
        to_state="SUCCEEDED",
        event="ARTIFACT_COMMITTED",
        data={
            "logical_artifact_id": pointer.logical_artifact_id,
            "revision_id": pointer.revision_id,
            "content_hash": pointer.content_hash,
            "visual_reference_publication_receipt": _receipt(pointer).model_dump(mode="json"),
        },
    )
    return pointer, job, artifact, revision, event


def test_visual_reference_receipt_binds_exact_image_result_records() -> None:
    pointer, job, artifact, revision, event = _records()
    receipt = OrchestratorVisualReferenceReceiptResolver._validate_image_result(
        image_result=pointer,
        workflow_id=WORKFLOW_ID,
        job=job,
        artifact=artifact,
        revision=revision,
        events=(event,),
    )
    assert receipt.image_result_artifact.revision_id == pointer.revision_id
    assert receipt.entries[0].visual_ordinal == 0


def test_visual_reference_receipt_rejects_stale_image_result_identity() -> None:
    pointer, job, artifact, revision, event = _records()
    stale = pointer.model_copy(update={"content_hash": _sha("f")})
    with pytest.raises(
        VisualReferenceReceiptResolutionError,
        match="immutable pointer",
    ):
        OrchestratorVisualReferenceReceiptResolver._validate_image_result(
            image_result=stale,
            workflow_id=WORKFLOW_ID,
            job=job,
            artifact=artifact,
            revision=revision,
            events=(event,),
        )


def test_visual_reference_receipt_rejects_duplicate_terminal_events() -> None:
    pointer, job, artifact, revision, event = _records()
    with pytest.raises(
        VisualReferenceReceiptResolutionError,
        match="do not resolve",
    ):
        OrchestratorVisualReferenceReceiptResolver._validate_image_result(
            image_result=pointer,
            workflow_id=WORKFLOW_ID,
            job=job,
            artifact=artifact,
            revision=revision,
            events=(event, event),
        )
