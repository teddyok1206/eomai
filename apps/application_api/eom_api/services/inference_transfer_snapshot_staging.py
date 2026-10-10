"""Adapt a captured API principal to the pure Orchestrator staging read port."""

from __future__ import annotations

from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotRequest,
    InferenceTransferSnapshotResult,
)
from eom_identity_service.tokens import AccessAuthentication
from eom_orchestrator.inference_transfer_snapshot_staging import SnapshotReadFailure

from eom_api.errors import ApiError
from eom_api.services.inference_transfer_snapshot import InferenceTransferSnapshotApplicationService


class AuthenticatedApiSnapshotStagingAdapter:
    """Only the supported caller captures authentication; actor strings cannot grant it."""

    def __init__(
        self,
        authentication: AccessAuthentication,
        snapshots: InferenceTransferSnapshotApplicationService,
    ) -> None:
        self.authentication = authentication
        self.snapshots = snapshots

    def execute(
        self, actor_id: str, request: InferenceTransferSnapshotRequest
    ) -> InferenceTransferSnapshotResult:
        if actor_id != self.authentication.operator.operator_id:
            raise SnapshotReadFailure("INFERENCE_TRANSFER_FORBIDDEN")
        try:
            return self.snapshots.execute(self.authentication, request)
        except ApiError as exc:
            code = (
                "INFERENCE_TRANSFER_FORBIDDEN"
                if exc.error_code == "PERMISSION_DENIED"
                else exc.error_code
            )
            raise SnapshotReadFailure(code) from exc
