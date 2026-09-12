from __future__ import annotations

import hashlib
from importlib.resources import files
from pathlib import Path

import pytest
from eom_workflow.control_schemas import (
    CONTROL_SCHEMA_RESOURCES,
    load_control_schema,
)
from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("name", "expected_id", "expected_protocol"),
    [
        (
            "standard-control-bootstrap-v12",
            "eom://schemas/workflow/standard-control-bootstrap/12.0",
            "workflow-role/1.20.0",
        ),
        (
            "knowledge-item-control-bootstrap-v9",
            "eom://schemas/workflow/knowledge-item-control-bootstrap/9.0",
            "workflow-role/1.20.0",
        ),
        (
            "standard-control-bootstrap-v13",
            "eom://schemas/workflow/standard-control-bootstrap/13.0",
            "workflow-role/1.20.0",
        ),
        (
            "knowledge-item-control-bootstrap-v10",
            "eom://schemas/workflow/knowledge-item-control-bootstrap/10.0",
            "workflow-role/1.20.0",
        ),
    ],
)
def test_v120_control_schema_is_202012_packaged_and_hash_pinned(
    name: str,
    expected_id: str,
    expected_protocol: str,
) -> None:
    resource = CONTROL_SCHEMA_RESOURCES[name]
    canonical = (ROOT / resource.canonical_path).read_bytes()
    packaged = files("eom_workflow").joinpath(resource.resource_path).read_bytes()
    assert canonical == packaged
    assert "sha256:" + hashlib.sha256(canonical).hexdigest() == resource.sha256

    schema = load_control_schema(name)
    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == expected_id
    protocol = schema["properties"]["compatible_workflow_protocols"]
    assert protocol["prefixItems"] == [{"const": expected_protocol}]


def test_v120_control_schemas_reject_historical_protocol_substitution() -> None:
    for name in (
        "standard-control-bootstrap-v12",
        "knowledge-item-control-bootstrap-v9",
        "standard-control-bootstrap-v13",
        "knowledge-item-control-bootstrap-v10",
    ):
        schema = load_control_schema(name)
        protocol_schema = schema["properties"]["compatible_workflow_protocols"]
        with pytest.raises(ValidationError):
            Draft202012Validator(protocol_schema).validate(["workflow-role/1.19.0"])
