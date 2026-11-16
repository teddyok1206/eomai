"""Small collection intent and ordered room checkpoints, without message/file payloads."""

from datetime import datetime

from eom_orchestrator.models import Base
from sqlalchemy import (
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


class KakaoCollectionRunRecord(Base):
    __tablename__ = "kakao_collection_runs"
    __table_args__ = (
        UniqueConstraint(
            "owner_operator_id",
            "source_binding_id",
            "idempotency_key",
            name="uq_kakao_collection_replay",
        ),
        UniqueConstraint(
            "owner_operator_id", "source_binding_id", "run_id", name="uq_kakao_collection_owner"
        ),
        ForeignKeyConstraint(
            ["run_id", "current_browser_run_id"],
            ["kakao_collection_browsers.run_id", "kakao_collection_browsers.browser_run_id"],
            name="fk_kakao_collection_current_browser",
            ondelete="RESTRICT",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id", "anchor_room_id"],
            [
                "kakao_rooms.owner_operator_id",
                "kakao_rooms.source_binding_id",
                "kakao_rooms.room_id",
            ],
            name="fk_kakao_collection_room",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_binding_id", "capability_revision_id"],
            [
                "kakao_capability_acceptances.source_binding_id",
                "kakao_capability_acceptances.capability_revision_id",
            ],
            name="fk_kakao_collection_capability",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_binding_id", "policy_revision_id"],
            [
                "kakao_collection_policy_revisions.source_binding_id",
                "kakao_collection_policy_revisions.policy_revision_id",
            ],
            name="fk_kakao_collection_policy",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "run_id ~ '^kakaorun_[0-9a-f]{32}$' AND "
            "idempotency_key ~ '^[!-~]{16,128}$' AND "
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "policy_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "adapter_release_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_kakao_collection_values",
        ),
        CheckConstraint(
            "state IN ('QUEUED','INVENTORY','COLLECTING','RECONCILING','PAUSING','PAUSED',"
            "'AUTH_REQUIRED','COMPLETED','PARTIAL','FAILED','CANCELLED')",
            name="ck_kakao_collection_state",
        ),
        CheckConstraint(
            "resource_version BETWEEN 1 AND 2147483647 AND "
            "accepted_binding_version BETWEEN 1 AND 2147483647 AND updated_at >= created_at",
            name="ck_kakao_collection_version",
        ),
        CheckConstraint(
            "(state = 'PAUSING' AND stop_target IS NOT NULL "
            "AND stop_target IN ('PAUSED','CANCELLED')) OR "
            "(state <> 'PAUSING' AND stop_target IS NULL)",
            name="ck_kakao_collection_stop_target",
        ),
        Index(
            "uq_kakao_collection_active_binding",
            "source_binding_id",
            unique=True,
            postgresql_where=text("state NOT IN ('COMPLETED','PARTIAL','FAILED','CANCELLED')"),
        ),
        Index("ix_kakao_collection_pending", "state", "created_at", "run_id"),
    )
    run_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    owner_operator_id: Mapped[str] = mapped_column(String(41), nullable=False)
    source_binding_id: Mapped[str] = mapped_column(String(45), nullable=False)
    anchor_room_id: Mapped[str] = mapped_column(String(42), nullable=False)
    capability_revision_id: Mapped[str] = mapped_column(String(51), nullable=False)
    policy_revision_id: Mapped[str] = mapped_column(String(47), nullable=False)
    policy_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    adapter_release_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    accepted_binding_version: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    stop_target: Mapped[str | None] = mapped_column(String(16))
    resource_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_browser_run_id: Mapped[str | None] = mapped_column(String(48))


class KakaoCollectionTaskRecord(Base):
    __tablename__ = "kakao_collection_tasks"
    __table_args__ = (
        UniqueConstraint("run_id", "ordinal", name="uq_kakao_collection_task_order"),
        UniqueConstraint("run_id", "room_id", name="uq_kakao_collection_task_room"),
        ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id", "run_id"],
            [
                "kakao_collection_runs.owner_operator_id",
                "kakao_collection_runs.source_binding_id",
                "kakao_collection_runs.run_id",
            ],
            name="fk_kakao_collection_task_run",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id", "room_id"],
            [
                "kakao_rooms.owner_operator_id",
                "kakao_rooms.source_binding_id",
                "kakao_rooms.room_id",
            ],
            name="fk_kakao_collection_task_room",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "task_id ~ '^kakaotask_[0-9a-f]{32}$' AND ordinal BETWEEN 1 AND 10000",
            name="ck_kakao_collection_task_values",
        ),
        CheckConstraint(
            "state IN ('QUEUED','RUNNING','LOCAL_ACCEPTED','COMPLETED','PARTIAL',"
            "'FAILED','CANCELLED')",
            name="ck_kakao_collection_task_state",
        ),
        Index("ix_kakao_collection_task_claim", "run_id", "state", "ordinal"),
    )
    task_id: Mapped[str] = mapped_column(String(42), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(41), nullable=False)
    owner_operator_id: Mapped[str] = mapped_column(String(41), nullable=False)
    source_binding_id: Mapped[str] = mapped_column(String(45), nullable=False)
    room_id: Mapped[str] = mapped_column(String(42), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
