"""Pure metadata contracts do not authenticate a service or grant source access."""

from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

import pytest
from eom_identifiers import canonical_json_bytes
from eom_operator_identity import (
    LOCAL_INDEXING_RUNTIME_SCHEMA_REF,
    MAX_LOCAL_INDEXING_RUNTIME_BYTES,
    LocalIndexingRuntimeConfiguration,
    LocalIndexingServiceReference,
    local_indexing_runtime_bytes,
    local_indexing_runtime_schema,
    parse_local_indexing_runtime_configuration,
)
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]


def document() -> dict[str, object]:
    return {
        "schema_version": "local-indexing-runtime/1.0",
        "service": {
            "service_id": "localindexservice_" + "1" * 32,
            "service_revision_id": "localindexservicerev_" + "2" * 32,
            "service_identity_sha256": "sha256:" + "3" * 64,
        },
        "runtime_source_commit": "4" * 40,
        "platform_wheel_sha256": "sha256:" + "5" * 64,
        "api_contracts_wheel_sha256": "sha256:" + "6" * 64,
        "interpreter_sha256": "sha256:" + "7" * 64,
        "unit_sha256": "sha256:" + "8" * 64,
    }


def test_closed_schema_mirror_package_and_canonical_round_trip() -> None:
    name = "local-indexing-runtime-v1.schema.json"
    raw = (ROOT / "schemas/identity" / name).read_bytes()
    assert (
        raw
        == (ROOT / "packages/operator_identity/eom_operator_identity/resources" / name).read_bytes()
    )
    assert hashlib.sha256(raw).hexdigest() == (
        "db53688fbf73d082cab552b696c59788aa0fbc7d404077f3610b91b81ef2756f"
    )
    schema = local_indexing_runtime_schema()
    assert schema["$id"] == LOCAL_INDEXING_RUNTIME_SCHEMA_REF
    Draft202012Validator.check_schema(schema)
    schema["additionalProperties"] = True
    assert local_indexing_runtime_schema()["additionalProperties"] is False
    config = LocalIndexingRuntimeConfiguration.model_validate(document())
    wire = local_indexing_runtime_bytes(config)
    assert wire == canonical_json_bytes(document())
    assert parse_local_indexing_runtime_configuration(wire) == config
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert (
        "resources/" + name
        in project["tool"]["setuptools"]["package-data"]["eom_operator_identity"]
    )
    assert not hasattr(config, "permissions") and not hasattr(config, "operator_id")


@pytest.mark.parametrize(
    "field", ["token", "password", "roles", "permissions", "path", "database_url", "operator_id"]
)
def test_no_credentials_authority_or_user_selected_paths(field: str) -> None:
    value = document()
    value[field] = "MUST_NOT_BE_ECHOED"
    with pytest.raises(ValueError) as caught:
        LocalIndexingRuntimeConfiguration.model_validate(value)
    assert "MUST_NOT_BE_ECHOED" not in str(caught.value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "local-indexing-runtime/2.0"),
        ("runtime_source_commit", "latest"),
        ("runtime_source_commit", "A" * 40),
        ("platform_wheel_sha256", "sha256:" + "a" * 63),
        ("api_contracts_wheel_sha256", "SHA256:" + "a" * 64),
        ("interpreter_sha256", True),
        ("unit_sha256", "sha256:" + "f" * 64 + "\n"),
        ("service", {"operator_id": "operator_" + "a" * 32}),
    ],
)
def test_schema_first_exact_pins(field: str, value: object) -> None:
    values = document()
    values[field] = value
    with pytest.raises(ValueError):
        LocalIndexingRuntimeConfiguration.model_validate(values)


def test_missing_fields_and_model_copy_are_revalidated() -> None:
    model = LocalIndexingRuntimeConfiguration.model_validate(document())
    for field in type(model).model_fields:
        values = document()
        del values[field]
        with pytest.raises(ValueError):
            LocalIndexingRuntimeConfiguration.model_validate(values)
    nested = model.service.model_copy(update={"permissions": ["ADMIN"]})
    for forged in (
        model.model_copy(update={"permissions": ["ADMIN"]}),
        model.model_copy(update={"service": nested}),
        model.model_copy(update={"runtime_source_commit": "latest"}),
        model.model_copy(update={"service": LocalIndexingServiceReference.model_construct()}),
    ):
        with pytest.raises(ValueError):
            local_indexing_runtime_bytes(forged)
    with pytest.raises(ValueError, match="frozen"):
        model.runtime_source_commit = "b" * 40


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"{}",
        b"[]",
        b"null",
        b"\xff",
        b"{",
        b'{"service":null,"service":null}',
        b'{"unit_sha256":NaN}',
        b'{"a":' * 1100 + b"{}" + b"}" * 1100,
        b" " * (MAX_LOCAL_INDEXING_RUNTIME_BYTES + 1),
    ],
)
def test_untrusted_wire_is_bounded_canonical_and_duplicate_free(raw: bytes) -> None:
    with pytest.raises(ValueError):
        parse_local_indexing_runtime_configuration(raw)


def test_equivalent_but_noncanonical_json_is_not_admitted() -> None:
    for wire in (json.dumps(document()).encode(), b" " + canonical_json_bytes(document())):
        with pytest.raises(ValueError):
            parse_local_indexing_runtime_configuration(wire)
