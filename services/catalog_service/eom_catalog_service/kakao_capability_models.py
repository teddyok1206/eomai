"""Immutable exact capability acceptances; not an activation head, queue or source body."""

from datetime import datetime

from eom_orchestrator.models import Base
from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column


class KakaoCapabilityAcceptanceRecord(Base):
    __tablename__ = "kakao_capability_acceptances"
    __table_args__ = (
        UniqueConstraint(
            "owner_operator_id",
            "source_binding_id",
            "idempotency_key",
            name="uq_kakao_capability_replay",
        ),
        UniqueConstraint(
            "source_binding_id", "capability_revision_id", name="uq_kakao_capability_binding"
        ),
        ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id", "room_id"],
            [
                "kakao_rooms.owner_operator_id",
                "kakao_rooms.source_binding_id",
                "kakao_rooms.room_id",
            ],
            name="fk_kakao_capability_room",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["manifest_artifact_id", "manifest_artifact_revision_id"],
            ["artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"],
            name="fk_kakao_capability_manifest",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "capability_revision_id ~ '^kakaocapabilityrev_[0-9a-f]{32}$' "
            "AND request_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND manifest_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND adapter_release_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND idempotency_key ~ '^[!-~]{16,128}$'",
            name="ck_kakao_capability_values",
        ),
    )
    capability_revision_id: Mapped[str] = mapped_column(String(51), primary_key=True)
    owner_operator_id: Mapped[str] = mapped_column(String(41), nullable=False)
    source_binding_id: Mapped[str] = mapped_column(String(45), nullable=False)
    room_id: Mapped[str] = mapped_column(String(42), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    manifest_artifact_id: Mapped[str] = mapped_column(String(41), nullable=False)
    manifest_artifact_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    adapter_release_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
