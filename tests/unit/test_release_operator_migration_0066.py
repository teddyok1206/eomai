"""Pinned0066 release boundary; synthetic files/DB do not prove privileged execution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from jsonschema import Draft202012Validator

from scripts.api import release_operator_runtime as operator
from tests.unit.test_release_operator_runtime import FakeEngine, _hash, _json
from tests.unit.test_release_operator_runtime import synthetic_stage as synthetic_stage

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def registered_index_stage(synthetic_stage, monkeypatch):
    from eom_orchestrator import migration

    path, _old, _old_digest = synthetic_stage
    value = json.loads(path.read_bytes())
    value.update(schema_version="release-operator-context/1.14", migration_revision="20261031_0066")
    path.write_bytes(_json(value))
    digest = _hash(path.read_bytes())
    monkeypatch.setattr(migration, "CURRENT_MIGRATION_REVISION", "20261031_0066")
    return path, operator.load_context(path, digest, "a" * 40), digest


def test_schema_mirror_exact_target_and_previous_bytes():
    previous_path = ROOT / "scripts/api/release_operator_context_v1_13.schema.json"
    previous = json.loads(previous_path.read_bytes())
    assert _hash(previous_path.read_bytes()) == operator._SCHEMA_V1_13_SHA256
    raw = (ROOT / "scripts/api/release_operator_context_v1_14.schema.json").read_bytes()
    assert (
        raw == (ROOT / "schemas/operations/release-operator-context-v1_14.schema.json").read_bytes()
    )
    assert _hash(raw) == operator._SCHEMA_V1_14_SHA256
    schema = json.loads(raw)
    Draft202012Validator.check_schema(schema)
    previous["$id"] = schema["$id"]
    for section in ("context", "receipt"):
        for field in ("schema_version", "migration_revision"):
            previous["$defs"][section]["properties"][field] = schema["$defs"][section][
                "properties"
            ][field]
    assert previous == schema


@pytest.mark.parametrize(
    "callback,revision,success,upgrades",
    [
        (operator.Callback.MIGRATION_VERIFY_0066, "20261031_0066", True, 0),
        (operator.Callback.MIGRATION_VERIFY_0066, "20261031_0065", False, 0),
        (operator.Callback.MIGRATION_VERIFY_0066, "20261030_0064", False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0066, "20261031_0065", True, 1),
        (operator.Callback.MIGRATION_UPGRADE_0066, "20261031_0066", True, 0),
        (operator.Callback.MIGRATION_UPGRADE_0066, "20261030_0064", False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0066_FROM_0064, "20261030_0064", True, 1),
        (operator.Callback.MIGRATION_UPGRADE_0066_FROM_0064, "20261031_0066", True, 0),
        (operator.Callback.MIGRATION_UPGRADE_0066_FROM_0064, "20261031_0065", False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0066_FROM_0064, "20261029_0063", False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0064, "20261030_0064", False, 0),
    ],
)
def test_exact_predecessor_and_replay_never_alias_old_callbacks(
    registered_index_stage, monkeypatch, callback, revision, success, upgrades
):
    from alembic import command
    from eom_api import build_info
    from eom_orchestrator import database

    path, context, _digest = registered_index_stage
    monkeypatch.setattr(build_info, "get_build_info", lambda: context)
    engine = FakeEngine(revision)
    monkeypatch.setattr(database, "build_engine", lambda: engine)
    calls = []

    def upgrade(_configuration: Any, target: str):
        assert target == "20261031_0066"
        calls.append(target)
        engine.revision = target

    monkeypatch.setattr(command, "upgrade", upgrade)
    if success:
        operator.run_callback(path.parent, context, callback)
    else:
        with pytest.raises(operator.OperatorRuntimeError):
            operator.run_callback(path.parent, context, callback)
    assert len(calls) == upgrades


def test_cross_version_receipt_does_not_admit_new_migration(registered_index_stage):
    path, context, digest = registered_index_stage
    operator.admit(path, context, digest)
    operator.verify_admission(path, context, digest)
    receipt_path = path.parent / "operator-admission.json"
    value = json.loads(receipt_path.read_bytes())
    assert value["schema_version"] == "release-operator-admission/1.14"
    value.update(
        schema_version="release-operator-admission/1.13", migration_revision="20261030_0064"
    )
    receipt_path.write_bytes(_json(value))
    with pytest.raises(operator.OperatorRuntimeError, match="ADMISSION_CHANGED"):
        operator.verify_admission(path, context, digest)


@pytest.mark.parametrize(
    "field,value",
    [
        ("migration_revision", "head"),
        ("migration_revision", "20261031_0065"),
        ("command", "SELECT 1"),
        ("database_url", "not-authority"),
        ("secret_path", "/tmp/not-authority"),
    ],
)
def test_new_context_stays_closed(registered_index_stage, field, value):
    path, _context, _digest = registered_index_stage
    document = json.loads(path.read_bytes())
    document[field] = value
    path.write_bytes(_json(document))
    with pytest.raises(operator.OperatorRuntimeError):
        operator.load_context(path, _hash(path.read_bytes()), "a" * 40)


def test_wrong_source_head_is_rejected_before_database_construction(
    registered_index_stage, monkeypatch
):
    from eom_api import build_info
    from eom_orchestrator import database, migration

    path, context, _digest = registered_index_stage
    monkeypatch.setattr(build_info, "get_build_info", lambda: context)
    monkeypatch.setattr(migration, "CURRENT_MIGRATION_REVISION", "20261030_0064")
    engine = Mock(side_effect=AssertionError("must reject before database"))
    monkeypatch.setattr(database, "build_engine", engine)
    with pytest.raises(operator.OperatorRuntimeError, match="REVISION_UNSUPPORTED"):
        operator.run_callback(path.parent, context, operator.Callback.MIGRATION_VERIFY_0066)
    engine.assert_not_called()
