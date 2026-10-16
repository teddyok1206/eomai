"""Synthetic SQL/loop tests; no live authority, claims, model or database mutation."""

from unittest.mock import MagicMock, Mock

import pytest
from eom_workflow_runner import native_cpu_scheduling_read as scheduling
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError


@pytest.mark.parametrize("value", [True, False])
def test_one_scalar_exists_query_returns_only_current_work_presence(value):
    session = Mock()
    session.scalar.return_value = value
    assert scheduling.active_reference_query_command_exists(session) is value
    session.scalar.assert_called_once()
    statement = session.scalar.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "EXISTS" in sql and "JOIN workflow_instances" in sql
    assert "workflow_id = workflow_commands.workflow_id" in sql
    assert "lease_expires_at > CURRENT_TIMESTAMP" in sql
    assert "lease_token IS NOT NULL" in sql and "lease_owner IS NOT NULL" in sql
    assert "lease_generation >" in sql and "attempts >" in sql
    assert compiled.params["state_1"] == ["LEASED", "PROCESSING"]
    assert compiled.params["command_type_1"] == ["START_WORKFLOW", "ADVANCE_WORKFLOW"]
    assert "local-embedding-reference-query" in compiled.params.values()
    assert "RUNNING" in compiled.params.values() and "human" in compiled.params.values()
    assert "actor_id = workflow_instances.created_actor_id" in sql
    for forbidden in (
        "initial_request",
        "payload",
        "SELECT *",
        "FOR UPDATE",
        "FOR SHARE",
        "INSERT",
        "UPDATE ",
        "DELETE",
    ):
        assert forbidden not in sql


@pytest.mark.parametrize("value", [None, 0, 1, "true", [], object()])
def test_unknown_scalar_is_not_assumed_idle(value):
    session = Mock()
    session.scalar.return_value = value
    with pytest.raises(scheduling.NativeCpuSchedulingReadUnavailable):
        scheduling.active_reference_query_command_exists(session)


def test_short_read_only_transaction_closes_before_decision_delivery(monkeypatch):
    session = MagicMock()
    session.scalar.return_value = True
    context = MagicMock()
    context.__enter__.return_value = session
    factory = Mock(return_value=context)
    monkeypatch.setattr(scheduling, "Session", factory)
    engine = object()
    assert scheduling.should_defer_background_cpu_claim(engine)
    factory.assert_called_once_with(engine)
    assert str(session.execute.call_args.args[0]) == "SET TRANSACTION READ ONLY"
    session.begin.assert_called_once()
    context.__exit__.assert_called_once()
    session.begin.return_value.__exit__.assert_called_once()
    session.add.assert_not_called()
    session.flush.assert_not_called()


@pytest.mark.parametrize("error", [SQLAlchemyError("private SQL details"), OSError("private path")])
def test_read_failure_is_safe_explicit_and_never_false_idle(monkeypatch, error):
    factory = Mock(side_effect=error)
    monkeypatch.setattr(scheduling, "Session", factory)
    with pytest.raises(scheduling.NativeCpuSchedulingReadUnavailable) as caught:
        scheduling.should_defer_background_cpu_claim(object())
    assert str(caught.value) == "NATIVE_CPU_SCHEDULING_READ_UNAVAILABLE"
