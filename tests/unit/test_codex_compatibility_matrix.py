"""Explicit maintenance selections: synthetic contract tests, never native model calls."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from eom_identifiers import content_sha256, sha256_bytes
from eom_workflow.codex_compatibility import compatibility_contract_sha256
from eom_workflow.codex_compatibility_matrix import (
    CompatibilityMatrix,
    CompatibilitySelection,
    load_compatibility_matrix,
)
from eom_workflow.control_plane import ReasoningEffort
from eom_workflow.control_schemas import (
    CONTROL_SCHEMA_RESOURCES,
    load_control_schema,
    validate_control_contract,
)
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

SCHEMA_NAME = "codex-compatibility-matrix"
SCHEMA_VERSION = "codex-compatibility-matrix/1.0"
EXECUTION_SCHEMA_NAMES = (
    "codex-compatibility-request",
    "codex-compatibility-report",
    "codex-compatibility-invocation",
    "codex-compatibility-probe-result",
)


def _selection(**changes: object) -> dict[str, Any]:
    return {
        "slot_id": "01",
        "model": "synthetic-model",
        "reasoning_effort": "medium",
        **changes,
    }


def _matrix(*selections: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "selections": list(selections) if selections else [_selection()],
    }


def test_schema_first_loader_preserves_exact_selection_wire_values() -> None:
    document = _matrix()
    matrix = load_compatibility_matrix(document)
    assert matrix == CompatibilityMatrix.model_validate(document)
    assert matrix.model_dump(mode="json") == document
    assert isinstance(matrix.selections, tuple)
    assert isinstance(matrix.selections[0], CompatibilitySelection)
    assert matrix.selections[0].reasoning_effort == ReasoningEffort.MEDIUM


def test_python_constructor_defaults_version_but_wire_requires_it() -> None:
    matrix = CompatibilityMatrix(selections=(CompatibilitySelection(**_selection()),))
    assert matrix.schema_version == SCHEMA_VERSION
    document = _matrix()
    del document["schema_version"]
    with pytest.raises(SchemaValidationError):
        load_compatibility_matrix(document)


@pytest.mark.parametrize("slot", ["01", "02", "03", "04", "05", "06"])
def test_all_fixed_worker_slots_are_explicit_valid_selections(slot: str) -> None:
    parsed = load_compatibility_matrix(_matrix(_selection(slot_id=slot)))
    assert parsed.selections[0].slot_id == slot


@pytest.mark.parametrize("effort", list(ReasoningEffort))
def test_existing_reasoning_efforts_are_preserved(effort: ReasoningEffort) -> None:
    parsed = load_compatibility_matrix(_matrix(_selection(reasoning_effort=effort.value)))
    assert parsed.selections[0].reasoning_effort == effort


@pytest.mark.parametrize("model", ["a", "A0._:-", "m" * 128])
def test_model_contract_accepts_only_explicit_valid_names(model: str) -> None:
    parsed = load_compatibility_matrix(_matrix(_selection(model=model)))
    assert parsed.selections[0].model == model


def test_full_64_selection_bound_preserves_input_order_without_expansion() -> None:
    document = _matrix(*(_selection(model=f"synthetic-{index}") for index in range(64)))
    matrix = load_compatibility_matrix(document)
    assert len(matrix.selections) == 64
    assert matrix.model_dump(mode="json") == document


@pytest.mark.parametrize("count", [0, 65])
def test_selection_count_bounds_apply_to_schema_and_model(count: int) -> None:
    document = {
        "schema_version": SCHEMA_VERSION,
        "selections": [_selection(model=f"synthetic-{index}") for index in range(count)],
    }
    with pytest.raises(SchemaValidationError):
        load_compatibility_matrix(document)
    with pytest.raises(ValidationError):
        CompatibilityMatrix.model_validate(document)


def test_duplicate_triples_are_rejected_even_with_different_object_key_order() -> None:
    first = _selection()
    second = dict(reversed(tuple(first.items())))
    document = _matrix(first, second)
    with pytest.raises(SchemaValidationError):
        validate_control_contract(SCHEMA_NAME, document)
    with pytest.raises(ValidationError):
        CompatibilityMatrix.model_validate(document)


def test_uniqueness_is_the_complete_slot_model_effort_triple() -> None:
    document = _matrix(
        _selection(),
        _selection(slot_id="02"),
        _selection(model="synthetic-other"),
        _selection(reasoning_effort="high"),
    )
    assert load_compatibility_matrix(document).model_dump(mode="json") == document


def test_matrix_and_nested_selections_are_frozen() -> None:
    matrix = load_compatibility_matrix(_matrix())
    with pytest.raises(ValidationError, match="frozen"):
        matrix.selections = ()
    with pytest.raises(ValidationError, match="frozen"):
        matrix.selections[0].model = "replacement"


def test_mutating_input_document_cannot_change_frozen_selection_snapshot() -> None:
    document = _matrix()
    original = deepcopy(document)
    matrix = load_compatibility_matrix(document)
    document["selections"][0]["model"] = "changed-input"
    document["selections"].append(_selection(slot_id="02"))
    assert matrix.model_dump(mode="json") == original


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("slot_id", "00"),
        ("slot_id", "07"),
        ("slot_id", "1"),
        ("slot_id", 1),
        ("slot_id", True),
        ("slot_id", None),
        ("model", ""),
        ("model", "model --unsafe"),
        ("model", "model;command"),
        ("model", "../model"),
        ("model", "model\n"),
        ("model", "한글"),
        ("model", "m" * 129),
        ("model", 1),
        ("model", None),
        ("reasoning_effort", "max"),
        ("reasoning_effort", "ultra"),
        ("reasoning_effort", "MEDIUM"),
        ("reasoning_effort", ""),
        ("reasoning_effort", 1),
        ("reasoning_effort", None),
    ],
)
def test_invalid_selection_values_are_rejected(field: str, value: object) -> None:
    document = _matrix(_selection(**{field: value}))
    with pytest.raises((SchemaValidationError, ValidationError)):
        load_compatibility_matrix(document)
    with pytest.raises(ValidationError):
        CompatibilityMatrix.model_validate(document)


@pytest.mark.parametrize("field", ["slot_id", "model", "reasoning_effort"])
def test_every_selection_field_is_required(field: str) -> None:
    selection = _selection()
    del selection[field]
    document = _matrix(selection)
    with pytest.raises(SchemaValidationError):
        load_compatibility_matrix(document)
    with pytest.raises(ValidationError):
        CompatibilityMatrix.model_validate(document)


@pytest.mark.parametrize("value", [None, [], 1, True, "{}"])
def test_matrix_must_be_an_object(value: object) -> None:
    with pytest.raises(SchemaValidationError):
        load_compatibility_matrix(value)
    with pytest.raises(ValidationError):
        CompatibilityMatrix.model_validate(value)


@pytest.mark.parametrize("value", [None, [], 1, True, "{}"])
def test_each_selection_must_be_an_object(value: object) -> None:
    document = {"schema_version": SCHEMA_VERSION, "selections": [value]}
    with pytest.raises(SchemaValidationError):
        load_compatibility_matrix(document)
    with pytest.raises(ValidationError):
        CompatibilityMatrix.model_validate(document)


@pytest.mark.parametrize("value", [None, {}, 1, True, "[]"])
def test_selections_wire_member_must_be_an_array(value: object) -> None:
    document = {"schema_version": SCHEMA_VERSION, "selections": value}
    with pytest.raises(SchemaValidationError):
        load_compatibility_matrix(document)
    with pytest.raises(ValidationError):
        CompatibilityMatrix.model_validate(document)


@pytest.mark.parametrize("value", ["codex-compatibility-matrix/2.0", "", None, 1])
def test_wire_version_is_exact(value: object) -> None:
    document = {**_matrix(), "schema_version": value}
    with pytest.raises(SchemaValidationError):
        load_compatibility_matrix(document)
    with pytest.raises(ValidationError):
        CompatibilityMatrix.model_validate(document)


def test_selections_wire_member_is_required() -> None:
    document = {"schema_version": SCHEMA_VERSION}
    with pytest.raises(SchemaValidationError):
        load_compatibility_matrix(document)
    with pytest.raises(ValidationError):
        CompatibilityMatrix.model_validate(document)


@pytest.mark.parametrize("location", ["matrix", "selection"])
@pytest.mark.parametrize(
    "field",
    [
        "binding_id",
        "assignment_revision_id",
        "auth_id",
        "account_id",
        "expected_resource_version",
        "worker_authority",
        "credentials",
        "max_model_calls",
        "unknown_field",
    ],
)
def test_matrix_cannot_supply_binding_authentication_or_other_authority(
    location: str, field: str
) -> None:
    document = _matrix()
    target = document if location == "matrix" else document["selections"][0]
    target[field] = "untrusted-model-supplied-value"
    with pytest.raises(SchemaValidationError):
        load_compatibility_matrix(document)
    with pytest.raises(ValidationError):
        CompatibilityMatrix.model_validate(document)


def test_canonical_matrix_schema_matches_packaged_resource_and_registered_hash() -> None:
    root = Path(__file__).resolve().parents[2]
    resource = CONTROL_SCHEMA_RESOURCES[SCHEMA_NAME]
    canonical = (root / resource.canonical_path).read_bytes()
    packaged = (root / "packages/workflow/eom_workflow" / resource.resource_path).read_bytes()
    assert canonical == packaged
    assert sha256_bytes(canonical) == resource.sha256
    assert resource.schema_version == "1.0"


def test_matrix_schema_is_closed_2020_12_with_required_version_and_bounded_unique_array() -> None:
    schema = load_control_schema(SCHEMA_NAME)
    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"schema_version", "selections"}
    assert set(schema["properties"]) == {"schema_version", "selections"}
    assert schema["properties"]["schema_version"]["const"] == SCHEMA_VERSION
    selections = schema["properties"]["selections"]
    assert selections["type"] == "array"
    assert selections["minItems"] == 1
    assert selections["maxItems"] == 64
    assert selections["uniqueItems"] is True
    selection = selections["items"]
    assert selection["type"] == "object"
    assert selection["additionalProperties"] is False
    assert set(selection["required"]) == {"slot_id", "model", "reasoning_effort"}
    assert set(selection["properties"]) == {"slot_id", "model", "reasoning_effort"}
    assert all(value["type"] == "string" for value in selection["properties"].values())


def test_matrix_does_not_change_the_existing_four_resource_runtime_contract_pin() -> None:
    assert SCHEMA_NAME in CONTROL_SCHEMA_RESOURCES
    assert compatibility_contract_sha256() == content_sha256(
        {name: CONTROL_SCHEMA_RESOURCES[name].sha256 for name in EXECUTION_SCHEMA_NAMES}
    )
