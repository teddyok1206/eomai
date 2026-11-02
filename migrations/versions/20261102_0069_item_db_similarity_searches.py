"""Owned recent search intents and completed selectors, never result content.

Revision ID: 20261102_0069
Revises: 20261102_0068
Create Date: 2026-11-02 UTC
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261102_0069"
down_revision = "20261102_0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "item_db_similarity_searches",
        sa.Column("search_id", sa.String(41), primary_key=True),
        sa.Column(
            "operator_id",
            sa.String(41),
            sa.ForeignKey("operators.operator_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("intent_sha256", sa.String(71), nullable=False),
        sa.Column("input_json", postgresql.JSONB(), nullable=False),
        sa.Column("pinned_query", postgresql.JSONB(), nullable=True),
        sa.Column("children_json", postgresql.JSONB(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("device", sa.String(4), nullable=True),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("operator_id", "idempotency_key", name="uq_item_db_search_owner_key"),
        sa.CheckConstraint(
            "jsonb_typeof(input_json)='object' "
            "AND input_json ?& ARRAY['schema_version','selections','top_k'] "
            "AND input_json - ARRAY['schema_version','selections','top_k'] = '{}'::jsonb "
            "AND input_json->>'schema_version'='item-db-similarity-list-input/1.0' "
            "AND octet_length(input_json::text)<=65536 "
            "AND jsonb_typeof(input_json->'selections')='array' "
            "AND jsonb_array_length(input_json->'selections') BETWEEN 1 AND 32 "
            "AND jsonb_typeof(input_json->'top_k')='number' "
            "AND (input_json->>'top_k')::integer BETWEEN 1 AND 64 "
            "AND jsonb_typeof(children_json)='array' "
            "AND jsonb_array_length(children_json)<=32 "
            "AND octet_length(children_json::text)<=32768 "
            "AND (pinned_query IS NULL OR octet_length(pinned_query::text)<=65536)",
            name="ck_item_db_search_metadata_bounds",
        ),
        sa.CheckConstraint(
            "state IN ('PREPARING','PENDING','READY','FAILED','UNAVAILABLE') "
            "AND (device IS NULL OR device IN ('CPU','CUDA')) "
            "AND (state <> 'READY' OR (pinned_query IS NOT NULL "
            "AND jsonb_array_length(children_json)=jsonb_array_length(input_json->'selections')))",
            name="ck_item_db_search_state",
        ),
    )
    op.create_index(
        "ix_item_db_search_owner_recent",
        "item_db_similarity_searches",
        ["operator_id", sa.text("created_at DESC"), "search_id"],
    )


def downgrade() -> None:
    # Native canonical history remains in its original owners; refuse silent UI history loss.
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM item_db_similarity_searches)"))
        .scalar_one()
    ):
        raise RuntimeError("item DB search history must be preserved before downgrade")
    op.drop_index("ix_item_db_search_owner_recent", table_name="item_db_similarity_searches")
    op.drop_table("item_db_similarity_searches")
