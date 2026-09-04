"""record extraction acceptance without claiming manual review

Revision ID: 20260904_0028
Revises: 20260903_0027
Create Date: 2026-09-04 00:00:00 UTC
"""

from __future__ import annotations

from alembic import op

revision: str = "20260904_0028"
down_revision: str | None = "20260903_0027"
branch_labels: str | None = None
depends_on: str | None = None

_KINDS_V2 = (
    "provenance_kind IN ('WORKFLOW','CONTENT_INTAKE','ITEM_PROVENANCE',"
    "'MANUAL_REVIEW','EXTRACTION_ACCEPTANCE')"
)
_TYPED_V2 = (
    "(provenance_kind = 'WORKFLOW' AND logical_id ~ '^workflow_[0-9a-f]{32}$' "
    "AND revision_id ~ '^execplan_[0-9a-f]{32}$') OR "
    "(provenance_kind = 'CONTENT_INTAKE' AND logical_id ~ '^intake_[0-9a-f]{32}$' "
    "AND revision_id ~ '^rev_[0-9a-f]{32}$') OR "
    "(provenance_kind = 'ITEM_PROVENANCE' "
    "AND logical_id ~ '^provenance_[0-9a-f]{32}$' AND revision_id IS NULL) OR "
    "(provenance_kind = 'MANUAL_REVIEW' "
    "AND logical_id ~ '^itemacceptance_[0-9a-f]{32}$' "
    "AND revision_id ~ '^rev_[0-9a-f]{32}$') OR "
    "(provenance_kind = 'EXTRACTION_ACCEPTANCE' "
    "AND logical_id ~ '^itemacceptance_[0-9a-f]{32}$' "
    "AND revision_id ~ '^rev_[0-9a-f]{32}$')"
)


def upgrade() -> None:
    op.drop_constraint(
        "ck_item_origin_provenance_typed_pointer",
        "item_origin_provenance",
        type_="check",
    )
    op.drop_constraint(
        "ck_item_origin_provenance_kind",
        "item_origin_provenance",
        type_="check",
    )
    op.create_check_constraint(
        "ck_item_origin_provenance_kind",
        "item_origin_provenance",
        _KINDS_V2,
    )
    op.create_check_constraint(
        "ck_item_origin_provenance_typed_pointer",
        "item_origin_provenance",
        _TYPED_V2,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_item_origin_provenance_typed_pointer",
        "item_origin_provenance",
        type_="check",
    )
    op.drop_constraint(
        "ck_item_origin_provenance_kind",
        "item_origin_provenance",
        type_="check",
    )
    op.create_check_constraint(
        "ck_item_origin_provenance_kind",
        "item_origin_provenance",
        "provenance_kind IN ('WORKFLOW','CONTENT_INTAKE','ITEM_PROVENANCE','MANUAL_REVIEW')",
    )
    op.create_check_constraint(
        "ck_item_origin_provenance_typed_pointer",
        "item_origin_provenance",
        _TYPED_V2.replace(
            " OR (provenance_kind = 'EXTRACTION_ACCEPTANCE' "
            "AND logical_id ~ '^itemacceptance_[0-9a-f]{32}$' "
            "AND revision_id ~ '^rev_[0-9a-f]{32}$')",
            "",
        ),
    )
