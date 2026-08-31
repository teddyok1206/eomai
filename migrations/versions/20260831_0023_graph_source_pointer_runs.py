"""Pin graph source pointers to their exact accepted Analysis Run.

Revision ID: 20260831_0023
Revises: 20260828_0022
Create Date: 2026-08-31 02:30:00 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260831_0023"
down_revision: str | None = "20260828_0022"
branch_labels: str | None = None
depends_on: str | None = None

_POINTER_TABLES = (
    (
        "knowledge_node_source_pointers",
        "node_id",
        "uq_knowledge_node_source_pointer",
        "fk_knowledge_node_source_analysis",
    ),
    (
        "knowledge_edge_source_pointers",
        "edge_id",
        "uq_knowledge_edge_source_pointer",
        "fk_knowledge_edge_source_analysis",
    ),
)


def upgrade() -> None:
    connection = op.get_bind()
    for table_name, entity_column, unique_name, foreign_key_name in _POINTER_TABLES:
        op.add_column(table_name, sa.Column("analysis_run_id", sa.String(length=44), nullable=True))
        connection.execute(
            sa.text(
                f"UPDATE {table_name} AS pointer SET analysis_run_id = matched.analysis_run_id "
                "FROM ("
                "SELECT graph_snapshot_revision_id, source_revision_id, "
                "source_artifact_revision_id, min(analysis_run_id) AS analysis_run_id "
                "FROM knowledge_snapshot_analyses "
                "GROUP BY graph_snapshot_revision_id, source_revision_id, "
                "source_artifact_revision_id HAVING count(*) = 1"
                ") AS matched "
                "WHERE matched.graph_snapshot_revision_id = pointer.graph_snapshot_revision_id "
                "AND matched.source_revision_id = pointer.source_revision_id "
                "AND matched.source_artifact_revision_id = pointer.artifact_revision_id"
            )
        )
        unresolved = connection.execute(
            sa.text(f"SELECT count(*) FROM {table_name} WHERE analysis_run_id IS NULL")
        ).scalar_one()
        if unresolved:
            raise RuntimeError(
                f"{table_name} contains source pointers without one exact accepted Analysis Run"
            )
        op.alter_column(table_name, "analysis_run_id", nullable=False)
        op.drop_constraint(unique_name, table_name, type_="unique")
        op.create_unique_constraint(
            unique_name,
            table_name,
            [
                "graph_snapshot_revision_id",
                entity_column,
                "analysis_run_id",
                "source_revision_id",
                "artifact_revision_id",
                "member_path",
                "anchor_id",
            ],
        )
        op.create_foreign_key(
            foreign_key_name,
            table_name,
            "knowledge_snapshot_analyses",
            ["graph_snapshot_revision_id", "analysis_run_id"],
            ["graph_snapshot_revision_id", "analysis_run_id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    connection = op.get_bind()
    for table_name, entity_column, unique_name, foreign_key_name in reversed(_POINTER_TABLES):
        collision = connection.execute(
            sa.text(
                f"SELECT 1 FROM {table_name} GROUP BY graph_snapshot_revision_id, "
                f"{entity_column}, source_revision_id, artifact_revision_id, member_path, "
                "anchor_id HAVING count(*) > 1 LIMIT 1"
            )
        ).scalar_one_or_none()
        if collision is not None:
            raise RuntimeError(
                f"{table_name} contains run-scoped history that prevents safe downgrade"
            )
        op.drop_constraint(foreign_key_name, table_name, type_="foreignkey")
        op.drop_constraint(unique_name, table_name, type_="unique")
        op.create_unique_constraint(
            unique_name,
            table_name,
            [
                "graph_snapshot_revision_id",
                entity_column,
                "source_revision_id",
                "artifact_revision_id",
                "member_path",
                "anchor_id",
            ],
        )
        op.drop_column(table_name, "analysis_run_id")
