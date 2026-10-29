"""Frozen successor DDL and CHECK truth tests, with no production database access."""

from __future__ import annotations

import ast
import importlib.util
import re
import sqlite3
from pathlib import Path

import pytest
from eom_catalog_service.embedding_registry_models import (
    EmbeddingIndexRecord,
    EmbeddingIndexRevisionRecord,
    EmbeddingSourceBindingRecord,
)
from sqlalchemy import CheckConstraint
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.schema import CreateIndex

from tests.unit.test_local_embedding_stage_migration import RecordingOperations
from tests.unit.test_registered_review_embedding_migration import _valid_binding

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "migrations/versions/20261029_0063_public_solution_embedding.py"


def public_solution_migration():
    spec = importlib.util.spec_from_file_location("synthetic_public_solution_migration", PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_checks_indexes_and_order_match_current_models(monkeypatch):
    module = public_solution_migration()
    assert module.revision == "20261029_0063"
    assert module.down_revision == "20261027_0062"
    models = (EmbeddingSourceBindingRecord, EmbeddingIndexRecord, EmbeddingIndexRevisionRecord)
    checks = {
        (model.__tablename__, check.name): str(check.sqltext)
        for model in models
        for check in model.__table__.constraints
        if isinstance(check, CheckConstraint)
    }
    assert len(module._CHECKS) == len(module._PREVIOUS_CHECKS) == 6
    assert all(checks[(owner, name)] == value for owner, name, value in module._CHECKS)
    indexes = {value.name: value for value in EmbeddingSourceBindingRecord.__table__.indexes}
    for name, frozen in (
        ("uq_embedding_binding_public_solution", module._PUBLIC_UNIQUE),
        ("ix_embedding_binding_public_solution_delta", module._PUBLIC_DELTA),
    ):
        rendered = str(CreateIndex(indexes[name]).compile(dialect=dialect()))
        assert "".join(rendered.split()) == "".join(frozen.split())
        assert str(indexes[name].dialect_options["postgresql"]["where"]) == (
            "evidence_kind = 'PUBLIC_SOLUTION_REPORT'"
        )
    assert indexes["uq_embedding_binding_public_solution"].unique
    operations = RecordingOperations()
    monkeypatch.setattr(module, "op", operations)
    module.upgrade()
    assert operations.calls[-2:] == [
        ("execute", (module._PUBLIC_UNIQUE,), {}),
        ("execute", (module._PUBLIC_DELTA,), {}),
    ]


def test_downgrade_refuses_new_history_before_ddl(monkeypatch):
    module = public_solution_migration()
    operations = RecordingOperations(refuse_history=True)
    monkeypatch.setattr(module, "op", operations)
    with pytest.raises(ValueError, match="history refusal"):
        module.downgrade()
    assert operations.calls == [("execute", (module._REFUSE_NEW_HISTORY,), {})]


def accepts(document, owner):
    if owner == "embedding_source_bindings":
        document = {"view": "CONCRETE_FACETS"} | document
    guards = [
        value.replace(" ~ ", " REGEXP ")
        for table, _, value in public_solution_migration()._CHECKS
        if table == owner
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


def public_binding(creative=False):
    value = _valid_binding(False)
    value.update(
        evidence_kind="PUBLIC_SOLUTION_REPORT",
        source_class="APPROVED_ITEM" if creative else "PAST_EXAM",
        solution_analysis_run_id=None if creative else "solution",
        projection_version="public-solution-text/1.0",
        view="CONCRETE_FACETS",
        binding_manifest_schema_ref="eom://schemas/knowledge/embedding-index-manifest/3.0",
    )
    return value


@pytest.mark.parametrize("creative", (False, True))
def test_genuine_past_exam_and_creative_families_without_invented_analysis(creative):
    assert accepts(public_binding(creative), "embedding_source_bindings")


@pytest.mark.parametrize(
    "field,value",
    (
        ("review_job_id", "job"),
        ("review_evidence_sha256", "sha256:" + "a" * 64),
        ("solution_pointer_sha256", None),
        ("projection_version", "accepted-solution-comparison/1.0"),
        ("view", "CONTENT_ONLY"),
        ("binding_manifest_schema_ref", "eom://schemas/knowledge/embedding-index-manifest/2.0"),
        ("solution_analysis_run_id", "base"),
    ),
)
def test_public_evidence_cannot_enter_an_older_family(field, value):
    assert not accepts(public_binding() | {field: value}, "embedding_source_bindings")


def test_past_exam_requires_real_solution_analysis_and_legacy_families_stay_valid():
    assert not accepts(
        public_binding() | {"solution_analysis_run_id": None}, "embedding_source_bindings"
    )
    for registered in (False, True):
        value = _valid_binding(registered)
        assert accepts(value, "embedding_source_bindings")
        assert not accepts(
            value
            | {
                "binding_manifest_schema_ref": "eom://schemas/knowledge/embedding-index-manifest/3.0"
            },
            "embedding_source_bindings",
        )


@pytest.mark.parametrize("schema,maximum", (("1.0", 1024), ("2.0", 1024), ("3.0", 16384)))
def test_only_new_family_expands_metadata_coverage(schema, maximum):
    value = {
        "binding_count": 1,
        "eligible_source_count": maximum,
        "manifest_member_path": "index.json",
        "manifest_schema_ref": "eom://schemas/knowledge/embedding-index-manifest/" + schema,
        "manifest_media_type": "application/json",
    }
    # SQLite needs INTEGER affinity for CASE comparisons, unlike string-only branch checks.
    module = public_solution_migration()
    predicate = next(
        value for _, name, value in module._CHECKS if name == "ck_embedding_index_revision_coverage"
    )
    with sqlite3.connect(":memory:") as connection:
        connection.execute(
            "CREATE TABLE value (binding_count INTEGER, eligible_source_count INTEGER, "
            "manifest_schema_ref TEXT, CHECK (" + predicate + "))"
        )
        connection.execute(
            "INSERT INTO value VALUES (?, ?, ?)", (1, maximum, value["manifest_schema_ref"])
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO value VALUES (?, ?, ?)", (1, maximum + 1, value["manifest_schema_ref"])
            )


def test_no_data_rewrite_new_store_or_mutable_application_dependency():
    source = PATH.read_text()
    assert all(
        value not in source
        for value in (
            "UPDATE embedding",
            "DELETE FROM",
            "DISABLE TRIGGER",
            "DROP TABLE",
            "CREATE TABLE",
            "GRANT ",
        )
    )
    imports = [
        node.module or ""
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
    ]
    assert not any(value.startswith("eom_") for value in imports)
