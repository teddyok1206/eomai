"""Reservation routing is independent of account health and never a synthetic lease."""

from datetime import UTC, datetime
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_orchestrator.chat_slot_reservation import (
    active_chat_slot_clause,
    ordinary_slot_allowed_clause,
    require_reserved_chat_admission,
    reserve_chat_slot,
)
from eom_orchestrator.general_chat_models import GeneralChatCapacityRecord
from eom_orchestrator.general_chat_state import ChatError
from eom_orchestrator.models import WorkerSlotRecord
from sqlalchemy import CheckConstraint, select
from sqlalchemy.dialects import postgresql


def sql(value):
    return str(value.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_reserved_slot_is_always_excluded_even_when_chat_is_idle_or_unhealthy():
    query = sql(
        select(WorkerSlotRecord.slot_id).where(
            ordinary_slot_allowed_clause(WorkerSlotRecord.slot_id)
        )
    )
    assert "NOT (EXISTS" in query and "general_chat_capacity.worker_slot_id" in query
    assert "heartbeat" not in query and "active_turn_id" not in query and "enabled" not in query


def test_unknown_expired_chat_execution_remains_busy():
    query = sql(
        select(WorkerSlotRecord.slot_id).where(active_chat_slot_clause(WorkerSlotRecord.slot_id))
    )
    assert "active_turn_id IS NOT NULL" in query
    assert "expires_at" not in query and "heartbeat" not in query


def test_reservation_schema_only_admits_reviewed_fixed_slot_and_preserves_legacy_null():
    table = GeneralChatCapacityRecord.__table__
    assert table.c.worker_slot_id.nullable
    assert {fk.target_fullname for fk in table.c.worker_slot_id.foreign_keys} == {
        "worker_slots.slot_id"
    }
    checks = {c.name: str(c.sqltext) for c in table.constraints if isinstance(c, CheckConstraint)}
    assert checks["ck_chat_reserved_worker_slot"] == "worker_slot_id IS NULL OR worker_slot_id='06'"


def test_historical_dedicated_claim_does_not_read_or_modify_six_slot_identity():
    session = Mock()
    assert (
        require_reserved_chat_admission(session, NS(worker_slot_id=None), now=datetime.now(UTC))
        is None
    )
    session.execute.assert_not_called()
    session.scalar.assert_not_called()


def test_fixed_reservation_replay_is_noop_and_never_changes_binding_state():
    capacity = NS(worker_slot_id="06")
    binding = NS(binding_id="authbinding_" + "a" * 32, state="DISABLED")
    session = Mock()
    session.scalar.side_effect = [binding, capacity]
    assert reserve_chat_slot(session) is False
    assert binding.state == "DISABLED"
    session.flush.assert_not_called()
    assert "pg_advisory_xact_lock" in sql(session.execute.call_args.args[0])


def test_unreviewed_slot_is_rejected_before_database_access():
    session = Mock()
    with pytest.raises(ChatError, match="GENERAL_CHAT_SLOT_INVALID"):
        reserve_chat_slot(session, worker_slot_id="05")
    session.execute.assert_not_called()


@pytest.mark.parametrize("changed", ["slot_id", "binding_id", "assignment_revision_id"])
def test_account_pin_changes_never_reuse_old_turn(changed):
    binding = NS(
        binding_id="authbinding_" + "a" * 32,
        current_assignment_revision_id="authassignrev_" + "b" * 32,
    )
    turn = NS(
        worker_slot_id="06",
        auth_binding_id=binding.binding_id,
        auth_assignment_revision_id=binding.current_assignment_revision_id,
    )
    setattr(
        turn,
        {
            "slot_id": "worker_slot_id",
            "binding_id": "auth_binding_id",
            "assignment_revision_id": "auth_assignment_revision_id",
        }[changed],
        "changed",
    )
    session = Mock()
    session.execute.return_value.one_or_none.return_value = binding
    with pytest.raises(ChatError, match="GENERAL_CHAT_NOT_READY"):
        require_reserved_chat_admission(
            session, NS(worker_slot_id="06"), now=datetime.now(UTC), model="test-model", turn=turn
        )
    session.scalar.assert_not_called()


def test_chat_preparation_checks_exact_model_with_select_only_binding_access():
    binding = NS(
        binding_id="authbinding_" + "a" * 32,
        current_assignment_revision_id="authassignrev_" + "b" * 32,
    )
    turn = NS(
        worker_slot_id="06",
        auth_binding_id=binding.binding_id,
        auth_assignment_revision_id=binding.current_assignment_revision_id,
    )
    session = Mock()
    session.execute.return_value.one_or_none.return_value = binding
    session.scalar.return_value = "capsnap_" + "c" * 32
    require_reserved_chat_admission(
        session,
        NS(worker_slot_id="06"),
        now=datetime.now(UTC),
        model="exact-reviewed-model",
        turn=turn,
    )
    query = sql(session.scalar.call_args.args[0])
    assert "exact-reviewed-model" in query and "AVAILABLE" in query
    assert "latest_binding_capability" in query and "assigned_at" in query
    assert "FOR UPDATE" not in sql(session.execute.call_args.args[0])
