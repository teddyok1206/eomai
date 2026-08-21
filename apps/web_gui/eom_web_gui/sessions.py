"""Bounded server-side session storage; browser cookies contain only opaque IDs."""

from __future__ import annotations

import asyncio
import secrets
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from eom_web_gui.contracts import RequestDraft


@dataclass(frozen=True, slots=True)
class ApiTokens:
    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime


@dataclass(slots=True)
class WebSession:
    session_id: str
    csrf_token: str
    operator: dict[str, Any]
    tokens: ApiTokens
    created_at: datetime
    expires_at: datetime
    drafts: OrderedDict[str, RequestDraft] = field(default_factory=OrderedDict)
    replay_results: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    refresh_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class SessionStore:
    def __init__(self, *, ttl_seconds: int, maximum_sessions: int, maximum_drafts: int) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._maximum_sessions = maximum_sessions
        self._maximum_drafts = maximum_drafts
        self._sessions: OrderedDict[str, WebSession] = OrderedDict()

    def create(self, *, operator: dict[str, Any], tokens: ApiTokens, now: datetime) -> WebSession:
        self._prune(now)
        while len(self._sessions) >= self._maximum_sessions:
            self._sessions.popitem(last=False)
        session = WebSession(
            session_id=f"websession_{secrets.token_hex(32)}",
            csrf_token=secrets.token_urlsafe(32),
            operator=operator,
            tokens=tokens,
            created_at=now,
            expires_at=min(now + self._ttl, tokens.refresh_expires_at),
        )
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str | None, *, now: datetime) -> WebSession | None:
        if not session_id:
            return None
        self._prune(now)
        session = self._sessions.get(session_id)
        if session is not None:
            self._sessions.move_to_end(session_id)
        return session

    def delete(self, session_id: str) -> WebSession | None:
        return self._sessions.pop(session_id, None)

    def save_draft(self, session: WebSession, draft: RequestDraft) -> None:
        session.drafts[draft.request_draft_id] = draft
        session.drafts.move_to_end(draft.request_draft_id)
        while len(session.drafts) > self._maximum_drafts:
            removed_id, _ = session.drafts.popitem(last=False)
            for key in tuple(session.replay_results):
                if key[0] == removed_id:
                    session.replay_results.pop(key)

    def _prune(self, now: datetime) -> None:
        for key, session in tuple(self._sessions.items()):
            if session.expires_at <= now:
                self._sessions.pop(key)


def utc_now() -> datetime:
    return datetime.now(UTC)
