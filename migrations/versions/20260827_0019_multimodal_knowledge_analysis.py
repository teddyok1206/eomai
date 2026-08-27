"""Allow immutable multimodal textbook bundle pointers in analysis batches.

Revision ID: 20260827_0019
Revises: 20260826_0018
Create Date: 2026-08-27 00:00:00 UTC
"""

from __future__ import annotations

from alembic import op

revision: str = "20260827_0019"
down_revision: str | None = "20260826_0018"
branch_labels: str | None = None
depends_on: str | None = None

_TABLE = "knowledge_analysis_batch_ranges"
_CONSTRAINT = "ck_knowledge_analysis_batch_range_pointer_contract"


def _pointer_contract(*, multimodal: bool) -> str:
    analysis_schema = (
        "analysis_schema_ref IN ("
        "'eom://schemas/legacy-knowledge/textbook-analysis-bundle-manifest/1.0',"
        "'eom://schemas/legacy-knowledge/textbook-analysis-bundle-manifest/2.0')"
        if multimodal
        else "analysis_schema_ref = "
        "'eom://schemas/legacy-knowledge/textbook-analysis-bundle-manifest/1.0'"
    )
    return (
        "source_media_type = 'application/pdf' AND "
        "source_schema_ref = 'eom://schemas/educational-document/pdf-source/1.0' AND "
        "analysis_media_type = 'application/json' AND "
        f"{analysis_schema} AND "
        "rights_media_type = 'application/json' AND "
        "rights_schema_ref = "
        "'eom://schemas/educational-document/rights-attestation/1.0'"
    )


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(_CONSTRAINT, _TABLE, _pointer_contract(multimodal=True))


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(_CONSTRAINT, _TABLE, _pointer_contract(multimodal=False))
