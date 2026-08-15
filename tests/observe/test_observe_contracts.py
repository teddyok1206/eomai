from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

pytest.importorskip("eom_observe")

from eom_observe.settings import load_settings
from eom_observe_contracts import NodeStatus, validate_contract

from tests.observe.helpers import snapshot


def test_snapshot_json_schema_validation() -> None:
    value = snapshot().model_dump(mode="json")
    validate_contract("snapshot", value)


def test_snapshot_schema_rejects_additional_property() -> None:
    value = snapshot().model_dump(mode="json")
    value["secret"] = "must fail"
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("snapshot", value)


def test_node_status_enum() -> None:
    assert {status.value for status in NodeStatus} >= {"IDLE", "RUNNING", "UNAVAILABLE"}


def test_config_validation_accepts_example() -> None:
    settings = load_settings(Path("config/observe.example.yaml"))
    assert settings.server.host == "127.0.0.1"
    assert settings.server.port == 8780


def test_config_rejects_non_loopback(tmp_path: Path) -> None:
    value = yaml.safe_load(Path("config/observe.example.yaml").read_text(encoding="utf-8"))
    value["server"]["host"] = "0.0.0.0"
    target = tmp_path / "observe.yaml"
    target.write_text(yaml.safe_dump(value), encoding="utf-8")
    with pytest.raises(RuntimeError):
        load_settings(target)


def test_pydantic_contract_rejects_unknown_status() -> None:
    value = snapshot().nodes[0].model_dump()
    value["status"] = "MUTATING"
    with pytest.raises(ValidationError):
        type(snapshot().nodes[0]).model_validate(value)
