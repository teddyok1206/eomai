"""Concrete root GPU driver/source-owner bridge; only the existing owner reads data or commits."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from eom_catalog_contracts.embedding_gpu_control import EmbeddingGpuAllocationRequest
from eom_catalog_contracts.embedding_work_batch import SupportedEmbeddingWorkBatchInput
from eom_identifiers import content_sha256
from eom_orchestrator.inference_transfer_cpu_handoff import fixed_owner_identity
from eom_workflow.embedding_batch_owner_control import (
    EmbeddingBatchOwnerBound,
    EmbeddingBatchRootBusy,
    EmbeddingBatchRootCompleted,
    EmbeddingBatchRootReady,
)

from eom_catalog_service.embedding_batch_owner_channel import EmbeddingBatchOwnerChannel
from eom_catalog_service.embedding_batch_owner_identity import embedding_batch_owner_start_ticks
from eom_catalog_service.embedding_batch_owner_workspace import (
    StagedOwnerEmbeddingBatch,
    read_owner_embedding_batch,
)
from eom_catalog_service.embedding_gpu_batch_controller import (
    CompletedEmbeddingGpuBatch,
    UnavailableEmbeddingGpuBatch,
    run_embedding_gpu_batch,
)
from eom_catalog_service.embedding_gpu_batch_observation import (
    CapturedEmbeddingGpuBatchMachine,
    EmbeddingGpuBatchReadyObservation,
)


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("EMBEDDING_BATCH_OWNER_PROXY_INVALID")


class RootEmbeddingBatchOwnerProxy:
    """The GPU driver calls this source port over the original actual owner's socket.

    No DB, NAS, authentication or source resolution occurs as root. The actual
    owner handler retains its original session/service authority and exact child
    lease bindings. A disconnected owner never supplies permission to recompute.
    """

    def __init__(
        self,
        captured: CapturedEmbeddingGpuBatchMachine,
        channel: EmbeddingBatchOwnerChannel,
        *,
        owner_start_ticks: int,
    ) -> None:
        _require(
            os.getresuid() == (0, 0, 0)
            and os.getresgid() == (0, 0, 0)
            and type(captured) is CapturedEmbeddingGpuBatchMachine
            and type(channel) is EmbeddingBatchOwnerChannel
            and channel.side == "ROOT"
            and channel.request == captured.prepared.request
            and type(owner_start_ticks) is int
            and 0 < owner_start_ticks < 2**63
        )
        captured.assert_precompute()
        self._captured, self._channel = captured, channel
        self._peer = channel.require_direct_peer()
        owner = fixed_owner_identity()
        _require(self._peer.uid == owner.owner_uid and self._peer.gid == owner.owner_gid)
        self._owner_birth = owner_start_ticks
        self._ready: EmbeddingBatchRootReady | None = None
        self._bound: StagedOwnerEmbeddingBatch | None = None
        self._finished = False
        self._fence()

    def _fence(self) -> None:
        _require(
            not self._finished
            and os.getresuid() == (0, 0, 0)
            and os.getresgid() == (0, 0, 0)
            and self._channel.require_direct_peer() == self._peer
            and embedding_batch_owner_start_ticks(
                self._peer.pid, uid=self._peer.uid, gid=self._peer.gid
            )
            == self._owner_birth
        )
        # The actual GPU controller owns installation/retirement proofs. Rewalking
        # the sealed numerical prefix on every child RPC would be O(files * checks).
        if self._bound is not None:
            self._bound.assert_current()

    def _body(self, kind: str, values: dict[str, Any]) -> dict[str, Any]:
        request = self._captured.prepared.request
        body = (
            dict(
                schema_version="embedding-batch-owner-control/1.0",
                message_type=kind,
                allocation_attempt_id=request.allocation_attempt_id,
                allocation_request_sha256=request.message_sha256,
                controller_release=self._channel.controller_release,
            )
            | values
        )
        return body | {"message_sha256": content_sha256(body)}

    def admit_allocation(
        self, request: EmbeddingGpuAllocationRequest, ready: EmbeddingGpuBatchReadyObservation
    ) -> SupportedEmbeddingWorkBatchInput:
        self._fence()
        _require(
            self._ready is None
            and self._bound is None
            and request == self._captured.prepared.request
            and type(ready) is EmbeddingGpuBatchReadyObservation
            and ready.unit.main_pid == ready.readiness.pid
        )
        notice = EmbeddingBatchRootReady.model_validate(
            self._body(
                "ROOT_READY",
                dict(
                    readiness=ready.readiness.model_dump(mode="json"),
                    unit_invocation_id=ready.unit.invocation_id,
                    unit_started_monotonic=ready.unit.status.exec_main_started_monotonic,
                    effective_policy_sha256=ready.effective_policy_sha256,
                    observed_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                ),
            )
        )
        self._ready = notice
        self._channel.send_ready(notice)
        bound = self._channel.receive_binding()
        _require(type(bound) is EmbeddingBatchOwnerBound)
        _require(bound.owner_pid == self._peer.pid and bound.owner_start_ticks == self._owner_birth)
        self._bound = read_owner_embedding_batch(request, bound)
        self._fence()
        return self._bound.batch

    def authorize_child(self, batch_request_sha256: str, child_request_sha256: str) -> None:
        self._fence()
        _require(self._bound is not None)
        self._channel.check_child(batch_request_sha256, child_request_sha256)
        self._fence()

    def completed(self, value: CompletedEmbeddingGpuBatch) -> None:
        self._fence()
        self._captured.assert_current()
        _require(
            type(value) is CompletedEmbeddingGpuBatch
            and self._bound is not None
            and self._ready is not None
        )
        assert self._bound is not None and self._ready is not None
        terminal = value.retirement.original_terminal
        claim = value.output_claim
        # PID1 may clear current InvocationID after verified retirement. The
        # emitted immutable identity still comes from the original terminal.
        _require(
            value.batch == self._bound.batch
            and terminal.original_outcome == "SUCCEEDED"
            and terminal.ready.readiness == self._ready.readiness
            and terminal.terminal_unit.invocation_id == self._ready.unit_invocation_id
            and value.retirement.retired_unit.invocation_id in {"", self._ready.unit_invocation_id}
            and value.retirement.retired_unit.stored_descriptors == 0
            and claim.batch_request_sha256 == value.batch.request_sha256
            and claim.grant_message_sha256 == value.grant.message_sha256
            and claim.result_sha256 == value.result.result_sha256
        )
        completed = EmbeddingBatchRootCompleted.model_validate(
            self._body(
                "ROOT_COMPLETED",
                dict(
                    bound_message_sha256=self._bound.notice.message_sha256,
                    grant=value.grant.model_dump(mode="json"),
                    unit_invocation_id=terminal.terminal_unit.invocation_id,
                    unit_exited_monotonic=terminal.terminal_unit.exited_monotonic,
                    retired_at=value.retirement.observed_at_utc,
                    result_raw_sha256=claim.result_raw_sha256,
                    result_sha256=claim.result_sha256,
                    result_byte_count=claim.result_byte_count,
                    vectors_sha256=claim.vectors_sha256,
                    vectors_byte_count=claim.vectors_byte_count,
                ),
            )
        )
        self._channel.send_completed(completed)
        self._finished = True

    def unavailable(self, value: UnavailableEmbeddingGpuBatch) -> None:
        self._fence()
        self._captured.assert_precompute()
        _require(
            type(value) is UnavailableEmbeddingGpuBatch
            and self._ready is None
            and self._bound is None
            and value.retired_unit.invocation_id in {"", value.original_unit.invocation_id}
            and value.retired_unit.stored_descriptors == 0
        )
        busy = EmbeddingBatchRootBusy.model_validate(
            self._body(
                "ROOT_BUSY",
                dict(
                    allocation=value.allocation.model_dump(mode="json"),
                    unit_invocation_id=value.original_unit.invocation_id,
                    unit_started_monotonic=value.original_unit.status.exec_main_started_monotonic,
                    unit_exited_monotonic=value.original_unit.exited_monotonic,
                    retired_at=value.observed_at_utc,
                ),
            )
        )
        self._channel.send_busy(busy)
        self._finished = True


def run_embedding_gpu_batch_with_owner(
    captured: CapturedEmbeddingGpuBatchMachine,
    channel: EmbeddingBatchOwnerChannel,
    *,
    owner_start_ticks: int,
) -> CompletedEmbeddingGpuBatch | UnavailableEmbeddingGpuBatch:
    """One original actual root lifecycle through the mandatory source-owner proxy."""
    try:
        proxy = RootEmbeddingBatchOwnerProxy(captured, channel, owner_start_ticks=owner_start_ticks)
        result = run_embedding_gpu_batch(captured, source_owner=proxy)
        if isinstance(result, CompletedEmbeddingGpuBatch):
            proxy.completed(result)
        else:
            proxy.unavailable(result)
        return result
    finally:
        channel.close()
