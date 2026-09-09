"""Pointer-only authority for deterministic PDF learning completion observations."""

from __future__ import annotations

from datetime import datetime

from eom_orchestrator.models import Base
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column


class PdfLearningCompletionObservationRecord(Base):
    """First truthful stable observation for one semantic completion identity.

    The 520 proof remains in immutable Artifacts.  This row stores only the identities needed to
    serialize concurrent construction and to replay the first observation timestamp exactly.
    """

    __tablename__ = "pdf_learning_completion_observations"
    __table_args__ = (
        CheckConstraint(
            "completion_identity_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND mutable_fingerprint_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND source_archive_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND inventory_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND graph_snapshot_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_pdf_learning_completion_observation_hashes",
        ),
        CheckConstraint(
            "source_commit ~ '^[0-9a-f]{40}$' AND source_tree ~ '^[0-9a-f]{40}$'",
            name="ck_pdf_learning_completion_observation_source_release",
        ),
    )

    completion_identity_sha256: Mapped[str] = mapped_column(String(71), primary_key=True)
    mutable_fingerprint_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    source_commit: Mapped[str] = mapped_column(String(40), nullable=False)
    source_tree: Mapped[str] = mapped_column(String(40), nullable=False)
    source_archive_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    inventory_id: Mapped[str] = mapped_column(String(48), nullable=False)
    inventory_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    original_batch_id: Mapped[str] = mapped_column(String(44), nullable=False)
    successor_batch_id: Mapped[str] = mapped_column(String(44), nullable=False)
    recovery_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    coverage_id: Mapped[str] = mapped_column(String(45), nullable=False)
    graph_snapshot_revision_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_graph_snapshots.graph_snapshot_revision_id", ondelete="RESTRICT"),
        nullable=False,
    )
    graph_snapshot_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    requested_by_operator_id: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = ["PdfLearningCompletionObservationRecord"]
