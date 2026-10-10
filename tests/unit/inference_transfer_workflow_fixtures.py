"""Synthetic application admission values, not authenticated or accepted production data."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from eom_identifiers import content_sha256
from eom_workflow import compile_definition
from eom_workflow.inference_transfer_workflow import InferenceTransferWorkflowRequest
from eom_workflow_runner.inference_transfer_admission import InferenceTransferSubmissionContext
from eom_workflow_runner.models import WorkflowDefinitionRecord

from tests.unit.inference_transfer_fixtures import profile, request, sha

OPERATOR_ID = "operator_" + "1" * 32
OTHER_OPERATOR_ID = "operator_" + "2" * 32


def workflow_request(*, request_id: str | None = None) -> InferenceTransferWorkflowRequest:
    left, right = profile("a"), profile("b")
    comparison = request(left, right)
    if request_id is not None:
        comparison_body = comparison.model_dump(mode="json", exclude={"request_sha256"})
        comparison_body["request_id"] = request_id
        comparison = type(comparison).model_validate(
            comparison_body | {"request_sha256": content_sha256(comparison_body)}
        )
    body: dict[str, Any] = {
        "schema_version": "inference-transfer-workflow-request/1.0",
        "request_name": "ITEM_INFERENCE_TRANSFER_PAIR_REQUEST",
        "execution_preset_key": "item-inference-transfer-comparison",
        "comparison": comparison.model_dump(mode="json"),
        "left_profile": left.model_dump(mode="json"),
        "right_profile": right.model_dump(mode="json"),
        "access_policy_revision_id": "accessrev_" + "3" * 32,
        "access_policy_sha256": sha("3"),
        "requester_permissions_sha256": sha("4"),
    }
    return InferenceTransferWorkflowRequest.model_validate(
        body | {"request_sha256": content_sha256(body)}
    )


def submission_context(operator_id: str = OPERATOR_ID) -> InferenceTransferSubmissionContext:
    return InferenceTransferSubmissionContext(
        operator_id=operator_id,
        requester_permissions_sha256=sha("4"),
    )


def definition() -> WorkflowDefinitionRecord:
    compiled = compile_definition(
        Path("config/workflows/item-inference-transfer-comparison.v1.yaml"), {"support"}
    )
    return WorkflowDefinitionRecord(
        definition_id="wfdef_" + "1" * 32,
        definition_key=compiled.definition.definition_key,
        definition_version=compiled.definition.definition_version,
        schema_version=compiled.definition.schema_version,
        canonical_definition=compiled.as_dict(),
        definition_hash=compiled.sha256,
        active=True,
        source_path=compiled.source_path,
    )
