"""The maintenance consumer claims only observations in a guarded disposable DB."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from eom_identity_service.models import OperatorRecord
from eom_orchestrator.control_commands import (
    build_codex_control_command,
    claim_next_codex_control_command,
    enqueue_codex_control_command,
)
from eom_orchestrator.control_models import CodexAuthBindingRecord
from sqlalchemy import select
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


def test_observation_claim_does_not_take_older_state_mutation_and_live_claim_replays(
    creative_engine,
):
    now = datetime.now(UTC)
    with creative_engine.connect() as connection:
        outer = connection.begin()
        with Session(bind=connection, expire_on_commit=False) as session:
            binding = session.scalar(
                select(CodexAuthBindingRecord)
                .order_by(CodexAuthBindingRecord.worker_slot_id)
                .limit(1)
            )
            assert binding is not None
            key = uuid4().hex
            operator = OperatorRecord(
                operator_id="operator_" + key,
                username="observation-" + key,
                normalized_username="observation-" + key,
                display_name="Synthetic observation scope",
                status="ACTIVE",
                must_change_password=False,
                role_version=1,
                created_by="guarded-disposable-test",
            )
            session.add(operator)
            session.flush()

            def enqueue(kind, requested_at):
                document = build_codex_control_command(
                    command_type=kind,
                    binding_id=binding.binding_id,
                    expected_resource_version=binding.resource_version,
                    requested_by_operator_id=operator.operator_id,
                    requested_at=requested_at,
                    reason_code="SYNTHETIC" if kind in {"DRAIN", "DISABLE"} else None,
                )
                return enqueue_codex_control_command(
                    session, document=document, idempotency_key="scope:" + uuid4().hex
                )

            older = enqueue("ENABLE", now)
            observation = enqueue("OBSERVE", now + timedelta(seconds=1))
            claim = claim_next_codex_control_command(
                session,
                lease_owner="maintenance-read-only",
                claimed_at=now + timedelta(seconds=2),
                lease_ttl=timedelta(minutes=4),
                command_type="OBSERVE",
            )
            assert claim.command_id == observation.command_id and claim.attempts == 1
            assert older.state == "PENDING" and older.attempts == 0
            assert (
                claim_next_codex_control_command(
                    session,
                    lease_owner="competing-reader",
                    claimed_at=now + timedelta(seconds=3),
                    lease_ttl=timedelta(minutes=4),
                    command_type="OBSERVE",
                )
                is None
            )
            regular = claim_next_codex_control_command(
                session,
                lease_owner="regular-runner",
                claimed_at=now + timedelta(seconds=4),
                lease_ttl=timedelta(minutes=4),
            )
            assert regular.command_id == older.command_id
        outer.rollback()
