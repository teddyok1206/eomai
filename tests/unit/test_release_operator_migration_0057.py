"""Additive0057 release context with synthetic root/runtime/database seams only."""

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
def private_step_stage(
    synthetic_stage: tuple[Path, operator.OperatorContext, str],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, operator.OperatorContext, str]:
    from eom_orchestrator import migration

    path, _, _ = synthetic_stage
    value = json.loads(path.read_bytes())
    value.update(schema_version="release-operator-context/1.6", migration_revision="20261017_0057")
    path.write_bytes(_json(value))
    digest = _hash(path.read_bytes())
    monkeypatch.setattr(migration, "CURRENT_MIGRATION_REVISION", "20261017_0057")
    return path, operator.load_context(path, digest, "a" * 40), digest


def test_schema_successor_changes_only_literal_version_and_target() -> None:
    previous = json.loads(
        (ROOT / "scripts/api/release_operator_context_v1_5.schema.json").read_bytes()
    )
    raw = (ROOT / "scripts/api/release_operator_context_v1_6.schema.json").read_bytes()
    assert _hash(raw) == operator._SCHEMA_V1_6_SHA256
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
        "schema_version": "release-operator-context/1.6",
        "migration_revision": "20261017_0057",
    }
    validator = Draft202012Validator(schema)
    validator.validate(value)
    for change in (
        {"migration_revision": "head"},
        {"migration_revision": "20261017_0056"},
        {"migration_revision": True},
        {"command": "arbitrary"},
        {"role": "ADMIN"},
        {"schema_version": "release-operator-context/1.5"},
    ):
        assert not validator.is_valid(value | change)


@pytest.mark.parametrize(
    "callback,revision,owner,success,upgrades",
    [
        (operator.Callback.MIGRATION_VERIFY_0057, "20261017_0057", True, True, 0),
        (operator.Callback.MIGRATION_VERIFY_0057, "20261017_0056", True, False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0057, "20261017_0056", True, True, 1),
        (operator.Callback.MIGRATION_UPGRADE_0057, "20261017_0057", True, True, 0),
        (operator.Callback.MIGRATION_UPGRADE_0057, "20261014_0055", True, False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0057, "unknown", True, False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0057, "20261017_0056", False, False, 0),
    ],
)
def test_exact_predecessor_target_owner_and_replay(
    private_step_stage: tuple[Path, operator.OperatorContext, str],
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

    path, context, _digest = private_step_stage
    monkeypatch.setattr(build_info, "get_build_info", lambda: context)
    engine = FakeEngine(revision, owner=owner)
    monkeypatch.setattr(database, "build_engine", lambda: engine)
    calls: list[str] = []

    def upgrade(_config: Any, target: str) -> None:
        assert target == "20261017_0057"
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
    ],
)
def test_old_callbacks_are_not_repointed_to_new_head(
    private_step_stage: tuple[Path, operator.OperatorContext, str],
    monkeypatch: pytest.MonkeyPatch,
    callback: operator.Callback,
) -> None:
    from eom_api import build_info
    from eom_orchestrator import database

    path, context, _digest = private_step_stage
    monkeypatch.setattr(build_info, "get_build_info", lambda: context)
    database_factory = Mock()
    monkeypatch.setattr(database, "build_engine", database_factory)
    with pytest.raises(operator.OperatorRuntimeError, match="REVISION_UNSUPPORTED"):
        operator.run_callback(path.parent, context, callback)
    database_factory.assert_not_called()


def test_receipt_pin_is_versioned_and_old_context_is_not_reused(
    private_step_stage: tuple[Path, operator.OperatorContext, str],
) -> None:
    path, context, digest = private_step_stage
    operator.admit(path, context, digest)
    operator.verify_admission(path, context, digest)
    receipt_path = path.parent / "operator-admission.json"
    value = json.loads(receipt_path.read_bytes())
    assert value["schema_version"] == "release-operator-admission/1.6"
    value.update(
        schema_version="release-operator-admission/1.5", migration_revision="20261017_0056"
    )
    receipt_path.write_bytes(_json(value))
    with pytest.raises(operator.OperatorRuntimeError, match="ADMISSION_CHANGED"):
        operator.verify_admission(path, context, digest)


def test_current_selector_only_uses0057_and_historical_wrapper_stays0051() -> None:
    for name in ("release_operator_runtime.sh", "release_operator_boundary.sh"):
        source = (ROOT / "scripts/api" / name).read_text()
        for suffix in ("0052", "0053", "0054", "0055", "0056", "0057"):
            assert f"MIGRATION_VERIFY_{suffix}|MIGRATION_UPGRADE_{suffix}" in source
    deploy = (ROOT / "scripts/api/deploy_release.sh").read_text()
    assert 'run_release_operator MIGRATION_VERIFY_0060 "${COMMIT}"' in deploy
    assert 'if CURRENT_MIGRATION_REVISION != "20261027_0060":' in deploy
    old = (ROOT / "scripts/api/migrate_release.sh").read_text()
    assert "MIGRATION_UPGRADE_0051" in old and "MIGRATION_UPGRADE_0057" not in old
