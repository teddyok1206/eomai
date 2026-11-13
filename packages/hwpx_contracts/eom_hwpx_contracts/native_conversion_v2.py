"""Explicit bounded-reader successor; historical converter contracts stay unchanged."""

from __future__ import annotations

import hashlib
import json
from typing import Literal, Self

from pydantic import Field, model_validator

from eom_hwpx_contracts.models import StrictModel
from eom_hwpx_contracts.native_conversion import (
    NativeCount,
    NativeHwpConverterFile,
    NativeHwpShapeCounts,
    Sha256,
)
from eom_hwpx_contracts.validation import validate_contract

NATIVE_HWP_QUALIFIED_CONVERSION_REF = "eom://schemas/hwpx/native-hwp-qualified-conversion/2.0"


class NativeHwpConverterSnapshotV2(StrictModel):
    profile: Literal["HWP2HWPX_NATIVE_V2"] = "HWP2HWPX_NATIVE_V2"
    source_commit: Literal["62d95b980a4e3a6766877dd3fb6f7f45f4afcf3d"]
    bundle_sha256: Sha256


class NativeHwpConverterBundleV2(StrictModel):
    schema_version: Literal["native-hwp-converter-bundle/2.0"]
    profile: Literal["HWP2HWPX_NATIVE_V2"]
    entrypoint: Literal["eom.hwpx.NativeHwpConverterV2"]
    source_commit: Literal["62d95b980a4e3a6766877dd3fb6f7f45f4afcf3d"]
    adapter_source_sha256: Sha256
    java_sha256: Sha256
    files: tuple[NativeHwpConverterFile, ...] = Field(min_length=3, max_length=3)
    bundle_sha256: Sha256

    @model_validator(mode="after")
    def exact_bundle(self) -> Self:
        if tuple(file.filename for file in self.files) != (
            "converter.jar",
            "hwplib-1.1.10.jar",
            "hwpxlib-1.0.9.jar",
        ):
            raise ValueError("converter V2 bundle file identity differs")
        payload = json.dumps(
            self.model_dump(mode="json", exclude={"bundle_sha256"}),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        if self.bundle_sha256 != "sha256:" + hashlib.sha256(payload).hexdigest():
            raise ValueError("converter V2 bundle hash differs")
        validate_contract("native-hwp-bundle-v2", self.model_dump(mode="json"))
        return self


class NativeHwpAuxiliaryRange(StrictModel):
    source_section: int = Field(strict=True, ge=0, le=9999)
    kind: Literal["LAST", "ANY", "TRAILING"]
    ordinal: int = Field(strict=True, ge=0, le=9999)
    flags: int = Field(strict=True, ge=0, le=4294967295)
    width: int = Field(strict=True, ge=0, le=4294967295)
    height: int = Field(strict=True, ge=0, le=4294967295)
    raw_record_sha256: Sha256
    source_start: int = Field(strict=True, ge=0, le=64 * 1024 * 1024)
    source_end: int = Field(strict=True, ge=1, le=64 * 1024 * 1024)

    @model_validator(mode="after")
    def nonempty_source_range(self) -> Self:
        if self.source_start >= self.source_end:
            raise ValueError("converter V2 auxiliary source range empty")
        return self


class NativeHwpAuxiliaryMasterPage(NativeHwpAuxiliaryRange):
    member_path: str = Field(pattern=r"^Contents/masterpage[0-9]+\.xml$")


class NativeHwpAuxiliaryException(NativeHwpAuxiliaryRange):
    code: Literal["AUXILIARY_MASTERPAGE_FIELD_INVALID"]
    paragraph_sha256: tuple[Sha256, ...] = Field(min_length=1, max_length=100000)
    table_sha256: tuple[Sha256, ...] = Field(max_length=10000)
    equation_sha256: tuple[Sha256, ...] = Field(max_length=10000)
    shape_counts: NativeHwpShapeCounts


class NativeHwpUnboundBinaryMember(StrictModel):
    """Opaque, unreferenced OLE storage remains in the immutable original only."""

    member_path: str = Field(pattern=r"^BinData/BIN[0-9A-Fa-f]{4}\.[A-Za-z0-9]{1,12}$")
    raw_sha256: Sha256
    size_bytes: int = Field(strict=True, ge=0, le=64 * 1024 * 1024)


class NativeHwpConversionEvidenceV2(StrictModel):
    schema_version: Literal["native-hwp-conversion-evidence/2.0"]
    source_sha256: Sha256
    candidate_sha256: Sha256
    section_count: int = Field(strict=True, ge=1, le=10000)
    masterpage_count: NativeCount
    memo_count: NativeCount
    paragraph_sha256: tuple[Sha256, ...] = Field(min_length=1, max_length=100000)
    table_sha256: tuple[Sha256, ...] = Field(max_length=10000)
    equation_sha256: tuple[Sha256, ...] = Field(max_length=10000)
    binary_sha256: tuple[Sha256, ...] = Field(max_length=10000)
    unbound_binary_members: tuple[NativeHwpUnboundBinaryMember, ...] = Field(
        default=(), max_length=10000
    )
    shape_counts: NativeHwpShapeCounts
    auxiliary_master_pages: tuple[NativeHwpAuxiliaryMasterPage, ...] = Field(max_length=10000)
    auxiliary_exceptions: tuple[NativeHwpAuxiliaryException, ...] = Field(max_length=10000)
    whole_paper_layout: Literal["NOT_VERIFIED"]
    warnings: tuple[
        Literal[
            "AUXILIARY_MASTERPAGE_APPLICATION_UNRESOLVED",
            "AUXILIARY_MASTERPAGE_FIELD_INVALID",
            "UNBOUND_BINARY_MEMBERS_RETAINED_IN_SOURCE",
        ],
        ...,
    ] = Field(max_length=3)

    @model_validator(mode="after")
    def explicit_auxiliary_scope(self) -> Self:
        expected = set()
        if self.auxiliary_master_pages:
            expected.add("AUXILIARY_MASTERPAGE_APPLICATION_UNRESOLVED")
        if self.auxiliary_exceptions:
            expected.add("AUXILIARY_MASTERPAGE_FIELD_INVALID")
        if self.unbound_binary_members:
            expected.add("UNBOUND_BINARY_MEMBERS_RETAINED_IN_SOURCE")
        unbound_names = [member.member_path.casefold() for member in self.unbound_binary_members]
        if len(set(unbound_names)) != len(unbound_names):
            raise ValueError("converter V2 unbound member identity is repeated")
        if set(self.warnings) != expected or len(set(self.warnings)) != len(self.warnings):
            raise ValueError("converter V2 auxiliary application warning differs")
        members = tuple(page.member_path for page in self.auxiliary_master_pages)
        if len(set(members)) != len(members) or len(members) > self.masterpage_count:
            raise ValueError("converter V2 auxiliary member identity differs")
        all_auxiliary = (*self.auxiliary_master_pages, *self.auxiliary_exceptions)
        if any(page.source_section >= self.section_count for page in all_auxiliary):
            raise ValueError("converter V2 auxiliary source section differs")
        if len({(page.source_section, page.ordinal) for page in all_auxiliary}) != len(
            all_auxiliary
        ):
            raise ValueError("converter V2 auxiliary source is repeated")
        validate_contract("native-hwp-evidence-v2", self.model_dump(mode="json"))
        return self


class NativeHwpNormalizationReceiptV2(StrictModel):
    candidate_sha256: Sha256
    output_sha256: Sha256
    empty_style_attribute_count: int = Field(strict=True, ge=0, le=1000000)
    expanded_size_attribute_count: int = Field(strict=True, ge=0, le=1000000)
    rebuilt_intent_box_count: int = Field(strict=True, ge=0, le=1000000)


class NativeHwpQualifiedConversionReceiptV2(StrictModel):
    """One canonical proof joins original HWP to the normalized HWPX split source."""

    schema_version: Literal["native-hwp-qualified-conversion/2.0"] = (
        "native-hwp-qualified-conversion/2.0"
    )
    snapshot: NativeHwpConverterSnapshotV2
    evidence: NativeHwpConversionEvidenceV2
    normalization: NativeHwpNormalizationReceiptV2
    core_native_preservation: Literal["PASS"] = "PASS"

    @model_validator(mode="after")
    def exact_candidate_lineage(self) -> Self:
        if self.evidence.candidate_sha256 != self.normalization.candidate_sha256:
            raise ValueError("converter V2 normalization candidate differs")
        validate_contract("native-hwp-qualified-conversion-v2", self.model_dump(mode="json"))
        return self
