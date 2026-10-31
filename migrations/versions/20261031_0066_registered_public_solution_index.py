"""Admit registered full-report index metadata without changing numeric storage.

Revision ID: 20261031_0066
Revises: 20261031_0065
Create Date: 2026-10-31 UTC
"""

from __future__ import annotations

from alembic import op

revision: str = "20261031_0066"
down_revision: str | None = "20261031_0065"
branch_labels: str | None = None
depends_on: str | None = None

# Frozen historical DDL; no runtime model or historical migration imports.
_PREVIOUS_CHECKS: tuple[tuple[str, str, str], ...] = (
    (
        "embedding_index_revisions",
        "ck_embedding_index_revision_coverage",
        "binding_count >= 1 AND eligible_source_count >= binding_count AND "
        "eligible_source_count <= CASE WHEN "
        "manifest_schema_ref = 'eom://schemas/knowledge/embedding-index-manifest/3.0' "
        "THEN 16384 ELSE 1024 END",
    ),
    (
        "embedding_index_revisions",
        "ck_embedding_index_revision_member",
        "manifest_member_path = 'index.json' AND "
        "manifest_schema_ref IN ('eom://schemas/knowledge/embedding-index-manifest/1.0',"
        "'eom://schemas/knowledge/embedding-index-manifest/2.0',"
        "'eom://schemas/knowledge/embedding-index-manifest/3.0') AND "
        "manifest_media_type = 'application/json'",
    ),
    (
        "embedding_source_bindings",
        "ck_embedding_binding_member",
        "binding_manifest_member_path = 'index.json' AND "
        "binding_manifest_schema_ref IN "
        "('eom://schemas/knowledge/embedding-index-manifest/1.0',"
        "'eom://schemas/knowledge/embedding-index-manifest/2.0',"
        "'eom://schemas/knowledge/embedding-index-manifest/3.0') AND "
        "binding_manifest_media_type = 'application/json' AND "
        "((evidence_kind = 'ACCEPTED_SOLUTION_ANALYSIS' AND "
        "binding_manifest_schema_ref IN "
        "('eom://schemas/knowledge/embedding-index-manifest/1.0',"
        "'eom://schemas/knowledge/embedding-index-manifest/2.0')) OR "
        "(evidence_kind = 'REGISTERED_ITEM_REVIEW_SOLUTION' AND "
        "binding_manifest_schema_ref = 'eom://schemas/knowledge/embedding-index-manifest/2.0') "
        "OR (evidence_kind = 'PUBLIC_SOLUTION_REPORT' AND "
        "binding_manifest_schema_ref = 'eom://schemas/knowledge/embedding-index-manifest/3.0'))",
    ),
)
_CHECKS: tuple[tuple[str, str, str], ...] = (
    (
        "embedding_index_revisions",
        "ck_embedding_index_revision_coverage",
        "binding_count >= 1 AND eligible_source_count >= binding_count AND "
        "eligible_source_count <= CASE WHEN manifest_schema_ref IN "
        "('eom://schemas/knowledge/embedding-index-manifest/3.0',"
        "'eom://schemas/knowledge/embedding-index-manifest/4.0') "
        "THEN 16384 ELSE 1024 END",
    ),
    (
        "embedding_index_revisions",
        "ck_embedding_index_revision_member",
        "manifest_member_path = 'index.json' AND "
        "manifest_schema_ref IN ('eom://schemas/knowledge/embedding-index-manifest/1.0',"
        "'eom://schemas/knowledge/embedding-index-manifest/2.0',"
        "'eom://schemas/knowledge/embedding-index-manifest/3.0',"
        "'eom://schemas/knowledge/embedding-index-manifest/4.0') AND "
        "manifest_media_type = 'application/json'",
    ),
    (
        "embedding_source_bindings",
        "ck_embedding_binding_member",
        "binding_manifest_member_path = 'index.json' AND "
        "binding_manifest_schema_ref IN "
        "('eom://schemas/knowledge/embedding-index-manifest/1.0',"
        "'eom://schemas/knowledge/embedding-index-manifest/2.0',"
        "'eom://schemas/knowledge/embedding-index-manifest/3.0',"
        "'eom://schemas/knowledge/embedding-index-manifest/4.0') AND "
        "binding_manifest_media_type = 'application/json' AND "
        "((evidence_kind = 'ACCEPTED_SOLUTION_ANALYSIS' AND "
        "binding_manifest_schema_ref IN "
        "('eom://schemas/knowledge/embedding-index-manifest/1.0',"
        "'eom://schemas/knowledge/embedding-index-manifest/2.0')) OR "
        "(evidence_kind = 'REGISTERED_ITEM_REVIEW_SOLUTION' AND "
        "binding_manifest_schema_ref = 'eom://schemas/knowledge/embedding-index-manifest/2.0') "
        "OR (evidence_kind = 'PUBLIC_SOLUTION_REPORT' AND "
        "binding_manifest_schema_ref IN ('eom://schemas/knowledge/embedding-index-manifest/3.0',"
        "'eom://schemas/knowledge/embedding-index-manifest/4.0')))",
    ),
)
_REFUSE_NEW_HISTORY = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM embedding_source_bindings
        WHERE binding_manifest_schema_ref = 'eom://schemas/knowledge/embedding-index-manifest/4.0'
    ) OR EXISTS (
        SELECT 1 FROM embedding_index_revisions
        WHERE manifest_schema_ref = 'eom://schemas/knowledge/embedding-index-manifest/4.0'
    ) THEN
        RAISE EXCEPTION 'registered public index downgrade requires absent successor history'
            USING ERRCODE = '23514';
    END IF;
END
$$
"""


def upgrade() -> None:
    for table, name, _predicate in _PREVIOUS_CHECKS:
        op.drop_constraint(name, table, type_="check")
    for table, name, predicate in _CHECKS:
        op.create_check_constraint(name, table, predicate)


def downgrade() -> None:
    op.execute(_REFUSE_NEW_HISTORY)
    for table, name, _predicate in _CHECKS:
        op.drop_constraint(name, table, type_="check")
    for table, name, predicate in _PREVIOUS_CHECKS:
        op.create_check_constraint(name, table, predicate)
