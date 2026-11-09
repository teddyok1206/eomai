"""Edition structure and exact Form/Assembly pointers, independent of storage."""

from __future__ import annotations

from collections import defaultdict
from typing import Annotated, Literal, Self

from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_catalog_contracts.curated_document_slots import AssemblyId, AssemblyRevisionId
from eom_catalog_contracts.models import ActorId, FrozenModel, Sha256, UtcDatetime

DeliverableId = Annotated[str, Field(pattern=r"^deliverable_[0-9a-f]{32}$")]
DeliverableRevisionId = Annotated[str, Field(pattern=r"^delivrev_[0-9a-f]{32}$")]
EditionId = Annotated[str, Field(pattern=r"^edition_[0-9a-f]{32}$")]
SectionId = Annotated[str, Field(pattern=r"^section_[0-9a-f]{32}$")]
FormId = Annotated[str, Field(pattern=r"^form_[0-9a-f]{32}$")]
FormRevisionId = Annotated[str, Field(pattern=r"^formrev_[0-9a-f]{32}$")]
ContentLabel = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[^\x00-\x1f\x7f]+$")]
AcademicYear = Annotated[int, Field(strict=True, ge=1900, le=3000)]
type ContentType = Literal["MOCK_EXAM", "TEXTBOOK", "WEEKLY", "OTHER"]
type NumberingPolicy = Literal["RESET_PER_SECTION", "CONTINUE_WITHIN_GROUP"]


class ContentFormPointer(FrozenModel):
    form_id: FormId
    form_revision_id: FormRevisionId
    form_sha256: Sha256
    assembly_id: AssemblyId
    assembly_revision_id: AssemblyRevisionId
    manifest_sha256: Sha256
    placement_count: int = Field(strict=True, ge=0, le=100000)


class ContentSectionStructure(FrozenModel):
    section_id: SectionId
    parent_id: SectionId | None
    kind: Literal["GROUP", "FORM"]
    ordinal: int = Field(strict=True, ge=1, le=10000)
    label: ContentLabel
    numbering: NumberingPolicy

    @model_validator(mode="after")
    def canonical_label(self) -> Self:
        if self.label != self.label.strip():
            raise ValueError("section label must not have outer whitespace")
        return self


class ContentSection(ContentSectionStructure):
    form: ContentFormPointer | None

    @model_validator(mode="after")
    def form_branch(self) -> Self:
        if (self.kind == "FORM") != (self.form is not None):
            raise ValueError("only FORM sections carry a Form revision pointer")
        return self


def validate_section_tree(sections: tuple[ContentSectionStructure, ...]) -> None:
    """Linear adjacency traversal, not per-section ancestor scans or recursion."""

    by_id = {section.section_id: section for section in sections}
    if len(by_id) != len(sections):
        raise ValueError("section identities must be unique")
    children: dict[str | None, list[ContentSectionStructure]] = defaultdict(list)
    for section in sections:
        if section.parent_id is not None:
            parent = by_id.get(section.parent_id)
            if parent is None or parent.kind != "GROUP":
                raise ValueError("section parent must be an existing GROUP")
        siblings = children[section.parent_id]
        if section.ordinal != len(siblings) + 1:
            raise ValueError("sibling ordinals must be contiguous and ordered")
        siblings.append(section)
    stack = [(section, 1) for section in reversed(children[None])]
    visited: list[str] = []
    while stack:
        section, depth = stack.pop()
        if depth > 64:
            raise ValueError("section nesting exceeds 64 levels")
        visited.append(section.section_id)
        stack.extend((child, depth + 1) for child in reversed(children[section.section_id]))
    if visited != list(by_id):
        raise ValueError("sections must form an acyclic canonical preorder tree")


class ContentEditionCompositionV1(FrozenModel):
    schema_version: Literal["content-edition-composition/1.0"]
    deliverable_id: DeliverableId
    edition_id: EditionId
    deliverable_revision_id: DeliverableRevisionId
    revision_number: int = Field(strict=True, ge=1)
    previous_revision_id: DeliverableRevisionId | None
    content_title: ContentLabel
    content_type: ContentType
    edition_label: ContentLabel
    academic_year: AcademicYear | None
    sections: tuple[ContentSection, ...] = Field(max_length=10000)
    created_by: ActorId
    created_at: UtcDatetime
    composition_sha256: Sha256

    @model_validator(mode="after")
    def immutable_tree(self) -> Self:
        validate_section_tree(self.sections)
        forms = [section.form.form_id for section in self.sections if section.form is not None]
        if len(forms) != len(set(forms)):
            raise ValueError("one Form may appear in only one section")
        if (self.revision_number == 1) != (self.previous_revision_id is None):
            raise ValueError("edition predecessor must be null only for revision one")
        if self.previous_revision_id == self.deliverable_revision_id:
            raise ValueError("edition revision cannot precede itself")
        if any(value != value.strip() for value in (self.content_title, self.edition_label)):
            raise ValueError("content labels must not have outer whitespace")
        if self.composition_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"composition_sha256"})
        ):
            raise ValueError("edition composition hash differs")
        return self


class ContentSectionPathEntry(FrozenModel):
    section_id: SectionId
    label: ContentLabel


class ContentScopedForm(FrozenModel):
    section_id: SectionId
    path: tuple[ContentSectionPathEntry, ...] = Field(min_length=1, max_length=64)
    form: ContentFormPointer
    numbering: NumberingPolicy
    start_number: int = Field(strict=True, ge=1, le=1000000000)

    @model_validator(mode="after")
    def exact_path(self) -> Self:
        ids = tuple(entry.section_id for entry in self.path)
        if ids[-1] != self.section_id or len(ids) != len(set(ids)):
            raise ValueError("print scope path must end at its unique leaf section")
        return self


class ContentPrintScopeV1(FrozenModel):
    schema_version: Literal["content-print-scope/1.0"]
    deliverable_id: DeliverableId
    edition_id: EditionId
    content_title: ContentLabel
    edition_label: ContentLabel
    academic_year: AcademicYear | None
    forms: tuple[ContentScopedForm, ...] = Field(min_length=1, max_length=10000)
    scope_sha256: Sha256

    @model_validator(mode="after")
    def exact_forms(self) -> Self:
        if len({form.section_id for form in self.forms}) != len(self.forms):
            raise ValueError("print scope repeats a section")
        if len({form.form.form_id for form in self.forms}) != len(self.forms):
            raise ValueError("print scope repeats a Form")
        if any(form.form.placement_count == 0 for form in self.forms):
            raise ValueError("an empty Form cannot be recorded as printed")
        if self.scope_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"scope_sha256"})
        ):
            raise ValueError("print scope hash differs")
        return self
