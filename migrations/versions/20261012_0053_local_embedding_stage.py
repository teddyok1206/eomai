"""Add only fixed native Workflow guards; no authority, state or queue is created.

Revision ID: 20261012_0053
Revises: 20261012_0052
Create Date: 2026-10-12 UTC
"""

from __future__ import annotations

from alembic import op

revision: str = "20261012_0053"
down_revision: str | None = "20261012_0052"
branch_labels: str | None = None
depends_on: str | None = None

# Frozen history: never import current models or admission policy in migrations.
_STAGE_CHECK = "ck_workflow_instances_stage"
_NATIVE_STEP_CHECK = "ck_workflow_step_runs_local_embedding"
_PREVIOUS_STAGES = (
    "'KNOWLEDGE_ANALYSIS','CUSTOMER_SUPPORT','DOCUMENT_REVIEW','INFERENCE_TRANSFER',"
    "'AUTHORING','IMAGE_REQUIRED','IMAGE_SKIPPED','REVIEWING','AWAITING_HUMAN_APPROVAL',"
    "'REGISTERING','COMPLETED','FAILED','CANCELLED'"
)
_NATIVE_STEP_PREDICATE = (
    "(step_type = 'application') = "
    "(result_schema IS NOT DISTINCT FROM 'incremental-embedding-result@1.0') "
    "AND (step_type <> 'application' OR (worker_role IS NULL AND step_key = 'encode_batch'))"
)
_REFUSE_NATIVE_HISTORY = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM workflow_definitions
        WHERE definition_key = 'local-embedding-index'
           OR canonical_definition ->> 'definition_key' = 'local-embedding-index'
    ) OR EXISTS (
        SELECT 1 FROM workflow_instances
        WHERE definition_key = 'local-embedding-index'
           OR stage = 'LOCAL_EMBEDDING'
           OR role_schema_version = 'local-embedding/1.0'
           OR (initial_request ->> 'request_name' = 'LOCAL_EMBEDDING_WORKFLOW_REQUEST' AND (
               initial_request ->> 'schema_version' = 'local-embedding-workflow-request/1.0'
               OR (initial_request ->> 'schema_version' = 'local-embedding-workflow-request/1.1'
                   AND initial_request ->> 'purpose' = 'LOCAL_EMBEDDING')))
           OR (request_payload ->> 'request_name' = 'LOCAL_EMBEDDING_WORKFLOW_REQUEST' AND (
               request_payload ->> 'schema_version' = 'local-embedding-workflow-request/1.0'
               OR (request_payload ->> 'schema_version' = 'local-embedding-workflow-request/1.1'
                   AND request_payload ->> 'purpose' = 'LOCAL_EMBEDDING')))
    ) OR EXISTS (
        SELECT 1 FROM workflow_step_runs
        WHERE step_type = 'application'
           OR result_schema = 'incremental-embedding-result@1.0'
           OR output_pointer_manifest ->> 'schema_version' = 'local-embedding-step-output/1.0'
    ) THEN
        RAISE EXCEPTION 'local embedding downgrade requires absent native Workflow history'
            USING ERRCODE = '23514';
    END IF;
END
$$
"""


def upgrade() -> None:
    op.drop_constraint(_STAGE_CHECK, "workflow_instances", type_="check")
    op.create_check_constraint(
        _STAGE_CHECK, "workflow_instances", "stage IN (" + _PREVIOUS_STAGES + ",'LOCAL_EMBEDDING')"
    )
    op.create_check_constraint(_NATIVE_STEP_CHECK, "workflow_step_runs", _NATIVE_STEP_PREDICATE)


def downgrade() -> None:
    # Completed native rows no longer carry their initial stage; inspect identity
    # and exact native snapshots too. Refuse BEFORE DDL, never erase/reinterpret them.
    op.execute(_REFUSE_NATIVE_HISTORY)
    op.drop_constraint(_NATIVE_STEP_CHECK, "workflow_step_runs", type_="check")
    op.drop_constraint(_STAGE_CHECK, "workflow_instances", type_="check")
    op.create_check_constraint(
        _STAGE_CHECK, "workflow_instances", "stage IN (" + _PREVIOUS_STAGES + ")"
    )
