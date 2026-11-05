"""Mixed document learning values; references confer no source/execution authority.

The installed JSON Schema owns the wire shape. Owners resolve Artifacts and
permissions; these pure values enforce bounded coverage and source closure.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from eom_identifiers import content_sha256
from pydantic import ConfigDict, Field, field_validator, model_validator

from eom_catalog_contracts.creative_source_draft import SourceImageBlock
from eom_catalog_contracts.external_item_learning_result_v2 import SourceItemLearningObservation
from eom_catalog_contracts.item_origin import OriginArtifactMemberPointer
from eom_catalog_contracts.legacy_assessment import NormalizedBoundingBox
from eom_catalog_contracts.models import ActorId, FrozenModel, Sha256, UtcDatetime, _safe_text
from eom_catalog_contracts.office_item_learning import OfficeVisualBindings
from eom_catalog_contracts.validation import validate_contract

SourceRole = Literal["MAIN", "SOLUTIONS"]
MaterialKind = Literal["TEXTBOOK", "REFERENCE_BOOK", "WORKBOOK", "MOCK_EXAM", "OTHER"]
UnitKind = Literal["EXPLANATION", "QUESTION", "SOLUTION", "ANSWER_KEY"]
SafeLabel = Annotated[str, Field(min_length=1, max_length=160)]
PERMITTED_USES = (
    "INTERNAL_ANALYSIS",
    "ITEM_REGISTRATION",
    "GRAPH_RETRIEVAL",
    "LOCAL_EMBEDDING",
)


def require_material_rights_confirmation(value: object) -> object:
    if value is not True:
        raise ValueError("MATERIAL_LEARNING_RIGHTS_CONFIRMATION_REQUIRED")
    return value


class MaterialLearningUpload(FrozenModel):
    schema_version: Literal["material-learning-upload/1.0"] = "material-learning-upload/1.0"
    title: str = Field(min_length=1, max_length=200)
    material_kind: MaterialKind
    source_description: str = Field(min_length=1, max_length=2000)
    additional_instructions: str = Field(max_length=8000)
    curriculum_unit_hints: tuple[SafeLabel, ...] = Field(max_length=16)
    rights_confirmed: Literal[True]

    _text = field_validator("title", "source_description", "additional_instructions")(_safe_text)

    @field_validator("rights_confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value: object) -> object:
        return require_material_rights_confirmation(value)

    @model_validator(mode="after")
    def closed_upload(self) -> Self:
        validate_contract("material-learning-upload-v1", self.model_dump(mode="json"))
        if not self.title.strip() or not self.source_description.strip():
            raise ValueError("MATERIAL_LEARNING_DESCRIPTION_REQUIRED")
        for hint in self.curriculum_unit_hints:
            _safe_text(hint)
            if not hint.strip():
                raise ValueError("MATERIAL_LEARNING_UNIT_HINT_INVALID")
        return self


class MaterialLearningRights(FrozenModel):
    schema_version: Literal["material-learning-rights/1.0"] = "material-learning-rights/1.0"
    material_id: str = Field(pattern=r"^material_[0-9a-f]{32}$")
    material_revision_id: str = Field(pattern=r"^materialrev_[0-9a-f]{32}$")
    attested_by: ActorId
    attested_at: UtcDatetime
    basis: Literal["UPLOADER_ATTESTED_INTERNAL_PROCESSING"]
    source_hashes: tuple[Sha256, ...] = Field(min_length=1, max_length=2)
    permitted_uses: tuple[str, ...] = Field(min_length=4, max_length=4)
    public_redistribution_permitted: Literal[False]
    withdrawal_policy: Literal["DENY_NEW_RESOLUTION_PRESERVE_PINNED_AUDIT"]
    attestation_sha256: Sha256

    @model_validator(mode="after")
    def exact_attestation(self) -> Self:
        document = self.model_dump(mode="json")
        validate_contract("material-learning-rights-v1", document)
        if self.permitted_uses != PERMITTED_USES:
            raise ValueError("MATERIAL_LEARNING_RIGHTS_USES_DIFFER")
        if self.attestation_sha256 != content_sha256(
            {key: value for key, value in document.items() if key != "attestation_sha256"}
        ):
            raise ValueError("MATERIAL_LEARNING_RIGHTS_HASH_MISMATCH")
        return self


class MaterialArtifactMember(OriginArtifactMemberPointer):
    bytes: int = Field(strict=True, ge=1, le=2 * 1024 * 1024 * 1024)


class MaterialPageAddress(FrozenModel):
    source_role: SourceRole
    physical_page: int = Field(strict=True, ge=1, le=2000)


class MaterialSourceRegion(MaterialPageAddress):
    bounding_box: NormalizedBoundingBox


class MaterialDiscoveredUnit(FrozenModel):
    local_key: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,95}$")
    kind: UnitKind
    section_path: tuple[SafeLabel, ...] = Field(max_length=12)
    printed_label: str | None = Field(min_length=1, max_length=100)
    anchors: tuple[MaterialSourceRegion, ...] = Field(min_length=1, max_length=32)
    continuation: Literal["COMPLETE", "FROM_PREVIOUS", "TO_NEXT", "BOTH"]
    related_item_labels: tuple[Annotated[str, Field(min_length=1, max_length=100)], ...] = Field(
        max_length=64
    )
    summary: str = Field(min_length=1, max_length=2000)
    warnings: tuple[Annotated[str, Field(min_length=1, max_length=2000)], ...] = Field(
        max_length=16
    )

    @model_validator(mode="after")
    def distinct_anchors(self) -> Self:
        signatures = tuple(
            (anchor.source_role, anchor.physical_page, anchor.bounding_box.model_dump_json())
            for anchor in self.anchors
        )
        if len(signatures) != len(set(signatures)):
            raise ValueError("MATERIAL_LEARNING_REGION_DUPLICATE")
        if len({anchor.source_role for anchor in self.anchors}) != 1 or tuple(
            anchor.physical_page for anchor in self.anchors
        ) != tuple(sorted(anchor.physical_page for anchor in self.anchors)):
            raise ValueError("MATERIAL_LEARNING_UNIT_SOURCE_ORDER_INVALID")
        for value in (*self.section_path, *self.related_item_labels, self.summary, *self.warnings):
            _safe_text(value)
        if self.printed_label is not None:
            _safe_text(self.printed_label)
        return self


class MaterialPreparedSource(FrozenModel):
    source_role: SourceRole
    actual_format: Literal["PDF", "HWP", "HWPX"]
    original_filename: str = Field(min_length=1, max_length=255)
    document_id: str = Field(pattern=r"^edudoc_[0-9a-f]{32}$")
    document_revision_id: str = Field(pattern=r"^edudocrev_[0-9a-f]{32}$")
    document_manifest_sha256: Sha256
    original: MaterialArtifactMember
    pdf: MaterialArtifactMember
    page_bundle: MaterialArtifactMember
    office_catalog: MaterialArtifactMember | None
    page_count: int = Field(strict=True, ge=1, le=2000)

    @model_validator(mode="after")
    def exact_media(self) -> Self:
        _safe_text(self.original_filename)
        expected = {
            "PDF": {"application/pdf"},
            "HWP": {"application/x-hwp", "application/vnd.hancom.hwp", "application/haansofthwp"},
            "HWPX": {"application/vnd.hancom.hwpx", "application/hwp+zip"},
        }
        if self.original.media_type not in expected[self.actual_format]:
            raise ValueError("MATERIAL_LEARNING_SOURCE_MEDIA_MISMATCH")
        if (
            self.pdf.media_type != "application/pdf"
            or self.page_bundle.media_type != "application/json"
        ):
            raise ValueError("MATERIAL_LEARNING_PREPARED_MEDIA_MISMATCH")
        if self.actual_format == "PDF":
            if self.original != self.pdf or self.office_catalog is not None:
                raise ValueError("MATERIAL_LEARNING_PDF_SOURCE_DUPLICATED")
        elif self.office_catalog is None or self.office_catalog.media_type != "application/json":
            raise ValueError("MATERIAL_LEARNING_OFFICE_CATALOG_REQUIRED")
        return self


class MaterialInputPage(MaterialPageAddress):
    input_index: int = Field(strict=True, ge=1, le=32)
    image: MaterialArtifactMember
    text: MaterialArtifactMember | None
    width_pixels: int = Field(strict=True, ge=1, le=16384)
    height_pixels: int = Field(strict=True, ge=1, le=16384)

    @model_validator(mode="after")
    def actual_page_media(self) -> Self:
        if self.image.media_type != "image/png" or self.image.bytes > 32 * 1024 * 1024:
            raise ValueError("MATERIAL_LEARNING_PAGE_IMAGE_INVALID")
        if self.text is not None and (
            self.text.media_type not in {"text/plain", "text/markdown"}
            or self.text.bytes > 2 * 1024 * 1024
        ):
            raise ValueError("MATERIAL_LEARNING_PAGE_TEXT_INVALID")
        return self


class _MaterialLearningWork(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    material_id: str = Field(pattern=r"^material_[0-9a-f]{32}$")
    material_revision_id: str = Field(pattern=r"^materialrev_[0-9a-f]{32}$")
    task_id: str = Field(pattern=r"^materialtask_[0-9a-f]{32}$")
    sources: tuple[MaterialPreparedSource, ...] = Field(min_length=1, max_length=2)
    rights_attestation: MaterialArtifactMember
    pages: tuple[MaterialInputPage, ...] = Field(min_length=1, max_length=32)
    additional_instructions: str = Field(max_length=8000)
    input_sha256: Sha256

    @model_validator(mode="after")
    def exact_prepared_inputs(self) -> Self:
        sources = {source.source_role: source for source in self.sources}
        if tuple(sources) not in {("MAIN",), ("MAIN", "SOLUTIONS")}:
            raise ValueError("MATERIAL_LEARNING_SOURCE_ROLE_ORDER_INVALID")
        if len(sources) != len(self.sources):
            raise ValueError("MATERIAL_LEARNING_SOURCE_ROLE_DUPLICATE")
        if tuple(page.input_index for page in self.pages) != tuple(range(1, len(self.pages) + 1)):
            raise ValueError("MATERIAL_LEARNING_PAGE_INDEX_INVALID")
        addresses = tuple((page.source_role, page.physical_page) for page in self.pages)
        if len(set(addresses)) != len(addresses):
            raise ValueError("MATERIAL_LEARNING_PAGE_DUPLICATE")
        if any(
            page.source_role not in sources
            or page.physical_page > sources[page.source_role].page_count
            for page in self.pages
        ):
            raise ValueError("MATERIAL_LEARNING_PAGE_OUTSIDE_SOURCE")
        if sum(page.image.bytes + (page.text.bytes if page.text else 0) for page in self.pages) > (
            128 * 1024 * 1024
        ):
            raise ValueError("MATERIAL_LEARNING_INPUT_TOO_LARGE")
        if self.rights_attestation.schema_ref != "eom://schemas/material-learning/rights/1.0":
            raise ValueError("MATERIAL_LEARNING_RIGHTS_SCHEMA_MISMATCH")
        if self.rights_attestation.media_type != "application/json":
            raise ValueError("MATERIAL_LEARNING_RIGHTS_MEDIA_MISMATCH")
        _safe_text(self.additional_instructions)
        document = self.model_dump(mode="json")
        if self.input_sha256 != content_sha256(
            {key: value for key, value in document.items() if key != "input_sha256"}
        ):
            raise ValueError("MATERIAL_LEARNING_INPUT_HASH_MISMATCH")
        return self


class MaterialDiscoveryWork(_MaterialLearningWork):
    schema_version: Literal["material-learning-discovery-work/1.0"]
    task_kind: Literal["DISCOVER"]
    core_pages: tuple[MaterialPageAddress, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def exact_discovery_range(self) -> Self:
        validate_contract("material-learning-discovery-work-v1", self.model_dump(mode="json"))
        pages = {(page.source_role, page.physical_page) for page in self.pages}
        core = tuple((page.source_role, page.physical_page) for page in self.core_pages)
        if len(set(core)) != len(core) or not set(core).issubset(pages):
            raise ValueError("MATERIAL_LEARNING_CORE_PAGES_INVALID")
        if len({role for role, _ in core}) != 1 or tuple(number for _, number in core) != tuple(
            range(core[0][1], core[-1][1] + 1)
        ):
            raise ValueError("MATERIAL_LEARNING_CORE_RANGE_INVALID")
        return self


class MaterialPageCoverage(MaterialPageAddress):
    roles: tuple[
        Literal["EXPLANATION", "QUESTION", "SOLUTION", "ANSWER_KEY", "NON_CONTENT", "UNREADABLE"],
        ...,
    ] = Field(min_length=1, max_length=6)
    note: str = Field(max_length=2000)

    @model_validator(mode="after")
    def meaningful_coverage(self) -> Self:
        if len(set(self.roles)) != len(self.roles) or (
            "NON_CONTENT" in self.roles and self.roles != ("NON_CONTENT",)
        ):
            raise ValueError("MATERIAL_LEARNING_PAGE_COVERAGE_INVALID")
        if "UNREADABLE" in self.roles and not self.note.strip():
            raise ValueError("MATERIAL_LEARNING_UNREADABLE_REASON_REQUIRED")
        _safe_text(self.note)
        return self


class MaterialDiscoveryResult(FrozenModel):
    schema_version: Literal["material-learning-discovery-result/1.0"]
    input_sha256: Sha256
    coverage: tuple[MaterialPageCoverage, ...] = Field(min_length=1, max_length=32)
    units: tuple[MaterialDiscoveredUnit, ...] = Field(max_length=128)
    warnings: tuple[Annotated[str, Field(min_length=1, max_length=2000)], ...] = Field(
        max_length=32
    )

    @model_validator(mode="after")
    def closed_discovery(self) -> Self:
        validate_contract("material-learning-discovery-result-v1", self.model_dump(mode="json"))
        if len({(page.source_role, page.physical_page) for page in self.coverage}) != len(
            self.coverage
        ) or len({unit.local_key for unit in self.units}) != len(self.units):
            raise ValueError("MATERIAL_LEARNING_DISCOVERY_DUPLICATE")
        for warning in self.warnings:
            _safe_text(warning)
        return self


class MaterialExtractionWork(_MaterialLearningWork):
    schema_version: Literal["material-learning-extraction-work/1.0"]
    task_kind: Literal["EXTRACT_ITEM"]
    unit_key: str = Field(pattern=r"^materialunit_[0-9a-f]{32}$")
    question: MaterialDiscoveredUnit
    solutions: tuple[MaterialDiscoveredUnit, ...] = Field(max_length=8)

    @model_validator(mode="after")
    def exact_item_selection(self) -> Self:
        validate_contract("material-learning-extraction-work-v1", self.model_dump(mode="json"))
        if self.question.kind != "QUESTION" or any(
            unit.kind not in {"SOLUTION", "ANSWER_KEY"} for unit in self.solutions
        ):
            raise ValueError("MATERIAL_LEARNING_ITEM_SELECTION_INVALID")
        units = (self.question, *self.solutions)
        if any(unit.continuation != "COMPLETE" for unit in units):
            raise ValueError("MATERIAL_LEARNING_CONTINUATION_UNRESOLVED")
        pages = {(page.source_role, page.physical_page) for page in self.pages}
        if any(
            (anchor.source_role, anchor.physical_page) not in pages
            for unit in units
            for anchor in unit.anchors
        ):
            raise ValueError("MATERIAL_LEARNING_UNIT_ANCHOR_NOT_STAGED")
        return self


class MaterialExtractionResult(SourceItemLearningObservation):
    schema_version: Literal["material-learning-extraction-result/1.0"]
    input_sha256: Sha256
    office_bindings: OfficeVisualBindings | None

    @model_validator(mode="after")
    def installed_schema(self) -> Self:
        validate_contract("material-learning-extraction-result-v1", self.model_dump(mode="json"))
        return self


MaterialLearningWork = Annotated[
    MaterialDiscoveryWork | MaterialExtractionWork, Field(discriminator="schema_version")
]
MaterialLearningResult = Annotated[
    MaterialDiscoveryResult | MaterialExtractionResult, Field(discriminator="schema_version")
]


def material_work_schema_ref(work: MaterialLearningWork) -> str:
    name = "discovery-work" if isinstance(work, MaterialDiscoveryWork) else "extraction-work"
    return f"eom://schemas/material-learning/{name}/1.0"


def validate_material_discovery(
    result: MaterialDiscoveryResult, work: MaterialDiscoveryWork
) -> None:
    """O(pages + regions): a result can only describe its exact staged source."""
    if result.input_sha256 != work.input_sha256:
        raise ValueError("MATERIAL_LEARNING_RESULT_INPUT_MISMATCH")
    pages = {(page.source_role, page.physical_page) for page in work.pages}
    coverage = {(page.source_role, page.physical_page): page.roles for page in result.coverage}
    if set(coverage) != pages:
        raise ValueError("MATERIAL_LEARNING_PAGE_COVERAGE_INCOMPLETE")
    described: set[tuple[str, int, str]] = set()
    for unit in result.units:
        for anchor in unit.anchors:
            address = (anchor.source_role, anchor.physical_page)
            if address not in pages or unit.kind not in coverage[address]:
                raise ValueError("MATERIAL_LEARNING_UNIT_COVERAGE_MISMATCH")
            described.add((*address, unit.kind))
    if any(
        (*address, role) not in described
        for address, roles in coverage.items()
        for role in roles
        if role not in {"NON_CONTENT", "UNREADABLE"}
    ):
        raise ValueError("MATERIAL_LEARNING_OBSERVED_CONTENT_WITHOUT_UNIT")


def validate_material_extraction(
    result: MaterialExtractionResult, work: MaterialExtractionWork
) -> None:
    if result.input_sha256 != work.input_sha256:
        raise ValueError("MATERIAL_LEARNING_RESULT_INPUT_MISMATCH")
    if any(region.physical_page > len(work.pages) for region in result.regions):
        raise ValueError("MATERIAL_LEARNING_RESULT_REGION_NOT_STAGED")
    page_by_index = {page.input_index: page for page in work.pages}
    allowed = {
        "TARGET_ITEM": {
            (anchor.source_role, anchor.physical_page) for anchor in work.question.anchors
        },
        "EDITORIAL_SOLUTION": {
            (anchor.source_role, anchor.physical_page)
            for unit in work.solutions
            for anchor in unit.anchors
        },
    }
    for region in result.regions:
        page = page_by_index[region.physical_page]
        if (
            region.role in allowed
            and (page.source_role, page.physical_page) not in allowed[region.role]
        ):
            raise ValueError("MATERIAL_LEARNING_RESULT_ROLE_OUTSIDE_SELECTION")
    target_roles = {anchor.source_role for anchor in work.question.anchors}
    office = tuple(
        source
        for source in work.sources
        if source.source_role in target_roles and source.actual_format != "PDF"
    )
    if office:
        if len(office) != 1 or result.office_bindings is None:
            raise ValueError("MATERIAL_LEARNING_OFFICE_BINDINGS_REQUIRED")
        catalog = office[0].office_catalog
        assert catalog is not None
        if result.office_bindings.office_catalog_sha256 != catalog.sha256:
            raise ValueError("MATERIAL_LEARNING_OFFICE_BINDINGS_HASH_MISMATCH")
        image_ids = {
            block.block_id
            for block in (result.proposal.content.body if result.proposal else ())
            if isinstance(block, SourceImageBlock)
        }
        if {binding.block_id for binding in result.office_bindings.bindings} != image_ids:
            raise ValueError("MATERIAL_LEARNING_OFFICE_BINDINGS_INCOMPLETE")
    elif result.office_bindings is not None:
        raise ValueError("MATERIAL_LEARNING_UNEXPECTED_OFFICE_BINDINGS")
