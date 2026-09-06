"""add typed assessment occurrence navigation fields

Revision ID: 20260906_0030
Revises: 20260905_0029
Create Date: 2026-09-06 00:00:00 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260906_0030"
down_revision: str | None = "20260905_0029"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "assessment_occurrence_revisions",
        sa.Column(
            "schema_version",
            sa.String(48),
            nullable=False,
            server_default="assessment-occurrence-revision/1.0",
        ),
    )
    op.add_column(
        "assessment_occurrence_revisions",
        sa.Column("administration_month", sa.Integer()),
    )
    op.add_column(
        "assessment_occurrence_revisions",
        sa.Column("target_school_level", sa.String(24)),
    )
    op.add_column(
        "assessment_occurrence_revisions",
        sa.Column("target_grade", sa.Integer()),
    )
    op.create_check_constraint(
        "ck_assessment_occurrence_revision_schema",
        "assessment_occurrence_revisions",
        "schema_version IN ('assessment-occurrence-revision/1.0',"
        "'assessment-occurrence-revision/2.0')",
    )
    op.create_check_constraint(
        "ck_assessment_occurrence_typed_audience",
        "assessment_occurrence_revisions",
        "(schema_version = 'assessment-occurrence-revision/1.0' AND "
        "target_school_level IS NULL AND target_grade IS NULL AND "
        "administration_month IS NULL) OR "
        "(schema_version = 'assessment-occurrence-revision/2.0' AND "
        "target_school_level IS NOT NULL AND target_grade IS NOT NULL AND "
        "administration_month IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_assessment_occurrence_grade",
        "assessment_occurrence_revisions",
        "target_school_level IS NULL OR "
        "(target_school_level = 'ELEMENTARY' AND target_grade BETWEEN 1 AND 6) OR "
        "(target_school_level IN ('MIDDLE_SCHOOL','HIGH_SCHOOL') "
        "AND target_grade BETWEEN 1 AND 3)",
    )
    op.create_check_constraint(
        "ck_assessment_occurrence_month",
        "assessment_occurrence_revisions",
        "administration_month IS NULL OR administration_month BETWEEN 1 AND 12",
    )
    op.create_index(
        "ix_assessment_occurrence_audience_lookup",
        "assessment_occurrence_revisions",
        [
            "administration_year",
            "target_school_level",
            "target_grade",
            "administration_month",
            "subject_key",
            "assessment_occurrence_revision_id",
        ],
    )
    op.create_table(
        "assessment_item_occurrence_references",
        sa.Column("graph_snapshot_revision_id", sa.String(41), nullable=False),
        sa.Column("placement_node_id", sa.String(72), nullable=False),
        sa.Column("occurrence_node_id", sa.String(72), nullable=False),
        sa.Column("item_node_id", sa.String(72), nullable=False),
        sa.Column("analysis_run_id", sa.String(44), nullable=False),
        sa.Column("assessment_occurrence_id", sa.String(43), nullable=False),
        sa.Column("assessment_occurrence_revision_id", sa.String(41), nullable=False),
        sa.Column("assessment_occurrence_revision_sha256", sa.String(71), nullable=False),
        sa.Column("occurrence_display_label", sa.String(512), nullable=False),
        sa.Column("administration_year", sa.Integer(), nullable=False),
        sa.Column("administration_month", sa.Integer(), nullable=False),
        sa.Column("target_school_level", sa.String(24), nullable=False),
        sa.Column("target_grade", sa.Integer(), nullable=False),
        sa.Column("subject_key", sa.String(160), nullable=False),
        sa.Column("item_number", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.String(37), nullable=False),
        sa.Column("item_revision_id", sa.String(40), nullable=False),
        sa.Column("item_origin_profile_id", sa.String(46), nullable=False),
        sa.Column("extraction_acceptance_id", sa.String(47), nullable=False),
        sa.Column("assessment_source_bundle_revision_id", sa.String(48), nullable=False),
        sa.Column("placement_sha256", sa.String(71), nullable=False),
        sa.CheckConstraint(
            "placement_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "assessment_occurrence_revision_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_assessment_item_ref_hashes",
        ),
        sa.CheckConstraint(
            "administration_month BETWEEN 1 AND 12 AND item_number BETWEEN 1 AND 200",
            name="ck_assessment_item_ref_ranges",
        ),
        sa.CheckConstraint(
            "target_school_level IN ('ELEMENTARY','MIDDLE_SCHOOL','HIGH_SCHOOL')",
            name="ck_assessment_item_ref_school_level",
        ),
        sa.CheckConstraint(
            "(target_school_level = 'ELEMENTARY' AND target_grade BETWEEN 1 AND 6) OR "
            "(target_school_level IN ('MIDDLE_SCHOOL','HIGH_SCHOOL') "
            "AND target_grade BETWEEN 1 AND 3)",
            name="ck_assessment_item_ref_grade",
        ),
        sa.ForeignKeyConstraint(
            ["graph_snapshot_revision_id"],
            ["knowledge_graph_snapshots.graph_snapshot_revision_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["graph_snapshot_revision_id", "occurrence_node_id"],
            ["knowledge_nodes.graph_snapshot_revision_id", "knowledge_nodes.node_id"],
            name="fk_assessment_item_ref_occurrence_node",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["graph_snapshot_revision_id", "placement_node_id"],
            ["knowledge_nodes.graph_snapshot_revision_id", "knowledge_nodes.node_id"],
            name="fk_assessment_item_ref_placement_node",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["graph_snapshot_revision_id", "item_node_id"],
            ["knowledge_nodes.graph_snapshot_revision_id", "knowledge_nodes.node_id"],
            name="fk_assessment_item_ref_item_node",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"], ["knowledge_analysis_runs.analysis_run_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["assessment_occurrence_id"],
            ["assessment_occurrences.assessment_occurrence_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assessment_occurrence_revision_id"],
            ["assessment_occurrence_revisions.assessment_occurrence_revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["item_id"], ["items.item_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["item_revision_id"], ["item_revisions.item_revision_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["item_origin_profile_id"],
            ["item_origin_profiles.item_origin_profile_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["extraction_acceptance_id"],
            ["legacy_item_extraction_acceptances.acceptance_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assessment_source_bundle_revision_id"],
            ["assessment_source_bundle_revisions.assessment_source_bundle_revision_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "graph_snapshot_revision_id",
            "placement_node_id",
            name="pk_assessment_item_occurrence_references",
        ),
        sa.UniqueConstraint(
            "graph_snapshot_revision_id",
            "assessment_occurrence_revision_id",
            "item_number",
            name="uq_assessment_item_ref_exam_number",
        ),
        sa.UniqueConstraint(
            "graph_snapshot_revision_id",
            "analysis_run_id",
            name="uq_assessment_item_ref_analysis",
        ),
    )
    op.create_index(
        "ix_assessment_item_ref_exam_lookup",
        "assessment_item_occurrence_references",
        [
            "graph_snapshot_revision_id",
            "administration_year",
            "target_school_level",
            "target_grade",
            "administration_month",
            "subject_key",
            "item_number",
        ],
    )
    op.create_index(
        "ix_assessment_item_ref_item_revision",
        "assessment_item_occurrence_references",
        ["graph_snapshot_revision_id", "item_revision_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_assessment_item_ref_item_revision",
        table_name="assessment_item_occurrence_references",
    )
    op.drop_index(
        "ix_assessment_item_ref_exam_lookup",
        table_name="assessment_item_occurrence_references",
    )
    op.drop_table("assessment_item_occurrence_references")
    op.drop_index(
        "ix_assessment_occurrence_audience_lookup",
        table_name="assessment_occurrence_revisions",
    )
    op.drop_constraint(
        "ck_assessment_occurrence_month",
        "assessment_occurrence_revisions",
        type_="check",
    )
    op.drop_constraint(
        "ck_assessment_occurrence_grade",
        "assessment_occurrence_revisions",
        type_="check",
    )
    op.drop_constraint(
        "ck_assessment_occurrence_typed_audience",
        "assessment_occurrence_revisions",
        type_="check",
    )
    op.drop_constraint(
        "ck_assessment_occurrence_revision_schema",
        "assessment_occurrence_revisions",
        type_="check",
    )
    op.drop_column("assessment_occurrence_revisions", "target_grade")
    op.drop_column("assessment_occurrence_revisions", "target_school_level")
    op.drop_column("assessment_occurrence_revisions", "administration_month")
    op.drop_column("assessment_occurrence_revisions", "schema_version")
