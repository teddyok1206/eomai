"""Synthetic allocation wire closure; no root peer, hardware grant or model execution."""

from __future__ import annotations

from copy import deepcopy

import pytest
from eom_catalog_contracts.embedding_gpu_control import (
    EmbeddingGpuAllocationBusy,
    EmbeddingGpuAllocationReady,
    EmbeddingGpuControlError,
    embedding_gpu_control_bytes,
    parse_embedding_gpu_control,
    parse_embedding_gpu_control_bytes,
    validate_embedding_gpu_allocation_link,
    validate_embedding_gpu_batch_grant,
    validate_embedding_gpu_fence_ack,
    validate_embedding_gpu_grant,
    validate_embedding_gpu_result_ack,
)
from eom_catalog_contracts.embedding_work_batch import EmbeddingWorkBatchInput
from eom_identifiers import canonical_json_bytes, sha256_bytes

from tests.unit.embedding_installed_runtime_fixtures import runtime_proof
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_work_batch import batch_body


def _frame(kind, values):
    return parse_embedding_gpu_control(
        seal(
            {
                "schema_version": "embedding-gpu-allocation-control/1.0",
                "message_type": kind,
                "allocation_attempt_id": "embeddingallocation_" + "a" * 32,
            }
            | values,
            "message_sha256",
        )
    )


def control_case(*, expires_ns=1000000000, batch=None):
    sha = "sha256:" + "a" * 64
    request = _frame(
        "ALLOCATION_REQUEST",
        {
            "parent_request_sha256": sha,
            "child_set_sha256": sha,
            "routing_policy_sha256": sha,
            "purpose": "REFERENCE_QUERY",
            "configuration": {
                "configuration_id": "embeddingnativeconfig_" + "a" * 32,
                "configuration_revision_id": "embeddingnativeconfigrev_" + "b" * 32,
                "configuration_sha256": sha,
                "configuration_raw_sha256": sha,
            },
            "receipt_raw_sha256": sha,
            "expires_monotonic_ns": expires_ns,
        },
    )
    identity = dict(pid=123, start_time_ticks=456, worker_uid=1234, worker_gid=1234)
    ready = _frame(
        "ALLOCATION_READY",
        {
            "allocation_request_sha256": request.message_sha256,
            "evidence_state": "RETENTION_REQUESTED_NOT_COMPUTE_ADMITTED",
            **identity,
            "supplementary_gids": [2468],
            "resource_fds": {
                "nvidia0_fd": 10,
                "nvidiactl_fd": 11,
                "nvidia_uvm_fd": 12,
                "nvidia_uvm_tools_fd": 13,
                "lease_fd": 14,
            },
            "expected_device_capture": runtime_proof("CUDA_INDEX_FP32").device_capture.model_dump(
                mode="json"
            ),
            "fdstore_name": "eom-gpu0-lease",
        },
    )
    busy = _frame(
        "ALLOCATION_BUSY",
        {
            "allocation_request_sha256": request.message_sha256,
            "evidence_state": "ALLOCATION_UNAVAILABLE_NOT_EXECUTED",
            **identity,
        },
    )
    batch = batch or EmbeddingWorkBatchInput.model_validate(batch_body(device="CUDA"))
    raw = canonical_json_bytes(batch.model_dump(mode="json"))
    grant = _frame(
        "COMPUTE_GRANT",
        {
            "allocation_request_sha256": request.message_sha256,
            "ready_message_sha256": ready.message_sha256,
            "routing_decision_sha256": batch.routing_decision_sha256,
            "batch_request_sha256": batch.request_sha256,
            "batch_input_raw_sha256": sha256_bytes(raw),
            "batch_input_byte_count": len(raw),
        },
    )
    check = _frame(
        "CHECK_CHILD",
        {
            "allocation_request_sha256": request.message_sha256,
            "grant_message_sha256": grant.message_sha256,
            "batch_request_sha256": batch.request_sha256,
            "child_request_sha256": batch.children[0].request.request_sha256,
            "sequence": 1,
        },
    )
    ack = _frame(
        "FENCE_ACK",
        check.model_dump(
            mode="json",
            exclude={"schema_version", "message_type", "allocation_attempt_id", "message_sha256"},
        )
        | {"check_message_sha256": check.message_sha256},
    )
    return request, ready, busy, grant, check, ack, batch, raw


@pytest.mark.parametrize("position", range(6))
def test_each_closed_frame_is_canonical_and_bounded(position):
    frame = control_case()[position]
    assert parse_embedding_gpu_control_bytes(embedding_gpu_control_bytes(frame)) == frame
    assert (
        parse_embedding_gpu_control_bytes(embedding_gpu_control_bytes(frame)).message_type
        == frame.message_type
    )
    with pytest.raises(EmbeddingGpuControlError):
        parse_embedding_gpu_control_bytes(b" " + embedding_gpu_control_bytes(frame))


def test_exact_original_request_ready_grant_batch_and_child_ack_close():
    request, ready, busy, grant, check, ack, batch, raw = control_case()
    validate_embedding_gpu_allocation_link(request, ready)
    validate_embedding_gpu_allocation_link(request, busy)
    validate_embedding_gpu_grant(request, ready, grant)
    validate_embedding_gpu_batch_grant(
        request, grant, batch, input_raw_sha256=sha256_bytes(raw), input_byte_count=len(raw)
    )
    validate_embedding_gpu_fence_ack(grant, check, ack)


def test_busy_or_grant_cannot_masquerade_as_an_acquired_readiness():
    request, ready, busy, grant, *_ = control_case()
    with pytest.raises(EmbeddingGpuControlError):
        validate_embedding_gpu_grant(request, busy, grant)
    with pytest.raises(EmbeddingGpuControlError):
        validate_embedding_gpu_allocation_link(request, grant)
    assert isinstance(ready, EmbeddingGpuAllocationReady)
    assert isinstance(busy, EmbeddingGpuAllocationBusy)


@pytest.mark.parametrize(
    "field",
    [
        "allocation_attempt_id",
        "allocation_request_sha256",
        "grant_message_sha256",
        "batch_request_sha256",
        "child_request_sha256",
        "sequence",
        "check_message_sha256",
    ],
)
def test_resealed_foreign_or_old_child_ack_is_not_valid(field):
    _, _, _, grant, check, ack, *_ = control_case()
    body = deepcopy(ack.model_dump(mode="json"))
    body[field] = (
        2
        if field == "sequence"
        else "embeddingallocation_" + "b" * 32
        if field == "allocation_attempt_id"
        else "sha256:" + "b" * 64
    )
    changed = parse_embedding_gpu_control(seal(body, "message_sha256"))
    with pytest.raises(EmbeddingGpuControlError):
        validate_embedding_gpu_fence_ack(grant, check, changed)


@pytest.mark.parametrize(
    "field", ["ready_message_sha256", "allocation_request_sha256", "allocation_attempt_id"]
)
def test_foreign_ready_or_allocation_grant_is_not_replayed(field):
    request, ready, _, grant, *_ = control_case()
    body = grant.model_dump(mode="json")
    body[field] = (
        "embeddingallocation_" + "b" * 32
        if field == "allocation_attempt_id"
        else "sha256:" + "b" * 64
    )
    with pytest.raises(EmbeddingGpuControlError):
        validate_embedding_gpu_grant(
            request, ready, parse_embedding_gpu_control(seal(body, "message_sha256"))
        )


@pytest.mark.parametrize("fault", ["byte_count", "raw_hash", "cpu", "purpose"])
def test_batch_grant_checks_actual_fd_values_device_and_purpose(fault):
    request, _, _, grant, _, _, batch, raw = control_case()
    count, digest = len(raw), sha256_bytes(raw)
    if fault == "byte_count":
        count += 1
    elif fault == "raw_hash":
        digest = "sha256:" + "b" * 64
    elif fault == "cpu":
        batch = EmbeddingWorkBatchInput.model_validate(batch_body(device="CPU"))
    else:
        body = request.model_dump(mode="json") | {"purpose": "PRIVATE_CHAT_QUERY"}
        request = parse_embedding_gpu_control(seal(body, "message_sha256"))
    with pytest.raises(EmbeddingGpuControlError):
        validate_embedding_gpu_batch_grant(
            request, grant, batch, input_raw_sha256=digest, input_byte_count=count
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("sequence", 0),
        ("sequence", 257),
        ("sequence", True),
        ("sequence", "1"),
        ("message_type", "RUN_SHELL"),
        ("token", "not allowed"),
    ],
)
def test_control_does_not_accept_unbounded_values_or_arbitrary_commands(field, value):
    check = control_case()[4]
    body = check.model_dump(mode="json") | {field: value}
    with pytest.raises(EmbeddingGpuControlError):
        parse_embedding_gpu_control(seal(body, "message_sha256"))


def test_constructed_extras_cannot_be_dropped_by_serialization():
    request = control_case()[0]
    with pytest.raises(EmbeddingGpuControlError):
        embedding_gpu_control_bytes(request.model_copy(update={"extra": True}))


def result_frames():
    request, _, _, grant, *_ = control_case()
    sha = "sha256:" + "c" * 64
    result = _frame(
        "RESULT_READY",
        {
            "allocation_request_sha256": request.message_sha256,
            "grant_message_sha256": grant.message_sha256,
            "batch_request_sha256": grant.batch_request_sha256,
            "result_raw_sha256": sha,
            "result_sha256": sha,
            "vectors_sha256": sha,
            "result_byte_count": 1024,
            "vectors_byte_count": 4096,
        },
    )
    ack = _frame(
        "RESULT_ACK",
        {
            "allocation_request_sha256": request.message_sha256,
            "grant_message_sha256": grant.message_sha256,
            "batch_request_sha256": grant.batch_request_sha256,
            "result_message_sha256": result.message_sha256,
        },
    )
    return grant, result, ack


@pytest.mark.parametrize("position", [1, 2])
def test_result_frames_are_canonical_and_closed(position):
    frame = result_frames()[position]
    assert parse_embedding_gpu_control_bytes(embedding_gpu_control_bytes(frame)) == frame


def test_output_ack_closes_original_grant_and_local_result_only():
    validate_embedding_gpu_result_ack(*result_frames())


@pytest.mark.parametrize(
    "field",
    [
        "allocation_attempt_id",
        "allocation_request_sha256",
        "grant_message_sha256",
        "batch_request_sha256",
        "result_message_sha256",
    ],
)
def test_resealed_result_ack_cannot_ack_another_result_or_grant(field):
    grant, result, ack = result_frames()
    body = ack.model_dump(mode="json")
    body[field] = (
        "embeddingallocation_" + "b" * 32
        if field == "allocation_attempt_id"
        else "sha256:" + "b" * 64
    )
    with pytest.raises(EmbeddingGpuControlError):
        validate_embedding_gpu_result_ack(
            grant, result, parse_embedding_gpu_control(seal(body, "message_sha256"))
        )
