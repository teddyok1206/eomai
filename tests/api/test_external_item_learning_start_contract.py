"""The public creative-learning selection pins a source; it grants no execution right."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

import pytest
from eom_api_contracts import ExternalItemLearningStartV1
from jsonschema import Draft202012Validator
from pydantic import ValidationError

_ROOT = Path(__file__).resolve().parents[2]
_NAME = "external-item-learning-start-v1.schema.json"


def _value() -> dict[str, object]:
    return {
        "schema_version": "external-item-learning-start/1.0",
        "import_id": "extimport_" + "a" * 32,
        "external_number": "10310",
        "source_revision_id": "extitemrev_" + "b" * 32,
        "observation_sha256": "sha256:" + "c" * 64,
        "selected_edition": 3,
    }


def test_creative_start_schema_is_bundled_and_matches_canonical_bytes() -> None:
    canonical = (_ROOT / "schemas/api/v1" / _NAME).read_bytes()
    bundled = files("eom_api_contracts").joinpath("schemas", _NAME).read_bytes()
    assert bundled == canonical
    schema = json.loads(canonical)
    Draft202012Validator.check_schema(schema)
    value = ExternalItemLearningStartV1.model_validate(_value()).model_dump(mode="json")
    Draft202012Validator(schema).validate(value)
    assert "operator_id" not in value and "artifact_id" not in value


@pytest.mark.parametrize(
    "change",
    [
        {"external_number": "1031"},
        {"selected_edition": 1},
        {"source_revision_id": "extitemrev_" + "B" * 32},
        {"observation_sha256": "sha256:" + "z" * 64},
        {"artifact_id": "artifact_" + "d" * 32},
    ],
)
def test_creative_start_rejects_unpinned_or_extra_input(change: dict[str, object]) -> None:
    value = {**_value(), **change}
    schema = json.loads((_ROOT / "schemas/api/v1" / _NAME).read_text())
    assert not Draft202012Validator(schema).is_valid(value)
    with pytest.raises(ValidationError):
        ExternalItemLearningStartV1.model_validate(value)
