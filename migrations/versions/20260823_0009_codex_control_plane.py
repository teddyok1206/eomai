"""Add Codex execution control-plane persistence.

Revision ID: 20260823_0009
Revises: 20260821_0008
Create Date: 2026-08-23 12:00:00Z
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260823_0009"
down_revision: str | Sequence[str] | None = "20260821_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HELD_LEASE_PREDICATE = sa.text("state IN ('ACTIVE','RECONCILING')")


def _json() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "execution_bundles",
        sa.Column("bundle_id", sa.String(length=44), nullable=False),
        sa.Column("bundle_kind", sa.String(length=16), nullable=False),
        sa.Column("bundle_key", sa.String(length=128), nullable=False),
        sa.Column("current_revision_id", sa.String(length=41), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("bundle_kind IN ('INSTRUCTION','REFERENCE')", name="ck_bundle_kind"),
        sa.CheckConstraint("state IN ('ACTIVE','RETIRED')", name="ck_execution_bundles_state"),
        sa.PrimaryKeyConstraint("bundle_id"),
        sa.UniqueConstraint("bundle_id", "bundle_kind", name="uq_execution_bundle_id_kind"),
        sa.UniqueConstraint("bundle_kind", "bundle_key", name="uq_execution_bundle_kind_key"),
    )
    op.create_table(
        "execution_bundle_revisions",
        sa.Column("bundle_revision_id", sa.String(length=41), nullable=False),
        sa.Column("bundle_id", sa.String(length=44), nullable=False),
        sa.Column("bundle_kind", sa.String(length=16), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("manifest_artifact_id", sa.String(length=41), nullable=False),
        sa.Column("manifest_artifact_revision_id", sa.String(length=36), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=71), nullable=False),
        sa.Column("content_sha256", sa.String(length=71), nullable=False),
        sa.Column("canonical_document", _json(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "state IN ('DRAFT','RELEASED','DEPRECATED')",
            name="ck_execution_bundle_revisions_state",
        ),
        sa.CheckConstraint(
            "(bundle_kind = 'INSTRUCTION' AND bundle_revision_id LIKE 'instrrev_%') OR "
            "(bundle_kind = 'REFERENCE' AND bundle_revision_id LIKE 'refrev_%')",
            name="ck_execution_bundle_revision_id_kind",
        ),
        sa.CheckConstraint("revision_number >= 1", name="ck_execution_bundle_revision_number"),
        sa.CheckConstraint(
            "manifest_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND content_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_execution_bundle_revision_hashes",
        ),
        sa.ForeignKeyConstraint(
            ["bundle_id", "bundle_kind"],
            ["execution_bundles.bundle_id", "execution_bundles.bundle_kind"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["manifest_artifact_id"], ["artifacts.logical_artifact_id"]),
        sa.ForeignKeyConstraint(
            ["manifest_artifact_revision_id"], ["artifact_revisions.revision_id"]
        ),
        sa.PrimaryKeyConstraint("bundle_revision_id"),
        sa.UniqueConstraint(
            "bundle_id", "revision_number", name="uq_execution_bundle_revision_number"
        ),
        sa.UniqueConstraint(
            "bundle_revision_id", "bundle_id", name="uq_execution_bundle_revision_owner"
        ),
        sa.UniqueConstraint("manifest_artifact_revision_id"),
    )
    op.create_index(
        "ix_execution_bundle_revisions_bundle_id", "execution_bundle_revisions", ["bundle_id"]
    )
    op.create_foreign_key(
        "fk_execution_bundles_current_revision_owner",
        "execution_bundles",
        "execution_bundle_revisions",
        ["current_revision_id", "bundle_id"],
        ["bundle_revision_id", "bundle_id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "worker_capacity_policies",
        sa.Column("capacity_policy_id", sa.String(length=41), nullable=False),
        sa.Column("policy_key", sa.String(length=128), nullable=False),
        sa.Column("current_revision_id", sa.String(length=44), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("state IN ('ACTIVE','RETIRED')", name="ck_capacity_policies_state"),
        sa.PrimaryKeyConstraint("capacity_policy_id"),
        sa.UniqueConstraint("policy_key", name="uq_worker_capacity_policy_key"),
    )
    op.create_table(
        "worker_capacity_policy_revisions",
        sa.Column("capacity_policy_revision_id", sa.String(length=44), nullable=False),
        sa.Column("capacity_policy_id", sa.String(length=41), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("max_configured_slots", sa.Integer(), nullable=False),
        sa.Column("max_active_codex", sa.Integer(), nullable=False),
        sa.Column("max_active_per_slot", sa.Integer(), nullable=False),
        sa.Column("max_active_gpu", sa.Integer(), nullable=False),
        sa.Column("max_active_knowledge_analysis", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=71), nullable=False),
        sa.Column("canonical_document", _json(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "state IN ('DRAFT','RELEASED','DEPRECATED')",
            name="ck_capacity_policy_revisions_state",
        ),
        sa.CheckConstraint(
            "max_configured_slots BETWEEN 1 AND 5 AND max_active_codex BETWEEN 1 AND 3 "
            "AND max_active_codex <= max_configured_slots AND max_active_per_slot = 1 "
            "AND max_active_gpu = 1 AND max_active_knowledge_analysis = 1",
            name="ck_capacity_policy_host_limits",
        ),
        sa.CheckConstraint("revision_number >= 1", name="ck_capacity_policy_revision_number_value"),
        sa.CheckConstraint(
            "content_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_capacity_policy_revision_hash",
        ),
        sa.ForeignKeyConstraint(
            ["capacity_policy_id"],
            ["worker_capacity_policies.capacity_policy_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("capacity_policy_revision_id"),
        sa.UniqueConstraint(
            "capacity_policy_id", "revision_number", name="uq_capacity_policy_revision_number"
        ),
        sa.UniqueConstraint(
            "capacity_policy_revision_id",
            "capacity_policy_id",
            name="uq_capacity_policy_revision_owner",
        ),
    )
    op.create_index(
        "ix_worker_capacity_policy_revisions_capacity_policy_id",
        "worker_capacity_policy_revisions",
        ["capacity_policy_id"],
    )
    op.create_foreign_key(
        "fk_capacity_policies_current_revision_owner",
        "worker_capacity_policies",
        "worker_capacity_policy_revisions",
        ["current_revision_id", "capacity_policy_id"],
        ["capacity_policy_revision_id", "capacity_policy_id"],
        ondelete="RESTRICT",
    )
    op.create_table(
        "worker_capacity_pools",
        sa.Column("capacity_policy_revision_id", sa.String(length=44), nullable=False),
        sa.Column("pool_key", sa.String(length=64), nullable=False),
        sa.Column("max_active", sa.Integer(), nullable=False),
        sa.CheckConstraint("max_active BETWEEN 1 AND 3", name="ck_worker_capacity_pool_limit"),
        sa.ForeignKeyConstraint(
            ["capacity_policy_revision_id"],
            ["worker_capacity_policy_revisions.capacity_policy_revision_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("capacity_policy_revision_id", "pool_key"),
    )
    op.create_table(
        "worker_capacity_pool_roles",
        sa.Column("capacity_policy_revision_id", sa.String(length=44), nullable=False),
        sa.Column("pool_key", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "role IN ('authoring','image','review','item_management','support')",
            name="ck_worker_capacity_pool_role",
        ),
        sa.ForeignKeyConstraint(
            ["capacity_policy_revision_id", "pool_key"],
            ["worker_capacity_pools.capacity_policy_revision_id", "worker_capacity_pools.pool_key"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("capacity_policy_revision_id", "pool_key", "role"),
    )
    op.create_table(
        "worker_capacity_pool_slots",
        sa.Column("capacity_policy_revision_id", sa.String(length=44), nullable=False),
        sa.Column("pool_key", sa.String(length=64), nullable=False),
        sa.Column("slot_id", sa.String(length=2), nullable=False),
        sa.ForeignKeyConstraint(
            ["capacity_policy_revision_id", "pool_key"],
            ["worker_capacity_pools.capacity_policy_revision_id", "worker_capacity_pools.pool_key"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["slot_id"], ["worker_slots.slot_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("capacity_policy_revision_id", "pool_key", "slot_id"),
    )

    op.create_table(
        "execution_presets",
        sa.Column("preset_id", sa.String(length=43), nullable=False),
        sa.Column("preset_key", sa.String(length=128), nullable=False),
        sa.Column("current_revision_id", sa.String(length=46), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("state IN ('ACTIVE','RETIRED')", name="ck_execution_presets_state"),
        sa.PrimaryKeyConstraint("preset_id"),
        sa.UniqueConstraint("preset_key", name="uq_execution_preset_key"),
    )
    op.create_table(
        "execution_preset_revisions",
        sa.Column("preset_revision_id", sa.String(length=46), nullable=False),
        sa.Column("preset_id", sa.String(length=43), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("capacity_policy_revision_id", sa.String(length=44), nullable=False),
        sa.Column("general_knowledge_policy", sa.String(length=32), nullable=False),
        sa.Column("compatible_workflow_protocols", _json(), nullable=False),
        sa.Column("content_sha256", sa.String(length=71), nullable=False),
        sa.Column("canonical_document", _json(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "state IN ('DRAFT','RELEASED','DEPRECATED')",
            name="ck_execution_preset_revisions_state",
        ),
        sa.CheckConstraint(
            "general_knowledge_policy IN ('DENY','ALLOW_WITH_PROVENANCE')",
            name="ck_execution_preset_general_knowledge",
        ),
        sa.CheckConstraint(
            "revision_number >= 1", name="ck_execution_preset_revision_number_value"
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_execution_preset_revision_hash",
        ),
        sa.ForeignKeyConstraint(
            ["preset_id"], ["execution_presets.preset_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["capacity_policy_revision_id"],
            ["worker_capacity_policy_revisions.capacity_policy_revision_id"],
        ),
        sa.PrimaryKeyConstraint("preset_revision_id"),
        sa.UniqueConstraint(
            "preset_id", "revision_number", name="uq_execution_preset_revision_number"
        ),
        sa.UniqueConstraint(
            "preset_revision_id", "preset_id", name="uq_execution_preset_revision_owner"
        ),
    )
    op.create_index(
        "ix_execution_preset_revisions_preset_id",
        "execution_preset_revisions",
        ["preset_id"],
    )
    op.create_foreign_key(
        "fk_execution_presets_current_revision_owner",
        "execution_presets",
        "execution_preset_revisions",
        ["current_revision_id", "preset_id"],
        ["preset_revision_id", "preset_id"],
        ondelete="RESTRICT",
    )
    op.create_table(
        "execution_preset_role_policies",
        sa.Column("preset_revision_id", sa.String(length=46), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("model_candidates", _json(), nullable=False),
        sa.Column("instruction_bundle_revision_id", sa.String(length=41), nullable=False),
        sa.Column("reference_bundle_revision_id", sa.String(length=41), nullable=True),
        sa.Column("worker_pool_key", sa.String(length=64), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("sandbox", sa.String(length=16), nullable=False),
        sa.Column("network", sa.String(length=16), nullable=False),
        sa.CheckConstraint(
            "role IN ('authoring','image','review','item_management','support')",
            name="ck_execution_preset_role",
        ),
        sa.CheckConstraint("timeout_seconds BETWEEN 30 AND 7200", name="ck_preset_role_timeout"),
        sa.ForeignKeyConstraint(
            ["preset_revision_id"],
            ["execution_preset_revisions.preset_revision_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["instruction_bundle_revision_id"],
            ["execution_bundle_revisions.bundle_revision_id"],
        ),
        sa.ForeignKeyConstraint(
            ["reference_bundle_revision_id"],
            ["execution_bundle_revisions.bundle_revision_id"],
        ),
        sa.PrimaryKeyConstraint("preset_revision_id", "role"),
    )

    op.create_table(
        "resolved_execution_plans",
        sa.Column("plan_id", sa.String(length=41), nullable=False),
        sa.Column("workflow_id", sa.String(length=41), nullable=False),
        sa.Column("preset_id", sa.String(length=43), nullable=False),
        sa.Column("preset_revision_id", sa.String(length=46), nullable=False),
        sa.Column("capacity_policy_revision_id", sa.String(length=44), nullable=False),
        sa.Column("graph_snapshot_revision_id", sa.String(length=41), nullable=True),
        sa.Column("evidence_bundle_revision_id", sa.String(length=44), nullable=True),
        sa.Column("plan_sha256", sa.String(length=71), nullable=False),
        sa.Column("resolver_version", sa.String(length=32), nullable=False),
        sa.Column("canonical_document", _json(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(evidence_bundle_revision_id IS NULL) OR (graph_snapshot_revision_id IS NOT NULL)",
            name="ck_execution_plan_evidence_snapshot",
        ),
        sa.CheckConstraint("plan_sha256 ~ '^sha256:[0-9a-f]{64}$'", name="ck_execution_plan_hash"),
        sa.ForeignKeyConstraint(
            ["workflow_id"], ["workflow_instances.workflow_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["preset_id"], ["execution_presets.preset_id"]),
        sa.ForeignKeyConstraint(
            ["preset_revision_id"], ["execution_preset_revisions.preset_revision_id"]
        ),
        sa.ForeignKeyConstraint(
            ["capacity_policy_revision_id"],
            ["worker_capacity_policy_revisions.capacity_policy_revision_id"],
        ),
        sa.PrimaryKeyConstraint("plan_id"),
        sa.UniqueConstraint("workflow_id", name="uq_execution_plan_workflow"),
    )
    op.create_table(
        "resolved_execution_plan_steps",
        sa.Column("plan_id", sa.String(length=41), nullable=False),
        sa.Column("step_key", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("reasoning_effort", sa.String(length=16), nullable=False),
        sa.Column("instruction_bundle_revision_id", sa.String(length=41), nullable=False),
        sa.Column("reference_bundle_revision_id", sa.String(length=41), nullable=True),
        sa.Column("worker_pool_key", sa.String(length=64), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("sandbox", sa.String(length=16), nullable=False),
        sa.Column("network", sa.String(length=16), nullable=False),
        sa.Column("general_knowledge_mode", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "role IN ('authoring','image','review','item_management','support')",
            name="ck_resolved_execution_plan_step_role",
        ),
        sa.CheckConstraint(
            "reasoning_effort IN ('minimal','low','medium','high','xhigh')",
            name="ck_resolved_execution_plan_step_effort",
        ),
        sa.CheckConstraint(
            "general_knowledge_mode IN ('DENIED','ALLOWED_WITH_PROVENANCE')",
            name="ck_resolved_execution_plan_step_knowledge",
        ),
        sa.CheckConstraint("timeout_seconds BETWEEN 30 AND 7200", name="ck_plan_step_timeout"),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["resolved_execution_plans.plan_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["instruction_bundle_revision_id"],
            ["execution_bundle_revisions.bundle_revision_id"],
        ),
        sa.ForeignKeyConstraint(
            ["reference_bundle_revision_id"],
            ["execution_bundle_revisions.bundle_revision_id"],
        ),
        sa.PrimaryKeyConstraint("plan_id", "step_key"),
    )

    op.create_table(
        "codex_auth_bindings",
        sa.Column("binding_id", sa.String(length=44), nullable=False),
        sa.Column("worker_slot_id", sa.String(length=2), nullable=False),
        sa.Column("account_label", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column("codex_cli_version", sa.String(length=32), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resource_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "state IN ('READY','STALE','AUTH_REQUIRED','DEGRADED','DRAINING','DISABLED')",
            name="ck_codex_auth_binding_state",
        ),
        sa.CheckConstraint(
            "(state = 'READY' AND reason_code IS NULL AND observed_at IS NOT NULL "
            "AND valid_until IS NOT NULL AND valid_until > observed_at) OR "
            "(state <> 'READY' AND reason_code IS NOT NULL)",
            name="ck_codex_auth_binding_health_evidence",
        ),
        sa.CheckConstraint("resource_version >= 1", name="ck_codex_auth_binding_version"),
        sa.ForeignKeyConstraint(["worker_slot_id"], ["worker_slots.slot_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("binding_id"),
        sa.UniqueConstraint("worker_slot_id", name="uq_codex_auth_binding_slot"),
    )
    op.create_table(
        "codex_auth_health_events",
        sa.Column("event_id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("binding_id", sa.String(length=44), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column("codex_cli_version", sa.String(length=32), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_codex_auth_health_event_sequence"),
        sa.CheckConstraint("valid_until > observed_at", name="ck_codex_auth_health_event_window"),
        sa.ForeignKeyConstraint(
            ["binding_id"], ["codex_auth_bindings.binding_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint("binding_id", "sequence", name="uq_codex_auth_health_event_sequence"),
    )
    op.create_index(
        "ix_codex_auth_health_events_binding_id", "codex_auth_health_events", ["binding_id"]
    )
    op.create_table(
        "codex_capability_snapshots",
        sa.Column("capability_snapshot_id", sa.String(length=40), nullable=False),
        sa.Column("binding_id", sa.String(length=44), nullable=False),
        sa.Column("codex_cli_version", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_sha256", sa.String(length=71), nullable=False),
        sa.Column("canonical_document", _json(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "source IN ('LOCAL_OBSERVATION','OPERATOR_ASSERTED')",
            name="ck_codex_capability_snapshot_source",
        ),
        sa.CheckConstraint("valid_until > observed_at", name="ck_codex_capability_snapshot_window"),
        sa.CheckConstraint(
            "snapshot_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_codex_capability_snapshot_hash",
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"], ["codex_auth_bindings.binding_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("capability_snapshot_id"),
        sa.UniqueConstraint(
            "binding_id", "snapshot_sha256", name="uq_codex_capability_binding_hash"
        ),
    )
    op.create_index(
        "ix_codex_capability_binding_valid",
        "codex_capability_snapshots",
        ["binding_id", "valid_until"],
    )
    op.create_table(
        "codex_capability_entries",
        sa.Column("capability_snapshot_id", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("reasoning_effort", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.CheckConstraint(
            "reasoning_effort IN ('minimal','low','medium','high','xhigh')",
            name="ck_codex_capability_effort",
        ),
        sa.CheckConstraint(
            "state IN ('AVAILABLE','UNAVAILABLE','UNKNOWN')",
            name="ck_codex_capability_state",
        ),
        sa.ForeignKeyConstraint(
            ["capability_snapshot_id"],
            ["codex_capability_snapshots.capability_snapshot_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("capability_snapshot_id", "model", "reasoning_effort"),
    )

    op.create_table(
        "worker_leases",
        sa.Column("lease_id", sa.String(length=44), nullable=False),
        sa.Column("capacity_policy_revision_id", sa.String(length=44), nullable=False),
        sa.Column("pool_key", sa.String(length=64), nullable=False),
        sa.Column("worker_slot_id", sa.String(length=2), nullable=False),
        sa.Column("binding_id", sa.String(length=44), nullable=False),
        sa.Column("workflow_id", sa.String(length=41), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("workload_class", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("release_reason", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "state IN ('ACTIVE','RELEASED','EXPIRED','RECONCILING')",
            name="ck_worker_lease_state",
        ),
        sa.CheckConstraint(
            "workload_class IN ('CODEX','KNOWLEDGE_ANALYSIS')",
            name="ck_worker_lease_workload_class",
        ),
        sa.CheckConstraint("attempt BETWEEN 1 AND 10", name="ck_worker_lease_attempt"),
        sa.CheckConstraint(
            "expires_at > acquired_at AND ((state IN ('ACTIVE','RECONCILING') "
            "AND released_at IS NULL AND release_reason IS NULL) OR "
            "(state IN ('RELEASED','EXPIRED') AND released_at IS NOT NULL "
            "AND release_reason IS NOT NULL AND released_at >= acquired_at))",
            name="ck_worker_lease_lifecycle",
        ),
        sa.ForeignKeyConstraint(
            ["capacity_policy_revision_id", "pool_key"],
            ["worker_capacity_pools.capacity_policy_revision_id", "worker_capacity_pools.pool_key"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["worker_slot_id"], ["worker_slots.slot_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["binding_id"], ["codex_auth_bindings.binding_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"], ["workflow_instances.workflow_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.job_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("lease_id"),
    )
    op.create_index("ix_worker_leases_workflow_id", "worker_leases", ["workflow_id"])
    op.create_index(
        "uq_worker_lease_held_slot",
        "worker_leases",
        ["worker_slot_id"],
        unique=True,
        postgresql_where=HELD_LEASE_PREDICATE,
    )
    op.create_index(
        "uq_worker_lease_held_job",
        "worker_leases",
        ["job_id"],
        unique=True,
        postgresql_where=HELD_LEASE_PREDICATE,
    )
    op.create_index(
        "ix_worker_lease_policy_pool_state",
        "worker_leases",
        ["capacity_policy_revision_id", "pool_key", "state"],
    )
    op.create_index(
        "ix_worker_lease_reconciliation",
        "worker_leases",
        ["expires_at", "lease_id"],
        postgresql_where=HELD_LEASE_PREDICATE,
    )
    op.create_table(
        "worker_lease_events",
        sa.Column("event_id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("lease_id", sa.String(length=44), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("prior_state", sa.String(length=16), nullable=True),
        sa.Column("new_state", sa.String(length=16), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_worker_lease_event_sequence"),
        sa.ForeignKeyConstraint(["lease_id"], ["worker_leases.lease_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint("lease_id", "sequence", name="uq_worker_lease_event_sequence"),
    )
    op.create_index("ix_worker_lease_events_lease_id", "worker_lease_events", ["lease_id"])

    op.execute(
        """
        CREATE FUNCTION reject_control_plane_immutable_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'immutable Codex control-plane record cannot be changed';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    immutable_tables = (
        "execution_bundle_revisions",
        "worker_capacity_policy_revisions",
        "worker_capacity_pools",
        "worker_capacity_pool_roles",
        "worker_capacity_pool_slots",
        "execution_preset_revisions",
        "execution_preset_role_policies",
        "resolved_execution_plans",
        "resolved_execution_plan_steps",
        "codex_auth_health_events",
        "codex_capability_snapshots",
        "codex_capability_entries",
        "worker_lease_events",
    )
    for table in immutable_tables:
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_control_plane_immutable_mutation()"
        )

    op.execute(
        """
        CREATE FUNCTION validate_control_plane_current_revision() RETURNS trigger AS $$
        DECLARE revision_state text;
        BEGIN
          IF NEW.current_revision_id IS NULL THEN
            RETURN NEW;
          END IF;
          IF TG_TABLE_NAME = 'execution_bundles' THEN
            SELECT state INTO revision_state FROM execution_bundle_revisions
            WHERE bundle_revision_id = NEW.current_revision_id AND bundle_id = NEW.bundle_id;
          ELSIF TG_TABLE_NAME = 'worker_capacity_policies' THEN
            SELECT state INTO revision_state FROM worker_capacity_policy_revisions
            WHERE capacity_policy_revision_id = NEW.current_revision_id
              AND capacity_policy_id = NEW.capacity_policy_id;
          ELSIF TG_TABLE_NAME = 'execution_presets' THEN
            SELECT state INTO revision_state FROM execution_preset_revisions
            WHERE preset_revision_id = NEW.current_revision_id AND preset_id = NEW.preset_id;
          END IF;
          IF revision_state IS DISTINCT FROM 'RELEASED' THEN
            RAISE EXCEPTION 'current control-plane revision must be a released owned revision';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in ("execution_bundles", "worker_capacity_policies", "execution_presets"):
        op.execute(
            f"CREATE TRIGGER {table}_current_revision BEFORE INSERT OR UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION validate_control_plane_current_revision()"
        )

    op.execute(
        """
        CREATE FUNCTION protect_control_plane_logical_identity() RETURNS trigger AS $$
        BEGIN
          IF (to_jsonb(OLD) - ARRAY['state','current_revision_id','updated_at'])
             IS DISTINCT FROM
             (to_jsonb(NEW) - ARRAY['state','current_revision_id','updated_at']) THEN
            RAISE EXCEPTION 'Codex control-plane logical identity is immutable';
          END IF;
          IF OLD.state = 'RETIRED' AND NEW.state <> OLD.state THEN
            RAISE EXCEPTION 'retired Codex control-plane identity cannot be reactivated';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in ("execution_bundles", "worker_capacity_policies", "execution_presets"):
        op.execute(
            f"CREATE TRIGGER {table}_identity_immutable BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION protect_control_plane_logical_identity()"
        )

    op.execute(
        """
        CREATE FUNCTION protect_codex_auth_binding_identity() RETURNS trigger AS $$
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
    op.execute(
        "CREATE TRIGGER codex_auth_bindings_identity_immutable "
        "BEFORE UPDATE ON codex_auth_bindings FOR EACH ROW "
        "EXECUTE FUNCTION protect_codex_auth_binding_identity()"
    )

    op.execute(
        """
        CREATE FUNCTION protect_worker_lease_identity() RETURNS trigger AS $$
        BEGIN
          IF (to_jsonb(OLD) - ARRAY['state','expires_at','released_at','release_reason'])
             IS DISTINCT FROM
             (to_jsonb(NEW) - ARRAY['state','expires_at','released_at','release_reason']) THEN
            RAISE EXCEPTION 'worker lease identity is immutable';
          END IF;
          IF NEW.state = OLD.state THEN
            IF NEW.expires_at < OLD.expires_at THEN
              RAISE EXCEPTION 'worker lease expiry cannot move backward';
            END IF;
          ELSIF NOT (
            (OLD.state = 'ACTIVE' AND NEW.state IN ('RECONCILING','RELEASED')) OR
            (OLD.state = 'RECONCILING' AND NEW.state IN ('RELEASED','EXPIRED'))
          ) THEN
            RAISE EXCEPTION 'invalid worker lease transition';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER worker_leases_identity_immutable BEFORE UPDATE ON worker_leases "
        "FOR EACH ROW EXECUTE FUNCTION protect_worker_lease_identity()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS worker_leases_identity_immutable ON worker_leases")
    op.execute("DROP FUNCTION IF EXISTS protect_worker_lease_identity()")
    op.execute(
        "DROP TRIGGER IF EXISTS codex_auth_bindings_identity_immutable ON codex_auth_bindings"
    )
    op.execute("DROP FUNCTION IF EXISTS protect_codex_auth_binding_identity()")
    for table in ("execution_bundles", "worker_capacity_policies", "execution_presets"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_identity_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS protect_control_plane_logical_identity()")
    for table in ("execution_bundles", "worker_capacity_policies", "execution_presets"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_current_revision ON {table}")
    op.execute("DROP FUNCTION IF EXISTS validate_control_plane_current_revision()")

    immutable_tables = (
        "execution_bundle_revisions",
        "worker_capacity_policy_revisions",
        "worker_capacity_pools",
        "worker_capacity_pool_roles",
        "worker_capacity_pool_slots",
        "execution_preset_revisions",
        "execution_preset_role_policies",
        "resolved_execution_plans",
        "resolved_execution_plan_steps",
        "codex_auth_health_events",
        "codex_capability_snapshots",
        "codex_capability_entries",
        "worker_lease_events",
    )
    for table in immutable_tables:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS reject_control_plane_immutable_mutation()")

    op.drop_index("ix_worker_lease_events_lease_id", table_name="worker_lease_events")
    op.drop_table("worker_lease_events")
    op.drop_index("ix_worker_lease_reconciliation", table_name="worker_leases")
    op.drop_index("ix_worker_lease_policy_pool_state", table_name="worker_leases")
    op.drop_index("uq_worker_lease_held_job", table_name="worker_leases")
    op.drop_index("uq_worker_lease_held_slot", table_name="worker_leases")
    op.drop_index("ix_worker_leases_workflow_id", table_name="worker_leases")
    op.drop_table("worker_leases")
    op.drop_table("codex_capability_entries")
    op.drop_index("ix_codex_capability_binding_valid", table_name="codex_capability_snapshots")
    op.drop_table("codex_capability_snapshots")
    op.drop_index("ix_codex_auth_health_events_binding_id", table_name="codex_auth_health_events")
    op.drop_table("codex_auth_health_events")
    op.drop_table("codex_auth_bindings")
    op.drop_table("resolved_execution_plan_steps")
    op.drop_table("resolved_execution_plans")
    op.drop_table("execution_preset_role_policies")
    op.drop_constraint(
        "fk_execution_presets_current_revision_owner", "execution_presets", type_="foreignkey"
    )
    op.drop_index(
        "ix_execution_preset_revisions_preset_id", table_name="execution_preset_revisions"
    )
    op.drop_table("execution_preset_revisions")
    op.drop_table("execution_presets")
    op.drop_table("worker_capacity_pool_slots")
    op.drop_table("worker_capacity_pool_roles")
    op.drop_table("worker_capacity_pools")
    op.drop_constraint(
        "fk_capacity_policies_current_revision_owner",
        "worker_capacity_policies",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_worker_capacity_policy_revisions_capacity_policy_id",
        table_name="worker_capacity_policy_revisions",
    )
    op.drop_table("worker_capacity_policy_revisions")
    op.drop_table("worker_capacity_policies")
    op.drop_constraint(
        "fk_execution_bundles_current_revision_owner", "execution_bundles", type_="foreignkey"
    )
    op.drop_index(
        "ix_execution_bundle_revisions_bundle_id", table_name="execution_bundle_revisions"
    )
    op.drop_table("execution_bundle_revisions")
    op.drop_table("execution_bundles")
