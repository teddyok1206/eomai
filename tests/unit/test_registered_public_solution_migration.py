"""Frozen metadata-only successor; no connection to a production database."""

import importlib.util
from pathlib import Path

import pytest
from eom_catalog_service.embedding_registry_models import (
    EmbeddingIndexRevisionRecord,
    EmbeddingSourceBindingRecord,
)
from sqlalchemy import CheckConstraint

from tests.unit.test_local_embedding_stage_migration import RecordingOperations

PATH = (
    Path(__file__).resolve().parents[2]
    / "migrations/versions/20261031_0066_registered_public_solution_index.py"
)


def registered_public_migration():
    spec = importlib.util.spec_from_file_location("synthetic_registered_public_migration", PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_three_check_successor_matches_orm_and_frozen_predecessor(monkeypatch):
    from tests.unit.test_public_solution_embedding_migration import public_solution_migration

    module = registered_public_migration()
    assert module.revision == "20261031_0066" and module.down_revision == "20261031_0065"
    current = {
        (model.__tablename__, value.name): str(value.sqltext)
        for model in (EmbeddingSourceBindingRecord, EmbeddingIndexRevisionRecord)
        for value in model.__table__.constraints
        if isinstance(value, CheckConstraint)
    }
    old = {(table, name): value for table, name, value in public_solution_migration()._CHECKS}
    assert len(module._CHECKS) == len(module._PREVIOUS_CHECKS) == 3
    assert all(current[(table, name)] == value for table, name, value in module._CHECKS)
    assert all(old[(table, name)] == value for table, name, value in module._PREVIOUS_CHECKS)
    operations = RecordingOperations()
    monkeypatch.setattr(module, "op", operations)
    module.upgrade()
    assert [value[0] for value in operations.calls] == ["drop"] * 3 + ["create"] * 3
    assert not any(
        value in PATH.read_text()
        for value in ("CREATE TABLE", "DELETE FROM", "UPDATE ", "DISABLE TRIGGER", "eom_")
    )


def test_downgrade_refuses_new_history_before_changing_constraints(monkeypatch):
    module = registered_public_migration()
    operations = RecordingOperations(refuse_history=True)
    monkeypatch.setattr(module, "op", operations)
    with pytest.raises(ValueError, match="history refusal"):
        module.downgrade()
    assert operations.calls == [("execute", (module._REFUSE_NEW_HISTORY,), {})]
    operations = RecordingOperations()
    monkeypatch.setattr(module, "op", operations)
    module.downgrade()
    assert [value[0] for value in operations.calls] == ["execute"] + ["drop"] * 3 + ["create"] * 3
