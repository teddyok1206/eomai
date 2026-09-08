from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from eom_api.errors import ApiError
from eom_api.routers.workflows import start_workflow
from eom_api_contracts.workflows import (
    WorkflowAcceptedResolutionView,
    WorkflowStartRequest,
)
from eom_identity_service.tokens import AccessAuthentication
from fastapi import Request
from jsonschema import Draft202012Validator
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]


def _resolution() -> dict[str, object]:
    return {
        "schema_version": "workflow-expected-resolution/1.0",
        "workflow_definition_key": "generic-item-development",
        "workflow_definition_version": "1.8.0",
        "workflow_definition_sha256": "sha256:" + "1" * 64,
        "content_pack_release_id": "packrel_" + "2" * 32,
        "content_pack_key": "generated-knowledge-item",
        "content_pack_version": "1.13.0",
        "content_pack_bundle_sha256": "sha256:" + "3" * 64,
        "content_pack_source_tree_sha256": "sha256:" + "4" * 64,
        "execution_preset_id": "execpreset_" + "5" * 32,
        "execution_preset_revision_id": "execpresetrev_" + "6" * 32,
        "execution_preset_key": "knowledge-grounded-item",
        "execution_preset_content_sha256": "sha256:" + "7" * 64,
    }


def _request() -> dict[str, object]:
    return {
        "definition_key": "generic-item-development",
        "definition_version": "1.8.0",
        "request_name": "GENERATED_KNOWLEDGE_ITEM_REQUEST",
        "image_mode": "required",
        "pack_key": "generated-knowledge-item",
        "execution_preset_key": "knowledge-grounded-item",
        "item_brief": {
            "subject": "통합과학",
            "topic": "생태계 평형",
            "task_type": "data_interpretation",
            "difficulty": "hard",
            "quality_profile": "deep",
            "original_request_sha256": "8" * 64,
        },
        "educational_retrieval": {
            "corpus_key": "science-core",
            "query_kind": "ITEM_PREPARATION",
            "curriculum_root_key": "ecology.balance",
            "topic_keys": [],
            "required_item_elements": ["choice", "paragraph"],
            "source_classes": ["APPROVED_ITEM", "TEXTBOOK"],
        },
        "production_occurrence": {
            "production_request_id": "productionreq_" + "9" * 32,
            "workflow_call_id": "workflowcall_" + "a" * 32,
        },
        "expected_resolution": _resolution(),
    }


def test_workflow_start_schema_is_draft_2020_12_and_packaged_byte_exact() -> None:
    canonical = ROOT / "schemas/api/v1/workflow-start-v1.schema.json"
    packaged = (
        ROOT / "packages/api_contracts/eom_api_contracts/schemas/workflow-start-v1.schema.json"
    )

    assert canonical.read_bytes() == packaged.read_bytes()
    Draft202012Validator.check_schema(json.loads(canonical.read_text(encoding="utf-8")))


def test_workflow_start_accepts_one_closed_exact_resolution_and_occurrence() -> None:
    request = WorkflowStartRequest.model_validate(_request())

    assert request.production_occurrence is not None
    assert request.expected_resolution is not None
    assert request.expected_resolution.content_pack_release_id == "packrel_" + "2" * 32
    assert WorkflowAcceptedResolutionView.model_validate(
        request.expected_resolution.model_dump(mode="json")
    ).model_dump(mode="json") == request.expected_resolution.model_dump(mode="json")
    with pytest.raises(ValidationError):
        WorkflowStartRequest.model_validate(
            _request()
            | {
                "expected_resolution": {
                    **_resolution(),
                    "latest": True,
                }
            }
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("definition_version", "1.7.0"),
        ("pack_key", "another-pack"),
        ("execution_preset_key", "another-preset"),
    ],
)
def test_workflow_start_rejects_selection_that_differs_from_expected_resolution(
    field: str, value: str
) -> None:
    with pytest.raises(ValidationError, match="expected resolution"):
        WorkflowStartRequest.model_validate(_request() | {field: value})


def test_workflow_start_rejects_partial_production_identity() -> None:
    with pytest.raises(ValidationError, match="supplied together"):
        WorkflowStartRequest.model_validate(_request() | {"production_occurrence": None})


def test_public_workflow_start_rejects_internal_production_occurrence() -> None:
    request = WorkflowStartRequest.model_validate(_request())

    with pytest.raises(ApiError) as raised:
        start_workflow(
            cast(Request, None),
            request,
            cast(AccessAuthentication, None),
            "public-production-occurrence-0001",
        )

    assert raised.value.status == 403
    assert raised.value.error_code == "WORKFLOW_PRODUCTION_OCCURRENCE_INTERNAL_ONLY"
