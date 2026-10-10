"""Authenticated comparison submission and purpose-specific owner reads."""

from __future__ import annotations

from typing import Annotated

from eom_api_contracts import CommandResult, SingleResponse
from eom_api_contracts.inference_transfer import (
    InferenceTransferPairSubmitRequest,
    InferenceTransferWorkflowReadRequest,
    InferenceTransferWorkflowReadResult,
)
from eom_catalog_contracts.inference_transfer_invocation import InferenceTransferWorkflowReadMode
from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotRequest,
    InferenceTransferSnapshotResult,
)
from eom_identifiers import content_sha256
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Query, Request
from pydantic import ValidationError

from eom_api.dependencies import Auth, IdempotencyKey, require_permission
from eom_api.errors import ApiError
from eom_api.routers.common import one, run_command

router = APIRouter(tags=["inference-transfer"])


@router.post(
    "/knowledge/inference-transfer/snapshot",
    operation_id="inference_transfer_snapshot_read",
    response_model=SingleResponse[InferenceTransferSnapshotResult],
    dependencies=[Depends(require_permission(PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE))],
    openapi_extra={
        "x-eom-read-only": True,
        "x-eom-additional-permissions": [
            PermissionKey.ITEM_READ.value,
            PermissionKey.KNOWLEDGE_ANALYSIS_READ.value,
        ],
        "x-eom-conditional-permissions": {"PAST_EXAM": [PermissionKey.CONTENT_INTAKE_READ.value]},
    },
)
def read_snapshot(
    request: Request,
    body: InferenceTransferSnapshotRequest,
    authentication: Auth,
) -> SingleResponse[InferenceTransferSnapshotResult]:
    return one(
        request,
        request.app.state.services.inference_transfer_snapshots.execute(authentication, body),
    )


@router.post(
    "/knowledge/inference-transfer/comparisons",
    operation_id="inference_transfer_pair_submit",
    status_code=202,
    response_model=SingleResponse[CommandResult],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_START))],
    openapi_extra={
        "x-eom-additional-permissions": [
            PermissionKey.ITEM_READ.value,
            PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE.value,
            PermissionKey.KNOWLEDGE_ANALYSIS_READ.value,
        ],
        "x-eom-conditional-permissions": {"PAST_EXAM": [PermissionKey.CONTENT_INTAKE_READ.value]},
    },
)
def submit_pair(
    request: Request,
    body: InferenceTransferPairSubmitRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[CommandResult]:
    services = request.app.state.services
    # run_command returns cached success before its callback. Current source
    # resolution must therefore precede the HTTP claim/replay boundary.
    submission = services.inference_transfer_submissions.authorize_submission(authentication, body)

    def execute() -> CommandResult:
        actor = request.state.request_context.actor()
        key = services.idempotency.submission_key(
            operator_id=actor.actor_id,
            endpoint_key="inference_transfer_pair_submit",
            raw_key=idempotency_key,
        )
        command_id, workflow_id, version = services.inference_transfer_submissions.start(
            submission,
            actor,
            idempotency_key=key,
        )
        return CommandResult(
            command_id=command_id,
            resource_type="workflow",
            resource_id=workflow_id,
            status="ACCEPTED",
            resource_version=version,
            status_url=f"/api/v1/knowledge/inference-transfer/workflows/{workflow_id}",
        )

    return one(
        request,
        run_command(
            request,
            raw_key=idempotency_key,
            body=body.model_dump(mode="json"),
            resource_type="workflow",
            callback=execute,
            response_status=202,
        ),
    )


@router.get(
    "/knowledge/inference-transfer/workflows/{workflow_id}",
    operation_id="inference_transfer_workflow_read",
    response_model=SingleResponse[InferenceTransferWorkflowReadResult],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_READ))],
    openapi_extra={
        "x-eom-read-only": True,
        "x-eom-additional-permissions": [
            PermissionKey.ITEM_READ.value,
            PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE.value,
            PermissionKey.KNOWLEDGE_ANALYSIS_READ.value,
        ],
        "x-eom-conditional-permissions": {"PAST_EXAM": [PermissionKey.CONTENT_INTAKE_READ.value]},
    },
)
def read_comparison(
    request: Request,
    workflow_id: str,
    authentication: Auth,
    mode: Annotated[InferenceTransferWorkflowReadMode, Query()] = "STATUS_ONLY",
) -> SingleResponse[InferenceTransferWorkflowReadResult]:
    body = {
        "schema_version": "inference-transfer-workflow-read-request/1.0",
        "workflow_id": workflow_id,
        "mode": mode,
    }
    try:
        query = InferenceTransferWorkflowReadRequest.model_validate(
            body | {"read_sha256": content_sha256(body)}
        )
    except ValidationError as exc:
        raise ApiError(
            422,
            "INFERENCE_TRANSFER_WORKFLOW_REQUEST_INVALID",
            "Invalid comparison read",
            "An exact Workflow identity is required.",
        ) from exc
    return one(
        request,
        request.app.state.services.inference_transfer_workflow_reads.execute(
            authentication,
            query,
        ),
    )
