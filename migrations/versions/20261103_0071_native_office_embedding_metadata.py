"""Admit native Office report metadata over unchanged numerical rows.

Revision ID: 20261103_0071
Revises: 20261103_0070
Create Date: 2026-11-03 UTC
"""

from alembic import op
from sqlalchemy import text

revision = "20261103_0071"
down_revision = "20261103_0070"
branch_labels = None
depends_on = None

# Frozen DDL: never import mutable runtime models or predecessor migration code.
_PREVIOUS_CHECKS: tuple[tuple[str, str, str], ...] = (
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
_CHECKS: tuple[tuple[str, str, str], ...] = (
    (
        "embedding_index_revisions",
        "ck_embedding_index_revision_coverage",
        "binding_count >= 1 AND eligible_source_count >= binding_count AND "
        "eligible_source_count <= CASE WHEN manifest_schema_ref IN "
        "('eom://schemas/knowledge/embedding-index-manifest/3.0',"
        "'eom://schemas/knowledge/embedding-index-manifest/4.0',"
        "'eom://schemas/knowledge/embedding-index-manifest/5.0') "
        "THEN 16384 ELSE 1024 END",
    ),
    (
        "embedding_index_revisions",
        "ck_embedding_index_revision_member",
        "manifest_member_path = 'index.json' AND "
        "manifest_schema_ref IN ('eom://schemas/knowledge/embedding-index-manifest/1.0',"
        "'eom://schemas/knowledge/embedding-index-manifest/2.0',"
        "'eom://schemas/knowledge/embedding-index-manifest/3.0',"
        "'eom://schemas/knowledge/embedding-index-manifest/4.0',"
        "'eom://schemas/knowledge/embedding-index-manifest/5.0') AND "
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
        "'eom://schemas/knowledge/embedding-index-manifest/4.0',"
        "'eom://schemas/knowledge/embedding-index-manifest/5.0') AND "
        "binding_manifest_media_type = 'application/json' AND "
        "((evidence_kind = 'ACCEPTED_SOLUTION_ANALYSIS' AND "
        "binding_manifest_schema_ref IN "
        "('eom://schemas/knowledge/embedding-index-manifest/1.0',"
        "'eom://schemas/knowledge/embedding-index-manifest/2.0')) OR "
        "(evidence_kind = 'REGISTERED_ITEM_REVIEW_SOLUTION' AND "
        "binding_manifest_schema_ref = 'eom://schemas/knowledge/embedding-index-manifest/2.0') "
        "OR (evidence_kind = 'PUBLIC_SOLUTION_REPORT' AND "
        "binding_manifest_schema_ref IN ('eom://schemas/knowledge/embedding-index-manifest/3.0',"
        "'eom://schemas/knowledge/embedding-index-manifest/4.0',"
        "'eom://schemas/knowledge/embedding-index-manifest/5.0')))",
    ),
)


def _replace(checks: tuple[tuple[str, str, str], ...]) -> None:
    for table, name, predicate in checks:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, predicate)


def upgrade() -> None:
    _replace(_CHECKS)


def downgrade() -> None:
    if op.get_bind().scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM embedding_source_bindings "
            "WHERE binding_manifest_schema_ref="
            "'eom://schemas/knowledge/embedding-index-manifest/5.0') "
            "OR EXISTS (SELECT 1 FROM embedding_index_revisions "
            "WHERE manifest_schema_ref='eom://schemas/knowledge/embedding-index-manifest/5.0')"
        )
    ):
        raise RuntimeError("NATIVE_OFFICE_PUBLIC_INDEX_HISTORY_EXISTS")
    _replace(_PREVIOUS_CHECKS)
