"""Add immutable Assembly educational-quality review workbench state.

Revision ID: 20261002_0045
Revises: 20260925_0044
Create Date: 2026-10-02 00:00:00+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261002_0045"
down_revision: str | None = "20260925_0044"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "educational_quality_review_plans",
        sa.Column("plan_id", sa.String(44), primary_key=True),
        sa.Column("plan_sha256", sa.String(71), nullable=False, unique=True),
        sa.Column(
            "assembly_id",
            sa.String(41),
            sa.ForeignKey("assessment_assemblies.assessment_assembly_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "assembly_revision_id",
            sa.String(44),
            sa.ForeignKey(
                "assessment_assembly_revisions.assessment_assembly_revision_id",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("assembly_manifest_sha256", sa.String(71), nullable=False),
        sa.Column("item_set_sha256", sa.String(71), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("secondary_positions", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_by",
            sa.String(128),
            sa.ForeignKey("operators.operator_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "item_count BETWEEN 1 AND 200", name="ck_educational_quality_plan_item_count"
        ),
        sa.UniqueConstraint(
            "assembly_revision_id", name="uq_educational_quality_plan_assembly_revision"
        ),
    )
    op.create_index(
        "ix_educational_quality_plan_created",
        "educational_quality_review_plans",
        ["created_at", "plan_id"],
    )
    op.create_table(
        "educational_quality_review_plan_items",
        sa.Column(
            "plan_id",
            sa.String(44),
            sa.ForeignKey("educational_quality_review_plans.plan_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("display_number", sa.String(32), nullable=False),
        sa.Column(
            "item_id",
            sa.String(37),
            sa.ForeignKey("items.item_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "item_revision_id",
            sa.String(40),
            sa.ForeignKey("item_revisions.item_revision_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("item_manifest_sha256", sa.String(71), nullable=False),
        sa.Column("material_type", sa.String(64), nullable=False),
        sa.Column("difficulty_band", sa.String(64)),
        sa.CheckConstraint(
            "position BETWEEN 1 AND 200", name="ck_educational_quality_plan_item_position"
        ),
        sa.UniqueConstraint(
            "plan_id", "item_revision_id", name="uq_educational_quality_plan_item_revision"
        ),
    )
    op.create_index(
        "ix_educational_quality_plan_item_revision",
        "educational_quality_review_plan_items",
        ["item_revision_id"],
    )
    op.create_table(
        "educational_quality_review_sessions",
        sa.Column("session_id", sa.String(47), primary_key=True),
        sa.Column(
            "plan_id",
            sa.String(44),
            sa.ForeignKey("educational_quality_review_plans.plan_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "reviewer_id",
            sa.String(128),
            sa.ForeignKey("operators.operator_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reviewer_role", sa.String(16), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("submission_sha256", sa.String(71)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finalized_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "reviewer_role IN ('PRIMARY','SECONDARY')",
            name="ck_educational_quality_session_role",
        ),
        sa.CheckConstraint(
            "state IN ('DRAFT','FINALIZED')", name="ck_educational_quality_session_state"
        ),
        sa.CheckConstraint(
            "lock_version >= 1 AND ((state = 'DRAFT' AND finalized_at IS NULL) OR "
            "(state = 'FINALIZED' AND finalized_at IS NOT NULL))",
            name="ck_educational_quality_session_lifecycle",
        ),
        sa.UniqueConstraint(
            "plan_id", "reviewer_role", name="uq_educational_quality_session_plan_role"
        ),
        sa.UniqueConstraint(
            "plan_id",
            "reviewer_id",
            name="uq_educational_quality_session_independent_reviewer",
        ),
    )
    op.create_index(
        "ix_educational_quality_session_plan",
        "educational_quality_review_sessions",
        ["plan_id", "reviewer_role", "state"],
    )
    op.create_table(
        "educational_quality_review_observations",
        sa.Column(
            "session_id",
            sa.String(47),
            sa.ForeignKey("educational_quality_review_sessions.session_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column(
            "item_revision_id",
            sa.String(40),
            sa.ForeignKey("item_revisions.item_revision_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("preview_checked", sa.Boolean(), nullable=False),
        sa.Column("hwpx_checked", sa.Boolean(), nullable=False),
        sa.Column("evidence_checked", sa.Boolean(), nullable=False),
        sa.Column("science_score", sa.Integer(), nullable=False),
        sa.Column("critical_error", sa.Boolean(), nullable=False),
        sa.Column("unique_answer", sa.String(16), nullable=False),
        sa.Column("evidence_score", sa.Integer(), nullable=False),
        sa.Column("authoring_value_score", sa.Integer(), nullable=False),
        sa.Column("visual_score", sa.Integer()),
        sa.Column("visual_not_applicable_reason", sa.String(240)),
        sa.Column("explanation_quality_score", sa.Integer(), nullable=False),
        sa.Column("disposition", sa.String(16), nullable=False),
        sa.Column("edit_minutes", sa.Integer(), nullable=False),
        sa.Column("short_reason", sa.Text(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "position BETWEEN 1 AND 200 AND science_score BETWEEN 1 AND 5 "
            "AND evidence_score BETWEEN 1 AND 5 AND authoring_value_score BETWEEN 1 AND 5 "
            "AND explanation_quality_score BETWEEN 1 AND 5 "
            "AND (visual_score IS NULL OR visual_score BETWEEN 1 AND 5) "
            "AND edit_minutes BETWEEN 0 AND 1440",
            name="ck_educational_quality_observation_bounds",
        ),
        sa.CheckConstraint(
            "unique_answer IN ('PASS','FAIL','AMBIGUOUS')",
            name="ck_educational_quality_observation_unique_answer",
        ),
        sa.CheckConstraint(
            "disposition IN ('NO_EDIT','MINOR_EDIT','MAJOR_EDIT','DISCARD')",
            name="ck_educational_quality_observation_disposition",
        ),
        sa.CheckConstraint(
            "(visual_score IS NULL) = (visual_not_applicable_reason IS NOT NULL)",
            name="ck_educational_quality_observation_visual",
        ),
    )
    op.create_index(
        "ix_educational_quality_observation_item",
        "educational_quality_review_observations",
        ["item_revision_id"],
    )
    op.create_table(
        "educational_quality_review_resolutions",
        sa.Column(
            "plan_id",
            sa.String(44),
            sa.ForeignKey("educational_quality_review_plans.plan_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column(
            "chosen_session_id",
            sa.String(47),
            sa.ForeignKey("educational_quality_review_sessions.session_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "resolved_by",
            sa.String(128),
            sa.ForeignKey("operators.operator_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column(
            "resolved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "position BETWEEN 1 AND 200", name="ck_educational_quality_resolution_position"
        ),
    )
    op.create_index(
        "ix_educational_quality_resolution_session",
        "educational_quality_review_resolutions",
        ["chosen_session_id"],
    )
    op.execute(
        """
        CREATE FUNCTION reject_educational_quality_immutable_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'educational quality immutable record cannot be changed';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in (
        "educational_quality_review_plans",
        "educational_quality_review_plan_items",
        "educational_quality_review_resolutions",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_educational_quality_immutable_mutation()"
        )
    op.execute(
        """
        CREATE FUNCTION guard_educational_quality_session_mutation() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'educational quality sessions cannot be deleted';
          END IF;
          IF OLD.state = 'FINALIZED' THEN
            RAISE EXCEPTION 'finalized educational quality session is immutable';
          END IF;
          IF NEW.plan_id <> OLD.plan_id OR NEW.reviewer_id <> OLD.reviewer_id
             OR NEW.reviewer_role <> OLD.reviewer_role OR NEW.created_at <> OLD.created_at THEN
            RAISE EXCEPTION 'educational quality session identity is immutable';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER educational_quality_session_guard BEFORE UPDATE OR DELETE ON "
        "educational_quality_review_sessions FOR EACH ROW EXECUTE FUNCTION "
        "guard_educational_quality_session_mutation()"
    )
    op.execute(
        """
        CREATE FUNCTION guard_educational_quality_observation_mutation() RETURNS trigger AS $$
        DECLARE parent_state text;
        DECLARE parent_session_id text;
        BEGIN
          IF TG_OP = 'DELETE' THEN
            parent_session_id := OLD.session_id;
          ELSE
            parent_session_id := NEW.session_id;
          END IF;
          SELECT state INTO parent_state FROM educational_quality_review_sessions
            WHERE session_id = parent_session_id;
          IF parent_state <> 'DRAFT' THEN
            RAISE EXCEPTION 'finalized educational quality observations are immutable';
          END IF;
          IF TG_OP = 'UPDATE'
             AND (NEW.session_id <> OLD.session_id OR NEW.position <> OLD.position) THEN
            RAISE EXCEPTION 'educational quality observation identity is immutable';
          END IF;
          IF TG_OP = 'DELETE' THEN
            RETURN OLD;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER educational_quality_observation_guard BEFORE INSERT OR UPDATE OR DELETE "
        "ON educational_quality_review_observations FOR EACH ROW EXECUTE FUNCTION "
        "guard_educational_quality_observation_mutation()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS educational_quality_observation_guard ON "
        "educational_quality_review_observations"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_educational_quality_observation_mutation()")
    op.execute(
        "DROP TRIGGER IF EXISTS educational_quality_session_guard ON "
        "educational_quality_review_sessions"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_educational_quality_session_mutation()")
    for table in (
        "educational_quality_review_resolutions",
        "educational_quality_review_plan_items",
        "educational_quality_review_plans",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS reject_educational_quality_immutable_mutation()")
    op.drop_table("educational_quality_review_resolutions")
    op.drop_table("educational_quality_review_observations")
    op.drop_table("educational_quality_review_sessions")
    op.drop_table("educational_quality_review_plan_items")
    op.drop_table("educational_quality_review_plans")
