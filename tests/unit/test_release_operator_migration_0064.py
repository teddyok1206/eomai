"""Three-report capacity requires a separately pinned 0064 operator context."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from scripts.api import release_operator_runtime as operator
from tests.unit.test_release_operator_runtime import FakeEngine, _hash, _json
from tests.unit.test_release_operator_runtime import synthetic_stage as synthetic_stage

ROOT = Path(__file__).resolve().parents[2]


def test_root_launcher_and_developer_boundary_route_the_same_closed_callback_set():
    for filename, extra in (
        ("release_operator_runtime.sh", {"ADMIT"}),
        ("release_operator_boundary.sh", set()),
    ):
        source = (ROOT / "scripts/api" / filename).read_text()
        match = re.search(r"\n\s+((?:[A-Z][A-Z0-9_]*\|)+[A-Z][A-Z0-9_]*)\) ;;", source)
        assert match is not None
        assert (
            set(match.group(1).split("|")) == {member.value for member in operator.Callback} | extra
        )


@pytest.fixture
def creative_capacity_stage(
    synthetic_stage: tuple[Path, operator.OperatorContext, str],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, operator.OperatorContext, str]:
    from eom_orchestrator import migration

    path, _, _ = synthetic_stage
    value = json.loads(path.read_bytes())
    value.update(schema_version="release-operator-context/1.13", migration_revision="20261030_0064")
    path.write_bytes(_json(value))
    digest = _hash(path.read_bytes())
    monkeypatch.setattr(migration, "CURRENT_MIGRATION_REVISION", "20261030_0064")
    return path, operator.load_context(path, digest, "a" * 40), digest


def test_schema_successor_is_exact_and_old_bytes_are_preserved() -> None:
    previous = json.loads(
        (ROOT / "scripts/api/release_operator_context_v1_12.schema.json").read_bytes()
    )
    raw = (ROOT / "scripts/api/release_operator_context_v1_13.schema.json").read_bytes()
    assert _hash(raw) == operator._SCHEMA_V1_13_SHA256
    canonical = ROOT / "schemas/operations/release-operator-context-v1_13.schema.json"
    assert raw == canonical.read_bytes()
    schema = json.loads(raw)
    Draft202012Validator.check_schema(schema)
    previous["$id"] = schema["$id"]
    for section in ("context", "receipt"):
        for key in ("schema_version", "migration_revision"):
            previous["$defs"][section]["properties"][key] = schema["$defs"][section]["properties"][
                key
            ]
    assert previous == schema


@pytest.mark.parametrize(
    "callback,revision,success,upgrade_count",
    [
        (operator.Callback.MIGRATION_VERIFY_0064, "20261030_0064", True, 0),
        (operator.Callback.MIGRATION_VERIFY_0064, "20261029_0063", False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0064, "20261029_0063", True, 1),
        (operator.Callback.MIGRATION_UPGRADE_0064, "20261030_0064", True, 0),
        (operator.Callback.MIGRATION_UPGRADE_0064, "20261027_0062", False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0063, "20261029_0063", False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0064_FROM_0062, "20261027_0062", True, 1),
        (operator.Callback.MIGRATION_UPGRADE_0064_FROM_0062, "20261030_0064", True, 0),
        (operator.Callback.MIGRATION_UPGRADE_0064_FROM_0062, "20261029_0063", False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0064_FROM_0062, "20261027_0061", False, 0),
    ],
)
def test_only_exact_predecessor_upgrades_without_repointing_old_callback(
    creative_capacity_stage: tuple[Path, operator.OperatorContext, str],
    monkeypatch: pytest.MonkeyPatch,
    callback: operator.Callback,
    revision: str,
    success: bool,
    upgrade_count: int,
) -> None:
    from alembic import command
    from eom_api import build_info
    from eom_orchestrator import database

    path, context, _ = creative_capacity_stage
    monkeypatch.setattr(build_info, "get_build_info", lambda: context)
    engine = FakeEngine(revision)
    monkeypatch.setattr(database, "build_engine", lambda: engine)
    calls: list[str] = []

    def upgrade(_config: Any, target: str) -> None:
        assert target == "20261030_0064"
        calls.append(target)
        engine.revision = target

    monkeypatch.setattr(command, "upgrade", upgrade)
    if success:
        operator.run_callback(path.parent, context, callback)
    else:
        with pytest.raises(operator.OperatorRuntimeError):
            operator.run_callback(path.parent, context, callback)
    assert len(calls) == upgrade_count


def test_admission_receipt_does_not_reuse_v112(
    creative_capacity_stage: tuple[Path, operator.OperatorContext, str],
) -> None:
    path, context, digest = creative_capacity_stage
    operator.admit(path, context, digest)
    operator.verify_admission(path, context, digest)
    receipt_path = path.parent / "operator-admission.json"
    value = json.loads(receipt_path.read_bytes())
    assert value["schema_version"] == "release-operator-admission/1.13"
    value["schema_version"] = "release-operator-admission/1.12"
    value["migration_revision"] = "20261029_0063"
    receipt_path.write_bytes(_json(value))
    with pytest.raises(operator.OperatorRuntimeError, match="ADMISSION_CHANGED"):
        operator.verify_admission(path, context, digest)
