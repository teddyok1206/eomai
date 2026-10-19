"""Pure persistence metadata, frozen migration DDL and dependency-boundary checks."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from typing import Any, cast

import eom_catalog_service.knowledge_graph_models
import eom_catalog_service.models  # noqa: F401
import eom_orchestrator.knowledge_analysis_models  # noqa: F401
from alembic.config import Config
from alembic.script import ScriptDirectory
from eom_catalog_service.embedding_registry_models import (
    EmbeddingEncodingRecord,
    EmbeddingIndexRecord,
    EmbeddingIndexRevisionRecord,
    EmbeddingSourceBindingRecord,
)
from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION
from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    MetaData,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql.base import PGDialect
from sqlalchemy.engine import Dialect
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlalchemy.sql.sqltypes import JSON, LargeBinary

ROOT = Path(__file__).resolve().parents[2]
MODELS = (
    EmbeddingEncodingRecord,
    EmbeddingSourceBindingRecord,
    EmbeddingIndexRecord,
    EmbeddingIndexRevisionRecord,
)
TABLES = tuple(cast(Table, model.__table__) for model in MODELS)
POSTGRES_DIALECT = cast(type[Dialect], PGDialect)()


def migration_module() -> Any:
    path = ROOT / "migrations/versions/20261012_0052_embedding_registry.py"
    spec = importlib.util.spec_from_file_location("embedding_registry_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_registry_has_exact_four_tables_and_no_payload_columns() -> None:
    assert {model.__tablename__ for model in MODELS} == {
        "embedding_encodings",
        "embedding_source_bindings",
        "embedding_indexes",
        "embedding_index_revisions",
    }
    forbidden = {"vector", "vectors", "text", "report", "payload", "canonical_document", "state"}
    for table in TABLES:
        assert not forbidden.intersection(table.columns.keys())
        assert not any(isinstance(column.type, (JSON, LargeBinary)) for column in table.columns)
        for constraint in table.foreign_key_constraints:
            assert constraint.ondelete == "RESTRICT"


def test_exact_identifier_lengths_and_separate_hashes() -> None:
    assert cast(String, EmbeddingIndexRecord.__table__.c.index_id.type).length == len(
        "embeddingindex_" + "a" * 32
    )
    assert cast(
        String, EmbeddingIndexRevisionRecord.__table__.c.index_revision_id.type
    ).length == len("embeddingindexrev_" + "a" * 32)
    assert cast(String, EmbeddingSourceBindingRecord.__table__.c.profile_id.type).length == len(
        "inferenceprofile_" + "a" * 32
    )
    assert cast(
        String, EmbeddingSourceBindingRecord.__table__.c.profile_revision_id.type
    ).length == len("inferenceprofilerev_" + "a" * 32)
    revision = EmbeddingIndexRevisionRecord.__table__.c
    assert {
        "index_revision_id",
        "index_id",
        "manifest_artifact_id",
        "manifest_artifact_revision_id",
        "index_sha256",
        "manifest_sha256",
    }.issubset(revision.keys())


def test_composite_artifact_source_current_and_predecessor_foreign_keys() -> None:
    expected = {
        "fk_embedding_encoding_shard_revision": ("shard_artifact_id", "shard_artifact_revision_id"),
        "fk_embedding_binding_item_revision": ("item_id", "item_revision_id"),
        "fk_embedding_binding_manifest_revision": (
            "binding_manifest_artifact_id",
            "binding_manifest_artifact_revision_id",
        ),
        "fk_embedding_index_current_revision": ("index_id", "current_index_revision_id"),
        "fk_embedding_index_previous_revision": ("index_id", "previous_index_revision_id"),
        "fk_embedding_index_manifest_revision": (
            "manifest_artifact_id",
            "manifest_artifact_revision_id",
        ),
    }
    constraints = {
        constraint.name: constraint
        for table in TABLES
        for constraint in table.foreign_key_constraints
    }
    for name, columns in expected.items():
        constraint = constraints[name]
        assert isinstance(constraint, ForeignKeyConstraint)
        assert tuple(constraint.column_keys) == columns
    assert constraints["fk_embedding_index_current_revision"].use_alter
    assert not any(
        "profile" in element.target_fullname
        for constraint in constraints.values()
        for element in constraint.elements
    )


def test_key_uniques_and_delta_indexes_are_not_json_scans() -> None:
    uniques = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for table in TABLES
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert uniques["uq_embedding_encoding_input"] == (
        "storage_partition",
        "space_sha256",
        "input_text_sha256",
    )
    assert uniques["uq_embedding_index_revision_identity"] == ("index_id", "index_revision_id")
    assert uniques["uq_embedding_index_registration"] == ("operation_key",)
    delta = next(
        index
        for index in cast(Table, EmbeddingSourceBindingRecord.__table__).indexes
        if index.name == "ix_embedding_binding_delta"
    )
    assert tuple(column.name for column in delta.columns)[-2:] == (
        "base_analysis_run_id",
        "solution_analysis_run_id",
    )
    for table in TABLES:
        for index in table.indexes:
            assert index.dialect_options["postgresql"]["using"] is False
        assert any(isinstance(constraint, CheckConstraint) for constraint in table.constraints)


def test_frozen_migration_matches_current_ddl_without_runtime_model_imports() -> None:
    module = migration_module()
    normalized = {"".join(statement.split()) for statement in module._DDL}
    successor_path = ROOT / "migrations/versions/20261019_0058_registered_review_embedding.py"
    spec = importlib.util.spec_from_file_location("embedding_registry_0058", successor_path)
    assert spec is not None and spec.loader is not None
    successor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(successor)
    # Compare every original table/index, not just unchanged tables. Project only
    # the explicitly additive 0058 changes back to their frozen 0052 definitions.
    baseline = MetaData()
    for current in TABLES[0].metadata.tables.values():
        copied = current.to_metadata(baseline)
        original_order = {
            (type(value), value.name, tuple(value.columns.keys())): value._creation_order
            for value in current.constraints
        }
        # to_metadata copies a set of constraints; keep original DDL ordering so
        # this remains the exact frozen-byte projection rather than a loose set.
        for value in copied.constraints:
            value._creation_order = original_order[
                (type(value), value.name, tuple(value.columns.keys()))
            ]
    changed = {(owner, name) for owner, name, _predicate in successor._CHECKS}
    for owner in ("embedding_source_bindings", "embedding_indexes", "embedding_index_revisions"):
        table = baseline.tables[owner]
        orders = {constraint.name: constraint._creation_order for constraint in table.constraints}
        for constraint in tuple(table.constraints):
            if (
                owner,
                constraint.name,
            ) in changed or constraint.name == "fk_embedding_binding_review_job":
                table.constraints.remove(constraint)
        for original_owner, name, predicate in successor._PREVIOUS_CHECKS:
            if owner == original_owner:
                restored = CheckConstraint(predicate, name=name)
                restored._creation_order = orders[name]
                table.append_constraint(restored)
    binding = baseline.tables["embedding_source_bindings"]
    for index in tuple(binding.indexes):
        if index.name in {
            "uq_embedding_binding_registered_review",
            "ix_embedding_binding_review_delta",
        }:
            binding.indexes.remove(index)
    for name in ("evidence_kind", "review_job_id", "review_evidence_sha256"):
        binding._columns.remove(binding.c[name])
    binding.c.solution_analysis_run_id.nullable = False
    binding.c.solution_pointer_sha256.nullable = False
    for model in MODELS:
        table = baseline.tables[model.__tablename__]
        statement = str(CreateTable(table).compile(dialect=POSTGRES_DIALECT))
        assert "".join(statement.split()) in normalized
        for index in table.indexes:
            statement = str(CreateIndex(index).compile(dialect=POSTGRES_DIALECT))
            assert "".join(statement.split()) in normalized
    source = (ROOT / "migrations/versions/20261012_0052_embedding_registry.py").read_text()
    imports = [
        node.module for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom)
    ]
    assert not any((name or "").startswith("eom_") for name in imports)
    assert "embedding registry downgrade requires empty registry" in source
    assert "OLD.lock_version + 1" in source
    assert "embedding registry history is immutable" in source
    assert "embedding_indexes_identity_immutable" in source
    assert "GRANT" not in source and "ALTER TABLE workflow" not in source


def test_source_head_and_migration_import_registration() -> None:
    scripts = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert scripts.get_heads() == [CURRENT_MIGRATION_REVISION]
    assert (
        "import eom_catalog_service.embedding_registry_models"
        in (ROOT / "migrations/env.py").read_text()
    )
