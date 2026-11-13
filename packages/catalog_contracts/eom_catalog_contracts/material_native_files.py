"""Native source bindings are immutable evidence references, never execution authority."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated, Literal, Self

from eom_hwpx_contracts.native_item_split import NativeItemSplitResult, NativeParagraphRange
from eom_identifiers import content_sha256
from pydantic import Field, field_validator, model_validator

from eom_catalog_contracts.material_learning import MaterialArtifactMember, MaterialExtractionWork
from eom_catalog_contracts.models import FrozenModel, Sha256, _safe_text
from eom_catalog_contracts.native_exam_intake import NativeExamWorkbookDocument
from eom_catalog_contracts.validation import validate_contract

MATERIAL_NATIVE_BINDING_REF = "eom://schemas/material-learning/native-item-binding/1.0"
MATERIAL_NATIVE_METADATA_REF = "eom://schemas/material-learning/item-metadata/2.0"
NATIVE_ITEM_SPLIT_EVIDENCE_REF = "eom://schemas/hwpx/native-item-split/1.0"
NATIVE_ITEM_DOCUMENT_REF = "eom://schemas/material-learning/native-item-document/1.0"
NATIVE_WORKBOOK_MANIFEST_REF = "eom://schemas/material-learning/native-exam/1.0"
_HWPX_MEDIA = frozenset({"application/vnd.hancom.hwpx", "application/hwp+zip"})
_WORKBOOK_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_PRINTED_NUMBER = re.compile(r"\s*([0-9]{1,5})\s*(?:번|[.)])?\s*")
NativeNumber = Annotated[int, Field(strict=True, ge=1, le=10000)]


def material_native_printed_number(value: str | None) -> int:
    """Only explicit numeric labels match; titles or descriptive text never do."""
    match = _PRINTED_NUMBER.fullmatch(value) if value is not None else None
    if match is None or not 1 <= int(match[1]) <= 10000:
        raise ValueError("MATERIAL_NATIVE_PRINTED_NUMBER_INVALID")
    return int(match[1])


class MaterialNativeFileBinding(FrozenModel):
    source_role: Literal["MAIN", "SOLUTIONS"]
    original_source_sha256: Sha256
    native_source_sha256: Sha256
    document: MaterialArtifactMember
    split_evidence: MaterialArtifactMember
    split_plan_sha256: Sha256
    ranges: tuple[NativeParagraphRange, ...] = Field(min_length=1, max_length=10000)

    @model_validator(mode="after")
    def exact_native_members(self) -> Self:
        if (
            self.document.schema_ref != NATIVE_ITEM_DOCUMENT_REF
            or self.document.media_type not in _HWPX_MEDIA
            or self.split_evidence.schema_ref != NATIVE_ITEM_SPLIT_EVIDENCE_REF
            or self.split_evidence.media_type != "application/json"
            or (self.document.artifact_revision_id, self.document.member_path)
            == (self.split_evidence.artifact_revision_id, self.split_evidence.member_path)
            or len({part.section_member for part in self.ranges}) != len(self.ranges)
        ):
            raise ValueError("MATERIAL_NATIVE_FILE_BINDING_INVALID")
        return self


class MaterialNativeWorkbookRow(FrozenModel):
    workbook: MaterialArtifactMember
    parsed_workbook: MaterialArtifactMember
    worksheet_name: str = Field(min_length=1, max_length=255)
    row_number: int = Field(strict=True, ge=1, le=1048576)
    row_sha256: Sha256

    _text = field_validator("worksheet_name")(_safe_text)

    @model_validator(mode="after")
    def exact_workbook_members(self) -> Self:
        require_material_native_workbook_members(self.workbook, self.parsed_workbook)
        return self


def require_material_native_workbook_members(
    workbook: MaterialArtifactMember, parsed_workbook: MaterialArtifactMember
) -> None:
    """One media/identity rule shared by exam-wide and item-specific workbook references."""
    if (
        workbook.media_type != _WORKBOOK_MEDIA
        or parsed_workbook.media_type != "application/json"
        or parsed_workbook.schema_ref != NATIVE_WORKBOOK_MANIFEST_REF
        or (workbook.artifact_revision_id, workbook.member_path)
        == (parsed_workbook.artifact_revision_id, parsed_workbook.member_path)
    ):
        raise ValueError("MATERIAL_NATIVE_WORKBOOK_BINDING_INVALID")


class MaterialNativeSourceMetadata(FrozenModel):
    external_number: str | None = Field(pattern=r"^[0-9]{5}$")
    original_unit: str | None = Field(max_length=32767)
    original_classification: str | None = Field(max_length=32767)
    source_name: str = Field(max_length=32767)

    _text = field_validator("original_unit", "original_classification", "source_name")(
        lambda value: None if value is None else _safe_text(value)
    )


class MaterialNativeItemBinding(FrozenModel):
    schema_version: Literal["material-native-item-binding/1.0"] = "material-native-item-binding/1.0"
    material_id: str = Field(pattern=r"^material_[0-9a-f]{32}$")
    material_revision_id: str = Field(pattern=r"^materialrev_[0-9a-f]{32}$")
    unit_key: str = Field(min_length=1, max_length=128)
    source_namespace: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    exam_key: str = Field(min_length=1, max_length=256)
    item_number: NativeNumber
    printed_label: str = Field(min_length=1, max_length=100)
    question: MaterialNativeFileBinding
    solution: MaterialNativeFileBinding
    workbook: MaterialNativeWorkbookRow
    source_metadata: MaterialNativeSourceMetadata
    binding_sha256: Sha256

    _text = field_validator("unit_key", "exam_key", "printed_label")(_safe_text)

    @model_validator(mode="after")
    def exact_source_binding(self) -> Self:
        if (
            self.question.source_role != "MAIN"
            or self.solution.source_role != "SOLUTIONS"
            or self.question.original_source_sha256 == self.solution.original_source_sha256
            or material_native_printed_number(self.printed_label) != self.item_number
            or self.binding_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"binding_sha256"}))
        ):
            raise ValueError("MATERIAL_NATIVE_ITEM_BINDING_INVALID")
        validate_contract("material-native-item-binding-v1", self.model_dump(mode="json"))
        return self


def material_native_source_identity(binding: MaterialNativeItemBinding) -> str:
    """Stable source key, not a cross-user authorization or Registry admission key.

    A later XLSX revision or supplied external number does not create a different
    source question. Actual registration still belongs to its authorized owner.
    """
    return content_sha256(
        {
            "source_namespace": binding.source_namespace,
            "exam_key": binding.exam_key,
            "main_sha256": binding.question.original_source_sha256,
            "solutions_sha256": binding.solution.original_source_sha256,
            "item_number": binding.item_number,
        }
    )


def material_native_registration_key(operator_id: str, binding: MaterialNativeItemBinding) -> str:
    """Existing Registry key, not authority: callers authorize the actual operator first.

    Workbook metadata revisions do not create another source Item. A later
    metadata change must use its explicit successor use case, not CREATE_ITEM.
    """
    return "material-native-item:" + content_sha256(
        {
            "operator_id": operator_id,
            "source_identity_sha256": material_native_source_identity(binding),
        }
    ).removeprefix("sha256:")


def require_material_native_binding_for_work(
    binding: MaterialNativeItemBinding, work: MaterialExtractionWork
) -> None:
    """The caller resolves/authorizes bytes first; this compares exact value identity."""
    if (
        binding.material_id != work.material_id
        or binding.material_revision_id != work.material_revision_id
        or binding.unit_key != work.unit_key
        or material_native_printed_number(work.question.printed_label) != binding.item_number
        or any(anchor.source_role != "MAIN" for anchor in work.question.anchors)
    ):
        raise ValueError("MATERIAL_NATIVE_WORK_BINDING_MISMATCH")
    sources = {source.source_role: source for source in work.sources}
    if set(sources) != {"MAIN", "SOLUTIONS"} or any(
        sources[file.source_role].original.sha256 != file.original_source_sha256
        or sources[file.source_role].actual_format not in {"HWP", "HWPX"}
        or (
            sources[file.source_role].actual_format == "HWPX"
            and file.original_source_sha256 != file.native_source_sha256
        )
        for file in (binding.question, binding.solution)
    ):
        raise ValueError("MATERIAL_NATIVE_ORIGINAL_SOURCE_MISMATCH")
    solutions = tuple(solution for solution in work.solutions if solution.kind == "SOLUTION")
    if not solutions or any(
        material_native_printed_number(solution.printed_label) != binding.item_number
        or any(anchor.source_role != "SOLUTIONS" for anchor in solution.anchors)
        for solution in solutions
    ):
        raise ValueError("MATERIAL_NATIVE_SOLUTION_BINDING_MISMATCH")


def require_material_native_split_result(
    file: MaterialNativeFileBinding, result: NativeItemSplitResult, *, item_number: int
) -> None:
    """Compare a hash-verified, parsed split receipt to its selected native member."""
    if (
        result.source_sha256 != file.native_source_sha256
        or result.plan_sha256 != file.split_plan_sha256
        or result.source_role != file.source_role
        or result.item_number != item_number
        or result.ranges != file.ranges
        or result.output_sha256 != file.document.sha256
        or result.output_size_bytes != file.document.bytes
    ):
        raise ValueError("MATERIAL_NATIVE_SPLIT_EVIDENCE_MISMATCH")


@dataclass(frozen=True, slots=True)
class MaterialNativeWorkbookSelection:
    row: MaterialNativeWorkbookRow
    item_number: int
    source_metadata: MaterialNativeSourceMetadata


def require_material_native_workbook_selections(
    selections: tuple[MaterialNativeWorkbookSelection, ...], workbook: NativeExamWorkbookDocument
) -> None:
    """Validate one workbook batch in O(cells + rows + selected items), without N+1 scans.

    The application must hash-verify the original and parsed Artifact members
    before this pure comparison. The source key intentionally excludes row data.
    """
    if not 1 <= len(selections) <= 10000:
        raise ValueError("MATERIAL_NATIVE_WORKBOOK_BATCH_INVALID")
    sheets = {sheet.name: sheet for sheet in workbook.worksheets}
    rows = {
        (sheet.name, row.row_number): row for sheet in workbook.worksheets for row in sheet.rows
    }
    cells = {
        (sheet.name, cell.reference): cell.value
        for sheet in workbook.worksheets
        for cell in sheet.cells
    }
    classification_columns = {
        sheet.name: tuple(
            column.column for column in sheet.columns if column.semantic == "CLASSIFICATION"
        )
        for sheet in workbook.worksheets
    }
    for selection in selections:
        pointer = selection.row
        row = rows.get((pointer.worksheet_name, pointer.row_number))
        if (
            pointer.workbook.sha256 != workbook.sha256
            or pointer.workbook.bytes != workbook.bytes
            or pointer.worksheet_name not in sheets
            or row is None
            or pointer.row_sha256 != content_sha256(row.model_dump(mode="json"))
            or row.question_number != selection.item_number
            or row.external_number != selection.source_metadata.external_number
            or row.unit_raw != selection.source_metadata.original_unit
            or row.source_label != selection.source_metadata.source_name
        ):
            raise ValueError("MATERIAL_NATIVE_WORKBOOK_ROW_MISMATCH")
        classes = {
            cells.get((pointer.worksheet_name, f"{column}{pointer.row_number}"))
            for column in classification_columns[pointer.worksheet_name]
        }
        expected_class = next(iter(classes)) if classes else None
        if len(classes) > 1 or expected_class != selection.source_metadata.original_classification:
            raise ValueError("MATERIAL_NATIVE_WORKBOOK_CLASSIFICATION_MISMATCH")


def require_material_native_workbook_rows(
    bindings: tuple[MaterialNativeItemBinding, ...], workbook: NativeExamWorkbookDocument
) -> None:
    """The same row validator for already discovered material units."""
    identities = tuple((binding.material_revision_id, binding.unit_key) for binding in bindings)
    if len(identities) != len(set(identities)):
        raise ValueError("MATERIAL_NATIVE_WORKBOOK_UNIT_DUPLICATED")
    require_material_native_workbook_selections(
        tuple(
            MaterialNativeWorkbookSelection(
                binding.workbook, binding.item_number, binding.source_metadata
            )
            for binding in bindings
        ),
        workbook,
    )


class MaterialImportedNativeItemMetadata(FrozenModel):
    """V2 adds native/source metadata without changing V1 or implying scientific approval."""

    schema_version: Literal["material-imported-native-item-metadata/2.0"] = (
        "material-imported-native-item-metadata/2.0"
    )
    item_type_key: Literal["uploaded-material-item"] = "uploaded-material-item"
    source_kind: Literal["EXTERNAL"] = "EXTERNAL"
    material_id: str = Field(pattern=r"^material_[0-9a-f]{32}$")
    material_revision_id: str = Field(pattern=r"^materialrev_[0-9a-f]{32}$")
    unit_key: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    source_filename: str = Field(min_length=1, max_length=255)
    printed_label: str = Field(min_length=1, max_length=100)
    section_path: tuple[str, ...] = Field(max_length=12)
    physical_pages: tuple[Annotated[int, Field(strict=True, ge=1, le=2000)], ...] = Field(
        min_length=1, max_length=32
    )
    lineage_sha256: Sha256
    approval_basis: Literal["SOURCE_IMPORT_AUTOMATION_NOT_SCIENTIFIC_VERIFICATION"] = (
        "SOURCE_IMPORT_AUTOMATION_NOT_SCIENTIFIC_VERIFICATION"
    )
    native_binding: MaterialArtifactMember
    item_number: NativeNumber
    external_number: str | None = Field(pattern=r"^[0-9]{5}$")
    original_unit: str | None = Field(max_length=32767)
    original_classification: str | None = Field(max_length=32767)
    source_name: str = Field(max_length=32767)

    _text = field_validator(
        "unit_key",
        "title",
        "source_filename",
        "printed_label",
        "original_unit",
        "original_classification",
        "source_name",
    )(lambda value: None if value is None else _safe_text(value))

    @model_validator(mode="after")
    def declared_native_metadata(self) -> Self:
        if (
            len(self.physical_pages) != len(set(self.physical_pages))
            or any(not 1 <= len(value) <= 200 for value in self.section_path)
            or self.native_binding.schema_ref != MATERIAL_NATIVE_BINDING_REF
            or self.native_binding.media_type != "application/json"
            or material_native_printed_number(self.printed_label) != self.item_number
        ):
            raise ValueError("MATERIAL_NATIVE_ITEM_METADATA_INVALID")
        for value in self.section_path:
            _safe_text(value)
        validate_contract("material-learning-item-metadata-v2", self.model_dump(mode="json"))
        return self


def require_material_native_metadata_binding(
    metadata: MaterialImportedNativeItemMetadata, binding: MaterialNativeItemBinding
) -> None:
    """Duplicate small read fields must agree with the authorized canonical binding."""
    if (
        metadata.material_id != binding.material_id
        or metadata.material_revision_id != binding.material_revision_id
        or metadata.unit_key != binding.unit_key
        or metadata.item_number != binding.item_number
        or metadata.external_number != binding.source_metadata.external_number
        or metadata.original_unit != binding.source_metadata.original_unit
        or metadata.original_classification != binding.source_metadata.original_classification
        or metadata.source_name != binding.source_metadata.source_name
    ):
        raise ValueError("MATERIAL_NATIVE_METADATA_BINDING_MISMATCH")
