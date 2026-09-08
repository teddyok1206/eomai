"""Application port for proving that the Workflow runner cannot claim old commands."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class WorkflowRunnerQuiescenceEvidence:
    """Small immutable system-service snapshot used before retirement DB effects."""

    active_state: str
    sub_state: str
    unit_file_state: str


class WorkflowRunnerQuiescencePort(Protocol):
    """Read-only boundary implemented by the host service-manager adapter."""

    def observe(self) -> WorkflowRunnerQuiescenceEvidence: ...


class ExpiredLeaseReconciliationPort(Protocol):
    """Orchestrator boundary for the exact cohort's expired worker leases."""

    def reconcile_expired_for_workflows(
        self,
        workflow_ids: tuple[str, ...],
        *,
        observed_at: datetime,
    ) -> tuple[object, ...]: ...
