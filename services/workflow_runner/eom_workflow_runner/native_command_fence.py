"""Per-root command acquisition witness shared by native INDEX and QUERY owners.

This mechanical fence is not Identity/source authority. Each owner independently
rechecks its actual caller and canonical sources before and after using it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from threading import get_ident
from weakref import WeakKeyDictionary

from sqlalchemy import select
from sqlalchemy.orm import Session, SessionTransaction

from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.models import WorkflowCommandRecord
from eom_workflow_runner.repository import (
    CommandLeaseIdentity,
    command_lease_identity,
    require_command_lease,
)
from eom_workflow_runner.state_machine import CommandState


@dataclass(frozen=True, slots=True)
class _AcquiredMutation:
    lease: CommandLeaseIdentity
    request_sha256: str
    initial_state: str
    thread_id: int


class NativeCommandMutationFence:
    """One immutable witness per live root; weak keys retain no session/authority."""

    def __init__(self) -> None:
        self._roots: WeakKeyDictionary[SessionTransaction, _AcquiredMutation] = WeakKeyDictionary()

    def acquire(
        self, session: Session, request_sha256: str, lease: CommandLeaseIdentity
    ) -> WorkflowCommandRecord:
        root = session.get_transaction()
        if not session.is_active or root is None or not root.is_active:
            raise WorkflowError(
                WorkflowErrorCode.ACTOR_AUTHORIZATION_UNAVAILABLE,
                "native mutation requires an active owner root",
            )
        witnessed = self._roots.get(root)
        command: WorkflowCommandRecord | None
        if witnessed is None:
            command = require_command_lease(session, lease, for_update=True)
            self._roots[root] = _AcquiredMutation(lease, request_sha256, command.state, get_ident())
            return command
        command = session.scalar(
            select(WorkflowCommandRecord)
            .where(WorkflowCommandRecord.command_id == lease.command_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            witnessed.lease != lease
            or witnessed.request_sha256 != request_sha256
            or witnessed.thread_id != get_ident()
            or command is None
            or (
                command.state not in {CommandState.LEASED.value, CommandState.PROCESSING.value}
                and not (
                    witnessed.initial_state == CommandState.PROCESSING.value
                    and command.state in {CommandState.SUCCEEDED.value, CommandState.FAILED.value}
                )
            )
        ):
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT,
                "native mutation lost its actual acquired command identity",
            )
        require_unexpired_native_command(command, lease)
        return command


def require_unexpired_native_command(
    command: WorkflowCommandRecord, lease: CommandLeaseIdentity
) -> None:
    """Late identity/wall-clock check, not a substitute for holding the row lock."""
    if (
        command_lease_identity(command) != lease
        or command.lease_expires_at is None
        or command.lease_expires_at <= datetime.now(UTC)
    ):
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT,
            "native command expired during current source admission",
        )
