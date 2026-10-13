"""Frozen DDL projection only; these tests never connect to or mutate a database."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from sqlalchemy import CheckConstraint, Table
from sqlalchemy.dialects.postgresql.base import PGDialect
from sqlalchemy.engine import Dialect
from sqlalchemy.schema import CreateTable

PATH = Path("migrations/versions/20261012_0053_local_embedding_stage.py")
POSTGRES_DIALECT = cast(type[Dialect], PGDialect)()


def migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("synthetic_native_stage_migration", PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecordingOperations:
    def __init__(self, *, refuse_history: bool = False) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.refuse_history = refuse_history

    def execute(self, statement: str) -> None:
        self.calls.append(("execute", (statement,), {}))
        if self.refuse_history:
            raise ValueError("synthetic native history refusal")

    def drop_constraint(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("drop", args, kwargs))

    def create_check_constraint(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("create", args, kwargs))


def test_revision_predecessor_upgrade_and_models_project_exact_total_boolean_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = migration()
    assert module.revision == "20261012_0053" and module.down_revision == "20261012_0052"
    operations = RecordingOperations()
    monkeypatch.setattr(module, "op", operations)
    module.upgrade()
    assert [call[0] for call in operations.calls] == ["drop", "create", "create"]
    stage = operations.calls[1][1][2]
    guard = operations.calls[2][1][2]
    assert "'LOCAL_EMBEDDING'" in stage and "'INFERENCE_TRANSFER'" in stage
    assert "IS NOT DISTINCT FROM" in guard and "worker_role IS NULL" in guard
    expected = {
        constraint.name: str(constraint.sqltext)
        for constraint in cast(Table, WorkflowStepRunRecord.__table__).constraints
        if isinstance(constraint, CheckConstraint)
    }
    # 0053 stays frozen. Its exact predecessor meaning is retained by0054,
    # while current models project the successor's two exact native purposes.
    spec = importlib.util.spec_from_file_location(
        "synthetic_query_step_successor",
        Path("migrations/versions/20261013_0054_reference_query_step.py"),
    )
    assert spec is not None and spec.loader is not None
    successor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(successor)
    assert guard == successor._PREVIOUS_PREDICATE
    current_guard = expected["ck_workflow_step_runs_local_embedding"]
    assert current_guard == successor._PREDICATE
    ddl = str(
        CreateTable(cast(Table, WorkflowStepRunRecord.__table__)).compile(dialect=POSTGRES_DIALECT)
    )
    assert current_guard in ddl
    assert "step_type VARCHAR(32) NOT NULL" in ddl
    assert "platform_job_id VARCHAR" in ddl and "FOREIGN KEY(platform_job_id)" in ddl
    instance_ddl = str(
        CreateTable(cast(Table, WorkflowInstanceRecord.__table__)).compile(dialect=POSTGRES_DIALECT)
    )
    assert "'LOCAL_EMBEDDING'" in instance_ddl
    assert not any(
        word in PATH.read_text()
        for word in ("CREATE TABLE", "DELETE FROM", "UPDATE workflow", "eom_workflow_runner.models")
    )


def test_empty_downgrade_checks_history_before_any_ddl_and_restores_old_stage_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = migration()
    operations = RecordingOperations()
    monkeypatch.setattr(module, "op", operations)
    module.downgrade()
    assert [call[0] for call in operations.calls] == ["execute", "drop", "drop", "create"]
    refusal = operations.calls[0][1][0]
    for table in ("workflow_definitions", "workflow_instances", "workflow_step_runs"):
        assert f"FROM {table}" in refusal
    assert "schema_version' = 'local-embedding-workflow-request/1.0'" in refusal
    assert "schema_version' = 'local-embedding-workflow-request/1.1'" in refusal
    assert "LIKE" not in refusal and "::text" not in refusal
    assert "'LOCAL_EMBEDDING'" not in operations.calls[-1][1][2]
    assert "'INFERENCE_TRANSFER'" in operations.calls[-1][1][2]


def test_refused_downgrade_makes_no_ddl_call(monkeypatch: pytest.MonkeyPatch) -> None:
    module = migration()
    operations = RecordingOperations(refuse_history=True)
    monkeypatch.setattr(module, "op", operations)
    with pytest.raises(ValueError, match="history refusal"):
        module.downgrade()
    assert len(operations.calls) == 1 and operations.calls[0][0] == "execute"
