"""API-owned persistence for human educational-quality evaluation."""

from __future__ import annotations

from datetime import datetime

from eom_orchestrator.models import Base
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class EducationalQualityReviewPlanRecord(Base):
    __tablename__ = "educational_quality_review_plans"
    __table_args__ = (
        CheckConstraint(
            "item_count BETWEEN 1 AND 200", name="ck_educational_quality_plan_item_count"
        ),
        UniqueConstraint(
            "assembly_revision_id", name="uq_educational_quality_plan_assembly_revision"
        ),
        Index("ix_educational_quality_plan_created", "created_at", "plan_id"),
    )

    plan_id: Mapped[str] = mapped_column(String(44), primary_key=True)
    plan_sha256: Mapped[str] = mapped_column(String(71), unique=True, nullable=False)
    assembly_id: Mapped[str] = mapped_column(
        ForeignKey("assessment_assemblies.assessment_assembly_id", ondelete="RESTRICT"),
        nullable=False,
    )
    assembly_revision_id: Mapped[str] = mapped_column(
        ForeignKey(
            "assessment_assembly_revisions.assessment_assembly_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    assembly_manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    item_set_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    secondary_positions: Mapped[list[int]] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EducationalQualityReviewPlanItemRecord(Base):
    __tablename__ = "educational_quality_review_plan_items"
    __table_args__ = (
        CheckConstraint(
            "position BETWEEN 1 AND 200", name="ck_educational_quality_plan_item_position"
        ),
        UniqueConstraint(
            "plan_id", "item_revision_id", name="uq_educational_quality_plan_item_revision"
        ),
        Index("ix_educational_quality_plan_item_revision", "item_revision_id"),
    )

    plan_id: Mapped[str] = mapped_column(
        ForeignKey("educational_quality_review_plans.plan_id", ondelete="CASCADE"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    display_number: Mapped[str] = mapped_column(String(32), nullable=False)
    item_id: Mapped[str] = mapped_column(
        ForeignKey("items.item_id", ondelete="RESTRICT"), nullable=False
    )
    item_revision_id: Mapped[str] = mapped_column(
        ForeignKey("item_revisions.item_revision_id", ondelete="RESTRICT"), nullable=False
    )
    item_manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    material_type: Mapped[str] = mapped_column(String(64), nullable=False)
    difficulty_band: Mapped[str | None] = mapped_column(String(64))


class EducationalQualityReviewSessionRecord(Base):
    __tablename__ = "educational_quality_review_sessions"
    __table_args__ = (
        CheckConstraint(
            "reviewer_role IN ('PRIMARY','SECONDARY')",
            name="ck_educational_quality_session_role",
        ),
        CheckConstraint(
            "state IN ('DRAFT','FINALIZED')", name="ck_educational_quality_session_state"
        ),
        CheckConstraint(
            "lock_version >= 1 AND ((state = 'DRAFT' AND finalized_at IS NULL) OR "
            "(state = 'FINALIZED' AND finalized_at IS NOT NULL))",
            name="ck_educational_quality_session_lifecycle",
        ),
        UniqueConstraint(
            "plan_id", "reviewer_role", name="uq_educational_quality_session_plan_role"
        ),
        UniqueConstraint(
            "plan_id", "reviewer_id", name="uq_educational_quality_session_independent_reviewer"
        ),
        UniqueConstraint(
            "session_id", "plan_id", name="uq_educational_quality_session_identity_plan"
        ),
        Index("ix_educational_quality_session_plan", "plan_id", "reviewer_role", "state"),
    )

    session_id: Mapped[str] = mapped_column(String(47), primary_key=True)
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("educational_quality_review_plans.plan_id", ondelete="RESTRICT"),
        nullable=False,
    )
    reviewer_id: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    reviewer_role: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    submission_sha256: Mapped[str | None] = mapped_column(String(71))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EducationalQualityReviewObservationRecord(Base):
    __tablename__ = "educational_quality_review_observations"
    __table_args__ = (
        CheckConstraint(
            "position BETWEEN 1 AND 200 AND science_score BETWEEN 1 AND 5 "
            "AND evidence_score BETWEEN 1 AND 5 AND authoring_value_score BETWEEN 1 AND 5 "
            "AND explanation_quality_score BETWEEN 1 AND 5 "
            "AND (visual_score IS NULL OR visual_score BETWEEN 1 AND 5) "
            "AND edit_minutes BETWEEN 0 AND 1440",
            name="ck_educational_quality_observation_bounds",
        ),
        CheckConstraint(
            "unique_answer IN ('PASS','FAIL','AMBIGUOUS')",
            name="ck_educational_quality_observation_unique_answer",
        ),
        CheckConstraint(
            "disposition IN ('NO_EDIT','MINOR_EDIT','MAJOR_EDIT','DISCARD')",
            name="ck_educational_quality_observation_disposition",
        ),
        CheckConstraint(
            "(visual_score IS NULL) = (visual_not_applicable_reason IS NOT NULL)",
            name="ck_educational_quality_observation_visual",
        ),
        Index("ix_educational_quality_observation_item", "item_revision_id"),
    )

    session_id: Mapped[str] = mapped_column(
        ForeignKey("educational_quality_review_sessions.session_id", ondelete="CASCADE"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_revision_id: Mapped[str] = mapped_column(
        ForeignKey("item_revisions.item_revision_id", ondelete="RESTRICT"), nullable=False
    )
    preview_checked: Mapped[bool]
    hwpx_checked: Mapped[bool]
    evidence_checked: Mapped[bool]
    science_score: Mapped[int] = mapped_column(Integer, nullable=False)
    critical_error: Mapped[bool]
    unique_answer: Mapped[str] = mapped_column(String(16), nullable=False)
    evidence_score: Mapped[int] = mapped_column(Integer, nullable=False)
    authoring_value_score: Mapped[int] = mapped_column(Integer, nullable=False)
    visual_score: Mapped[int | None] = mapped_column(Integer)
    visual_not_applicable_reason: Mapped[str | None] = mapped_column(String(240))
    explanation_quality_score: Mapped[int] = mapped_column(Integer, nullable=False)
    disposition: Mapped[str] = mapped_column(String(16), nullable=False)
    edit_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    short_reason: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class EducationalQualityReviewResolutionRecord(Base):
    __tablename__ = "educational_quality_review_resolutions"
    __table_args__ = (
        CheckConstraint(
            "position BETWEEN 1 AND 200", name="ck_educational_quality_resolution_position"
        ),
        ForeignKeyConstraint(
            ("chosen_session_id", "plan_id"),
            (
                "educational_quality_review_sessions.session_id",
                "educational_quality_review_sessions.plan_id",
            ),
            name="fk_quality_resolution_session_plan",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("chosen_session_id", "position"),
            (
                "educational_quality_review_observations.session_id",
                "educational_quality_review_observations.position",
            ),
            name="fk_quality_resolution_observation",
            ondelete="RESTRICT",
        ),
        Index("ix_educational_quality_resolution_session", "chosen_session_id"),
    )

    plan_id: Mapped[str] = mapped_column(
        ForeignKey("educational_quality_review_plans.plan_id", ondelete="CASCADE"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    chosen_session_id: Mapped[str] = mapped_column(String(47), nullable=False)
    resolved_by: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    notes: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
