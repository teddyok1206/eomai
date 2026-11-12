"""All archived formats retain exact schema/hash/head and receipt identities."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.api import release_operator_runtime as operator
from tests.unit.test_release_operator_runtime import _context_value, _hash, _json
from tests.unit.test_release_operator_runtime import synthetic_stage as synthetic_stage

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = sorted((ROOT / "scripts/api").glob("release_operator_context*.schema.json"))


@pytest.mark.parametrize("schema_path", SCHEMAS, ids=lambda path: path.stem)
def test_every_released_schema_loads_and_emits_the_same_admission(synthetic_stage, schema_path):
    path, _, _ = synthetic_stage
    schema = json.loads(schema_path.read_bytes())
    context_properties = schema["$defs"]["context"]["properties"]
    receipt_properties = schema["$defs"]["receipt"]["properties"]
    version = context_properties["schema_version"]["const"]
    body = _context_value() | {"schema_version": version}
    if "migration_revision" in context_properties:
        body["migration_revision"] = context_properties["migration_revision"]["const"]
    path.write_bytes(_json(body))
    context = operator.load_context(path, _hash(path.read_bytes()), "a" * 40)
    rule = operator._CONTEXT_FORMATS[version]
    assert rule.schema_name == schema_path.name
    assert rule.schema_sha256 == _hash(schema_path.read_bytes())
    assert operator._context_migration_revision(context) == context.migration_revision
    receipt = operator._admission_document(path, context, _hash(path.read_bytes()))
    assert receipt["schema_version"] == receipt_properties["schema_version"]["const"]
    assert operator._json(_json(receipt)) == receipt
    for other in operator._CONTEXT_FORMATS.values():
        if other.migration_revision != context.migration_revision:
            with pytest.raises(
                operator.OperatorRuntimeError, match="RELEASE_OPERATOR_CONTEXT_INVALID"
            ):
                operator._context_migration_revision(
                    replace(context, migration_revision=other.migration_revision)
                )


def test_context_inventory_is_exact_and_immutable():
    released = {
        json.loads(path.read_bytes())["$defs"]["context"]["properties"]["schema_version"]["const"]
        for path in SCHEMAS
    }
    assert set(operator._CONTEXT_FORMATS) == released
    with pytest.raises(TypeError):
        operator._CONTEXT_FORMATS["release-operator-context/1.25"] = None


@pytest.mark.parametrize(
    "version", ["release-operator-context/1.25", "release-operator-admission/1.25", [], {}, None]
)
def test_unreleased_or_nonstring_version_has_stable_rejection(version):
    with pytest.raises(operator.OperatorRuntimeError, match="RELEASE_OPERATOR_JSON_INVALID"):
        operator._json(_json(_context_value() | {"schema_version": version}))
