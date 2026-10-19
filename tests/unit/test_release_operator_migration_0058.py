"""Additive0058 release context with synthetic root/runtime/database seams only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from jsonschema import Draft202012Validator

from scripts.api import release_operator_runtime as operator
from tests.unit.test_release_operator_runtime import FakeEngine, _context_value, _hash, _json
from tests.unit.test_release_operator_runtime import synthetic_stage as synthetic_stage

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def registered_review_stage(
    synthetic_stage: tuple[Path, operator.OperatorContext, str],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, operator.OperatorContext, str]:
    from eom_orchestrator import migration

    path, _, _ = synthetic_stage
    value = json.loads(path.read_bytes())
    value.update(schema_version="release-operator-context/1.7", migration_revision="20261019_0058")
    path.write_bytes(_json(value))
    digest = _hash(path.read_bytes())
    monkeypatch.setattr(migration, "CURRENT_MIGRATION_REVISION", "20261019_0058")
    return path, operator.load_context(path, digest, "a" * 40), digest


def test_schema_successor_changes_only_literal_version_and_target() -> None:
    previous = json.loads(
        (ROOT / "scripts/api/release_operator_context_v1_6.schema.json").read_bytes()
    )
    raw = (ROOT / "scripts/api/release_operator_context_v1_7.schema.json").read_bytes()
    assert _hash(raw) == operator._SCHEMA_V1_7_SHA256
    assert (
        raw == (ROOT / "schemas/operations/release-operator-context-v1_7.schema.json").read_bytes()
    )
    assert _hash((ROOT / "scripts/api/release_operator_context_v1_6.schema.json").read_bytes()) == (
        operator._SCHEMA_V1_6_SHA256
    )
    schema = json.loads(raw)
    Draft202012Validator.check_schema(schema)
    previous["$id"] = schema["$id"]
    for section in ("context", "receipt"):
        for key in ("schema_version", "migration_revision"):
            previous["$defs"][section]["properties"][key] = schema["$defs"][section]["properties"][
                key
            ]
    assert previous == schema
    value = _context_value() | {
        "schema_version": "release-operator-context/1.7",
        "migration_revision": "20261019_0058",
    }
    validator = Draft202012Validator(schema)
    validator.validate(value)
    for change in (
        {"migration_revision": "head"},
        {"migration_revision": "20261017_0057"},
        {"migration_revision": True},
        {"command": "arbitrary"},
        {"role": "ADMIN"},
        {"schema_version": "release-operator-context/1.6"},
    ):
        assert not validator.is_valid(value | change)


@pytest.mark.parametrize(
    "callback,revision,owner,success,upgrades",
    [
        (operator.Callback.MIGRATION_VERIFY_0058, "20261019_0058", True, True, 0),
        (operator.Callback.MIGRATION_VERIFY_0058, "20261017_0057", True, False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0058, "20261017_0057", True, True, 1),
        (operator.Callback.MIGRATION_UPGRADE_0058, "20261019_0058", True, True, 0),
        (operator.Callback.MIGRATION_UPGRADE_0058, "20261014_0055", True, False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0058, "unknown", True, False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0058, "20261017_0057", False, False, 0),
    ],
)
def test_exact_predecessor_target_owner_and_replay(
    registered_review_stage: tuple[Path, operator.OperatorContext, str],
    monkeypatch: pytest.MonkeyPatch,
    callback: operator.Callback,
    revision: str,
    owner: bool,
    success: bool,
    upgrades: int,
) -> None:
    from alembic import command
    from eom_api import build_info
    from eom_orchestrator import database

    path, context, _digest = registered_review_stage
    monkeypatch.setattr(build_info, "get_build_info", lambda: context)
    engine = FakeEngine(revision, owner=owner)
    monkeypatch.setattr(database, "build_engine", lambda: engine)
    calls: list[str] = []

    def upgrade(_config: Any, target: str) -> None:
        assert target == "20261019_0058"
        calls.append(target)
        engine.revision = target

    monkeypatch.setattr(command, "upgrade", upgrade)
    if success:
        operator.run_callback(path.parent, context, callback)
    else:
        with pytest.raises(operator.OperatorRuntimeError):
            operator.run_callback(path.parent, context, callback)
    assert len(calls) == upgrades and engine.disposed


@pytest.mark.parametrize(
    "callback",
    [
        operator.Callback.MIGRATION_VERIFY,
        operator.Callback.MIGRATION_UPGRADE_0051,
        operator.Callback.MIGRATION_VERIFY_0052,
        operator.Callback.MIGRATION_UPGRADE_0052,
        operator.Callback.MIGRATION_VERIFY_0053,
        operator.Callback.MIGRATION_UPGRADE_0053,
        operator.Callback.MIGRATION_VERIFY_0054,
        operator.Callback.MIGRATION_UPGRADE_0054,
        operator.Callback.MIGRATION_VERIFY_0055,
        operator.Callback.MIGRATION_UPGRADE_0055,
        operator.Callback.MIGRATION_VERIFY_0056,
        operator.Callback.MIGRATION_UPGRADE_0056,
        operator.Callback.MIGRATION_VERIFY_0057,
        operator.Callback.MIGRATION_UPGRADE_0057,
    ],
)
def test_old_callbacks_are_not_repointed_to_new_head(
    registered_review_stage: tuple[Path, operator.OperatorContext, str],
    monkeypatch: pytest.MonkeyPatch,
    callback: operator.Callback,
) -> None:
    from eom_api import build_info
    from eom_orchestrator import database

    path, context, _digest = registered_review_stage
    monkeypatch.setattr(build_info, "get_build_info", lambda: context)
    database_factory = Mock()
    monkeypatch.setattr(database, "build_engine", database_factory)
    with pytest.raises(operator.OperatorRuntimeError, match="REVISION_UNSUPPORTED"):
        operator.run_callback(path.parent, context, callback)
    database_factory.assert_not_called()


def test_receipt_pin_is_versioned_and_old_context_is_not_reused(
    registered_review_stage: tuple[Path, operator.OperatorContext, str],
) -> None:
    path, context, digest = registered_review_stage
    operator.admit(path, context, digest)
    operator.verify_admission(path, context, digest)
    receipt_path = path.parent / "operator-admission.json"
    value = json.loads(receipt_path.read_bytes())
    assert value["schema_version"] == "release-operator-admission/1.7"
    value.update(
        schema_version="release-operator-admission/1.6", migration_revision="20261017_0057"
    )
    receipt_path.write_bytes(_json(value))
    with pytest.raises(operator.OperatorRuntimeError, match="ADMISSION_CHANGED"):
        operator.verify_admission(path, context, digest)


def test_context_target_does_not_borrow_an_old_source_head_or_read_credentials(
    registered_review_stage: tuple[Path, operator.OperatorContext, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from eom_api import build_info
    from eom_orchestrator import database, migration

    path, context, _digest = registered_review_stage
    monkeypatch.setattr(build_info, "get_build_info", lambda: context)
    monkeypatch.setattr(migration, "CURRENT_MIGRATION_REVISION", "20261017_0057")
    secret_check = Mock(side_effect=AssertionError("no credential read"))
    database_factory = Mock(side_effect=AssertionError("no database connection"))
    monkeypatch.setattr(operator, "check_postgres_environment", secret_check)
    monkeypatch.setattr(database, "build_engine", database_factory)
    with pytest.raises(operator.OperatorRuntimeError, match="REVISION_UNSUPPORTED"):
        operator.run_callback(path.parent, context, operator.Callback.MIGRATION_UPGRADE_0058)
    secret_check.assert_not_called()
    database_factory.assert_not_called()


def test_changed_schema_is_rejected_before_context_admission(
    registered_review_stage: tuple[Path, operator.OperatorContext, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, _context, digest = registered_review_stage
    original_read = operator.read_protected

    def changed_schema(path: Path, *, maximum: int, allow_empty: bool = False) -> bytes:
        if path.name == "release_operator_context_v1_7.schema.json":
            return b"{}"
        return original_read(path, maximum=maximum, allow_empty=allow_empty)

    monkeypatch.setattr(operator, "read_protected", changed_schema)
    with pytest.raises(operator.OperatorRuntimeError, match="SCHEMA_CHANGED"):
        operator.load_context(path, digest, "a" * 40)
    assert not (path.parent / "operator-admission.json").exists()


def test_current_selector_only_uses0058_and_historical_wrapper_stays0051() -> None:
    for name in ("release_operator_runtime.sh", "release_operator_boundary.sh"):
        source = (ROOT / "scripts/api" / name).read_text()
        for suffix in ("0052", "0053", "0054", "0055", "0056", "0057", "0058"):
            assert f"MIGRATION_VERIFY_{suffix}|MIGRATION_UPGRADE_{suffix}" in source
    deploy = (ROOT / "scripts/api/deploy_release.sh").read_text()
    assert 'run_release_operator MIGRATION_VERIFY_0058 "${COMMIT}"' in deploy
    assert 'if CURRENT_MIGRATION_REVISION != "20261019_0058":' in deploy
    old = (ROOT / "scripts/api/migrate_release.sh").read_text()
    assert "MIGRATION_UPGRADE_0051" in old and "MIGRATION_UPGRADE_0058" not in old
