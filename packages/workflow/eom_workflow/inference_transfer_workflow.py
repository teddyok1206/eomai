"""Bounded application comparison request, distinct from worker execution input."""

from __future__ import annotations

from typing import Literal

from eom_catalog_contracts.item_inference_transfer import (
    InferenceTransferProfile,
    PairComparisonRequest,
)
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_identifiers import canonical_json_bytes, content_sha256
from pydantic import Field, model_validator

from eom_workflow.inference_transfer import (
    MAX_TRANSFER_WORKER_CONTEXT_BYTES,
    InferenceTransferPairWorkerRequest,
    InferenceTransferPairWorkerRequestV11,
)


class InferenceTransferWorkflowRequest(FrozenModel):
    """Exact pair and initial audit pins, never actor or source-access authority."""

    schema_version: Literal["inference-transfer-workflow-request/1.0"] = (
        "inference-transfer-workflow-request/1.0"
    )
    request_name: Literal["ITEM_INFERENCE_TRANSFER_PAIR_REQUEST"] = (
        "ITEM_INFERENCE_TRANSFER_PAIR_REQUEST"
    )
    execution_preset_key: Literal["item-inference-transfer-comparison"] = (
        "item-inference-transfer-comparison"
    )
    comparison: PairComparisonRequest
    left_profile: InferenceTransferProfile
    right_profile: InferenceTransferProfile
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    access_policy_sha256: Sha256
    requester_permissions_sha256: Sha256
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_bounded_context_and_hash(self) -> InferenceTransferWorkflowRequest:
        # Reparse nested values as well: frozen model_copy does not run validators.
        self.worker_request()
        if self.left_profile.source_basis.graph_snapshot != (
            self.right_profile.source_basis.graph_snapshot
        ):
            raise ValueError("inference-transfer Workflow profiles require one exact Graph pin")
        document = self.model_dump(mode="json")
        if len(canonical_json_bytes(document)) > MAX_TRANSFER_WORKER_CONTEXT_BYTES:
            raise ValueError("inference-transfer Workflow context exceeds 64 KiB")
        if content_sha256(self.model_dump(mode="json", exclude={"request_sha256"})) != (
            self.request_sha256
        ):
            raise ValueError("inference-transfer Workflow request hash differs")
        return self

    def worker_request(self) -> InferenceTransferPairWorkerRequest:
        """Materialize only the bounded worker value; audit pins grant no access."""

        return InferenceTransferPairWorkerRequest.model_validate(
            {
                "request_name": self.request_name,
                "comparison": self.comparison.model_dump(mode="json"),
                "left_profile": self.left_profile.model_dump(mode="json"),
                "right_profile": self.right_profile.model_dump(mode="json"),
            }
        )


class InferenceTransferWorkflowRequestV11(InferenceTransferWorkflowRequest):
    """Choose new meaning explicitly, without silently upgrading a saved request."""

    schema_version: Literal["inference-transfer-workflow-request/1.1"] = (
        "inference-transfer-workflow-request/1.1"  # type: ignore[assignment]
    )
    request_name: Literal["ITEM_INFERENCE_TRANSFER_PAIR_REQUEST_V11"] = (
        "ITEM_INFERENCE_TRANSFER_PAIR_REQUEST_V11"  # type: ignore[assignment]
    )
    execution_preset_key: Literal["item-inference-transfer-comparison-axes"] = (
        "item-inference-transfer-comparison-axes"  # type: ignore[assignment]
    )

    def worker_request(self) -> InferenceTransferPairWorkerRequestV11:
        return InferenceTransferPairWorkerRequestV11.model_validate(
            {
                "request_name": self.request_name,
                "comparison": self.comparison.model_dump(mode="json"),
                "left_profile": self.left_profile.model_dump(mode="json"),
                "right_profile": self.right_profile.model_dump(mode="json"),
            }
        )
