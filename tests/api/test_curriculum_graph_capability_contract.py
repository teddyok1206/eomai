from __future__ import annotations

import json
from pathlib import Path

import pytest
from eom_api_contracts import CurriculumGraphCapabilityView
from jsonschema import Draft202012Validator
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "schemas/api/v1/curriculum-graph-capability-v1.schema.json"
RESOURCE = (
    ROOT
    / "packages/api_contracts/eom_api_contracts/schemas/curriculum-graph-capability-v1.schema.json"
)
OUTLINE_SHA256 = "sha256:" + "1" * 64


def _ready() -> dict[str, object]:
    return {
        "schema_version": "curriculum-graph-capability/1.0",
        "corpus_key": "integrated-science-textbooks",
        "outline_key": "eom-integrated-science-editorial-outline",
        "outline_revision": "1.0",
        "outline_sha256": OUTLINE_SHA256,
        "capability_state": "READY",
        "graph_grounding_available": True,
        "reason": "READY",
        "graph_snapshot_revision_id": "graphrev_" + "2" * 32,
        "snapshot_sha256": "sha256:" + "3" * 64,
        "framework_revision_id": "curriculumrev_" + "4" * 32,
        "unit_count": 43,
        "closure_count": 119,
    }


def test_curriculum_graph_capability_schema_is_mirrored_and_matches_model() -> None:
    assert CANONICAL.read_bytes() == RESOURCE.read_bytes()
    schema = json.loads(CANONICAL.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    value = CurriculumGraphCapabilityView.model_validate(_ready()).model_dump(mode="json")
    Draft202012Validator(schema).validate(value)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("graph_grounding_available", False),
        ("unit_count", 42),
        ("closure_count", 118),
        ("reason", "CURRICULUM_MAPPING_INCOMPLETE"),
        ("graph_snapshot_revision_id", None),
    ),
)
def test_ready_curriculum_capability_requires_exact_verified_projection(
    field: str, value: object
) -> None:
    payload = _ready()
    payload[field] = value
    with pytest.raises(ValidationError):
        CurriculumGraphCapabilityView.model_validate(payload)


def test_unavailable_curriculum_capability_does_not_expose_partial_pointers() -> None:
    payload = _ready()
    payload.update(
        {
            "capability_state": "UNAVAILABLE",
            "graph_grounding_available": False,
            "reason": "CURRICULUM_MAPPING_INCOMPLETE",
            "graph_snapshot_revision_id": None,
            "snapshot_sha256": None,
            "framework_revision_id": None,
            "unit_count": 42,
            "closure_count": 118,
        }
    )
    CurriculumGraphCapabilityView.model_validate(payload)
    payload["graph_snapshot_revision_id"] = "graphrev_" + "5" * 32
    with pytest.raises(ValidationError):
        CurriculumGraphCapabilityView.model_validate(payload)
