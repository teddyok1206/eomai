"""Content-scoped delivery and bounded occurrence render successor.

Revision ID: 20261109_0076
Revises: 20261109_0075
Create Date: 2026-11-09 UTC
"""

from alembic import op
from sqlalchemy import text

revision = "20261109_0076"
down_revision = "20261109_0075"
branch_labels = None
depends_on = None

_COUNT = (
    "placement_count >= 1 AND resource_version > 0 AND placement_count <= "
    "CASE input_plan->>'schema_version' WHEN 'curated-hwpx-build-input/1.0' THEN 200 "
    "WHEN 'curated-hwpx-build-input/2.0' THEN 100000 ELSE 0 END"
)
_BUDGET = (
    "jsonb_typeof(input_plan) = 'object' AND "
    "octet_length(input_plan::text) <= CASE input_plan->>'schema_version' "
    "WHEN 'curated-hwpx-build-input/1.0' THEN 524288 "
    "WHEN 'curated-hwpx-build-input/2.0' THEN 16777216 ELSE 0 END AND "
    "jsonb_typeof(initiator_context) = 'object' AND octet_length(initiator_context::text) <= 4096"
)


def upgrade() -> None:
    op.execute("""CREATE TABLE content_delivery_scopes (
      assembly_revision_id VARCHAR(44) PRIMARY KEY,
      assembly_id VARCHAR(41) NOT NULL,
      edition_id VARCHAR(40) NOT NULL,
      deliverable_revision_id VARCHAR(41) NOT NULL,
      scope_sha256 VARCHAR(71) NOT NULL,
      canonical_scope JSONB NOT NULL,
      created_at TIMESTAMPTZ NOT NULL,
      CONSTRAINT fk_content_delivery_edition_revision
        FOREIGN KEY (edition_id, deliverable_revision_id)
        REFERENCES content_edition_revisions (edition_id, deliverable_revision_id)
        ON DELETE RESTRICT,
      CONSTRAINT fk_content_delivery_assembly_revision
        FOREIGN KEY (assembly_id, assembly_revision_id)
        REFERENCES curated_document_assembly_revisions (assembly_id, assembly_revision_id)
        ON DELETE RESTRICT,
      CONSTRAINT uq_content_delivery_scope UNIQUE (deliverable_revision_id, scope_sha256),
      CONSTRAINT uq_content_delivery_assembly UNIQUE (assembly_id),
      CONSTRAINT ck_content_delivery_scope_hash CHECK (scope_sha256 ~ '^sha256:[0-9a-f]{64}$'),
      CONSTRAINT ck_content_delivery_scope_budget CHECK (
        jsonb_typeof(canonical_scope)='object' AND octet_length(canonical_scope::text)<=4194304)
    )""")
    op.execute(
        "CREATE INDEX ix_content_delivery_edition ON content_delivery_scopes "
        "(edition_id, created_at, assembly_revision_id)"
    )
    op.execute(
        "CREATE TRIGGER content_delivery_scopes_immutable BEFORE UPDATE OR DELETE "
        "ON content_delivery_scopes FOR EACH ROW "
        "EXECUTE FUNCTION reject_content_history_mutation()"
    )
    op.drop_constraint("ck_hwpx_curated_count", "hwpx_curated_builds", type_="check")
    op.create_check_constraint("ck_hwpx_curated_count", "hwpx_curated_builds", _COUNT)
    op.drop_constraint("ck_hwpx_curated_metadata_budget", "hwpx_curated_builds", type_="check")
    op.create_check_constraint("ck_hwpx_curated_metadata_budget", "hwpx_curated_builds", _BUDGET)


def downgrade() -> None:
    connection = op.get_bind()
    if connection.scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM content_delivery_scopes) OR "
            "EXISTS(SELECT 1 FROM hwpx_curated_builds WHERE "
            "input_plan->>'schema_version'='curated-hwpx-build-input/2.0')"
        )
    ):
        raise RuntimeError("content delivery history must be preserved before downgrade")
    op.drop_table("content_delivery_scopes")
    op.drop_constraint("ck_hwpx_curated_count", "hwpx_curated_builds", type_="check")
    op.create_check_constraint(
        "ck_hwpx_curated_count",
        "hwpx_curated_builds",
        "placement_count BETWEEN 1 AND 200 AND resource_version > 0",
    )
    op.drop_constraint("ck_hwpx_curated_metadata_budget", "hwpx_curated_builds", type_="check")
    op.create_check_constraint(
        "ck_hwpx_curated_metadata_budget",
        "hwpx_curated_builds",
        "jsonb_typeof(input_plan) = 'object' AND octet_length(input_plan::text) <= 524288 AND "
        "jsonb_typeof(initiator_context) = 'object' AND "
        "octet_length(initiator_context::text) <= 4096",
    )
