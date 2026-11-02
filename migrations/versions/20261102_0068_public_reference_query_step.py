"""Admit the released public reference-query2 application-step tuple.

Revision ID: 20261102_0068
Revises: 20261101_0067
Create Date: 2026-11-02 UTC
"""

from __future__ import annotations

from alembic import op

revision: str = "20261102_0068"
down_revision: str | None = "20261101_0067"
branch_labels: str | None = None
depends_on: str | None = None

_CHECK = "ck_workflow_step_runs_local_embedding"
# Frozen predecessor predicate; never import a mutable model or another migration.
_PREVIOUS = (
    "(step_type = 'application') = (result_schema IS NOT DISTINCT FROM "
    "'incremental-embedding-result@1.0' OR result_schema IS NOT DISTINCT FROM "
    "'embedding-reference-query-result@1.0' OR result_schema IS NOT DISTINCT FROM "
    "'embedding-reference-query-result@2.0' OR result_schema IS NOT DISTINCT FROM "
    "'embedding-private-chat-query-result@1.0') AND (step_type <> 'application' OR "
    "(worker_role IS NULL AND ((result_schema = 'incremental-embedding-result@1.0' AND "
    "step_key = 'encode_batch') OR (result_schema = 'embedding-reference-query-result@1.0' "
    "AND step_key = 'encode_reference_query' AND attempt = 1) OR (result_schema = "
    "'embedding-private-chat-query-result@1.0' AND step_key = 'encode_private_chat_query' "
    "AND attempt = 1) OR (result_schema = 'embedding-reference-query-result@2.0' AND "
    "step_key = 'encode_private_chat_query' AND attempt = 1))))"
)
_CURRENT = (
    "(step_type = 'application') = (result_schema IS NOT DISTINCT FROM "
    "'incremental-embedding-result@1.0' OR result_schema IS NOT DISTINCT FROM "
    "'embedding-reference-query-result@1.0' OR result_schema IS NOT DISTINCT FROM "
    "'embedding-reference-query-result@2.0' OR result_schema IS NOT DISTINCT FROM "
    "'embedding-private-chat-query-result@1.0') AND (step_type <> 'application' OR "
    "(worker_role IS NULL AND ((result_schema = 'incremental-embedding-result@1.0' AND "
    "step_key = 'encode_batch') OR (result_schema = 'embedding-reference-query-result@1.0' "
    "AND step_key = 'encode_reference_query' AND attempt = 1) OR (result_schema = "
    "'embedding-private-chat-query-result@1.0' AND step_key = 'encode_private_chat_query' "
    "AND attempt = 1) OR (result_schema = 'embedding-reference-query-result@2.0' AND "
    "step_key IN ('encode_private_chat_query','encode_reference_query') AND attempt = 1))))"
)
_FAMILY_FUNCTION = """
CREATE FUNCTION __QUALIFIED_FUNCTION__() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,app AS $$
DECLARE parent_family text;
BEGIN
    IF NEW.result_schema IS DISTINCT FROM 'embedding-reference-query-result@2.0' THEN
        RETURN NEW;
    END IF;
    EXECUTE format('SELECT definition_key FROM %I.workflow_instances WHERE workflow_id=$1',
                   TG_TABLE_SCHEMA) INTO parent_family USING NEW.workflow_id;
    IF NOT (
        (parent_family = 'local-embedding-reference-query'
         AND NEW.step_key = 'encode_reference_query') OR
        (parent_family = 'local-embedding-private-chat-query'
         AND NEW.step_key = 'encode_private_chat_query')
    ) IS TRUE THEN
        RAISE EXCEPTION 'reference query2 step family mismatch'
            USING ERRCODE='23514', CONSTRAINT='ck_workflow_step_runs_local_embedding';
    END IF;
    RETURN NEW;
END $$
"""


def _family_function_name() -> str:
    bind = op.get_bind()
    schema = bind.exec_driver_sql(
        "SELECT n.nspname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE c.oid='workflow_step_runs'::regclass"
    ).scalar_one()
    # Qualify against the same resolved relation, not function search-path lookup.
    # This also keeps transactional temporary-table migration tests isolated.
    return (
        bind.dialect.identifier_preparer.quote_schema(schema)
        + ".enforce_reference_query2_step_family"
    )


def upgrade() -> None:
    function = _family_function_name()
    op.drop_constraint(_CHECK, "workflow_step_runs", type_="check")
    op.create_check_constraint(_CHECK, "workflow_step_runs", _CURRENT)
    # The shared result2 envelope alone cannot distinguish public/private steps.
    # Resolve only the immutable parent's indexed PK; retain both family fences.
    op.execute(_FAMILY_FUNCTION.replace("__QUALIFIED_FUNCTION__", function))
    op.execute(f"""
        CREATE TRIGGER trg_reference_query2_step_family
        BEFORE INSERT OR UPDATE ON workflow_step_runs
        FOR EACH ROW EXECUTE FUNCTION {function}()
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM workflow_step_runs
                WHERE result_schema = 'embedding-reference-query-result@2.0'
                  AND step_key = 'encode_reference_query'
            ) THEN
                RAISE EXCEPTION 'public query2 downgrade requires absent public successor history'
                    USING ERRCODE = '23514';
            END IF;
        END $$
    """)
    function = _family_function_name()
    op.drop_constraint(_CHECK, "workflow_step_runs", type_="check")
    op.create_check_constraint(_CHECK, "workflow_step_runs", _PREVIOUS)
    op.execute("DROP TRIGGER trg_reference_query2_step_family ON workflow_step_runs")
    op.execute(f"DROP FUNCTION {function}()")
