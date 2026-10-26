"""Indexed PostgreSQL access and lock ordering for dedicated conversation metadata."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from hashlib import sha256

from eom_identity_service.models import OperatorRecord
from sqlalchemy import Engine, select, text, tuple_
from sqlalchemy.orm import Session

from eom_orchestrator.database import build_session_factory
from eom_orchestrator.general_chat_models import (
    GeneralChatCapacityRecord,
    GeneralChatConversationRecord,
    GeneralChatTurnRecord,
)
from eom_orchestrator.general_chat_state import ACTIVE_CHAT_STATES, ChatError


class GeneralChatRepository:
    def __init__(self, engine: Engine) -> None:
        if engine.dialect.name != "postgresql":
            raise ValueError("chat claims require PostgreSQL transaction semantics")
        self.sessions = build_session_factory(engine)

    @contextmanager
    def read_snapshot(self) -> Iterator[Session]:
        with self.sessions.begin() as session:
            session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            yield session

    @staticmethod
    def require_actor(session: Session, actor_id: str) -> None:
        actor = session.scalar(
            select(OperatorRecord.operator_id).where(
                OperatorRecord.operator_id == actor_id,
                OperatorRecord.status == "ACTIVE",
                OperatorRecord.deleted_at.is_(None),
            )
        )
        if actor is None:
            raise ChatError("GENERAL_CHAT_FORBIDDEN")

    @staticmethod
    def lock_intent(session: Session, intent: str) -> None:
        # Scoped advisory locks cover first publication and receipt, not model execution.
        key = int.from_bytes(sha256(intent.encode()).digest()[:8], "big", signed=True)
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})

    @staticmethod
    def owned(
        session: Session,
        actor_id: str,
        conversation_id: str,
        *,
        lock: bool = False,
        include_deleted: bool = False,
    ) -> GeneralChatConversationRecord:
        query = select(GeneralChatConversationRecord).where(
            GeneralChatConversationRecord.conversation_id == conversation_id,
            GeneralChatConversationRecord.owner_id == actor_id,
        )
        if not include_deleted:
            query = query.where(GeneralChatConversationRecord.deleted_at.is_(None))
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        value = session.scalar(query)
        if value is None:
            # Same answer for a missing and another owner's conversation.
            raise ChatError("GENERAL_CHAT_NOT_FOUND")
        return value

    @staticmethod
    def conversation_record(
        session: Session,
        conversation_id: str,
        *,
        lock: bool = False,
    ) -> GeneralChatConversationRecord:
        query = select(GeneralChatConversationRecord).where(
            GeneralChatConversationRecord.conversation_id == conversation_id,
        )
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        value = session.scalar(query)
        if value is None:
            raise ChatError("GENERAL_CHAT_NOT_FOUND")
        return value

    @staticmethod
    def create_receipt(
        session: Session,
        actor_id: str,
        key: str,
    ) -> GeneralChatConversationRecord | None:
        return session.scalar(
            select(GeneralChatConversationRecord).where(
                GeneralChatConversationRecord.owner_id == actor_id,
                GeneralChatConversationRecord.create_key_sha256 == key,
            )
        )

    @staticmethod
    def turn_receipt(
        session: Session,
        conversation_id: str,
        key: str,
    ) -> GeneralChatTurnRecord | None:
        return session.scalar(
            select(GeneralChatTurnRecord).where(
                GeneralChatTurnRecord.conversation_id == conversation_id,
                GeneralChatTurnRecord.submission_key_sha256 == key,
            )
        )

    @staticmethod
    def active_turn(session: Session, conversation_id: str) -> bool:
        return (
            session.scalar(
                select(GeneralChatTurnRecord.turn_id)
                .where(
                    GeneralChatTurnRecord.conversation_id == conversation_id,
                    GeneralChatTurnRecord.state.in_(ACTIVE_CHAT_STATES),
                )
                .limit(1)
            )
            is not None
        )

    @staticmethod
    def history(
        session: Session,
        conversation_id: str,
        *,
        limit: int,
        before: int | None = None,
        completed_only: bool = False,
    ) -> tuple[GeneralChatTurnRecord, ...]:
        query = select(GeneralChatTurnRecord).where(
            GeneralChatTurnRecord.conversation_id == conversation_id,
        )
        if before is not None:
            query = query.where(GeneralChatTurnRecord.user_sequence < before)
        if completed_only:
            query = query.where(GeneralChatTurnRecord.state == "COMPLETED")
        return tuple(
            session.scalars(
                query.order_by(
                    GeneralChatTurnRecord.user_sequence.desc(),
                ).limit(limit)
            ).all()
        )

    @staticmethod
    def conversations(
        session: Session,
        actor_id: str,
        *,
        before: tuple[datetime, str] | None,
    ) -> tuple[GeneralChatConversationRecord, ...]:
        query = select(GeneralChatConversationRecord).where(
            GeneralChatConversationRecord.owner_id == actor_id,
            GeneralChatConversationRecord.deleted_at.is_(None),
        )
        if before is not None:
            query = query.where(
                tuple_(
                    GeneralChatConversationRecord.updated_at,
                    GeneralChatConversationRecord.conversation_id,
                )
                < before
            )
        return tuple(
            session.scalars(
                query.order_by(
                    GeneralChatConversationRecord.updated_at.desc(),
                    GeneralChatConversationRecord.conversation_id.desc(),
                ).limit(51)
            ).all()
        )

    @staticmethod
    def capacity(session: Session, *, lock: bool = False) -> GeneralChatCapacityRecord:
        query = select(GeneralChatCapacityRecord).where(
            GeneralChatCapacityRecord.slot_key == "chat",
        )
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        value = session.scalar(query)
        if value is None:
            raise ChatError("GENERAL_CHAT_NOT_READY")
        return value

    @staticmethod
    def turn(session: Session, turn_id: str, *, lock: bool = False) -> GeneralChatTurnRecord:
        query = select(GeneralChatTurnRecord).where(GeneralChatTurnRecord.turn_id == turn_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        value = session.scalar(query)
        if value is None:
            raise ChatError("GENERAL_CHAT_NOT_FOUND")
        return value

    @staticmethod
    def next_queued(session: Session) -> GeneralChatTurnRecord | None:
        return session.scalar(
            select(GeneralChatTurnRecord)
            .join(GeneralChatConversationRecord)
            .join(
                OperatorRecord, OperatorRecord.operator_id == GeneralChatConversationRecord.owner_id
            )
            .where(
                GeneralChatTurnRecord.state == "QUEUED",
                GeneralChatConversationRecord.deleted_at.is_(None),
                OperatorRecord.status == "ACTIVE",
                OperatorRecord.deleted_at.is_(None),
            )
            .order_by(GeneralChatTurnRecord.created_at, GeneralChatTurnRecord.turn_id)
            .with_for_update(skip_locked=True, of=GeneralChatTurnRecord)
            .limit(1)
        )

    @staticmethod
    def touch(conversation: GeneralChatConversationRecord, *, now: datetime) -> None:
        conversation.resource_version += 1
        conversation.updated_at = max(now, conversation.updated_at)
