"""add bounded evidence bundle retrieval

Revision ID: 20260824_0014
Revises: 20260824_0013
Create Date: 2026-08-24 04:30:00Z
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from hashlib import sha256

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260824_0014"
down_revision: str | Sequence[str] | None = "20260824_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCESS_POLICY_REVISION_ID = "accessrev_4f62f8b4c4544443a9d0a809dd1c0bb9"
ACCESS_POLICY_SHA256 = "sha256:bf35bc53cd756efdff81fe4154a639968083b5d91932bdc09deaa439b32fcbc0"
NEW_PERMISSIONS = (
    "knowledge_graph:read",
    "knowledge_graph:retrieve",
    "knowledge_graph:publish",
)


def _stable_id(prefix: str, key: str) -> str:
    return prefix + sha256(f"eom-api-v1:{prefix}:{key}".encode()).hexdigest()[:32]


def upgrade() -> None:
    op.create_table(
        "knowledge_node_terms",
        sa.Column("graph_snapshot_revision_id", sa.String(length=41), nullable=False),
        sa.Column("term", sa.String(length=128), nullable=False),
        sa.Column("node_id", sa.String(length=72), nullable=False),
        sa.ForeignKeyConstraint(
            ["graph_snapshot_revision_id", "node_id"],
            ["knowledge_nodes.graph_snapshot_revision_id", "knowledge_nodes.node_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("graph_snapshot_revision_id", "term", "node_id"),
    )
    op.create_index(
        "ix_knowledge_node_term_lookup",
        "knowledge_node_terms",
        ["graph_snapshot_revision_id", "term", "node_id"],
    )
    op.create_index(
        "ix_knowledge_node_term_reverse",
        "knowledge_node_terms",
        ["graph_snapshot_revision_id", "node_id", "term"],
    )

    op.create_table(
        "education_retrieval_access_policy_revisions",
        sa.Column("access_policy_revision_id", sa.String(length=42), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("content_sha256", sa.String(length=71), nullable=False),
        sa.Column("canonical_document", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("state = 'RELEASED'", name="ck_education_retrieval_policy_state"),
        sa.CheckConstraint(
            "content_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_education_retrieval_policy_hash",
        ),
        sa.PrimaryKeyConstraint("access_policy_revision_id"),
        sa.UniqueConstraint("content_sha256"),
    )
    op.create_table(
        "education_retrieval_requests",
        sa.Column("retrieval_request_id", sa.String(length=42), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("submission_sha256", sa.String(length=71), nullable=False),
        sa.Column("request_sha256", sa.String(length=71), nullable=False),
        sa.Column("canonical_request", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("graph_snapshot_revision_id", sa.String(length=41), nullable=False),
        sa.Column("access_policy_revision_id", sa.String(length=42), nullable=False),
        sa.Column("query_kind", sa.String(length=40), nullable=False),
        sa.Column("requester_role", sa.String(length=16), nullable=False),
        sa.Column("requester_operator_id", sa.String(length=41), nullable=False),
        sa.Column("requester_permissions_sha256", sa.String(length=71), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("state = 'PUBLISHED'", name="ck_education_retrieval_request_state"),
        sa.CheckConstraint(
            "submission_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND request_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND requester_permissions_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_education_retrieval_request_hashes",
        ),
        sa.CheckConstraint(
            "query_kind IN ('CURRICULUM_COMPONENTS','APPROVED_ITEM_STRUCTURE','ITEM_PREPARATION')",
            name="ck_education_retrieval_query_kind",
        ),
        sa.CheckConstraint(
            "requester_role IN ('ADMIN','EDITOR','REVIEWER','WORKER')",
            name="ck_education_retrieval_requester_role",
        ),
        sa.ForeignKeyConstraint(
            ["access_policy_revision_id"],
            ["education_retrieval_access_policy_revisions.access_policy_revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["graph_snapshot_revision_id"],
            ["knowledge_graph_snapshots.graph_snapshot_revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requester_operator_id"], ["operators.operator_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("retrieval_request_id"),
        sa.UniqueConstraint("idempotency_key"),
        sa.UniqueConstraint("request_sha256"),
    )
    op.create_index(
        "ix_education_retrieval_snapshot_created",
        "education_retrieval_requests",
        ["graph_snapshot_revision_id", sa.literal_column("requested_at DESC")],
    )

    op.create_table(
        "evidence_bundles",
        sa.Column("evidence_bundle_id", sa.String(length=41), nullable=False),
        sa.Column("retrieval_request_id", sa.String(length=42), nullable=False),
        sa.Column("current_revision_id", sa.String(length=44), nullable=True),
        sa.Column("created_by_operator_id", sa.String(length=41), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_operator_id"], ["operators.operator_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["retrieval_request_id"],
            ["education_retrieval_requests.retrieval_request_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("evidence_bundle_id"),
        sa.UniqueConstraint("retrieval_request_id"),
    )
    op.create_table(
        "evidence_bundle_revisions",
        sa.Column("evidence_bundle_revision_id", sa.String(length=44), nullable=False),
        sa.Column("evidence_bundle_id", sa.String(length=41), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("retrieval_request_id", sa.String(length=42), nullable=False),
        sa.Column("graph_snapshot_revision_id", sa.String(length=41), nullable=False),
        sa.Column("access_policy_revision_id", sa.String(length=42), nullable=False),
        sa.Column("requester_permissions_sha256", sa.String(length=71), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("context_artifact_id", sa.String(length=41), nullable=False),
        sa.Column("context_artifact_revision_id", sa.String(length=36), nullable=False),
        sa.Column("context_sha256", sa.String(length=71), nullable=False),
        sa.Column("manifest_artifact_id", sa.String(length=41), nullable=False),
        sa.Column("manifest_artifact_revision_id", sa.String(length=36), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=71), nullable=False),
        sa.Column("document_count", sa.Integer(), nullable=False),
        sa.Column("item_revision_count", sa.Integer(), nullable=False),
        sa.Column("graph_node_count", sa.Integer(), nullable=False),
        sa.Column("claim_count", sa.Integer(), nullable=False),
        sa.Column("estimated_context_tokens", sa.Integer(), nullable=False),
        sa.Column("created_by_operator_id", sa.String(length=41), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision_number >= 1", name="ck_evidence_bundle_revision_number"),
        sa.CheckConstraint("state = 'PUBLISHED'", name="ck_evidence_bundle_revision_state"),
        sa.CheckConstraint(
            "context_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND manifest_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND requester_permissions_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_evidence_bundle_revision_hashes",
        ),
        sa.CheckConstraint(
            "document_count >= 0 AND item_revision_count >= 0 "
            "AND graph_node_count >= 1 AND claim_count >= 0 "
            "AND estimated_context_tokens >= 1",
            name="ck_evidence_bundle_revision_counts",
        ),
        sa.ForeignKeyConstraint(
            ["access_policy_revision_id"],
            ["education_retrieval_access_policy_revisions.access_policy_revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["context_artifact_id"], ["artifacts.logical_artifact_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["context_artifact_revision_id"],
            ["artifact_revisions.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_operator_id"], ["operators.operator_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["evidence_bundle_id"], ["evidence_bundles.evidence_bundle_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["graph_snapshot_revision_id"],
            ["knowledge_graph_snapshots.graph_snapshot_revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["manifest_artifact_id"], ["artifacts.logical_artifact_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["manifest_artifact_revision_id"],
            ["artifact_revisions.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["retrieval_request_id"],
            ["education_retrieval_requests.retrieval_request_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("evidence_bundle_revision_id"),
        sa.UniqueConstraint(
            "evidence_bundle_id", "revision_number", name="uq_evidence_bundle_revision"
        ),
        sa.UniqueConstraint("retrieval_request_id", name="uq_evidence_bundle_request"),
        sa.UniqueConstraint("manifest_sha256"),
    )
    op.create_index(
        "ix_evidence_bundle_snapshot",
        "evidence_bundle_revisions",
        ["graph_snapshot_revision_id", "created_at"],
    )
    op.create_foreign_key(
        "fk_evidence_bundle_current_revision",
        "evidence_bundles",
        "evidence_bundle_revisions",
        ["current_revision_id"],
        ["evidence_bundle_revision_id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "evidence_bundle_entries",
        sa.Column("evidence_bundle_revision_id", sa.String(length=44), nullable=False),
        sa.Column("evidence_id", sa.String(length=45), nullable=False),
        sa.Column("evidence_kind", sa.String(length=24), nullable=False),
        sa.Column("evidence_use", sa.String(length=24), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_class", sa.String(length=32), nullable=False),
        sa.Column("intake_batch_id", sa.String(length=39), nullable=True),
        sa.Column("source_file_id", sa.String(length=43), nullable=True),
        sa.Column("item_id", sa.String(length=37), nullable=True),
        sa.Column("item_revision_id", sa.String(length=40), nullable=True),
        sa.Column("source_artifact_id", sa.String(length=41), nullable=False),
        sa.Column("source_artifact_revision_id", sa.String(length=36), nullable=False),
        sa.Column("source_member_path", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.String(length=71), nullable=False),
        sa.Column("source_bytes", sa.BigInteger(), nullable=False),
        sa.Column("source_schema_ref", sa.String(length=256), nullable=True),
        sa.Column("source_media_type", sa.String(length=128), nullable=False),
        sa.Column("source_logical_name", sa.String(length=256), nullable=False),
        sa.Column("graph_node_ids", postgresql.ARRAY(sa.String(length=72)), nullable=False),
        sa.Column("anchor_ids", postgresql.ARRAY(sa.String(length=71)), nullable=False),
        sa.Column("relevance_milli", sa.Integer(), nullable=False),
        sa.Column("answer_bearing", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "evidence_kind IN ('DOCUMENT','ITEM_REVISION','CLAIM','TABLE','FIGURE','EQUATION')",
            name="ck_evidence_bundle_entry_kind",
        ),
        sa.CheckConstraint(
            "evidence_use IN ('GROUNDING','REFERENCE_PATTERN','AVOID_COPY')",
            name="ck_evidence_bundle_entry_use",
        ),
        sa.CheckConstraint(
            "source_kind IN ('CONTENT_INTAKE_FILE','APPROVED_ITEM_REVISION')",
            name="ck_evidence_bundle_entry_source_kind",
        ),
        sa.CheckConstraint(
            "relevance_milli >= 0 AND relevance_milli <= 1000",
            name="ck_evidence_bundle_entry_relevance",
        ),
        sa.CheckConstraint(
            "source_sha256 ~ '^sha256:[0-9a-f]{64}$' AND source_bytes >= 1",
            name="ck_evidence_bundle_entry_source_metadata",
        ),
        sa.CheckConstraint(
            "(source_kind = 'CONTENT_INTAKE_FILE' AND intake_batch_id IS NOT NULL "
            "AND source_file_id IS NOT NULL AND item_id IS NULL AND item_revision_id IS NULL) "
            "OR (source_kind = 'APPROVED_ITEM_REVISION' AND intake_batch_id IS NULL "
            "AND source_file_id IS NULL AND item_id IS NOT NULL AND item_revision_id IS NOT NULL)",
            name="ck_evidence_bundle_entry_source_family",
        ),
        sa.CheckConstraint(
            "cardinality(graph_node_ids) >= 1 AND cardinality(graph_node_ids) <= 16 "
            "AND cardinality(anchor_ids) >= 1 AND cardinality(anchor_ids) <= 32",
            name="ck_evidence_bundle_entry_pointer_counts",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_bundle_revision_id"],
            ["evidence_bundle_revisions.evidence_bundle_revision_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_artifact_id"], ["artifacts.logical_artifact_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_artifact_revision_id"],
            ["artifact_revisions.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("evidence_bundle_revision_id", "evidence_id"),
        sa.UniqueConstraint(
            "evidence_bundle_revision_id",
            "source_artifact_revision_id",
            "source_member_path",
            "evidence_use",
            name="uq_evidence_bundle_entry_source_use",
        ),
    )
    op.create_index(
        "ix_evidence_bundle_entry_source",
        "evidence_bundle_entries",
        ["source_kind", "source_artifact_revision_id"],
    )
    op.create_index(
        "ix_evidence_bundle_entry_nodes",
        "evidence_bundle_entries",
        ["graph_node_ids"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_evidence_bundle_entry_anchors",
        "evidence_bundle_entries",
        ["anchor_ids"],
        postgresql_using="gin",
    )

    for table_name in (
        "education_retrieval_access_policy_revisions",
        "education_retrieval_requests",
        "evidence_bundle_revisions",
        "evidence_bundle_entries",
    ):
        op.execute(
            f"CREATE TRIGGER {table_name}_immutable "
            f"BEFORE UPDATE OR DELETE ON {table_name} FOR EACH ROW "
            "EXECUTE FUNCTION reject_control_plane_immutable_mutation()"
        )

    policy_document = {
        "schema_version": "education-retrieval-access-policy/1.0",
        "access_policy_revision_id": ACCESS_POLICY_REVISION_ID,
        "state": "RELEASED",
        "allowed_query_kinds": [
            "APPROVED_ITEM_STRUCTURE",
            "CURRICULUM_COMPONENTS",
            "ITEM_PREPARATION",
        ],
        "allowed_requester_roles": ["ADMIN", "EDITOR", "REVIEWER", "WORKER"],
        "allowed_source_classes": [
            "APPROVED_ITEM",
            "CURRICULUM",
            "INTERNAL_GUIDE",
            "PAST_EXAM",
            "TEXTBOOK",
        ],
        "answer_bearing_roles": ["ADMIN", "EDITOR", "REVIEWER"],
        "maximum_budget": {
            "max_documents": 16,
            "max_item_revisions": 32,
            "max_graph_nodes": 128,
            "max_claims": 64,
            "max_context_tokens": 16000,
        },
        "created_at": "2026-08-24T00:00:00Z",
        "content_sha256": ACCESS_POLICY_SHA256,
    }
    policy_table = sa.table(
        "education_retrieval_access_policy_revisions",
        sa.column("access_policy_revision_id", sa.String),
        sa.column("schema_version", sa.String),
        sa.column("state", sa.String),
        sa.column("content_sha256", sa.String),
        sa.column("canonical_document", postgresql.JSONB),
        sa.column("created_by", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        policy_table,
        [
            {
                "access_policy_revision_id": ACCESS_POLICY_REVISION_ID,
                "schema_version": policy_document["schema_version"],
                "state": policy_document["state"],
                "content_sha256": ACCESS_POLICY_SHA256,
                "canonical_document": policy_document,
                "created_by": "eom-platform/phase9",
                "created_at": datetime(2026, 8, 24, tzinfo=UTC),
            }
        ],
        multiinsert=False,
    )

    permission_table = sa.table(
        "permissions",
        sa.column("permission_id", sa.String),
        sa.column("permission_key", sa.String),
        sa.column("description", sa.String),
    )
    role_permission_table = sa.table(
        "role_permissions",
        sa.column("role_id", sa.String),
        sa.column("permission_id", sa.String),
    )
    op.bulk_insert(
        permission_table,
        [
            {
                "permission_id": _stable_id("permission_", key),
                "permission_key": key,
                "description": f"Allows {key}",
            }
            for key in NEW_PERMISSIONS
        ],
    )
    op.bulk_insert(
        role_permission_table,
        [
            {
                "role_id": _stable_id("role_", "ADMIN"),
                "permission_id": _stable_id("permission_", key),
            }
            for key in NEW_PERMISSIONS
        ],
    )


def downgrade() -> None:
    for key in NEW_PERMISSIONS:
        permission_id = _stable_id("permission_", key)
        op.execute(
            sa.text("DELETE FROM role_permissions WHERE permission_id = :permission_id").bindparams(
                permission_id=permission_id
            )
        )
        op.execute(
            sa.text("DELETE FROM permissions WHERE permission_id = :permission_id").bindparams(
                permission_id=permission_id
            )
        )
    op.drop_index("ix_evidence_bundle_entry_anchors", table_name="evidence_bundle_entries")
    op.drop_index("ix_evidence_bundle_entry_nodes", table_name="evidence_bundle_entries")
    op.drop_index("ix_evidence_bundle_entry_source", table_name="evidence_bundle_entries")
    op.drop_table("evidence_bundle_entries")
    op.drop_constraint(
        "fk_evidence_bundle_current_revision", "evidence_bundles", type_="foreignkey"
    )
    op.drop_index("ix_evidence_bundle_snapshot", table_name="evidence_bundle_revisions")
    op.drop_table("evidence_bundle_revisions")
    op.drop_table("evidence_bundles")
    op.drop_index(
        "ix_education_retrieval_snapshot_created", table_name="education_retrieval_requests"
    )
    op.drop_table("education_retrieval_requests")
    op.drop_table("education_retrieval_access_policy_revisions")
    op.drop_index("ix_knowledge_node_term_reverse", table_name="knowledge_node_terms")
    op.drop_index("ix_knowledge_node_term_lookup", table_name="knowledge_node_terms")
    op.drop_table("knowledge_node_terms")
