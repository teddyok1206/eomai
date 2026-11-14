"""Effective Native visual inputs over unchanged document/page source pins."""

from bisect import bisect_left

from eom_catalog_contracts.material_learning import MaterialPreparedSource
from eom_catalog_contracts.material_native_files import material_native_printed_number
from eom_catalog_contracts.material_native_intake import MaterialNativeExamBundle, MaterialPrepared
from eom_catalog_contracts.material_native_visual_preparation import (
    MaterialNativeQuestionVisualScope,
    MaterialNativeVisualPreparedArtifact,
)
from eom_catalog_contracts.material_native_visual_selection import material_native_visual_guidance


def require_material_native_visual_bundle(
    prepared: MaterialNativeVisualPreparedArtifact, bundle: MaterialNativeExamBundle
) -> None:
    """The checkpoint cannot redirect one question's scope to another native file."""
    if len(prepared.question_visual_scopes) != len(bundle.items) or any(
        (scope.item_number, scope.question_document, scope.split_evidence)
        != (item.item_number, item.question.document, item.question.split_evidence)
        for scope, item in zip(prepared.question_visual_scopes, bundle.items, strict=True)
    ):
        raise ValueError("MATERIAL_NATIVE_VISUAL_BUNDLE_SCOPE_MISMATCH")


def material_visual_work_sources(prepared: MaterialPrepared) -> tuple[MaterialPreparedSource, ...]:
    """Only replace the selected catalog; canonical pages retain the base source."""
    if not isinstance(prepared, MaterialNativeVisualPreparedArtifact):
        return prepared.sources
    catalogs = {entry.source_role: entry.catalog for entry in prepared.catalog_supplements}
    return tuple(
        MaterialPreparedSource.model_validate(
            {**source.model_dump(mode="json"), "office_catalog": catalog.model_dump(mode="json")}
        )
        if (catalog := catalogs.get(source.source_role)) is not None
        else source
        for source in prepared.sources
    )


def material_native_question_visual_scope(
    prepared: MaterialPrepared, *, printed_label: str | None
) -> MaterialNativeQuestionVisualScope | None:
    """One indexed immutable-scope lookup, without scanning a book per question."""
    if not isinstance(prepared, MaterialNativeVisualPreparedArtifact):
        return None
    number = material_native_printed_number(printed_label)
    scopes = prepared.question_visual_scopes
    position = bisect_left(scopes, number, key=lambda scope: scope.item_number)
    if position == len(scopes) or scopes[position].item_number != number:
        raise ValueError("MATERIAL_NATIVE_VISUAL_QUESTION_SCOPE_MISSING")
    return scopes[position]


def material_visual_work_instructions(
    *,
    source_instructions: str,
    scope: MaterialNativeQuestionVisualScope | None,
) -> str:
    """Display guidance only; registration separately validates exact image membership."""
    if scope is None:
        return source_instructions
    instructions = source_instructions + "\n\n" + material_native_visual_guidance(scope)
    if len(instructions) > 8000:
        raise ValueError("MATERIAL_NATIVE_VISUAL_GUIDANCE_TOO_LONG")
    return instructions
