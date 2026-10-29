"""Source recipes and public independent solution survive separate materialization."""

from collections.abc import Mapping
from typing import Any, Literal, Self

from eom_identifiers import content_sha256
from pydantic import Field, field_validator, model_validator

from eom_catalog_contracts.creative_source_draft import (
    CreativeSourceItemDraft,
    SourceImageBlock,
    validate_source_draft_visual_regions,
)
from eom_catalog_contracts.external_item_learning_result import (
    ExternalItemContentRegionMap,
    ExternalItemLearningConflict,
    ExternalItemLearningRegion,
    ExternalItemSolutionStep,
    resolve_external_item_content_path,
)
from eom_catalog_contracts.models import FrozenModel, Sha256, _safe_text
from eom_catalog_contracts.validation import validate_contract

EXTERNAL_ITEM_LEARNING_RESULT_V2_SCHEMA = "external-item-learning-result-v2"
EXTERNAL_ITEM_LEARNING_RESULT_V2_SCHEMA_REF = "eom://schemas/external-item/learning-result/2.0"


class IndependentSourceSolution(FrozenModel):
    answer_state: Literal["DETERMINED", "UNDETERMINED"]
    answer_labels: tuple[str, ...] = Field(max_length=10)
    accepted_answers: tuple[str, ...] = Field(max_length=20)
    explanation: str = Field(min_length=1, max_length=20_000)
    solution_steps: tuple[ExternalItemSolutionStep, ...] = Field(max_length=32)
    answer_cross_check: Literal[
        "MATCHES_EDITORIAL_SOLUTION", "DISAGREES", "NO_EDITORIAL_SOLUTION", "NOT_DETERMINED"
    ]
    editorial_region_ids: tuple[str, ...] = Field(max_length=16)

    _text = field_validator("explanation")(_safe_text)

    @model_validator(mode="after")
    def coherent_public_solution(self) -> Self:
        for values, maximum in ((self.answer_labels, 16), (self.accepted_answers, 20_000)):
            if len(values) != len(set(values)) or any(
                not 1 <= len(value) <= maximum for value in values
            ):
                raise ValueError("independent source answer is invalid")
            for value in values:
                _safe_text(value)
        if len(self.editorial_region_ids) != len(set(self.editorial_region_ids)):
            raise ValueError("independent source editorial references repeat")
        if tuple(step.step_number for step in self.solution_steps) != tuple(
            range(1, len(self.solution_steps) + 1)
        ):
            raise ValueError("independent source solution steps are not contiguous")
        if self.answer_state == "DETERMINED":
            if (
                bool(self.answer_labels) == bool(self.accepted_answers)
                or not self.solution_steps
                or self.answer_cross_check == "NOT_DETERMINED"
            ):
                raise ValueError("determined source solution lacks a unique answer representation")
        elif (
            self.answer_labels
            or self.accepted_answers
            or self.answer_cross_check != "NOT_DETERMINED"
        ):
            raise ValueError("undetermined source solution claims a determined answer")
        compared = self.answer_cross_check in {"MATCHES_EDITORIAL_SOLUTION", "DISAGREES"}
        # Observing an editorial source does not assert a determined comparison.
        # Preserve those references when the independent answer is undetermined;
        # the enclosing body still checks each reference's actual source role.
        if (compared and not self.editorial_region_ids) or (
            self.answer_cross_check == "NO_EDITORIAL_SOLUTION" and self.editorial_region_ids
        ):
            raise ValueError("editorial cross-check differs from its cited source")
        return self


class ExternalItemLearningProposalV2(FrozenModel):
    item_number: int = Field(strict=True, ge=1, le=10000)
    content: CreativeSourceItemDraft
    content_region_map: tuple[ExternalItemContentRegionMap, ...] = Field(
        min_length=2, max_length=128
    )

    @model_validator(mode="after")
    def complete_source_mapping(self) -> Self:
        paths = tuple(mapping.content_path for mapping in self.content_region_map)
        required = {
            "title",
            "interaction",
            "solution.explanation",
            "score",
            *(f"body[{index}]" for index in range(len(self.content.body))),
        }
        required.add(
            "solution.correct_choice_ids"
            if self.content.interaction.type == "single_choice"
            else "solution.accepted_answers"
        )
        if len(paths) != len(set(paths)) or not required.issubset(paths):
            raise ValueError("source draft lacks complete unique region mapping")
        content = self.content.model_dump(mode="json")
        for path in paths:
            resolve_external_item_content_path(content, path)
        return self


class ExternalItemLearningBodyV2(FrozenModel):
    """Untrusted worker body, validated before the owner stamps canonical storage."""

    schema_version: Literal["external-item-learning-result/2.0"] = (
        "external-item-learning-result/2.0"
    )
    result_id: str = Field(pattern=r"^extlearnresult_[0-9a-f]{32}$")
    input_sha256: Sha256
    source_id: str = Field(pattern=r"^extitem_[0-9a-f]{32}$")
    source_revision_id: str = Field(pattern=r"^extitemrev_[0-9a-f]{32}$")
    external_number: str = Field(pattern=r"^[0-9]{5}$")
    status: Literal["PROPOSED", "NEEDS_DECISION"]
    regions: tuple[ExternalItemLearningRegion, ...] = Field(min_length=1, max_length=64)
    proposal: ExternalItemLearningProposalV2 | None
    solution_report: IndependentSourceSolution
    conflicts: tuple[ExternalItemLearningConflict, ...] = Field(max_length=32)

    @model_validator(mode="after")
    def source_and_solution_closure(self) -> Self:
        roles = {region.region_id: region.role for region in self.regions}
        if len(roles) != len(self.regions) or "TARGET_ITEM" not in roles.values():
            raise ValueError("source successor needs unique observed regions and a target")
        for conflict in self.conflicts:
            if not set(conflict.source_region_ids).issubset(roles):
                raise ValueError("source successor conflict references an unknown region")
        for step in self.solution_report.solution_steps:
            if any(
                roles.get(identifier) not in {"TARGET_ITEM", "EDITORIAL_SOLUTION"}
                for identifier in step.source_region_ids
            ):
                raise ValueError("independent solution cites an unrelated source")
        if any(
            roles.get(identifier) != "EDITORIAL_SOLUTION"
            for identifier in self.solution_report.editorial_region_ids
        ):
            raise ValueError("editorial comparison cites an unrelated source")
        blocking = any(conflict.blocking for conflict in self.conflicts)
        if (
            self.status == "PROPOSED"
            and (
                self.proposal is None
                or blocking
                or self.solution_report.answer_state != "DETERMINED"
            )
        ) or (self.status == "NEEDS_DECISION" and not blocking):
            raise ValueError("source successor status differs from its unresolved issues")
        if self.solution_report.answer_cross_check == "DISAGREES" and not any(
            conflict.conflict_code == "ANSWER_DISAGREEMENT" for conflict in self.conflicts
        ):
            raise ValueError("source disagreement lacks an explicit preserved issue")
        if self.proposal is not None:
            self._validate_proposal_regions(roles)
        return self

    def _validate_proposal_regions(self, roles: Mapping[str, str]) -> None:
        proposal = self.proposal
        assert proposal is not None
        for mapping in proposal.content_region_map:
            allowed = (
                {"TARGET_ITEM", "EDITORIAL_SOLUTION"}
                if mapping.content_path.startswith("solution")
                else {"TARGET_ITEM", "EDITORIAL_SOLUTION", "OTHER"}
                if mapping.content_path.startswith("score")
                else {"TARGET_ITEM"}
            )
            if any(roles.get(identifier) not in allowed for identifier in mapping.region_ids):
                raise ValueError("source draft maps to unrelated source regions")
        mappings = {
            entry.content_path: set(entry.region_ids) for entry in proposal.content_region_map
        }
        for index, block in enumerate(proposal.content.body):
            if (
                isinstance(block, SourceImageBlock)
                and block.source_region_id not in mappings[f"body[{index}]"]
            ):
                raise ValueError("source visual differs from its actual mapped region")
        validate_source_draft_visual_regions(proposal.content, self.regions)
        interaction = proposal.content.interaction
        report = self.solution_report
        if interaction.type == "single_choice":
            labels = {choice.choice_id: choice.label for choice in interaction.choices}
            if report.accepted_answers or not set(report.answer_labels).issubset(labels.values()):
                raise ValueError("independent answer is not a declared source choice")
            editorial = {
                labels[identifier] for identifier in proposal.content.solution.correct_choice_ids
            }
            independent = set(report.answer_labels)
        else:
            if report.answer_labels:
                raise ValueError("constructed response uses choice labels")
            editorial = set(proposal.content.solution.accepted_answers)
            independent = set(report.accepted_answers)
        if proposal.content.solution_origin == "EDITORIAL_SOURCE":
            field = (
                "solution.correct_choice_ids"
                if interaction.type == "single_choice"
                else "solution.accepted_answers"
            )
            if not any(roles[identifier] == "EDITORIAL_SOLUTION" for identifier in mappings[field]):
                raise ValueError("editorial source answer lacks an editorial anchor")
        elif report.answer_cross_check == "MATCHES_EDITORIAL_SOLUTION":
            raise ValueError("unverified source answer cannot claim editorial agreement")
        if (
            interaction.type == "single_choice"
            and report.answer_cross_check == "MATCHES_EDITORIAL_SOLUTION"
            and editorial != independent
        ):
            raise ValueError("claimed editorial match disagrees with the source answer")
        if (
            report.answer_cross_check == "DISAGREES"
            and interaction.type == "single_choice"
            and proposal.content.solution_origin == "EDITORIAL_SOURCE"
            and editorial == independent
        ):
            raise ValueError("claimed source disagreement actually matches")


class ExternalItemLearningResultV2(ExternalItemLearningBodyV2):
    """Owner-stamped immutable result; neither source publication nor permission."""

    result_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def exact_hash(cls, value: Any) -> Any:
        if isinstance(value, Mapping) and value.get("result_sha256") != content_sha256(
            {key: field for key, field in value.items() if key != "result_sha256"}
        ):
            raise ValueError("creative learning successor result hash differs")
        return value

    @model_validator(mode="after")
    def canonical_storage(self) -> Self:
        if self.result_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"result_sha256"})
        ):
            raise ValueError("creative learning successor result is not canonical")
        validate_contract(EXTERNAL_ITEM_LEARNING_RESULT_V2_SCHEMA, self.model_dump(mode="json"))
        return self


def stamp_external_item_learning_result_v2(
    value: Mapping[str, Any],
) -> ExternalItemLearningResultV2:
    """Pure Orchestrator normalization; compute the hash after validated defaults.

    This returns data only. Job/source authorization, final Artifact commit and
    publication remain with their existing owners. A worker-supplied hash is
    rejected by the unhashed body's closed fields, not trusted or overwritten.
    """
    body = ExternalItemLearningBodyV2.model_validate(value).model_dump(mode="json")
    return ExternalItemLearningResultV2.model_validate(
        {**body, "result_sha256": content_sha256(body)}
    )
