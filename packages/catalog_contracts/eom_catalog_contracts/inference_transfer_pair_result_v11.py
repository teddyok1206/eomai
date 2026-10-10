"""Three-axis machine hypotheses grounded in exact selected pair claims.

Axis reference closure is not semantic correctness or source authorization.
CONCEPT/MATERIAL evidence can occur in any explicit claim facet; CRUX requires
the recorded decisive-inference facet. No scores or human labels are inferred.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_catalog_contracts.item_inference_transfer import (
    ClaimId,
    InferenceTransferDifference,
    InferenceTransferMapping,
    InferenceTransferProfile,
    InferenceTransferProfilePointer,
    InferenceTransferRubricPointer,
    PairComparisonRequest,
    PairComparisonResult,
    TransferFacet,
    TransferText,
    validate_pair_comparison_references,
)
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.validation import validate_contract

PAIR_COMPARISON_RESULT_V11_SCHEMA_NAME = "item-inference-transfer-pair-result-v1.1"
PAIR_COMPARISON_RESULT_V11_SCHEMA_REF = (
    "eom://schemas/knowledge/item-inference-transfer-pair-result/1.1"
)


class ComparisonAxis(StrEnum):
    CONCEPT = "CONCEPT"
    MATERIAL = "MATERIAL"
    CRUX = "CRUX"


class AxisJudgement(StrEnum):
    SAME = "SAME"
    DIFFERENT = "DIFFERENT"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"


class InferenceTransferAxisAssessment(FrozenModel):
    axis: ComparisonAxis
    judgement: AxisJudgement
    explanation: TransferText = Field(min_length=1, max_length=2000, pattern=r"\S")
    left_claim_ids: tuple[ClaimId, ...] = Field(max_length=16)
    right_claim_ids: tuple[ClaimId, ...] = Field(max_length=16)

    @model_validator(mode="after")
    def exact_bounded_evidence(self) -> InferenceTransferAxisAssessment:
        if any(
            values != tuple(sorted(set(values)))
            for values in (self.left_claim_ids, self.right_claim_ids)
        ):
            raise ValueError("axis claim references must be sorted and unique")
        if self.judgement != AxisJudgement.INSUFFICIENT and (
            not self.left_claim_ids or not self.right_claim_ids
        ):
            raise ValueError("a sufficient axis judgement requires claims from both sides")
        return self


class PairComparisonResultV11(FrozenModel):
    schema_version: Literal["item-inference-transfer-pair-result/1.1"] = (
        "item-inference-transfer-pair-result/1.1"
    )
    request_id: str = Field(pattern=r"^transferrequest_[0-9a-f]{32}$")
    request_sha256: Sha256
    left_profile: InferenceTransferProfilePointer
    right_profile: InferenceTransferProfilePointer
    direction: Literal["A_TO_B"] = "A_TO_B"
    rubric: InferenceTransferRubricPointer
    judgement: Literal[
        "INSUFFICIENT", "NO_TRANSFER", "STRUCTURAL_ANALOGY", "NEAR_IDENTICAL_CANDIDATE"
    ]
    mappings: tuple[InferenceTransferMapping, ...] = Field(max_length=64)
    shared_idea: TransferText | None = Field(min_length=1, max_length=2000)
    differences: tuple[InferenceTransferDifference, ...] = Field(max_length=32)
    new_reasoning: tuple[InferenceTransferDifference, ...] = Field(max_length=32)
    limitations: tuple[Annotated[TransferText, Field(min_length=1, max_length=1000)], ...] = Field(
        max_length=32
    )
    assessment_kind: Literal["MACHINE_HYPOTHESIS_NOT_HUMAN_VERIFICATION"] = (
        "MACHINE_HYPOTHESIS_NOT_HUMAN_VERIFICATION"
    )
    axes: tuple[
        InferenceTransferAxisAssessment,
        InferenceTransferAxisAssessment,
        InferenceTransferAxisAssessment,
    ]
    result_sha256: Sha256

    @model_validator(mode="after")
    def independent_axes_and_core(self) -> PairComparisonResultV11:
        # A transient validation view reuses the predecessor's core invariants.
        # It is neither a published 1.0 result nor a compatibility conversion.
        _legacy_validation_view(self)
        axes = tuple(
            InferenceTransferAxisAssessment.model_validate(axis.model_dump(mode="json"))
            for axis in self.axes
        )
        if tuple(axis.axis for axis in axes) != (
            ComparisonAxis.CONCEPT,
            ComparisonAxis.MATERIAL,
            ComparisonAxis.CRUX,
        ):
            raise ValueError("the three axes must occur once in CONCEPT/MATERIAL/CRUX order")
        if self.judgement in {"STRUCTURAL_ANALOGY", "NEAR_IDENTICAL_CANDIDATE"} and axes[
            2
        ].judgement not in {AxisJudgement.SAME, AxisJudgement.PARTIAL}:
            raise ValueError("a positive transfer hypothesis requires SAME/PARTIAL crux evidence")
        if self.result_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"result_sha256"})
        ):
            raise ValueError("result_sha256 differs from canonical three-axis content")
        return self


def _legacy_validation_view(result: PairComparisonResultV11) -> PairComparisonResult:
    body = result.model_dump(mode="json", exclude={"axes", "result_sha256"})
    body["schema_version"] = "item-inference-transfer-pair-result/1.0"
    return PairComparisonResult.model_validate(body | {"result_sha256": content_sha256(body)})


def parse_pair_comparison_result_v11(value: object) -> PairComparisonResultV11:
    """Validate the distinct 2020-12 successor, then its canonical frozen value."""
    if not isinstance(value, dict):
        raise ValueError("a three-axis pair result must be a closed JSON object")
    validate_contract(PAIR_COMPARISON_RESULT_V11_SCHEMA_NAME, value)
    return PairComparisonResultV11.model_validate(value)


def validate_pair_comparison_references_v11(
    request: PairComparisonRequest,
    result: PairComparisonResultV11,
    left: InferenceTransferProfile,
    right: InferenceTransferProfile,
) -> None:
    """Check exact request/profile/rubric and selected-claim closure in linear space/time.

    Callers must first resolve the canonical approved sources and current actor
    authority. These pure checks do not classify a claim's scientific concept or
    material accurately merely because a reference exists.
    """
    request = PairComparisonRequest.model_validate(request.model_dump(mode="json"))
    left = InferenceTransferProfile.model_validate(left.model_dump(mode="json"))
    right = InferenceTransferProfile.model_validate(right.model_dump(mode="json"))
    result = parse_pair_comparison_result_v11(result.model_dump(mode="json"))
    validate_pair_comparison_references(request, _legacy_validation_view(result), left, right)
    left_selected, right_selected = set(request.left_claim_ids), set(request.right_claim_ids)
    left_claims = {claim.claim_id: claim for claim in left.claims}
    right_claims = {claim.claim_id: claim for claim in right.claims}
    for axis in result.axes:
        if not set(axis.left_claim_ids).issubset(left_selected) or not set(
            axis.right_claim_ids
        ).issubset(right_selected):
            raise ValueError("an axis references an unselected or foreign profile claim")
        if axis.axis != ComparisonAxis.CRUX or axis.judgement == AxisJudgement.INSUFFICIENT:
            continue
        if any(
            left_claims[claim_id].facet != TransferFacet.DECISIVE_INFERENCE
            for claim_id in axis.left_claim_ids
        ) or any(
            right_claims[claim_id].facet != TransferFacet.DECISIVE_INFERENCE
            for claim_id in axis.right_claim_ids
        ):
            raise ValueError("a sufficient crux comparison requires decisive claims on both sides")
