"""Synthetic private provenance only, never real Chat ownership or unit completion."""

from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.native_private_chat_query_coordinator import (
    NativePrivateQueryAllocation,
    NativePrivateQueryCompleted,
    NativePrivateQueryExecuted,
    NativePrivateQueryPublished,
    native_private_chat_query_checkpoint,
    private_chat_query_checkpoint_receipt,
)
from eom_workflow.native_reference_query_coordinator import NativeQueryAllocation
from eom_workflow.private_chat_query_workflow import PrivateChatQueryStepOutput

from tests.unit.inference_transfer_embedding_fixtures import seal


def private_query_records(value):
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
    published = NativePrivateQueryPublished.model_validate(
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
    checked = private_chat_query_checkpoint_receipt(
        value.request, value.launch, allocation, executed, published
    )
    body = value.output.model_dump(mode="json")
    body["receipt_sha256"] = checked.receipt_sha256
    body["receipt"]["sha256"] = sha256_bytes(canonical_json_bytes(checked))
    completed = NativePrivateQueryCompleted(
        output=PrivateChatQueryStepOutput.model_validate(seal(body, "output_sha256"))
    )
    return tuple(
        native_private_chat_query_checkpoint(value.launch, phase, payload)
        for phase, payload in (
            ("ALLOCATION", allocation),
            ("EXECUTED", executed),
            ("PUBLISHED", published),
            ("COMPLETED", completed),
        )
    )
