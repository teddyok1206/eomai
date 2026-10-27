"""Creative analysis execution is pinned to source pages and one support pool."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from eom_identifiers import content_sha256
from eom_workflow.control_plane import ResolvedExecutionPlanV27
from eom_workflow.control_schemas import validate_control_contract
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from tests.unit.test_external_item_learning_work_contract import _work

ROOT = Path(__file__).resolve().parents[2]


def _plan() -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "resolved-execution-plan/27.0",
        "plan_id": "execplan_" + "1" * 32,
        "workflow_id": "workflow_" + "2" * 32,
        "workload_class": "KNOWLEDGE_ANALYSIS",
        "preset_id": "execpreset_" + "3" * 32,
        "preset_revision_id": "execpresetrev_" + "4" * 32,
        "preset_sha256": "sha256:" + "5" * 64,
        "workflow_definition_key": "external-item-learning",
        "workflow_definition_version": "1.0.0",
        "workflow_definition_sha256": "sha256:" + "6" * 64,
        "work_input": _work(),
        "capacity_policy_revision_id": "capacityrev_" + "7" * 32,
        "steps": [
            {
                "step_key": "extract",
                "role": "support",
                "model": "gpt-5.6-terra",
                "reasoning_effort": "xhigh",
                "instruction_bundle": {
                    "bundle_id": "instrbundle_" + "8" * 32,
                    "bundle_revision_id": "instrrev_" + "9" * 32,
                    "manifest_artifact": {
                        "artifact_id": "artifact_" + "a" * 32,
                        "artifact_revision_id": "rev_" + "b" * 32,
                        "sha256": "sha256:" + "c" * 64,
                        "schema_ref": "eom://schemas/workflow/bundle-manifest/1.0",
                        "media_type": "application/json",
                        "logical_name": "manifest.json",
                    },
                    "manifest_sha256": "sha256:" + "d" * 64,
                },
                "reference_bundle": None,
                "worker_pool_key": "creative-learning",
                "timeout_seconds": 7200,
                "sandbox": "read-only",
                "network": "disabled",
                "general_knowledge_mode": "DENIED",
            }
        ],
        "resolver_version": "27.0.0",
        "resolved_at": "2026-10-27T11:00:00Z",
    }
    value["plan_sha256"] = content_sha256(value)
    return value


def test_creative_plan_schema_mirror_and_exact_typed_plan() -> None:
    canonical = ROOT / "schemas/workflow/control-plane/resolved-execution-plan-v27.schema.json"
    resource = (
        ROOT
        / "packages/workflow/eom_workflow/resources/control-plane"
        / "resolved-execution-plan-v27.schema.json"
    )
    assert canonical.read_bytes() == resource.read_bytes()
    value = _plan()
    validate_control_contract("resolved-execution-plan-v27", value)
    parsed = ResolvedExecutionPlanV27.model_validate(value)
    assert parsed.work_input.source.external_number == "12345"
    assert parsed.steps[0].worker_pool_key == "creative-learning"


def test_creative_plan_rejects_other_pool_and_changed_source() -> None:
    value = deepcopy(_plan())
    steps = value["steps"]
    assert isinstance(steps, list) and isinstance(steps[0], dict)
    steps[0]["worker_pool_key"] = "legacy-extraction"
    value["plan_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "plan_sha256"}
    )
    with pytest.raises(JsonSchemaValidationError):
        validate_control_contract("resolved-execution-plan-v27", value)
    with pytest.raises(ValidationError, match="isolated support step"):
        ResolvedExecutionPlanV27.model_validate(value)

    value = deepcopy(_plan())
    work = value["work_input"]
    assert isinstance(work, dict)
    work["request_id"] = "extlearnreq_" + "0" * 32
    work["request_sha256"] = content_sha256(
        {key: item for key, item in work.items() if key != "request_sha256"}
    )
    with pytest.raises(ValidationError, match="plan hash differs"):
        ResolvedExecutionPlanV27.model_validate(value)
