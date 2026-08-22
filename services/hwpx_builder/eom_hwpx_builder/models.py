"""Internal analyzer, binding, validation, and render request models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PackageLimits(StrictModel):
    max_package_bytes: int = 50 * 1024 * 1024
    max_entries: int = 2000
    max_member_bytes: int = 25 * 1024 * 1024
    max_uncompressed_bytes: int = 200 * 1024 * 1024
    max_compression_ratio: int = 100
    max_filename_length: int = 240
    max_xml_bytes: int = 10 * 1024 * 1024
    max_xml_depth: int = 128


class EntryRecord(StrictModel):
    name: str
    order: int
    compression_method: int
    compressed_size: int
    uncompressed_size: int
    crc: int
    sha256: str
    is_xml: bool


class PackageAnalysis(StrictModel):
    analysis_version: Literal["1.0"] = "1.0"
    package_sha256: str
    entries: tuple[EntryRecord, ...]
    namespaces: tuple[str, ...]
    mimetype: str | None
    version_info: dict[str, str]
    manifest_items: tuple[dict[str, str], ...]
    spine: tuple[str, ...]
    sections: tuple[str, ...]
    bindata: tuple[str, ...]
    internal_references: tuple[dict[str, str], ...]
    marker_locations: tuple[dict[str, Any], ...]
    image_candidates: tuple[dict[str, str], ...]
    equation_candidates: tuple[dict[str, str], ...]
    active_content: tuple[str, ...]
    external_links: tuple[str, ...]
    unknown_parts: tuple[str, ...]
    warnings: tuple[str, ...]


class BindingKind(StrEnum):
    TEXT_MARKER = "TEXT_MARKER"
    TABLE_CELL_MARKER = "TABLE_CELL_MARKER"
    IMAGE_BINARY = "IMAGE_BINARY"
    EQUATION_SCRIPT = "EQUATION_SCRIPT"
    EQUATION_ANCHOR = "EQUATION_ANCHOR"
    METADATA = "METADATA"


class TemplateBinding(StrictModel):
    field_name: str
    part_name: str
    binding_kind: BindingKind
    locator: dict[str, Any]
    expected_occurrence_count: Literal[1] = 1
    expected_original_value: str
    object_id: str | None = None
    binary_part: str | None = None
    reference_ids: tuple[str, ...] = ()
    constraints: dict[str, Any] = Field(default_factory=dict)


class BindingManifest(StrictModel):
    manifest_version: Literal["1.0"] = "1.0"
    template_id: str = Field(pattern=r"^hwpxtpl_[a-f0-9]{32}$")
    template_revision_id: str = Field(pattern=r"^hwpxrev_[a-f0-9]{32}$")
    template_sha256: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    binding_manifest_sha256: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    bindings: tuple[TemplateBinding, ...]
    warnings: tuple[str, ...] = ()


class CheckStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ValidationCheck(StrictModel):
    check_id: str
    status: CheckStatus
    severity: Literal["INFO", "WARNING", "ERROR"]
    message: str
    part: str | None = None
    locator: str | None = None
    evidence_hash: str | None = None


class StructuralValidationReport(StrictModel):
    report_version: Literal["1.0"] = "1.0"
    status: Literal["PASS", "FAIL"]
    package_sha256: str
    checks: tuple[ValidationCheck, ...]
    metrics: dict[str, int] = Field(default_factory=dict)


class SemanticComparison(StrEnum):
    EXACT_MATCH = "EXACT_MATCH"
    NORMALIZED_MATCH = "NORMALIZED_MATCH"
    MISMATCH = "MISMATCH"
    NOT_EXTRACTABLE = "NOT_EXTRACTABLE"


class SemanticValidationReport(StrictModel):
    report_version: Literal["1.0"] = "1.0"
    status: Literal["PASS", "FAIL"]
    semantic_hash: str
    fields: dict[str, SemanticComparison]
    extracted: dict[str, Any]


class RenderRequest(StrictModel):
    request_version: Literal["1.0"] = "1.0"
    build_id: str = Field(pattern=r"^hwpxbuild_[a-f0-9]{32}$")
    template_id: str = Field(pattern=r"^hwpxtpl_[a-f0-9]{32}$")
    template_revision_id: str = Field(pattern=r"^hwpxrev_[a-f0-9]{32}$")
    template_sha256: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    template_file: Literal["template.hwpx"] = "template.hwpx"
    bindings_file: Literal["template-bindings.json"] = "template-bindings.json"
    document_file: Literal["input/document.json"] = "input/document.json"
    image_file: Literal["input/eom-placeholder-image-output.png"] = (
        "input/eom-placeholder-image-output.png"
    )
    output_directory: Literal["output"] = "output"
