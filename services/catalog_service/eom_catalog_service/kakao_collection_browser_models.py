"""Actual collection browser lifetime; one profile gate remains shared with MANUAL."""

from datetime import datetime

from eom_orchestrator.models import Base
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column


class KakaoCollectionBrowserRecord(Base):
    __tablename__ = "kakao_collection_browsers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id", "run_id"],
            [
                "kakao_collection_runs.owner_operator_id",
                "kakao_collection_runs.source_binding_id",
                "kakao_collection_runs.run_id",
            ],
            name="fk_kakao_collection_browser_run",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_operator_id", "profile_id"],
            ["kakao_profile_runtime.owner_operator_id", "kakao_profile_runtime.profile_id"],
            name="fk_kakao_collection_browser_profile",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("run_id", "browser_run_id", name="uq_kakao_collection_browser_run"),
        UniqueConstraint(
            "profile_id",
            "browser_run_id",
            "fence_epoch",
            name="uq_kakao_collection_browser_pointer",
        ),
        UniqueConstraint("profile_id", "fence_epoch", name="uq_kakao_collection_browser_fence"),
        UniqueConstraint("run_id", "epoch_number", name="uq_kakao_collection_browser_epoch"),
        CheckConstraint(
            "browser_run_id ~ '^kakaobrowserrun_[0-9a-f]{32}$' AND "
            "command_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "dispatch_boot_id ~ '^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$'",
            name="ck_kakao_collection_browser_values",
        ),
        CheckConstraint(
            "fence_epoch BETWEEN 1 AND 2147483647 AND "
            "epoch_number BETWEEN 1 AND 2147483647 AND "
            "resource_version BETWEEN 1 AND 2147483647",
            name="ck_kakao_collection_browser_versions",
        ),
        CheckConstraint(
            "phase IN ('PREPARING','RUNNING','STOPPING','CLOSED')",
            name="ck_kakao_collection_browser_phase",
        ),
        CheckConstraint(
            "(phase = 'CLOSED') = (closed_at IS NOT NULL) AND "
            "(phase = 'CLOSED') = (close_kind IS NOT NULL) AND "
            "(closed_at IS NULL OR closed_at >= created_at)",
            name="ck_kakao_collection_browser_closed",
        ),
        CheckConstraint(
            "close_kind IS NULL OR close_kind IN ('STOPPED','PRE_READY_FAILED','REBOOT_UNCLEAN')",
            name="ck_kakao_collection_browser_closure",
        ),
        CheckConstraint(
            "last_error IS NULL OR last_error IN "
            "('START_FAILED','RUNTIME_LOST','OWNER_UNAVAILABLE','REBOOT_UNCLEAN')",
            name="ck_kakao_collection_browser_error",
        ),
        CheckConstraint(
            "(browser_invocation_id IS NULL AND browser_pid IS NULL AND "
            "browser_monotonic_us IS NULL AND browser_observed_at IS NULL) OR "
            "(browser_invocation_id IS NOT NULL AND browser_pid IS NOT NULL AND "
            "browser_monotonic_us IS NOT NULL AND browser_observed_at IS NOT NULL AND "
            "browser_invocation_id ~ '^[0-9a-f]{32}$' AND browser_pid > 0 AND "
            "browser_monotonic_us > 0 AND browser_observed_at >= created_at)",
            name="ck_kakao_collection_browser_handle",
        ),
        CheckConstraint(
            "phase <> 'RUNNING' OR browser_invocation_id IS NOT NULL",
            name="ck_kakao_collection_browser_running",
        ),
        Index(
            "uq_kakao_collection_browser_open",
            "profile_id",
            unique=True,
            postgresql_where=text("phase <> 'CLOSED'"),
        ),
    )
    browser_run_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(41), nullable=False)
    owner_operator_id: Mapped[str] = mapped_column(String(41), nullable=False)
    source_binding_id: Mapped[str] = mapped_column(String(45), nullable=False)
    profile_id: Mapped[str] = mapped_column(String(45), nullable=False)
    fence_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    epoch_number: Mapped[int] = mapped_column(Integer, nullable=False)
    command_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    dispatch_boot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    phase: Mapped[str] = mapped_column(String(16), nullable=False)
    resource_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    close_kind: Mapped[str | None] = mapped_column(String(32))
    browser_invocation_id: Mapped[str | None] = mapped_column(String(32))
    browser_pid: Mapped[int | None] = mapped_column(Integer)
    browser_monotonic_us: Mapped[int | None] = mapped_column(BigInteger)
    browser_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(32))
