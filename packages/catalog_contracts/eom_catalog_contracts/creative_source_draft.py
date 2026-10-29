"""Source-first draft: no invented media identity or inferred printed score."""

from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_catalog_contracts.assessment_item import (
    EquationBlock,
    Interaction,
    ItemSolution,
    ParagraphBlock,
    StatementSetBlock,
    TableBlock,
    validate_item_reference_contract,
)
from eom_catalog_contracts.external_item_learning_result import ExternalItemLearningRegion
from eom_catalog_contracts.models import FrozenModel, _safe_text
from eom_catalog_contracts.validation import validate_contract

CREATIVE_SOURCE_DRAFT_SCHEMA = "creative-source-item-draft-v1"
CREATIVE_SOURCE_DRAFT_SCHEMA_REF = "eom://schemas/external-item/source-item-draft/1.0"


class PrintedSourceScore(FrozenModel):
    state: Literal["PRINTED"]
    points: int = Field(strict=True, ge=0, le=100)


class UnprintedSourceScore(FrozenModel):
    state: Literal["UNPRINTED"]
    points: None


SourceScore = Annotated[PrintedSourceScore | UnprintedSourceScore, Field(discriminator="state")]


class SourceImageBlock(FrozenModel):
    """A crop recipe referring to observed regions, never a resolved image pointer."""

    block_id: str = Field(pattern=r"^block_[a-z][a-z0-9_]{0,63}$")
    type: Literal["source_image"] = "source_image"
    purpose: Literal["stimulus", "reference"]
    source_region_id: str = Field(pattern=r"^extregion_[0-9a-f]{32}$")
    target_region_id: str = Field(pattern=r"^extregion_[0-9a-f]{32}$")
    alt_text: str = Field(min_length=1, max_length=1000)

    _text = field_validator("alt_text")(_safe_text)


SourceDraftBlock = Annotated[
    ParagraphBlock | EquationBlock | TableBlock | StatementSetBlock | SourceImageBlock,
    Field(discriminator="type"),
]


class CreativeSourceItemDraft(FrozenModel):
    schema_version: Literal["creative-source-item-draft/1.0"] = "creative-source-item-draft/1.0"
    locale: str = Field(pattern=r"^[a-z]{2}-[A-Z]{2}$")
    title: str = Field(min_length=1, max_length=20_000)
    body: tuple[SourceDraftBlock, ...] = Field(min_length=1, max_length=100)
    interaction: Interaction
    solution: ItemSolution
    score: SourceScore
    solution_origin: Literal["EDITORIAL_SOURCE", "INDEPENDENT_PROPOSAL_UNVERIFIED"]

    _text = field_validator("title")(_safe_text)

    @model_validator(mode="after")
    def closed_item_references(self) -> Self:
        validate_contract(CREATIVE_SOURCE_DRAFT_SCHEMA, self.model_dump(mode="json"))
        validate_item_reference_contract(
            block_ids=tuple(block.block_id for block in self.body),
            statement_ids=tuple(
                statement.statement_id
                for block in self.body
                if isinstance(block, StatementSetBlock)
                for statement in block.statements
            ),
            interaction=self.interaction,
            solution=self.solution,
        )
        return self


def validate_source_draft_visual_regions(
    draft: CreativeSourceItemDraft,
    regions: tuple[ExternalItemLearningRegion, ...],
) -> None:
    """Check role/page/containment before any owner dereferences or crops bytes.

    At most 100 blocks and 64 declared regions: map lookup is constant-time;
    checking the bounded exclusion regions is O(images * exclusion_regions).
    This is geometry/source validation, not proof of semantic image correctness.
    """
    indexed = {region.region_id: region for region in regions}
    if len(indexed) != len(regions):
        raise ValueError("CREATIVE_DRAFT_REGION_DUPLICATE")
    excluded = tuple(
        region for region in regions if region.role in {"REFERENCE_ORIGINAL", "EDITORIAL_SOLUTION"}
    )
    for block in draft.body:
        if not isinstance(block, SourceImageBlock):
            continue
        source = indexed.get(block.source_region_id)
        target = indexed.get(block.target_region_id)
        if (
            source is None
            or target is None
            or source.role != "TARGET_ITEM"
            or target.role != "TARGET_ITEM"
            or source.physical_page != target.physical_page
        ):
            raise ValueError("CREATIVE_DRAFT_VISUAL_SOURCE_INVALID")
        crop, parent = source.bounding_box, target.bounding_box
        if not (
            parent.left <= crop.left < crop.right <= parent.right
            and parent.top <= crop.top < crop.bottom <= parent.bottom
        ):
            raise ValueError("CREATIVE_DRAFT_VISUAL_OUTSIDE_TARGET")
        if any(
            region.physical_page == source.physical_page
            and max(crop.left, region.bounding_box.left)
            < min(crop.right, region.bounding_box.right)
            and max(crop.top, region.bounding_box.top)
            < min(crop.bottom, region.bounding_box.bottom)
            for region in excluded
        ):
            raise ValueError("CREATIVE_DRAFT_VISUAL_UNRELATED_REGION_OVERLAP")
