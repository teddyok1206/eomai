"""Permit the exact QUERY application-step pair; no owner/admission/data mutation.

Revision ID: 20261013_0054
Revises: 20261012_0053
Create Date: 2026-10-13 UTC
"""

from __future__ import annotations

from alembic import op

revision: str = "20261013_0054"
down_revision: str | None = "20261012_0053"
branch_labels: str | None = None
depends_on: str | None = None

# Frozen literals: never import current model/admission code from a migration.
_CHECK = "ck_workflow_step_runs_local_embedding"
_PREVIOUS_PREDICATE = (
    "(step_type = 'application') = "
    "(result_schema IS NOT DISTINCT FROM 'incremental-embedding-result@1.0') "
    "AND (step_type <> 'application' OR (worker_role IS NULL AND step_key = 'encode_batch'))"
)
_PREDICATE = (
    "(step_type = 'application') = "
    "(result_schema IS NOT DISTINCT FROM 'incremental-embedding-result@1.0' OR "
    "result_schema IS NOT DISTINCT FROM 'embedding-reference-query-result@1.0') "
    "AND (step_type <> 'application' OR (worker_role IS NULL AND ("
    "(result_schema = 'incremental-embedding-result@1.0' AND step_key = 'encode_batch') OR "
    "(result_schema = 'embedding-reference-query-result@1.0' "
    "AND step_key = 'encode_reference_query' AND attempt = 1))))"
)
_REFUSE_QUERY_HISTORY = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM workflow_definitions
        WHERE definition_key = 'local-embedding-reference-query'
           OR canonical_definition ->> 'definition_key' = 'local-embedding-reference-query'
    ) OR EXISTS (
        SELECT 1 FROM workflow_instances
        WHERE definition_key = 'local-embedding-reference-query'
           OR role_schema_version = 'reference-query/1.0'
           OR initial_request ->> 'schema_version' = 'reference-query-workflow-request/1.0'
           OR request_payload ->> 'schema_version' = 'reference-query-workflow-request/1.0'
           OR initial_request ->> 'purpose' = 'REFERENCE_QUERY'
           OR request_payload ->> 'purpose' = 'REFERENCE_QUERY'
    ) OR EXISTS (
        SELECT 1 FROM workflow_step_runs
        WHERE step_key = 'encode_reference_query'
           OR result_schema = 'embedding-reference-query-result@1.0'
           OR output_pointer_manifest ->> 'schema_version' = 'reference-query-step-output/1.0'
    ) THEN
        RAISE EXCEPTION 'reference query downgrade requires absent QUERY Workflow history'
            USING ERRCODE = '23514';
    END IF;
END
$$
"""


def upgrade() -> None:
    op.drop_constraint(_CHECK, "workflow_step_runs", type_="check")
    op.create_check_constraint(_CHECK, "workflow_step_runs", _PREDICATE)


def downgrade() -> None:
    op.execute(_REFUSE_QUERY_HISTORY)
    op.drop_constraint(_CHECK, "workflow_step_runs", type_="check")
    op.create_check_constraint(_CHECK, "workflow_step_runs", _PREVIOUS_PREDICATE)
