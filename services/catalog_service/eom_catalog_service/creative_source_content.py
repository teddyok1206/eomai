"""Materialize the editorial source independently of the worker's proposed answer."""

from __future__ import annotations

import re
from dataclasses import dataclass

from eom_catalog_contracts.assessment_item import AssessmentItemContent
from eom_catalog_contracts.creative_source_lineage import (
    CreativeSourceAnswerMode,
    CreativeSourceNormalizationAction,
)
from eom_catalog_contracts.external_item_learning_result import ExternalItemLearningResult
from eom_identifiers import content_sha256


class CreativeSourceContentError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class CreativeSourceContent:
    content: AssessmentItemContent
    proposed_content_sha256: str
    registered_content_sha256: str
    source_answer_mode: CreativeSourceAnswerMode
    normalization_actions: tuple[CreativeSourceNormalizationAction, ...]
    warning_codes: tuple[str, ...]


def materialize_creative_source_content(
    result: ExternalItemLearningResult,
) -> CreativeSourceContent:
    """Preserve the source's wrong answer too; never fix the exam or mutate the proposal.

    Only an explicit `답:`/`정답:` label in the worker's declared answer regions
    is interpreted. This is archive-format extraction, not scientific inference.
    Other formats retain an explicitly unverified proposal and a visible warning.
    The caller must independently validate current source/Artifact authority.
    """
    proposal = result.proposal
    if proposal is None:
        raise CreativeSourceContentError("CREATIVE_SOURCE_ITEM_UNREADABLE")
    original = proposal.content
    data = original.model_dump(mode="json")
    before = content_sha256(data)
    regions = {region.region_id: region for region in result.regions}
    mappings = {entry.content_path: entry.region_ids for entry in proposal.content_region_map}
    actions: list[CreativeSourceNormalizationAction] = []
    warnings: set[str] = {issue.conflict_code for issue in result.conflicts}
    answer_mode: CreativeSourceAnswerMode = "NOT_APPLICABLE"
    if original.interaction.type == "single_choice":
        labels = {choice.label: choice.choice_id for choice in original.interaction.choices}
        if len(labels) != len(original.interaction.choices):
            raise CreativeSourceContentError("CREATIVE_SOURCE_CHOICE_LABEL_AMBIGUOUS")
        # Longer labels first prevents a short numeric label from consuming 10.
        label_pattern = "|".join(
            re.escape(label) for label in sorted(labels, key=len, reverse=True)
        )
        answer_pattern = re.compile(
            r"(?m)^\s*(?:정답|답)\s*[:\uff1a]\s*(" + label_pattern + r")(?=\s|[(),.\u3001]|$)"
        )
        observed = {
            labels[match.group(1)]
            for region_id in mappings.get("solution.correct_choice_ids", ())
            if regions[region_id].role in {"TARGET_ITEM", "EDITORIAL_SOLUTION"}
            for match in answer_pattern.finditer(regions[region_id].observed_text)
        }
        if len(observed) == 1:
            data["solution"]["correct_choice_ids"] = sorted(observed)
            answer_mode = "EDITORIAL_SOURCE"
            actions.append("PRESERVED_EDITORIAL_ANSWER")
        else:
            answer_mode = "MODEL_PROPOSAL_UNVERIFIED"
            warnings.add("SOURCE_EDITORIAL_ANSWER_NOT_UNAMBIGUOUS")
    explanation_regions = sorted(
        (
            regions[region_id]
            for region_id in mappings.get("solution.explanation", ())
            if regions[region_id].role == "EDITORIAL_SOLUTION"
        ),
        key=lambda region: (
            region.physical_page,
            region.bounding_box.top,
            region.bounding_box.left,
            region.region_id,
        ),
    )
    if explanation_regions:
        explanation = "\n\n".join(region.observed_text for region in explanation_regions)
        if len(explanation) > 20_000:
            raise CreativeSourceContentError("CREATIVE_SOURCE_EXPLANATION_TOO_LARGE")
        data["solution"]["explanation"] = explanation
        actions.append("PRESERVED_EDITORIAL_EXPLANATION")
    else:
        warnings.add("SOURCE_EDITORIAL_EXPLANATION_NOT_MAPPED")
    content = AssessmentItemContent.model_validate(data)
    return CreativeSourceContent(
        content,
        before,
        content_sha256(content.model_dump(mode="json")),
        answer_mode,
        tuple(actions),
        tuple(sorted(warnings)),
    )
