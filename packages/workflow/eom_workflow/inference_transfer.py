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
from eom_identifiers import canonical_json_bytes, content_sha256
from pydantic import model_validator

from eom_workflow.control_plane import ResolvedExecutionPlan

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
        validate_inference_transfer_worker_request(self)
        return self


def validate_inference_transfer_worker_request(request: InferenceTransferPairWorkerRequest) -> None:
    """Revalidate hashes and bounds even for a copied or recovered frozen input."""

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
) -> ResolvedExecutionPlan:
    """Admit only a purpose-pinned V1 plan; never reuse an unrelated support preset."""

    plan = ResolvedExecutionPlan.model_validate(document)
    if content_sha256(plan.model_dump(mode="json", exclude={"plan_sha256"})) != plan.plan_sha256:
        raise ValueError("inference-transfer execution plan hash differs")
    if (
        plan.workflow_id != workflow_id
        or plan.workflow_definition_key != TRANSFER_PAIR_WORKFLOW_KEY
        or plan.workflow_definition_version != TRANSFER_PAIR_WORKFLOW_VERSION
    ):
        raise ValueError("inference-transfer execution plan purpose differs")
    if len(plan.steps) != 1:
        raise ValueError("inference-transfer execution plan must have one bounded support step")
    step = plan.steps[0]
    if (
        step.step_key != step_key
        or step.role != "support"
        or step.general_knowledge_mode != "DENIED"
    ):
        raise ValueError("inference-transfer execution step differs")
    left_graph = request.left_profile.source_basis.graph_snapshot
    right_graph = request.right_profile.source_basis.graph_snapshot
    if (
        left_graph != right_graph
        or plan.graph_snapshot_revision_id != left_graph.graph_snapshot_revision_id
    ):
        raise ValueError("inference-transfer execution plan Graph pin differs")
    validate_inference_transfer_worker_request(request)
    return plan
