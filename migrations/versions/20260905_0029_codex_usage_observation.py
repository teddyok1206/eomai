"""index immutable Codex slot usage observations

Revision ID: 20260905_0029
Revises: 20260904_0028
Create Date: 2026-09-05 00:00:00 UTC
"""

from __future__ import annotations

from alembic import op

revision: str = "20260905_0029"
down_revision: str | None = "20260904_0028"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_codex_control_command_latest_usage "
        "ON codex_control_commands (binding_id, processed_at, command_id) "
        "WHERE command_type = 'OBSERVE' AND state = 'SUCCEEDED' "
        "AND result_document ->> 'schema_version' = "
        "'codex-control-command-result/1.1'"
    )


def downgrade() -> None:
    op.drop_index("ix_codex_control_command_latest_usage", table_name="codex_control_commands")
