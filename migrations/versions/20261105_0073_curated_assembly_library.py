"""Titled saved assemblies and list-only removal with preserved delivery history.

Revision ID: 20261105_0073
Revises: 20261104_0072
Create Date: 2026-11-05 UTC
"""

from alembic import op
from sqlalchemy import text

revision = "20261105_0073"
down_revision = "20261104_0072"
branch_labels = None
depends_on = None

_DDL = (
    "ALTER TABLE curated_document_assemblies ADD COLUMN title VARCHAR(200) NOT NULL DEFAULT '', "
    "ADD COLUMN removed_at TIMESTAMP WITH TIME ZONE, "
    "ADD COLUMN removal_idempotency_key VARCHAR(128), "
    "ADD COLUMN removal_request_sha256 VARCHAR(71)",
    "ALTER TABLE curated_document_assemblies ADD CONSTRAINT ck_curated_document_title "
    "CHECK (title !~ E'[\\n\\r\\t]'), "
    "ADD CONSTRAINT ck_curated_document_removal_receipt CHECK "
    "((removed_at IS NULL AND removal_idempotency_key IS NULL "
    "AND removal_request_sha256 IS NULL) OR (removed_at IS NOT NULL "
    "AND removal_idempotency_key IS NOT NULL AND removal_request_sha256 IS NOT NULL "
    "AND removal_idempotency_key ~ '^[!-~]{16,128}$' "
    "AND removal_request_sha256 ~ '^sha256:[0-9a-f]{64}$'))",
    "CREATE UNIQUE INDEX uq_curated_document_removal_replay ON curated_document_assemblies "
    "(created_by, removal_idempotency_key) WHERE removed_at IS NOT NULL",
    "CREATE INDEX ix_curated_document_active_owner_recent ON curated_document_assemblies "
    "(created_by, created_at DESC, assembly_id DESC) WHERE removed_at IS NULL",
    """CREATE FUNCTION protect_curated_assembly_library_metadata() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
IF NEW.title IS DISTINCT FROM OLD.title THEN
RAISE EXCEPTION 'CURATED_ASSEMBLY_TITLE_IMMUTABLE' USING ERRCODE='23514';
END IF;
IF OLD.removed_at IS NOT NULL AND NEW IS DISTINCT FROM OLD THEN
RAISE EXCEPTION 'CURATED_ASSEMBLY_REMOVAL_IMMUTABLE' USING ERRCODE='23514';
END IF;
RETURN NEW;
END;
$$""",
    "CREATE TRIGGER curated_assembly_library_metadata BEFORE UPDATE ON "
    "curated_document_assemblies FOR EACH ROW "
    "EXECUTE FUNCTION protect_curated_assembly_library_metadata()",
)


def upgrade() -> None:
    for statement in _DDL:
        op.execute(statement)


def downgrade() -> None:
    # A schema rollback must not silently discard a user's saved title/removal receipt.
    if op.get_bind().scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM curated_document_assemblies "
            "WHERE title <> '' OR removed_at IS NOT NULL)"
        )
    ):
        raise RuntimeError("CURATED_ASSEMBLY_LIBRARY_HISTORY_EXISTS")
    op.execute("DROP TRIGGER curated_assembly_library_metadata ON curated_document_assemblies")
    op.execute("DROP FUNCTION protect_curated_assembly_library_metadata()")
    op.execute("DROP INDEX ix_curated_document_active_owner_recent")
    op.execute("DROP INDEX uq_curated_document_removal_replay")
    op.execute(
        "ALTER TABLE curated_document_assemblies "
        "DROP CONSTRAINT ck_curated_document_title, "
        "DROP CONSTRAINT ck_curated_document_removal_receipt, "
        "DROP COLUMN title, DROP COLUMN removed_at, "
        "DROP COLUMN removal_idempotency_key, DROP COLUMN removal_request_sha256"
    )
