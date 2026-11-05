"""Bounded server-side session storage; browser cookies contain only opaque IDs."""

from __future__ import annotations

import asyncio
import json
import secrets
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from eom_web_gui.contracts import RequestDraft

MAX_REPLAY_RESULTS = 64
MAX_REPLAY_RESULT_BYTES = 65_536
MAX_REPLAY_BYTES_PER_SESSION = 262_144


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
    replay_results: OrderedDict[tuple[str, str], bytes] = field(default_factory=OrderedDict)
    replay_result_bytes: int = 0
    refresh_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class SessionStore:
    def __init__(self, *, ttl_seconds: int, maximum_sessions: int, maximum_drafts: int) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._maximum_sessions = maximum_sessions
        self._maximum_drafts = maximum_drafts
        self._sessions: OrderedDict[str, WebSession] = OrderedDict()
        # FastAPI sync dependencies may access this in-memory adapter from
        # different worker threads. Keep the map/LRU operations atomic; the
        # per-session async refresh lock still owns token refresh sequencing.
        self._lock = threading.RLock()

    def create(self, *, operator: dict[str, Any], tokens: ApiTokens, now: datetime) -> WebSession:
        with self._lock:
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
        with self._lock:
            self._prune(now)
            session = self._sessions.get(session_id)
            if session is not None:
                self._sessions.move_to_end(session_id)
            return session

    def delete(self, session_id: str) -> WebSession | None:
        with self._lock:
            return self._sessions.pop(session_id, None)

    def delete_other_operator_sessions(self, operator_id: str, *, except_session_id: str) -> int:
        """Remove cached Studio sessions invalidated by a credential change."""

        with self._lock:
            session_ids = tuple(
                session_id
                for session_id, session in self._sessions.items()
                if session_id != except_session_id
                and session.operator.get("operator_id") == operator_id
            )
            for session_id in session_ids:
                self._sessions.pop(session_id, None)
            return len(session_ids)

    def save_draft(self, session: WebSession, draft: RequestDraft) -> None:
        with self._lock:
            session.drafts[draft.request_draft_id] = draft
            session.drafts.move_to_end(draft.request_draft_id)
            while len(session.drafts) > self._maximum_drafts:
                removed_id, _ = session.drafts.popitem(last=False)
                for key in tuple(session.replay_results):
                    if key[0] == removed_id:
                        session.replay_result_bytes -= len(session.replay_results.pop(key))

    def draft_result(self, session: WebSession, key: tuple[str, str]) -> dict[str, Any] | None:
        with self._lock:
            value = session.replay_results.get(key)
            if value is None:
                return None
            session.replay_results.move_to_end(key)
            return json.loads(value)  # type: ignore[no-any-return]

    def save_draft_result(
        self, session: WebSession, key: tuple[str, str], result: dict[str, Any]
    ) -> None:
        encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_REPLAY_RESULT_BYTES:
            # This is only a cache. Same-key replay still resolves the official API
            # command; skipping/evicting here never creates a new submission key.
            return
        with self._lock:
            previous = session.replay_results.pop(key, None)
            if previous is not None:
                session.replay_result_bytes -= len(previous)
            session.replay_results[key] = encoded
            session.replay_result_bytes += len(encoded)
            while (
                len(session.replay_results) > MAX_REPLAY_RESULTS
                or session.replay_result_bytes > MAX_REPLAY_BYTES_PER_SESSION
            ):
                _, removed = session.replay_results.popitem(last=False)
                session.replay_result_bytes -= len(removed)

    def _prune(self, now: datetime) -> None:
        for key, session in tuple(self._sessions.items()):
            if session.expires_at <= now:
                self._sessions.pop(key)


def utc_now() -> datetime:
    return datetime.now(UTC)
