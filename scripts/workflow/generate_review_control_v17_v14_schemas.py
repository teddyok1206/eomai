#!/usr/bin/env python3
"""Generate protocol-first control schemas for verification-planned item review."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "schemas/workflow/control-plane"
PACKAGE = ROOT / "packages/workflow/eom_workflow/resources/control-plane"


def _load(name: str) -> dict[str, object]:
    value = json.loads((CANONICAL / name).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"schema is not an object: {name}")
    return value


def _write(name: str, value: dict[str, object]) -> None:
    Draft202012Validator.check_schema(value)
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    for root in (CANONICAL, PACKAGE):
        path = root / name
        if path.exists() and path.read_bytes() != payload:
            raise ValueError(f"generated schema has drifted: {path}")
        path.write_bytes(payload)


def _standard() -> dict[str, object]:
    value = deepcopy(_load("standard-control-bootstrap-v16.schema.json"))
    value["$id"] = "eom://schemas/workflow/standard-control-bootstrap/17.0"
    value["title"] = "Standard item control bootstrap V17 manifest"
    properties = value["properties"]
    assert isinstance(properties, dict)
    schema_version = properties["schema_version"]
    assert isinstance(schema_version, dict)
    schema_version["const"] = "standard-control-bootstrap/17.0"
    protocols = properties["compatible_workflow_protocols"]
    assert isinstance(protocols, dict)
    prefix = protocols["prefixItems"]
    assert isinstance(prefix, list) and isinstance(prefix[0], dict)
    prefix[0]["const"] = "workflow-role/1.24.0"
    properties["review_escalation_model"] = {
        "type": "string",
        "pattern": "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    }
    properties["review_escalation_reasoning_effort"] = {
        "enum": ["minimal", "low", "medium", "high", "xhigh"]
    }
    required = value["required"]
    assert isinstance(required, list)
    required.extend(("review_escalation_model", "review_escalation_reasoning_effort"))
    return value


def _knowledge() -> dict[str, object]:
    value = deepcopy(_load("knowledge-item-control-bootstrap-v13.schema.json"))
    value["$id"] = "eom://schemas/workflow/knowledge-item-control-bootstrap/14.0"
    value["title"] = "Knowledge item control bootstrap V14 manifest"
    properties = value["properties"]
    assert isinstance(properties, dict)
    schema_version = properties["schema_version"]
    assert isinstance(schema_version, dict)
    schema_version["const"] = "knowledge-item-control-bootstrap/14.0"
    protocols = properties["compatible_workflow_protocols"]
    assert isinstance(protocols, dict)
    prefix = protocols["prefixItems"]
    assert isinstance(prefix, list) and isinstance(prefix[0], dict)
    prefix[0]["const"] = "workflow-role/1.24.0"
    revision_ids = properties["base_instruction_bundle_revision_ids"]
    member_hashes = properties["base_instruction_member_sha256s"]
    assert isinstance(revision_ids, dict) and isinstance(member_hashes, dict)
    revision_properties = revision_ids["properties"]
    hash_properties = member_hashes["properties"]
    assert isinstance(revision_properties, dict) and isinstance(hash_properties, dict)
    for role, revision_id in {
        "authoring": "instrrev_962c3376a767113a6467b20038f92d1e",
        "image": "instrrev_ba147748d79ebf929979cba963afec20",
        "review": "instrrev_5fea0e7c90c9c925c494afa2babd29b8",
        "item_management": "instrrev_e3739f17cd6f72c6ee5f9d10b3cc6a04",
    }.items():
        definition = revision_properties[role]
        assert isinstance(definition, dict)
        definition["const"] = revision_id
    for role, member_hash in {
        "platform": "sha256:5a3cfab6dc1c195ebc93cb13c7549cd31ea30f6229a4b134bed818d9dd69271b",
        "authoring": "sha256:f6019d8e13c8887bce76adbf183eaa5aa13bf014a749fcddfb97fa349dc3be0b",
        "image": "sha256:18ad7994b5d84bb395be1dddc40f3fde6d6637419926f1a7a59c8e8e6ec527e1",
        "review": "sha256:616b46ceb031c3044242597422c93e5538ab3caebaa16ea5d4650a01725f2898",
        "item_management": (
            "sha256:9482b7380920b1f0ffcdbca342e66a1c3797962beaa4d37d8d54eadcc30bdcd8"
        ),
    }.items():
        definition = hash_properties[role]
        assert isinstance(definition, dict)
        definition["const"] = member_hash
    return value


def main() -> None:
    _write("standard-control-bootstrap-v17.schema.json", _standard())
    _write("knowledge-item-control-bootstrap-v14.schema.json", _knowledge())


if __name__ == "__main__":
    main()
