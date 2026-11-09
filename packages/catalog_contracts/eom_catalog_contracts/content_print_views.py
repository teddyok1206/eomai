"""Read facts independently of whether a different section has since changed."""

from typing import Literal

from pydantic import Field

from eom_catalog_contracts.content_planning import DeliverableRevisionId, EditionId
from eom_catalog_contracts.content_print_commands import PrintRecordId
from eom_catalog_contracts.content_print_record import ContentPrintRecordV1
from eom_catalog_contracts.models import FrozenModel


class ReadContentPrints(FrozenModel):
    query_kind: Literal["PRINTS"]
    edition_id: EditionId
    before_id: PrintRecordId | None
    limit: int = Field(strict=True, ge=1, le=100)


class ContentPrintEntry(FrozenModel):
    record: ContentPrintRecordV1
    state: Literal["ACTIVE", "VOIDED", "CORRECTED"]
    replacement_print_record_id: PrintRecordId | None
    reason: str | None = Field(max_length=2000)
    matches_current_scope: bool


class ContentPrintList(FrozenModel):
    result_kind: Literal["PRINTS"] = "PRINTS"
    edition_id: EditionId
    current_revision_id: DeliverableRevisionId
    rows: tuple[ContentPrintEntry, ...] = Field(max_length=100)
    next_id: PrintRecordId | None
