from __future__ import annotations

import json
from pathlib import Path

import pytest
from eom_api_contracts.auth import LoginRequest
from eom_api_contracts.common import ArtifactPointer
from eom_api_contracts.knowledge_analysis import (
    CreateKnowledgeAnalysisRequest,
    KnowledgeAnalysisReviewRequest,
)
from eom_api_contracts.operators import CreateOperatorRequest
from eom_api_contracts.workflows import WorkflowStartRequest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas" / "api" / "v1"


def test_api_json_schemas_are_draft_2020_12() -> None:
    schemas = sorted(SCHEMA_ROOT.glob("*.schema.json"))
    assert schemas
    for path in schemas:
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        Draft202012Validator.check_schema(document)


def test_request_contracts_forbid_unknown_fields_and_redact_secrets() -> None:
    login = LoginRequest(
        username="admin",
        password="TEST_ONLY valid password 42",
        client_name="contract-test",
    )
    assert "TEST_ONLY valid password 42" not in repr(login)
    with pytest.raises(ValidationError):
        LoginRequest.model_validate(
            {
                "username": "admin",
                "password": "TEST_ONLY valid password 42",
                "client_name": "contract-test",
                "unknown": True,
            }
        )


def test_operator_contract_never_serializes_temporary_password() -> None:
    request = CreateOperatorRequest(
        username="review01",
        display_name="검토자",
        temporary_password="TEST_ONLY temporary password 42",
        initial_roles=("REVIEWER",),
    )
    assert "TEST_ONLY temporary password 42" not in request.model_dump_json()


def test_pack_pinned_workflow_requires_valid_source_intake_pointer() -> None:
    base = {
        "definition_key": "generic-item-development",
        "definition_version": "1.1.0",
        "request_name": "PLACEHOLDER_REQUEST",
        "image_mode": "skip",
        "pack_key": "generic-placeholder",
    }
    with pytest.raises(ValidationError, match="source intake batch"):
        WorkflowStartRequest.model_validate({**base, "source_intake_batch_ids": []})
    with pytest.raises(ValidationError):
        WorkflowStartRequest.model_validate({**base, "source_intake_batch_ids": ["not-an-intake"]})
    value = WorkflowStartRequest.model_validate(
        {**base, "source_intake_batch_ids": ["intake_" + "0" * 32]}
    )
    assert value.source_intake_batch_ids == ("intake_" + "0" * 32,)


def test_knowledge_item_workflow_is_source_optional_but_template_constrained() -> None:
    request = {
        "definition_key": "generic-item-development",
        "definition_version": "1.2.0",
        "request_name": "KNOWLEDGE_ITEM_REQUEST",
        "image_mode": "required",
        "pack_key": "general-knowledge-item",
        "source_intake_batch_ids": [],
        "item_brief": {
            "subject": "일반 과학",
            "topic": "변인 사이의 선형 관계",
            "task_type": "data_interpretation",
            "difficulty": "medium",
            "choice_count": 5,
            "equation_required": True,
            "image_required": True,
            "quality_profile": "balanced",
            "original_request_sha256": "0" * 64,
        },
        "stimulus_asset_key": "eom-question-template-reference-v1",
    }
    parsed = WorkflowStartRequest.model_validate(request)
    assert parsed.source_intake_batch_ids == ()
    assert parsed.item_brief is not None and parsed.item_brief.choice_count == 5
    with pytest.raises(ValidationError, match="fixed workflow contract"):
        WorkflowStartRequest.model_validate(request | {"image_mode": "skip"})


@pytest.mark.parametrize("definition_version", ["1.3.0", "1.4.0"])
def test_generated_item_workflow_requires_image_role_without_a_prebuilt_stimulus(
    definition_version: str,
) -> None:
    request = {
        "definition_key": "generic-item-development",
        "definition_version": definition_version,
        "request_name": "GENERATED_KNOWLEDGE_ITEM_REQUEST",
        "image_mode": "required",
        "pack_key": "generated-knowledge-item",
        "source_intake_batch_ids": [],
        "item_brief": {
            "subject": "일반 과학",
            "topic": "변인 사이의 선형 관계",
            "task_type": "data_interpretation",
            "difficulty": "medium",
            "choice_count": 5,
            "equation_required": True,
            "image_required": True,
            "quality_profile": "balanced",
            "original_request_sha256": "0" * 64,
        },
        "stimulus_asset_key": None,
    }
    parsed = WorkflowStartRequest.model_validate(request)
    assert parsed.pack_key == "generated-knowledge-item"
    assert parsed.stimulus_asset_key is None
    with pytest.raises(ValidationError, match="generated item request"):
        WorkflowStartRequest.model_validate(
            request | {"source_intake_batch_ids": ["intake_" + "1" * 32]}
        )
    with pytest.raises(ValidationError, match="generated item request"):
        WorkflowStartRequest.model_validate(
            request | {"stimulus_asset_key": "eom-question-template-reference-v1"}
        )


def test_artifact_pointer_can_pin_one_safe_member_without_exposing_storage_path() -> None:
    pointer = ArtifactPointer(
        artifact_id="artifact_" + "1" * 32,
        artifact_revision_id="rev_" + "2" * 32,
        artifact_member="source/diagram.png",
        sha256="sha256:" + "3" * 64,
        schema_ref="urn:eom:schema:content-intake-source:1.0",
        media_type="image/png",
        logical_uri="nas://artifacts/artifact_1/rev_2",
    )
    assert pointer.artifact_member == "source/diagram.png"
    with pytest.raises(ValidationError, match="artifact member"):
        ArtifactPointer.model_validate(pointer.model_dump() | {"artifact_member": "../diagram.png"})


def test_knowledge_analysis_request_is_discriminated_and_retry_is_explicit() -> None:
    request: CreateKnowledgeAnalysisRequest = CreateKnowledgeAnalysisRequest.model_validate(
        {
            "source": {
                "source_kind": "APPROVED_ITEM_REVISION",
                "source_class": "APPROVED_ITEM",
                "item_revision_id": "itemrev_" + "1" * 32,
            },
            "preset_key": "knowledge-analysis",
            "general_knowledge_mode": "DISABLED",
            "risk_policy_revision_id": "analysisriskrev_" + "2" * 32,
            "predecessor_analysis_run_id": "analysisrun_" + "3" * 32,
        }
    )
    assert request.source.source_kind == "APPROVED_ITEM_REVISION"
    assert request.predecessor_analysis_run_id == "analysisrun_" + "3" * 32
    with pytest.raises(ValidationError):
        CreateKnowledgeAnalysisRequest.model_validate(
            request.model_dump(mode="json")
            | {
                "source": {
                    "source_kind": "APPROVED_ITEM_REVISION",
                    "source_class": "TEXTBOOK",
                    "item_revision_id": "itemrev_" + "1" * 32,
                }
            }
        )


def test_knowledge_analysis_review_rejects_unsafe_or_empty_notes() -> None:
    assert KnowledgeAnalysisReviewRequest(decision="APPROVE", notes="Reviewed.").decision == (
        "APPROVE"
    )
    for notes in ("", "unsafe\x00note"):
        with pytest.raises(ValidationError):
            KnowledgeAnalysisReviewRequest(decision="REJECT", notes=notes)
