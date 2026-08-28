"""Add credential-free Codex GUI device reauthentication state.

Revision ID: 20260827_0020
Revises: 20260827_0019
Create Date: 2026-08-27 12:00:00 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260827_0020"
down_revision: str | None = "20260827_0019"
branch_labels: str | None = None
depends_on: str | None = None

_ACTIVE_STATES = "'REQUESTED','DRAINING','READY_FOR_LOGIN','WAITING_FOR_USER','VERIFYING'"


def upgrade() -> None:
    op.create_table(
        "codex_auth_enrollments",
        sa.Column("enrollment_id", sa.String(length=41), nullable=False),
        sa.Column("binding_id", sa.String(length=44), nullable=False),
        sa.Column("expected_binding_resource_version", sa.Integer(), nullable=False),
        sa.Column("requested_account_label", sa.String(length=64), nullable=False),
        sa.Column("requested_by_operator_id", sa.String(length=41), nullable=False),
        sa.Column("requested_by_api_session_id", sa.String(length=43), nullable=False),
        sa.Column("idempotency_key", sa.String(length=96), nullable=False),
        sa.Column("request_sha256", sa.String(length=71), nullable=False),
        sa.Column("canonical_document", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_action_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("challenge_revealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("login_unit_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assignment_revision_id", sa.String(length=46), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resource_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "state IN ('REQUESTED','DRAINING','READY_FOR_LOGIN','WAITING_FOR_USER',"
            "'VERIFYING','SUCCEEDED','FAILED','CANCELLED','EXPIRED')",
            name="ck_codex_auth_enrollment_state",
        ),
        sa.CheckConstraint("resource_version >= 1", name="ck_codex_auth_enrollment_version"),
        sa.CheckConstraint(
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_codex_auth_enrollment_hash",
        ),
        sa.CheckConstraint(
            "expires_at > requested_at AND expires_at <= requested_at + interval '15 minutes'",
            name="ck_codex_auth_enrollment_window",
        ),
        sa.CheckConstraint(
            "login_unit_started_at IS NULL OR "
            "(login_unit_started_at >= requested_at AND login_unit_started_at < expires_at)",
            name="ck_codex_auth_enrollment_login_start_window",
        ),
        sa.CheckConstraint(
            "(lease_owner IS NULL AND lease_expires_at IS NULL) OR "
            "(lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_codex_auth_enrollment_lease_pair",
        ),
        sa.CheckConstraint(
            "(state = 'SUCCEEDED' AND completed_at IS NOT NULL "
            "AND assignment_revision_id IS NOT NULL AND error_code IS NULL "
            "AND next_action_at IS NULL AND lease_owner IS NULL) OR "
            "(state IN ('FAILED','CANCELLED','EXPIRED') AND completed_at IS NOT NULL "
            "AND assignment_revision_id IS NULL AND error_code IS NOT NULL "
            "AND next_action_at IS NULL AND lease_owner IS NULL) OR "
            "(state IN ('REQUESTED','DRAINING','READY_FOR_LOGIN','WAITING_FOR_USER','VERIFYING') "
            "AND completed_at IS NULL AND assignment_revision_id IS NULL AND error_code IS NULL "
            "AND next_action_at IS NOT NULL)",
            name="ck_codex_auth_enrollment_lifecycle",
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"], ["codex_auth_bindings.binding_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_operator_id"], ["operators.operator_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_api_session_id"], ["api_sessions.api_session_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("enrollment_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_codex_auth_enrollment_idempotency"),
    )
    op.create_index(
        "uq_codex_auth_enrollment_active_binding",
        "codex_auth_enrollments",
        ["binding_id"],
        unique=True,
        postgresql_where=sa.text(f"state IN ({_ACTIVE_STATES})"),
    )
    op.create_index(
        "ix_codex_auth_enrollment_claim",
        "codex_auth_enrollments",
        [
            "state",
            "next_action_at",
            "lease_expires_at",
            "requested_at",
            "enrollment_id",
        ],
        postgresql_where=sa.text(f"state IN ({_ACTIVE_STATES})"),
    )

    op.create_table(
        "codex_auth_assignment_revisions",
        sa.Column("assignment_revision_id", sa.String(length=46), nullable=False),
        sa.Column("binding_id", sa.String(length=44), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("enrollment_id", sa.String(length=41), nullable=False),
        sa.Column("account_label", sa.String(length=64), nullable=False),
        sa.Column("login_method", sa.String(length=32), nullable=False),
        sa.Column("codex_cli_version", sa.String(length=32), nullable=False),
        sa.Column("assigned_by_operator_id", sa.String(length=41), nullable=False),
        sa.Column("assignment_sha256", sa.String(length=71), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("revision_number >= 1", name="ck_codex_auth_assignment_revision_number"),
        sa.CheckConstraint(
            "login_method = 'CHATGPT_DEVICE_CODE'",
            name="ck_codex_auth_assignment_login_method",
        ),
        sa.CheckConstraint(
            "assignment_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_codex_auth_assignment_revision_hash",
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"], ["codex_auth_bindings.binding_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["enrollment_id"], ["codex_auth_enrollments.enrollment_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by_operator_id"], ["operators.operator_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("assignment_revision_id"),
        sa.UniqueConstraint(
            "binding_id", "revision_number", name="uq_codex_auth_assignment_revision_number"
        ),
        sa.UniqueConstraint(
            "assignment_revision_id",
            "binding_id",
            name="uq_codex_auth_assignment_revision_owner",
        ),
        sa.UniqueConstraint("enrollment_id", name="uq_codex_auth_assignment_enrollment"),
    )
    op.execute(
        "CREATE TRIGGER codex_auth_assignment_revisions_immutable "
        "BEFORE UPDATE OR DELETE ON codex_auth_assignment_revisions FOR EACH ROW "
        "EXECUTE FUNCTION reject_control_plane_immutable_mutation()"
    )

    op.create_foreign_key(
        "fk_codex_auth_enrollment_assignment_owner",
        "codex_auth_enrollments",
        "codex_auth_assignment_revisions",
        ["assignment_revision_id", "binding_id"],
        ["assignment_revision_id", "binding_id"],
        ondelete="RESTRICT",
    )
    op.add_column(
        "codex_auth_bindings",
        sa.Column("current_assignment_revision_id", sa.String(length=46), nullable=True),
    )
    op.create_foreign_key(
        "fk_codex_auth_binding_current_assignment_owner",
        "codex_auth_bindings",
        "codex_auth_assignment_revisions",
        ["current_assignment_revision_id", "binding_id"],
        ["assignment_revision_id", "binding_id"],
        ondelete="RESTRICT",
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION protect_codex_auth_binding_identity() RETURNS trigger AS $$
        BEGIN
          IF (to_jsonb(OLD) - ARRAY[
                'account_label','current_assignment_revision_id',
                'state','reason_code','codex_cli_version','observed_at','valid_until',
                'resource_version','updated_at'
              ])
             IS DISTINCT FROM
             (to_jsonb(NEW) - ARRAY[
                'account_label','current_assignment_revision_id',
                'state','reason_code','codex_cli_version','observed_at','valid_until',
                'resource_version','updated_at'
              ]) THEN
            RAISE EXCEPTION 'Codex authentication binding identity is immutable';
          END IF;
          IF (NEW.account_label, NEW.current_assignment_revision_id)
             IS DISTINCT FROM (OLD.account_label, OLD.current_assignment_revision_id)
             AND (
               NEW.current_assignment_revision_id IS NULL
               OR NOT EXISTS (
                 SELECT 1 FROM codex_auth_assignment_revisions assignment
                 WHERE assignment.assignment_revision_id = NEW.current_assignment_revision_id
                   AND assignment.binding_id = NEW.binding_id
                   AND assignment.account_label = NEW.account_label
               )
             ) THEN
            RAISE EXCEPTION 'Codex authentication assignment pointer is invalid';
          END IF;
          IF NEW.resource_version <= OLD.resource_version THEN
            RAISE EXCEPTION 'Codex authentication binding version must increase';
          END IF;
          IF OLD.observed_at IS NOT NULL AND NEW.observed_at <= OLD.observed_at THEN
            RAISE EXCEPTION 'Codex authentication observation must advance';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_codex_auth_binding_current_assignment_owner",
        "codex_auth_bindings",
        type_="foreignkey",
    )
    op.drop_column("codex_auth_bindings", "current_assignment_revision_id")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION protect_codex_auth_binding_identity() RETURNS trigger AS $$
        BEGIN
          IF (to_jsonb(OLD) - ARRAY[
                'state','reason_code','codex_cli_version','observed_at','valid_until',
                'resource_version','updated_at'
              ])
             IS DISTINCT FROM
             (to_jsonb(NEW) - ARRAY[
                'state','reason_code','codex_cli_version','observed_at','valid_until',
                'resource_version','updated_at'
              ]) THEN
            RAISE EXCEPTION 'Codex authentication binding identity is immutable';
          END IF;
          IF NEW.resource_version <= OLD.resource_version THEN
            RAISE EXCEPTION 'Codex authentication binding version must increase';
          END IF;
          IF OLD.observed_at IS NOT NULL AND NEW.observed_at <= OLD.observed_at THEN
            RAISE EXCEPTION 'Codex authentication observation must advance';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.drop_constraint(
        "fk_codex_auth_enrollment_assignment_owner",
        "codex_auth_enrollments",
        type_="foreignkey",
    )
    op.execute(
        "DROP TRIGGER codex_auth_assignment_revisions_immutable ON codex_auth_assignment_revisions"
    )
    op.drop_table("codex_auth_assignment_revisions")
    op.drop_index("ix_codex_auth_enrollment_claim", table_name="codex_auth_enrollments")
    op.drop_index("uq_codex_auth_enrollment_active_binding", table_name="codex_auth_enrollments")
    op.drop_table("codex_auth_enrollments")
