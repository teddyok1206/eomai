"""Pure synthetic execution pins, not published presets or authorized exam evidence."""

from __future__ import annotations

from typing import Any

from eom_catalog_contracts.item_inference_transfer import PairComparisonRequest
from eom_identifiers import content_sha256
from eom_workflow.control_plane import InstructionBundleManifest
from eom_workflow.inference_transfer_control import ResolvedExecutionPlanV21

from tests.unit.inference_transfer_fixtures import NOW, request, sha, source_basis


def rubric_artifact(query: PairComparisonRequest) -> dict[str, str]:
    return {
        "artifact_id": "artifact_" + "4" * 32,
        "artifact_revision_id": "rev_" + "4" * 32,
        "sha256": query.rubric.rubric_sha256,
        "schema_ref": "eom://schemas/workflow/instruction-member/1.0",
        "media_type": "text/markdown",
        "logical_name": "instructions/transfer-rubric.md",
    }


def transfer_instruction(query: PairComparisonRequest | None = None) -> InstructionBundleManifest:
    query = query or request()
    platform = rubric_artifact(query) | {
        "artifact_id": "artifact_" + "5" * 32,
        "artifact_revision_id": "rev_" + "5" * 32,
        "sha256": sha("5"),
        "logical_name": "instructions/platform.md",
    }
    value: dict[str, Any] = {
        "schema_version": "instruction-bundle-manifest/1.0",
        "bundle_id": "instrbundle_" + "1" * 32,
        "bundle_revision_id": "instrrev_" + "1" * 32,
        "revision_number": 1,
        "state": "RELEASED",
        "components": [
            {
                "layer": "PLATFORM",
                "relative_path": "instructions/platform.md",
                "artifact": platform,
            },
            {
                "layer": "ROLE",
                "relative_path": "instructions/transfer-rubric.md",
                "artifact": rubric_artifact(query),
            },
        ],
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    value["content_sha256"] = content_sha256(value)
    return InstructionBundleManifest.model_validate(value)


def transfer_plan(
    query: PairComparisonRequest | None = None, *, prompt_sha256: str | None = None
) -> ResolvedExecutionPlanV21:
    query = query or request()
    instruction = transfer_instruction(query)
    instruction_sha = content_sha256(instruction.model_dump(mode="json"))
    value: dict[str, Any] = {
        "schema_version": "resolved-execution-plan/21.0",
        "plan_id": "execplan_" + "1" * 32,
        "workflow_id": "workflow_" + "1" * 32,
        "workload_class": "CODEX",
        "preset_id": "execpreset_" + "1" * 32,
        "preset_revision_id": "execpresetrev_" + "1" * 32,
        "preset_sha256": sha("1"),
        "workflow_definition_key": "item-inference-transfer-comparison",
        "workflow_definition_version": "1.0.0",
        "workflow_definition_sha256": sha("2"),
        "comparison_request_sha256": query.request_sha256,
        "left_profile": query.left_profile.model_dump(mode="json"),
        "right_profile": query.right_profile.model_dump(mode="json"),
        "graph_snapshot": source_basis().graph_snapshot.model_dump(mode="json"),
        "access_policy_revision_id": "accessrev_" + "1" * 32,
        "access_policy_sha256": sha("3"),
        "requester_permissions_sha256": sha("4"),
        "rubric": query.rubric.model_dump(mode="json"),
        "rubric_artifact": rubric_artifact(query),
        "core_prompt_sha256": sha("5"),
        "prompt_sha256": prompt_sha256 or sha("6"),
        "capacity_policy_revision_id": "capacityrev_" + "1" * 32,
        "steps": [
            {
                "step_key": "compare_pair",
                "role": "support",
                "model": "gpt-6.1-sol",
                "reasoning_effort": "high",
                "instruction_bundle": {
                    "bundle_id": instruction.bundle_id,
                    "bundle_revision_id": instruction.bundle_revision_id,
                    "manifest_artifact": {
                        "artifact_id": "artifact_" + "1" * 32,
                        "artifact_revision_id": "rev_" + "1" * 32,
                        "sha256": instruction_sha,
                        "schema_ref": "eom://schemas/workflow/instruction-bundle-manifest/1.0",
                        "media_type": "application/json",
                        "logical_name": "manifest.json",
                    },
                    "manifest_sha256": instruction_sha,
                },
                "reference_bundle": None,
                "worker_pool_key": "customer-support",
                "timeout_seconds": 900,
                "sandbox": "read-only",
                "network": "disabled",
                "general_knowledge_mode": "DENIED",
            }
        ],
        "resolver_version": "21.0.0",
        "resolved_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    value["plan_sha256"] = content_sha256(value)
    return ResolvedExecutionPlanV21.model_validate(value)
