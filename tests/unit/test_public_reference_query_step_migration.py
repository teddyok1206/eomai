"""Released tuple/model and frozen migration checks; no runtime or DB authority."""

import importlib.util
import sqlite3
from pathlib import Path

import pytest
from eom_workflow_runner.models import WorkflowStepRunRecord


def _migration(member):
    path = Path(__file__).resolve().parents[2] / "migrations/versions" / member
    spec = importlib.util.spec_from_file_location("public_reference_step68", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def public_step_migration():
    return _migration("20261102_0068_public_reference_query_step.py")


def test_frozen_predecessor_and_current_model_match_exact_tuple_contract():
    migration = public_step_migration()
    previous = _migration("20261101_0067_private_chat_public_query.py")
    assert migration.down_revision == previous.revision
    assert migration._PREVIOUS == previous._STEP_PREDICATE
    current = next(
        str(c.sqltext)
        for c in WorkflowStepRunRecord.__table__.constraints
        if c.name == migration._CHECK
    )
    assert current == migration._CURRENT
    assert "TG_TABLE_SCHEMA" in migration._FAMILY_FUNCTION
    assert "WHERE workflow_id=$1" in migration._FAMILY_FUNCTION
    assert "NEW.step_key = 'encode_reference_query'" in migration._FAMILY_FUNCTION
    assert "NEW.step_key = 'encode_private_chat_query'" in migration._FAMILY_FUNCTION


@pytest.mark.parametrize("key", ("encode_reference_query", "encode_private_chat_query"))
@pytest.mark.parametrize("attempt", (1, 2))
def test_new_check_is_bounded_to_attempt_one_for_both_result2_step_keys(key, attempt):
    with sqlite3.connect(":memory:") as connection:
        connection.execute(
            "CREATE TABLE step (step_type TEXT, result_schema TEXT, "
            "worker_role TEXT, step_key TEXT, attempt INTEGER, CHECK ("
            + public_step_migration()._CURRENT
            + "))"
        )
        args = ("application", "embedding-reference-query-result@2.0", None, key, attempt)
        if attempt == 1:
            connection.execute("INSERT INTO step VALUES (?,?,?,?,?)", args)
        else:
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO step VALUES (?,?,?,?,?)", args)
