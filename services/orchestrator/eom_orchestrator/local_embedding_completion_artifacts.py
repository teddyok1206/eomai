"""Commit a self-identifying native completion through the existing file-set owner."""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.local_embedding_workflow_receipt_v2 import (
    SupportedLocalEmbeddingStepOutput,
    SupportedLocalEmbeddingWorkflowReceipt,
    build_supported_local_embedding_step_output,
    local_embedding_step_output_type_for_receipt,
    parse_supported_local_embedding_workflow_receipt,
)
from eom_workflow.private_chat_query_workflow import (
    PRIVATE_CHAT_QUERY_RECEIPT_REF,
    PrivateChatQueryStepOutput,
    PrivateChatQueryWorkflowReceipt,
    validate_private_chat_query_step_output,
)
from eom_workflow.reference_query_execution import (
    PUBLIC_REFERENCE_QUERY_RECEIPT_REF,
    REFERENCE_QUERY_RECEIPT_REF,
    ReferenceQueryStepOutput,
    ReferenceQueryStepOutputV2,
    ReferenceQueryWorkflowReceipt,
    ReferenceQueryWorkflowReceiptV2,
    SupportedReferenceQueryStepOutput,
    SupportedReferenceQueryWorkflowReceipt,
    parse_reference_query_workflow_receipt,
    parse_supported_reference_query_step_output,
    parse_supported_reference_query_workflow_receipt,
    validate_reference_query_step_output,
)

from eom_orchestrator.file_set_control_artifacts import (
    CONTROL_FILE_SET_PROTOCOL,
    ControlFileSetIdentity,
    ControlFileSetMember,
    ControlFileSetPublisher,
)

NATIVE_COMPLETION_ARTIFACT_TYPE = "control_local_embedding_completion"
QUERY_COMPLETION_ARTIFACT_TYPE = "control_reference_query_completion"
PRIVATE_CHAT_QUERY_COMPLETION_ARTIFACT_TYPE = "control_private_chat_query_completion"


class NativeEmbeddingCompletionPublisher:
    """Caller pins allocation/observation once and freshly fences before publication."""

    def __init__(self, publisher: ControlFileSetPublisher, *, source_commit: str) -> None:
        self.publisher, self.source_commit = publisher, source_commit

    def publish(
        self, receipt: SupportedLocalEmbeddingWorkflowReceipt, *, identity: ControlFileSetIdentity
    ) -> SupportedLocalEmbeddingStepOutput:
        receipt = parse_supported_local_embedding_workflow_receipt(receipt)
        output_type = local_embedding_step_output_type_for_receipt(receipt)
        schema_ref = output_type.model_fields["receipt_schema"].default
        identity = ControlFileSetIdentity(
            identity.job_id, identity.artifact_id, identity.artifact_revision_id
        )
        if receipt.receipt_owner_job_id != identity.job_id:
            raise ValueError("LOCAL_EMBEDDING_RECEIPT_PRODUCER_MISMATCH")
        raw = canonical_json_bytes(receipt.model_dump(mode="json"))
        key = "native-embedding-receipt:" + content_sha256(
            {
                "workflow_id": receipt.workflow_id,
                "step_run_id": receipt.step_run_id,
                "attempt": receipt.attempt,
                "request_sha256": receipt.workflow_request_sha256,
            }
        ).removeprefix("sha256:")
        pointer = self._publish_receipt(
            raw,
            identity=identity,
            key=key,
            artifact_type=NATIVE_COMPLETION_ARTIFACT_TYPE,
            schema_ref=schema_ref,
            created_at=receipt.registration_observed_at,
            mismatch_code="LOCAL_EMBEDDING_RECEIPT_PUBLICATION_MISMATCH",
        )
        return build_supported_local_embedding_step_output(receipt, pointer)

    def publish_reference_query(
        self, receipt: ReferenceQueryWorkflowReceipt, *, identity: ControlFileSetIdentity
    ) -> ReferenceQueryStepOutput:
        receipt = parse_reference_query_workflow_receipt(receipt)
        output = self.publish_supported_reference_query(receipt, identity=identity)
        if not isinstance(output, ReferenceQueryStepOutput):
            raise ValueError("REFERENCE_QUERY_RECEIPT_PRODUCER_MISMATCH")
        return output

    def publish_public_solution_reference_query(
        self, receipt: ReferenceQueryWorkflowReceiptV2, *, identity: ControlFileSetIdentity
    ) -> ReferenceQueryStepOutputV2:
        receipt = ReferenceQueryWorkflowReceiptV2.model_validate(receipt)
        output = self.publish_supported_reference_query(receipt, identity=identity)
        if not isinstance(output, ReferenceQueryStepOutputV2):
            raise ValueError("REFERENCE_QUERY_RECEIPT_PRODUCER_MISMATCH")
        return output

    def publish_supported_reference_query(
        self, receipt: SupportedReferenceQueryWorkflowReceipt, *, identity: ControlFileSetIdentity
    ) -> SupportedReferenceQueryStepOutput:
        receipt = parse_supported_reference_query_workflow_receipt(receipt)
        public = isinstance(receipt, ReferenceQueryWorkflowReceiptV2)
        schema_ref = PUBLIC_REFERENCE_QUERY_RECEIPT_REF if public else REFERENCE_QUERY_RECEIPT_REF
        identity = ControlFileSetIdentity(
            identity.job_id, identity.artifact_id, identity.artifact_revision_id
        )
        if (
            receipt.receipt_owner_job_id != identity.job_id
            or identity.artifact_id == receipt.query_input.artifact_id
            or identity.artifact_revision_id == receipt.query_input.artifact_revision_id
            or len(
                {
                    receipt.receipt_owner_job_id,
                    receipt.query_artifact_owner_job_id,
                    receipt.native_launch_job_id,
                }
            )
            != 3
        ):
            raise ValueError("REFERENCE_QUERY_RECEIPT_PRODUCER_MISMATCH")
        raw = canonical_json_bytes(receipt.model_dump(mode="json"))
        key = "native-reference-query-receipt:" + content_sha256(
            {
                "workflow_id": receipt.workflow_id,
                "step_run_id": receipt.step_run_id,
                "attempt": receipt.attempt,
                "request_sha256": receipt.workflow_request_sha256,
            }
        ).removeprefix("sha256:")
        pointer = self._publish_receipt(
            raw,
            identity=identity,
            key=key,
            artifact_type=QUERY_COMPLETION_ARTIFACT_TYPE,
            schema_ref=schema_ref,
            created_at=receipt.published_at,
            mismatch_code="REFERENCE_QUERY_RECEIPT_PUBLICATION_MISMATCH",
        )
        body = {
            "schema_version": "reference-query-step-output/2.0"
            if public
            else "reference-query-step-output/1.0",
            "purpose": "REFERENCE_QUERY",
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
            "receipt_schema": schema_ref,
            "receipt": pointer.model_dump(mode="json"),
        }
        output = parse_supported_reference_query_step_output(
            body | {"output_sha256": content_sha256(body)}
        )
        validate_reference_query_step_output(output, receipt)
        return output

    def publish_private_chat_query(
        self, receipt: PrivateChatQueryWorkflowReceipt, *, identity: ControlFileSetIdentity
    ) -> PrivateChatQueryStepOutput:
        """Commit validated metadata only; caller retains original live-source/native fences."""
        receipt = PrivateChatQueryWorkflowReceipt.model_validate(receipt)
        identity = ControlFileSetIdentity(
            identity.job_id, identity.artifact_id, identity.artifact_revision_id
        )
        if receipt.receipt_owner_job_id != identity.job_id:
            raise ValueError("PRIVATE_CHAT_QUERY_RECEIPT_PRODUCER_MISMATCH")
        raw = canonical_json_bytes(receipt)
        body = {
            "schema_version": "private-chat-query-step-output/1.0",
            "purpose": "PRIVATE_CHAT_QUERY",
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
            "receipt_schema": PRIVATE_CHAT_QUERY_RECEIPT_REF,
            "receipt": ArtifactMemberPointer(
                artifact_id=identity.artifact_id,
                artifact_revision_id=identity.artifact_revision_id,
                member_path="receipt.json",
                schema_ref=PRIVATE_CHAT_QUERY_RECEIPT_REF,
                media_type="application/json",
                sha256=sha256_bytes(raw),
            ).model_dump(mode="json"),
        }
        output = PrivateChatQueryStepOutput.model_validate(
            body | {"output_sha256": content_sha256(body)}
        )
        # A four-member numeric file set cannot be reused as the one-member receipt set.
        validate_private_chat_query_step_output(output, receipt)
        key = "native-private-chat-query-receipt:" + content_sha256(
            {
                "workflow_id": receipt.workflow_id,
                "step_run_id": receipt.step_run_id,
                "attempt": receipt.attempt,
            }
        ).removeprefix("sha256:")
        pointer = self._publish_receipt(
            raw,
            identity=identity,
            key=key,
            artifact_type=PRIVATE_CHAT_QUERY_COMPLETION_ARTIFACT_TYPE,
            schema_ref=PRIVATE_CHAT_QUERY_RECEIPT_REF,
            created_at=receipt.published_at,
            mismatch_code="PRIVATE_CHAT_QUERY_RECEIPT_PUBLICATION_MISMATCH",
        )
        if pointer != output.receipt:
            raise ValueError("PRIVATE_CHAT_QUERY_RECEIPT_PUBLICATION_MISMATCH")
        return output

    def _publish_receipt(
        self,
        raw: bytes,
        *,
        identity: ControlFileSetIdentity,
        key: str,
        artifact_type: str,
        schema_ref: str,
        created_at: datetime,
        mismatch_code: str,
    ) -> ArtifactMemberPointer:
        """Only shared file-set mechanics; each purpose validates its own contract above."""
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
                        schema_ref,
                        "application/json",
                    ),
                ),
                primary_file="receipt.json",
                artifact_type=artifact_type,
                manifest_version=CONTROL_FILE_SET_PROTOCOL,
                idempotency_key=key,
                source_commit=self.source_commit,
                created_at=created_at,
            )
        if (
            published.job_id != identity.job_id
            or published.artifact_id != identity.artifact_id
            or published.artifact_revision_id != identity.artifact_revision_id
            or published.primary_file != "receipt.json"
            or published.primary_sha256 != sha256_bytes(raw)
        ):
            raise ValueError(mismatch_code)
        return ArtifactMemberPointer(
            artifact_id=published.artifact_id,
            artifact_revision_id=published.artifact_revision_id,
            member_path="receipt.json",
            schema_ref=schema_ref,
            media_type="application/json",
            sha256=sha256_bytes(raw),
        )
