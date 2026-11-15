"""Native use-to-representation closure, not authority or scientific equivalence.

The caller resolves the exact native scope and source permissions. This receipt
records each allowed use once without changing Work1, Result1 or OfficeBindings1.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from eom_identifiers import content_sha256
from eom_image_contracts.office_picture_uses import OfficeObjectId
from pydantic import AfterValidator, Field, model_validator

from eom_catalog_contracts.assessment_item import EquationBlock, TableBlock
from eom_catalog_contracts.creative_source_draft import SourceImageBlock
from eom_catalog_contracts.material_learning import (
    MaterialExtractionResult,
    MaterialExtractionResultFamily,
    MaterialExtractionResultV2,
)
from eom_catalog_contracts.material_native_visual_preparation import (
    MaterialNativeQuestionVisualScope,
)
from eom_catalog_contracts.models import FrozenModel, Sha256, _safe_text
from eom_catalog_contracts.validation import validate_contract

MATERIAL_NATIVE_VISUAL_COVERAGE_REF = "eom://schemas/material-learning/native-visual-coverage/1.0"
_BlockId = Annotated[str, Field(pattern=r"^block_[a-z][a-z0-9_]{0,63}$")]
_RegionId = Annotated[str, Field(pattern=r"^extregion_[0-9a-f]{32}$")]


def _meaningful_evidence(value: str) -> str:
    _safe_text(value)
    if not value.strip():
        raise ValueError("MATERIAL_NATIVE_VISUAL_COVERAGE_EVIDENCE_EMPTY")
    return value


_Evidence = Annotated[
    str, Field(min_length=1, max_length=1500), AfterValidator(_meaningful_evidence)
]


class MaterialNativeImageDisposition(FrozenModel):
    kind: Literal["IMAGE"]
    picture_use_id: OfficeObjectId
    block_id: _BlockId
    source_region_id: _RegionId


class _RegionDisposition(FrozenModel):
    picture_use_id: OfficeObjectId
    source_region_ids: tuple[_RegionId, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def unique_regions(self) -> Self:
        if len(self.source_region_ids) != len(set(self.source_region_ids)):
            raise ValueError("MATERIAL_NATIVE_VISUAL_COVERAGE_REGION_DUPLICATE")
        return self


class _NativeBlockDisposition(_RegionDisposition):
    block_id: _BlockId
    justification: _Evidence


class MaterialNativeEquationDisposition(_NativeBlockDisposition):
    kind: Literal["NATIVE_EQUATION"]


class MaterialNativeTableDisposition(_NativeBlockDisposition):
    kind: Literal["NATIVE_TABLE"]


class MaterialNativeNonContentDisposition(_RegionDisposition):
    kind: Literal["NON_CONTENT"]
    reason: Literal["DECORATION", "PAGE_FURNITURE", "EDITORIAL_MARK"]
    evidence: _Evidence


class MaterialNativeUnresolvedDisposition(_RegionDisposition):
    kind: Literal["UNRESOLVED"]
    conflict_index: int = Field(strict=True, ge=0, le=31)


MaterialNativeVisualDisposition = Annotated[
    MaterialNativeImageDisposition
    | MaterialNativeEquationDisposition
    | MaterialNativeTableDisposition
    | MaterialNativeNonContentDisposition
    | MaterialNativeUnresolvedDisposition,
    Field(discriminator="kind"),
]


class MaterialNativeVisualCoverage(FrozenModel):
    schema_version: Literal["material-native-visual-coverage/1.0"]
    input_sha256: Sha256
    scope_sha256: Sha256
    dispositions: tuple[MaterialNativeVisualDisposition, ...] = Field(max_length=64)

    @model_validator(mode="after")
    def closed_dispositions(self) -> Self:
        ids = tuple(entry.picture_use_id for entry in self.dispositions)
        if len(ids) != len(set(ids)):
            raise ValueError("MATERIAL_NATIVE_VISUAL_COVERAGE_USE_DUPLICATE")
        validate_contract("material-native-visual-coverage-v1", self.model_dump(mode="json"))
        return self


def validate_material_native_visual_coverage(
    coverage: MaterialNativeVisualCoverage,
    *,
    scope: MaterialNativeQuestionVisualScope,
    result: MaterialExtractionResultFamily,
) -> None:
    """O(U + B + regions/bindings), U<=64; no pixels, paths, DB or implicit latest.

    A valid receipt proves declared structural coverage only. It cannot establish
    that an equation preserves a picture's science, or that a decoration claim is true.
    """
    # Typed copies can bypass nested validators; this is an admission boundary.
    coverage = MaterialNativeVisualCoverage.model_validate(coverage.model_dump(mode="json"))
    scope = MaterialNativeQuestionVisualScope.model_validate(scope.model_dump(mode="json"))
    model = (
        MaterialExtractionResultV2
        if result.schema_version == "material-learning-extraction-result/2.0"
        else MaterialExtractionResult
    )
    result = model.model_validate(result.model_dump(mode="json"))
    if coverage.input_sha256 != result.input_sha256:
        raise ValueError("MATERIAL_NATIVE_VISUAL_COVERAGE_INPUT_MISMATCH")
    if coverage.scope_sha256 != content_sha256(scope.model_dump(mode="json")):
        raise ValueError("MATERIAL_NATIVE_VISUAL_COVERAGE_SCOPE_MISMATCH")
    bindings = result.office_bindings
    if bindings is None or bindings.office_catalog_sha256 != scope.source_catalog_sha256:
        raise ValueError("MATERIAL_NATIVE_VISUAL_COVERAGE_CATALOG_MISMATCH")
    if {entry.picture_use_id for entry in coverage.dispositions} != set(
        scope.allowed_picture_use_ids
    ):
        raise ValueError("MATERIAL_NATIVE_VISUAL_COVERAGE_USE_SET_MISMATCH")

    proposal = result.proposal
    if proposal is not None and proposal.item_number != scope.item_number:
        raise ValueError("MATERIAL_NATIVE_VISUAL_COVERAGE_ITEM_MISMATCH")
    body = () if proposal is None else proposal.content.body
    blocks = {block.block_id: (index, block) for index, block in enumerate(body)}
    native_kinds: dict[str, str] = {}
    for block in body:
        if isinstance(block, EquationBlock) and block.source.strip():
            native_kinds[block.block_id] = "NATIVE_EQUATION"
        elif isinstance(block, TableBlock) and any(
            cell.strip() for row in (block.headers, *block.rows) for cell in row
        ):
            native_kinds[block.block_id] = "NATIVE_TABLE"
    mappings = (
        {}
        if proposal is None
        else {
            entry.content_path: frozenset(entry.region_ids) for entry in proposal.content_region_map
        }
    )
    regions = {region.region_id: region.role for region in result.regions}
    by_block = {binding.block_id: binding for binding in bindings.bindings}
    image_dispositions: set[str] = set()
    for entry in coverage.dispositions:
        if isinstance(entry, MaterialNativeImageDisposition):
            selected = blocks.get(entry.block_id)
            binding = by_block.get(entry.block_id)
            if (
                selected is None
                or not isinstance(selected[1], SourceImageBlock)
                or binding is None
                or binding.picture_use_id != entry.picture_use_id
                or binding.source_region_id != entry.source_region_id
                or selected[1].source_region_id != entry.source_region_id
                or regions.get(entry.source_region_id) != "TARGET_ITEM"
                or entry.source_region_id not in mappings.get(f"body[{selected[0]}]", ())
            ):
                raise ValueError("MATERIAL_NATIVE_VISUAL_COVERAGE_IMAGE_BINDING_MISMATCH")
            image_dispositions.add(entry.block_id)
            continue
        allowed_roles = (
            {"TARGET_ITEM", "OTHER"}
            if isinstance(entry, MaterialNativeNonContentDisposition)
            else {"TARGET_ITEM"}
        )
        if any(
            regions.get(identifier) not in allowed_roles for identifier in entry.source_region_ids
        ):
            raise ValueError("MATERIAL_NATIVE_VISUAL_COVERAGE_REGION_MISMATCH")
        if isinstance(entry, (MaterialNativeEquationDisposition, MaterialNativeTableDisposition)):
            selected = blocks.get(entry.block_id)
            if selected is None:
                raise ValueError("MATERIAL_NATIVE_VISUAL_COVERAGE_BLOCK_MISMATCH")
            index, block = selected
            if native_kinds.get(block.block_id) != entry.kind:
                raise ValueError("MATERIAL_NATIVE_VISUAL_COVERAGE_BLOCK_MISMATCH")
            if frozenset(entry.source_region_ids) != mappings.get(f"body[{index}]"):
                raise ValueError("MATERIAL_NATIVE_VISUAL_COVERAGE_REGION_MISMATCH")
        elif isinstance(entry, MaterialNativeUnresolvedDisposition):
            conflict = (
                result.conflicts[entry.conflict_index]
                if entry.conflict_index < len(result.conflicts)
                else None
            )
            if (
                result.status != "NEEDS_DECISION"
                or conflict is None
                or not conflict.blocking
                or conflict.conflict_code
                not in {
                    "UNRESOLVED_IMAGE",
                    "UNSUPPORTED_STRUCTURE",
                    "UNREADABLE_CONTENT",
                    "AMBIGUOUS_REGION",
                }
                or not set(entry.source_region_ids).issubset(conflict.source_region_ids)
            ):
                raise ValueError("MATERIAL_NATIVE_VISUAL_COVERAGE_UNRESOLVED_INVALID")
    image_blocks = {block.block_id for block in body if isinstance(block, SourceImageBlock)}
    if image_dispositions != image_blocks or image_dispositions != set(by_block):
        raise ValueError("MATERIAL_NATIVE_VISUAL_COVERAGE_IMAGE_BINDING_MISMATCH")
