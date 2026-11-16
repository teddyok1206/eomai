"""Private binding state, immutable small policies and command receipts, owned by Catalog."""

from __future__ import annotations

from datetime import datetime

from eom_orchestrator.models import Base
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column


class KakaoChannelBindingRecord(Base):
    __tablename__ = "kakao_channel_bindings"
    __table_args__ = (
        CheckConstraint(
            "source_binding_id ~ '^kakaobinding_[0-9a-f]{32}$'", name="ck_kakao_binding_id"
        ),
        CheckConstraint("state IN ('DRAFT','RETIRED')", name="ck_kakao_binding_state"),
        CheckConstraint("resource_version >= 1", name="ck_kakao_binding_version"),
        CheckConstraint(
            "length(btrim(display_name)) > 0 AND display_name !~ '[[:cntrl:]]'",
            name="ck_kakao_binding_name",
        ),
        CheckConstraint("updated_at >= created_at", name="ck_kakao_binding_time"),
        UniqueConstraint("owner_operator_id", "source_binding_id", name="uq_kakao_binding_owner"),
        ForeignKeyConstraint(
            ["source_binding_id", "current_policy_revision_id"],
            [
                "kakao_collection_policy_revisions.source_binding_id",
                "kakao_collection_policy_revisions.policy_revision_id",
            ],
            name="fk_kakao_binding_current_policy",
            ondelete="RESTRICT",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    source_binding_id: Mapped[str] = mapped_column(String(45), primary_key=True)
    owner_operator_id: Mapped[str] = mapped_column(
        String(41), ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    resource_version: Mapped[int] = mapped_column(Integer, nullable=False)
    current_policy_revision_id: Mapped[str] = mapped_column(String(47), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KakaoCollectionPolicyRevisionRecord(Base):
    __tablename__ = "kakao_collection_policy_revisions"
    __table_args__ = (
        CheckConstraint(
            "policy_revision_id ~ '^kakaopolicyrev_[0-9a-f]{32}$'", name="ck_kakao_policy_id"
        ),
        CheckConstraint(
            "(revision_number = 1 AND previous_revision_id IS NULL) OR "
            "(revision_number > 1 AND previous_revision_id IS NOT NULL "
            "AND previous_revision_id <> policy_revision_id)",
            name="ck_kakao_policy_lineage",
        ),
        CheckConstraint("sha256 ~ '^sha256:[0-9a-f]{64}$'", name="ck_kakao_policy_hash"),
        CheckConstraint("interval_minutes BETWEEN 60 AND 10080", name="ck_kakao_policy_interval"),
        CheckConstraint(
            "source_timezone IN ('unknown','Asia/Seoul')", name="ck_kakao_policy_timezone"
        ),
        UniqueConstraint("source_binding_id", "policy_revision_id", name="uq_kakao_policy_binding"),
        UniqueConstraint("source_binding_id", "revision_number", name="uq_kakao_policy_number"),
        ForeignKeyConstraint(
            ["source_binding_id", "previous_revision_id"],
            [
                "kakao_collection_policy_revisions.source_binding_id",
                "kakao_collection_policy_revisions.policy_revision_id",
            ],
            name="fk_kakao_policy_previous",
            ondelete="RESTRICT",
        ),
    )

    policy_revision_id: Mapped[str] = mapped_column(String(47), primary_key=True)
    source_binding_id: Mapped[str] = mapped_column(
        String(45),
        ForeignKey("kakao_channel_bindings.source_binding_id", ondelete="RESTRICT"),
        nullable=False,
    )
    previous_revision_id: Mapped[str | None] = mapped_column(String(47))
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    source_timezone: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by: Mapped[str] = mapped_column(
        String(41), ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KakaoBindingCommandRecord(Base):
    __tablename__ = "kakao_binding_commands"
    __table_args__ = (
        CheckConstraint("command_id ~ '^kakaocommand_[0-9a-f]{32}$'", name="ck_kakao_command_id"),
        CheckConstraint(
            "action IN ('CREATE','UPDATE_COLLECTION_POLICY','RETIRE')",
            name="ck_kakao_command_action",
        ),
        CheckConstraint(
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$' AND idempotency_key ~ '^[!-~]{16,128}$'",
            name="ck_kakao_command_request",
        ),
        CheckConstraint(
            "result_version >= 1 AND result_state IN ('DRAFT','RETIRED')",
            name="ck_kakao_command_result",
        ),
        UniqueConstraint(
            "owner_operator_id",
            "idempotency_scope",
            "idempotency_key",
            name="uq_kakao_command_replay",
        ),
        ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id"],
            [
                "kakao_channel_bindings.owner_operator_id",
                "kakao_channel_bindings.source_binding_id",
            ],
            name="fk_kakao_command_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_binding_id", "result_policy_revision_id"],
            [
                "kakao_collection_policy_revisions.source_binding_id",
                "kakao_collection_policy_revisions.policy_revision_id",
            ],
            name="fk_kakao_command_policy",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("source_binding_id", "result_version", name="uq_kakao_command_version"),
    )

    command_id: Mapped[str] = mapped_column(String(45), primary_key=True)
    source_binding_id: Mapped[str] = mapped_column(String(45), nullable=False)
    owner_operator_id: Mapped[str] = mapped_column(String(41), nullable=False)
    idempotency_scope: Mapped[str] = mapped_column(String(96), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    result_state: Mapped[str] = mapped_column(String(16), nullable=False)
    result_version: Mapped[int] = mapped_column(Integer, nullable=False)
    result_policy_revision_id: Mapped[str] = mapped_column(String(47), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
