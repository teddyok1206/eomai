"""Closed browser wire values. Catalog owns hashes, trees, permissions and state.

These DTOs keep the Web wheel independent of platform/database packages. Alignment
tests use canonical owner payloads; no domain validation is reimplemented here.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from eom_web_gui.contracts import CuratedAssemblyItemPointerView, UtcDatetime, WebModel

Sha = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
ProductId = Annotated[str, Field(pattern=r"^deliverable_[0-9a-f]{32}$")]
RevisionId = Annotated[str, Field(pattern=r"^delivrev_[0-9a-f]{32}$")]
EditionId = Annotated[str, Field(pattern=r"^edition_[0-9a-f]{32}$")]
SectionId = Annotated[str, Field(pattern=r"^section_[0-9a-f]{32}$")]
PlacementId = Annotated[str, Field(pattern=r"^placement_[0-9a-f]{32}$")]
AssemblyId = Annotated[str, Field(pattern=r"^assembly_[0-9a-f]{32}$")]
AssemblyRevisionId = Annotated[str, Field(pattern=r"^assemblyrev_[0-9a-f]{32}$")]
FormId = Annotated[str, Field(pattern=r"^form_[0-9a-f]{32}$")]
PrintId = Annotated[str, Field(pattern=r"^print_[0-9a-f]{32}$")]
Label = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[^\x00-\x1f\x7f]+$")]
Year = Annotated[int, Field(strict=True, ge=1900, le=3000)]
Numbering = Literal["RESET_PER_SECTION", "CONTINUE_WITHIN_GROUP"]
ContentType = Literal["MOCK_EXAM", "TEXTBOOK", "WEEKLY", "OTHER"]
Note = Annotated[str, Field(max_length=2000, pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]*$")]


class EmptyTarget(WebModel):
    placement_kind: Literal["EMPTY"]


class SourceTarget(WebModel):
    placement_kind: Literal["EXTERNAL_SOURCE_DOCUMENT"]
    source_id: str = Field(pattern=r"^extitem_[0-9a-f]{32}$")
    source_revision_id: str = Field(pattern=r"^extitemrev_[0-9a-f]{32}$")
    observation_sha256: Sha
    edition: Literal[2, 3]
    source_format: Literal["HWP", "HWPX"]


class ArtifactMember(WebModel):
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    member_path: str = Field(min_length=1, max_length=512)
    schema_ref: str = Field(min_length=1, max_length=256)
    media_type: str = Field(min_length=1, max_length=128)
    sha256: Sha


class ResolvedSourceTarget(SourceTarget):
    external_number: str = Field(pattern=r"^[0-9]{5}$")
    source_file_id: str = Field(pattern=r"^sourcefile_[0-9a-f]{32}$")
    document_artifact: ArtifactMember
    document_size_bytes: int = Field(strict=True, ge=1, le=100 * 1024**2)


Target = Annotated[
    EmptyTarget | SourceTarget | CuratedAssemblyItemPointerView,
    Field(discriminator="placement_kind"),
]
ResolvedTarget = Annotated[
    EmptyTarget | ResolvedSourceTarget | CuratedAssemblyItemPointerView,
    Field(discriminator="placement_kind"),
]


class CopyOrigin(WebModel):
    assembly_id: AssemblyId
    assembly_revision_id: AssemblyRevisionId
    manifest_sha256: Sha
    placement_id: PlacementId


class SlotFields(WebModel):
    placement_id: PlacementId
    position: int = Field(strict=True, ge=1, le=100000)
    points_milli: Annotated[int, Field(strict=True, ge=0, le=1000000)] | None
    display_number: Annotated[str, Field(min_length=1, max_length=32)] | None
    note: Note
    copied_from: CopyOrigin | None


class Slot(SlotFields):
    target: Target


class ResolvedSlot(SlotFields):
    target: ResolvedTarget


class FormPointer(WebModel):
    form_id: FormId
    form_revision_id: str = Field(pattern=r"^formrev_[0-9a-f]{32}$")
    form_sha256: Sha
    assembly_id: AssemblyId
    assembly_revision_id: AssemblyRevisionId
    manifest_sha256: Sha
    placement_count: int = Field(strict=True, ge=0, le=100000)


class SectionStructure(WebModel):
    section_id: SectionId
    parent_id: SectionId | None
    kind: Literal["GROUP", "FORM"]
    ordinal: int = Field(strict=True, ge=1, le=10000)
    label: Label
    numbering: Numbering


class Section(SectionStructure):
    form: FormPointer | None


class Composition(WebModel):
    schema_version: Literal["content-edition-composition/1.0"]
    deliverable_id: ProductId
    edition_id: EditionId
    deliverable_revision_id: RevisionId
    revision_number: int = Field(strict=True, ge=1)
    previous_revision_id: RevisionId | None
    content_title: Label
    content_type: ContentType
    edition_label: Label
    academic_year: Year | None
    sections: tuple[Section, ...] = Field(max_length=10000)
    created_by: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    created_at: UtcDatetime
    composition_sha256: Sha


class NewEdition(WebModel):
    edition_label: Label
    academic_year: Year | None
    sections: tuple[SectionStructure, ...] = Field(max_length=10000)


class CreateContent(NewEdition):
    command_kind: Literal["CREATE_CONTENT"]
    content_title: Label
    content_type: ContentType


class CreateEdition(NewEdition):
    command_kind: Literal["CREATE_EDITION"]
    deliverable_id: ProductId


class CopyEdition(WebModel):
    command_kind: Literal["COPY_EDITION"]
    source_edition_id: EditionId
    source_revision_id: RevisionId
    source_sha256: Sha
    edition_label: Label
    academic_year: Year | None


class SectionChange(WebModel):
    section_id: SectionId
    before_assembly_revision_id: AssemblyRevisionId
    before_manifest_sha256: Sha
    placements: tuple[Slot, ...] = Field(max_length=100000)


class SaveSections(WebModel):
    change_kind: Literal["SAVE_SECTIONS"]
    expected_revision_id: RevisionId
    expected_sha256: Sha
    changes: tuple[SectionChange, ...] = Field(min_length=1, max_length=10000)


class SaveStructure(WebModel):
    change_kind: Literal["SAVE_STRUCTURE"]
    expected_revision_id: RevisionId
    expected_sha256: Sha
    edition_label: Label
    academic_year: Year | None
    sections: tuple[SectionStructure, ...] = Field(max_length=10000)
    confirmed_removed_sections: tuple[SectionId, ...] = Field(max_length=10000)


class EditEdition(WebModel):
    command_kind: Literal["EDIT_EDITION"]
    edition_id: EditionId
    edit: Annotated[SaveSections | SaveStructure, Field(discriminator="change_kind")]


PlanningCommand = Annotated[
    CreateContent | CreateEdition | CopyEdition | EditEdition, Field(discriminator="command_kind")
]


class WriteResult(WebModel):
    schema_version: Literal["content-planning-write-result/1.0"]
    disposition: Literal["SAVED", "NO_CHANGE"]
    replayed: bool
    composition: Composition
    current_revision_id: RevisionId


class ListContents(WebModel):
    query_kind: Literal["LIST_CONTENTS"]
    text: str = Field(max_length=200)
    limit: int = Field(strict=True, ge=1, le=100)
    after_id: ProductId | None


class ListEditions(WebModel):
    query_kind: Literal["LIST_EDITIONS"]
    deliverable_id: ProductId
    limit: int = Field(strict=True, ge=1, le=100)
    after_id: EditionId | None


class ReadEdition(WebModel):
    query_kind: Literal["READ_EDITION"]
    edition_id: EditionId
    revision_id: RevisionId | None


class ReadSection(WebModel):
    query_kind: Literal["READ_SECTION"]
    edition_id: EditionId
    revision_id: RevisionId
    composition_sha256: Sha
    section_id: SectionId
    after_position: int = Field(strict=True, ge=0, le=100000)
    limit: int = Field(strict=True, ge=1, le=200)


class ReadHistory(WebModel):
    query_kind: Literal["HISTORY"]
    edition_id: EditionId
    before_sequence: Annotated[int, Field(strict=True, ge=1)] | None
    limit: int = Field(strict=True, ge=1, le=100)


class ReadPrints(WebModel):
    query_kind: Literal["PRINTS"]
    edition_id: EditionId
    before_id: PrintId | None
    limit: int = Field(strict=True, ge=1, le=100)


class ReadDeliveries(WebModel):
    query_kind: Literal["DELIVERIES"]
    edition_id: EditionId
    before_id: AssemblyRevisionId | None
    limit: int = Field(strict=True, ge=1, le=100)


class UsageCursor(WebModel):
    edition_id: EditionId
    year_key: int = Field(strict=True, ge=0, le=3000)
    form_id: FormId
    placement_id: PlacementId
    target: ResolvedTarget


class ReadUsage(WebModel):
    query_kind: Literal["USAGE"]
    targets: tuple[Target, ...] = Field(min_length=1, max_length=100)
    academic_year: Literal["ALL"] | Year | None
    after: UsageCursor | None
    limit: int = Field(strict=True, ge=1, le=200)


class ReadUsageSummary(WebModel):
    query_kind: Literal["USAGE_SUMMARY"]
    targets: tuple[Target, ...] = Field(min_length=1, max_length=100)
    academic_year: Literal["ALL"] | Year | None
    edition_id: EditionId | None


class PriorUsageCursor(WebModel):
    ledger: Literal["USAGE", "LEGACY_USAGE_V1"]
    usage_record_id: str = Field(pattern=r"^usagerecord_[0-9a-f]{32}$")


class ReadPriorUsage(WebModel):
    query_kind: Literal["PRIOR_USAGE"]
    targets: tuple[Target, ...] = Field(min_length=1, max_length=100)
    academic_year: Literal["ALL"]
    after: PriorUsageCursor | None
    limit: int = Field(strict=True, ge=1, le=200)


PlanningQuery = Annotated[
    ListContents
    | ListEditions
    | ReadEdition
    | ReadSection
    | ReadHistory
    | ReadPrints
    | ReadUsage
    | ReadUsageSummary
    | ReadPriorUsage
    | ReadDeliveries,
    Field(discriminator="query_kind"),
]


class ContentEntry(WebModel):
    deliverable_id: ProductId
    title: Label
    content_type: ContentType
    edition_count: int = Field(strict=True, ge=1)


class ContentList(WebModel):
    result_kind: Literal["CONTENTS"]
    rows: tuple[ContentEntry, ...] = Field(max_length=100)
    next_id: ProductId | None


class EditionEntry(WebModel):
    edition_id: EditionId
    deliverable_id: ProductId
    revision_id: RevisionId
    composition_sha256: Sha
    edition_label: Label
    academic_year: Year | None
    section_count: int = Field(strict=True, ge=0, le=10000)


class EditionList(WebModel):
    result_kind: Literal["EDITIONS"]
    rows: tuple[EditionEntry, ...] = Field(max_length=100)
    next_id: EditionId | None


class EditionView(WebModel):
    result_kind: Literal["COMPOSITION"]
    composition: Composition
    current_revision_id: RevisionId


class SlotLabel(WebModel):
    placement_id: PlacementId
    title: str = Field(min_length=1, max_length=512)
    external_number: str | None = Field(pattern=r"^[0-9]{5}$")


class SectionPage(WebModel):
    result_kind: Literal["SECTION"]
    edition_id: EditionId
    revision_id: RevisionId
    composition_sha256: Sha
    section_id: SectionId
    form: FormPointer
    rows: tuple[ResolvedSlot, ...] = Field(max_length=200)
    labels: tuple[SlotLabel, ...] = Field(max_length=200)
    next_position: Annotated[int, Field(strict=True, ge=1, le=100000)] | None
    total: int = Field(strict=True, ge=0, le=100000)


class HistoryEntry(WebModel):
    sequence: int = Field(strict=True, ge=1)
    command_kind: str = Field(max_length=64)
    before_revision_id: RevisionId | None
    after_revision_id: RevisionId
    created_by: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    created_at: UtcDatetime


class HistoryPage(WebModel):
    result_kind: Literal["HISTORY"]
    edition_id: EditionId
    rows: tuple[HistoryEntry, ...] = Field(max_length=100)
    next_sequence: Annotated[int, Field(strict=True, ge=1)] | None


class ScopePathEntry(WebModel):
    section_id: SectionId
    label: Label


class ScopedForm(WebModel):
    section_id: SectionId
    path: tuple[ScopePathEntry, ...] = Field(min_length=1, max_length=64)
    form: FormPointer
    numbering: Numbering
    start_number: int = Field(strict=True, ge=1, le=1000000000)


class PrintScope(WebModel):
    schema_version: Literal["content-print-scope/1.0"]
    deliverable_id: ProductId
    edition_id: EditionId
    content_title: Label
    edition_label: Label
    academic_year: Year | None
    forms: tuple[ScopedForm, ...] = Field(min_length=1, max_length=10000)
    scope_sha256: Sha


class PrintOutput(WebModel):
    hwpx_build_id: str = Field(pattern=r"^hwpxbuild_[0-9a-f]{32}$")
    scope_sha256: Sha
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    artifact_sha256: Sha
    output_sha256: Sha


class PrintRecord(WebModel):
    schema_version: Literal["content-print-record/1.0"]
    print_record_id: PrintId
    deliverable_revision_id: RevisionId
    composition_sha256: Sha
    scope: PrintScope
    origin: Literal["USER_RECORDED"]
    intent: Literal["INITIAL", "REPRINT", "CORRECTION"]
    predecessor_print_record_id: PrintId | None
    printed_on: date | None
    recorded_at: UtcDatetime
    recorded_by: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    note: Note
    output: PrintOutput | None
    record_sha256: Sha


class PrintEntry(WebModel):
    record: PrintRecord
    state: Literal["ACTIVE", "VOIDED", "CORRECTED"]
    replacement_print_record_id: PrintId | None
    reason: str | None = Field(max_length=2000)
    matches_current_scope: bool


class PrintList(WebModel):
    result_kind: Literal["PRINTS"]
    edition_id: EditionId
    current_revision_id: RevisionId
    rows: tuple[PrintEntry, ...] = Field(max_length=100)
    next_id: PrintId | None


class UsageLocation(WebModel):
    edition_id: EditionId
    deliverable_id: ProductId
    revision_id: RevisionId
    content_title: Label
    edition_label: Label
    academic_year: Year | None
    section_id: SectionId
    section_label: Label
    form_id: FormId
    placement_id: PlacementId
    position: int = Field(strict=True, ge=1, le=100000)
    target: ResolvedTarget
    currently_placed: bool
    print_count: int = Field(strict=True, ge=0)
    sample_print_record_id: PrintId | None
    matched_target_indices: tuple[Annotated[int, Field(strict=True, ge=0, le=99)], ...] = Field(
        min_length=1, max_length=100
    )


class UsagePage(WebModel):
    result_kind: Literal["USAGE"]
    query_sha256: Sha
    coverage: Literal["ACCESSIBLE_CONTENTS"]
    total_locations: int = Field(strict=True, ge=0)
    rows: tuple[UsageLocation, ...] = Field(max_length=200)
    next_after: UsageCursor | None


class UsageCount(WebModel):
    target_index: int = Field(strict=True, ge=0, le=99)
    total_locations: int = Field(strict=True, ge=0)
    edition_locations: int = Field(strict=True, ge=0)
    other_locations: int = Field(strict=True, ge=0)


class UsageSummary(WebModel):
    result_kind: Literal["USAGE_SUMMARY"]
    query_sha256: Sha
    coverage: Literal["ACCESSIBLE_CONTENTS"]
    rows: tuple[UsageCount, ...] = Field(max_length=100)


class _RecordPrintFields(WebModel):
    edition_id: EditionId
    revision_id: RevisionId
    composition_sha256: Sha
    section_ids: tuple[SectionId, ...] = Field(min_length=1, max_length=10000)
    intent: Literal["INITIAL", "REPRINT", "CORRECTION"]
    predecessor_print_record_id: PrintId | None
    printed_on: date | None
    note: Note


class RecordPrint(_RecordPrintFields):
    command_kind: Literal["RECORD_PRINT"]


class RecordPrintWithOutput(_RecordPrintFields):
    command_kind: Literal["RECORD_PRINT_WITH_OUTPUT"]
    output_build_id: str = Field(pattern=r"^hwpxbuild_[0-9a-f]{32}$")
    output_sha256: Sha


class VoidPrint(WebModel):
    command_kind: Literal["VOID_PRINT"]
    edition_id: EditionId
    print_record_id: PrintId
    record_sha256: Sha
    reason: Note = Field(min_length=1)


PrintCommand = Annotated[
    RecordPrint | RecordPrintWithOutput | VoidPrint, Field(discriminator="command_kind")
]


class PrintResult(WebModel):
    result_kind: Literal["PRINT_MUTATION"]
    disposition: Literal["RECORDED", "ALREADY_RECORDED", "VOIDED"]
    replayed: bool
    record: PrintRecord


class PrepareDelivery(WebModel):
    command_kind: Literal["PREPARE_DELIVERY"]
    edition_id: EditionId
    revision_id: RevisionId
    composition_sha256: Sha
    section_ids: tuple[SectionId, ...] = Field(min_length=1, max_length=10000)


class PreparedDelivery(WebModel):
    schema_version: Literal["content-delivery-prepared/1.0"]
    edition_id: EditionId
    revision_id: RevisionId
    composition_sha256: Sha
    scope_sha256: Sha
    assembly_id: AssemblyId
    assembly_revision_id: AssemblyRevisionId
    manifest_sha256: Sha
    placement_count: int = Field(strict=True, ge=1, le=100000)
    created_at: UtcDatetime
    replayed: bool


class DeliveryEntry(WebModel):
    prepared: PreparedDelivery
    section_labels: tuple[Label, ...] = Field(min_length=1, max_length=3)
    section_count: int = Field(strict=True, ge=1, le=10000)
    matches_current_revision: bool


class DeliveryList(WebModel):
    result_kind: Literal["DELIVERIES"]
    edition_id: EditionId
    rows: tuple[DeliveryEntry, ...] = Field(max_length=100)
    next_id: AssemblyRevisionId | None


class PriorItemPointer(WebModel):
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_manifest_sha256: Sha


class PriorUsageLocation(PriorUsageCursor):
    deliverable_id: ProductId
    deliverable_revision_id: RevisionId
    title: str = Field(min_length=1, max_length=256)
    section: str = Field(min_length=1, max_length=200)
    position: int = Field(strict=True, ge=1)
    target: PriorItemPointer
    recorded_at: UtcDatetime
    publication_revision_id: str | None = Field(pattern=r"^publicationrev_[0-9a-f]{32}$")


class PriorUsagePage(WebModel):
    result_kind: Literal["PRIOR_USAGE"]
    query_sha256: Sha
    coverage: Literal["PRIOR_LEDGER_WITHOUT_ACADEMIC_YEAR"]
    rows: tuple[PriorUsageLocation, ...] = Field(max_length=200)
    next_after: PriorUsageCursor | None


PlanningResult = Annotated[
    ContentList
    | EditionList
    | EditionView
    | SectionPage
    | HistoryPage
    | PrintList
    | UsagePage
    | UsageSummary
    | PriorUsagePage
    | DeliveryList,
    Field(discriminator="result_kind"),
]
PLANNING_RESULT: TypeAdapter[PlanningResult] = TypeAdapter(PlanningResult)
