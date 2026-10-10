"""Stable read port implemented by the private Catalog transport adapter."""

from __future__ import annotations

from typing import Protocol

from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotRequest,
    InferenceTransferSnapshotResult,
)


class InferenceTransferSnapshotReadError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class InferenceTransferSnapshotReadPort(Protocol):
    def execute(
        self, actor_id: str, request: InferenceTransferSnapshotRequest
    ) -> InferenceTransferSnapshotResult: ...
