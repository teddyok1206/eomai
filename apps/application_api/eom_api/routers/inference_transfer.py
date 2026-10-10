"""Bounded authenticated comparison reads; no model execution or artifact writes."""

from __future__ import annotations

from eom_api_contracts import SingleResponse
from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotRequest,
    InferenceTransferSnapshotResult,
)
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Request

from eom_api.dependencies import Auth, require_permission
from eom_api.routers.common import one

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
