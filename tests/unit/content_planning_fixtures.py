"""Synthetic, pointer-only examples. No production workbook/item content."""

from eom_identifiers import content_sha256

SHA = "sha256:" + "a" * 64
TIME = "2026-11-09T09:40:00Z"


def identifier(prefix: str, number: int = 1) -> str:
    return f"{prefix}_{number:032x}"


def item_target(number: int = 1) -> dict:
    return {
        "placement_kind": "REGISTERED_ITEM_REVISION",
        "item_id": identifier("item", number),
        "item_revision_id": identifier("itemrev", number),
        "item_manifest_sha256": SHA,
        "graph_snapshot_revision_id": identifier("graphrev"),
        "graph_snapshot_sha256": SHA,
    }


def source_target() -> dict:
    return {
        "placement_kind": "EXTERNAL_SOURCE_DOCUMENT",
        "source_id": identifier("extitem"),
        "source_revision_id": identifier("extitemrev"),
        "observation_sha256": SHA,
        "edition": 3,
        "source_format": "HWPX",
    }


def slot(position: int, *, target: dict | None = None) -> dict:
    return {
        "placement_id": identifier("placement", position),
        "position": position,
        "target": target or item_target(),
        "points_milli": None,
        "display_number": None,
        "note": "",
        "copied_from": None,
    }


def draft(count: int = 2) -> dict:
    return {
        "schema_version": "curated-document-assembly-draft/3.0",
        "title": "학교별 맞춤 시험지",
        "placements": [slot(position) for position in range(1, count + 1)],
    }


def form(number: int = 1, count: int = 20) -> dict:
    return {
        "form_id": identifier("form", number),
        "form_revision_id": identifier("formrev", number),
        "form_sha256": SHA,
        "assembly_id": identifier("assembly", number),
        "assembly_revision_id": identifier("assemblyrev", number),
        "manifest_sha256": SHA,
        "placement_count": count,
    }


def section(number: int = 1, ordinal: int = 1, parent: int | None = None) -> dict:
    return {
        "section_id": identifier("section", number),
        "parent_id": None if parent is None else identifier("section", parent),
        "kind": "FORM",
        "ordinal": ordinal,
        "label": f"{number}회차",
        "numbering": "RESET_PER_SECTION",
        "form": form(number),
    }


def composition(sections: list[dict] | None = None, **changes) -> dict:
    value = {
        "schema_version": "content-edition-composition/1.0",
        "deliverable_id": identifier("deliverable"),
        "edition_id": identifier("edition"),
        "deliverable_revision_id": identifier("delivrev"),
        "revision_number": 1,
        "previous_revision_id": None,
        "content_title": "새로운 학교 맞춤 콘텐츠",
        "content_type": "OTHER",
        "edition_label": "2027 초판",
        "academic_year": 2027,
        "sections": [section()] if sections is None else sections,
        "created_by": identifier("operator"),
        "created_at": TIME,
        **changes,
    }
    value["composition_sha256"] = content_sha256(value)
    return value
