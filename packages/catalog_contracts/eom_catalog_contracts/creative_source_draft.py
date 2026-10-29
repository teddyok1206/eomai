"""Source-first draft: no invented media identity or inferred printed score."""

from collections.abc import Mapping
from types import MappingProxyType
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

_TARGET_ROLES = frozenset({"TARGET_ITEM"})
_SOLUTION_ROLES = frozenset({"TARGET_ITEM", "EDITORIAL_SOLUTION"})
_METADATA_ROLES = frozenset({"TARGET_ITEM", "EDITORIAL_SOLUTION", "OTHER"})
_ROOT_FIELD_REGION_ROLES: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "title": _TARGET_ROLES,
        "body": _TARGET_ROLES,
        "interaction": _TARGET_ROLES,
        "solution": _SOLUTION_ROLES,
        "score": _METADATA_ROLES,
    }
)
_SOLUTION_FIELD_REGION_ROLES: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "correct_choice_ids": _SOLUTION_ROLES,
        "accepted_answers": _SOLUTION_ROLES,
        "explanation": _SOLUTION_ROLES,
        "authoring_intent": _METADATA_ROLES,
        "statement_explanations": _SOLUTION_ROLES,
    }
)


def creative_source_field_region_roles(content_path: str) -> frozenset[str]:
    """Classify an already resolved path, not authority or a substitute for resolution.

    The enclosing proposal resolves the complete actual path first. Exact root
    and solution-field lookup prevent a metadata leaf from widening its parent
    or a similarly named answer field. Reference-original is never admissible.
    """
    head, separator, tail = content_path.partition(".")
    root = head.partition("[")[0]
    if root == "solution" and separator:
        member = tail.partition(".")[0].partition("[")[0]
        allowed = _SOLUTION_FIELD_REGION_ROLES.get(member)
    else:
        allowed = _ROOT_FIELD_REGION_ROLES.get(root)
    if allowed is None:
        raise ValueError("CREATIVE_DRAFT_SOURCE_FIELD_UNKNOWN")
    return allowed


def creative_source_region_policy_description() -> str:
    """Generation guidance and admission share this one fixed source-role policy."""
    fields = tuple(
        ("body[i]" if field == "body" else field, roles)
        for field, roles in _ROOT_FIELD_REGION_ROLES.items()
    ) + tuple((f"solution.{field}", roles) for field, roles in _SOLUTION_FIELD_REGION_ROLES.items())
    return (
        "Map each actual field to declared source regions with these roles: "
        + "; ".join(f"{field}: {', '.join(sorted(roles))}" for field, roles in fields)
        + ". Nested values inherit their field's policy. Use the authoring_intent leaf for "
        "editorial metadata; OTHER is not answer, explanation, stem or choice evidence. "
        "REFERENCE_ORIGINAL is never permitted. Paths must resolve to actual values."
    )


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
