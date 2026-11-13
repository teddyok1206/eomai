"""Small file-only request and exact ZIP closure; no runtime or persistence behavior."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from eom_hwpx_contracts.models import StrictModel
from eom_hwpx_contracts.native_conversion import Sha256
from eom_hwpx_contracts.native_conversion_v2 import NativeHwpConverterSnapshotV2
from eom_hwpx_contracts.validation import validate_contract

NATIVE_EXAM_FILE_PREPARATION_REF = "eom://schemas/hwpx/native-exam-file-preparation/1.0"
NATIVE_EXAM_SOURCE_LIMIT = 50 * 1024 * 1024
NATIVE_EXAM_ZIP_LIMIT = 512 * 1024 * 1024
NATIVE_EXAM_MATERIAL_LIMIT = 500 * 1024 * 1024
NATIVE_EXAM_REQUEST_LIMIT = 64 * 1024
NATIVE_EXAM_RESULT_LIMIT = 2 * 1024 * 1024
NativeExamNumber = Annotated[int, Field(strict=True, ge=1, le=10000)]


def native_exam_preparation_sha256(value: object) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(data).hexdigest()


class NativeExamFilePreparationRequest(StrictModel):
    schema_version: Literal["native-exam-file-preparation-request/1.0"] = (
        "native-exam-file-preparation-request/1.0"
    )
    expected_source_sha256: Sha256
    source_format: Literal["HWP", "HWPX"]
    source_role: Literal["MAIN", "SOLUTIONS"]
    expected_numbers: tuple[NativeExamNumber, ...] = Field(min_length=1, max_length=128)
    converter: NativeHwpConverterSnapshotV2 | None

    @model_validator(mode="after")
    def exact_native_input(self) -> Self:
        if self.expected_numbers != tuple(sorted(set(self.expected_numbers))):
            raise ValueError("NATIVE_EXAM_PREPARATION_NUMBERS_INVALID")
        if (self.source_format == "HWP") != (self.converter is not None):
            raise ValueError("NATIVE_EXAM_PREPARATION_CONVERTER_MISMATCH")
        validate_contract("native-exam-file-preparation", self.model_dump(mode="json"))
        return self


class NativeExamPreparedMember(StrictModel):
    member_path: str = Field(
        pattern=r"^(items/[0-9]{3,5}\.hwpx|splits/[0-9]{3,5}\.json|conversion\.json)$"
    )
    sha256: Sha256
    bytes: int = Field(strict=True, ge=1, le=64 * 1024 * 1024)
    media_type: Literal["application/vnd.hancom.hwpx", "application/json"]


class NativeExamPreparedItem(StrictModel):
    item_number: NativeExamNumber
    document: NativeExamPreparedMember
    split_evidence: NativeExamPreparedMember

    @model_validator(mode="after")
    def fixed_members(self) -> Self:
        label = f"{self.item_number:03d}"
        if (
            self.document.member_path != f"items/{label}.hwpx"
            or self.document.media_type != "application/vnd.hancom.hwpx"
            or self.split_evidence.member_path != f"splits/{label}.json"
            or self.split_evidence.media_type != "application/json"
            or self.split_evidence.bytes > 4 * 1024 * 1024
        ):
            raise ValueError("NATIVE_EXAM_PREPARATION_ITEM_MEMBER_INVALID")
        return self


class NativeExamFilePreparationResult(StrictModel):
    schema_version: Literal["native-exam-file-preparation-result/1.0"] = (
        "native-exam-file-preparation-result/1.0"
    )
    profile: Literal["HANCOM_NATIVE_EXAM_FILES_V1"] = "HANCOM_NATIVE_EXAM_FILES_V1"
    request_sha256: Sha256
    original_source_sha256: Sha256
    native_source_sha256: Sha256
    source_format: Literal["HWP", "HWPX"]
    source_role: Literal["MAIN", "SOLUTIONS"]
    expected_numbers: tuple[NativeExamNumber, ...] = Field(min_length=1, max_length=128)
    plan_sha256: Sha256
    items: tuple[NativeExamPreparedItem, ...] = Field(min_length=1, max_length=128)
    conversion: NativeExamPreparedMember | None
    materialized_bytes: int = Field(strict=True, ge=1, le=NATIVE_EXAM_MATERIAL_LIMIT)

    @model_validator(mode="after")
    def exact_output_closure(self) -> Self:
        if (
            self.expected_numbers != tuple(sorted(set(self.expected_numbers)))
            or tuple(item.item_number for item in self.items) != self.expected_numbers
        ):
            raise ValueError("NATIVE_EXAM_PREPARATION_RESULT_NUMBERS_INVALID")
        if self.source_format == "HWPX":
            if (
                self.conversion is not None
                or self.native_source_sha256 != self.original_source_sha256
            ):
                raise ValueError("NATIVE_EXAM_PREPARATION_IDENTITY_MISMATCH")
        elif (
            self.conversion is None
            or self.conversion.member_path != "conversion.json"
            or self.conversion.media_type != "application/json"
            or self.conversion.bytes > 16 * 1024 * 1024
        ):
            raise ValueError("NATIVE_EXAM_PREPARATION_CONVERSION_MISSING")
        members = [member for item in self.items for member in (item.document, item.split_evidence)]
        if self.conversion is not None:
            members.append(self.conversion)
        if self.materialized_bytes != sum(member.bytes for member in members):
            raise ValueError("NATIVE_EXAM_PREPARATION_RESULT_SIZE_MISMATCH")
        validate_contract("native-exam-file-preparation", self.model_dump(mode="json"))
        return self
