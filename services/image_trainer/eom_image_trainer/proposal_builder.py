"""Build immutable visual-crop proposal sets from orchestrator-staged page images."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    ImageEvaluationBoundingBox,
    ImageEvaluationSourceSnapshot,
    ImageTrainingRightsPolicy,
    LocalImageTrainingCropProposal,
    LocalImageTrainingCropProposalOmission,
    LocalImageTrainingCropProposalSet,
    content_sha256,
    training_crop_proposal_population_sha256,
    validate_contract,
)
from PIL import Image  # type: ignore[import-not-found]
from pydantic import ValidationError as PydanticValidationError

from eom_image_trainer.crop_locator import LocatedVisualRegion, locate_visual_regions, run_tesseract


class CropProposalBuildError(RuntimeError):
    """Stable fail-closed proposal construction error."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class StagedVisualCropSource:
    item_revision_id: str
    extraction_result: ImageEvaluationArtifactMember
    source_anchor_id: str
    visual_pattern_ids: tuple[str, ...]
    source_page_image: ImageEvaluationArtifactMember
    physical_page: int
    context_bounding_box: ImageEvaluationBoundingBox | None
    rights_policy: ImageTrainingRightsPolicy
    representation_kind: Literal[
        "APPARATUS",
        "COMPOSITE",
        "CROSS_SECTION",
        "DIAGRAM",
        "MAP",
        "PARTICLE_MODEL",
        "PHOTOGRAPH",
    ]
    rendering_mode: Literal["MIXED", "RASTER", "VECTOR_LIKE"]
    visual_features: tuple[
        Literal[
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
        ],
        ...,
    ]
    page_image: Image.Image


OcrLocator = Callable[[Image.Image], tuple[ImageEvaluationBoundingBox, ...]]
VisualLocator = Callable[..., tuple[LocatedVisualRegion, ...]]


def _proposal(source: StagedVisualCropSource, region: LocatedVisualRegion) -> dict[str, object]:
    body: dict[str, object] = {
        "item_revision_id": source.item_revision_id,
        "extraction_result": source.extraction_result.model_dump(mode="json"),
        "source_anchor_id": source.source_anchor_id,
        "visual_pattern_ids": list(source.visual_pattern_ids),
        "source_page_image": source.source_page_image.model_dump(mode="json"),
        "physical_page": source.physical_page,
        "context_bounding_box": (
            None
            if source.context_bounding_box is None
            else source.context_bounding_box.model_dump(mode="json")
        ),
        "crop_bounding_box": region.crop_bounding_box.model_dump(mode="json"),
        "redaction_boxes": [value.model_dump(mode="json") for value in region.redaction_boxes],
        "rights_policy": source.rights_policy.model_dump(mode="json"),
        "representation_kind": source.representation_kind,
        "rendering_mode": source.rendering_mode,
        "visual_features": list(source.visual_features),
        "candidate_rank": region.candidate_rank,
        "ink_fraction_milli": region.ink_fraction_milli,
        "ocr_redaction_count": len(region.redaction_boxes),
    }
    identity = content_sha256(body).removeprefix("sha256:")
    return {"crop_proposal_id": "imgcropproposal_" + identity[:32], **body}


def build_training_crop_proposal_set(
    *,
    sources: tuple[StagedVisualCropSource, ...],
    preliminary_omissions: tuple[LocalImageTrainingCropProposalOmission, ...],
    source_snapshot: ImageEvaluationSourceSnapshot,
    training_authorization: ImageEvaluationArtifactMember,
    holdout_evaluation_plan: ImageEvaluationArtifactMember,
    holdout_sample_ids: tuple[str, ...],
    holdout_source_anchor_ids: tuple[str, ...],
    created_at: datetime,
    created_by: str,
    ocr_locator: OcrLocator = run_tesseract,
    visual_locator: VisualLocator = locate_visual_regions,
) -> LocalImageTrainingCropProposalSet:
    """Run bounded OCR/layout proposal generation without making eligibility decisions."""

    source_anchor_ids = tuple(value.source_anchor_id for value in sources)
    if source_anchor_ids != tuple(sorted(set(source_anchor_ids))):
        raise CropProposalBuildError("IMAGE_TRAINING_CROP_SOURCE_SET_INVALID")
    proposals: list[LocalImageTrainingCropProposal] = []
    omissions = list(preliminary_omissions)
    try:
        for source in sources:
            ocr_boxes = ocr_locator(source.page_image)
            regions = visual_locator(
                source.page_image,
                context_bounding_box=source.context_bounding_box,
                ocr_boxes=ocr_boxes,
            )
            if not regions:
                omissions.append(
                    LocalImageTrainingCropProposalOmission(
                        item_revision_id=source.item_revision_id,
                        extraction_result=source.extraction_result,
                        source_anchor_id=source.source_anchor_id,
                        visual_pattern_ids=source.visual_pattern_ids,
                        reason="NO_VISUAL_REGION",
                    )
                )
                continue
            proposals.extend(
                LocalImageTrainingCropProposal.model_validate(_proposal(source, region))
                for region in regions
            )
        typed_proposals = tuple(sorted(proposals, key=lambda value: value.crop_proposal_id))
        typed_omissions = tuple(
            sorted(
                omissions,
                key=lambda value: (value.item_revision_id, value.source_anchor_id, value.reason),
            )
        )
        if not typed_proposals:
            raise CropProposalBuildError("IMAGE_TRAINING_CROP_PROPOSAL_SET_EMPTY")
        population = training_crop_proposal_population_sha256(
            source_snapshot=source_snapshot,
            training_authorization=training_authorization,
            holdout_evaluation_plan=holdout_evaluation_plan,
            holdout_sample_ids=holdout_sample_ids,
            holdout_source_anchor_ids=holdout_source_anchor_ids,
            selection_query_revision="local-image-lora-crop-source-query/1.0",
            locator_revision="local-image-visual-crop-locator/1.0",
            proposals=typed_proposals,
            omissions=typed_omissions,
        )
        body = {
            "schema_version": "local-image-training-crop-proposal-set/1.0",
            "proposal_set_id": ("imgcropproposalset_" + population.removeprefix("sha256:")[:32]),
            "source_snapshot": source_snapshot.model_dump(mode="json"),
            "training_authorization": training_authorization.model_dump(mode="json"),
            "holdout_evaluation_plan": holdout_evaluation_plan.model_dump(mode="json"),
            "holdout_sample_ids": list(holdout_sample_ids),
            "holdout_source_anchor_ids": list(holdout_source_anchor_ids),
            "selection_query_revision": "local-image-lora-crop-source-query/1.0",
            "locator_revision": "local-image-visual-crop-locator/1.0",
            "proposals": [value.model_dump(mode="json") for value in typed_proposals],
            "omissions": [value.model_dump(mode="json") for value in typed_omissions],
            "proposal_population_sha256": population,
            "created_at": created_at.isoformat().replace("+00:00", "Z"),
            "created_by": created_by,
        }
        value = {**body, "proposal_set_sha256": content_sha256(body)}
        validate_contract("training-crop-proposal-set", value)
        return LocalImageTrainingCropProposalSet.model_validate(value)
    except CropProposalBuildError:
        raise
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise CropProposalBuildError("IMAGE_TRAINING_CROP_PROPOSAL_SET_INVALID") from exc
