"""QUERY2 continuation values only; unit/GPU receipt pointers are synthetic, not authority."""

from pathlib import Path

import pytest
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_workflow.native_reference_query_coordinator import (
    NativeQueryAllocation,
    NativeQueryBatchExecuted,
    NativeQueryCompletedV2,
    NativeQueryExecutedV11,
    NativeQueryPublishedV2,
    native_reference_query_continuation_checkpoint,
    parse_native_reference_query_checkpoint,
    parse_supported_native_reference_query_checkpoint,
    reference_query_checkpoint_receipt,
    validate_native_reference_query_history,
)
from eom_workflow.reference_query_execution import ReferenceQueryStepOutputV2
from eom_workflow.schemas import (
    NATIVE_REFERENCE_QUERY_COORDINATOR_V2_SCHEMA_RESOURCE,
    load_native_reference_query_coordinator_v2_schema,
)

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.native_reference_query_coordinator_fixtures import query_records
from tests.unit.test_native_reference_query_coordinator_v12 import batch_query_records
from tests.unit.test_public_solution_reference_query_execution import public_workflow_case
from tests.unit.test_reference_query_execution_contracts import case

VERSION = "native-reference-query-coordinator/2.0"
ROOT = Path(__file__).resolve().parents[2]


def public_query_records(value=None, *, device="CPU"):
    value = value or public_workflow_case(device=device)
    old = query_records(case(device=device), version="native-reference-query-coordinator/1.1")
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
            "created_at": value.launch.launched_at,
            "source_commit": "a" * 40,
        }
    )
    executed = (
        NativeQueryBatchExecuted.model_validate(
            batch_query_records()[1].payload.model_dump(mode="json")
            | {"result_sha256": value.result.result_sha256}
        )
        if device == "CUDA"
        else NativeQueryExecutedV11.model_validate(
            old[1].payload.model_dump(mode="json") | {"result_sha256": value.result.result_sha256}
        )
    )
    published = NativeQueryPublishedV2.model_validate(
        {
            "query_owner_job_id": value.receipt.query_artifact_owner_job_id,
            "input": value.receipt.query_input.model_dump(mode="json"),
            "result": value.receipt.query_execution.result_member.model_dump(mode="json"),
            "shard": value.receipt.shard.model_dump(mode="json"),
            "binary": value.receipt.binary.model_dump(mode="json"),
            "manifest_sha256": "sha256:" + "c" * 64,
            "published_observed_at": value.receipt.published_at,
        }
    )
    receipt = reference_query_checkpoint_receipt(
        value.request, value.launch, allocation, executed, published
    )
    body = value.output.model_dump(mode="json")
    body["receipt_sha256"] = receipt.receipt_sha256
    body["receipt"]["sha256"] = sha256_bytes(canonical_json_bytes(receipt.model_dump(mode="json")))
    completed = NativeQueryCompletedV2(
        output=ReferenceQueryStepOutputV2.model_validate(seal(body, "output_sha256"))
    )
    records = []
    for phase, payload in [
        ("ALLOCATION", allocation),
        ("EXECUTED", executed),
        ("PUBLISHED", published),
        ("COMPLETED", completed),
    ]:
        records.append(
            native_reference_query_continuation_checkpoint(
                value.launch,
                phase,
                payload,
                previous=tuple(records),
                initial_version=VERSION,
            )
        )
    return tuple(records)


@pytest.mark.parametrize("device", ["CPU", "CUDA"])
def test_public_query_contiguous_prefixes_keep_exact_request_device_members_and_receipt(device):
    value = public_workflow_case(device=device)
    records = public_query_records(value, device=device)
    for count in range(5):
        validate_native_reference_query_history(records[:count], value.launch, value.request)
    for record in records:
        assert parse_supported_native_reference_query_checkpoint(record) == record
        assert record.schema_version == VERSION
        assert len(canonical_json_bytes(record.model_dump(mode="json"))) < 16 * 1024
        with pytest.raises(ValueError):
            parse_native_reference_query_checkpoint(record)
    assert records[2].payload.input.schema_ref.endswith("/2.0")
    assert (
        records[3].payload.output.execution_result_schema == "embedding-reference-query-result@2.0"
    )


def test_public_query_continuation_schema_is_pinned_mirrored_and_predecessor_not_modified():
    filename, schema_id, digest = NATIVE_REFERENCE_QUERY_COORDINATOR_V2_SCHEMA_RESOURCE
    payload = (ROOT / "schemas/workflow" / filename).read_bytes()
    assert payload == (ROOT / "packages/workflow/eom_workflow/resources" / filename).read_bytes()
    assert sha256_bytes(payload) == digest and schema_id.endswith("/2.0")
    assert load_native_reference_query_coordinator_v2_schema()["$id"] == schema_id
    assert (
        sha256_bytes(
            (
                ROOT / "schemas/workflow/native-reference-query-coordinator-v1.schema.json"
            ).read_bytes()
        )
        == "sha256:b3711bf1f8722b9a0b884dac7f3ef032c0bd28bd4e76351f3d7ee4d1e0f17745"
    )


@pytest.mark.parametrize(
    "fault",
    [
        "legacy_input",
        "legacy_result",
        "wrong_receipt",
        "extra",
        "hash",
        "mixed_execution",
        "cpu_batch",
        "foreign_request",
        "mixed_history",
    ],
)
def test_public_query_history_rejects_family_device_and_producer_substitution(fault):
    value = public_workflow_case()
    records = public_query_records(value)
    old = query_records(case())
    if fault in {
        "legacy_input",
        "legacy_result",
        "wrong_receipt",
        "extra",
        "hash",
        "mixed_execution",
    }:
        ordinal = (
            2
            if fault in {"legacy_input", "legacy_result"}
            else 3
            if fault == "wrong_receipt"
            else 1
        )
        body = records[ordinal].model_dump(mode="json")
        if fault in {"legacy_input", "legacy_result"}:
            field = "input" if fault == "legacy_input" else "result"
            body["payload"][field] = getattr(old[2].payload, field).model_dump(mode="json")
        elif fault == "wrong_receipt":
            body["payload"]["output"] = old[3].payload.output.model_dump(mode="json")
        elif fault == "extra":
            body["payload"]["authority"] = "ADMIN"
        elif fault == "hash":
            body["checkpoint_sha256"] = content_sha256({"foreign": True})
        else:
            body["payload"]["batch_receipt"] = batch_query_records()[
                1
            ].payload.batch_receipt.model_dump(mode="json")
        with pytest.raises(ValueError):
            parse_supported_native_reference_query_checkpoint(
                body if fault == "hash" else seal(body, "checkpoint_sha256")
            )
        return
    if fault == "foreign_request":
        with pytest.raises(ValueError):
            validate_native_reference_query_history(records[:1], case().launch, case().request)
    elif fault == "mixed_history":
        with pytest.raises(ValueError):
            validate_native_reference_query_history(
                (old[0], *records[1:]), value.launch, value.request
            )
    else:
        batch = batch_query_records()[1].payload
        wrong = native_reference_query_continuation_checkpoint(
            value.launch, "EXECUTED", batch, previous=records[:1], initial_version=VERSION
        )
        with pytest.raises(ValueError, match="device"):
            validate_native_reference_query_history(
                (records[0], wrong), value.launch, value.request
            )


def test_public_query_resume_retains_original_checkpoint_family_after_release_change():
    value = public_workflow_case()
    records = public_query_records(value)
    replay = native_reference_query_continuation_checkpoint(
        value.launch,
        "PUBLISHED",
        records[2].payload,
        previous=records[:2],
        initial_version="native-reference-query-coordinator/1.1",
    )
    assert replay == records[2]
