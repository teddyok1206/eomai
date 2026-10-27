"""Exact successor migration context; all root, runtime and DB ports are synthetic."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from jsonschema import Draft202012Validator

from scripts.api import release_operator_runtime as operator
from tests.unit.test_release_operator_runtime import FakeEngine, _context_value, _hash, _json
from tests.unit.test_release_operator_runtime import synthetic_stage as synthetic_stage

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def native_stage(
    synthetic_stage: tuple[Path, operator.OperatorContext, str],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, operator.OperatorContext, str]:
    from eom_orchestrator import migration

    path, _, _ = synthetic_stage
    value = json.loads(path.read_bytes())
    value.update(schema_version="release-operator-context/1.2", migration_revision="20261012_0053")
    path.write_bytes(_json(value))
    digest = _hash(path.read_bytes())
    monkeypatch.setattr(migration, "CURRENT_MIGRATION_REVISION", "20261012_0053")
    return path, operator.load_context(path, digest, "a" * 40), digest


def test_new_schema_is_additive_and_has_same_closed_nonversioned_fields() -> None:
    historical = ROOT / "scripts/api/release_operator_context.schema.json"
    previous = ROOT / "scripts/api/release_operator_context_v1_1.schema.json"
    current = ROOT / "scripts/api/release_operator_context_v1_2.schema.json"
    assert _hash(historical.read_bytes()) == operator._SCHEMA_SHA256
    assert _hash(previous.read_bytes()) == operator._SCHEMA_V1_1_SHA256
    assert _hash(current.read_bytes()) == operator._SCHEMA_V1_2_SHA256
    schema = json.loads(current.read_bytes())
    Draft202012Validator.check_schema(schema)
    comparison = json.loads(current.read_bytes())
    comparison["$id"] = "eom://operations/release-operator-context/1.1"
    for definition, version in (("context", "context"), ("receipt", "admission")):
        properties = comparison["$defs"][definition]["properties"]
        properties["schema_version"]["const"] = f"release-operator-{version}/1.1"
        properties["migration_revision"]["const"] = "20261012_0052"
    assert comparison == json.loads(previous.read_bytes())
    value = _context_value() | {
        "schema_version": "release-operator-context/1.2",
        "migration_revision": "20261012_0053",
    }
    Draft202012Validator(schema).validate(value)
    for old in (historical, previous):
        assert not Draft202012Validator(json.loads(old.read_bytes())).is_valid(value)


@pytest.mark.parametrize(
    "changes",
    [
        {"migration_revision": "head"},
        {"migration_revision": "20261012_0052"},
        {"migration_revision": "20261010_0051"},
        {"migration_revision": True},
        {"schema_version": "release-operator-context/1.1"},
        {"schema_version": "release-operator-context/2.0"},
        {"command": "alembic upgrade head"},
        {"requester_role": "ADMIN"},
        {"callbacks": ["MIGRATION_UPGRADE_0053"]},
    ],
)
def test_new_schema_has_no_target_command_or_authority_override(changes: dict[str, Any]) -> None:
    schema = json.loads(
        (ROOT / "scripts/api/release_operator_context_v1_2.schema.json").read_bytes()
    )
    value = _context_value() | {
        "schema_version": "release-operator-context/1.2",
        "migration_revision": "20261012_0053",
    }
    assert not Draft202012Validator(schema).is_valid(value | changes)


@pytest.mark.parametrize("old_version,old_revision", [("1.0", None), ("1.1", "20261012_0052")])
def test_old_admission_cannot_be_reinterpreted_as_native_release(
    native_stage: tuple[Path, operator.OperatorContext, str],
    old_version: str,
    old_revision: str | None,
) -> None:
    path, context, digest = native_stage
    operator.admit(path, context, digest)
    target = path.parent / "operator-admission.json"
    receipt = json.loads(target.read_bytes())
    assert receipt["schema_version"] == "release-operator-admission/1.2"
    assert receipt["migration_revision"] == "20261012_0053"
    operator.verify_admission(path, context, digest)
    receipt["schema_version"] = f"release-operator-admission/{old_version}"
    if old_revision is None:
        receipt.pop("migration_revision")
    else:
        receipt["migration_revision"] = old_revision
    target.write_bytes(_json(receipt))
    with pytest.raises(operator.OperatorRuntimeError, match="ADMISSION_CHANGED"):
        operator.verify_admission(path, context, digest)


def test_wrong_commit_raw_hash_or_schema_is_denied_before_admission(
    native_stage: tuple[Path, operator.OperatorContext, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    path, _, digest = native_stage
    with pytest.raises(operator.OperatorRuntimeError, match="SOURCE_MISMATCH"):
        operator.load_context(path, digest, "b" * 40)
    with pytest.raises(operator.OperatorRuntimeError, match="CONTEXT_CHANGED"):
        operator.load_context(path, "sha256:" + "0" * 64, "a" * 40)
    original = operator.read_protected

    def changed(target: Path, *, maximum: int, allow_empty: bool = False) -> bytes:
        if target.name == "release_operator_context_v1_2.schema.json":
            return b"{}"
        return original(target, maximum=maximum, allow_empty=allow_empty)

    monkeypatch.setattr(operator, "read_protected", changed)
    with pytest.raises(operator.OperatorRuntimeError, match="SCHEMA_CHANGED"):
        operator.load_context(path, digest, "a" * 40)


@pytest.mark.parametrize(
    "callback,revision,owner,succeeds,upgrades",
    [
        (operator.Callback.MIGRATION_VERIFY_0053, "20261012_0053", True, True, 0),
        (operator.Callback.MIGRATION_VERIFY_0053, "20261012_0052", True, False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0053, "20261012_0052", True, True, 1),
        (operator.Callback.MIGRATION_UPGRADE_0053, "20261012_0053", True, True, 0),
        (operator.Callback.MIGRATION_UPGRADE_0053, "20261010_0051", True, False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0053, "20261009_0050", True, False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0053, "unknown", True, False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0053, "20261012_0052", False, False, 0),
    ],
)
def test_exact_target_predecessor_owner_and_replay(
    native_stage: tuple[Path, operator.OperatorContext, str],
    monkeypatch: pytest.MonkeyPatch,
    callback: operator.Callback,
    revision: str,
    owner: bool,
    succeeds: bool,
    upgrades: int,
) -> None:
    from alembic import command
    from alembic.config import Config
    from eom_api import build_info
    from eom_orchestrator import database

    path, context, _ = native_stage
    monkeypatch.setattr(
        build_info,
        "get_build_info",
        lambda: SimpleNamespace(
            **{
                key: getattr(context, key)
                for key in ("source_commit", "source_tree", "source_archive_sha256")
            }
        ),
    )
    engine = FakeEngine(revision, owner=owner)
    monkeypatch.setattr(database, "build_engine", lambda: engine)
    configurations: list[Config] = []

    def upgrade(configuration: Config, target: str) -> None:
        assert target == "20261012_0053"
        configurations.append(configuration)
        engine.revision = target

    monkeypatch.setattr(command, "upgrade", upgrade)
    if succeeds:
        operator.run_callback(path.parent, context, callback)
    else:
        with pytest.raises(operator.OperatorRuntimeError):
            operator.run_callback(path.parent, context, callback)
    assert len(configurations) == upgrades and engine.disposed
    for configuration in configurations:
        assert configuration.get_main_option("script_location") == str(
            path.parent / "source/migrations"
        )
        assert configuration.get_main_option("prepend_sys_path") == ""


@pytest.mark.parametrize(
    "callback",
    [
        operator.Callback.MIGRATION_VERIFY,
        operator.Callback.MIGRATION_UPGRADE_0051,
        operator.Callback.MIGRATION_VERIFY_0052,
        operator.Callback.MIGRATION_UPGRADE_0052,
    ],
)
def test_native_context_never_routes_old_callback_to_new_target(
    native_stage: tuple[Path, operator.OperatorContext, str],
    monkeypatch: pytest.MonkeyPatch,
    callback: operator.Callback,
) -> None:
    from eom_api import build_info
    from eom_orchestrator import database

    path, context, _ = native_stage
    monkeypatch.setattr(build_info, "get_build_info", lambda: context)
    engine = Mock()
    monkeypatch.setattr(database, "build_engine", engine)
    with pytest.raises(operator.OperatorRuntimeError, match="REVISION_UNSUPPORTED"):
        operator.run_callback(path.parent, context, callback)
    engine.assert_not_called()


def test_current_shell_and_deployment_use_only_the_exact_successor() -> None:
    for name in ("release_operator_runtime.sh", "release_operator_boundary.sh"):
        source = (ROOT / "scripts/api" / name).read_text()
        assert "MIGRATION_VERIFY_0052|MIGRATION_UPGRADE_0052" in source
        assert "MIGRATION_VERIFY_0053|MIGRATION_UPGRADE_0053" in source
    deployment = (ROOT / "scripts/api/deploy_release.sh").read_text()
    assert 'run_release_operator MIGRATION_VERIFY_0060 "${COMMIT}"' in deployment
    assert 'if CURRENT_MIGRATION_REVISION != "20261027_0060":' in deployment
    assert 'run_release_operator MIGRATION_VERIFY_0052 "${COMMIT}"' not in deployment
    historical = (ROOT / "scripts/api/migrate_release.sh").read_text()
    assert "MIGRATION_UPGRADE_0051" in historical and "MIGRATION_VERIFY_0053" not in historical


@pytest.mark.parametrize("changed", ["head", "context", "commit", "tree", "archive"])
def test_changed_source_or_forged_context_denies_before_database(
    native_stage: tuple[Path, operator.OperatorContext, str],
    monkeypatch: pytest.MonkeyPatch,
    changed: str,
) -> None:
    from eom_api import build_info
    from eom_orchestrator import database, migration

    path, context, _ = native_stage
    build: Any = SimpleNamespace(
        **{
            key: getattr(context, key)
            for key in ("source_commit", "source_tree", "source_archive_sha256")
        }
    )
    if changed == "head":
        monkeypatch.setattr(migration, "CURRENT_MIGRATION_REVISION", "20261012_0052")
    elif changed == "context":
        context = replace(context, migration_revision="20261012_0052")
    else:
        setattr(
            build,
            {"commit": "source_commit", "tree": "source_tree", "archive": "source_archive_sha256"}[
                changed
            ],
            "f" * 40,
        )
    monkeypatch.setattr(build_info, "get_build_info", lambda: build)
    engine = Mock()
    monkeypatch.setattr(database, "build_engine", engine)
    with pytest.raises(operator.OperatorRuntimeError):
        operator.run_callback(path.parent, context, operator.Callback.MIGRATION_VERIFY_0053)
    engine.assert_not_called()
