"""Bounded, source-anchored proposal from a creative archive analysis worker."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Literal, Protocol, Self

from eom_identifiers import content_sha256
from pydantic import Field, field_validator, model_validator

from eom_catalog_contracts.assessment_item import AssessmentItemContent
from eom_catalog_contracts.legacy_assessment import NormalizedBoundingBox
from eom_catalog_contracts.models import FrozenModel, Sha256, _safe_text

EXTERNAL_ITEM_LEARNING_RESULT_SCHEMA = "external-item-learning-result-v1"
EXTERNAL_ITEM_LEARNING_RESULT_SCHEMA_REF = "eom://schemas/external-item/learning-result/1.0"

type RegionId = str
_CONTENT_PATH_SEGMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)(?:\[([0-9]+)\])?$")


def resolve_external_item_content_path(content: object, path: str) -> object:
    """Reject a plausible-looking anchor path that names no actual Item value."""

    current = content
    for segment in path.split("."):
        match = _CONTENT_PATH_SEGMENT.fullmatch(segment)
        if match is None or not isinstance(current, dict) or match[1] not in current:
            raise ValueError("content region path does not resolve")
        current = current[match[1]]
        if match[2] is not None:
            if not isinstance(current, list) or int(match[2]) >= len(current):
                raise ValueError("content region path does not resolve")
            current = current[int(match[2])]
    return current


class ExternalItemLearningRegion(FrozenModel):
    region_id: RegionId = Field(pattern=r"^extregion_[0-9a-f]{32}$")
    role: Literal["TARGET_ITEM", "EDITORIAL_SOLUTION", "REFERENCE_ORIGINAL", "OTHER"]
    physical_page: int = Field(strict=True, ge=1, le=32)
    bounding_box: NormalizedBoundingBox
    observed_text: str = Field(min_length=1, max_length=6000)
    confidence_milli: int = Field(strict=True, ge=0, le=1000)

    _text = field_validator("observed_text")(_safe_text)


class ExternalItemContentRegionMap(FrozenModel):
    content_path: str = Field(
        pattern=(
            r"^(title|body\[[0-9]+\](?:\.[A-Za-z0-9_\[\].-]+)?|"
            r"interaction(?:\.[A-Za-z0-9_\[\].-]+)?|"
            r"solution(?:\.[A-Za-z0-9_\[\].-]+)?|"
            r"score(?:\.[A-Za-z0-9_\[\].-]+)?)$"
        )
    )
    region_ids: tuple[RegionId, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def unique_regions(self) -> Self:
        if len(self.region_ids) != len(set(self.region_ids)):
            raise ValueError("content region references repeat")
        return self


class ExternalItemSolutionStep(FrozenModel):
    step_number: int = Field(strict=True, ge=1, le=32)
    reasoning_summary: str = Field(min_length=1, max_length=3000)
    source_region_ids: tuple[RegionId, ...] = Field(min_length=1, max_length=16)

    _text = field_validator("reasoning_summary")(_safe_text)

    @model_validator(mode="after")
    def unique_regions(self) -> Self:
        if len(self.source_region_ids) != len(set(self.source_region_ids)):
            raise ValueError("solution step region references repeat")
        return self


class ExternalItemLearningConflict(FrozenModel):
    conflict_code: Literal[
        "UNREADABLE_CONTENT",
        "AMBIGUOUS_REGION",
        "MISSING_SOLUTION",
        "ANSWER_DISAGREEMENT",
        "UNRESOLVED_IMAGE",
        "UNSUPPORTED_STRUCTURE",
        "OTHER_OBSERVED",
    ]
    description: str = Field(min_length=1, max_length=2000)
    source_region_ids: tuple[RegionId, ...] = Field(max_length=16)
    blocking: bool

    _text = field_validator("description")(_safe_text)


class ExternalItemLearningProposal(FrozenModel):
    item_number: int = Field(strict=True, ge=1, le=10000)
    content: AssessmentItemContent
    content_region_map: tuple[ExternalItemContentRegionMap, ...] = Field(
        min_length=2, max_length=128
    )
    solution_steps: tuple[ExternalItemSolutionStep, ...] = Field(min_length=1, max_length=32)
    answer_cross_check: Literal["MATCHES_EDITORIAL_SOLUTION", "DISAGREES", "NO_EDITORIAL_SOLUTION"]

    @model_validator(mode="after")
    def complete_mapping_and_ordered_steps(self) -> Self:
        paths = tuple(mapping.content_path for mapping in self.content_region_map)
        if len(paths) != len(set(paths)) or "title" not in paths:
            raise ValueError("proposal content regions repeat or omit title")
        required = {
            "title",
            "interaction",
            "solution.explanation",
            "score.points",
            *(f"body[{index}]" for index in range(len(self.content.body))),
        }
        if self.content.interaction.type == "single_choice":
            required.add("solution.correct_choice_ids")
        else:
            required.add("solution.accepted_answers")
        if not required.issubset(paths):
            raise ValueError("proposal lacks source regions for required Item fields")
        content = self.content.model_dump(mode="json")
        for path in paths:
            resolve_external_item_content_path(content, path)
        steps = tuple(step.step_number for step in self.solution_steps)
        if steps != tuple(range(1, len(steps) + 1)):
            raise ValueError("solution steps must be contiguous and ordered")
        return self


class ExternalItemLearningResult(FrozenModel):
    """Worker proposal; neither human approval nor Item/Graph publication."""

    schema_version: Literal["external-item-learning-result/1.0"] = (
        "external-item-learning-result/1.0"
    )
    result_id: str = Field(pattern=r"^extlearnresult_[0-9a-f]{32}$")
    input_sha256: Sha256
    source_id: str = Field(pattern=r"^extitem_[0-9a-f]{32}$")
    source_revision_id: str = Field(pattern=r"^extitemrev_[0-9a-f]{32}$")
    external_number: str = Field(pattern=r"^[0-9]{5}$")
    status: Literal["PROPOSED", "NEEDS_DECISION"]
    regions: tuple[ExternalItemLearningRegion, ...] = Field(min_length=1, max_length=64)
    proposal: ExternalItemLearningProposal | None
    conflicts: tuple[ExternalItemLearningConflict, ...] = Field(max_length=32)
    result_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def submitted_bytes_hash(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            supplied_hash = value.get("result_sha256")
            if supplied_hash != content_sha256(
                {key: field_value for key, field_value in value.items() if key != "result_sha256"}
            ):
                raise ValueError("creative learning result hash differs")
        return value

    @model_validator(mode="after")
    def closed_references_and_status(self) -> Self:
        roles = {region.region_id: region.role for region in self.regions}
        if len(roles) != len(self.regions) or "TARGET_ITEM" not in roles.values():
            raise ValueError("learning result needs unique regions and a target Item")
        for conflict in self.conflicts:
            if not set(conflict.source_region_ids).issubset(roles):
                raise ValueError("conflict references an unknown region")
        if self.proposal is not None:
            for mapping in self.proposal.content_region_map:
                allowed_roles = (
                    {"TARGET_ITEM", "EDITORIAL_SOLUTION"}
                    if mapping.content_path.startswith("solution")
                    else {"TARGET_ITEM", "EDITORIAL_SOLUTION", "OTHER"}
                    if mapping.content_path.startswith("score")
                    else {"TARGET_ITEM"}
                )
                if any(
                    roles.get(region_id) not in allowed_roles for region_id in mapping.region_ids
                ):
                    raise ValueError("Item content maps to an unrelated source region")
            for step in self.proposal.solution_steps:
                if any(
                    roles.get(region_id) not in {"TARGET_ITEM", "EDITORIAL_SOLUTION"}
                    for region_id in step.source_region_ids
                ):
                    raise ValueError("solution step references an unrelated source region")
            if (
                self.proposal.answer_cross_check == "MATCHES_EDITORIAL_SOLUTION"
                and "EDITORIAL_SOLUTION" not in roles.values()
            ):
                raise ValueError("editorial answer match requires an editorial region")
        if self.status == "PROPOSED" and (
            self.proposal is None
            or any(conflict.blocking for conflict in self.conflicts)
            or self.proposal.answer_cross_check == "DISAGREES"
        ):
            raise ValueError("proposed result has missing content or an unresolved conflict")
        if self.status == "NEEDS_DECISION" and not any(
            conflict.blocking for conflict in self.conflicts
        ):
            raise ValueError("needs-decision result must explain its blocking conflict")
        return self


class LearningSourceResultIdentity(Protocol):
    """Shared identity boundary for immutable historical and successor results."""

    @property
    def input_sha256(self) -> str: ...

    @property
    def source_id(self) -> str: ...

    @property
    def source_revision_id(self) -> str: ...

    @property
    def external_number(self) -> str: ...


def validate_external_item_learning_result_for_source(
    result: LearningSourceResultIdentity,
    source_input_sha256: str,
    source_id: str,
    source_revision_id: str,
    external_number: str,
) -> None:
    """Require exact replay identity before accepting even a proposal Artifact."""

    if (
        result.input_sha256 != source_input_sha256
        or result.source_id != source_id
        or result.source_revision_id != source_revision_id
        or result.external_number != external_number
    ):
        raise ValueError("creative learning result differs from its pinned source")
