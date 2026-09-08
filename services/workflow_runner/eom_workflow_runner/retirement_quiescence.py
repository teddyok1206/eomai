"""Application port for proving that the Workflow runner cannot claim old commands."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

WORKFLOW_RUNNER_UNIT_NAME = "eom-workflow-runner.service"
WORKFLOW_RUNNER_FRAGMENT_PATH = "/etc/systemd/system/eom-workflow-runner.service"
WORKFLOW_RUNNER_DEPLOYMENT_HOLD_DIRECTORY = "/etc/systemd/system/eom-workflow-runner.service.d"
WORKFLOW_RUNNER_DEPLOYMENT_HOLD_PATH = (
    "/etc/systemd/system/eom-workflow-runner.service.d/zzzz-eom-deployment-hold.conf"
)
WORKFLOW_RUNNER_DEPLOYMENT_HOLD_SHA256 = (
    "sha256:d63c1155611f0305d4bcc99da04be6ab89811b7ec1b0abff93e1af118df056e0"
)


@dataclass(frozen=True)
class WorkflowRunnerQuiescenceEvidence:
    """Pinned system-service and hold snapshot used before retirement DB effects."""

    load_state: str
    active_state: str
    sub_state: str
    main_pid: int
    unit_file_state: str
    job: str
    fragment_path: str
    drop_in_paths: tuple[str, ...]
    refuse_manual_start: bool
    need_daemon_reload: bool
    hold_directory_path: str
    hold_directory_owner_uid: int
    hold_directory_group_gid: int
    hold_directory_mode: int
    hold_path: str
    hold_sha256: str
    hold_owner_uid: int
    hold_group_gid: int
    hold_mode: int


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
