"""Bounded inference-transfer worker values; no storage or execution ownership."""

from __future__ import annotations

from typing import Literal

from eom_catalog_contracts.item_inference_transfer import (
    InferenceTransferProfile,
    PairComparisonRequest,
    PairComparisonResult,
    validate_pair_comparison_references,
    validate_pair_comparison_request_references,
)
from eom_catalog_contracts.models import FrozenModel
from eom_identifiers import canonical_json_bytes
from pydantic import model_validator

from eom_workflow.inference_transfer_control import (
    ResolvedExecutionPlanV21,
    validate_inference_transfer_plan_context,
)

TRANSFER_PAIR_PROTOCOL: Literal["workflow-role/1.29.0"] = "workflow-role/1.29.0"
TRANSFER_PAIR_RESULT_SCHEMA = "item-inference-transfer-pair-result@1.0"
TRANSFER_PAIR_WORKFLOW_KEY = "item-inference-transfer-comparison"
TRANSFER_PAIR_WORKFLOW_VERSION = "1.0.0"
MAX_TRANSFER_WORKER_CONTEXT_BYTES = 64 * 1024


class InferenceTransferPairWorkerRequest(FrozenModel):
    request_name: Literal["ITEM_INFERENCE_TRANSFER_PAIR_REQUEST"] = (
        "ITEM_INFERENCE_TRANSFER_PAIR_REQUEST"
    )
    comparison: PairComparisonRequest
    left_profile: InferenceTransferProfile
    right_profile: InferenceTransferProfile

    @model_validator(mode="after")
    def exact_bounded_context(self) -> InferenceTransferPairWorkerRequest:
        _validate_worker_request_references(self)
        return self


def validate_inference_transfer_worker_request(request: InferenceTransferPairWorkerRequest) -> None:
    """Reparse the complete closed schema, including copied Literal fields."""

    InferenceTransferPairWorkerRequest.model_validate(request.model_dump(mode="json"))


def _validate_worker_request_references(request: InferenceTransferPairWorkerRequest) -> None:
    """One reference/size invariant, called after the closed field schema runs."""

    validate_pair_comparison_request_references(
        request.comparison, request.left_profile, request.right_profile
    )
    if len(canonical_json_bytes(request.model_dump(mode="json"))) > (
        MAX_TRANSFER_WORKER_CONTEXT_BYTES
    ):
        raise ValueError("inference-transfer worker context exceeds 64 KiB")


def validate_inference_transfer_worker_result(
    request: InferenceTransferPairWorkerRequest, result: PairComparisonResult
) -> None:
    """Check exact request/profile closure before the Orchestrator commits the envelope."""

    validate_inference_transfer_worker_request(request)
    validate_pair_comparison_references(
        request.comparison, result, request.left_profile, request.right_profile
    )
    if len(canonical_json_bytes(result.model_dump(mode="json"))) > (
        MAX_TRANSFER_WORKER_CONTEXT_BYTES
    ):
        raise ValueError("inference-transfer worker result exceeds 64 KiB")


def validate_inference_transfer_execution_plan(
    document: object,
    *,
    request: InferenceTransferPairWorkerRequest,
    workflow_id: str,
    step_key: str,
    core_prompt_sha256: str,
    prompt_sha256: str,
) -> ResolvedExecutionPlanV21:
    """Admit only V21 with exact source and prompt pins, never a generic Pack plan."""

    if not isinstance(document, dict) or document.get("schema_version") != (
        "resolved-execution-plan/21.0"
    ):
        raise ValueError("inference-transfer requires its dedicated V21 purpose plan")
    if (
        document.get("workflow_definition_key") != TRANSFER_PAIR_WORKFLOW_KEY
        or document.get("workflow_definition_version") != TRANSFER_PAIR_WORKFLOW_VERSION
    ):
        raise ValueError("inference-transfer execution plan purpose differs")
    plan = ResolvedExecutionPlanV21.model_validate(document)
    if plan.steps[0].step_key != step_key:
        raise ValueError("inference-transfer execution step differs")
    validate_inference_transfer_worker_request(request)
    validate_inference_transfer_plan_context(
        plan,
        comparison=request.comparison,
        left_profile=request.left_profile,
        right_profile=request.right_profile,
        workflow_id=workflow_id,
        core_prompt_sha256=core_prompt_sha256,
        prompt_sha256=prompt_sha256,
    )
    return plan
