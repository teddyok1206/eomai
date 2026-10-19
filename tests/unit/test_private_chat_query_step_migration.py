"""Frozen private CHECK/SQLite truth table only, not a real PostgreSQL migration."""

import importlib.util
import itertools
import sqlite3
from pathlib import Path

import pytest
from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION
from eom_workflow_runner.models import WorkflowStepRunRecord
from sqlalchemy import CheckConstraint

from tests.unit.test_local_embedding_stage_migration import RecordingOperations
from tests.unit.test_reference_query_step_migration import query_migration

PATH = Path("migrations/versions/20261017_0057_private_chat_query_step.py")


def private_step_migration():
    spec = importlib.util.spec_from_file_location("synthetic_private_step_migration", PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_private_check_preserves_frozen_0054_and_matches_current_model(monkeypatch):
    module = private_step_migration()
    assert module.revision == "20261017_0057"
    assert CURRENT_MIGRATION_REVISION == "20261019_0058"
    assert module.down_revision == "20261017_0056"
    assert module._PREVIOUS_PREDICATE == query_migration()._PREDICATE
    guard = next(
        str(constraint.sqltext)
        for constraint in WorkflowStepRunRecord.__table__.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name == module._CHECK
    )
    assert guard == module._PREDICATE
    operations = RecordingOperations()
    monkeypatch.setattr(module, "op", operations)
    module.upgrade()
    assert [call[0] for call in operations.calls] == ["drop", "create"]
    assert operations.calls[-1][1][2] == guard
    for forbidden in ("CREATE TABLE", "UPDATE workflow", "DELETE FROM", "eom_workflow_runner"):
        assert forbidden not in PATH.read_text()


def test_private_truth_table_only_adds_the_exact_third_native_tuple():
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute(
            "CREATE TABLE step (step_type TEXT NOT NULL, result_schema TEXT, worker_role TEXT, "
            "step_key TEXT NOT NULL, attempt INTEGER NOT NULL, "
            "CHECK (" + private_step_migration()._PREDICATE + "))"
        )
        native = {
            "incremental-embedding-result@1.0": "encode_batch",
            "embedding-reference-query-result@1.0": "encode_reference_query",
            "embedding-private-chat-query-result@1.0": "encode_private_chat_query",
        }
        for kind, schema, role, key, attempt in itertools.product(
            ("application", "agent", "terminal"),
            (None, "authoring-result@1.0", *native),
            (None, "reviewer"),
            (*native.values(), "complete", "arbitrary"),
            (1, 2, 3),
        ):
            allowed = (kind != "application" and schema not in native) or (
                kind == "application"
                and role is None
                and schema in native
                and key == native[schema]
                and (schema == "incremental-embedding-result@1.0" or attempt == 1)
            )
            if allowed:
                connection.execute(
                    "INSERT INTO step VALUES (?,?,?,?,?)", (kind, schema, role, key, attempt)
                )
            else:
                with pytest.raises(sqlite3.IntegrityError):
                    connection.execute(
                        "INSERT INTO step VALUES (?,?,?,?,?)", (kind, schema, role, key, attempt)
                    )
    finally:
        connection.close()


@pytest.mark.parametrize("history", [False, True])
def test_private_step_downgrade_refuses_retained_history_before_any_ddl(monkeypatch, history):
    module = private_step_migration()
    operations = RecordingOperations(refuse_history=history)
    monkeypatch.setattr(module, "op", operations)
    if history:
        with pytest.raises(ValueError, match="history refusal"):
            module.downgrade()
        assert [call[0] for call in operations.calls] == ["execute"]
    else:
        module.downgrade()
        assert [call[0] for call in operations.calls] == ["execute", "drop", "create"]
        assert operations.calls[-1][1][2] == query_migration()._PREDICATE
    refusal = operations.calls[0][1][0]
    assert "FROM workflow_step_runs" in refusal
    assert "workflow_instances" not in refusal and "workflow_definitions" not in refusal
    for marker in (
        "encode_private_chat_query",
        "embedding-private-chat-query-result@1.0",
        "private-chat-query-step-output/1.0",
    ):
        assert marker in refusal
    assert "LIKE" not in refusal and "::text" not in refusal
