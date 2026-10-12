"""Add bounded pointer-only embedding registry; no runtime admission or grants.

Revision ID: 20261012_0052
Revises: 20261010_0051
Create Date: 2026-10-12 UTC
"""

from __future__ import annotations

from alembic import op

revision: str = "20261012_0052"
down_revision: str | None = "20261010_0051"
branch_labels: str | None = None
depends_on: str | None = None

# Frozen DDL: migrations must not import mutable current application models.
_DDL: tuple[str, ...] = (
    """
CREATE TABLE embedding_encodings (
    encoding_sha256 VARCHAR(71) NOT NULL,
    storage_partition VARCHAR(64) NOT NULL,
    space_sha256 VARCHAR(71) NOT NULL,
    input_text_sha256 VARCHAR(71) NOT NULL,
    shard_artifact_id VARCHAR(41) NOT NULL,
    shard_artifact_revision_id VARCHAR(36) NOT NULL,
    shard_member_path VARCHAR(512) NOT NULL,
    shard_schema_ref VARCHAR(256) NOT NULL,
    shard_media_type VARCHAR(128) NOT NULL,
    shard_sha256 VARCHAR(71) NOT NULL,
    row_index INTEGER NOT NULL,
    registered_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (encoding_sha256),
    CONSTRAINT ck_embedding_encoding_hashes CHECK (encoding_sha256 ~ '^sha256:[0-9a-f]{64}$' AND
        space_sha256 ~ '^sha256:[0-9a-f]{64}$' AND input_text_sha256 ~ '^sha256:[0-9a-f]{64}$' AND
        shard_sha256 ~ '^sha256:[0-9a-f]{64}$' ),
    CONSTRAINT ck_embedding_encoding_partition CHECK (storage_partition ~
        '^[a-z0-9][a-z0-9._-]{0,63}$' ),
    CONSTRAINT ck_embedding_encoding_row CHECK (row_index >= 0 AND row_index < 1024),
    CONSTRAINT ck_embedding_encoding_member CHECK (shard_member_path = 'shard.json' AND
        shard_schema_ref = 'eom://schemas/knowledge/embedding-vector-shard/1.0' AND
        shard_media_type = 'application/json' ),
    CONSTRAINT fk_embedding_encoding_shard_revision FOREIGN KEY(shard_artifact_id,
        shard_artifact_revision_id) REFERENCES artifact_revisions (logical_artifact_id,
        revision_id) ON DELETE RESTRICT,
    CONSTRAINT uq_embedding_encoding_input UNIQUE (storage_partition, space_sha256,
        input_text_sha256),
    CONSTRAINT uq_embedding_encoding_row UNIQUE (shard_artifact_revision_id, shard_member_path,
        row_index)
)
    """,
    """
CREATE INDEX ix_embedding_encoding_shard ON embedding_encodings (shard_artifact_id,
    shard_artifact_revision_id)
    """,
    """
CREATE TABLE embedding_source_bindings (
    binding_sha256 VARCHAR(71) NOT NULL,
    encoding_sha256 VARCHAR(71) NOT NULL,
    item_id VARCHAR(37) NOT NULL,
    item_revision_id VARCHAR(40) NOT NULL,
    source_class VARCHAR(16) NOT NULL,
    source_sha256 VARCHAR(71) NOT NULL,
    base_analysis_run_id VARCHAR(44) NOT NULL,
    solution_analysis_run_id VARCHAR(44) NOT NULL,
    solution_pointer_sha256 VARCHAR(71) NOT NULL,
    profile_id VARCHAR(49) NOT NULL,
    profile_revision_id VARCHAR(52) NOT NULL,
    profile_sha256 VARCHAR(71) NOT NULL,
    graph_snapshot_revision_id VARCHAR(41) NOT NULL,
    policy_revision_id VARCHAR(42) NOT NULL,
    policy_sha256 VARCHAR(71) NOT NULL,
    view VARCHAR(16) NOT NULL,
    recipe_sha256 VARCHAR(71) NOT NULL,
    projection_version VARCHAR(64) NOT NULL,
    binding_manifest_artifact_id VARCHAR(41) NOT NULL,
    binding_manifest_artifact_revision_id VARCHAR(36) NOT NULL,
    binding_manifest_member_path VARCHAR(512) NOT NULL,
    binding_manifest_schema_ref VARCHAR(256) NOT NULL,
    binding_manifest_media_type VARCHAR(128) NOT NULL,
    binding_manifest_sha256 VARCHAR(71) NOT NULL,
    registered_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (binding_sha256),
    CONSTRAINT ck_embedding_binding_hashes CHECK (binding_sha256 ~ '^sha256:[0-9a-f]{64}$' AND
        source_sha256 ~ '^sha256:[0-9a-f]{64}$' AND solution_pointer_sha256 ~
        '^sha256:[0-9a-f]{64}$' AND profile_sha256 ~ '^sha256:[0-9a-f]{64}$' AND policy_sha256 ~
        '^sha256:[0-9a-f]{64}$' AND recipe_sha256 ~ '^sha256:[0-9a-f]{64}$' AND
        binding_manifest_sha256 ~ '^sha256:[0-9a-f]{64}$' ),
    CONSTRAINT ck_embedding_binding_source CHECK (source_class IN ('PAST_EXAM','APPROVED_ITEM')),
    CONSTRAINT ck_embedding_binding_view CHECK (view IN
        ('CONTENT_ONLY','CONCRETE_FACETS','METADATA_ONLY')),
    CONSTRAINT ck_embedding_binding_projection CHECK (projection_version =
        'accepted-solution-comparison/1.0' ),
    CONSTRAINT ck_embedding_binding_runs CHECK (base_analysis_run_id <> solution_analysis_run_id),
    CONSTRAINT ck_embedding_binding_profile CHECK (profile_id ~ '^inferenceprofile_[0-9a-f]{32}$'
        AND profile_revision_id ~ '^inferenceprofilerev_[0-9a-f]{32}$' ),
    CONSTRAINT ck_embedding_binding_member CHECK (binding_manifest_member_path = 'index.json' AND
        binding_manifest_schema_ref = 'eom://schemas/knowledge/embedding-index-manifest/1.0' AND
        binding_manifest_media_type = 'application/json' ),
    CONSTRAINT fk_embedding_binding_item_revision FOREIGN KEY(item_id, item_revision_id) REFERENCES
        item_revisions (item_id, item_revision_id) ON DELETE RESTRICT,
    CONSTRAINT fk_embedding_binding_manifest_revision FOREIGN KEY(binding_manifest_artifact_id,
        binding_manifest_artifact_revision_id) REFERENCES artifact_revisions (logical_artifact_id,
        revision_id) ON DELETE RESTRICT,
    CONSTRAINT uq_embedding_binding_association UNIQUE (item_revision_id,
        graph_snapshot_revision_id, policy_revision_id, recipe_sha256, view, projection_version,
        base_analysis_run_id, profile_revision_id, solution_analysis_run_id, encoding_sha256),
    FOREIGN KEY(encoding_sha256) REFERENCES embedding_encodings (encoding_sha256) ON DELETE
        RESTRICT,
    FOREIGN KEY(base_analysis_run_id) REFERENCES knowledge_analysis_runs (analysis_run_id) ON
        DELETE RESTRICT,
    FOREIGN KEY(solution_analysis_run_id) REFERENCES knowledge_analysis_runs (analysis_run_id) ON
        DELETE RESTRICT,
    FOREIGN KEY(graph_snapshot_revision_id) REFERENCES knowledge_graph_snapshots
        (graph_snapshot_revision_id) ON DELETE RESTRICT,
    FOREIGN KEY(policy_revision_id) REFERENCES education_retrieval_access_policy_revisions
        (access_policy_revision_id) ON DELETE RESTRICT
)
    """,
    """
CREATE INDEX ix_embedding_binding_delta ON embedding_source_bindings
    (graph_snapshot_revision_id, policy_revision_id, recipe_sha256, view, projection_version,
    item_revision_id, base_analysis_run_id, solution_analysis_run_id)
    """,
    """
CREATE INDEX ix_embedding_binding_encoding ON embedding_source_bindings (encoding_sha256)
    """,
    """
CREATE INDEX ix_embedding_binding_source ON embedding_source_bindings (item_id,
    item_revision_id)
    """,
    """
CREATE TABLE embedding_indexes (
    index_id VARCHAR(47) NOT NULL,
    corpus_id VARCHAR(39) NOT NULL,
    storage_partition VARCHAR(64) NOT NULL,
    space_sha256 VARCHAR(71) NOT NULL,
    view VARCHAR(16) NOT NULL,
    recipe_sha256 VARCHAR(71) NOT NULL,
    projection_version VARCHAR(64) NOT NULL,
    population_scope VARCHAR(64) NOT NULL,
    current_index_revision_id VARCHAR(50),
    lock_version INTEGER NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (index_id),
    CONSTRAINT ck_embedding_index_id CHECK (index_id ~ '^embeddingindex_[0-9a-f]{32}$'),
    CONSTRAINT ck_embedding_index_namespace_hashes CHECK (storage_partition ~
        '^[a-z0-9][a-z0-9._-]{0,63}$' AND space_sha256 ~ '^sha256:[0-9a-f]{64}$' AND recipe_sha256
        ~ '^sha256:[0-9a-f]{64}$' ),
    CONSTRAINT ck_embedding_index_namespace CHECK (view IN
        ('CONTENT_ONLY','CONCRETE_FACETS','METADATA_ONLY') AND projection_version =
        'accepted-solution-comparison/1.0' AND population_scope IN
        ('ALL_ADMITTED_GRAPH_ITEMS','OCCURRENCE_BACKED_PAST_EXAM')),
    CONSTRAINT ck_embedding_index_current_version CHECK ((current_index_revision_id IS NULL AND
        lock_version = 1) OR (current_index_revision_id IS NOT NULL AND lock_version >= 2)),
    CONSTRAINT uq_embedding_index_namespace UNIQUE (corpus_id, storage_partition, space_sha256,
        view, recipe_sha256, projection_version, population_scope),
    FOREIGN KEY(corpus_id) REFERENCES knowledge_corpora (corpus_id) ON DELETE RESTRICT
)
    """,
    """
CREATE TABLE embedding_index_revisions (
    index_revision_id VARCHAR(50) NOT NULL,
    index_id VARCHAR(47) NOT NULL,
    revision_number INTEGER NOT NULL,
    previous_index_revision_id VARCHAR(50),
    graph_snapshot_revision_id VARCHAR(41) NOT NULL,
    policy_revision_id VARCHAR(42) NOT NULL,
    policy_sha256 VARCHAR(71) NOT NULL,
    manifest_artifact_id VARCHAR(41) NOT NULL,
    manifest_artifact_revision_id VARCHAR(36) NOT NULL,
    manifest_member_path VARCHAR(512) NOT NULL,
    manifest_schema_ref VARCHAR(256) NOT NULL,
    manifest_media_type VARCHAR(128) NOT NULL,
    manifest_sha256 VARCHAR(71) NOT NULL,
    index_sha256 VARCHAR(71) NOT NULL,
    source_set_sha256 VARCHAR(71) NOT NULL,
    binding_set_sha256 VARCHAR(71) NOT NULL,
    eligible_source_count BIGINT NOT NULL,
    binding_count BIGINT NOT NULL,
    operation_key VARCHAR(128) NOT NULL,
    registration_request_sha256 VARCHAR(71) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (index_revision_id),
    CONSTRAINT ck_embedding_index_revision_id CHECK (index_revision_id ~
        '^embeddingindexrev_[0-9a-f]{32}$' ),
    CONSTRAINT ck_embedding_index_revision_predecessor CHECK ((revision_number = 1 AND
        previous_index_revision_id IS NULL) OR (revision_number > 1 AND previous_index_revision_id
        IS NOT NULL AND previous_index_revision_id <> index_revision_id)),
    CONSTRAINT ck_embedding_index_revision_hashes CHECK (policy_sha256 ~ '^sha256:[0-9a-f]{64}$'
        AND manifest_sha256 ~ '^sha256:[0-9a-f]{64}$' AND index_sha256 ~ '^sha256:[0-9a-f]{64}$'
        AND source_set_sha256 ~ '^sha256:[0-9a-f]{64}$' AND binding_set_sha256 ~
        '^sha256:[0-9a-f]{64}$' AND registration_request_sha256 ~ '^sha256:[0-9a-f]{64}$' ),
    CONSTRAINT ck_embedding_index_revision_coverage CHECK (binding_count >= 1 AND
        eligible_source_count >= binding_count AND eligible_source_count <= 1024),
    CONSTRAINT ck_embedding_index_revision_member CHECK (manifest_member_path = 'index.json' AND
        manifest_schema_ref = 'eom://schemas/knowledge/embedding-index-manifest/1.0' AND
        manifest_media_type = 'application/json' ),
    CONSTRAINT ck_embedding_index_registration_key CHECK (operation_key ~
        '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' ),
    CONSTRAINT fk_embedding_index_previous_revision FOREIGN KEY(index_id,
        previous_index_revision_id) REFERENCES embedding_index_revisions (index_id,
        index_revision_id) ON DELETE RESTRICT,
    CONSTRAINT fk_embedding_index_manifest_revision FOREIGN KEY(manifest_artifact_id,
        manifest_artifact_revision_id) REFERENCES artifact_revisions (logical_artifact_id,
        revision_id) ON DELETE RESTRICT,
    CONSTRAINT uq_embedding_index_revision_number UNIQUE (index_id, revision_number),
    CONSTRAINT uq_embedding_index_revision_identity UNIQUE (index_id, index_revision_id),
    CONSTRAINT uq_embedding_index_registration UNIQUE (operation_key),
    CONSTRAINT uq_embedding_index_manifest UNIQUE (manifest_artifact_id,
        manifest_artifact_revision_id, manifest_member_path),
    FOREIGN KEY(index_id) REFERENCES embedding_indexes (index_id) ON DELETE RESTRICT,
    FOREIGN KEY(graph_snapshot_revision_id) REFERENCES knowledge_graph_snapshots
        (graph_snapshot_revision_id) ON DELETE RESTRICT,
    FOREIGN KEY(policy_revision_id) REFERENCES education_retrieval_access_policy_revisions
        (access_policy_revision_id) ON DELETE RESTRICT
)
    """,
    """
CREATE INDEX ix_embedding_index_revision_graph ON embedding_index_revisions
    (graph_snapshot_revision_id, index_id, revision_number)
    """,
    """
ALTER TABLE embedding_indexes ADD CONSTRAINT fk_embedding_index_current_revision FOREIGN
    KEY(index_id, current_index_revision_id) REFERENCES embedding_index_revisions (index_id,
    index_revision_id) ON DELETE RESTRICT
    """,
    """
CREATE FUNCTION reject_embedding_registry_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'embedding registry history is immutable' USING ERRCODE = '23514';
END
$$
    """,
    """
CREATE FUNCTION protect_embedding_index_head() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'embedding index identity is immutable' USING ERRCODE = '23514';
    END IF;
    IF (to_jsonb(NEW) - ARRAY['current_index_revision_id','lock_version','updated_at'])
       IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY['current_index_revision_id','lock_version','updated_at']) THEN
        RAISE EXCEPTION 'embedding index identity is immutable' USING ERRCODE = '23514';
    END IF;
    IF NEW.current_index_revision_id IS NOT DISTINCT FROM OLD.current_index_revision_id
       OR NEW.current_index_revision_id IS NULL OR NEW.lock_version <> OLD.lock_version + 1
       OR NEW.updated_at < OLD.updated_at THEN
        RAISE EXCEPTION 'embedding index head must advance one fenced version'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$
    """,
    """
CREATE TRIGGER embedding_encodings_immutable BEFORE UPDATE OR DELETE ON embedding_encodings FOR
    EACH ROW EXECUTE FUNCTION reject_embedding_registry_mutation()
    """,
    """
CREATE TRIGGER embedding_source_bindings_immutable BEFORE UPDATE OR DELETE ON
    embedding_source_bindings FOR EACH ROW EXECUTE FUNCTION reject_embedding_registry_mutation()
    """,
    """
CREATE TRIGGER embedding_index_revisions_immutable BEFORE UPDATE OR DELETE ON
    embedding_index_revisions FOR EACH ROW EXECUTE FUNCTION reject_embedding_registry_mutation()
    """,
    """
CREATE TRIGGER embedding_indexes_identity_immutable BEFORE UPDATE OR DELETE ON embedding_indexes
    FOR EACH ROW EXECUTE FUNCTION protect_embedding_index_head()
    """,
)


def upgrade() -> None:
    for statement in _DDL:
        op.execute(statement)


def downgrade() -> None:
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM embedding_encodings)
           OR EXISTS (SELECT 1 FROM embedding_source_bindings)
           OR EXISTS (SELECT 1 FROM embedding_indexes)
           OR EXISTS (SELECT 1 FROM embedding_index_revisions) THEN
            RAISE EXCEPTION 'embedding registry downgrade requires empty registry'
                USING ERRCODE = '23514';
        END IF;
    END
    $$
    """)
    op.drop_constraint(
        "fk_embedding_index_current_revision", "embedding_indexes", type_="foreignkey"
    )
    for table in (
        "embedding_source_bindings",
        "embedding_index_revisions",
        "embedding_encodings",
        "embedding_indexes",
    ):
        op.drop_table(table)
    op.execute("DROP FUNCTION protect_embedding_index_head()")
    op.execute("DROP FUNCTION reject_embedding_registry_mutation()")
