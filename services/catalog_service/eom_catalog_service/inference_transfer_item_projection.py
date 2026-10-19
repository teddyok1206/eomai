"""Pure question-only Item and evidence-bound metadata projections.

The owner must first verify actual Artifact bytes, member/schema/hash, accepted
report lineage and current access. Typed values and the hashes propagated here
are not permission grants or proof of those infrastructure checks. This module
does not read files, query a database, inspect pixels or resolve latest values.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from eom_catalog_contracts.assessment_item import (
    AssessmentItemContent,
    AssessmentItemContentContract,
    AssessmentItemContentV2,
    AssessmentItemContentV3,
    EquationBlock,
    ImageBlock,
    ParagraphBlock,
    SingleChoiceInteraction,
    StatementSetBlock,
    TableBlock,
)
from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.inference_transfer_experiment import (
    CanonicalExperimentItemText,
    ExperimentMetadataField,
    ExperimentViewRecipe,
    StagedExperimentEntry,
)
from eom_catalog_contracts.item_inference_transfer import (
    InferenceTransferProfile,
    validate_inference_transfer_profile_references,
)
from eom_catalog_contracts.knowledge import (
    KnowledgeAnalysisSolutionReport,
    KnowledgeAnalysisSourceArtifactMemberV2,
    KnowledgeSolutionEvidencePointer,
)
from eom_hwpx_contracts import ContentTeamTable
from eom_identifiers import content_sha256

from eom_catalog_service.item_content_contract import ITEM_CONTENT_SCHEMAS

PATTERN_SUMMARY_LIMITATION = (
    "Accepted ASSESSMENT_PATTERN values are exact concept-assessment-link summaries, "
    "not formal pattern names or human-confirmed classifications."
)
STRUCTURAL_METADATA_LIMITATION = (
    "Original MATERIAL_FORM and ASSESSMENT_PATTERN values describe canonical structure only; "
    "science domain, curriculum unit, difficulty and Graph labels are not inferred."
)
IMAGE_ACCESS_LIMITATION = (
    "Image pixels were not inspected; only canonical alt text or image-slot presence is projected."
)
INLINE_FORMULA_METADATA_LIMITATION = (
    "V2/V3 inline equations remain in question text but are not extracted as FORMULA metadata; "
    "aggregate equation_sources is excluded because it can contain answer/explanation equations."
)
_MAXIMUM_METADATA_FIELDS = 32
_MAXIMUM_METADATA_VALUE_CHARACTERS = 512


class ItemProjectionUnavailable(ValueError):
    """Stable unavailable outcome; callers must not silently substitute another view."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class EvidenceBoundItemMetadata:
    """Small local value, not a persisted profile, source resolver or authority proof."""

    fields: tuple[ExperimentMetadataField, ...]
    limitations: tuple[str, ...]


def _validated_item(
    item: AssessmentItemContentContract,
    original_source: KnowledgeAnalysisSourceArtifactMemberV2,
) -> tuple[AssessmentItemContentContract, KnowledgeAnalysisSourceArtifactMemberV2]:
    source = KnowledgeAnalysisSourceArtifactMemberV2.model_validate(
        original_source.model_dump(mode="json")
    )
    if source.media_type != "application/json":
        raise ItemProjectionUnavailable("INFERENCE_ITEM_CONTENT_MEDIA_TYPE_UNAVAILABLE")
    entry = ITEM_CONTENT_SCHEMAS.get(source.schema_ref or "")
    if entry is None:
        raise ItemProjectionUnavailable("INFERENCE_ITEM_CONTENT_SCHEMA_UNAVAILABLE")
    _schema, model = entry
    if type(item) is not model:
        raise ItemProjectionUnavailable("INFERENCE_ITEM_CONTENT_TYPE_MISMATCH")
    # Revalidate nested values: frozen model_copy/model_construct are not validation boundaries.
    return model.model_validate(item.model_dump(mode="json")), source


def _table_text(
    headers: tuple[str, ...], rows: tuple[tuple[str, ...], ...], *, caption: str | None = None
) -> str:
    """JSON cell arrays retain boundaries even when a native cell contains tabs/pipes/newlines."""
    lines = [] if caption is None else [caption]
    lines.append(json.dumps(headers, ensure_ascii=False, separators=(",", ":")))
    lines.extend(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows)
    return "\n".join(lines)


def _v1_question_parts(item: AssessmentItemContent) -> tuple[str, ...]:
    parts: list[str] = []
    for block in item.body:
        if isinstance(block, ParagraphBlock):
            parts.append(block.text)
        elif isinstance(block, EquationBlock):
            parts.append(block.source)
        elif isinstance(block, TableBlock):
            parts.append(_table_text(block.headers, block.rows, caption=block.caption))
        elif isinstance(block, ImageBlock):
            parts.append(block.alt_text)
        elif isinstance(block, StatementSetBlock):
            parts.extend(f"{statement.label} {statement.text}" for statement in block.statements)
    if isinstance(item.interaction, SingleChoiceInteraction):
        parts.extend(f"{choice.label} {choice.text}" for choice in item.interaction.choices)
    else:
        parts.append(f"응답 형식: {item.interaction.response_format}")
    return tuple(parts)


def _content_team_question_parts(
    item: AssessmentItemContentV2 | AssessmentItemContentV3,
) -> tuple[str, ...]:
    parts = [item.stem, *(block.content for block in item.labeled_blocks)]
    if item.inquiry is not None:
        # The exact 탐구/실험 kind is structural metadata, not added prose in CONTENT_ONLY.
        if item.inquiry.goal is not None:
            parts.append(item.inquiry.goal)
        parts.extend((item.inquiry.procedure, item.inquiry.result))
    for visual in item.visuals:
        if visual.label:
            parts.append(visual.label)
        parts.append(
            _table_text(visual.headers, visual.rows)
            if isinstance(visual, ContentTeamTable)
            else "[그림]"
        )
    parts.append(item.bottom_stem)
    parts.extend(f"{statement.label} {statement.text}" for statement in item.statements)
    parts.extend(f"{choice.number} {choice.text}" for choice in item.choices)
    return tuple(parts)


def render_no_solution_item_text(
    *,
    item: AssessmentItemContentContract,
    original_source: KnowledgeAnalysisSourceArtifactMemberV2,
    recipe: ExperimentViewRecipe,
) -> CanonicalExperimentItemText:
    """Preserve complete question fields; never render answers or aggregate equation_sources.

    Source-member SHA is propagated from the owner's validated pointer. It is not
    recomputed from normalized typed JSON, which need not match original file bytes.
    The independently derived rendered-text SHA uses the existing canonical recipe.
    """
    checked_recipe = ExperimentViewRecipe.model_validate(recipe.model_dump(mode="json"))
    checked_item, source = _validated_item(item, original_source)
    return _render_checked_item_text(checked_item, source, checked_recipe)


def _render_checked_item_text(
    item: AssessmentItemContentContract,
    source: KnowledgeAnalysisSourceArtifactMemberV2,
    recipe: ExperimentViewRecipe,
) -> CanonicalExperimentItemText:
    parts = (
        _v1_question_parts(item)
        if isinstance(item, AssessmentItemContent)
        else _content_team_question_parts(item)
    )
    text = "\n\n".join(parts)
    if len(text.encode("utf-8")) > recipe.maximum_text_bytes:
        raise ItemProjectionUnavailable("INFERENCE_ITEM_TEXT_TOO_LARGE")
    return CanonicalExperimentItemText(
        text=text, original_source=source, text_sha256=content_sha256(text)
    )


def extract_evidence_bound_item_metadata(
    *,
    item: AssessmentItemContentContract,
    original_source: KnowledgeAnalysisSourceArtifactMemberV2,
    accepted_report: KnowledgeAnalysisSolutionReport,
    solution_evidence: KnowledgeSolutionEvidencePointer,
) -> EvidenceBoundItemMetadata:
    """Extract only existing question structure/equations and exact accepted link summaries.

    No Registry metadata, Graph labels, IDs, concept classifier or domain/unit/
    difficulty inference is used. Oversize values are wholly omitted with a
    limitation, never sliced; an over-budget field set is unavailable as a whole.
    """
    checked_item, source = _validated_item(item, original_source)
    report = KnowledgeAnalysisSolutionReport.model_validate(accepted_report.model_dump(mode="json"))
    evidence = KnowledgeSolutionEvidencePointer.model_validate(
        solution_evidence.model_dump(mode="json")
    )
    if report.base_analysis_result_id != evidence.base_analysis_result_id:
        raise ValueError("INFERENCE_ITEM_REPORT_BASE_MISMATCH")
    return _extract_checked_item_metadata(checked_item, source, report, evidence)


def _extract_checked_item_metadata(
    item: AssessmentItemContentContract,
    source: KnowledgeAnalysisSourceArtifactMemberV2,
    report: KnowledgeAnalysisSolutionReport,
    evidence: KnowledgeSolutionEvidencePointer,
) -> EvidenceBoundItemMetadata:
    fields, limitations = _original_item_metadata(item, source)

    summaries = tuple(
        link.summary for link in report.concept_assessment_links if link.assessment_pattern_node_ids
    )
    if summaries:
        limitations.add(PATTERN_SUMMARY_LIMITATION)
        for summary in summaries:
            _append_metadata(
                fields,
                limitations,
                key="ASSESSMENT_PATTERN",
                value=summary,
                basis="ACCEPTED_SOLUTION",
                source_sha256=evidence.solution_report.sha256,
            )
    else:
        limitations.add("Accepted assessment-pattern link summary is unavailable.")
    return _bounded_metadata(fields, limitations)


def _append_metadata(
    fields: dict[tuple[str, str, str], ExperimentMetadataField],
    limitations: set[str],
    *,
    key: str,
    value: str,
    basis: Literal["ORIGINAL_ITEM", "ACCEPTED_SOLUTION"],
    source_sha256: str,
) -> None:
    if len(value) > _MAXIMUM_METADATA_VALUE_CHARACTERS:
        limitations.add(f"{key} metadata value exceeds 512 characters and was wholly omitted.")
        return
    field = ExperimentMetadataField.model_validate(
        {"key": key, "value": value, "basis": basis, "source_sha256": source_sha256}
    )
    fields[(field.key, field.value, field.basis)] = field


def _original_item_metadata(
    item: AssessmentItemContentContract,
    source: KnowledgeAnalysisSourceArtifactMemberV2,
) -> tuple[dict[tuple[str, str, str], ExperimentMetadataField], set[str]]:
    fields: dict[tuple[str, str, str], ExperimentMetadataField] = {}
    limitations = {STRUCTURAL_METADATA_LIMITATION}

    def append(key: str, value: str) -> None:
        _append_metadata(
            fields,
            limitations,
            key=key,
            value=value,
            basis="ORIGINAL_ITEM",
            source_sha256=source.sha256,
        )

    if isinstance(item, AssessmentItemContent):
        for block in item.body:
            append("MATERIAL_FORM", block.type)
            if isinstance(block, EquationBlock):
                append("FORMULA", block.source)
        append("ASSESSMENT_PATTERN", item.interaction.type)
    else:
        limitations.add(INLINE_FORMULA_METADATA_LIMITATION)
        append("MATERIAL_FORM", item.visual_layout)
        if item.inquiry is not None:
            append("MATERIAL_FORM", item.inquiry.kind)
        for labeled_block in item.labeled_blocks:
            append("MATERIAL_FORM", labeled_block.kind)
        append(
            "ASSESSMENT_PATTERN",
            f"statements={len(item.statements)};choices={len(item.choices)}",
        )

    return fields, limitations


def _bounded_metadata(
    fields: dict[tuple[str, str, str], ExperimentMetadataField],
    limitations: set[str],
) -> EvidenceBoundItemMetadata:
    if len(fields) > _MAXIMUM_METADATA_FIELDS:
        limitations.add(
            "Metadata field budget exceeds 32; the entire metadata view is unavailable."
        )
        return EvidenceBoundItemMetadata(fields=(), limitations=tuple(sorted(limitations)))
    return EvidenceBoundItemMetadata(
        fields=tuple(fields[key] for key in sorted(fields)), limitations=tuple(sorted(limitations))
    )


def extract_original_item_metadata(
    *,
    item: AssessmentItemContentContract,
    original_source: KnowledgeAnalysisSourceArtifactMemberV2,
) -> EvidenceBoundItemMetadata:
    """Question-only structural metadata; no fake report or inferred science/DAG."""
    raw_similarity_contract_value(item)
    raw_similarity_contract_value(original_source)
    checked_item, source = _validated_item(item, original_source)
    return _bounded_metadata(*_original_item_metadata(checked_item, source))


def project_staged_item_entry(
    *,
    profile: InferenceTransferProfile,
    item: AssessmentItemContentContract,
    accepted_report: KnowledgeAnalysisSolutionReport,
    recipe: ExperimentViewRecipe,
) -> StagedExperimentEntry:
    """Compose existing experiment values, retaining honest unavailable content/metadata.

    This is not an admission operation. The owner must reauthorize exact sources
    before staging and publication, regardless of the resulting value's hashes.
    """
    checked_profile = InferenceTransferProfile.model_validate(profile.model_dump(mode="json"))
    report = KnowledgeAnalysisSolutionReport.model_validate(accepted_report.model_dump(mode="json"))
    validate_inference_transfer_profile_references(checked_profile, report)
    source = checked_profile.source_basis.source.artifact_member
    checked_recipe = ExperimentViewRecipe.model_validate(recipe.model_dump(mode="json"))
    try:
        checked_item, source = _validated_item(item, source)
    except ItemProjectionUnavailable as exc:
        return StagedExperimentEntry(
            profile=checked_profile, content=None, metadata=(), limitations=(exc.code,)
        )
    limitations: set[str] = set()
    content: CanonicalExperimentItemText | None = None
    try:
        content = _render_checked_item_text(checked_item, source, checked_recipe)
    except ItemProjectionUnavailable as exc:
        limitations.add(exc.code)
    result = _extract_checked_item_metadata(
        checked_item, source, report, checked_profile.source_basis.solution_evidence
    )
    limitations.update(result.limitations)
    has_images = (
        any(isinstance(block, ImageBlock) for block in checked_item.body)
        if isinstance(checked_item, AssessmentItemContent)
        else any(visual.kind == "IMAGE" for visual in checked_item.visuals)
    )
    if has_images:
        limitations.add(IMAGE_ACCESS_LIMITATION)
    return StagedExperimentEntry(
        profile=checked_profile,
        content=content,
        metadata=result.fields,
        limitations=tuple(sorted(limitations)),
    )
