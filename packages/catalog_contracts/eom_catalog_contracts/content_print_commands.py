"""Explicit print facts and compensating events, never inferred from an export."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import Field, TypeAdapter, model_validator

from eom_catalog_contracts.content_planning import DeliverableRevisionId, EditionId, SectionId
from eom_catalog_contracts.content_print_record import ContentPrintRecordV1
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.validation import validate_contract

PrintRecordId = Annotated[str, Field(pattern=r"^print_[0-9a-f]{32}$")]
PrintNote = Annotated[str, Field(max_length=2000, pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]*$")]


class _RecordPrintFields(FrozenModel):
    edition_id: EditionId
    revision_id: DeliverableRevisionId
    composition_sha256: Sha256
    section_ids: tuple[SectionId, ...] = Field(min_length=1, max_length=10000)
    intent: Literal["INITIAL", "REPRINT", "CORRECTION"]
    predecessor_print_record_id: PrintRecordId | None
    printed_on: date | None
    note: PrintNote

    @model_validator(mode="after")
    def exact_intent(self) -> Self:
        if len(set(self.section_ids)) != len(self.section_ids):
            raise ValueError("print sections must be unique")
        if (self.intent == "INITIAL") != (self.predecessor_print_record_id is None):
            raise ValueError("explicit reprint/correction requires an original record")
        if self.intent == "CORRECTION" and not self.note.strip():
            raise ValueError("correction requires a reason")
        return self


class RecordContentPrint(_RecordPrintFields):
    command_kind: Literal["RECORD_PRINT"]


class RecordContentPrintWithOutput(_RecordPrintFields):
    command_kind: Literal["RECORD_PRINT_WITH_OUTPUT"]
    output_build_id: str = Field(pattern=r"^hwpxbuild_[0-9a-f]{32}$")
    output_sha256: Sha256


type ContentRecordPrintCommand = RecordContentPrint | RecordContentPrintWithOutput


class VoidContentPrint(FrozenModel):
    command_kind: Literal["VOID_PRINT"]
    edition_id: EditionId
    print_record_id: PrintRecordId
    record_sha256: Sha256
    reason: PrintNote = Field(min_length=1)

    @model_validator(mode="after")
    def meaningful_reason(self) -> Self:
        if not self.reason.strip():
            raise ValueError("voiding requires a reason")
        return self


type ContentPrintCommand = Annotated[
    RecordContentPrint | RecordContentPrintWithOutput | VoidContentPrint,
    Field(discriminator="command_kind"),
]
_COMMAND: TypeAdapter[ContentPrintCommand] = TypeAdapter(ContentPrintCommand)


def parse_content_print_command(value: dict[str, object]) -> ContentPrintCommand:
    validate_contract("content-print-command-v2", value)
    return _COMMAND.validate_python(value)


class ContentPrintMutationResult(FrozenModel):
    result_kind: Literal["PRINT_MUTATION"] = "PRINT_MUTATION"
    disposition: Literal["RECORDED", "ALREADY_RECORDED", "VOIDED"]
    replayed: bool
    record: ContentPrintRecordV1
