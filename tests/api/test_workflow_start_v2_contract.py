from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from eom_api_contracts.workflows import WorkflowStartRequest
from jsonschema import Draft202012Validator, ValidationError
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[2]


def _schema(path: str) -> dict[str, object]:
    value = json.loads((ROOT / path).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    Draft202012Validator.check_schema(value)
    return value


def _validator() -> Draft202012Validator:
    paths = (
        "schemas/api/v1/workflow-start-v1.schema.json",
        "schemas/api/v1/workflow-start-v2.schema.json",
        "schemas/workflow/knowledge-item-brief-v1.schema.json",
        "schemas/workflow/content-team-material-requirement-v1.schema.json",
        "schemas/knowledge/educational-retrieval-requirement-v1.schema.json",
        "schemas/assessment-assembly/mock-exam-production-plan-v1.schema.json",
    )
    resources: list[tuple[str, Resource[object]]] = []
    schemas: dict[str, dict[str, object]] = {}
    for path in paths:
        schema = _schema(path)
        identifier = schema.get("$id")
        assert isinstance(identifier, str)
        resources.append((identifier, Resource.from_contents(schema)))
        schemas[path] = schema
    return Draft202012Validator(
        schemas["schemas/api/v1/workflow-start-v2.schema.json"],
        registry=Registry().with_resources(resources),
    )


def _validator_v3() -> Draft202012Validator:
    paths = (
        "schemas/api/v1/workflow-start-v1.schema.json",
        "schemas/api/v1/workflow-start-v2.schema.json",
        "schemas/api/v1/workflow-start-v3.schema.json",
        "schemas/workflow/knowledge-item-brief-v1.schema.json",
        "schemas/workflow/content-team-material-requirement-v1.schema.json",
        "schemas/knowledge/educational-retrieval-requirement-v1.schema.json",
        "schemas/assessment-assembly/mock-exam-production-plan-v1.schema.json",
    )
    resources: list[tuple[str, Resource[object]]] = []
    schemas: dict[str, dict[str, object]] = {}
    for path in paths:
        schema = _schema(path)
        identifier = schema.get("$id")
        assert isinstance(identifier, str)
        resources.append((identifier, Resource.from_contents(schema)))
        schemas[path] = schema
    return Draft202012Validator(
        schemas["schemas/api/v1/workflow-start-v3.schema.json"],
        registry=Registry().with_resources(resources),
    )


def _request() -> dict[str, object]:
    guidance = "통합과학 범위에서 검증된 근거를 사용하여 표 자료 해석 문항을 작성한다."
    return {
        "definition_key": "generic-item-development",
        "definition_version": "1.12.0",
        "request_name": "GENERATED_KNOWLEDGE_ITEM_REQUEST",
        "image_mode": "skip",
        "pack_key": "generated-knowledge-item",
        "environment": "development",
        "source_intake_batch_ids": [],
        "registry_mode": "CREATE_ITEM",
        "item_id": None,
        "base_revision_id": None,
        "stimulus_asset_key": None,
        "execution_preset_key": "knowledge-grounded-item",
        "production_occurrence": None,
        "expected_resolution": None,
        "item_brief": {
            "schema_version": "4.0",
            "subject": "통합과학",
            "topic": "시간과 공간",
            "task_type": "자료 해석",
            "difficulty": "중",
            "authoring_guidance": guidance,
            "authoring_guidance_sha256": (
                "sha256:13bfcf2a02ba90c8ddffb5fd3da63f893a97e20f23e14995e9526ed0c064e2aa"
            ),
            "curriculum_selected_unit_key": "eom.is.middle.1-1",
            "mock_exam_slot": None,
            "material_requirement": {
                "schema_version": "content-team-material-requirement/1.0",
                "form": "TABLE",
                "panel_count": 1,
            },
            "original_request_sha256": (
                "13bfcf2a02ba90c8ddffb5fd3da63f893a97e20f23e14995e9526ed0c064e2aa"
            ),
        },
        "educational_retrieval": {
            "schema_version": "educational-retrieval-requirement/1.0",
            "corpus_key": "integrated-science-textbooks",
            "query_kind": "ITEM_PREPARATION",
            "curriculum_root_key": None,
            "topic_keys": [],
            "required_item_elements": ["choice", "paragraph", "table"],
            "source_classes": ["PAST_EXAM"],
        },
    }


def test_workflow_start_v2_is_packaged_and_validates_v4_like_pydantic() -> None:
    canonical = ROOT / "schemas/api/v1/workflow-start-v2.schema.json"
    packaged = (
        ROOT / "packages/api_contracts/eom_api_contracts/schemas/workflow-start-v2.schema.json"
    )
    assert canonical.read_bytes() == packaged.read_bytes()

    request = _request()
    _validator().validate(request)
    assert WorkflowStartRequest.model_validate(request).item_brief is not None


def test_workflow_start_v2_rejects_v4_without_material_requirement() -> None:
    request = _request()
    item_brief = request["item_brief"]
    assert isinstance(item_brief, dict)
    del item_brief["material_requirement"]

    with pytest.raises(ValidationError):
        _validator().validate(request)


def test_workflow_start_v3_adds_only_verification_review_definition() -> None:
    canonical = ROOT / "schemas/api/v1/workflow-start-v3.schema.json"
    packaged = (
        ROOT / "packages/api_contracts/eom_api_contracts/schemas/workflow-start-v3.schema.json"
    )
    assert canonical.read_bytes() == packaged.read_bytes()
    request = _request()
    request["definition_version"] = "1.13.0"

    with pytest.raises(ValidationError):
        _validator().validate(request)
    _validator_v3().validate(request)
    assert WorkflowStartRequest.model_validate(request).definition_version == "1.13.0"


def test_workflow_start_v2_preserves_v1_bytes_and_accepts_legacy_branch() -> None:
    assert (
        hashlib.sha256(
            (ROOT / "schemas/api/v1/workflow-start-v1.schema.json").read_bytes()
        ).hexdigest()
        == "0123a95c69b02fdb6f3ad877bf824782d25db07dc500ced8935823209a06ba6f"
    )
    legacy = {
        "definition_key": "generic-item-development",
        "definition_version": "1.7.0",
        "image_mode": "required",
    }
    _validator().validate(legacy)
