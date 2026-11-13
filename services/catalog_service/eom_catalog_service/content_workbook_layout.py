"""Ordered workbook-to-edition layout; repeated targets get separate occurrence IDs."""

from collections import defaultdict
from collections.abc import Iterator
from typing import Literal

from eom_catalog_contracts.content_planning import CONTENT_MAX_SECTIONS, ContentSectionStructure
from eom_catalog_contracts.content_planning_commands import CreatePlannedContent
from eom_catalog_contracts.content_workbook_import import (
    ContentWorkbookDocument,
    ContentWorkbookProposal,
)
from eom_catalog_contracts.curated_document_slots import CuratedSlot

from eom_catalog_service.content_planning_access import ContentPlanningError
from eom_catalog_service.content_planning_storage import new_content_id


def _workbook_sections(
    document: ContentWorkbookDocument,
) -> Iterator[tuple[Literal["GROUP", "FORM"], str, str]]:
    """Shared ordered membership rule for lightweight admission and actual layout."""
    groups: set[str] = set()
    forms: set[tuple[str, str]] = set()
    for row in document.rows:
        group = row.group_label
        if group and group not in groups:
            groups.add(group)
            yield "GROUP", group, ""
        key = (group, row.section_label)
        if key not in forms:
            forms.add(key)
            yield "FORM", *key


def _bounded_workbook_sections(
    document: ContentWorkbookDocument,
) -> Iterator[tuple[Literal["GROUP", "FORM"], str, str]]:
    for count, section in enumerate(_workbook_sections(document), 1):
        if count > CONTENT_MAX_SECTIONS:
            raise ContentPlanningError("CONTENT_WORKBOOK_STRUCTURE_TOO_LARGE")
        yield section


def require_workbook_layout(document: ContentWorkbookDocument) -> None:
    """Check the existing Edition bound without allocating IDs, slots or file copies."""
    for _section in _bounded_workbook_sections(document):
        pass


def workbook_layout(
    proposal: ContentWorkbookProposal,
) -> tuple[CreatePlannedContent, dict[str, tuple[CuratedSlot, ...]]]:
    structures: list[ContentSectionStructure] = []
    groups: dict[str, str] = {}
    sections: dict[tuple[str, str], str] = {}
    children: dict[str | None, int] = defaultdict(int)
    slots: dict[str, list[CuratedSlot]] = defaultdict(list)

    def section(parent: str | None, kind: str, label: str) -> str:
        identity = new_content_id("section")
        children[parent] += 1
        structures.append(
            ContentSectionStructure.model_validate(
                dict(
                    section_id=identity,
                    parent_id=parent,
                    kind=kind,
                    ordinal=children[parent],
                    label=label,
                    numbering="RESET_PER_SECTION",
                )
            )
        )
        return identity

    for kind, group, label in _bounded_workbook_sections(proposal.document):
        if kind == "GROUP":
            groups[group] = section(None, kind, group)
        else:
            sections[(group, label)] = section(groups.get(group), kind, label or "본문")
    for row, resolution in zip(proposal.document.rows, proposal.resolutions, strict=True):
        if resolution.target is None:
            raise ContentPlanningError("CONTENT_WORKBOOK_UNRESOLVED")
        identity = sections[(row.group_label, row.section_label)]
        slots[identity].append(
            CuratedSlot(
                placement_id=new_content_id("placement"),
                position=len(slots[identity]) + 1,
                display_number=row.display_number,
                points_milli=row.points_milli,
                note=row.note,
                copied_from=None,
                target=resolution.target,
            )
        )
    metadata = proposal.document.metadata
    return CreatePlannedContent(
        command_kind="CREATE_CONTENT",
        content_title=metadata.content_title,
        content_type=metadata.content_type,
        edition_label=metadata.edition_label,
        academic_year=metadata.academic_year,
        sections=tuple(structures),
    ), {key: tuple(value) for key, value in slots.items()}
