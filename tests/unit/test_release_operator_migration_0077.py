"""Exact chat 0076 to 0077 admission; predecessor bytes remain immutable."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from scripts.api import release_operator_runtime as operator
from tests.unit.test_release_operator_runtime import FakeEngine, _hash, _json
from tests.unit.test_release_operator_runtime import synthetic_stage as synthetic_stage

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def chat_stage(synthetic_stage, monkeypatch):
    from eom_orchestrator import migration

    path, _old, _old_hash = synthetic_stage
    raw = json.loads(path.read_bytes())
    raw.update(schema_version="release-operator-context/1.23", migration_revision="20261110_0077")
    path.write_bytes(_json(raw))
    digest = _hash(path.read_bytes())
    monkeypatch.setattr(migration, "CURRENT_MIGRATION_REVISION", "20261110_0077")
    return path, operator.load_context(path, digest, "a" * 40), digest


def test_schema77_only_changes_version_and_migration_while_preserving76():
    before_raw = (ROOT / "scripts/api/release_operator_context_v1_22.schema.json").read_bytes()
    assert _hash(before_raw) == operator._SCHEMA_V1_22_SHA256
    raw = (ROOT / "scripts/api/release_operator_context_v1_23.schema.json").read_bytes()
    assert _hash(raw) == operator._SCHEMA_V1_23_SHA256
    assert (
        raw == (ROOT / "schemas/operations/release-operator-context-v1_23.schema.json").read_bytes()
    )
    before, after = json.loads(before_raw), json.loads(raw)
    Draft202012Validator.check_schema(after)
    before["$id"] = after["$id"]
    for definition in ("context", "receipt"):
        for field in ("schema_version", "migration_revision"):
            before["$defs"][definition]["properties"][field] = after["$defs"][definition][
                "properties"
            ][field]
    assert before == after


@pytest.mark.parametrize(
    "callback,head,allowed,count",
    (
        (operator.Callback.MIGRATION_VERIFY_0077, "20261110_0077", True, 0),
        (operator.Callback.MIGRATION_UPGRADE_0077, "20261109_0076", True, 1),
        (operator.Callback.MIGRATION_UPGRADE_0077, "20261105_0074", False, 0),
        (operator.Callback.MIGRATION_VERIFY_0077, "20261105_0074", False, 0),
        (operator.Callback.MIGRATION_VERIFY_0074, "20261110_0077", False, 0),
    ),
)
def test_exact76_to77_and_replay_do_not_alias_predecessors(
    chat_stage, monkeypatch, callback, head, allowed, count
):
    from alembic import command
    from eom_api import build_info
    from eom_orchestrator import database

    path, context, _digest = chat_stage
    monkeypatch.setattr(build_info, "get_build_info", lambda: context)
    engine = FakeEngine(head)
    monkeypatch.setattr(database, "build_engine", lambda: engine)
    calls = []

    def upgrade(_configuration, target):
        assert target == "20261110_0077"
        calls.append(target)
        engine.revision = target

    monkeypatch.setattr(command, "upgrade", upgrade)
    if allowed:
        operator.run_callback(path.parent, context, callback)
    else:
        with pytest.raises(operator.OperatorRuntimeError):
            operator.run_callback(path.parent, context, callback)
    assert len(calls) == count


def test_schema77_admission_receipt_and_replay_pin_exact_revision(chat_stage):
    path, context, digest = chat_stage
    operator.admit(path, context, digest)
    operator.verify_admission(path, context, digest)
    receipt = json.loads((path.parent / "operator-admission.json").read_bytes())
    assert receipt["schema_version"] == "release-operator-admission/1.23"
    assert receipt["migration_revision"] == "20261110_0077"
