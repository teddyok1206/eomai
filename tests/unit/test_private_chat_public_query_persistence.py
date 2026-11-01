"""Frozen successor DDL and exhaustive local step tuples, not PostgreSQL execution."""

import importlib.util
import itertools
import sqlite3
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.private_chat_query_persistence_guards import (
    PRIVATE_CHAT_QUERY_CONTEXT_PREDICATE,
)

from tests.unit.test_local_embedding_stage_migration import RecordingOperations

ROOT = Path(__file__).resolve().parents[2]


def public_query_migration():
    path = ROOT / "migrations/versions/20261101_0067_private_chat_public_query.py"
    spec = importlib.util.spec_from_file_location("private_public_query_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_successor_check_matches_model_and_keeps_one_original_turn_index(monkeypatch):
    module = public_query_migration()
    assert module.revision == "20261101_0067"
    scripts = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert scripts.get_heads() == [CURRENT_MIGRATION_REVISION]
    assert module.revision in {
        revision.revision for revision in scripts.walk_revisions(head=CURRENT_MIGRATION_REVISION)
    }
    assert module.down_revision == "20261031_0066"
    assert module._CONTEXT_PREDICATE == PRIVATE_CHAT_QUERY_CONTEXT_PREDICATE
    steps = next(
        str(c.sqltext)
        for c in WorkflowStepRunRecord.__table__.constraints
        if c.name == module._STEP_CHECK
    )
    assert steps == module._STEP_PREDICATE
    indexes = [
        index
        for index in WorkflowInstanceRecord.__table__.indexes
        if index.name == "uq_workflow_private_chat_query_turn"
    ]
    assert len(indexes) == 1 and indexes[0].unique
    operation = RecordingOperations()
    monkeypatch.setattr(module, "op", operation)
    module.upgrade()
    assert [c[0] for c in operation.calls] == ["drop", "create", "drop", "create"]
    assert operation.calls[1][1][2] == module._CONTEXT_PREDICATE
    assert operation.calls[3][1][2] == module._STEP_PREDICATE


def test_private2_step_check_extends_only_the_exact_common_result_tuple():
    connection = sqlite3.connect(":memory:")
    module = public_query_migration()
    try:
        connection.execute(
            "CREATE TABLE step (step_type TEXT NOT NULL, result_schema TEXT, worker_role TEXT, "
            "step_key TEXT NOT NULL, attempt INTEGER NOT NULL, CHECK ("
            + module._STEP_PREDICATE
            + "))"
        )
        native = {
            "incremental-embedding-result@1.0": "encode_batch",
            "embedding-reference-query-result@1.0": "encode_reference_query",
            "embedding-private-chat-query-result@1.0": "encode_private_chat_query",
            "embedding-reference-query-result@2.0": "encode_private_chat_query",
        }
        for kind, schema, role, key, attempt in itertools.product(
            ("application", "agent", "terminal"),
            (None, "review-result@12.0", *native),
            (None, "reviewer"),
            set(native.values()) | {"complete", "arbitrary"},
            (1, 2),
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


@pytest.mark.parametrize("history", (False, True))
def test_downgrade_refuses_successor_history_before_ddl_and_never_drops_ownership_guard(
    monkeypatch, history
):
    module = public_query_migration()
    operation = RecordingOperations(refuse_history=history)
    monkeypatch.setattr(module, "op", operation)
    if history:
        with pytest.raises(ValueError, match="history refusal"):
            module.downgrade()
        assert [c[0] for c in operation.calls] == ["execute"]
    else:
        module.downgrade()
        assert [c[0] for c in operation.calls] == ["execute", "drop", "create", "drop", "create"]
        assert operation.calls[-1][1][2] == module._PREVIOUS_CONTEXT_PREDICATE
    raw = (ROOT / "migrations/versions/20261101_0067_private_chat_public_query.py").read_text()
    assert not any(
        word in raw
        for word in (
            "CREATE TABLE",
            "DROP INDEX",
            "UPDATE workflow",
            "DELETE FROM",
            "eom_workflow_runner",
        )
    )
