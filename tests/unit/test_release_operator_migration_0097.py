"""Explicit 0096→0097 admission; historical formats and callbacks remain frozen."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from scripts.api import release_operator_runtime as operator
from tests.unit.test_release_operator_migration_0084 import kakao_stage as kakao_stage
from tests.unit.test_release_operator_migration_0093 import collection_stage as collection_stage
from tests.unit.test_release_operator_runtime import FakeEngine, _hash, _json
from tests.unit.test_release_operator_runtime import synthetic_stage as synthetic_stage

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def first_observation_stage(collection_stage, monkeypatch):
    from eom_orchestrator import migration

    monkeypatch.setattr(migration, "CURRENT_MIGRATION_REVISION", "20261117_0097")
    path, _, _ = collection_stage
    value = json.loads(path.read_bytes())
    value.update(schema_version="release-operator-context/1.32", migration_revision="20261117_0097")
    path.write_bytes(_json(value))
    digest = _hash(path.read_bytes())
    return path, operator.load_context(path, digest, "a" * 40), digest


def test_context_and_schema_preserve_predecessor_bytes(first_observation_stage):
    path, context, digest = first_observation_stage
    raw = (ROOT / "scripts/api/release_operator_context_v1_32.schema.json").read_bytes()
    assert _hash(raw) == operator._SCHEMA_V1_32_SHA256
    assert (
        raw == (ROOT / "schemas/operations/release-operator-context-v1_32.schema.json").read_bytes()
    )
    assert (
        _hash((ROOT / "scripts/api/release_operator_context_v1_31.schema.json").read_bytes())
        == operator._SCHEMA_V1_31_SHA256
    )
    Draft202012Validator.check_schema(json.loads(raw))
    for name in ("release_operator_runtime.sh", "release_operator_boundary.sh"):
        assert (
            "MIGRATION_VERIFY_0097|MIGRATION_UPGRADE_0097_FROM_0096"
            in (ROOT / "scripts/api" / name).read_text()
        )
    operator.admit(path, context, digest)
    operator.verify_admission(path, context, digest)
    receipt = json.loads((path.parent / "operator-admission.json").read_bytes())
    assert receipt["migration_revision"] == "20261117_0097"
    assert receipt["schema_version"] == "release-operator-admission/1.32"


@pytest.mark.parametrize(
    "callback,head,allowed,count",
    [
        (operator.Callback.MIGRATION_VERIFY_0097, "20261117_0097", True, 0),
        (operator.Callback.MIGRATION_UPGRADE_0097_FROM_0096, "20261117_0096", True, 1),
        (operator.Callback.MIGRATION_UPGRADE_0097_FROM_0096, "20261117_0097", True, 0),
        (operator.Callback.MIGRATION_VERIFY_0097, "20261117_0096", False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0097_FROM_0096, "20261116_0093", False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0097_FROM_0096, "20261117_0095", False, 0),
        (operator.Callback.MIGRATION_VERIFY_0096, "20261117_0097", False, 0),
    ],
)
def test_exact_predecessor_and_completed_replay(
    first_observation_stage, monkeypatch, callback, head, allowed, count
):
    from alembic import command
    from eom_api import build_info
    from eom_orchestrator import database

    path, context, _ = first_observation_stage
    monkeypatch.setattr(build_info, "get_build_info", lambda: context)
    engine, calls = FakeEngine(head), []
    monkeypatch.setattr(database, "build_engine", lambda: engine)

    def upgrade(configuration, target):
        assert target == "20261117_0097"
        calls.append(target)
        engine.revision = target

    monkeypatch.setattr(command, "upgrade", upgrade)
    if allowed:
        operator.run_callback(path.parent, context, callback)
    else:
        with pytest.raises(operator.OperatorRuntimeError):
            operator.run_callback(path.parent, context, callback)
    assert len(calls) == count
