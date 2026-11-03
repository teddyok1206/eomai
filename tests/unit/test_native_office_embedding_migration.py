"""Only metadata allow-lists change; frozen migration66 and vectors remain intact."""

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest
from eom_catalog_service.embedding_registry_models import (
    EmbeddingIndexRevisionRecord,
    EmbeddingSourceBindingRecord,
)
from sqlalchemy import CheckConstraint

from tests.unit.test_registered_public_solution_migration import registered_public_migration


def migration():
    path = (
        Path(__file__).resolve().parents[2]
        / "migrations/versions/20261103_0071_native_office_embedding_metadata.py"
    )
    spec = importlib.util.spec_from_file_location("native_office_metadata_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_native_metadata71_matches_current_orm_and_exact_frozen66_checks(monkeypatch):
    module = migration()
    assert module.revision == "20261103_0071" and module.down_revision == "20261103_0070"
    assert module._PREVIOUS_CHECKS == registered_public_migration()._CHECKS
    current = {
        (model.__tablename__, c.name): str(c.sqltext)
        for model in (EmbeddingSourceBindingRecord, EmbeddingIndexRevisionRecord)
        for c in model.__table__.constraints
        if isinstance(c, CheckConstraint)
    }
    assert len(module._CHECKS) == 3
    assert all(current[(table, name)] == predicate for table, name, predicate in module._CHECKS)
    operations = Mock()
    monkeypatch.setattr(module, "op", operations)
    module.upgrade()
    assert (
        operations.drop_constraint.call_count == operations.create_check_constraint.call_count == 3
    )
    operations.reset_mock()
    operations.get_bind.return_value.scalar.return_value = True
    with pytest.raises(RuntimeError, match="HISTORY_EXISTS"):
        module.downgrade()
    operations.drop_constraint.assert_not_called()
