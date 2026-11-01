"""Synthetic private provenance only, never real Chat ownership or unit completion."""

from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.embedding_batch_execution_receipt import (
    PRIVATE_CHAT_BATCH_EXECUTION_RECEIPT_SCHEMA_REF,
)
from eom_workflow.native_private_chat_query_coordinator import (
    NativePrivateQueryAllocation,
    NativePrivateQueryBatchExecuted,
    NativePrivateQueryCompleted,
    NativePrivateQueryCompletedV2,
    NativePrivateQueryExecuted,
    NativePrivateQueryPublished,
    NativePrivateQueryPublishedV2,
    native_private_chat_gpu_query_checkpoint,
    native_private_chat_public_query_checkpoint,
    native_private_chat_query_checkpoint,
    private_chat_public_query_checkpoint_receipt,
    private_chat_query_checkpoint_receipt,
)
from eom_workflow.native_reference_query_coordinator import NativeQueryAllocation
from eom_workflow.private_chat_query_execution_v2 import PrivateChatQueryWorkflowRequestV2
from eom_workflow.private_chat_query_workflow import PrivateChatQueryStepOutput
from eom_workflow.private_chat_query_workflow_v2 import PrivateChatQueryStepOutputV2

from tests.unit.inference_transfer_embedding_fixtures import seal


def private_query_records(value):
    public = isinstance(value.request, PrivateChatQueryWorkflowRequestV2)
    receipt = value.receipt
    allocation = NativePrivateQueryAllocation(
        allocation=NativeQueryAllocation.model_validate(
            {
                "query_producer": {
                    "job_id": receipt.query_artifact_owner_job_id,
                    "artifact_id": receipt.execution_record.artifact_id,
                    "artifact_revision_id": receipt.execution_record.artifact_revision_id,
                },
                "receipt_producer": {
                    "job_id": receipt.receipt_owner_job_id,
                    "artifact_id": value.output.receipt.artifact_id,
                    "artifact_revision_id": value.output.receipt.artifact_revision_id,
                },
                "created_at": value.launch.launched_at,
                "source_commit": "a" * 40,
            }
        ),
        origin=value.expected["origin"],
    )
    executed = NativePrivateQueryExecuted.model_validate(
        {
            "boot_id": "11111111-1111-1111-1111-111111111111",
            "prepare": {"invocation_id": "1" * 32, "started_monotonic": 1, "exited_monotonic": 2},
            "query": {"invocation_id": "2" * 32, "started_monotonic": 3, "exited_monotonic": 4},
            "prepare_template_sha256": (
                "sha256:f3c9d2bad306b0f3f1ac35272d2af8d8957c7f8cfd16866695403da0cd4d7227"
            ),
            "query_template_sha256": (
                "sha256:cecb3128eaf33b0e897a813aab7ec4559ca26e63291fb7622a5c429826538bde"
            ),
            "cpu_environment_sha256": "sha256:" + "a" * 64,
            "owner_environment_sha256": "sha256:" + "b" * 64,
            "result_sha256": value.result.result_sha256,
            "completed_observed_at": value.launch.launched_at,
        }
    )
    published = (
        NativePrivateQueryPublishedV2 if public else NativePrivateQueryPublished
    ).model_validate(
        {
            "query_owner_job_id": receipt.query_artifact_owner_job_id,
            "execution_record": receipt.execution_record,
            "result": receipt.query_execution.result_member,
            "shard": receipt.shard,
            "binary": receipt.binary,
            "manifest_sha256": "sha256:" + "c" * 64,
            "published_observed_at": receipt.published_at,
        }
    )
    checked = (
        private_chat_public_query_checkpoint_receipt
        if public
        else private_chat_query_checkpoint_receipt
    )(value.request, value.launch, allocation, executed, published)
    body = value.output.model_dump(mode="json")
    body["receipt_sha256"] = checked.receipt_sha256
    body["receipt"]["sha256"] = sha256_bytes(canonical_json_bytes(checked))
    completed = (NativePrivateQueryCompletedV2 if public else NativePrivateQueryCompleted)(
        output=(
            PrivateChatQueryStepOutputV2 if public else PrivateChatQueryStepOutput
        ).model_validate(seal(body, "output_sha256"))
    )
    return tuple(
        (
            native_private_chat_public_query_checkpoint
            if public
            else native_private_chat_query_checkpoint
        )(value.launch, phase, payload)
        for phase, payload in (
            ("ALLOCATION", allocation),
            ("EXECUTED", executed),
            ("PUBLISHED", published),
            ("COMPLETED", completed),
        )
    )


def private_gpu_query_records(value):
    """Synthetic receipt pointer only; never evidence of physical GPU/source admission."""
    previous = private_query_records(value)
    executed = NativePrivateQueryBatchExecuted(
        batch_receipt=ArtifactMemberPointer(
            artifact_id="artifact_" + "e" * 32,
            artifact_revision_id="rev_" + "e" * 32,
            member_path="receipt.json",
            schema_ref=PRIVATE_CHAT_BATCH_EXECUTION_RECEIPT_SCHEMA_REF,
            media_type="application/json",
            sha256=content_sha256({"synthetic_private_batch": value.launch.association_sha256}),
        ),
        batch_receipt_sha256=content_sha256({"synthetic_receipt": value.launch.association_sha256}),
        child_ordinal=0,
        result_sha256=value.result.result_sha256,
        completed_observed_at=previous[1].payload.completed_observed_at,
    )
    return tuple(
        native_private_chat_gpu_query_checkpoint(
            value.launch,
            record.record_type,
            executed if record.record_type == "EXECUTED" else record.payload,
        )
        for record in previous
    )
