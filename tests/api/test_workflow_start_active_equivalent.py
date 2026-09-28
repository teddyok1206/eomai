from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from eom_api.services.command_adapter import CommandAdapter
from eom_operator_identity import ActorContext, ActorSource, ActorType, PermissionKey


class _Session:
    def __init__(self, command: object) -> None:
        self.command = command

    def scalar(self, _statement: object) -> object:
        return self.command


def test_active_equivalent_returns_its_existing_start_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = SimpleNamespace(command_id="wfcmd_" + "1" * 32)
    workflow = SimpleNamespace(workflow_id="workflow_" + "2" * 32, lock_version=7)
    definition = SimpleNamespace(definition_hash="sha256:" + "3" * 64)
    workflow_request = SimpleNamespace(
        educational_retrieval=None,
        expected_resolution=None,
        content_pack=None,
        execution_preset_key=None,
    )
    adapter = object.__new__(CommandAdapter)
    adapter.sessions = lambda: _Session(command)  # type: ignore[assignment]
    adapter._workflow_start_replay = lambda *args, **kwargs: None  # type: ignore[method-assign]
    adapter._require_expected_definition = lambda *args, **kwargs: None  # type: ignore[method-assign]

    @contextmanager
    def fake_transaction(_sessions: object) -> Iterator[_Session]:
        yield _Session(command)

    monkeypatch.setattr(
        "eom_api.services.command_adapter._workflow_request_from_api",
        lambda _request: workflow_request,
    )
    monkeypatch.setattr(
        "eom_api.services.command_adapter.admitted_workflow_definition",
        lambda *_args, **_kwargs: definition,
    )
    monkeypatch.setattr(
        "eom_api.services.command_adapter.create_workflow_instance",
        lambda *_args, **_kwargs: (workflow, False),
    )
    monkeypatch.setattr("eom_api.services.command_adapter.transaction", fake_transaction)
    actor = ActorContext(
        actor_type=ActorType.OPERATOR,
        operator_id="operator_" + "4" * 32,
        session_id="apisession_" + "5" * 32,
        request_id="request_" + "6" * 32,
        authentication_time=datetime(2026, 9, 28, 17, 30, tzinfo=UTC),
        permissions=frozenset(PermissionKey),
        source=ActorSource.APPLICATION_API,
    )
    request: Any = SimpleNamespace(
        definition_key="generic-item-development", definition_version="1.13.0"
    )

    assert adapter.start_workflow(
        request,
        actor,
        idempotency_key="api:" + "7" * 64,
    ) == (command.command_id, workflow.workflow_id, workflow.lock_version)
