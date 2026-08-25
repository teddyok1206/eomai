"""Add immutable educational documents and revisions.

Revision ID: 20260825_0016
Revises: 20260824_0015
Create Date: 2026-08-25 00:00:00 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0016"
down_revision: str | None = "20260824_0015"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "educational_documents",
        sa.Column("document_id", sa.String(39), primary_key=True),
        sa.Column("document_key", sa.String(128), nullable=False, unique=True),
        sa.Column("document_kind", sa.String(32), nullable=False),
        sa.Column("lifecycle_state", sa.String(16), nullable=False),
        sa.Column("current_revision_id", sa.String(42), nullable=True, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retirement_reason", sa.Text(), nullable=True),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint(
            "lifecycle_state IN ('ACTIVE','RETIRED')",
            name="ck_educational_documents_lifecycle",
        ),
    )
    op.create_index(
        "ix_educational_documents_document_kind",
        "educational_documents",
        ["document_kind"],
    )
    op.create_index(
        "ix_educational_documents_lifecycle_state",
        "educational_documents",
        ["lifecycle_state"],
    )
    op.create_table(
        "educational_document_revisions",
        sa.Column("document_revision_id", sa.String(42), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(39),
            sa.ForeignKey("educational_documents.document_id"),
            nullable=False,
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column(
            "previous_revision_id",
            sa.String(42),
            sa.ForeignKey("educational_document_revisions.document_revision_id"),
            nullable=True,
        ),
        sa.Column("revision_state", sa.String(16), nullable=False),
        sa.Column("registration_key", sa.String(200), nullable=False),
        sa.Column("registration_request_sha256", sa.String(71), nullable=False),
        sa.Column("publisher_key", sa.String(64), nullable=False),
        sa.Column("publisher_label", sa.String(100), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("curriculum_volume", sa.String(8), nullable=True),
        sa.Column("edition_label", sa.String(100), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column(
            "source_artifact_id",
            sa.String(41),
            sa.ForeignKey("artifacts.logical_artifact_id"),
            nullable=False,
        ),
        sa.Column(
            "source_artifact_revision_id",
            sa.String(36),
            sa.ForeignKey("artifact_revisions.revision_id"),
            nullable=False,
        ),
        sa.Column("source_sha256", sa.String(71), nullable=False),
        sa.Column("source_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("source_page_count", sa.Integer(), nullable=False),
        sa.Column(
            "analysis_artifact_id",
            sa.String(41),
            sa.ForeignKey("artifacts.logical_artifact_id"),
            nullable=False,
        ),
        sa.Column(
            "analysis_artifact_revision_id",
            sa.String(36),
            sa.ForeignKey("artifact_revisions.revision_id"),
            nullable=False,
        ),
        sa.Column("analysis_manifest_sha256", sa.String(71), nullable=False),
        sa.Column(
            "rights_artifact_id",
            sa.String(41),
            sa.ForeignKey("artifacts.logical_artifact_id"),
            nullable=False,
        ),
        sa.Column(
            "rights_artifact_revision_id",
            sa.String(36),
            sa.ForeignKey("artifact_revisions.revision_id"),
            nullable=False,
        ),
        sa.Column("rights_attestation_sha256", sa.String(71), nullable=False),
        sa.Column(
            "revision_manifest_artifact_id",
            sa.String(41),
            sa.ForeignKey("artifacts.logical_artifact_id"),
            nullable=False,
        ),
        sa.Column(
            "revision_manifest_artifact_revision_id",
            sa.String(36),
            sa.ForeignKey("artifact_revisions.revision_id"),
            nullable=False,
        ),
        sa.Column("revision_manifest_sha256", sa.String(71), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.UniqueConstraint(
            "document_id", "revision_number", name="uq_educational_document_revision_number"
        ),
        sa.UniqueConstraint("registration_key", name="uq_educational_document_registration_key"),
        sa.UniqueConstraint(
            "registration_request_sha256", name="uq_educational_document_registration_request_sha"
        ),
        sa.CheckConstraint(
            "revision_number > 0", name="ck_educational_document_revision_number_positive"
        ),
        sa.CheckConstraint(
            "revision_state = 'APPROVED'", name="ck_educational_document_revision_state"
        ),
    )
    op.create_index(
        "ix_educational_document_revisions_document_id",
        "educational_document_revisions",
        ["document_id"],
    )
    op.create_index(
        "ix_educational_document_revision_publisher_volume",
        "educational_document_revisions",
        ["publisher_key", "curriculum_volume", "document_revision_id"],
    )
    op.create_index(
        "ix_educational_document_revision_source_sha",
        "educational_document_revisions",
        ["source_sha256", "document_revision_id"],
    )
    op.create_foreign_key(
        "fk_educational_documents_current_revision",
        "educational_documents",
        "educational_document_revisions",
        ["current_revision_id"],
        ["document_revision_id"],
    )
    op.create_table(
        "educational_document_registrations",
        sa.Column("document_registration_id", sa.String(42), primary_key=True),
        sa.Column("registration_key", sa.String(200), nullable=False, unique=True),
        sa.Column("registration_request_sha256", sa.String(71), nullable=False, unique=True),
        sa.Column(
            "document_id",
            sa.String(39),
            sa.ForeignKey("educational_documents.document_id"),
            nullable=False,
        ),
        sa.Column("document_revision_id", sa.String(42), nullable=False, unique=True),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("previous_revision_id", sa.String(42), nullable=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "document_id",
            "revision_number",
            name="uq_educational_document_registration_revision_number",
        ),
        sa.CheckConstraint(
            "state IN ('PREPARED','COMMITTED','FAILED')",
            name="ck_educational_document_registrations_state",
        ),
        sa.CheckConstraint(
            "revision_number > 0",
            name="ck_educational_document_registration_revision_positive",
        ),
    )
    op.create_index(
        "ix_educational_document_registrations_document_id",
        "educational_document_registrations",
        ["document_id"],
    )
    op.create_index(
        "ix_educational_document_registrations_state",
        "educational_document_registrations",
        ["state"],
    )
    op.execute(
        """
        CREATE FUNCTION reject_educational_document_revision_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'educational document revisions are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER educational_document_revisions_immutable "
        "BEFORE UPDATE OR DELETE ON educational_document_revisions FOR EACH ROW "
        "EXECUTE FUNCTION reject_educational_document_revision_mutation()"
    )
    op.execute(
        """
        CREATE FUNCTION enforce_educational_document_identity_immutability() RETURNS trigger AS $$
        BEGIN
          IF NEW.document_id <> OLD.document_id
             OR NEW.document_key <> OLD.document_key
             OR NEW.document_kind <> OLD.document_kind
             OR NEW.created_at <> OLD.created_at
             OR NEW.created_by <> OLD.created_by THEN
            RAISE EXCEPTION 'educational document identity is immutable';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER educational_documents_identity_immutable "
        "BEFORE UPDATE ON educational_documents FOR EACH ROW "
        "EXECUTE FUNCTION enforce_educational_document_identity_immutability()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS educational_documents_identity_immutable ON educational_documents"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS educational_document_revisions_immutable "
        "ON educational_document_revisions"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_educational_document_identity_immutability()")
    op.execute("DROP FUNCTION IF EXISTS reject_educational_document_revision_mutation()")
    op.drop_table("educational_document_registrations")
    op.drop_constraint(
        "fk_educational_documents_current_revision",
        "educational_documents",
        type_="foreignkey",
    )
    op.drop_table("educational_document_revisions")
    op.drop_table("educational_documents")
