"""One immutable provider-channel pin per logical binding; no intake queue or content."""

from datetime import datetime

from eom_orchestrator.models import Base
from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column


class KakaoManualChannelPinRecord(Base):
    __tablename__ = "kakao_manual_channel_pins"
    __table_args__ = (
        CheckConstraint(
            "channel_key_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND evidence_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_kakao_manual_channel_hashes",
        ),
        ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id"],
            [
                "kakao_channel_bindings.owner_operator_id",
                "kakao_channel_bindings.source_binding_id",
            ],
            name="fk_kakao_manual_channel_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["evidence_artifact_id", "evidence_artifact_revision_id"],
            ["artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"],
            name="fk_kakao_manual_channel_evidence",
            ondelete="RESTRICT",
        ),
    )
    source_binding_id: Mapped[str] = mapped_column(String(45), primary_key=True)
    owner_operator_id: Mapped[str] = mapped_column(String(41), nullable=False)
    channel_key_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    evidence_artifact_id: Mapped[str] = mapped_column(String(41), nullable=False)
    evidence_artifact_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
