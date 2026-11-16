"""One assigned browser profile, bounded manual leases and immutable command receipts."""

from datetime import datetime

from eom_orchestrator.models import Base
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column


class KakaoProfileRuntimeRecord(Base):
    __tablename__ = "kakao_profile_runtime"
    __table_args__ = (
        CheckConstraint("slot_key = 'primary'", name="ck_kakao_profile_slot"),
        CheckConstraint("profile_id ~ '^kakaoprofile_[0-9a-f]{32}$'", name="ck_kakao_profile_id"),
        CheckConstraint(
            "mode IN ('STOPPED','MANUAL','AUTO','PAUSING','ERROR')", name="ck_kakao_profile_mode"
        ),
        CheckConstraint(
            "fence_epoch >= 0 AND gateway_epoch >= 0 AND resource_version >= 1",
            name="ck_kakao_profile_versions",
        ),
        CheckConstraint(
            "mode <> 'STOPPED' OR current_lease_id IS NULL", name="ck_kakao_profile_stopped"
        ),
        UniqueConstraint("profile_id", name="uq_kakao_profile_id"),
        UniqueConstraint(
            "owner_operator_id", "source_binding_id", "profile_id", name="uq_kakao_profile_owner"
        ),
        ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id"],
            [
                "kakao_channel_bindings.owner_operator_id",
                "kakao_channel_bindings.source_binding_id",
            ],
            name="fk_kakao_profile_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["profile_id", "current_lease_id"],
            ["kakao_manual_sessions.profile_id", "kakao_manual_sessions.lease_id"],
            name="fk_kakao_profile_current_lease",
            ondelete="RESTRICT",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    slot_key: Mapped[str] = mapped_column(String(16), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(45), nullable=False)
    owner_operator_id: Mapped[str] = mapped_column(String(41), nullable=False)
    source_binding_id: Mapped[str] = mapped_column(String(45), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    fence_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    gateway_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    resource_version: Mapped[int] = mapped_column(Integer, nullable=False)
    current_lease_id: Mapped[str | None] = mapped_column(String(49))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KakaoManualSessionRecord(Base):
    __tablename__ = "kakao_manual_sessions"
    __table_args__ = (
        CheckConstraint("lease_id ~ '^kakaoremotelease_[0-9a-f]{32}$'", name="ck_kakao_manual_id"),
        CheckConstraint("command_sha256 ~ '^sha256:[0-9a-f]{64}$'", name="ck_kakao_manual_hash"),
        CheckConstraint(
            "phase IN ('PREPARING','ACTIVE','STOPPING','ENDED','ERROR')",
            name="ck_kakao_manual_phase",
        ),
        CheckConstraint(
            "resource_version >= 1 AND fence_epoch >= 1 "
            "AND gateway_epoch >= 1 AND grant_revision >= 0",
            name="ck_kakao_manual_versions",
        ),
        CheckConstraint(
            "absolute_expires_at > created_at "
            "AND absolute_expires_at <= created_at + interval '20 minutes'",
            name="ck_kakao_manual_absolute",
        ),
        CheckConstraint(
            "(grant_revision = 0 AND authorized_at IS NULL AND expires_at IS NULL) OR "
            "(grant_revision > 0 AND authorized_at IS NOT NULL AND expires_at IS NOT NULL "
            "AND authorized_at >= created_at AND expires_at > authorized_at "
            "AND expires_at <= authorized_at + interval '30 seconds' "
            "AND expires_at <= absolute_expires_at)",
            name="ck_kakao_manual_grant",
        ),
        CheckConstraint(
            "(phase = 'ENDED') = (closed_at IS NOT NULL)", name="ck_kakao_manual_closed"
        ),
        CheckConstraint(
            "(browser_invocation_id IS NULL AND browser_pid IS NULL "
            "AND browser_monotonic_us IS NULL AND browser_observed_at IS NULL) OR "
            "(browser_invocation_id IS NOT NULL AND browser_pid IS NOT NULL "
            "AND browser_monotonic_us IS NOT NULL AND browser_observed_at IS NOT NULL "
            "AND browser_pid > 0 AND browser_monotonic_us > 0 "
            "AND browser_observed_at >= created_at)",
            name="ck_kakao_manual_browser",
        ),
        CheckConstraint(
            "phase <> 'ACTIVE' OR (grant_revision > 0 "
            "AND browser_invocation_id IS NOT NULL AND gateway_invocation_id IS NOT NULL)",
            name="ck_kakao_manual_active",
        ),
        UniqueConstraint("profile_id", "lease_id", name="uq_kakao_manual_profile"),
        UniqueConstraint("owner_operator_id", "lease_id", name="uq_kakao_manual_owner"),
        UniqueConstraint("profile_id", "fence_epoch", name="uq_kakao_manual_fence"),
        ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id", "profile_id"],
            [
                "kakao_profile_runtime.owner_operator_id",
                "kakao_profile_runtime.source_binding_id",
                "kakao_profile_runtime.profile_id",
            ],
            name="fk_kakao_manual_profile_owner",
            ondelete="RESTRICT",
        ),
    )
    lease_id: Mapped[str] = mapped_column(String(49), primary_key=True)
    owner_operator_id: Mapped[str] = mapped_column(String(41), nullable=False)
    source_binding_id: Mapped[str] = mapped_column(String(45), nullable=False)
    profile_id: Mapped[str] = mapped_column(String(45), nullable=False)
    identity_session_id: Mapped[str] = mapped_column(
        String(43), ForeignKey("api_sessions.api_session_id", ondelete="RESTRICT"), nullable=False
    )
    browser_run_id: Mapped[str] = mapped_column(String(48), nullable=False)
    command_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    dispatch_boot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    fence_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    gateway_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    phase: Mapped[str] = mapped_column(String(16), nullable=False)
    resource_version: Mapped[int] = mapped_column(Integer, nullable=False)
    grant_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(32))
    ended_reason: Mapped[str | None] = mapped_column(String(32))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    browser_invocation_id: Mapped[str | None] = mapped_column(String(32))
    browser_pid: Mapped[int | None] = mapped_column(Integer)
    browser_monotonic_us: Mapped[int | None] = mapped_column(BigInteger)
    browser_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gateway_invocation_id: Mapped[str | None] = mapped_column(String(32))


class KakaoRemoteCommandRecord(Base):
    __tablename__ = "kakao_remote_commands"
    __table_args__ = (
        CheckConstraint("action IN ('START','RENEW','END')", name="ck_kakao_remote_command_action"),
        CheckConstraint(
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$' AND idempotency_key ~ '^[!-~]{16,128}$'",
            name="ck_kakao_remote_command_request",
        ),
        UniqueConstraint(
            "owner_operator_id",
            "idempotency_scope",
            "idempotency_key",
            name="uq_kakao_remote_command_replay",
        ),
        ForeignKeyConstraint(
            ["owner_operator_id", "lease_id"],
            ["kakao_manual_sessions.owner_operator_id", "kakao_manual_sessions.lease_id"],
            name="fk_kakao_remote_command_owner",
            ondelete="RESTRICT",
        ),
    )
    command_id: Mapped[str] = mapped_column(String(45), primary_key=True)
    owner_operator_id: Mapped[str] = mapped_column(String(41), nullable=False)
    lease_id: Mapped[str] = mapped_column(String(49), nullable=False)
    idempotency_scope: Mapped[str] = mapped_column(String(96), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    action: Mapped[str] = mapped_column(String(8), nullable=False)
    result_phase: Mapped[str] = mapped_column(String(16), nullable=False)
    result_version: Mapped[int] = mapped_column(Integer, nullable=False)
    result_grant_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    result_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_ready: Mapped[bool] = mapped_column(Boolean, nullable=False)
    result_error: Mapped[str | None] = mapped_column(String(32))
    result_ended_reason: Mapped[str | None] = mapped_column(String(32))
    result_closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
