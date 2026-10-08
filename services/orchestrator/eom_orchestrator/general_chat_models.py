"""Pointer-only conversation receipts and an independent indexed single-slot queue."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from eom_orchestrator.models import Base


class GeneralChatConversationRecord(Base):
    __tablename__ = "general_chat_conversations"
    __table_args__ = (
        UniqueConstraint("owner_id", "create_key_sha256", name="uq_chat_owner_create"),
        CheckConstraint(
            "resource_version >= 1 AND next_sequence >= 1 AND next_sequence % 2 = 1",
            name="ck_chat_conversation_version",
        ),
        CheckConstraint("conversation_id ~ '^chat_[0-9a-f]{32}$'", name="ck_chat_conversation_id"),
        CheckConstraint(
            "create_key_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "create_request_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_chat_create_hashes",
        ),
        Index("ix_chat_owner_history", "owner_id", "updated_at", "conversation_id"),
    )

    conversation_id: Mapped[str] = mapped_column(String(37), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String(41), ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    resource_version: Mapped[int] = mapped_column(Integer, nullable=False)
    next_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    create_key_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    create_request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GeneralChatTurnRecord(Base):
    __tablename__ = "general_chat_turns"
    __table_args__ = (
        UniqueConstraint("conversation_id", "submission_key_sha256", name="uq_chat_turn_intent"),
        UniqueConstraint("conversation_id", "user_sequence", name="uq_chat_turn_sequence"),
        CheckConstraint("turn_id ~ '^chatturn_[0-9a-f]{32}$'", name="ck_chat_turn_id"),
        CheckConstraint(
            "user_sequence >= 1 AND user_sequence % 2 = 1 AND expected_version >= 1",
            name="ck_chat_turn_sequence",
        ),
        CheckConstraint(
            "state IN ('QUEUED','CLAIMED','RUNNING','COMMITTING','COMPLETED','FAILED','CANCELLED')",
            name="ck_chat_turn_state",
        ),
        CheckConstraint(
            "submission_key_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "submission_request_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "input_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_chat_turn_hashes",
        ),
        CheckConstraint(
            "(state IN ('QUEUED','CANCELLED') AND claim_id IS NULL) OR "
            "(state NOT IN ('QUEUED','CANCELLED') AND claim_id IS NOT NULL AND "
            "claim_id ~ '^chatclaim_[0-9a-f]{32}$')",
            name="ck_chat_turn_claim",
        ),
        CheckConstraint(
            "(request_artifact_id IS NULL AND request_revision_id IS NULL AND "
            "request_sha256 IS NULL) OR (request_artifact_id IS NOT NULL AND "
            "request_revision_id IS NOT NULL AND request_sha256 IS NOT NULL AND "
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$')",
            name="ck_chat_request_pointer",
        ),
        CheckConstraint(
            "(output_artifact_id IS NULL AND output_revision_id IS NULL AND "
            "output_sha256 IS NULL) OR (output_artifact_id IS NOT NULL AND "
            "output_revision_id IS NOT NULL AND output_sha256 IS NOT NULL AND "
            "output_sha256 ~ '^sha256:[0-9a-f]{64}$')",
            name="ck_chat_output_pointer",
        ),
        CheckConstraint(
            "state NOT IN ('RUNNING','COMMITTING','COMPLETED') OR request_artifact_id IS NOT NULL",
            name="ck_chat_running_request",
        ),
        CheckConstraint(
            "(state <> 'COMPLETED' OR output_artifact_id IS NOT NULL) AND "
            "(output_artifact_id IS NULL OR state IN ('COMPLETED','FAILED'))",
            name="ck_chat_completed_output",
        ),
        CheckConstraint(
            "(state NOT IN ('COMMITTING','COMPLETED') OR result_sha256 IS NOT NULL) AND "
            "(result_sha256 IS NULL OR state IN ('COMMITTING','COMPLETED','FAILED'))",
            name="ck_chat_result_hash",
        ),
        CheckConstraint(
            "result_sha256 IS NULL OR result_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_chat_result_format",
        ),
        CheckConstraint(
            "(state = 'FAILED' OR (state = 'COMMITTING' AND "
            "COALESCE(result_status = 'FAILED', false))) = (failure_code IS NOT NULL)",
            name="ck_chat_failure",
        ),
        CheckConstraint(
            "(result_status IS NULL) = (result_sha256 IS NULL) AND "
            "(result_status IS NULL OR result_status IN ('SUCCEEDED','FAILED')) AND "
            "(state <> 'COMPLETED' OR result_status = 'SUCCEEDED') AND "
            "(state <> 'FAILED' OR result_status IS NULL OR result_status = 'FAILED')",
            name="ck_chat_result_status",
        ),
        CheckConstraint(
            "output_artifact_id IS NULL OR (result_sha256 IS NOT NULL AND "
            "output_sha256 = result_sha256)",
            name="ck_chat_output_result",
        ),
        CheckConstraint(
            "failure_code IS NULL OR failure_code ~ '^[A-Z][A-Z0-9_]{0,63}$'",
            name="ck_chat_failure_format",
        ),
        CheckConstraint(
            "(state IN ('COMPLETED','FAILED','CANCELLED')) = (completed_at IS NOT NULL)",
            name="ck_chat_terminal_time",
        ),
        ForeignKeyConstraint(
            ("input_artifact_id", "input_revision_id"),
            ("artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"),
            name="fk_chat_input_revision",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("request_artifact_id", "request_revision_id"),
            ("artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"),
            name="fk_chat_request_revision",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("output_artifact_id", "output_revision_id"),
            ("artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"),
            name="fk_chat_output_revision",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(dispatch_artifact_id IS NULL AND dispatch_revision_id IS NULL AND "
            "dispatch_sha256 IS NULL) OR (dispatch_artifact_id IS NOT NULL AND "
            "dispatch_revision_id IS NOT NULL AND dispatch_sha256 IS NOT NULL AND "
            "dispatch_sha256 ~ '^sha256:[0-9a-f]{64}$' AND request_artifact_id IS NOT NULL AND "
            "state IN ('RUNNING','COMMITTING','COMPLETED','FAILED'))",
            name="ck_chat_dispatch_pointer",
        ),
        ForeignKeyConstraint(
            ("dispatch_artifact_id", "dispatch_revision_id"),
            ("artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"),
            name="fk_chat_dispatch_revision",
            ondelete="RESTRICT",
        ),
        Index(
            "uq_chat_one_active",
            "conversation_id",
            unique=True,
            postgresql_where=text("state IN ('QUEUED','CLAIMED','RUNNING','COMMITTING')"),
        ),
        Index("ix_chat_fifo", "created_at", "turn_id", postgresql_where=text("state = 'QUEUED'")),
    )

    turn_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(37),
        ForeignKey("general_chat_conversations.conversation_id", ondelete="RESTRICT"),
        nullable=False,
    )
    user_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expected_version: Mapped[int] = mapped_column(Integer, nullable=False)
    submission_key_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    submission_request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    input_artifact_id: Mapped[str] = mapped_column(String(41), nullable=False)
    input_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    request_artifact_id: Mapped[str | None] = mapped_column(String(41))
    request_revision_id: Mapped[str | None] = mapped_column(String(36))
    request_sha256: Mapped[str | None] = mapped_column(String(71))
    output_artifact_id: Mapped[str | None] = mapped_column(String(41))
    output_revision_id: Mapped[str | None] = mapped_column(String(36))
    output_sha256: Mapped[str | None] = mapped_column(String(71))
    claim_id: Mapped[str | None] = mapped_column(String(42))
    result_sha256: Mapped[str | None] = mapped_column(String(71))
    result_status: Mapped[str | None] = mapped_column(String(9))
    failure_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatch_artifact_id: Mapped[str | None] = mapped_column(String(41))
    dispatch_revision_id: Mapped[str | None] = mapped_column(String(36))
    dispatch_sha256: Mapped[str | None] = mapped_column(String(71))


class GeneralChatCapacityRecord(Base):
    __tablename__ = "general_chat_capacity"
    __table_args__ = (
        CheckConstraint("slot_key = 'chat'", name="ck_chat_capacity_key"),
        CheckConstraint("(runtime_id IS NULL) = (heartbeat_at IS NULL)", name="ck_chat_heartbeat"),
        CheckConstraint(
            "(active_turn_id IS NULL AND claim_id IS NULL AND expires_at IS NULL) OR "
            "(active_turn_id IS NOT NULL AND claim_id IS NOT NULL AND "
            "claim_id ~ '^chatclaim_[0-9a-f]{32}$' AND "
            "expires_at IS NOT NULL AND runtime_id IS NOT NULL)",
            name="ck_chat_capacity_claim",
        ),
    )

    slot_key: Mapped[str] = mapped_column(String(4), primary_key=True)
    runtime_id: Mapped[str | None] = mapped_column(String(64))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active_turn_id: Mapped[str | None] = mapped_column(
        String(41), ForeignKey("general_chat_turns.turn_id", ondelete="RESTRICT")
    )
    claim_id: Mapped[str | None] = mapped_column(String(42))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
