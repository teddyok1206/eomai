"""Bounded schema68 release admission; root/source/DB ports are synthetic."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from scripts.api import release_operator_runtime as operator
from tests.unit.test_release_operator_runtime import FakeEngine, _hash, _json
from tests.unit.test_release_operator_runtime import synthetic_stage as synthetic_stage

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def public_step_stage(synthetic_stage, monkeypatch):
    from eom_orchestrator import migration

    path, _old, _old_hash = synthetic_stage
    raw = json.loads(path.read_bytes())
    raw.update(schema_version="release-operator-context/1.15", migration_revision="20261102_0068")
    path.write_bytes(_json(raw))
    digest = _hash(path.read_bytes())
    monkeypatch.setattr(migration, "CURRENT_MIGRATION_REVISION", "20261102_0068")
    return path, operator.load_context(path, digest, "a" * 40), digest


def test_schema68_is_exact_successor_and_mirror_preserves_released66_bytes():
    previous_raw = (ROOT / "scripts/api/release_operator_context_v1_14.schema.json").read_bytes()
    assert _hash(previous_raw) == operator._SCHEMA_V1_14_SHA256
    raw = (ROOT / "scripts/api/release_operator_context_v1_15.schema.json").read_bytes()
    assert (
        raw == (ROOT / "schemas/operations/release-operator-context-v1_15.schema.json").read_bytes()
    )
    assert _hash(raw) == operator._SCHEMA_V1_15_SHA256
    before, after = json.loads(previous_raw), json.loads(raw)
    Draft202012Validator.check_schema(after)
    before["$id"] = after["$id"]
    for section in ("context", "receipt"):
        for key in ("schema_version", "migration_revision"):
            before["$defs"][section]["properties"][key] = after["$defs"][section]["properties"][key]
    assert before == after


@pytest.mark.parametrize(
    "callback,head,allowed,count",
    (
        (operator.Callback.MIGRATION_VERIFY_0068, "20261102_0068", True, 0),
        (operator.Callback.MIGRATION_VERIFY_0068, "20261031_0066", False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0068_FROM_0066, "20261031_0066", True, 1),
        (operator.Callback.MIGRATION_UPGRADE_0068_FROM_0066, "20261102_0068", True, 0),
        (operator.Callback.MIGRATION_UPGRADE_0068_FROM_0066, "20261101_0067", False, 0),
        (operator.Callback.MIGRATION_VERIFY_0066, "20261102_0068", False, 0),
    ),
)
def test_exact66_to68_and_replay_do_not_alias_old_callbacks(
    public_step_stage, monkeypatch, callback, head, allowed, count
):
    from alembic import command
    from eom_api import build_info
    from eom_orchestrator import database

    path, context, _digest = public_step_stage
    monkeypatch.setattr(build_info, "get_build_info", lambda: context)
    engine = FakeEngine(head)
    monkeypatch.setattr(database, "build_engine", lambda: engine)
    calls = []

    def upgrade(_configuration, target):
        assert target == "20261102_0068"
        calls.append(target)
        engine.revision = target

    monkeypatch.setattr(command, "upgrade", upgrade)
    if allowed:
        operator.run_callback(path.parent, context, callback)
    else:
        with pytest.raises(operator.OperatorRuntimeError):
            operator.run_callback(path.parent, context, callback)
    assert len(calls) == count


def test_context68_receipt_replay_keeps_exact_revision(public_step_stage):
    path, context, digest = public_step_stage
    operator.admit(path, context, digest)
    operator.verify_admission(path, context, digest)
    receipt = json.loads((path.parent / "operator-admission.json").read_bytes())
    assert receipt["schema_version"] == "release-operator-admission/1.15"
    assert receipt["migration_revision"] == "20261102_0068"
