from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_orchestrator import general_chat_owner
from eom_orchestrator.general_chat_models import GeneralChatCapacityRecord, GeneralChatTurnRecord
from eom_orchestrator.general_chat_state import ChatError

NOW = datetime(2026, 11, 10, 12, tzinfo=UTC)


@pytest.mark.parametrize("active", [False, True])
@pytest.mark.parametrize("case", ["legacy", "ready", "stale", "account_unavailable"])
def test_chat_slot_uses_existing_reservation_admission_without_changing_public_identity(
    monkeypatch: pytest.MonkeyPatch, active: bool, case: str
) -> None:
    capacity = GeneralChatCapacityRecord(
        slot_key="chat",
        worker_slot_id=None if case == "legacy" else "06",
        active_turn_id="chatturn_" + "a" * 32 if active else None,
        runtime_id="runtime-test",
        heartbeat_at=NOW - timedelta(seconds=31) if case == "stale" else NOW,
        expires_at=NOW + timedelta(minutes=5) if active else None,
    )
    turn = GeneralChatTurnRecord(turn_id=capacity.active_turn_id)
    session = object()
    calls: list[object] = []

    def admit(actual_session: object, actual_capacity: object, **kwargs: Any) -> None:
        assert actual_session is session and actual_capacity is capacity
        assert kwargs == {"now": NOW, "turn": turn if active else None}
        calls.append(actual_capacity)
        if case == "account_unavailable":
            raise ChatError("GENERAL_CHAT_NOT_READY")

    monkeypatch.setattr(general_chat_owner, "require_reserved_chat_admission", admit)
    owner = object.__new__(general_chat_owner.GeneralChatConversationOwner)
    owner.clock = lambda: NOW
    owner.repository = cast(
        Any,
        SimpleNamespace(
            read_snapshot=lambda: nullcontext(session),
            capacity=lambda _: capacity,
            turn=lambda _session, _turn_id: turn,
        ),
    )
    result = owner.slot()
    assert result.slot_key == "chat" and result.dedicated and result.resident
    assert "worker_slot_key" not in result.model_dump()
    assert bool(calls) == (case not in {"legacy", "stale"})
    if case in {"stale", "account_unavailable"}:
        assert result.state == "UNAVAILABLE" and result.unavailable_reason
    else:
        assert result.state == ("BUSY" if active else "READY")
        assert result.unavailable_reason is None
