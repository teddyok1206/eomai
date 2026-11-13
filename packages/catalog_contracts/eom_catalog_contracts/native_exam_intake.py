"""Immutable native-exam transport observations, not registration or execution authority."""

from __future__ import annotations

import unicodedata
from typing import Literal, Self

from pydantic import Field, model_validator

from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.validation import validate_contract

NativeExamSemantic = Literal[
    "QUESTION_NUMBER",
    "UNIT",
    "SOURCE_LABEL",
    "AUTHOR",
    "POINTS",
    "DIFFICULTY",
    "INQUIRY",
    "CLASSIFICATION",
    "GRADE",
    "SUBJECT",
    "EXTERNAL_NUMBER",
    "UNMAPPED",
]


def _safe_path(value: str) -> None:
    if (
        not value
        or value.startswith("/")
        or "\\" in value
        or ":" in value
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ValueError("NATIVE_EXAM_MEMBER_PATH_INVALID")


class NativeExamArchiveMember(FrozenModel):
    zip_member: str = Field(min_length=1, max_length=2048)
    member_path: str = Field(min_length=1, max_length=2048)
    source_format: Literal["HWP", "HWPX", "XLSX"]
    sha256: Sha256
    bytes: int = Field(strict=True, ge=8, le=128 * 1024 * 1024)

    @model_validator(mode="after")
    def safe_location(self) -> Self:
        _safe_path(self.zip_member)
        _safe_path(self.member_path)
        if unicodedata.normalize("NFC", self.member_path) != self.member_path:
            raise ValueError("NATIVE_EXAM_MEMBER_PATH_NOT_NORMALIZED")
        return self


class NativeExamFolder(FrozenModel):
    folder_path: str = Field(min_length=1, max_length=2048)
    question: NativeExamArchiveMember
    solutions: NativeExamArchiveMember
    workbook: NativeExamArchiveMember | None

    @model_validator(mode="after")
    def exact_members(self) -> Self:
        _safe_path(self.folder_path)
        members = (self.question, self.solutions) + ((self.workbook,) if self.workbook else ())
        if (
            self.question.source_format == "XLSX"
            or self.solutions.source_format == "XLSX"
            or (self.workbook is not None and self.workbook.source_format != "XLSX")
            or len({m.member_path for m in members}) != len(members)
            or any(m.member_path.rsplit("/", 1)[0] != self.folder_path for m in members)
        ):
            raise ValueError("NATIVE_EXAM_FOLDER_MEMBERS_INVALID")
        return self


class NativeExamArchiveInventory(FrozenModel):
    schema_version: Literal["material-native-exam-archive/1.0"] = "material-native-exam-archive/1.0"
    sha256: Sha256
    bytes: int = Field(strict=True, ge=8, le=512 * 1024 * 1024)
    folders: tuple[NativeExamFolder, ...] = Field(min_length=1, max_length=128)
    ignored_metadata_count: int = Field(strict=True, ge=0, le=2000)

    @model_validator(mode="after")
    def unique_folders(self) -> Self:
        if len({f.folder_path.casefold() for f in self.folders}) != len(self.folders):
            raise ValueError("NATIVE_EXAM_FOLDER_DUPLICATED")
        validate_contract("material-native-exam-v1", self.model_dump(mode="json"))
        return self


class NativeExamFormulaAttribute(FrozenModel):
    name: str = Field(min_length=1, max_length=200)
    value: str = Field(max_length=32767)


class NativeExamCell(FrozenModel):
    reference: str = Field(pattern=r"^[A-Z]{1,3}[1-9][0-9]{0,6}$")
    value: str | None = Field(max_length=32767)
    raw_value: str | None = Field(max_length=32767)
    storage_type: Literal["n", "s", "inlineStr", "str", "b", "e", "d"]
    formula: str | None = Field(max_length=32767)
    formula_attributes: tuple[NativeExamFormulaAttribute, ...] = Field(max_length=16)


class NativeExamColumn(FrozenModel):
    column: str = Field(pattern=r"^[A-Z]{1,3}$")
    header: str = Field(max_length=32767)
    semantic: NativeExamSemantic


class NativeExamWorkbookRow(FrozenModel):
    row_number: int = Field(strict=True, ge=1, le=1048576)
    question_number: int = Field(strict=True, ge=1, le=10000)
    external_number: str | None = Field(pattern=r"^[0-9]{5}$")
    unit_raw: str = Field(max_length=32767)
    unit_normalized: str = Field(max_length=32767)
    source_label: str = Field(max_length=32767)

    @model_validator(mode="after")
    def exact_normalization(self) -> Self:
        if self.unit_normalized != unicodedata.normalize("NFC", self.unit_raw).strip():
            raise ValueError("NATIVE_EXAM_UNIT_NORMALIZATION_INVALID")
        return self


class NativeExamWorksheet(FrozenModel):
    name: str = Field(min_length=1, max_length=255)
    member_path: str = Field(min_length=1, max_length=512)
    header_row: int | None = Field(strict=True, ge=1, le=100)
    external_number_basis: Literal["EXPLICIT_HEADER", "RIGHTMOST_UNTITLED_FIVE_DIGIT", "ABSENT"]
    columns: tuple[NativeExamColumn, ...] = Field(max_length=256)
    cells: tuple[NativeExamCell, ...] = Field(max_length=100000)
    rows: tuple[NativeExamWorkbookRow, ...] = Field(max_length=10000)

    @model_validator(mode="after")
    def coherent_observations(self) -> Self:
        _safe_path(self.member_path)
        references = {c.reference: c for c in self.cells}
        if len(references) != len(self.cells):
            raise ValueError("NATIVE_EXAM_CELL_DUPLICATED")
        if len({c.column for c in self.columns}) != len(self.columns):
            raise ValueError("NATIVE_EXAM_COLUMN_DUPLICATED")
        if self.header_row is None and (self.columns or self.rows):
            raise ValueError("NATIVE_EXAM_HEADER_MISSING")
        if len({r.question_number for r in self.rows}) != len(self.rows):
            raise ValueError("NATIVE_EXAM_QUESTION_DUPLICATED")
        for column in self.columns:
            cell = references.get(column.column + str(self.header_row))
            if column.header != ((cell.value or "") if cell is not None else ""):
                raise ValueError("NATIVE_EXAM_HEADER_OBSERVATION_MISMATCH")
        expected_semantics = {"QUESTION_NUMBER", "UNIT", "SOURCE_LABEL", "EXTERNAL_NUMBER"}
        selected = {
            key: tuple(c.column for c in self.columns if c.semantic == key)
            for key in expected_semantics
        }
        if self.rows and len(selected["QUESTION_NUMBER"]) != 1:
            raise ValueError("NATIVE_EXAM_QUESTION_COLUMN_INVALID")
        if self.external_number_basis == "ABSENT" and selected["EXTERNAL_NUMBER"]:
            raise ValueError("NATIVE_EXAM_EXTERNAL_NUMBER_BASIS_INVALID")
        if self.external_number_basis != "ABSENT" and len(selected["EXTERNAL_NUMBER"]) != 1:
            raise ValueError("NATIVE_EXAM_EXTERNAL_NUMBER_BASIS_INVALID")
        previous = 0
        for row in self.rows:
            if row.row_number <= previous or (
                self.header_row is not None and row.row_number <= self.header_row
            ):
                raise ValueError("NATIVE_EXAM_ROW_ORDER_INVALID")
            previous = row.row_number
            expected = {
                "QUESTION_NUMBER": str(row.question_number),
                "UNIT": row.unit_raw,
                "SOURCE_LABEL": row.source_label,
                "EXTERNAL_NUMBER": row.external_number or "",
            }
            for key, value in expected.items():
                observations = tuple(references.get(c + str(row.row_number)) for c in selected[key])
                if any(c is not None and c.formula is not None for c in observations):
                    raise ValueError("NATIVE_EXAM_MAPPED_FORMULA_UNSUPPORTED")
                actual = tuple((c.value or "") if c is not None else "" for c in observations)
                if any(v != value for v in actual) or (not actual and value):
                    raise ValueError("NATIVE_EXAM_ROW_OBSERVATION_MISMATCH")
        return self


class NativeExamWorkbookDocument(FrozenModel):
    schema_version: Literal["material-native-exam-workbook/1.0"] = (
        "material-native-exam-workbook/1.0"
    )
    sha256: Sha256
    bytes: int = Field(strict=True, ge=8, le=8 * 1024 * 1024)
    worksheets: tuple[NativeExamWorksheet, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def single_question_mapping(self) -> Self:
        if len({s.name for s in self.worksheets}) != len(self.worksheets):
            raise ValueError("NATIVE_EXAM_SHEET_DUPLICATED")
        if sum(bool(s.rows) for s in self.worksheets) != 1:
            raise ValueError("NATIVE_EXAM_QUESTION_SHEET_AMBIGUOUS")
        external = [r.external_number for s in self.worksheets for r in s.rows if r.external_number]
        if len(external) != len(set(external)):
            raise ValueError("NATIVE_EXAM_EXTERNAL_NUMBER_DUPLICATED")
        validate_contract("material-native-exam-v1", self.model_dump(mode="json"))
        return self
