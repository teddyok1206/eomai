"""Add registered-review embedding associations without rewriting immutable history.

Revision ID: 20261019_0058
Revises: 20261017_0057
Create Date: 2026-10-19 UTC
"""

from __future__ import annotations

from alembic import op

revision: str = "20261019_0058"
down_revision: str | None = "20261017_0057"
branch_labels: str | None = None
depends_on: str | None = None

# Frozen predicates: migrations never import mutable application models.
_PREVIOUS_CHECKS: tuple[tuple[str, str, str], ...] = (
    (
        "embedding_source_bindings",
        "ck_embedding_binding_hashes",
        "binding_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
        "source_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
        "solution_pointer_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
        "profile_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
        "policy_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
        "recipe_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
        "binding_manifest_sha256 ~ '^sha256:[0-9a-f]{64}$'",
    ),
    (
        "embedding_source_bindings",
        "ck_embedding_binding_projection",
        "projection_version = 'accepted-solution-comparison/1.0'",
    ),
    (
        "embedding_source_bindings",
        "ck_embedding_binding_runs",
        "base_analysis_run_id <> solution_analysis_run_id",
    ),
    (
        "embedding_source_bindings",
        "ck_embedding_binding_member",
        "binding_manifest_member_path = 'index.json' AND "
        "binding_manifest_schema_ref = 'eom://schemas/knowledge/embedding-index-manifest/1.0' "
        "AND binding_manifest_media_type = 'application/json'",
    ),
    (
        "embedding_indexes",
        "ck_embedding_index_namespace",
        "view IN ('CONTENT_ONLY','CONCRETE_FACETS','METADATA_ONLY') AND "
        "projection_version = 'accepted-solution-comparison/1.0' AND "
        "population_scope IN ('ALL_ADMITTED_GRAPH_ITEMS','OCCURRENCE_BACKED_PAST_EXAM')",
    ),
    (
        "embedding_index_revisions",
        "ck_embedding_index_revision_member",
        "manifest_member_path = 'index.json' AND "
        "manifest_schema_ref = 'eom://schemas/knowledge/embedding-index-manifest/1.0' AND "
        "manifest_media_type = 'application/json'",
    ),
)
_CHECKS: tuple[tuple[str, str, str], ...] = (
    (
        "embedding_source_bindings",
        "ck_embedding_binding_hashes",
        "binding_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
        "source_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
        "(solution_pointer_sha256 IS NULL OR "
        "solution_pointer_sha256 ~ '^sha256:[0-9a-f]{64}$') AND "
        "(review_evidence_sha256 IS NULL OR "
        "review_evidence_sha256 ~ '^sha256:[0-9a-f]{64}$') AND "
        "profile_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
        "policy_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
        "recipe_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
        "binding_manifest_sha256 ~ '^sha256:[0-9a-f]{64}$'",
    ),
    (
        "embedding_source_bindings",
        "ck_embedding_binding_projection",
        "projection_version IN ('accepted-solution-comparison/1.0',"
        "'registered-item-review-comparison/1.0')",
    ),
    (
        "embedding_source_bindings",
        "ck_embedding_binding_runs",
        "solution_analysis_run_id IS NULL OR base_analysis_run_id <> solution_analysis_run_id",
    ),
    (
        "embedding_source_bindings",
        "ck_embedding_binding_evidence",
        "(evidence_kind = 'ACCEPTED_SOLUTION_ANALYSIS' AND "
        "solution_analysis_run_id IS NOT NULL AND solution_pointer_sha256 IS NOT NULL AND "
        "review_job_id IS NULL AND review_evidence_sha256 IS NULL AND "
        "projection_version = 'accepted-solution-comparison/1.0' AND "
        "base_analysis_run_id <> solution_analysis_run_id) OR "
        "(evidence_kind = 'REGISTERED_ITEM_REVIEW_SOLUTION' AND "
        "solution_analysis_run_id IS NULL AND solution_pointer_sha256 IS NULL AND "
        "review_job_id IS NOT NULL AND review_evidence_sha256 IS NOT NULL AND "
        "source_class = 'APPROVED_ITEM' AND "
        "projection_version = 'registered-item-review-comparison/1.0')",
    ),
    (
        "embedding_source_bindings",
        "ck_embedding_binding_member",
        "binding_manifest_member_path = 'index.json' AND "
        "binding_manifest_schema_ref IN "
        "('eom://schemas/knowledge/embedding-index-manifest/1.0',"
        "'eom://schemas/knowledge/embedding-index-manifest/2.0') AND "
        "binding_manifest_media_type = 'application/json' AND "
        "(evidence_kind = 'ACCEPTED_SOLUTION_ANALYSIS' OR "
        "binding_manifest_schema_ref = 'eom://schemas/knowledge/embedding-index-manifest/2.0')",
    ),
    (
        "embedding_indexes",
        "ck_embedding_index_namespace",
        "view IN ('CONTENT_ONLY','CONCRETE_FACETS','METADATA_ONLY') AND "
        "((projection_version = 'accepted-solution-comparison/1.0' AND "
        "population_scope IN ('ALL_ADMITTED_GRAPH_ITEMS','OCCURRENCE_BACKED_PAST_EXAM')) OR "
        "(projection_version = 'mixed-solution-comparison/2.0' AND "
        "population_scope = 'ALL_ADMITTED_GRAPH_ITEMS'))",
    ),
    (
        "embedding_index_revisions",
        "ck_embedding_index_revision_member",
        "manifest_member_path = 'index.json' AND "
        "manifest_schema_ref IN ('eom://schemas/knowledge/embedding-index-manifest/1.0',"
        "'eom://schemas/knowledge/embedding-index-manifest/2.0') AND "
        "manifest_media_type = 'application/json'",
    ),
)
_ADD_COLUMNS = """
ALTER TABLE embedding_source_bindings
    ADD COLUMN evidence_kind VARCHAR(40) NOT NULL DEFAULT 'ACCEPTED_SOLUTION_ANALYSIS',
    ADD COLUMN review_job_id VARCHAR(36),
    ADD COLUMN review_evidence_sha256 VARCHAR(71),
    ADD CONSTRAINT fk_embedding_binding_review_job
        FOREIGN KEY (review_job_id) REFERENCES jobs (job_id) ON DELETE RESTRICT,
    ALTER COLUMN solution_analysis_run_id DROP NOT NULL,
    ALTER COLUMN solution_pointer_sha256 DROP NOT NULL
"""
_REGISTERED_UNIQUE = """
CREATE UNIQUE INDEX uq_embedding_binding_registered_review ON embedding_source_bindings
    (item_revision_id, graph_snapshot_revision_id, policy_revision_id, recipe_sha256,
     view, projection_version, base_analysis_run_id, profile_revision_id, encoding_sha256,
     review_job_id, review_evidence_sha256)
    WHERE evidence_kind = 'REGISTERED_ITEM_REVIEW_SOLUTION'
"""
_REGISTERED_DELTA = """
CREATE INDEX ix_embedding_binding_review_delta ON embedding_source_bindings
    (graph_snapshot_revision_id, policy_revision_id, recipe_sha256, view,
     projection_version, item_revision_id, base_analysis_run_id, review_job_id,
     review_evidence_sha256)
    WHERE evidence_kind = 'REGISTERED_ITEM_REVIEW_SOLUTION'
"""
_REFUSE_NEW_HISTORY = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM embedding_source_bindings
        WHERE evidence_kind <> 'ACCEPTED_SOLUTION_ANALYSIS'
           OR review_job_id IS NOT NULL OR review_evidence_sha256 IS NOT NULL
           OR solution_analysis_run_id IS NULL OR solution_pointer_sha256 IS NULL
           OR binding_manifest_schema_ref = 'eom://schemas/knowledge/embedding-index-manifest/2.0'
    ) OR EXISTS (
        SELECT 1 FROM embedding_indexes
        WHERE projection_version = 'mixed-solution-comparison/2.0'
    ) OR EXISTS (
        SELECT 1 FROM embedding_index_revisions
        WHERE manifest_schema_ref = 'eom://schemas/knowledge/embedding-index-manifest/2.0'
    ) THEN
        RAISE EXCEPTION 'registered review downgrade requires absent successor history'
            USING ERRCODE = '23514';
    END IF;
END
$$
"""
_DROP_COLUMNS = """
ALTER TABLE embedding_source_bindings
    ALTER COLUMN solution_analysis_run_id SET NOT NULL,
    ALTER COLUMN solution_pointer_sha256 SET NOT NULL,
    DROP CONSTRAINT fk_embedding_binding_review_job,
    DROP COLUMN review_evidence_sha256,
    DROP COLUMN review_job_id,
    DROP COLUMN evidence_kind
"""


def upgrade() -> None:
    op.execute(_ADD_COLUMNS)
    for table, name, _predicate in _PREVIOUS_CHECKS:
        op.drop_constraint(name, table, type_="check")
    for table, name, predicate in _CHECKS:
        op.create_check_constraint(name, table, predicate)
    op.execute(_REGISTERED_UNIQUE)
    op.execute(_REGISTERED_DELTA)


def downgrade() -> None:
    op.execute(_REFUSE_NEW_HISTORY)
    op.execute("DROP INDEX ix_embedding_binding_review_delta")
    op.execute("DROP INDEX uq_embedding_binding_registered_review")
    for table, name, _predicate in _CHECKS:
        op.drop_constraint(name, table, type_="check")
    for table, name, predicate in _PREVIOUS_CHECKS:
        op.create_check_constraint(name, table, predicate)
    op.execute(_DROP_COLUMNS)
