"""Frozen PostgreSQL DDL and local SQLite CHECK truth tests, never production DB."""

from __future__ import annotations

import ast
import importlib.util
import re
import sqlite3
from pathlib import Path
from typing import Any, cast

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from eom_catalog_service.embedding_registry_models import (
    EmbeddingIndexRecord,
    EmbeddingIndexRevisionRecord,
    EmbeddingSourceBindingRecord,
)
from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION
from sqlalchemy import CheckConstraint, Table, UniqueConstraint
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.schema import CreateIndex, CreateTable

from tests.unit.test_local_embedding_stage_migration import RecordingOperations

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "migrations/versions/20261019_0058_registered_review_embedding.py"


def registered_review_migration() -> Any:
    spec = importlib.util.spec_from_file_location("synthetic_registered_review_migration", PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_revision_and_current_orm_checks_are_exact(monkeypatch):
    module = registered_review_migration()
    assert module.revision == "20261019_0058"
    assert module.down_revision == "20261017_0057"
    assert ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_heads() == [
        CURRENT_MIGRATION_REVISION
    ]
    models = (EmbeddingSourceBindingRecord, EmbeddingIndexRecord, EmbeddingIndexRevisionRecord)
    current = {
        (model.__tablename__, check.name): str(check.sqltext)
        for model in models
        for check in cast(Table, model.__table__).constraints
        if isinstance(check, CheckConstraint)
    }
    # A released migration remains frozen when a later family adds CHECK branches.
    from tests.unit.test_public_solution_embedding_migration import public_solution_migration

    current.update(
        {
            (table, name): value
            for table, name, value in public_solution_migration()._PREVIOUS_CHECKS
        }
    )
    assert len(module._CHECKS) == 7
    for table, name, predicate in module._CHECKS:
        assert current[(table, name)] == predicate
    operations = RecordingOperations()
    monkeypatch.setattr(module, "op", operations)
    module.upgrade()
    assert operations.calls[0] == ("execute", (module._ADD_COLUMNS,), {})
    assert operations.calls[-2:] == [
        ("execute", (module._REGISTERED_UNIQUE,), {}),
        ("execute", (module._REGISTERED_DELTA,), {}),
    ]
    assert [call[1][2] for call in operations.calls if call[0] == "create"] == [
        predicate for _, _, predicate in module._CHECKS
    ]


def test_nullable_branch_fields_default_and_real_base_review_foreign_keys():
    table = cast(Table, EmbeddingSourceBindingRecord.__table__)
    assert table.c.base_analysis_run_id.nullable is False
    assert table.c.solution_analysis_run_id.nullable is True
    assert table.c.solution_pointer_sha256.nullable is True
    assert table.c.review_job_id.nullable is True
    assert table.c.review_evidence_sha256.nullable is True
    assert table.c.evidence_kind.nullable is False
    assert str(table.c.evidence_kind.server_default.arg) == "ACCEPTED_SOLUTION_ANALYSIS"
    assert {fk.target_fullname for fk in table.c.base_analysis_run_id.foreign_keys} == {
        "knowledge_analysis_runs.analysis_run_id"
    }
    assert {fk.target_fullname for fk in table.c.solution_analysis_run_id.foreign_keys} == {
        "knowledge_analysis_runs.analysis_run_id"
    }
    assert {fk.target_fullname for fk in table.c.review_job_id.foreign_keys} == {"jobs.job_id"}
    assert all(fk.ondelete == "RESTRICT" for fk in table.c.review_job_id.foreign_keys)
    ddl = str(CreateTable(table).compile(dialect=dialect()))
    assert "base_analysis_run_id VARCHAR(44) NOT NULL" in ddl
    assert "evidence_kind VARCHAR(40) DEFAULT 'ACCEPTED_SOLUTION_ANALYSIS' NOT NULL" in ddl


def test_original_unique_and_delta_indexes_remain_and_partial_registered_indexes_match():
    module = registered_review_migration()
    table = cast(Table, EmbeddingSourceBindingRecord.__table__)
    unique = next(
        value
        for value in table.constraints
        if isinstance(value, UniqueConstraint) and value.name == "uq_embedding_binding_association"
    )
    assert tuple(unique.columns.keys()) == (
        "item_revision_id",
        "graph_snapshot_revision_id",
        "policy_revision_id",
        "recipe_sha256",
        "view",
        "projection_version",
        "base_analysis_run_id",
        "profile_revision_id",
        "solution_analysis_run_id",
        "encoding_sha256",
    )
    indexes = {index.name: index for index in table.indexes}
    assert "ix_embedding_binding_delta" in indexes
    for name, frozen in (
        ("uq_embedding_binding_registered_review", module._REGISTERED_UNIQUE),
        ("ix_embedding_binding_review_delta", module._REGISTERED_DELTA),
    ):
        compiled = str(CreateIndex(indexes[name]).compile(dialect=dialect()))
        assert "".join(compiled.split()) == "".join(frozen.split())
        assert "review_job_id" in indexes[name].columns
        assert "review_evidence_sha256" in indexes[name].columns
        assert str(indexes[name].dialect_options["postgresql"]["where"]) == (
            "evidence_kind = 'REGISTERED_ITEM_REVIEW_SOLUTION'"
        )
    assert indexes["uq_embedding_binding_registered_review"].unique is True


def test_downgrade_refuses_successor_history_before_any_ddl(monkeypatch):
    module = registered_review_migration()
    operations = RecordingOperations(refuse_history=True)
    monkeypatch.setattr(module, "op", operations)
    with pytest.raises(ValueError, match="history refusal"):
        module.downgrade()
    assert operations.calls == [("execute", (module._REFUSE_NEW_HISTORY,), {})]
    assert all(
        f"FROM {table}" in module._REFUSE_NEW_HISTORY
        for table in ("embedding_source_bindings", "embedding_indexes", "embedding_index_revisions")
    )
    operations = RecordingOperations()
    monkeypatch.setattr(module, "op", operations)
    module.downgrade()
    assert operations.calls[0] == ("execute", (module._REFUSE_NEW_HISTORY,), {})
    assert operations.calls[-1] == ("execute", (module._DROP_COLUMNS,), {})
    assert [call[1][2] for call in operations.calls if call[0] == "create"] == [
        predicate for _, _, predicate in module._PREVIOUS_CHECKS
    ]


def test_migration_never_rewrites_history_or_disables_immutable_guards():
    source = PATH.read_text()
    assert all(
        word not in source
        for word in (
            "CREATE TABLE",
            "UPDATE embedding",
            "DELETE FROM",
            "DISABLE TRIGGER",
            "DROP TRIGGER",
            "DROP TABLE",
            "GRANT ",
        )
    )
    assert "DEFAULT 'ACCEPTED_SOLUTION_ANALYSIS'" in source
    imports = [
        node.module or ""
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
    ]
    assert not any(name.startswith("eom_") for name in imports)


def _valid_binding(registered: bool) -> dict[str, object]:
    digest = "sha256:" + "a" * 64
    return {
        "binding_sha256": digest,
        "source_sha256": digest,
        "profile_sha256": digest,
        "policy_sha256": digest,
        "recipe_sha256": digest,
        "binding_manifest_sha256": digest,
        "evidence_kind": "REGISTERED_ITEM_REVIEW_SOLUTION"
        if registered
        else "ACCEPTED_SOLUTION_ANALYSIS",
        "base_analysis_run_id": "base",
        "solution_analysis_run_id": None if registered else "solution",
        "solution_pointer_sha256": None if registered else digest,
        "review_job_id": "job" if registered else None,
        "review_evidence_sha256": digest if registered else None,
        "source_class": "APPROVED_ITEM" if registered else "PAST_EXAM",
        "projection_version": "registered-item-review-comparison/1.0"
        if registered
        else "accepted-solution-comparison/1.0",
        "binding_manifest_member_path": "index.json",
        "binding_manifest_schema_ref": "eom://schemas/knowledge/embedding-index-manifest/2.0"
        if registered
        else "eom://schemas/knowledge/embedding-index-manifest/1.0",
        "binding_manifest_media_type": "application/json",
    }


def _checks_accept(document: dict[str, object], *, namespace: bool = False) -> bool:
    module = registered_review_migration()
    table = "embedding_indexes" if namespace else "embedding_source_bindings"
    names = (
        {"ck_embedding_index_namespace"}
        if namespace
        else {
            "ck_embedding_binding_hashes",
            "ck_embedding_binding_projection",
            "ck_embedding_binding_runs",
            "ck_embedding_binding_evidence",
            "ck_embedding_binding_member",
        }
    )
    guards = [
        predicate.replace(" ~ ", " REGEXP ")
        for owner, name, predicate in module._CHECKS
        if owner == table and name in names
    ]
    with sqlite3.connect(":memory:") as connection:
        connection.create_function(
            "regexp",
            2,
            lambda pattern, value: value is not None and re.fullmatch(pattern, value) is not None,
        )
        connection.execute(
            "CREATE TABLE value ("
            + ",".join(f"{key} TEXT" for key in document)
            + ", CHECK (("
            + ") AND (".join(guards)
            + ")))"
        )
        try:
            connection.execute(
                "INSERT INTO value VALUES (" + ",".join("?" for _ in document) + ")",
                tuple(document.values()),
            )
        except sqlite3.IntegrityError:
            return False
        return True


@pytest.mark.parametrize("registered", (False, True))
def test_two_real_evidence_shapes_are_allowed_without_casting_review_as_analysis(registered):
    assert _checks_accept(_valid_binding(registered))


@pytest.mark.parametrize(
    "registered,field,value",
    (
        (False, "solution_analysis_run_id", None),
        (False, "solution_pointer_sha256", None),
        (False, "solution_analysis_run_id", "base"),
        (False, "review_job_id", "job"),
        (False, "review_evidence_sha256", "sha256:" + "a" * 64),
        (False, "projection_version", "registered-item-review-comparison/1.0"),
        (True, "solution_analysis_run_id", "solution"),
        (True, "solution_pointer_sha256", "sha256:" + "a" * 64),
        (True, "review_job_id", None),
        (True, "review_evidence_sha256", None),
        (True, "review_evidence_sha256", "bad-hash"),
        (True, "source_class", "PAST_EXAM"),
        (True, "projection_version", "accepted-solution-comparison/1.0"),
        (
            True,
            "binding_manifest_schema_ref",
            "eom://schemas/knowledge/embedding-index-manifest/1.0",
        ),
        (True, "evidence_kind", "UNKNOWN"),
        (False, "evidence_kind", "UNKNOWN"),
    ),
)
def test_xor_rejects_null_hybrids_wrong_source_projection_manifest_and_hash(
    registered, field, value
):
    assert not _checks_accept(_valid_binding(registered) | {field: value})


@pytest.mark.parametrize(
    "projection,population,allowed",
    (
        ("accepted-solution-comparison/1.0", "ALL_ADMITTED_GRAPH_ITEMS", True),
        ("accepted-solution-comparison/1.0", "OCCURRENCE_BACKED_PAST_EXAM", True),
        ("mixed-solution-comparison/2.0", "ALL_ADMITTED_GRAPH_ITEMS", True),
        ("mixed-solution-comparison/2.0", "OCCURRENCE_BACKED_PAST_EXAM", False),
        ("registered-item-review-comparison/1.0", "ALL_ADMITTED_GRAPH_ITEMS", False),
    ),
)
def test_namespace_successor_is_closed_to_mixed_all_scope(projection, population, allowed):
    assert (
        _checks_accept(
            {
                "view": "CONTENT_ONLY",
                "projection_version": projection,
                "population_scope": population,
            },
            namespace=True,
        )
        is allowed
    )
