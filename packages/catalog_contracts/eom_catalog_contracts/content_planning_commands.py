"""Small planning commands; authority and idempotency belong to the caller boundary."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, TypeAdapter, model_validator

from eom_catalog_contracts.content_planning import (
    CONTENT_MAX_SECTIONS,
    AcademicYear,
    ContentEditionCompositionV1,
    ContentLabel,
    ContentSectionStructure,
    ContentType,
    DeliverableId,
    DeliverableRevisionId,
    EditionId,
    validate_section_tree,
)
from eom_catalog_contracts.content_planning_edits import SaveContentSections, SaveContentStructure
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.validation import validate_contract


class _NewEdition(FrozenModel):
    edition_label: ContentLabel
    academic_year: AcademicYear | None
    sections: tuple[ContentSectionStructure, ...] = Field(max_length=CONTENT_MAX_SECTIONS)

    @model_validator(mode="after")
    def valid_structure(self) -> Self:
        validate_section_tree(self.sections)
        if self.edition_label != self.edition_label.strip():
            raise ValueError("edition label must not have outer whitespace")
        return self


class CreatePlannedContent(_NewEdition):
    command_kind: Literal["CREATE_CONTENT"]
    content_title: ContentLabel
    content_type: ContentType

    @model_validator(mode="after")
    def canonical_title(self) -> Self:
        if self.content_title != self.content_title.strip():
            raise ValueError("content title must not have outer whitespace")
        return self


class CreateContentEdition(_NewEdition):
    command_kind: Literal["CREATE_EDITION"]
    deliverable_id: DeliverableId


class CopyContentEdition(FrozenModel):
    command_kind: Literal["COPY_EDITION"]
    source_edition_id: EditionId
    source_revision_id: DeliverableRevisionId
    source_sha256: Sha256
    edition_label: ContentLabel
    academic_year: AcademicYear | None

    @model_validator(mode="after")
    def canonical_label(self) -> Self:
        if self.edition_label != self.edition_label.strip():
            raise ValueError("edition label must not have outer whitespace")
        return self


class EditContentEdition(FrozenModel):
    command_kind: Literal["EDIT_EDITION"]
    edition_id: EditionId
    edit: Annotated[SaveContentSections | SaveContentStructure, Field(discriminator="change_kind")]


type ContentPlanningCommand = Annotated[
    CreatePlannedContent | CreateContentEdition | CopyContentEdition | EditContentEdition,
    Field(discriminator="command_kind"),
]

_COMMAND_ADAPTER: TypeAdapter[ContentPlanningCommand] = TypeAdapter(ContentPlanningCommand)


def parse_content_planning_command(value: dict[str, object]) -> ContentPlanningCommand:
    validate_contract("content-planning-command-v1", value)
    return _COMMAND_ADAPTER.validate_python(value)


class ContentPlanningWriteResult(FrozenModel):
    schema_version: Literal["content-planning-write-result/1.0"] = (
        "content-planning-write-result/1.0"
    )
    disposition: Literal["SAVED", "NO_CHANGE"]
    replayed: bool
    composition: ContentEditionCompositionV1
    current_revision_id: DeliverableRevisionId
