"""Schema-only queue guards, independent of a database or Codex inference."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest
from eom_orchestrator.control_models import ExecutionPresetValidationRecord
from sqlalchemy import CheckConstraint, LargeBinary, UniqueConstraint


def test_validation_command_is_small_metadata_with_reserved_job_identity() -> None:
    table = ExecutionPresetValidationRecord.__table__
    assert set(table.columns.keys()) == {
        "validation_id",
        "preset_revision_id",
        "base_revision_id",
        "requested_by",
        "idempotency_key",
        "request_sha256",
        "canonical_request",
        "state",
        "requested_at",
        "completed_at",
        "error_code",
    }
    assert list(table.primary_key.columns.keys()) == ["validation_id"]
    assert all(not isinstance(column.type, LargeBinary) for column in table.columns)
    assert not table.c.validation_id.foreign_keys  # Its Job does not exist at enqueue.
    targets = {key.target_fullname for key in table.foreign_keys}
    assert targets == {
        "execution_preset_revisions.preset_revision_id",
        "operators.operator_id",
    }
    assert all(key.ondelete == "RESTRICT" for key in table.foreign_keys)


def test_validation_queue_has_unique_replay_key_and_bounded_pending_keyset() -> None:
    table = ExecutionPresetValidationRecord.__table__
    unique = {
        constraint.name: tuple(constraint.columns.keys())
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert unique["uq_preset_validation_idempotency"] == ("idempotency_key",)
    indexes = {index.name: index for index in table.indexes}
    pending = indexes["ix_preset_validation_pending"]
    assert list(pending.columns.keys()) == ["requested_at", "validation_id"]
    assert str(pending.dialect_options["postgresql"]["where"]) == (
        "state IN ('PENDING','PROCESSING')"
    )


@pytest.mark.parametrize(
    ("constraint_name", "expected"),
    (
        ("ck_preset_validation_id", "^job_[0-9a-f]{32}$"),
        ("ck_preset_validation_request_hash", "^sha256:[0-9a-f]{64}$"),
        ("ck_preset_validation_state", "'PENDING','PROCESSING','SUCCEEDED','FAILED'"),
        ("ck_preset_validation_lifecycle", "completed_at >= requested_at"),
        ("ck_preset_validation_error_code", "^[A-Z][A-Z0-9_]{0,95}$"),
        ("ck_preset_validation_request_identity", "octet_length(canonical_request::text) <= 8192"),
    ),
)
def test_validation_command_constraint_metadata(constraint_name: str, expected: str) -> None:
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in ExecutionPresetValidationRecord.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert expected in checks[constraint_name]
    assert "IS TRUE" in checks["ck_preset_validation_request_identity"]


def test_validation_migration_matches_model_and_protects_request_terminal_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = Path("migrations/versions/20261009_0050_preset_model_validation_queue.py")
    specification = importlib.util.spec_from_file_location(
        "preset_validation_migration", source_path
    )
    assert specification is not None and specification.loader is not None
    migration = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(migration)
    operations = Mock()
    monkeypatch.setattr(migration, "op", operations)
    migration.upgrade()
    name, *definitions = operations.create_table.call_args.args
    assert name == "execution_preset_validations"
    checks = {
        definition.name: str(definition.sqltext)
        for definition in definitions
        if isinstance(definition, CheckConstraint)
    }
    assert checks == {
        definition.name: str(definition.sqltext)
        for definition in ExecutionPresetValidationRecord.__table__.constraints
        if isinstance(definition, CheckConstraint)
    }
    statements = "\n".join(str(call.args[0]) for call in operations.execute.call_args_list)
    assert "BEFORE INSERT OR UPDATE OR DELETE" in statements
    assert "NEW.state <> 'PENDING'" in statements
    assert "OLD.state IN ('SUCCEEDED','FAILED')" in statements
    assert "to_jsonb(OLD) - ARRAY['state','completed_at','error_code']" in statements
    assert "OLD.state = 'PENDING' AND NEW.state IN ('PROCESSING','FAILED')" in statements
    assert (
        "OLD.state = 'PROCESSING' AND NEW.state IN ('PROCESSING','SUCCEEDED','FAILED')"
        in statements
    )
    assert "SECURITY DEFINER" not in statements
    operations.reset_mock()
    migration.downgrade()
    assert "cannot discard preset validation history" in str(operations.execute.call_args_list[0])
    operations.drop_table.assert_called_once_with("execution_preset_validations")
