from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from eom_workflow_runner.actor_authorization import WorkflowActorAuthorizer
from eom_workflow_runner.catalog_port import WorkflowCatalogPort
from eom_workflow_runner.engine import WorkflowRunner
from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.models import WorkflowCommandRecord
from eom_workflow_runner.readiness import WorkflowExecutionReadiness
from eom_workflow_runner.repository import (
    CommandLeaseIdentity,
    claim_next_command,
    command_lease_identity,
    renew_command_lease,
    require_command_lease,
)
from eom_workflow_runner.settings import WorkflowSettings
from eom_workflow_runner.state_machine import CommandState, transition_command
from sqlalchemy import create_engine


class _ScalarResult:
    def __init__(self, value: WorkflowCommandRecord) -> None:
        self._value = value

    def scalar_one_or_none(self) -> WorkflowCommandRecord:
        return self._value


class _Session:
    def __init__(self, command: WorkflowCommandRecord) -> None:
        self.command = command
        self.flush_count = 0

    def execute(self, _query: object) -> _ScalarResult:
        return _ScalarResult(self.command)

    def flush(self) -> None:
        self.flush_count += 1


def _command() -> WorkflowCommandRecord:
    return WorkflowCommandRecord(
        command_id="wfcmd_" + "1" * 32,
        workflow_id="workflow_" + "2" * 32,
        command_type="START_WORKFLOW",
        payload={},
        actor_type="human",
        actor_id="operator_" + "3" * 32,
        source="api",
        idempotency_key="fencing-unit-test",
        request_hash="sha256:" + "4" * 64,
        state=CommandState.PENDING.value,
        attempts=0,
        lease_generation=0,
        available_at=datetime.now(UTC) - timedelta(seconds=1),
    )


def test_reclaim_uses_a_new_token_and_monotonic_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokens = iter(("a" * 32, "b" * 32))
    monkeypatch.setattr("eom_workflow_runner.repository.secrets.token_hex", lambda _n: next(tokens))
    command = _command()
    session = _Session(command)

    first = claim_next_command(
        session,  # type: ignore[arg-type]
        runner_id="runner-one",
        lease_seconds=60,
    )
    assert first is command
    first_identity = command_lease_identity(command)
    assert first_identity.lease_token == "wflease_" + "a" * 32
    assert first_identity.lease_generation == 1

    transition_command(command, CommandState.PROCESSING)
    command.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    second = claim_next_command(
        session,  # type: ignore[arg-type]
        runner_id="runner-two",
        lease_seconds=60,
    )
    assert second is command
    second_identity = command_lease_identity(command)
    assert second_identity.lease_token == "wflease_" + "b" * 32
    assert second_identity.lease_generation == 2
    assert second_identity != first_identity

    with pytest.raises(WorkflowError) as stale:
        require_command_lease(session, first_identity)  # type: ignore[arg-type]
    assert stale.value.code is WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT
    assert require_command_lease(session, second_identity) is command  # type: ignore[arg-type]


def test_renewal_requires_the_exact_unexpired_claim() -> None:
    command = _command()
    session = _Session(command)
    command.state = CommandState.PROCESSING.value
    command.lease_owner = "runner-one"
    command.lease_token = "wflease_" + "a" * 32
    command.lease_generation = 7
    command.lease_expires_at = datetime.now(UTC) + timedelta(seconds=30)
    identity = command_lease_identity(command)
    before = command.lease_expires_at

    renewed = renew_command_lease(
        session,  # type: ignore[arg-type]
        identity,
        lease_seconds=60,
    )
    assert renewed > before
    assert command.lease_expires_at == renewed

    command.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(WorkflowError) as expired:
        renew_command_lease(session, identity, lease_seconds=60)  # type: ignore[arg-type]
    assert expired.value.code is WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT


def test_heartbeat_renews_and_fences_each_runner_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner_config = tmp_path / "workflow-runner.yaml"
    runner_config.write_text(
        "version: 1\npoll_interval_seconds: 1\ncommand_lease_seconds: 10\n"
        "command_lease_heartbeat_seconds: 1\nmax_commands_per_run: 1\n",
        encoding="utf-8",
    )
    engine = create_engine("sqlite://")
    runner = WorkflowRunner(
        engine,
        WorkflowSettings(runner_config_path=runner_config),
        catalog=cast(WorkflowCatalogPort, object()),
        actor_authorizer=cast(WorkflowActorAuthorizer, object()),
        readiness=cast(WorkflowExecutionReadiness, object()),
        available_roles=frozenset({"authoring"}),
    )
    lease = CommandLeaseIdentity(
        command_id="wfcmd_" + "1" * 32,
        runner_id="runner-one",
        lease_token="wflease_" + "2" * 32,
        lease_generation=3,
    )
    renewals: list[CommandLeaseIdentity] = []
    fences: list[bool] = []

    @contextmanager
    def fake_transaction(_factory: object) -> Iterator[object]:
        yield _Session(_command())

    def fake_renew(
        _session: object,
        identity: CommandLeaseIdentity,
        *,
        lease_seconds: int,
        observed_at: datetime | None = None,
    ) -> datetime:
        del observed_at
        assert lease_seconds == 10
        renewals.append(identity)
        return datetime.now(UTC) + timedelta(seconds=lease_seconds)

    def fake_require(
        _session: object,
        identity: CommandLeaseIdentity,
        *,
        observed_at: datetime | None = None,
        for_update: bool = False,
    ) -> WorkflowCommandRecord:
        del observed_at
        assert identity is lease
        fences.append(for_update)
        return _command()

    monkeypatch.setattr("eom_workflow_runner.engine.transaction", fake_transaction)
    monkeypatch.setattr("eom_workflow_runner.engine.renew_command_lease", fake_renew)
    monkeypatch.setattr("eom_workflow_runner.engine.require_command_lease", fake_require)

    with runner._command_lease_scope(lease):
        with runner._fenced_transaction():
            pass
        deadline = time.monotonic() + 2
        while len(renewals) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)

    assert renewals == [lease, lease]
    assert fences == [False, True, True]
    engine.dispose()
