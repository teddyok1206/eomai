"""Project exact past-exam visual pointers into a human-review draft.

The projection is deliberately read-only.  It performs one pass over accepted analyses and uses
maps keyed by item, anchor, and page position, giving O(a + v + p) time and O(a + p) space for
anchors, visual observations, and source pages.  It never reads source pixels or decides that a
candidate is eligible; only a final human review can do that.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast

from eom_catalog_contracts import (
    AssessmentPageImageInput,
    AssessmentVisualPatternObservation,
    KnowledgeAnalysisResultV9,
    LegacyItemExtractionResult,
)
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    ImageEvaluationBoundingBox,
    ImageEvaluationSourceSnapshot,
    ImageTrainingRightsPolicy,
    LocalImageTrainingCandidateInventory,
    LocalImageTrainingCropProposalOmission,
    LocalImageTrainingEligibilityEntry,
    LocalImageTrainingEligibilityReview,
    LocalImageTrainingProjectionOmission,
    content_sha256,
    training_eligibility_population_sha256,
    validate_contract,
)
from pydantic import ValidationError as PydanticValidationError


class TrainingCandidateProjectionError(RuntimeError):
    """Stable fail-closed error for malformed or incomplete source provenance."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class AcceptedVisualTrainingSource:
    """One exact accepted V9 result and the extraction result it pins."""

    accepted: KnowledgeAnalysisResultV9
    extraction: LegacyItemExtractionResult
    rights_policy: ImageTrainingRightsPolicy


TrainingCropRepresentation = Literal[
    "APPARATUS",
    "COMPOSITE",
    "CROSS_SECTION",
    "DIAGRAM",
    "MAP",
    "PARTICLE_MODEL",
    "PHOTOGRAPH",
]
TrainingCropMode = Literal["MIXED", "RASTER"]
TrainingCropFeature = Literal[
    "ARROWS",
    "AXES",
    "BOUNDARY",
    "CALLOUT",
    "DATA_POINTS",
    "ERROR_BAR",
    "GRID",
    "LABELS",
    "LEADER_LINES",
    "LEGEND",
    "MULTIPLE_PANELS",
    "NUMBERED_STEPS",
    "PATTERN_FILL",
    "SCALE",
    "SYMBOL_KEY",
    "TRAJECTORY",
]
TrainingCropOmissionReason = Literal[
    "ANSWER_EXPLANATION_SOURCE",
    "HOLDOUT_SOURCE",
    "NO_PAGE_INPUT",
    "NO_VISUAL_REGION",
    "SOURCE_POINTER_INVALID",
    "UNSUPPORTED_REPRESENTATION",
]


@dataclass(frozen=True, slots=True)
class TrainingVisualCropSource:
    """One source page and visual anchor selected for deterministic crop proposals."""

    item_revision_id: str
    extraction_result: ImageEvaluationArtifactMember
    source_anchor_id: str
    visual_pattern_ids: tuple[str, ...]
    source_page_image: ImageEvaluationArtifactMember
    physical_page: int
    context_bounding_box: ImageEvaluationBoundingBox | None
    rights_policy: ImageTrainingRightsPolicy
    representation_kind: TrainingCropRepresentation
    rendering_mode: TrainingCropMode
    visual_features: tuple[TrainingCropFeature, ...]


_CROP_REPRESENTATIONS = frozenset(
    {
        "APPARATUS",
        "COMPOSITE",
        "CROSS_SECTION",
        "DIAGRAM",
        "MAP",
        "PARTICLE_MODEL",
        "PHOTOGRAPH",
    }
)


def select_training_visual_crop_sources(
    *,
    sources: tuple[AcceptedVisualTrainingSource, ...],
    holdout_source_anchor_ids: tuple[str, ...],
) -> tuple[
    tuple[TrainingVisualCropSource, ...],
    tuple[LocalImageTrainingCropProposalOmission, ...],
]:
    """Select exact raster/mixed visual pointers without reading pixels or approving crops."""

    holdout = frozenset(holdout_source_anchor_ids)
    selected: list[TrainingVisualCropSource] = []
    omissions: list[LocalImageTrainingCropProposalOmission] = []
    seen_anchors: set[str] = set()
    for source in sources:
        accepted_source = source.accepted.source
        extraction = source.extraction
        if (
            extraction.extraction_result_id != accepted_source.extraction_result_id
            or extraction.result_sha256 != accepted_source.extraction_result_sha256
        ):
            raise TrainingCandidateProjectionError("IMAGE_TRAINING_EXTRACTION_POINTER_MISMATCH")
        matching_items = tuple(
            proposal
            for proposal in extraction.items
            if proposal.item_proposal_id == accepted_source.item_proposal_id
            and proposal.item_number == accepted_source.item_number
        )
        if len(matching_items) != 1:
            raise TrainingCandidateProjectionError("IMAGE_TRAINING_ITEM_PROPOSAL_UNRESOLVED")
        item = matching_items[0]
        anchors = {anchor.anchor_id: anchor for anchor in item.source_anchors}
        if len(anchors) != len(item.source_anchors):
            raise TrainingCandidateProjectionError("IMAGE_TRAINING_SOURCE_ANCHOR_DUPLICATE")
        pages: dict[tuple[str, int], AssessmentPageImageInput] = {
            (page.source_role, page.physical_page): page for page in accepted_source.page_inputs
        }
        if len(pages) != len(accepted_source.page_inputs):
            raise TrainingCandidateProjectionError("IMAGE_TRAINING_SOURCE_PAGE_DUPLICATE")
        patterns_by_anchor: dict[str, list[AssessmentVisualPatternObservation]] = defaultdict(list)
        for pattern in item.visual_patterns:
            if pattern.rendering_mode not in {"RASTER", "MIXED"}:
                continue
            for anchor_id in pattern.source_anchor_ids:
                patterns_by_anchor[anchor_id].append(pattern)

        extraction_pointer = ImageEvaluationArtifactMember.model_validate(
            _artifact_member(accepted_source.extraction_result_artifact)
        )
        for anchor_id in sorted(patterns_by_anchor):
            if anchor_id in seen_anchors:
                raise TrainingCandidateProjectionError("IMAGE_TRAINING_SOURCE_ANCHOR_DUPLICATE")
            seen_anchors.add(anchor_id)
            patterns = patterns_by_anchor[anchor_id]
            anchor = anchors.get(anchor_id)
            if anchor is None:
                raise TrainingCandidateProjectionError("IMAGE_TRAINING_SOURCE_ANCHOR_UNRESOLVED")
            pattern_ids = tuple(sorted({pattern.pattern_id for pattern in patterns}))
            kinds = {pattern.representation_kind for pattern in patterns}
            modes = {pattern.rendering_mode for pattern in patterns}
            omission_reason: TrainingCropOmissionReason | None = None
            if anchor_id in holdout:
                omission_reason = "HOLDOUT_SOURCE"
            elif anchor.source_role == "ANSWER_EXPLANATION_DOCUMENT":
                omission_reason = "ANSWER_EXPLANATION_SOURCE"
            elif len(kinds) != 1 or len(modes) != 1 or not kinds.issubset(_CROP_REPRESENTATIONS):
                omission_reason = "UNSUPPORTED_REPRESENTATION"
            page = (
                None
                if anchor.physical_page is None
                else pages.get((anchor.source_role, anchor.physical_page))
            )
            if omission_reason is None and page is None:
                omission_reason = "NO_PAGE_INPUT"
            if omission_reason is not None:
                omissions.append(
                    LocalImageTrainingCropProposalOmission(
                        item_revision_id=accepted_source.item_revision_id,
                        extraction_result=extraction_pointer,
                        source_anchor_id=anchor_id,
                        visual_pattern_ids=pattern_ids,
                        reason=omission_reason,
                    )
                )
                continue
            assert page is not None and anchor.physical_page is not None
            kind = next(iter(kinds))
            mode = next(iter(modes))
            selected.append(
                TrainingVisualCropSource(
                    item_revision_id=accepted_source.item_revision_id,
                    extraction_result=extraction_pointer,
                    source_anchor_id=anchor_id,
                    visual_pattern_ids=pattern_ids,
                    source_page_image=ImageEvaluationArtifactMember.model_validate(
                        _artifact_member(page.image)
                    ),
                    physical_page=anchor.physical_page,
                    context_bounding_box=(
                        None
                        if anchor.bounding_box is None
                        else ImageEvaluationBoundingBox.model_validate(
                            anchor.bounding_box.model_dump(mode="json")
                        )
                    ),
                    rights_policy=source.rights_policy,
                    representation_kind=cast(TrainingCropRepresentation, kind),
                    rendering_mode=cast(TrainingCropMode, mode),
                    visual_features=cast(
                        tuple[TrainingCropFeature, ...],
                        tuple(
                            sorted(
                                {feature for pattern in patterns for feature in pattern.features}
                            )
                        ),
                    ),
                )
            )
    selected.sort(key=lambda value: value.source_anchor_id)
    omissions.sort(key=lambda value: (value.item_revision_id, value.source_anchor_id, value.reason))
    return tuple(selected), tuple(omissions)


def _artifact_member(value: object) -> dict[str, object]:
    model_dump = getattr(value, "model_dump", None)
    if not callable(model_dump):
        raise TrainingCandidateProjectionError("IMAGE_TRAINING_SOURCE_POINTER_INVALID")
    raw = model_dump(mode="json")
    return ImageEvaluationArtifactMember.model_validate(raw).model_dump(mode="json")


def _project_one(
    source: AcceptedVisualTrainingSource,
    *,
    holdout_anchors: frozenset[str],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    accepted = source.accepted
    extraction = source.extraction
    accepted_source = accepted.source
    if (
        extraction.extraction_result_id != accepted_source.extraction_result_id
        or extraction.result_sha256 != accepted_source.extraction_result_sha256
    ):
        raise TrainingCandidateProjectionError("IMAGE_TRAINING_EXTRACTION_POINTER_MISMATCH")
    proposals = tuple(
        proposal
        for proposal in extraction.items
        if proposal.item_proposal_id == accepted_source.item_proposal_id
        and proposal.item_number == accepted_source.item_number
    )
    if len(proposals) != 1:
        raise TrainingCandidateProjectionError("IMAGE_TRAINING_ITEM_PROPOSAL_UNRESOLVED")
    proposal = proposals[0]
    anchors = {anchor.anchor_id: anchor for anchor in proposal.source_anchors}
    if len(anchors) != len(proposal.source_anchors):
        raise TrainingCandidateProjectionError("IMAGE_TRAINING_SOURCE_ANCHOR_DUPLICATE")
    pages: dict[tuple[str, int], AssessmentPageImageInput] = {
        (page.source_role, page.physical_page): page for page in accepted_source.page_inputs
    }
    if len(pages) != len(accepted_source.page_inputs):
        raise TrainingCandidateProjectionError("IMAGE_TRAINING_SOURCE_PAGE_DUPLICATE")

    patterns_by_anchor: dict[str, list[AssessmentVisualPatternObservation]] = defaultdict(list)
    for pattern in proposal.visual_patterns:
        if pattern.representation_kind not in {"PHOTOGRAPH", "COMPOSITE"}:
            continue
        if pattern.rendering_mode not in {"RASTER", "MIXED"}:
            continue
        for anchor_id in pattern.source_anchor_ids:
            patterns_by_anchor[anchor_id].append(pattern)

    entries: list[dict[str, object]] = []
    omissions: list[dict[str, object]] = []
    extraction_pointer = _artifact_member(accepted_source.extraction_result_artifact)
    rights_policy = source.rights_policy.model_dump(mode="json")
    for anchor_id in sorted(patterns_by_anchor):
        patterns = patterns_by_anchor[anchor_id]
        anchor = anchors.get(anchor_id)
        if anchor is None:
            raise TrainingCandidateProjectionError("IMAGE_TRAINING_SOURCE_ANCHOR_UNRESOLVED")
        kinds = {pattern.representation_kind for pattern in patterns}
        modes = {pattern.rendering_mode for pattern in patterns}
        pattern_ids = sorted({pattern.pattern_id for pattern in patterns})
        page = (
            None
            if anchor.physical_page is None
            else pages.get((anchor.source_role, anchor.physical_page))
        )
        if (
            anchor.physical_page is None
            or anchor.bounding_box is None
            or page is None
            or len(kinds) != 1
            or len(modes) != 1
        ):
            omissions.append(
                {
                    "item_revision_id": accepted_source.item_revision_id,
                    "extraction_result": extraction_pointer,
                    "source_anchor_id": anchor_id,
                    "visual_pattern_ids": pattern_ids,
                    "exclusion_reasons": ["AMBIGUOUS_CROP"],
                }
            )
            continue
        source_page = _artifact_member(page.image)
        identity = content_sha256(
            {
                "item_revision_id": accepted_source.item_revision_id,
                "extraction_result": extraction_pointer,
                "source_anchor_id": anchor_id,
                "visual_pattern_ids": pattern_ids,
                "source_page_image": source_page,
                "bounding_box": anchor.bounding_box.model_dump(mode="json"),
            }
        ).removeprefix("sha256:")
        reasons: list[str] = []
        if anchor_id in holdout_anchors:
            reasons.append("HOLDOUT_OR_NEAR_DUPLICATE")
        if anchor.source_role == "ANSWER_EXPLANATION_DOCUMENT":
            reasons.append("ANSWER_OR_EXPLANATION_CONTENT")
        entries.append(
            {
                "candidate_id": "imgtraincandidate_" + identity[:32],
                "item_revision_id": accepted_source.item_revision_id,
                "extraction_result": extraction_pointer,
                "source_anchor_id": anchor_id,
                "visual_pattern_ids": pattern_ids,
                "source_page_image": source_page,
                "physical_page": anchor.physical_page,
                "bounding_box": anchor.bounding_box.model_dump(mode="json"),
                "rights_policy": rights_policy,
                "representation_kind": next(iter(kinds)),
                "rendering_mode": next(iter(modes)),
                "decision": "EXCLUDED" if reasons else "PENDING",
                "exclusion_reasons": sorted(reasons),
                "caption_en": None,
                "caption_sha256": None,
            }
        )
    return entries, omissions


def project_training_eligibility_draft(
    *,
    sources: tuple[AcceptedVisualTrainingSource, ...],
    source_snapshot: ImageEvaluationSourceSnapshot,
    holdout_evaluation_plan: ImageEvaluationArtifactMember,
    holdout_sample_ids: tuple[str, ...],
    holdout_source_anchor_ids: tuple[str, ...],
    created_at: datetime,
    created_by: str,
) -> LocalImageTrainingEligibilityReview:
    """Create an immutable draft; no projected entry is automatically eligible."""

    if len(sources) != source_snapshot.target_count:
        raise TrainingCandidateProjectionError("IMAGE_TRAINING_SOURCE_SET_INCOMPLETE")
    item_revision_ids = tuple(source.accepted.source.item_revision_id for source in sources)
    if item_revision_ids != tuple(sorted(item_revision_ids)) or len(item_revision_ids) != len(
        set(item_revision_ids)
    ):
        raise TrainingCandidateProjectionError("IMAGE_TRAINING_SOURCE_SET_INVALID")
    if holdout_sample_ids != tuple(sorted(set(holdout_sample_ids))) or (
        holdout_source_anchor_ids != tuple(sorted(set(holdout_source_anchor_ids)))
    ):
        raise TrainingCandidateProjectionError("IMAGE_TRAINING_HOLDOUT_SET_INVALID")

    entries: list[dict[str, object]] = []
    omissions: list[dict[str, object]] = []
    holdout_anchors = frozenset(holdout_source_anchor_ids)
    try:
        for source in sources:
            projected, omitted = _project_one(source, holdout_anchors=holdout_anchors)
            entries.extend(projected)
            omissions.extend(omitted)
        entries.sort(key=lambda entry: str(entry["candidate_id"]))
        omissions.sort(
            key=lambda omission: (
                str(omission["item_revision_id"]),
                str(omission["source_anchor_id"]),
            )
        )
        if not entries and not omissions:
            raise TrainingCandidateProjectionError("IMAGE_TRAINING_CANDIDATE_SET_EMPTY")
        typed_entries = tuple(
            LocalImageTrainingEligibilityEntry.model_validate(entry) for entry in entries
        )
        typed_omissions = tuple(
            LocalImageTrainingProjectionOmission.model_validate(omission) for omission in omissions
        )
        population_sha256 = training_eligibility_population_sha256(
            source_snapshot=source_snapshot,
            holdout_evaluation_plan=holdout_evaluation_plan,
            holdout_sample_ids=holdout_sample_ids,
            holdout_source_anchor_ids=holdout_source_anchor_ids,
            selection_query_revision="local-image-lora-candidate-query/1.0",
            eligibility_policy_revision="local-image-lora-eligibility/1.0",
            entries=typed_entries,
            projection_omissions=typed_omissions,
        )
        identity = population_sha256.removeprefix("sha256:")
        body = {
            "schema_version": "local-image-training-eligibility-review/1.0",
            "review_id": "imgtrainreview_" + identity[:32],
            "review_state": "DRAFT",
            "source_snapshot": source_snapshot.model_dump(mode="json"),
            "holdout_evaluation_plan": holdout_evaluation_plan.model_dump(mode="json"),
            "holdout_sample_ids": list(holdout_sample_ids),
            "holdout_source_anchor_ids": list(holdout_source_anchor_ids),
            "selection_query_revision": "local-image-lora-candidate-query/1.0",
            "eligibility_policy_revision": "local-image-lora-eligibility/1.0",
            "entries": entries,
            "projection_omissions": omissions,
            "candidate_population_sha256": population_sha256,
            "eligible_candidate_set_sha256": content_sha256([]),
            "reviewed_at": created_at.isoformat().replace("+00:00", "Z"),
            "reviewed_by": created_by,
        }
        value = {**body, "review_sha256": content_sha256(body)}
        validate_contract("training-eligibility-review", value)
        return LocalImageTrainingEligibilityReview.model_validate(value)
    except TrainingCandidateProjectionError:
        raise
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise TrainingCandidateProjectionError(
            "IMAGE_TRAINING_CANDIDATE_PROJECTION_FAILED"
        ) from exc


def build_training_candidate_inventory(
    *,
    review: LocalImageTrainingEligibilityReview,
    created_at: datetime,
    created_by: str,
) -> LocalImageTrainingCandidateInventory:
    """Derive the sole ordered candidate inventory from one final review."""

    if review.review_state != "FINAL":
        raise TrainingCandidateProjectionError("IMAGE_TRAINING_ELIGIBILITY_REVIEW_NOT_FINAL")
    candidates = tuple(
        entry.candidate() for entry in review.entries if entry.decision == "ELIGIBLE"
    )
    if not candidates:
        raise TrainingCandidateProjectionError("IMAGE_TRAINING_CANDIDATE_SET_EMPTY")
    identity = content_sha256(
        {
            "review_id": review.review_id,
            "review_sha256": review.review_sha256,
            "eligible_candidate_set_sha256": review.eligible_candidate_set_sha256,
        }
    ).removeprefix("sha256:")
    body = {
        "schema_version": "local-image-training-candidate-inventory/1.0",
        "inventory_id": "imgtraininventory_" + identity[:32],
        "source_snapshot": review.source_snapshot.model_dump(mode="json"),
        "holdout_evaluation_plan": review.holdout_evaluation_plan.model_dump(mode="json"),
        "holdout_sample_ids": list(review.holdout_sample_ids),
        "holdout_source_anchor_ids": list(review.holdout_source_anchor_ids),
        "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "created_by": created_by,
    }
    value = {**body, "inventory_sha256": content_sha256(body)}
    try:
        validate_contract("training-candidate-inventory", value)
        return LocalImageTrainingCandidateInventory.model_validate(value)
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise TrainingCandidateProjectionError(
            "IMAGE_TRAINING_CANDIDATE_INVENTORY_INVALID"
        ) from exc
