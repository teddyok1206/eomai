"""Small local evidence and fixed installed-tool identities for native HWP conversion."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from eom_hwpx_contracts.models import StrictModel

Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
NativeCount = Annotated[int, Field(strict=True, ge=0, le=10000)]


class NativeHwpShapeCounts(StrictModel):
    pic: NativeCount
    container: NativeCount
    rect: NativeCount
    ellipse: NativeCount
    arc: NativeCount
    polygon: NativeCount
    curve: NativeCount
    line: NativeCount
    connectLine: NativeCount


class NativeHwpConversionEvidence(StrictModel):
    schema_version: Literal["native-hwp-conversion-evidence/1.0"]
    source_sha256: Sha256
    candidate_sha256: Sha256
    section_count: int = Field(strict=True, ge=1, le=10000)
    paragraph_sha256: tuple[Sha256, ...] = Field(min_length=1, max_length=100000)
    table_sha256: tuple[Sha256, ...] = Field(max_length=10000)
    equation_sha256: tuple[Sha256, ...] = Field(max_length=10000)
    binary_sha256: tuple[Sha256, ...] = Field(max_length=10000)
    shape_counts: NativeHwpShapeCounts


class NativeHwpConverterFile(StrictModel):
    filename: Literal["converter.jar", "hwplib-1.1.10.jar", "hwpxlib-1.0.9.jar"]
    sha256: Sha256
    size_bytes: int = Field(strict=True, ge=1, le=16 * 1024 * 1024)


class NativeHwpConverterBundle(StrictModel):
    schema_version: Literal["native-hwp-converter-bundle/1.0"]
    source_commit: Literal["62d95b980a4e3a6766877dd3fb6f7f45f4afcf3d"]
    java_sha256: Sha256
    files: tuple[NativeHwpConverterFile, ...] = Field(min_length=3, max_length=3)
    bundle_sha256: Sha256

    @model_validator(mode="after")
    def complete_immutable_bundle(self) -> Self:
        if tuple(file.filename for file in self.files) != (
            "converter.jar",
            "hwplib-1.1.10.jar",
            "hwpxlib-1.0.9.jar",
        ):
            raise ValueError("converter bundle must pin exactly its ordered installed files")
        value = self.model_dump(mode="json", exclude={"bundle_sha256"})
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        if self.bundle_sha256 != "sha256:" + hashlib.sha256(encoded).hexdigest():
            raise ValueError("converter bundle hash differs")
        return self
