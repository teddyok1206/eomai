"""Synthetic unit/source metadata only; never real numerical or IAM evidence."""

from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.native_reference_query_coordinator import (
    NativeQueryAllocation,
    NativeQueryCompleted,
    NativeQueryExecuted,
    NativeQueryPublished,
    native_reference_query_checkpoint,
    reference_query_checkpoint_receipt,
)
from eom_workflow.reference_query_execution import parse_reference_query_step_output

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.inference_transfer_fixtures import NOW, sha
from tests.unit.test_reference_query_execution_contracts import Case, case


def query_records(value: Case | None = None):
    value = value or case()
    allocation = NativeQueryAllocation.model_validate(
        {
            "query_producer": {
                "job_id": value.receipt.query_artifact_owner_job_id,
                "artifact_id": value.receipt.query_input.artifact_id,
                "artifact_revision_id": value.receipt.query_input.artifact_revision_id,
            },
            "receipt_producer": {
                "job_id": value.receipt.receipt_owner_job_id,
                "artifact_id": value.output.receipt.artifact_id,
                "artifact_revision_id": value.output.receipt.artifact_revision_id,
            },
            "created_at": NOW,
            "source_commit": "a" * 40,
        }
    )
    executed = NativeQueryExecuted.model_validate(
        {
            "boot_id": "11111111-1111-1111-1111-111111111111",
            "prepare": {"invocation_id": "1" * 32, "started_monotonic": 1, "exited_monotonic": 2},
            "query": {"invocation_id": "2" * 32, "started_monotonic": 3, "exited_monotonic": 4},
            "prepare_template_sha256": (
                "sha256:4194d01ea9cffbc5468aac5f5f174303952e1008f8a8621ad1adea07ef76905f"
            ),
            "query_template_sha256": (
                "sha256:1bd18e257988df4b3e39eb486e208b999ae7e9e897905ca07f513fc5f3e7893b"
            ),
            "cpu_environment_sha256": sha("a"),
            "owner_environment_sha256": sha("b"),
            "result_sha256": value.result.result_sha256,
            "completed_observed_at": NOW,
        }
    )
    published = NativeQueryPublished.model_validate(
        {
            "query_owner_job_id": value.receipt.query_artifact_owner_job_id,
            "input": value.receipt.query_input.model_dump(mode="json"),
            "result": value.receipt.query_execution.result_member.model_dump(mode="json"),
            "shard": value.receipt.shard.model_dump(mode="json"),
            "binary": value.receipt.binary.model_dump(mode="json"),
            "manifest_sha256": sha("c"),
            "published_observed_at": NOW,
        }
    )
    receipt = reference_query_checkpoint_receipt(
        value.request, value.launch, allocation, executed, published
    )
    body = value.output.model_dump(mode="json")
    body["receipt_sha256"] = receipt.receipt_sha256
    body["receipt"]["sha256"] = sha256_bytes(canonical_json_bytes(receipt.model_dump(mode="json")))
    completed = NativeQueryCompleted(
        output=parse_reference_query_step_output(seal(body, "output_sha256"))
    )
    return tuple(
        native_reference_query_checkpoint(value.launch, phase, payload)
        for phase, payload in (
            ("ALLOCATION", allocation),
            ("EXECUTED", executed),
            ("PUBLISHED", published),
            ("COMPLETED", completed),
        )
    )
