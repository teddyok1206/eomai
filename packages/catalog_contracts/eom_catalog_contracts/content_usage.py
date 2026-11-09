"""Small paged usage locations, not copied items or guessed equivalence by number."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from eom_catalog_contracts.content_planning import (
    AcademicYear,
    ContentLabel,
    DeliverableId,
    DeliverableRevisionId,
    EditionId,
    FormId,
    SectionId,
)
from eom_catalog_contracts.content_print_commands import PrintRecordId
from eom_catalog_contracts.curated_document_slots import (
    PlacementId,
    ResolvedSlotTarget,
    SlotPosition,
    SlotTarget,
)
from eom_catalog_contracts.item_origin import OriginItemRevisionPointer
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime


class PriorUsageCursor(FrozenModel):
    ledger: Literal["USAGE", "LEGACY_USAGE_V1"]
    usage_record_id: str = Field(pattern=r"^usagerecord_[0-9a-f]{32}$")


class PriorUsageLocation(PriorUsageCursor):
    deliverable_id: DeliverableId
    deliverable_revision_id: DeliverableRevisionId
    title: str = Field(min_length=1, max_length=256)
    section: ContentLabel
    position: int = Field(strict=True, ge=1)
    target: OriginItemRevisionPointer
    recorded_at: UtcDatetime
    publication_revision_id: str | None = Field(pattern=r"^publicationrev_[0-9a-f]{32}$")


class PriorUsagePage(FrozenModel):
    result_kind: Literal["PRIOR_USAGE"] = "PRIOR_USAGE"
    query_sha256: Sha256
    coverage: Literal["PRIOR_LEDGER_WITHOUT_ACADEMIC_YEAR"] = "PRIOR_LEDGER_WITHOUT_ACADEMIC_YEAR"
    rows: tuple[PriorUsageLocation, ...] = Field(max_length=200)
    next_after: PriorUsageCursor | None


class ContentUsageCursor(FrozenModel):
    edition_id: EditionId
    year_key: int = Field(strict=True, ge=0, le=3000)
    form_id: FormId
    placement_id: PlacementId
    target: ResolvedSlotTarget


class _UsageTargets(FrozenModel):
    targets: tuple[SlotTarget, ...] = Field(min_length=1, max_length=100)
    academic_year: Literal["ALL"] | AcademicYear | None

    @model_validator(mode="after")
    def actual_targets(self) -> Self:
        if len(set(self.targets)) != len(self.targets) or any(
            target.placement_kind == "EMPTY" for target in self.targets
        ):
            raise ValueError("usage requires distinct actual Item or source pointers")
        return self


class ReadContentUsage(_UsageTargets):
    query_kind: Literal["USAGE"]
    after: ContentUsageCursor | None
    limit: int = Field(strict=True, ge=1, le=200)


class ReadPriorContentUsage(_UsageTargets):
    query_kind: Literal["PRIOR_USAGE"]
    academic_year: Literal["ALL"]
    after: PriorUsageCursor | None
    limit: int = Field(strict=True, ge=1, le=200)


class ReadContentUsageSummary(_UsageTargets):
    query_kind: Literal["USAGE_SUMMARY"]
    edition_id: EditionId | None


class ContentUsageCount(FrozenModel):
    target_index: int = Field(strict=True, ge=0, le=99)
    total_locations: int = Field(strict=True, ge=0)
    edition_locations: int = Field(strict=True, ge=0)
    other_locations: int = Field(strict=True, ge=0)


class ContentUsageSummary(FrozenModel):
    result_kind: Literal["USAGE_SUMMARY"] = "USAGE_SUMMARY"
    query_sha256: Sha256
    coverage: Literal["ACCESSIBLE_CONTENTS"] = "ACCESSIBLE_CONTENTS"
    rows: tuple[ContentUsageCount, ...] = Field(max_length=100)


class ContentUsageLocation(FrozenModel):
    edition_id: EditionId
    deliverable_id: DeliverableId
    revision_id: DeliverableRevisionId
    content_title: ContentLabel
    edition_label: ContentLabel
    academic_year: AcademicYear | None
    section_id: SectionId
    section_label: ContentLabel
    form_id: FormId
    placement_id: PlacementId
    position: SlotPosition
    target: ResolvedSlotTarget
    currently_placed: bool
    print_count: int = Field(strict=True, ge=0)
    sample_print_record_id: PrintRecordId | None
    matched_target_indices: tuple[Annotated[int, Field(strict=True, ge=0, le=99)], ...] = Field(
        min_length=1, max_length=100
    )


class ContentUsagePage(FrozenModel):
    result_kind: Literal["USAGE"] = "USAGE"
    query_sha256: Sha256
    coverage: Literal["ACCESSIBLE_CONTENTS"] = "ACCESSIBLE_CONTENTS"
    total_locations: int = Field(strict=True, ge=0)
    rows: tuple[ContentUsageLocation, ...] = Field(max_length=200)
    next_after: ContentUsageCursor | None
