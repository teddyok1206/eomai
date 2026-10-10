"""Reviewed-input synthetic examples, not real runtime or release approval."""

from __future__ import annotations

from typing import Any

from eom_identifiers import content_sha256, sha256_bytes
from eom_workflow.inference_transfer_bootstrap_contract import (
    InferenceTransferBootstrapManifest,
)

PLATFORM_BYTES = "# 합성 플랫폼 지침\n원본 출처 권한은 실제 owner가 확인한다.\n".encode()
RUBRIC_BYTES = "# 합성 비교 기준\n기계 가설은 사람의 교육 품질 승인이 아니다.\n".encode()


def bootstrap_manifest(**overrides: Any) -> InferenceTransferBootstrapManifest:
    def member(layer: str, path: str, payload: bytes) -> dict[str, Any]:
        return {
            "layer": layer,
            "relative_path": path,
            "logical_name": path,
            "schema_ref": "eom://schemas/workflow/instruction-member/1.0",
            "media_type": "text/markdown",
            "sha256": sha256_bytes(payload),
            "size_bytes": len(payload),
        }

    body: dict[str, Any] = {
        "schema_version": "inference-transfer-control-bootstrap/1.0",
        "workflow_definition_key": "item-inference-transfer-comparison",
        "workflow_definition_version": "1.0.0",
        "workflow_definition_sha256": "sha256:" + "a" * 64,
        "workflow_role_schema_version": "workflow-role/1.29.0",
        "result_schema": "item-inference-transfer-pair-result@1.0",
        "source": {
            "repository_key": "EOM",
            "source_commit": "a" * 40,
            "source_tree": "b" * 40,
            "reviewed_at": "2026-10-10T09:00:00Z",
        },
        "capacity": {
            "capacity_policy_id": "capacity_" + "c" * 32,
            "capacity_policy_revision_id": "capacityrev_" + "d" * 32,
            "schema_version": "worker-capacity-policy/1.3",
            "content_sha256": "sha256:" + "c" * 64,
        },
        "rubric": {
            "rubric_id": "transferrubric_" + "e" * 32,
            "rubric_revision_id": "transferrubricrev_" + "f" * 32,
            "rubric_sha256": sha256_bytes(RUBRIC_BYTES),
        },
        "platform_instruction": member("PLATFORM", "instructions/platform.md", PLATFORM_BYTES),
        "rubric_instruction": member("ROLE", "instructions/transfer-rubric.md", RUBRIC_BYTES),
        "model_candidate": {"model": "reviewed-candidate-a", "reasoning_effort": "medium"},
        "timeout_seconds": 300,
    } | overrides
    return InferenceTransferBootstrapManifest.model_validate(
        body | {"manifest_sha256": content_sha256(body)}
    )
