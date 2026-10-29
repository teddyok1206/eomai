"""Add format-neutral public-solution associations, preserving predecessor history.

Revision ID: 20261029_0063
Revises: 20261027_0062
Create Date: 2026-10-29 UTC
"""

from __future__ import annotations

from alembic import op

revision: str = "20261029_0063"
down_revision: str | None = "20261027_0062"
branch_labels: str | None = None
depends_on: str | None = None

# Frozen DDL: runtime models are not dependencies of an historical migration.
_PREVIOUS_CHECKS: tuple[tuple[str, str, str], ...] = (
    (
        "embedding_index_revisions",
        "ck_embedding_index_revision_coverage",
        "binding_count >= 1 AND eligible_source_count >= binding_count AND eligible_s"
        "ource_count <= 1024",
    ),
    (
        "embedding_index_revisions",
        "ck_embedding_index_revision_member",
        "manifest_member_path = 'index.json' AND manifest_schema_ref IN ('eom://schem"
        "as/knowledge/embedding-index-manifest/1.0','eom://schemas/knowledge/embeddin"
        "g-index-manifest/2.0') AND manifest_media_type = 'application/json'",
    ),
    (
        "embedding_indexes",
        "ck_embedding_index_namespace",
        "view IN ('CONTENT_ONLY','CONCRETE_FACETS','METADATA_ONLY') AND ((projection_"
        "version = 'accepted-solution-comparison/1.0' AND population_scope IN ('ALL_A"
        "DMITTED_GRAPH_ITEMS','OCCURRENCE_BACKED_PAST_EXAM')) OR (projection_version "
        "= 'mixed-solution-comparison/2.0' AND population_scope = 'ALL_ADMITTED_GRAPH"
        "_ITEMS'))",
    ),
    (
        "embedding_source_bindings",
        "ck_embedding_binding_evidence",
        "(evidence_kind = 'ACCEPTED_SOLUTION_ANALYSIS' AND solution_analysis_run_id I"
        "S NOT NULL AND solution_pointer_sha256 IS NOT NULL AND review_job_id IS NULL"
        " AND review_evidence_sha256 IS NULL AND projection_version = 'accepted-solut"
        "ion-comparison/1.0' AND base_analysis_run_id <> solution_analysis_run_id) OR"
        " (evidence_kind = 'REGISTERED_ITEM_REVIEW_SOLUTION' AND solution_analysis_ru"
        "n_id IS NULL AND solution_pointer_sha256 IS NULL AND review_job_id IS NOT NU"
        "LL AND review_evidence_sha256 IS NOT NULL AND source_class = 'APPROVED_ITEM'"
        " AND projection_version = 'registered-item-review-comparison/1.0')",
    ),
    (
        "embedding_source_bindings",
        "ck_embedding_binding_member",
        "binding_manifest_member_path = 'index.json' AND binding_manifest_schema_ref "
        "IN ('eom://schemas/knowledge/embedding-index-manifest/1.0','eom://schemas/kn"
        "owledge/embedding-index-manifest/2.0') AND binding_manifest_media_type = 'ap"
        "plication/json' AND (evidence_kind = 'ACCEPTED_SOLUTION_ANALYSIS' OR binding"
        "_manifest_schema_ref = 'eom://schemas/knowledge/embedding-index-manifest/2.0"
        "')",
    ),
    (
        "embedding_source_bindings",
        "ck_embedding_binding_projection",
        "projection_version IN ('accepted-solution-comparison/1.0','registered-item-r"
        "eview-comparison/1.0')",
    ),
)
_CHECKS: tuple[tuple[str, str, str], ...] = (
    (
        "embedding_index_revisions",
        "ck_embedding_index_revision_coverage",
        "binding_count >= 1 AND eligible_source_count >= binding_count AND eligible_s"
        "ource_count <= CASE WHEN manifest_schema_ref = 'eom://schemas/knowledge/embe"
        "dding-index-manifest/3.0' THEN 16384 ELSE 1024 END",
    ),
    (
        "embedding_index_revisions",
        "ck_embedding_index_revision_member",
        "manifest_member_path = 'index.json' AND manifest_schema_ref IN ('eom://schem"
        "as/knowledge/embedding-index-manifest/1.0','eom://schemas/knowledge/embeddin"
        "g-index-manifest/2.0','eom://schemas/knowledge/embedding-index-manifest/3.0'"
        ") AND manifest_media_type = 'application/json'",
    ),
    (
        "embedding_indexes",
        "ck_embedding_index_namespace",
        "view IN ('CONTENT_ONLY','CONCRETE_FACETS','METADATA_ONLY') AND ((projection_"
        "version = 'accepted-solution-comparison/1.0' AND population_scope IN ('ALL_A"
        "DMITTED_GRAPH_ITEMS','OCCURRENCE_BACKED_PAST_EXAM')) OR (projection_version "
        "= 'mixed-solution-comparison/2.0' AND population_scope = 'ALL_ADMITTED_GRAPH"
        "_ITEMS') OR (projection_version = 'public-solution-text/1.0' AND view = 'CON"
        "CRETE_FACETS' AND population_scope = 'ALL_ADMITTED_GRAPH_ITEMS'))",
    ),
    (
        "embedding_source_bindings",
        "ck_embedding_binding_evidence",
        "(evidence_kind = 'ACCEPTED_SOLUTION_ANALYSIS' AND solution_analysis_run_id I"
        "S NOT NULL AND solution_pointer_sha256 IS NOT NULL AND review_job_id IS NULL"
        " AND review_evidence_sha256 IS NULL AND projection_version = 'accepted-solut"
        "ion-comparison/1.0' AND base_analysis_run_id <> solution_analysis_run_id) OR"
        " (evidence_kind = 'REGISTERED_ITEM_REVIEW_SOLUTION' AND solution_analysis_ru"
        "n_id IS NULL AND solution_pointer_sha256 IS NULL AND review_job_id IS NOT NU"
        "LL AND review_evidence_sha256 IS NOT NULL AND source_class = 'APPROVED_ITEM'"
        " AND projection_version = 'registered-item-review-comparison/1.0') OR (evide"
        "nce_kind = 'PUBLIC_SOLUTION_REPORT' AND solution_pointer_sha256 IS NOT NULL "
        "AND review_job_id IS NULL AND review_evidence_sha256 IS NULL AND view = 'CON"
        "CRETE_FACETS' AND projection_version = 'public-solution-text/1.0' AND ((sour"
        "ce_class = 'PAST_EXAM' AND solution_analysis_run_id IS NOT NULL AND base_ana"
        "lysis_run_id <> solution_analysis_run_id) OR source_class = 'APPROVED_ITEM')"
        ")",
    ),
    (
        "embedding_source_bindings",
        "ck_embedding_binding_member",
        "binding_manifest_member_path = 'index.json' AND binding_manifest_schema_ref "
        "IN ('eom://schemas/knowledge/embedding-index-manifest/1.0','eom://schemas/kn"
        "owledge/embedding-index-manifest/2.0','eom://schemas/knowledge/embedding-ind"
        "ex-manifest/3.0') AND binding_manifest_media_type = 'application/json' AND ("
        "(evidence_kind = 'ACCEPTED_SOLUTION_ANALYSIS' AND binding_manifest_schema_re"
        "f IN ('eom://schemas/knowledge/embedding-index-manifest/1.0','eom://schemas/"
        "knowledge/embedding-index-manifest/2.0')) OR (evidence_kind = 'REGISTERED_IT"
        "EM_REVIEW_SOLUTION' AND binding_manifest_schema_ref = 'eom://schemas/knowled"
        "ge/embedding-index-manifest/2.0') OR (evidence_kind = 'PUBLIC_SOLUTION_REPOR"
        "T' AND binding_manifest_schema_ref = 'eom://schemas/knowledge/embedding-inde"
        "x-manifest/3.0'))",
    ),
    (
        "embedding_source_bindings",
        "ck_embedding_binding_projection",
        "projection_version IN ('accepted-solution-comparison/1.0','registered-item-r"
        "eview-comparison/1.0','public-solution-text/1.0')",
    ),
)
_PUBLIC_UNIQUE = """
CREATE UNIQUE INDEX uq_embedding_binding_public_solution ON embedding_source_bindings
    (item_revision_id, graph_snapshot_revision_id, policy_revision_id, recipe_sha256,
    view, projection_version, base_analysis_run_id, profile_revision_id, encoding_sha256,
    solution_pointer_sha256) WHERE evidence_kind = 'PUBLIC_SOLUTION_REPORT'
"""
_PUBLIC_DELTA = """
CREATE INDEX ix_embedding_binding_public_solution_delta ON embedding_source_bindings
    (graph_snapshot_revision_id, policy_revision_id, recipe_sha256, view,
    projection_version, item_revision_id, base_analysis_run_id, solution_pointer_sha256)
    WHERE evidence_kind = 'PUBLIC_SOLUTION_REPORT'
"""
_REFUSE_NEW_HISTORY = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM embedding_source_bindings
        WHERE evidence_kind = 'PUBLIC_SOLUTION_REPORT'
           OR projection_version = 'public-solution-text/1.0'
           OR binding_manifest_schema_ref = 'eom://schemas/knowledge/embedding-index-manifest/3.0'
    ) OR EXISTS (
        SELECT 1 FROM embedding_indexes
        WHERE projection_version = 'public-solution-text/1.0'
    ) OR EXISTS (
        SELECT 1 FROM embedding_index_revisions
        WHERE manifest_schema_ref = 'eom://schemas/knowledge/embedding-index-manifest/3.0'
    ) THEN
        RAISE EXCEPTION 'public solution downgrade requires absent successor history'
            USING ERRCODE = '23514';
    END IF;
END
$$
"""


def upgrade() -> None:
    for table, name, _predicate in _PREVIOUS_CHECKS:
        op.drop_constraint(name, table, type_="check")
    for table, name, predicate in _CHECKS:
        op.create_check_constraint(name, table, predicate)
    op.execute(_PUBLIC_UNIQUE)
    op.execute(_PUBLIC_DELTA)


def downgrade() -> None:
    op.execute(_REFUSE_NEW_HISTORY)
    op.execute("DROP INDEX ix_embedding_binding_public_solution_delta")
    op.execute("DROP INDEX uq_embedding_binding_public_solution")
    for table, name, _predicate in _CHECKS:
        op.drop_constraint(name, table, type_="check")
    for table, name, predicate in _PREVIOUS_CHECKS:
        op.create_check_constraint(name, table, predicate)
