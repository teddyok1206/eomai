"""Bounded content views; exact snapshot cursors keep old pages reproducible."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from eom_catalog_contracts.content_delivery import ContentDeliveryList, ReadContentDeliveries
from eom_catalog_contracts.content_planning import (
    AcademicYear,
    ContentEditionCompositionV1,
    ContentFormPointer,
    ContentLabel,
    ContentType,
    DeliverableId,
    DeliverableRevisionId,
    EditionId,
    SectionId,
)
from eom_catalog_contracts.content_print_views import ContentPrintList, ReadContentPrints
from eom_catalog_contracts.content_usage import (
    ContentUsagePage,
    ContentUsageSummary,
    PriorUsagePage,
    ReadContentUsage,
    ReadContentUsageSummary,
    ReadPriorContentUsage,
)
from eom_catalog_contracts.curated_document_slots import PlacementId, ResolvedCuratedSlot
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.validation import validate_contract


class ListPlannedContents(FrozenModel):
    query_kind: Literal["LIST_CONTENTS"]
    text: str = Field(max_length=200)
    limit: int = Field(strict=True, ge=1, le=100)
    after_id: DeliverableId | None


class ListContentEditions(FrozenModel):
    query_kind: Literal["LIST_EDITIONS"]
    deliverable_id: DeliverableId
    limit: int = Field(strict=True, ge=1, le=100)
    after_id: EditionId | None


class ReadContentEdition(FrozenModel):
    query_kind: Literal["READ_EDITION"]
    edition_id: EditionId
    revision_id: DeliverableRevisionId | None


class ReadContentSection(FrozenModel):
    query_kind: Literal["READ_SECTION"]
    edition_id: EditionId
    revision_id: DeliverableRevisionId
    composition_sha256: Sha256
    section_id: SectionId
    after_position: int = Field(strict=True, ge=0, le=100000)
    limit: int = Field(strict=True, ge=1, le=200)


class ReadContentHistory(FrozenModel):
    query_kind: Literal["HISTORY"]
    edition_id: EditionId
    before_sequence: Annotated[int, Field(strict=True, ge=1)] | None
    limit: int = Field(strict=True, ge=1, le=100)


class PlannedContentEntry(FrozenModel):
    deliverable_id: DeliverableId
    title: ContentLabel
    content_type: ContentType
    edition_count: int = Field(strict=True, ge=1)


class ContentEditionEntry(FrozenModel):
    edition_id: EditionId
    deliverable_id: DeliverableId
    revision_id: DeliverableRevisionId
    composition_sha256: Sha256
    edition_label: ContentLabel
    academic_year: AcademicYear | None
    section_count: int = Field(strict=True, ge=0, le=10000)


class ContentHistoryEntry(FrozenModel):
    sequence: int = Field(strict=True, ge=1)
    command_kind: str = Field(max_length=64)
    before_revision_id: DeliverableRevisionId | None
    after_revision_id: DeliverableRevisionId
    created_by: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    created_at: UtcDatetime


class PlannedContentList(FrozenModel):
    result_kind: Literal["CONTENTS"] = "CONTENTS"
    rows: tuple[PlannedContentEntry, ...] = Field(max_length=100)
    next_id: DeliverableId | None


class ContentEditionList(FrozenModel):
    result_kind: Literal["EDITIONS"] = "EDITIONS"
    rows: tuple[ContentEditionEntry, ...] = Field(max_length=100)
    next_id: EditionId | None


class ContentEditionView(FrozenModel):
    result_kind: Literal["COMPOSITION"] = "COMPOSITION"
    composition: ContentEditionCompositionV1
    current_revision_id: DeliverableRevisionId


class ContentSlotLabel(FrozenModel):
    """Display metadata from the already-authorized exact revision, not identity."""

    placement_id: PlacementId
    title: str = Field(min_length=1, max_length=512)
    external_number: str | None = Field(pattern=r"^[0-9]{5}$")


class ContentSectionPage(FrozenModel):
    result_kind: Literal["SECTION"] = "SECTION"
    edition_id: EditionId
    revision_id: DeliverableRevisionId
    composition_sha256: Sha256
    section_id: SectionId
    form: ContentFormPointer
    rows: tuple[ResolvedCuratedSlot, ...] = Field(max_length=200)
    labels: tuple[ContentSlotLabel, ...] = Field(max_length=200)
    next_position: Annotated[int, Field(strict=True, ge=1, le=100000)] | None
    total: int = Field(strict=True, ge=0, le=100000)


class ContentHistoryPage(FrozenModel):
    result_kind: Literal["HISTORY"] = "HISTORY"
    edition_id: EditionId
    rows: tuple[ContentHistoryEntry, ...] = Field(max_length=100)
    next_sequence: Annotated[int, Field(strict=True, ge=1)] | None


type ContentPlanningQuery = Annotated[
    ListPlannedContents
    | ListContentEditions
    | ReadContentEdition
    | ReadContentSection
    | ReadContentHistory
    | ReadContentPrints
    | ReadContentUsage
    | ReadContentUsageSummary
    | ReadPriorContentUsage
    | ReadContentDeliveries,
    Field(discriminator="query_kind"),
]
type ContentPlanningQueryResult = Annotated[
    PlannedContentList
    | ContentEditionList
    | ContentEditionView
    | ContentSectionPage
    | ContentHistoryPage
    | ContentPrintList
    | ContentUsagePage
    | ContentUsageSummary
    | PriorUsagePage
    | ContentDeliveryList,
    Field(discriminator="result_kind"),
]
_QUERY: TypeAdapter[ContentPlanningQuery] = TypeAdapter(ContentPlanningQuery)
_RESULT: TypeAdapter[ContentPlanningQueryResult] = TypeAdapter(ContentPlanningQueryResult)


def parse_content_planning_query(value: dict[str, object]) -> ContentPlanningQuery:
    validate_contract("content-planning-query-v1", value)
    return _QUERY.validate_python(value)


def parse_content_planning_query_result(value: dict[str, object]) -> ContentPlanningQueryResult:
    validate_contract("content-planning-query-result-v1", value)
    return _RESULT.validate_python(value)
