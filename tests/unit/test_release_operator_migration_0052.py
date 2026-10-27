"""Synthetic successor context and fake migration ports; never privileged execution."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from jsonschema import Draft202012Validator

from scripts.api import release_operator_runtime as operator
from tests.unit.test_release_operator_runtime import (
    FakeEngine,
    _context_value,
    _hash,
    _json,
)
from tests.unit.test_release_operator_runtime import (
    synthetic_stage as synthetic_stage,
)

ROOT = Path(__file__).resolve().parents[2]


def _successor() -> dict[str, Any]:
    return _context_value() | {
        "schema_version": "release-operator-context/1.1",
        "migration_revision": "20261012_0052",
    }


@pytest.fixture
def successor_stage(
    synthetic_stage: tuple[Path, operator.OperatorContext, str],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, operator.OperatorContext, str]:
    from eom_orchestrator import migration

    path, _, _ = synthetic_stage
    value = json.loads(path.read_bytes())
    value.update(schema_version="release-operator-context/1.1", migration_revision="20261012_0052")
    path.write_bytes(_json(value))
    digest = _hash(path.read_bytes())
    monkeypatch.setattr(migration, "CURRENT_MIGRATION_REVISION", "20261012_0052")
    return path, operator.load_context(path, digest, "a" * 40), digest


def test_successor_schema_raw_sha_and_old_bytes_remain_exact() -> None:
    old = ROOT / "scripts/api/release_operator_context.schema.json"
    successor = ROOT / "scripts/api/release_operator_context_v1_1.schema.json"
    assert (
        _hash(old.read_bytes())
        == operator._SCHEMA_SHA256
        == ("sha256:5a60d4ec278f4d1200abfff99525cea4654bdbbcba0f86e801de669637e33c8a")
    )
    assert (
        _hash(successor.read_bytes())
        == operator._SCHEMA_V1_1_SHA256
        == ("sha256:3fbe06b5c74a74f46f98fb14813c48d1ede8e95be786061510eb0956ddce5eba")
    )
    schema = json.loads(successor.read_bytes())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(_successor())
    assert not Draft202012Validator(schema).is_valid(_context_value())
    assert not Draft202012Validator(json.loads(old.read_bytes())).is_valid(_successor())


@pytest.mark.parametrize(
    "changes",
    [
        {"migration_revision": "20261010_0051"},
        {"migration_revision": "head"},
        {"migration_revision": "20261013_0053"},
        {"migration_revision": True},
        {"schema_version": "release-operator-context/2.0"},
        {"command": "alembic upgrade head"},
        {"requester_role": "ADMIN"},
        {"callbacks": ["MIGRATION_VERIFY"]},
    ],
)
def test_successor_is_closed_and_has_no_target_or_permission_override(
    changes: dict[str, Any],
) -> None:
    schema = json.loads(
        (ROOT / "scripts/api/release_operator_context_v1_1.schema.json").read_bytes()
    )
    assert not Draft202012Validator(schema).is_valid(_successor() | changes)


def test_successor_admission_pins_exact_version_target_and_no_old_receipt_reinterpretation(
    successor_stage: tuple[Path, operator.OperatorContext, str],
) -> None:
    path, context, digest = successor_stage
    operator.admit(path, context, digest)
    receipt_path = path.parent / "operator-admission.json"
    receipt = json.loads(receipt_path.read_bytes())
    assert receipt["schema_version"] == "release-operator-admission/1.1"
    assert receipt["migration_revision"] == "20261012_0052"
    operator.verify_admission(path, context, digest)
    receipt.pop("migration_revision")
    receipt["schema_version"] = "release-operator-admission/1.0"
    receipt_path.write_bytes(_json(receipt))
    with pytest.raises(operator.OperatorRuntimeError, match="ADMISSION_CHANGED"):
        operator.verify_admission(path, context, digest)


def test_successor_context_commit_raw_hash_and_schema_change_are_explicit(
    successor_stage: tuple[Path, operator.OperatorContext, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, _, digest = successor_stage
    with pytest.raises(operator.OperatorRuntimeError, match="SOURCE_MISMATCH"):
        operator.load_context(path, digest, "b" * 40)
    with pytest.raises(operator.OperatorRuntimeError, match="CONTEXT_CHANGED"):
        operator.load_context(path, "sha256:" + "0" * 64, "a" * 40)
    original = operator.read_protected

    def changed_schema(target: Path, *, maximum: int, allow_empty: bool = False) -> bytes:
        if target.name == "release_operator_context_v1_1.schema.json":
            return b"{}"
        return original(target, maximum=maximum, allow_empty=allow_empty)

    monkeypatch.setattr(operator, "read_protected", changed_schema)
    with pytest.raises(operator.OperatorRuntimeError, match="SCHEMA_CHANGED"):
        operator.load_context(path, digest, "a" * 40)


def _build_pin(context: operator.OperatorContext) -> SimpleNamespace:
    return SimpleNamespace(
        source_commit=context.source_commit,
        source_tree=context.source_tree,
        source_archive_sha256=context.source_archive_sha256,
    )


@pytest.mark.parametrize(
    "callback,revision,owner,succeeds,upgrade_count",
    [
        (operator.Callback.MIGRATION_VERIFY_0052, "20261012_0052", True, True, 0),
        (operator.Callback.MIGRATION_VERIFY_0052, "20261010_0051", True, False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0052, "20261010_0051", True, True, 1),
        (operator.Callback.MIGRATION_UPGRADE_0052, "20261012_0052", True, True, 0),
        (operator.Callback.MIGRATION_UPGRADE_0052, "20261009_0050", True, False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0052, "unexpected", True, False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0052, "20261010_0051", False, False, 0),
    ],
)
def test_exact_0052_callback_target_predecessor_and_owner_guard(
    successor_stage: tuple[Path, operator.OperatorContext, str],
    monkeypatch: pytest.MonkeyPatch,
    callback: operator.Callback,
    revision: str,
    owner: bool,
    succeeds: bool,
    upgrade_count: int,
) -> None:
    from alembic import command
    from alembic.config import Config
    from eom_api import build_info
    from eom_orchestrator import database

    path, context, _ = successor_stage
    monkeypatch.setattr(build_info, "get_build_info", lambda: _build_pin(context))
    engine = FakeEngine(revision, owner=owner)
    monkeypatch.setattr(database, "build_engine", lambda: engine)
    configurations = []

    def upgrade(configuration: Config, target: str) -> None:
        assert target == "20261012_0052"
        configurations.append(configuration)
        engine.revision = target

    monkeypatch.setattr(command, "upgrade", upgrade)
    if succeeds:
        operator.run_callback(path.parent, context, callback)
    else:
        with pytest.raises(operator.OperatorRuntimeError):
            operator.run_callback(path.parent, context, callback)
    assert len(configurations) == upgrade_count and engine.disposed
    for configuration in configurations:
        assert configuration.get_main_option("script_location") == str(
            path.parent / "source/migrations"
        )
        assert configuration.get_main_option("prepend_sys_path") == ""


@pytest.mark.parametrize(
    "callback", [operator.Callback.MIGRATION_VERIFY, operator.Callback.MIGRATION_UPGRADE_0051]
)
def test_successor_never_routes_legacy_callback_to_0052(
    successor_stage: tuple[Path, operator.OperatorContext, str],
    monkeypatch: pytest.MonkeyPatch,
    callback: operator.Callback,
) -> None:
    from eom_api import build_info
    from eom_orchestrator import database

    path, context, _ = successor_stage
    monkeypatch.setattr(build_info, "get_build_info", lambda: _build_pin(context))
    engine = Mock()
    monkeypatch.setattr(database, "build_engine", engine)
    with pytest.raises(operator.OperatorRuntimeError, match="REVISION_UNSUPPORTED"):
        operator.run_callback(path.parent, context, callback)
    engine.assert_not_called()


def test_archived_context_and_current_source_cannot_impersonate_one_another(
    synthetic_stage: tuple[Path, operator.OperatorContext, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from eom_api import build_info
    from eom_orchestrator import database, migration

    path, old_context, _ = synthetic_stage
    monkeypatch.setattr(build_info, "get_build_info", lambda: _build_pin(old_context))
    monkeypatch.setattr(migration, "CURRENT_MIGRATION_REVISION", "20261012_0052")
    engine = Mock()
    monkeypatch.setattr(database, "build_engine", engine)
    with pytest.raises(operator.OperatorRuntimeError, match="REVISION_UNSUPPORTED"):
        operator.run_callback(path.parent, old_context, operator.Callback.MIGRATION_VERIFY)
    engine.assert_not_called()
    invalid = replace(old_context, migration_revision="20261012_0052")
    with pytest.raises(operator.OperatorRuntimeError, match="CONTEXT_INVALID"):
        operator.run_callback(path.parent, invalid, operator.Callback.MIGRATION_VERIFY_0052)


@pytest.mark.parametrize("changed", ["source_head", "source_commit", "source_tree", "archive"])
def test_successor_rejects_wrong_source_and_head_before_any_database_port(
    successor_stage: tuple[Path, operator.OperatorContext, str],
    monkeypatch: pytest.MonkeyPatch,
    changed: str,
) -> None:
    from eom_api import build_info
    from eom_orchestrator import database, migration

    path, context, _ = successor_stage
    build = _build_pin(context)
    if changed == "source_head":
        monkeypatch.setattr(migration, "CURRENT_MIGRATION_REVISION", "20261010_0051")
    elif changed == "source_commit":
        build.source_commit = "f" * 40
    elif changed == "source_tree":
        build.source_tree = "f" * 40
    else:
        build.source_archive_sha256 = "sha256:" + "f" * 64
    monkeypatch.setattr(build_info, "get_build_info", lambda: build)
    engine = Mock()
    monkeypatch.setattr(database, "build_engine", engine)
    with pytest.raises(operator.OperatorRuntimeError):
        operator.run_callback(path.parent, context, operator.Callback.MIGRATION_VERIFY_0052)
    engine.assert_not_called()


def test_root_requirement_and_closed_shell_callbacks_are_not_widened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 1001)
    with pytest.raises(operator.OperatorRuntimeError, match="ROOT_REQUIRED"):
        operator.require_root()
    for filename in ("release_operator_runtime.sh", "release_operator_boundary.sh"):
        source = (ROOT / "scripts/api" / filename).read_text()
        assert "MIGRATION_VERIFY_0052|MIGRATION_UPGRADE_0052" in source
        assert "ARBITRARY_COMMAND" not in source
    deployment = (ROOT / "scripts/api/deploy_release.sh").read_text()
    assert 'run_release_operator MIGRATION_VERIFY_0061 "${COMMIT}"' in deployment
    assert 'if CURRENT_MIGRATION_REVISION != "20261027_0061":' in deployment
    assert 'run_release_operator MIGRATION_VERIFY "${COMMIT}"' not in deployment
    historical = (ROOT / "scripts/api/migrate_release.sh").read_text()
    assert "MIGRATION_UPGRADE_0051" in historical and "MIGRATION_VERIFY_0052" not in historical
