"""Commit a self-identifying native completion through the existing file-set owner."""

from __future__ import annotations

import tempfile
from pathlib import Path

from eom_identifiers import content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.local_embedding_workflow_receipt import (
    LOCAL_EMBEDDING_WORKFLOW_RECEIPT_SCHEMA_REF,
    LocalEmbeddingStepOutput,
    LocalEmbeddingWorkflowReceipt,
    local_embedding_workflow_receipt_bytes,
    parse_local_embedding_step_output,
    parse_local_embedding_workflow_receipt,
    validate_local_embedding_step_output,
)

from eom_orchestrator.file_set_control_artifacts import (
    CONTROL_FILE_SET_PROTOCOL,
    ControlFileSetIdentity,
    ControlFileSetMember,
    ControlFileSetPublisher,
)

NATIVE_COMPLETION_ARTIFACT_TYPE = "control_local_embedding_completion"


class NativeEmbeddingCompletionPublisher:
    """Caller pins allocation/observation once and freshly fences before publication."""

    def __init__(self, publisher: ControlFileSetPublisher, *, source_commit: str) -> None:
        self.publisher, self.source_commit = publisher, source_commit

    def publish(
        self, receipt: LocalEmbeddingWorkflowReceipt, *, identity: ControlFileSetIdentity
    ) -> LocalEmbeddingStepOutput:
        receipt = parse_local_embedding_workflow_receipt(receipt)
        identity = ControlFileSetIdentity(
            identity.job_id, identity.artifact_id, identity.artifact_revision_id
        )
        if receipt.receipt_owner_job_id != identity.job_id:
            raise ValueError("LOCAL_EMBEDDING_RECEIPT_PRODUCER_MISMATCH")
        raw = local_embedding_workflow_receipt_bytes(receipt)
        key = "native-embedding-receipt:" + content_sha256(
            {
                "workflow_id": receipt.workflow_id,
                "step_run_id": receipt.step_run_id,
                "attempt": receipt.attempt,
                "request_sha256": receipt.workflow_request_sha256,
            }
        ).removeprefix("sha256:")
        with tempfile.TemporaryDirectory(
            prefix="native-receipt-", dir=self.publisher.settings.workspace_root
        ) as directory:
            path = Path(directory) / "receipt.json"
            path.write_bytes(raw)
            path.chmod(0o600)
            published = self.publisher.publish_identified(
                identity=identity,
                members=(
                    ControlFileSetMember(
                        "receipt.json",
                        path,
                        sha256_bytes(raw),
                        len(raw),
                        LOCAL_EMBEDDING_WORKFLOW_RECEIPT_SCHEMA_REF,
                        "application/json",
                    ),
                ),
                primary_file="receipt.json",
                artifact_type=NATIVE_COMPLETION_ARTIFACT_TYPE,
                manifest_version=CONTROL_FILE_SET_PROTOCOL,
                idempotency_key=key,
                source_commit=self.source_commit,
                created_at=receipt.registration_observed_at,
            )
        if (
            published.job_id != identity.job_id
            or published.artifact_id != identity.artifact_id
            or published.artifact_revision_id != identity.artifact_revision_id
            or published.primary_file != "receipt.json"
            or published.primary_sha256 != sha256_bytes(raw)
        ):
            raise ValueError("LOCAL_EMBEDDING_RECEIPT_PUBLICATION_MISMATCH")
        pointer = ArtifactMemberPointer(
            artifact_id=published.artifact_id,
            artifact_revision_id=published.artifact_revision_id,
            member_path="receipt.json",
            schema_ref=LOCAL_EMBEDDING_WORKFLOW_RECEIPT_SCHEMA_REF,
            media_type="application/json",
            sha256=sha256_bytes(raw),
        )
        body = {
            "schema_version": "local-embedding-step-output/1.0",
            "purpose": "LOCAL_EMBEDDING",
            **{
                field: getattr(receipt, field)
                for field in (
                    "workflow_id",
                    "step_run_id",
                    "step_key",
                    "attempt",
                    "receipt_owner_job_id",
                    "execution_result_schema",
                    "receipt_sha256",
                )
            },
            "receipt_schema": LOCAL_EMBEDDING_WORKFLOW_RECEIPT_SCHEMA_REF,
            "receipt": pointer.model_dump(mode="json"),
        }
        output = parse_local_embedding_step_output(body | {"output_sha256": content_sha256(body)})
        return validate_local_embedding_step_output(output, receipt)
