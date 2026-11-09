"""User-recorded print facts preserve the exact selected composition and output."""

from __future__ import annotations

from datetime import date
from typing import Literal, Self

from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_catalog_contracts.content_planning import ContentPrintScopeV1, DeliverableRevisionId
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime


class ContentPrintOutput(FrozenModel):
    hwpx_build_id: str = Field(pattern=r"^hwpxbuild_[0-9a-f]{32}$")
    scope_sha256: Sha256
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    artifact_sha256: Sha256
    output_sha256: Sha256


class ContentPrintRecordV1(FrozenModel):
    schema_version: Literal["content-print-record/1.0"]
    print_record_id: str = Field(pattern=r"^print_[0-9a-f]{32}$")
    deliverable_revision_id: DeliverableRevisionId
    composition_sha256: Sha256
    scope: ContentPrintScopeV1
    origin: Literal["USER_RECORDED"]
    intent: Literal["INITIAL", "REPRINT", "CORRECTION"]
    predecessor_print_record_id: str | None = Field(pattern=r"^print_[0-9a-f]{32}$")
    printed_on: date | None
    recorded_at: UtcDatetime
    recorded_by: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    note: str = Field(max_length=2000, pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]*$")
    output: ContentPrintOutput | None
    record_sha256: Sha256

    @model_validator(mode="after")
    def immutable_fact(self) -> Self:
        if (self.intent == "INITIAL") != (self.predecessor_print_record_id is None):
            raise ValueError("reprint and correction require an exact predecessor")
        if self.predecessor_print_record_id == self.print_record_id:
            raise ValueError("print record cannot precede itself")
        if self.output is not None and self.output.scope_sha256 != self.scope.scope_sha256:
            raise ValueError("output is not for the recorded print scope")
        if self.record_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"record_sha256"})
        ):
            raise ValueError("print record hash differs")
        return self
