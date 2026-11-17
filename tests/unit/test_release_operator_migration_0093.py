"""Exact 0087→0093 release admission; old contexts and intermediate states stay closed."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from scripts.api import release_operator_runtime as operator
from tests.unit.test_release_operator_migration_0084 import kakao_stage as kakao_stage
from tests.unit.test_release_operator_runtime import FakeEngine, _hash, _json
from tests.unit.test_release_operator_runtime import synthetic_stage as synthetic_stage

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def collection_stage(kakao_stage, monkeypatch):
    from eom_orchestrator import migration

    monkeypatch.setattr(migration, "CURRENT_MIGRATION_REVISION", "20261116_0093")
    path, _, _ = kakao_stage
    value = json.loads(path.read_bytes())
    value.update(schema_version="release-operator-context/1.28", migration_revision="20261116_0093")
    path.write_bytes(_json(value))
    digest = _hash(path.read_bytes())
    return path, operator.load_context(path, digest, "a" * 40), digest


def test_successor_schema_mirror_admission_and_predecessor_bytes(collection_stage):
    path, context, digest = collection_stage
    raw = (ROOT / "scripts/api/release_operator_context_v1_28.schema.json").read_bytes()
    assert _hash(raw) == operator._SCHEMA_V1_28_SHA256
    assert (
        raw == (ROOT / "schemas/operations/release-operator-context-v1_28.schema.json").read_bytes()
    )
    Draft202012Validator.check_schema(json.loads(raw))
    assert (
        _hash((ROOT / "scripts/api/release_operator_context_v1_27.schema.json").read_bytes())
        == operator._SCHEMA_V1_27_SHA256
    )
    for shell in ("release_operator_runtime.sh", "release_operator_boundary.sh"):
        source = (ROOT / "scripts/api" / shell).read_text()
        assert "MIGRATION_VERIFY_0093" in source
        assert "MIGRATION_UPGRADE_0093_FROM_0087" in source
    deploy = (ROOT / "scripts/api/deploy_release.sh").read_text()
    assert 'run_release_operator MIGRATION_VERIFY_0093 "${COMMIT}"' in deploy
    assert len(context.wheels) == 4
    operator.admit(path, context, digest)
    operator.verify_admission(path, context, digest)
    receipt = json.loads((path.parent / "operator-admission.json").read_bytes())
    assert receipt["schema_version"] == "release-operator-admission/1.28"
    assert receipt["migration_revision"] == "20261116_0093"


@pytest.mark.parametrize(
    "callback,head,allowed,count",
    [
        (operator.Callback.MIGRATION_VERIFY_0093, "20261116_0093", True, 0),
        (operator.Callback.MIGRATION_UPGRADE_0093_FROM_0087, "20261116_0087", True, 1),
        (operator.Callback.MIGRATION_UPGRADE_0093_FROM_0087, "20261116_0093", True, 0),
        (operator.Callback.MIGRATION_UPGRADE_0093_FROM_0087, "20261116_0084", False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0093_FROM_0087, "20261116_0088", False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0093_FROM_0087, "20261116_0089", False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0093_FROM_0087, "20261116_0090", False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0093_FROM_0087, "20261116_0091", False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0093_FROM_0087, "20261116_0092", False, 0),
        (operator.Callback.MIGRATION_VERIFY_0093, "20261116_0087", False, 0),
        (operator.Callback.MIGRATION_VERIFY_0087, "20261116_0093", False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0087_FROM_0084, "20261116_0084", False, 0),
    ],
)
def test_exact_predecessor_noop_replay_and_unknown_state_rejection(
    collection_stage, monkeypatch, callback, head, allowed, count
):
    from alembic import command
    from eom_api import build_info
    from eom_orchestrator import database

    path, context, _ = collection_stage
    monkeypatch.setattr(build_info, "get_build_info", lambda: context)
    engine, calls = FakeEngine(head), []
    monkeypatch.setattr(database, "build_engine", lambda: engine)

    def upgrade(configuration, target):
        assert target == "20261116_0093"
        calls.append(target)
        engine.revision = target

    monkeypatch.setattr(command, "upgrade", upgrade)
    if allowed:
        operator.run_callback(path.parent, context, callback)
    else:
        with pytest.raises(operator.OperatorRuntimeError):
            operator.run_callback(path.parent, context, callback)
    assert len(calls) == count
