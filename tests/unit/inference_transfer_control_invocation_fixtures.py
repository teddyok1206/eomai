"""Synthetic preparation/release metadata, never real publication or authority."""

from __future__ import annotations

from typing import Any

from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_workflow.inference_transfer_control_invocation import (
    InferenceTransferControlReleaseRequest,
    InferenceTransferControlReleaseResult,
    InferenceTransferPreparedReceipt,
)

from tests.unit.inference_transfer_bootstrap_fixtures import bootstrap_manifest


def rehash(value: dict[str, Any], field: str) -> dict[str, Any]:
    body = {key: child for key, child in value.items() if key != field}
    return body | {field: content_sha256(body)}


def prepared_receipt() -> InferenceTransferPreparedReceipt:
    manifest = bootstrap_manifest()
    bootstrap = {
        "artifact_id": "artifact_" + "a" * 32,
        "artifact_revision_id": "rev_" + "b" * 32,
        "sha256": sha256_bytes(canonical_json_bytes(manifest.model_dump(mode="json")) + b"\n"),
        "schema_ref": "eom://schemas/workflow/inference-transfer-control-bootstrap/1.0",
        "media_type": "application/json",
        "logical_name": "inference-transfer-bootstrap.json",
    }
    bundle = {
        "bundle_id": "instrbundle_" + "c" * 32,
        "bundle_revision_id": "instrrev_" + "d" * 32,
        "manifest_sha256": content_sha256("synthetic published instruction bundle"),
        "manifest_artifact": bootstrap
        | {
            "artifact_id": "artifact_" + "c" * 32,
            "artifact_revision_id": "rev_" + "d" * 32,
            "sha256": content_sha256("synthetic published instruction bundle"),
            "schema_ref": "eom://schemas/workflow/instruction-bundle-manifest/1.0",
            "logical_name": "instruction-bundle.json",
        },
    }
    draft = rehash(
        {
            "schema_version": "execution-preset-revision/1.0",
            "preset_id": "execpreset_" + "e" * 32,
            "preset_revision_id": "execpresetrev_" + "f" * 32,
            "revision_number": 1,
            "state": "DRAFT",
            "display_name": "Synthetic inference transfer",
            "description": "Synthetic prepared policy is not actual release evidence.",
            "role_policies": [
                {
                    "role": "support",
                    "model_candidates": [manifest.model_candidate.model_dump(mode="json")],
                    "instruction_bundle": bundle,
                    "reference_bundle": None,
                    "worker_pool_key": "customer-support",
                    "timeout_seconds": manifest.timeout_seconds,
                    "sandbox": "read-only",
                    "network": "disabled",
                }
            ],
            "capacity_policy_revision_id": manifest.capacity.capacity_policy_revision_id,
            "general_knowledge_policy": "DENY",
            "compatible_workflow_protocols": [manifest.workflow_role_schema_version],
            "created_at": "2026-10-10T09:00:00Z",
        },
        "content_sha256",
    )
    body = {
        "schema_version": "inference-transfer-prepared-receipt/1.0",
        "manifest": manifest.model_dump(mode="json"),
        "bootstrap_artifact": bootstrap,
        "instruction_bundle": bundle,
        "draft": draft,
    }
    return InferenceTransferPreparedReceipt.model_validate(rehash(body, "receipt_sha256"))


def release_request(
    receipt: InferenceTransferPreparedReceipt | None = None,
) -> InferenceTransferControlReleaseRequest:
    body = {
        "schema_version": "inference-transfer-control-release-request/1.0",
        "receipt": (receipt or prepared_receipt()).model_dump(mode="json"),
    }
    return InferenceTransferControlReleaseRequest.model_validate(rehash(body, "request_sha256"))


def release_result(
    request: InferenceTransferControlReleaseRequest | None = None,
) -> InferenceTransferControlReleaseResult:
    request = request or release_request()
    preset = rehash(
        request.receipt.draft.model_dump(mode="json")
        | {
            "preset_revision_id": "execpresetrev_" + "1" * 32,
            "revision_number": 2,
            "state": "RELEASED",
            "created_at": "2026-10-10T10:00:00Z",
        },
        "content_sha256",
    )
    body = {
        "schema_version": "inference-transfer-control-release-result/1.0",
        "prepared_receipt_sha256": request.receipt.receipt_sha256,
        "preset": preset,
        "evaluation_id": "preseteval_" + "2" * 32,
        "evaluation_artifact": {
            "artifact_id": "artifact_" + "3" * 32,
            "artifact_revision_id": "rev_" + "4" * 32,
            "sha256": content_sha256("synthetic technical report"),
            "schema_ref": "eom://schemas/workflow/execution-preset-evaluation-report/1.0",
            "media_type": "application/json",
            "logical_name": "inference-transfer-preset-evaluation.json",
        },
        "executed_cases": ["REVIEWED_BOOTSTRAP_SCHEMA", "support:0:MODEL_PIN"],
        "quality_score_permille": None,
        "scientific_evaluation": "NOT_EVALUATED",
        "human_transfer_evaluation": "NOT_EVALUATED",
    }
    return InferenceTransferControlReleaseResult.model_validate(rehash(body, "result_sha256"))
