from __future__ import annotations

import json
from pathlib import Path

import pytest
from eom_api.services.query_adapter import QueryAdapter
from eom_api_contracts.assessment_assemblies import MockExamAssemblyPolicyViewV2
from eom_api_contracts.control_plane import ExecutionPresetDraftRequestV2
from eom_api_contracts.mock_exam_execution import (
    MockExamExplicitRatingSetV1,
    MockExamGraphPublicationInputV1,
)
from eom_identifiers import content_sha256
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]


def _validator(name: str) -> Draft202012Validator:
    value = json.loads((ROOT / "schemas/api/v1" / name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(value)
    return Draft202012Validator(value, format_checker=FormatChecker())


def _role_policy() -> dict[str, object]:
    return {
        "role": "authoring",
        "model_candidates": [{"model": "gpt-5.6-terra", "reasoning_effort": "high"}],
        "instruction_bundle": {
            "bundle_id": "instrbundle_" + "1" * 32,
            "bundle_revision_id": "instrrev_" + "2" * 32,
            "manifest_artifact": {
                "artifact_id": "artifact_" + "3" * 32,
                "artifact_revision_id": "rev_" + "4" * 32,
                "sha256": "sha256:" + "5" * 64,
                "schema_ref": "eom://schemas/workflow/instruction-bundle-manifest/1.0",
                "media_type": "application/json",
                "logical_name": "manifest.json",
            },
            "manifest_sha256": "sha256:" + "6" * 64,
        },
        "reference_bundle": None,
        "worker_pool_key": "authoring",
        "timeout_seconds": 1800,
        "sandbox": "read-only",
        "network": "disabled",
    }


def test_execution_preset_successor_separates_request_and_target_revision_identity() -> None:
    value = {
        "schema_version": "execution-preset-draft-request/1.0",
        "target_revision_schema_version": "execution-preset-revision/1.0",
        "preset_key": "standard-item",
        "display_name": "Standard item",
        "description": "Reviewed execution policy.",
        "role_policies": [_role_policy()],
        "capacity_policy_revision_id": "capacityrev_" + "7" * 32,
        "general_knowledge_policy": "DENY",
        "compatible_workflow_protocols": ["workflow-role/1.20.0"],
    }
    _validator("execution-preset-draft-request-v1.schema.json").validate(value)
    assert (
        ExecutionPresetDraftRequestV2.model_validate(value).target_revision_schema_version
        == "execution-preset-revision/1.0"
    )

    invalid = value | {"schema_version": "execution-preset-revision/1.0"}
    with pytest.raises(JsonSchemaValidationError):
        _validator("execution-preset-draft-request-v1.schema.json").validate(invalid)
    with pytest.raises(ValidationError):
        ExecutionPresetDraftRequestV2.model_validate(invalid)


def test_mock_exam_policy_projection_has_a_distinct_successor_identity() -> None:
    value = {
        "schema_version": "mock-exam-assembly-policy-view/1.0",
        "policy_key": "integrated-science",
        "policy_revision_id": "assemblypolicyrev_" + "1" * 32,
        "policy_sha256": "sha256:" + "2" * 64,
        "subject_key": "integrated-science",
        "item_count": 25,
        "total_points_milli": 50000,
        "score_distribution": [{"points_milli": 2000, "count": 25}],
        "required_slot_count": 20,
        "balance_slot_count": 5,
        "inquiry_min_count": 4,
        "inquiry_max_count": 8,
        "coverage_requirements": [
            {
                "requirement_id": "matter",
                "selection_count": 1,
                "distinct_units": True,
                "allowed_unit_keys": ["eom.is.middle.1-1"],
            }
        ],
        "eligible_item_revision_states": ["APPROVED"],
        "outline_key": "integrated-science",
        "outline_revision": "2022",
        "outline_sha256": "sha256:" + "3" * 64,
        "guidance_revision": 1,
        "guidance_reviewed_document_sha256": "sha256:" + "4" * 64,
        "guidance_original_sha256": "sha256:" + "5" * 64,
    }
    _validator("mock-exam-assembly-policy-view-v1.schema.json").validate(value)
    assert MockExamAssemblyPolicyViewV2.model_validate(value).item_count == 25


def test_mock_exam_policy_keeps_the_legacy_endpoint_projection_separate() -> None:
    legacy = QueryAdapter.mock_exam_assembly_policy()
    successor = QueryAdapter.mock_exam_assembly_policy_view()

    assert legacy.schema_version == "mock-exam-assembly-policy/1.0"
    assert successor.schema_version == "mock-exam-assembly-policy-view/1.0"
    assert successor.policy_revision_id == legacy.policy_revision_id
    assert successor.policy_sha256 == legacy.policy_sha256
    _validator("mock-exam-assembly-policy-view-v1.schema.json").validate(
        successor.model_dump(mode="json")
    )


def test_operator_rating_and_graph_inputs_match_json_schema_then_pydantic() -> None:
    rating = {
        "schema_version": "mock-exam-explicit-rating-set/1.0",
        "execution_id": "productionexec_" + "1" * 32,
        "operator_id": "operator_" + "2" * 32,
        "assignments": [
            {
                "workflow_call_id": f"workflowcall_{position:032x}",
                "position": position,
                "item_revision_id": f"itemrev_{position + 100:032x}",
                "final_rating": "A",
            }
            for position in range(1, 26)
        ],
        "authorized_at": "2026-10-01T00:00:00Z",
    }
    rating["decision_set_sha256"] = content_sha256(rating)
    _validator("mock-exam-explicit-rating-set-v1.schema.json").validate(rating)
    MockExamExplicitRatingSetV1.model_validate(rating)

    graph = {
        "current_graph_snapshot_revision_id": "graphrev_" + "3" * 32,
        "current_graph_snapshot_sha256": "sha256:" + "4" * 64,
        "access_policy_revision_id": "accessrev_" + "5" * 32,
        "access_policy_sha256": "sha256:" + "6" * 64,
        "authorized_at": "2026-10-01T00:00:00Z",
        "supersedes_authorization_sha256": None,
    }
    graph["authorization_sha256"] = content_sha256(graph)
    _validator("mock-exam-graph-publication-input-v1.schema.json").validate(graph)
    MockExamGraphPublicationInputV1.model_validate(graph)

    with pytest.raises(JsonSchemaValidationError):
        _validator("mock-exam-explicit-rating-set-v1.schema.json").validate(
            rating | {"assignments": rating["assignments"][:-1]}
        )
