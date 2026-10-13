"""Frozen DDL/SQLite truth table only; not PostgreSQL or live migration evidence."""

from __future__ import annotations

import importlib.util
import itertools
import sqlite3
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest
from eom_workflow_runner.models import WorkflowStepRunRecord
from sqlalchemy import CheckConstraint, Table

from tests.unit.test_local_embedding_stage_migration import RecordingOperations, migration

PATH = Path("migrations/versions/20261013_0054_reference_query_step.py")


def query_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("synthetic_query_step_migration", PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_additive_constraint_and_frozen_predecessor_match_current_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = query_migration()
    assert module.revision == "20261013_0054" and module.down_revision == "20261012_0053"
    assert module._PREVIOUS_PREDICATE == migration()._NATIVE_STEP_PREDICATE
    operations = RecordingOperations()
    monkeypatch.setattr(module, "op", operations)
    module.upgrade()
    assert [call[0] for call in operations.calls] == ["drop", "create"]
    guard = operations.calls[1][1][2]
    model_guard = next(
        str(c.sqltext)
        for c in cast(Table, WorkflowStepRunRecord.__table__).constraints
        if isinstance(c, CheckConstraint) and c.name == module._CHECK
    )
    assert guard == model_guard == module._PREDICATE
    assert "IS NOT DISTINCT FROM" in guard and "attempt = 1" in guard
    assert not any(
        word in PATH.read_text()
        for word in ("CREATE TABLE", "DELETE FROM", "UPDATE workflow", "eom_workflow_runner.models")
    )


def test_actual_constraint_truth_table_preserves_legacy_and_rejects_cross_purpose_pairs() -> None:
    guard = query_migration()._PREDICATE
    database = sqlite3.connect(":memory:")
    try:
        database.execute(
            "CREATE TABLE step (step_type TEXT NOT NULL, result_schema TEXT, "
            "worker_role TEXT, step_key TEXT NOT NULL, attempt INTEGER NOT NULL, "
            "CHECK (" + guard + "))"
        )
        for kind, schema, role, key, attempt in itertools.product(
            ("application", "agent", "terminal"),
            (
                None,
                "authoring-result@1.0",
                "incremental-embedding-result@1.0",
                "embedding-reference-query-result@1.0",
            ),
            (None, "reviewer"),
            ("encode_batch", "encode_reference_query", "complete"),
            (1, 2),
        ):
            native_schema = schema in {
                "incremental-embedding-result@1.0",
                "embedding-reference-query-result@1.0",
            }
            allowed = (kind != "application" and not native_schema) or (
                kind == "application"
                and role is None
                and (
                    (schema == "incremental-embedding-result@1.0" and key == "encode_batch")
                    or (
                        schema == "embedding-reference-query-result@1.0"
                        and key == "encode_reference_query"
                        and attempt == 1
                    )
                )
            )
            values = (kind, schema, role, key, attempt)
            if allowed:
                database.execute("INSERT INTO step VALUES (?,?,?,?,?)", values)
            else:
                with pytest.raises(sqlite3.IntegrityError):
                    database.execute("INSERT INTO step VALUES (?,?,?,?,?)", values)
    finally:
        database.close()


def test_downgrade_refuses_query_history_before_ddl_and_restores_exact_0053(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = query_migration()
    operations = RecordingOperations()
    monkeypatch.setattr(module, "op", operations)
    module.downgrade()
    assert [call[0] for call in operations.calls] == ["execute", "drop", "create"]
    assert operations.calls[-1][1][2] == migration()._NATIVE_STEP_PREDICATE
    refusal = operations.calls[0][1][0]
    for marker in (
        "workflow_definitions",
        "workflow_instances",
        "workflow_step_runs",
        "reference-query/1.0",
        "reference-query-workflow-request/1.0",
        "REFERENCE_QUERY",
        "reference-query-step-output/1.0",
    ):
        assert marker in refusal
    assert "LIKE" not in refusal and "::text" not in refusal
    refused = RecordingOperations(refuse_history=True)
    monkeypatch.setattr(module, "op", refused)
    with pytest.raises(ValueError, match="history refusal"):
        module.downgrade()
    assert [call[0] for call in refused.calls] == ["execute"]
