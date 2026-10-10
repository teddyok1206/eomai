"""Synthetic wire values, not actual source authorization or member-read evidence."""

from __future__ import annotations

from typing import Any

from eom_catalog_contracts.inference_transfer_invocation import (
    TRANSFER_RESULT_MEMBER_SCHEMA,
    InferenceTransferPairSubmitRequest,
    InferenceTransferWorkflowReadRequest,
    InferenceTransferWorkflowReadResult,
)
from eom_catalog_contracts.inference_transfer_workflow_binding import (
    InferenceTransferWorkflowBindingReply,
    InferenceTransferWorkflowBindingRequest,
)
from eom_identifiers import content_sha256

from tests.unit.inference_transfer_fixtures import request, result
from tests.unit.inference_transfer_snapshot_fixtures import hashed, snapshot_prepare_result

WORKFLOW_ID = "workflow_" + "1" * 32
ACTOR_ID = "operator_" + "a" * 32


def submit_request() -> InferenceTransferPairSubmitRequest:
    header = snapshot_prepare_result().header
    return hashed(
        InferenceTransferPairSubmitRequest,
        "submission_sha256",
        comparison=request(),
        snapshot_prepare=header.prepare,
        expected_header_sha256=header.header_sha256,
    )


def read_request(
    mode: str = "CANONICAL_RESULT", workflow_id: str = WORKFLOW_ID
) -> InferenceTransferWorkflowReadRequest:
    return hashed(
        InferenceTransferWorkflowReadRequest,
        "read_sha256",
        workflow_id=workflow_id,
        mode=mode,
    )


def role_result_document() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "protocol_version": "workflow-role/1.29.0",
        "job_id": "job_" + "2" * 32,
        "workflow_id": WORKFLOW_ID,
        "step_run_id": "steprun_" + "3" * 32,
        "status": "ok",
        "artifact": {
            "logical_artifact_id": "artifact_" + "4" * 32,
            "revision_id": "rev_" + "5" * 32,
            "file_name": "result.json",
            "media_type": "application/json",
        },
        "completed_at": "2026-10-10T09:00:00Z",
        "role": "support",
        "output": result().model_dump(mode="json"),
    }


def read_result(
    state: str = "COMPLETED", *, verified: bool = True
) -> InferenceTransferWorkflowReadResult:
    prepare = snapshot_prepare_result().header.prepare
    completed = state == "COMPLETED"
    pointer = {
        "artifact_id": "artifact_" + "4" * 32,
        "artifact_revision_id": "rev_" + "5" * 32,
        "member_path": "result.json",
        "schema_ref": TRANSFER_RESULT_MEMBER_SCHEMA,
        "media_type": "application/json",
        "sha256": content_sha256(role_result_document()),
    }
    return hashed(
        InferenceTransferWorkflowReadResult,
        "result_sha256",
        workflow_id=WORKFLOW_ID,
        workflow_state=state,
        resource_version=2,
        comparison=request(),
        graph_snapshot=prepare.graph_snapshot,
        access_policy_revision_id=prepare.access_policy_revision_id,
        access_policy_sha256=prepare.access_policy_sha256,
        result_state=("MEMBER_VERIFIED" if verified else "POINTER_ONLY")
        if completed
        else "PENDING"
        if state in {"REQUESTED", "RUNNING"}
        else "NO_RESULT",
        result_artifact=pointer if completed else None,
        result=result() if completed and verified else None,
        failure_code="WORKER_RESULT_INVALID" if state == "FAILED" else None,
    )


def binding_pair(
    *, mode: str = "CANONICAL_RESULT", state: str = "COMPLETED"
) -> tuple[InferenceTransferWorkflowBindingRequest, InferenceTransferWorkflowBindingReply]:
    query = hashed(
        InferenceTransferWorkflowBindingRequest,
        "binding_sha256",
        actor_id=ACTOR_ID,
        request=read_request(mode),
    )
    reply = hashed(
        InferenceTransferWorkflowBindingReply,
        "reply_sha256",
        actor_id=ACTOR_ID,
        request_binding_sha256=query.binding_sha256,
        status="SUCCESS",
        result=read_result(state, verified=mode == "CANONICAL_RESULT"),
        error_code=None,
    )
    return query, reply


def rehash(value: dict[str, Any], hash_field: str) -> dict[str, Any]:
    body = {key: child for key, child in value.items() if key != hash_field}
    return body | {hash_field: content_sha256(body)}
