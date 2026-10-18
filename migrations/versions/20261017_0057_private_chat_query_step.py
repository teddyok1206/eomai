"""Permit only the exact private QUERY application step, not runtime admission.

Revision ID: 20261017_0057
Revises: 20261017_0056
Create Date: 2026-10-17 UTC
"""

from __future__ import annotations

from alembic import op

revision: str = "20261017_0057"
down_revision: str | None = "20261017_0056"
branch_labels: str | None = None
depends_on: str | None = None

# Frozen migration literals, independent of later model/admission changes.
_CHECK = "ck_workflow_step_runs_local_embedding"
_PREVIOUS_PREDICATE = (
    "(step_type = 'application') = "
    "(result_schema IS NOT DISTINCT FROM 'incremental-embedding-result@1.0' OR "
    "result_schema IS NOT DISTINCT FROM 'embedding-reference-query-result@1.0') "
    "AND (step_type <> 'application' OR (worker_role IS NULL AND ("
    "(result_schema = 'incremental-embedding-result@1.0' AND step_key = 'encode_batch') OR "
    "(result_schema = 'embedding-reference-query-result@1.0' "
    "AND step_key = 'encode_reference_query' AND attempt = 1))))"
)
_PREDICATE = (
    "(step_type = 'application') = "
    "(result_schema IS NOT DISTINCT FROM 'incremental-embedding-result@1.0' OR "
    "result_schema IS NOT DISTINCT FROM 'embedding-reference-query-result@1.0' OR "
    "result_schema IS NOT DISTINCT FROM 'embedding-private-chat-query-result@1.0') "
    "AND (step_type <> 'application' OR (worker_role IS NULL AND ("
    "(result_schema = 'incremental-embedding-result@1.0' AND step_key = 'encode_batch') OR "
    "(result_schema = 'embedding-reference-query-result@1.0' "
    "AND step_key = 'encode_reference_query' AND attempt = 1) OR "
    "(result_schema = 'embedding-private-chat-query-result@1.0' "
    "AND step_key = 'encode_private_chat_query' AND attempt = 1))))"
)
_REFUSE_PRIVATE_STEP_HISTORY = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM workflow_step_runs
        WHERE step_key = 'encode_private_chat_query'
           OR result_schema = 'embedding-private-chat-query-result@1.0'
           OR output_pointer_manifest ->> 'schema_version' = 'private-chat-query-step-output/1.0'
    ) THEN
        RAISE EXCEPTION 'private query downgrade requires absent private step history'
            USING ERRCODE = '23514';
    END IF;
END
$$
"""


def upgrade() -> None:
    op.drop_constraint(_CHECK, "workflow_step_runs", type_="check")
    op.create_check_constraint(_CHECK, "workflow_step_runs", _PREDICATE)


def downgrade() -> None:
    op.execute(_REFUSE_PRIVATE_STEP_HISTORY)
    op.drop_constraint(_CHECK, "workflow_step_runs", type_="check")
    op.create_check_constraint(_CHECK, "workflow_step_runs", _PREVIOUS_PREDICATE)
