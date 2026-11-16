"""Kakao successor admits exact 0079→0083 and four wheels, never widens old contexts."""

import json
import zipfile
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from scripts.api import release_operator_runtime as operator
from tests.unit.test_release_operator_runtime import FakeEngine, _hash, _json
from tests.unit.test_release_operator_runtime import synthetic_stage as synthetic_stage

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def kakao_stage(synthetic_stage, monkeypatch):
    from eom_orchestrator import migration

    monkeypatch.setattr(migration, "CURRENT_MIGRATION_REVISION", "20261116_0083")
    path, _, _ = synthetic_stage
    raw = json.loads(path.read_bytes())
    raw.update(schema_version="release-operator-context/1.25", migration_revision="20261116_0083")
    name = "eom_kakao_archive_contracts-0.1.0-py3-none-any.whl"
    wheel = path.parent / "dist" / name
    members = {
        "eom_kakao_archive_contracts/__init__.py": b"# synthetic pure contracts\n",
        "eom_kakao_archive_contracts-0.1.0.dist-info/RECORD": b"synthetic\n",
    }
    with zipfile.ZipFile(wheel, "w") as archive:
        for member, value in members.items():
            archive.writestr(member, value)
            target = path.parent / "site-packages" / member
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(value)
    raw["wheels"]["kakao_contracts"] = {"name": name, "sha256": _hash(wheel.read_bytes())}
    path.write_bytes(_json(raw))
    digest = _hash(path.read_bytes())
    return path, operator.load_context(path, digest, "a" * 40), digest


def test_successor_pins_mirror_and_requires_fourth_wheel(kakao_stage):
    path, context, _ = kakao_stage
    raw = (ROOT / "scripts/api/release_operator_context_v1_25.schema.json").read_bytes()
    assert _hash(raw) == operator._SCHEMA_V1_25_SHA256
    assert (
        raw == (ROOT / "schemas/operations/release-operator-context-v1_25.schema.json").read_bytes()
    )
    schema = json.loads(raw)
    Draft202012Validator.check_schema(schema)
    assert len(context.wheels) == 4
    value = json.loads(path.read_bytes())
    Draft202012Validator(schema).validate(value)
    del value["wheels"]["kakao_contracts"]
    assert not Draft202012Validator(schema).is_valid(value)
    before = (ROOT / "scripts/api/release_operator_context_v1_24.schema.json").read_bytes()
    assert _hash(before) == operator._SCHEMA_V1_24_SHA256
    value = json.loads(path.read_bytes())
    value.update(schema_version="release-operator-context/1.24", migration_revision="20261112_0079")
    assert not Draft202012Validator(json.loads(before)).is_valid(value)


@pytest.mark.parametrize(
    "callback,head,allowed,count",
    [
        (operator.Callback.MIGRATION_VERIFY_0083, "20261116_0083", True, 0),
        (operator.Callback.MIGRATION_UPGRADE_0083_FROM_0079, "20261112_0079", True, 1),
        (operator.Callback.MIGRATION_UPGRADE_0083_FROM_0079, "20261116_0083", True, 0),
        (operator.Callback.MIGRATION_UPGRADE_0083_FROM_0079, "20261112_0078", False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0083_FROM_0079, "20261116_0082", False, 0),
        (operator.Callback.MIGRATION_VERIFY_0083, "20261112_0079", False, 0),
        (operator.Callback.MIGRATION_VERIFY_0079, "20261116_0083", False, 0),
    ],
)
def test_exact_predecessor_target_and_noop_replay(
    kakao_stage, monkeypatch, callback, head, allowed, count
):
    from alembic import command
    from eom_api import build_info
    from eom_orchestrator import database

    path, context, _ = kakao_stage
    monkeypatch.setattr(build_info, "get_build_info", lambda: context)
    engine, calls = FakeEngine(head), []
    monkeypatch.setattr(database, "build_engine", lambda: engine)

    def upgrade(configuration, target):
        assert target == "20261116_0083"
        calls.append(target)
        engine.revision = target

    monkeypatch.setattr(command, "upgrade", upgrade)
    if allowed:
        operator.run_callback(path.parent, context, callback)
    else:
        with pytest.raises(operator.OperatorRuntimeError):
            operator.run_callback(path.parent, context, callback)
    assert len(calls) == count


def test_admission_verifies_fourth_wheel_and_keeps_exact_receipt(kakao_stage):
    path, context, digest = kakao_stage
    operator.admit(path, context, digest)
    operator.verify_admission(path, context, digest)
    receipt = json.loads((path.parent / "operator-admission.json").read_bytes())
    assert receipt["schema_version"] == "release-operator-admission/1.25"
    assert receipt["migration_revision"] == "20261116_0083"
    (path.parent / "site-packages/eom_kakao_archive_contracts/__init__.py").write_bytes(b"drift")
    with pytest.raises(operator.OperatorRuntimeError, match="INSTALLED_PAYLOAD_CHANGED"):
        operator.verify_admission(path, context, digest)


def test_fourth_wheel_cannot_be_a_different_distribution(kakao_stage):
    path, _, _ = kakao_stage
    value = json.loads(path.read_bytes())
    value["wheels"]["kakao_contracts"]["name"] = value["wheels"]["platform"]["name"]
    path.write_bytes(_json(value))
    with pytest.raises(operator.OperatorRuntimeError, match="WHEEL_INVALID"):
        operator.load_context(path, _hash(path.read_bytes()), "a" * 40)
