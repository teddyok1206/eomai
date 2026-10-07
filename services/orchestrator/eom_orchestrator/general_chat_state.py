"""Conversation execution invariants independent of storage and model adapters."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Literal


class ChatError(RuntimeError):
    """A stable, content-free code for the application boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


CHAT_HEARTBEAT_TTL = timedelta(seconds=30)


def chat_runtime_available(
    *,
    runtime_id: str | None,
    heartbeat_at: datetime | None,
    expires_at: datetime | None,
    now: datetime,
) -> bool:
    return (
        runtime_id is not None
        and heartbeat_at is not None
        and timedelta(0) <= now - heartbeat_at <= CHAT_HEARTBEAT_TTL
        and (expires_at is None or expires_at > now)
    )


class ChatTurnState(StrEnum):
    QUEUED = "QUEUED"
    CLAIMED = "CLAIMED"
    RUNNING = "RUNNING"
    COMMITTING = "COMMITTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


ACTIVE_CHAT_STATES = ("QUEUED", "CLAIMED", "RUNNING", "COMMITTING")
CHAT_TRANSITIONS = MappingProxyType(
    {
        ChatTurnState.QUEUED: frozenset({ChatTurnState.CLAIMED, ChatTurnState.CANCELLED}),
        ChatTurnState.CLAIMED: frozenset({ChatTurnState.RUNNING, ChatTurnState.FAILED}),
        ChatTurnState.RUNNING: frozenset({ChatTurnState.COMMITTING, ChatTurnState.FAILED}),
        ChatTurnState.COMMITTING: frozenset({ChatTurnState.COMPLETED, ChatTurnState.FAILED}),
        ChatTurnState.COMPLETED: frozenset(),
        ChatTurnState.FAILED: frozenset(),
        ChatTurnState.CANCELLED: frozenset(),
    }
)


def require_chat_transition(prior: str, target: ChatTurnState) -> None:
    if target not in CHAT_TRANSITIONS[ChatTurnState(prior)]:
        raise ChatError("GENERAL_CHAT_INVALID_TRANSITION")


PublicChatState = Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]
PUBLIC_CHAT_STATES: Mapping[str, PublicChatState] = MappingProxyType(
    {
        "QUEUED": "QUEUED",
        "CLAIMED": "RUNNING",
        "RUNNING": "RUNNING",
        "COMMITTING": "RUNNING",
        "COMPLETED": "COMPLETED",
        "FAILED": "FAILED",
        "CANCELLED": "CANCELLED",
    }
)


def public_chat_state(state: str) -> PublicChatState:
    try:
        return PUBLIC_CHAT_STATES[state]
    except KeyError as exc:
        raise ChatError("GENERAL_CHAT_INVALID_STATE") from exc
