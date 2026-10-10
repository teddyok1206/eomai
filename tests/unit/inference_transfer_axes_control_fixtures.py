"""Synthetic successor control values, not live authority or evaluation."""

from __future__ import annotations

from typing import Any

from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_workflow.inference_transfer_bootstrap_contract import InferenceTransferBootstrapManifestV11
from eom_workflow.inference_transfer_control_invocation import (
    InferenceTransferControlReleaseRequestV11,
    InferenceTransferControlReleaseResultV11,
    InferenceTransferPreparedReceiptV11,
)
from eom_workflow.inference_transfer_workflow import InferenceTransferWorkflowRequestV11

from tests.unit.inference_transfer_bootstrap_fixtures import bootstrap_manifest
from tests.unit.inference_transfer_control_invocation_fixtures import prepared_receipt
from tests.unit.inference_transfer_workflow_fixtures import workflow_request


def rehash(body: dict[str, Any], field: str) -> dict[str, Any]:
    body = {key: value for key, value in body.items() if key != field}
    return body | {field: content_sha256(body)}


def bootstrap_manifest_v11(**overrides: Any) -> InferenceTransferBootstrapManifestV11:
    body = (
        bootstrap_manifest().model_dump(mode="json")
        | {
            "schema_version": "inference-transfer-control-bootstrap/1.1",
            "workflow_definition_version": "1.1.0",
            "workflow_role_schema_version": "workflow-role/1.30.0",
            "result_schema": "item-inference-transfer-pair-result@1.1",
        }
        | overrides
    )
    return InferenceTransferBootstrapManifestV11.model_validate(rehash(body, "manifest_sha256"))


def prepared_receipt_v11() -> InferenceTransferPreparedReceiptV11:
    manifest = bootstrap_manifest_v11()
    body = prepared_receipt().model_dump(mode="json")
    body["schema_version"] = "inference-transfer-prepared-receipt/1.1"
    body["manifest"] = manifest.model_dump(mode="json")
    body["bootstrap_artifact"]["schema_ref"] = (
        "eom://schemas/workflow/inference-transfer-control-bootstrap/1.1"
    )
    body["bootstrap_artifact"]["sha256"] = sha256_bytes(
        canonical_json_bytes(body["manifest"]) + b"\n"
    )
    body["draft"]["compatible_workflow_protocols"] = ["workflow-role/1.30.0"]
    body["draft"] = rehash(body["draft"], "content_sha256")
    return InferenceTransferPreparedReceiptV11.model_validate(rehash(body, "receipt_sha256"))


def release_request_v11(
    receipt: InferenceTransferPreparedReceiptV11 | None = None,
) -> InferenceTransferControlReleaseRequestV11:
    body = {
        "schema_version": "inference-transfer-control-release-request/1.1",
        "receipt": (receipt or prepared_receipt_v11()).model_dump(mode="json"),
    }
    return InferenceTransferControlReleaseRequestV11.model_validate(rehash(body, "request_sha256"))


def release_result_v11(
    request: InferenceTransferControlReleaseRequestV11 | None = None,
) -> InferenceTransferControlReleaseResultV11:
    request = request or release_request_v11()
    body = {
        "schema_version": "inference-transfer-control-release-result/1.1",
        "prepared_receipt_sha256": request.receipt.receipt_sha256,
        "preset": rehash(
            request.receipt.draft.model_dump(mode="json")
            | {
                "preset_revision_id": "execpresetrev_" + "1" * 32,
                "revision_number": 2,
                "state": "RELEASED",
                "created_at": "2026-10-10T10:00:00Z",
            },
            "content_sha256",
        ),
        "evaluation_id": "preseteval_" + "2" * 32,
        "evaluation_artifact": {
            "artifact_id": "artifact_" + "3" * 32,
            "artifact_revision_id": "rev_" + "4" * 32,
            "sha256": content_sha256("synthetic successor technical report"),
            "schema_ref": "eom://schemas/workflow/execution-preset-evaluation-report/1.0",
            "media_type": "application/json",
            "logical_name": "inference-transfer-preset-evaluation.json",
        },
        "executed_cases": ["REVIEWED_BOOTSTRAP_SCHEMA", "support:0:MODEL_PIN"],
        "quality_score_permille": None,
        "scientific_evaluation": "NOT_EVALUATED",
        "human_transfer_evaluation": "NOT_EVALUATED",
    }
    return InferenceTransferControlReleaseResultV11.model_validate(rehash(body, "result_sha256"))


def workflow_request_v11() -> InferenceTransferWorkflowRequestV11:
    body = workflow_request().model_dump(mode="json") | {
        "schema_version": "inference-transfer-workflow-request/1.1",
        "request_name": "ITEM_INFERENCE_TRANSFER_PAIR_REQUEST_V11",
        "execution_preset_key": "item-inference-transfer-comparison-axes",
    }
    return InferenceTransferWorkflowRequestV11.model_validate(rehash(body, "request_sha256"))
