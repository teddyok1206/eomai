"""Pure draft compiler. Caller owns authorized crop resolution and registration."""

from collections.abc import Mapping
from dataclasses import dataclass

from eom_catalog_contracts.assessment_item import AssessmentItemContent, ImageBlock
from eom_catalog_contracts.creative_source_draft import (
    CreativeSourceItemDraft,
    SourceImageBlock,
)


@dataclass(frozen=True, slots=True)
class MaterializedCreativeSourceDraft:
    content: AssessmentItemContent
    source_score_state: str
    solution_origin: str
    warning_codes: tuple[str, ...]


def creative_source_draft_warning_codes(draft: CreativeSourceItemDraft) -> tuple[str, ...]:
    """The compiler and official report reader share the same interpretation flags."""
    warnings = []
    if draft.score.state == "UNPRINTED":
        warnings.append("SOURCE_SCORE_NOT_PRINTED")
    if draft.solution_origin == "INDEPENDENT_PROPOSAL_UNVERIFIED":
        warnings.append("SOURCE_SOLUTION_UNVERIFIED")
    return tuple(sorted(warnings))


def materialize_creative_source_draft(
    draft: CreativeSourceItemDraft,
    *,
    resolved_images: Mapping[str, ImageBlock],
) -> MaterializedCreativeSourceDraft:
    """Compile only after the owner validates crop receipts and image pointers.

    The model never supplies resolved_images. Unknown printed scores use the
    canonical contract's legal zero without asserting that the source awards
    zero points; the caller must persist source_score_state and its warning.
    """
    expected = {block.block_id for block in draft.body if isinstance(block, SourceImageBlock)}
    if set(resolved_images) != expected:
        raise ValueError("CREATIVE_DRAFT_RESOLVED_IMAGE_SET_MISMATCH")
    body = []
    for block in draft.body:
        if isinstance(block, SourceImageBlock):
            image = resolved_images[block.block_id]
            if (
                image.block_id != block.block_id
                or image.purpose != block.purpose
                or image.alt_text != block.alt_text
            ):
                raise ValueError("CREATIVE_DRAFT_RESOLVED_IMAGE_BINDING_MISMATCH")
            body.append(image.model_dump(mode="json"))
        else:
            body.append(block.model_dump(mode="json"))
    content = AssessmentItemContent.model_validate(
        {
            "schema_version": "1.0",
            "locale": draft.locale,
            "title": draft.title,
            "body": body,
            "interaction": draft.interaction.model_dump(mode="json"),
            "solution": draft.solution.model_dump(mode="json"),
            "score": {"points": draft.score.points if draft.score.state == "PRINTED" else 0},
        }
    )
    return MaterializedCreativeSourceDraft(
        content,
        draft.score.state,
        draft.solution_origin,
        creative_source_draft_warning_codes(draft),
    )
