"""Bounded selected-pair values; public hashes never grant source authority.

The API captures the principal and permission provenance separately. A read result
is a current owner response, not a reusable permission token. Its Artifact member
hash pins the outer workflow-role/1.29 envelope, not the inner comparison hash.
"""

from __future__ import annotations

from typing import Annotated, Literal

from eom_identifiers import canonical_json_bytes, content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import Field, model_validator

from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotPrepareRequest,
)
from eom_catalog_contracts.item_inference_transfer import (
    InferenceTransferDifference,
    InferenceTransferMapping,
    PairComparisonRequest,
    PairComparisonResult,
)
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.validation import validate_contract

MAX_TRANSFER_SUBMISSION_BYTES = 32 * 1024
MAX_TRANSFER_WORKFLOW_READ_BYTES = 128 * 1024
TRANSFER_RESULT_MEMBER_SCHEMA = (
    "https://eom.local/schemas/workflow/roles/item-inference-transfer-pair-result-v1.schema.json"
)
type TransferWorkflowId = Annotated[str, Field(pattern=r"^workflow_[0-9a-f]{32}$")]
type InferenceTransferWorkflowReadMode = Literal["STATUS_ONLY", "CANONICAL_RESULT"]
type InferenceTransferWorkflowState = Literal[
    "REQUESTED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"
]
type InferenceTransferWorkflowResultState = Literal[
    "PENDING", "NO_RESULT", "POINTER_ONLY", "MEMBER_VERIFIED"
]


def _canonical_hash_and_bound(value: FrozenModel, hash_field: str, maximum: int) -> None:
    if getattr(value, hash_field) != content_sha256(
        value.model_dump(mode="json", exclude={hash_field})
    ):
        raise ValueError(f"{hash_field} differs from canonical invocation content")
    if len(canonical_json_bytes(value.model_dump(mode="json"))) > maximum:
        raise ValueError("inference-transfer invocation exceeds its encoded byte budget")


class InferenceTransferPairSubmitRequest(FrozenModel):
    """Small caller selection; the owner resolves both profiles and current authority.

    The 32 KiB ceiling admits two bounded claim-ID selections and a small existing
    PREPARE value, but not the complete 64 KiB worker profile context.
    """

    schema_version: Literal["inference-transfer-pair-submit/1.0"] = (
        "inference-transfer-pair-submit/1.0"
    )
    comparison: PairComparisonRequest
    snapshot_prepare: InferenceTransferSnapshotPrepareRequest
    expected_header_sha256: Sha256
    submission_sha256: Sha256

    @model_validator(mode="after")
    def exact_bounded_selection(self) -> InferenceTransferPairSubmitRequest:
        # Reparsing nested values closes model_copy/model_construct bypasses too.
        PairComparisonRequest.model_validate(self.comparison.model_dump(mode="json"))
        InferenceTransferSnapshotPrepareRequest.model_validate(
            self.snapshot_prepare.model_dump(mode="json")
        )
        _canonical_hash_and_bound(self, "submission_sha256", MAX_TRANSFER_SUBMISSION_BYTES)
        return self


class InferenceTransferWorkflowReadRequest(FrozenModel):
    schema_version: Literal["inference-transfer-workflow-read-request/1.0"] = (
        "inference-transfer-workflow-read-request/1.0"
    )
    workflow_id: TransferWorkflowId
    mode: InferenceTransferWorkflowReadMode
    read_sha256: Sha256

    @model_validator(mode="after")
    def exact_read_identity(self) -> InferenceTransferWorkflowReadRequest:
        _canonical_hash_and_bound(self, "read_sha256", MAX_TRANSFER_WORKFLOW_READ_BYTES)
        return self


class InferenceTransferWorkflowReadResult(FrozenModel):
    """Owner-resolved purpose state, with explicit canonical-member verification.

    The pure contract validates identity and selected-reference closure only. The
    owner separately verifies current caller/source access, exact Workflow/Step/
    Job/V21 lineage, canonical member bytes and claim facets before constructing it.
    """

    schema_version: Literal["inference-transfer-workflow-read-result/1.0"] = (
        "inference-transfer-workflow-read-result/1.0"
    )
    workflow_id: TransferWorkflowId
    workflow_state: InferenceTransferWorkflowState
    resource_version: int = Field(ge=1, strict=True)
    comparison: PairComparisonRequest
    graph_snapshot: KnowledgeGraphSnapshotPointer
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    access_policy_sha256: Sha256
    result_state: InferenceTransferWorkflowResultState
    result_artifact: ArtifactMemberPointer | None
    result: PairComparisonResult | None
    failure_code: str | None = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$", max_length=64)
    result_sha256: Sha256

    @model_validator(mode="after")
    def exact_state_and_member_identity(self) -> InferenceTransferWorkflowReadResult:
        PairComparisonRequest.model_validate(self.comparison.model_dump(mode="json"))
        KnowledgeGraphSnapshotPointer.model_validate(self.graph_snapshot.model_dump(mode="json"))
        if self.workflow_state in {"REQUESTED", "RUNNING"}:
            if (
                self.result_state != "PENDING"
                or self.result_artifact is not None
                or self.result is not None
                or self.failure_code is not None
            ):
                raise ValueError("pending Workflow cannot expose a terminal result or failure")
        elif self.workflow_state in {"FAILED", "CANCELLED"}:
            if (
                self.result_state != "NO_RESULT"
                or self.result_artifact is not None
                or self.result is not None
            ):
                raise ValueError("unsuccessful Workflow cannot expose a completed comparison")
        else:
            if (
                self.result_state not in {"POINTER_ONLY", "MEMBER_VERIFIED"}
                or self.result_artifact is None
                or self.failure_code is not None
            ):
                raise ValueError("completed Workflow requires its exact result Artifact pointer")
            member = ArtifactMemberPointer.model_validate(
                self.result_artifact.model_dump(mode="json")
            )
            if (
                member.member_path != "result.json"
                or member.schema_ref != TRANSFER_RESULT_MEMBER_SCHEMA
                or member.media_type != "application/json"
            ):
                raise ValueError("comparison Artifact pointer must pin the outer result envelope")
            if (self.result_state == "MEMBER_VERIFIED") != (self.result is not None):
                raise ValueError("only member-verified results expose canonical comparison content")
            if self.result is not None:
                _validate_comparison_result_selection(self.comparison, self.result)
        _canonical_hash_and_bound(self, "result_sha256", MAX_TRANSFER_WORKFLOW_READ_BYTES)
        return self


def _validate_comparison_result_selection(
    request: PairComparisonRequest, result: PairComparisonResult
) -> None:
    """Wire closure only; source-owner validation additionally checks resolved facets."""
    checked = PairComparisonResult.model_validate(result.model_dump(mode="json"))
    if (
        checked.request_id != request.request_id
        or checked.request_sha256 != request.request_sha256
        or checked.left_profile != request.left_profile
        or checked.right_profile != request.right_profile
        or checked.direction != request.direction
        or checked.rubric != request.rubric
    ):
        raise ValueError("canonical comparison content differs from the pinned request")
    left, right = set(request.left_claim_ids), set(request.right_claim_ids)
    references: tuple[InferenceTransferMapping | InferenceTransferDifference, ...] = (
        *checked.mappings,
        *checked.differences,
        *checked.new_reasoning,
    )
    for reference in references:
        if not set(reference.left_claim_ids).issubset(left) or not set(
            reference.right_claim_ids
        ).issubset(right):
            raise ValueError("canonical comparison content refers to an unselected claim")


def parse_pair_submit_request(value: object) -> InferenceTransferPairSubmitRequest:
    if not isinstance(value, dict):
        raise ValueError("selected-pair submission must be a JSON object")
    validate_contract("item-inference-transfer-invocation", value)
    return InferenceTransferPairSubmitRequest.model_validate(value)


def parse_workflow_read_request(value: object) -> InferenceTransferWorkflowReadRequest:
    if not isinstance(value, dict):
        raise ValueError("comparison Workflow read must be a JSON object")
    validate_contract("item-inference-transfer-invocation", value)
    return InferenceTransferWorkflowReadRequest.model_validate(value)


def parse_workflow_read_result(value: object) -> InferenceTransferWorkflowReadResult:
    if not isinstance(value, dict):
        raise ValueError("comparison Workflow read result must be a JSON object")
    validate_contract("item-inference-transfer-invocation", value)
    return InferenceTransferWorkflowReadResult.model_validate(value)


def validate_workflow_read_result_context(
    request: InferenceTransferWorkflowReadRequest, result: InferenceTransferWorkflowReadResult
) -> None:
    """Check exact Workflow/mode closure, never infer caller authority from the hash."""
    request = parse_workflow_read_request(request.model_dump(mode="json"))
    result = parse_workflow_read_result(result.model_dump(mode="json"))
    if request.workflow_id != result.workflow_id:
        raise ValueError("comparison result belongs to a different exact Workflow")
    if result.workflow_state == "COMPLETED" and result.result_state != (
        "POINTER_ONLY" if request.mode == "STATUS_ONLY" else "MEMBER_VERIFIED"
    ):
        raise ValueError("comparison result verification state differs from the requested mode")
