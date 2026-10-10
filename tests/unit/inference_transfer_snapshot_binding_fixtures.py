"""Synthetic private-boundary values, never a source authorization credential."""

from __future__ import annotations

from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotAuthorizeRequest,
    InferenceTransferSnapshotAuthorizeResult,
    snapshot_baseline_set_sha256,
    snapshot_entry_set_sha256,
)
from eom_catalog_contracts.inference_transfer_snapshot_binding import (
    InferenceTransferSnapshotBindingReply,
    InferenceTransferSnapshotBindingRequest,
)

from tests.unit.inference_transfer_snapshot_fixtures import (
    hashed,
    snapshot_prepare_result,
    snapshot_read_request,
    snapshot_read_result,
)


def binding_pair(
    phase: str = "PREPARE",
) -> tuple[InferenceTransferSnapshotBindingRequest, InferenceTransferSnapshotBindingReply]:
    prepared = snapshot_prepare_result()
    if phase == "PREPARE":
        return (
            InferenceTransferSnapshotBindingRequest(
                actor_id=prepared.header.actor_id, request=prepared.header.prepare
            ),
            InferenceTransferSnapshotBindingReply(
                status="SUCCESS", result=prepared, error_code=None
            ),
        )
    read_request = snapshot_read_request(prepared)
    read_result = snapshot_read_result(request=read_request)
    if phase == "READ":
        return (
            InferenceTransferSnapshotBindingRequest(
                actor_id=prepared.header.actor_id, request=read_request
            ),
            InferenceTransferSnapshotBindingReply(
                status="SUCCESS", result=read_result, error_code=None
            ),
        )
    authorize_request = hashed(
        InferenceTransferSnapshotAuthorizeRequest,
        "authorization_sha256",
        header=prepared.header,
        staged_entry_set_sha256=snapshot_entry_set_sha256(
            tuple(
                record.staged_entry
                for record in read_result.records
                if record.staged_entry is not None
            )
        ),
        staged_baseline_set_sha256=snapshot_baseline_set_sha256(read_result.baselines),
    )
    authorize_result = hashed(
        InferenceTransferSnapshotAuthorizeResult,
        "result_sha256",
        header_sha256=prepared.header.header_sha256,
        authorization_sha256=authorize_request.authorization_sha256,
        source_count=prepared.header.source_count,
        profile_count=prepared.header.profile_count,
        missing_report_count=prepared.header.missing_report_count,
        staged_entry_set_sha256=authorize_request.staged_entry_set_sha256,
        staged_baseline_set_sha256=authorize_request.staged_baseline_set_sha256,
    )
    return (
        InferenceTransferSnapshotBindingRequest(
            actor_id=prepared.header.actor_id, request=authorize_request
        ),
        InferenceTransferSnapshotBindingReply(
            status="SUCCESS", result=authorize_result, error_code=None
        ),
    )
