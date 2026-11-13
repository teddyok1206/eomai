"""Immutable native paragraph ranges; no parser, storage or executable authority."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from eom_hwpx_contracts.models import StrictModel
from eom_hwpx_contracts.validation import validate_contract

Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
ItemNumber = Annotated[int, Field(strict=True, ge=1, le=10000)]
SourceRole = Literal["MAIN", "SOLUTIONS"]


def native_split_contract_sha256(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class NativeParagraphRange(StrictModel):
    section_member: str = Field(pattern=r"^Contents/section[0-9]+\.xml$")
    start_paragraph: int = Field(strict=True, ge=0, le=100000)
    end_paragraph: int = Field(strict=True, ge=1, le=100000)
    subtree_sha256: Sha256

    @model_validator(mode="after")
    def nonempty_range(self) -> Self:
        if self.start_paragraph >= self.end_paragraph:
            raise ValueError("NATIVE_ITEM_SPLIT_RANGE_EMPTY")
        return self


class NativeItemSelection(StrictModel):
    item_number: ItemNumber
    ranges: tuple[NativeParagraphRange, ...] = Field(min_length=1, max_length=10000)

    @model_validator(mode="after")
    def unique_sections(self) -> Self:
        if len({part.section_member for part in self.ranges}) != len(self.ranges):
            raise ValueError("NATIVE_ITEM_SPLIT_REPEATED_SECTION")
        return self


class NativeItemSplitPlan(StrictModel):
    schema_version: Literal["native-item-split-plan/1.0"] = "native-item-split-plan/1.0"
    profile: Literal["DIRECT_NATIVE_PARAGRAPHS_V1"] = "DIRECT_NATIVE_PARAGRAPHS_V1"
    source_sha256: Sha256
    source_role: SourceRole
    items: tuple[NativeItemSelection, ...] = Field(min_length=1, max_length=10000)
    plan_sha256: Sha256

    @model_validator(mode="after")
    def exact_pinned_plan(self) -> Self:
        numbers = tuple(item.item_number for item in self.items)
        if len(set(numbers)) != len(numbers) or numbers != tuple(sorted(numbers)):
            raise ValueError("NATIVE_ITEM_SPLIT_NUMBERS_INVALID")
        if self.plan_sha256 != native_split_contract_sha256(
            self.model_dump(mode="json", exclude={"plan_sha256"})
        ):
            raise ValueError("NATIVE_ITEM_SPLIT_PLAN_HASH_MISMATCH")
        validate_contract("native-item-split", self.model_dump(mode="json"))
        return self


class NativeItemCounts(StrictModel):
    paragraphs: int = Field(strict=True, ge=1, le=100000)
    tables: int = Field(strict=True, ge=0, le=100000)
    equations: int = Field(strict=True, ge=0, le=100000)
    pictures: int = Field(strict=True, ge=0, le=100000)


class NativeItemExcludedSourcePart(StrictModel):
    """Only the byte-exact reviewed empty editor template may be sanitized out."""

    member_path: Literal["Scripts/headerScripts", "Scripts/sourceScripts"]
    sha256: Sha256
    bytes: int = Field(strict=True, ge=1, le=150)
    reason: Literal["EXACT_EMPTY_HANCOM_SCRIPT_TEMPLATE_V1"] = (
        "EXACT_EMPTY_HANCOM_SCRIPT_TEMPLATE_V1"
    )

    @model_validator(mode="after")
    def exact_empty_template_identity(self) -> Self:
        expected = {
            "Scripts/headerScripts": (
                150,
                "sha256:d24eb743b49a913f449c0a4e9ee6e6a9465c890298c769145dba831e7b13b4b0",
            ),
            "Scripts/sourceScripts": (
                80,
                "sha256:6f558fdcd17d07a7d2f29478a6eb3d628c7e3c9c64f049dce4959426c17360d0",
            ),
        }
        if (self.bytes, self.sha256) != expected[self.member_path]:
            raise ValueError("NATIVE_ITEM_SPLIT_EXCLUDED_TEMPLATE_CHANGED")
        return self


class NativeItemSplitResult(StrictModel):
    schema_version: Literal["native-item-split-result/1.0"] = "native-item-split-result/1.0"
    profile: Literal["DIRECT_NATIVE_PARAGRAPHS_V1"] = "DIRECT_NATIVE_PARAGRAPHS_V1"
    source_sha256: Sha256
    plan_sha256: Sha256
    source_role: SourceRole
    item_number: ItemNumber
    ranges: tuple[NativeParagraphRange, ...] = Field(min_length=1, max_length=10000)
    paragraph_sha256: tuple[Sha256, ...] = Field(min_length=1, max_length=100000)
    context_sha256: tuple[Sha256, ...] = Field(max_length=10000)
    binary_sha256: tuple[Sha256, ...] = Field(max_length=10000)
    excluded_source_parts: tuple[NativeItemExcludedSourcePart, ...] = Field(
        default=(), max_length=2
    )
    counts: NativeItemCounts
    output_sha256: Sha256
    output_size_bytes: int = Field(strict=True, ge=1, le=256 * 1024 * 1024)

    @model_validator(mode="after")
    def installed_contract(self) -> Self:
        if self.excluded_source_parts and tuple(
            p.member_path for p in self.excluded_source_parts
        ) != ("Scripts/headerScripts", "Scripts/sourceScripts"):
            raise ValueError("NATIVE_ITEM_SPLIT_EXCLUDED_TEMPLATE_PAIR_INVALID")
        validate_contract("native-item-split", self.model_dump(mode="json"))
        return self
