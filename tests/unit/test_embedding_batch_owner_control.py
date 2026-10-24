"""Synthetic owner metadata contracts; no source grant, original unit or GPU observation."""

from __future__ import annotations

import os
import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.embedding_gpu_control import parse_embedding_gpu_control
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow import embedding_batch_owner_control as wire
from jsonschema import Draft202012Validator

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_batch_plan import planning_case
from tests.unit.test_embedding_gpu_control import control_case

RELEASE = "a" * 40


def control_frames(*, request=None, batch=None, binding=None, expires_ns=None):
    planned = planning_case()
    request = request or parse_embedding_gpu_control(
        seal(
            planned.allocation.control_request.model_dump(mode="json")
            | {"expires_monotonic_ns": expires_ns or time.monotonic_ns() + 20 * 10**9},
            "message_sha256",
        )
    )
    batch, binding = batch or planned.batch, binding or planned.bound
    native = control_case()
    ready_claim = parse_embedding_gpu_control(
        seal(
            native[1].model_dump(mode="json")
            | {
                "allocation_attempt_id": request.allocation_attempt_id,
                "allocation_request_sha256": request.message_sha256,
            },
            "message_sha256",
        )
    )

    def frame(kind, **values):
        body = (
            dict(
                schema_version="embedding-batch-owner-control/1.0",
                message_type=kind,
                allocation_attempt_id=request.allocation_attempt_id,
                allocation_request_sha256=request.message_sha256,
                controller_release=RELEASE,
            )
            | values
        )
        return wire.parse_embedding_batch_owner_control(seal(body, "message_sha256"))

    ready = frame(
        "ROOT_READY",
        readiness=ready_claim.model_dump(mode="json"),
        unit_invocation_id="1" * 32,
        unit_started_monotonic=100,
        effective_policy_sha256="sha256:" + "1" * 64,
        observed_at="2026-10-24T19:00:00Z",
    )
    raw = canonical_json_bytes(batch.model_dump(mode="json"))
    bound = frame(
        "OWNER_BOUND",
        binding=binding.model_dump(mode="json"),
        ready_message_sha256=ready.message_sha256,
        input_raw_sha256=sha256_bytes(raw),
        input_byte_count=len(raw),
        owner_pid=os.getpid(),
        owner_start_ticks=12345,
    )
    check = frame(
        "ROOT_CHECK",
        batch_request_sha256=batch.request_sha256,
        child_request_sha256=batch.children[0].request.request_sha256,
        sequence=1,
    )
    checked = frame(
        "OWNER_CHECKED",
        batch_request_sha256=check.batch_request_sha256,
        child_request_sha256=check.child_request_sha256,
        sequence=1,
        check_message_sha256=check.message_sha256,
    )
    grant = parse_embedding_gpu_control(
        seal(
            native[3].model_dump(mode="json")
            | {
                "allocation_attempt_id": request.allocation_attempt_id,
                "allocation_request_sha256": request.message_sha256,
                "ready_message_sha256": ready_claim.message_sha256,
                "routing_decision_sha256": batch.routing_decision_sha256,
                "batch_request_sha256": batch.request_sha256,
                "batch_input_raw_sha256": bound.input_raw_sha256,
                "batch_input_byte_count": bound.input_byte_count,
            },
            "message_sha256",
        )
    )
    completed = frame(
        "ROOT_COMPLETED",
        bound_message_sha256=bound.message_sha256,
        grant=grant.model_dump(mode="json"),
        unit_invocation_id=ready.unit_invocation_id,
        unit_exited_monotonic=200,
        retired_at="2026-10-24T19:00:01Z",
        result_raw_sha256="sha256:" + "2" * 64,
        result_sha256="sha256:" + "3" * 64,
        result_byte_count=512,
        vectors_sha256="sha256:" + "4" * 64,
        vectors_byte_count=batch.expected_vector_bytes,
    )
    ack = frame(
        "OWNER_ACK",
        completion_message_sha256=completed.message_sha256,
        evidence_state="RECEIVED_NOT_CANONICAL_PUBLICATION",
    )
    busy_claim = parse_embedding_gpu_control(
        seal(
            native[2].model_dump(mode="json")
            | {
                "allocation_attempt_id": request.allocation_attempt_id,
                "allocation_request_sha256": request.message_sha256,
            },
            "message_sha256",
        )
    )
    busy = frame(
        "ROOT_BUSY",
        allocation=busy_claim.model_dump(mode="json"),
        unit_invocation_id="1" * 32,
        unit_started_monotonic=100,
        unit_exited_monotonic=200,
        retired_at="2026-10-24T19:00:01Z",
    )
    return SimpleNamespace(
        request=request,
        batch=batch,
        binding=binding,
        frame=frame,
        raw=raw,
        ready=ready,
        bound=bound,
        check=check,
        checked=checked,
        completed=completed,
        ack=ack,
        busy=busy,
    )


def test_schema_pinned_mirrored_isolated_202012():
    root = Path(__file__).resolve().parents[2]
    name = "embedding-batch-owner-control-v1.schema.json"
    raw = (root / "schemas/workflow" / name).read_bytes()
    assert raw == (root / "packages/workflow/eom_workflow/resources" / name).read_bytes()
    assert sha256_bytes(raw) == wire.BATCH_OWNER_CONTROL_SCHEMA_SHA256
    schema = wire.embedding_batch_owner_control_schema()
    Draft202012Validator.check_schema(schema)
    schema.clear()
    assert wire.embedding_batch_owner_control_schema()["$id"] == wire.BATCH_OWNER_CONTROL_SCHEMA_REF


@pytest.mark.parametrize("kind", ("ready", "bound", "check", "checked", "completed", "ack", "busy"))
def test_canonical_round_trip_and_original_request_release_context(kind):
    value = control_frames()
    frame = getattr(value, kind)
    raw = wire.embedding_batch_owner_control_bytes(frame)
    assert len(raw) < wire.MAX_BATCH_OWNER_CONTROL_BYTES
    assert wire.parse_embedding_batch_owner_control_bytes(raw) == frame
    wire.validate_embedding_batch_owner_context(value.request, RELEASE, frame)
    with pytest.raises(ValueError):
        wire.validate_embedding_batch_owner_context(value.request, "b" * 40, frame)
    with pytest.raises(ValueError):
        wire.parse_embedding_batch_owner_control_bytes(raw + b"\n")
    with pytest.raises(ValueError):
        wire.parse_embedding_batch_owner_control(
            frame.model_copy(update={"message_sha256": "sha256:" + "f" * 64})
        )


@pytest.mark.parametrize("kind", ("ready", "bound", "check", "checked", "completed", "ack", "busy"))
@pytest.mark.parametrize("field", ("role", "path", "vectors", "token", "extra"))
def test_undeclared_authority_paths_payloads_or_other_fields_are_rejected(kind, field):
    value = getattr(control_frames(), kind).model_dump(mode="json")
    with pytest.raises(ValueError):
        wire.parse_embedding_batch_owner_control(
            seal(value | {field: "not-allowed"}, "message_sha256")
        )


@pytest.mark.parametrize(
    "field,value",
    (("sequence", True), ("sequence", 0), ("sequence", 353), ("child_request_sha256", "latest")),
)
def test_check_fields_strict_and_bounded(field, value):
    body = control_frames().check.model_dump(mode="json")
    with pytest.raises(ValueError):
        wire.parse_embedding_batch_owner_control(seal(body | {field: value}, "message_sha256"))


def test_noncanonical_duplicate_and_oversize_documents_are_rejected():
    raw = wire.embedding_batch_owner_control_bytes(control_frames().check)
    for invalid in (
        b'{"message_type":"ROOT_CHECK",' + raw[1:],
        b'"' + b"x" * wire.MAX_BATCH_OWNER_CONTROL_BYTES + b'"',
        raw.replace(b'"sequence":1', b'"sequence":1.0'),
    ):
        with pytest.raises(ValueError):
            wire.parse_embedding_batch_owner_control_bytes(invalid)


@pytest.mark.parametrize("kind", ("ready", "busy", "completed"))
def test_inner_native_frame_cannot_refer_to_another_original_allocation(kind):
    value = control_frames()
    document = deepcopy(getattr(value, kind).model_dump(mode="json"))
    field = {"ready": "readiness", "busy": "allocation", "completed": "grant"}[kind]
    document[field] = seal(
        document[field] | {"allocation_request_sha256": "sha256:" + "f" * 64}, "message_sha256"
    )
    parsed = wire.parse_embedding_batch_owner_control(seal(document, "message_sha256"))
    with pytest.raises(ValueError):
        wire.validate_embedding_batch_owner_context(value.request, RELEASE, parsed)
