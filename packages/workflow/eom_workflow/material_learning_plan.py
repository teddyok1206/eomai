"""Pure ordered plan over validated discovery; no files, DB or model execution.

The frequent operations are membership, source lookup and sparse label joins.
Maps/sets make planning O(pages + regions + candidates), excluding output size.
Printed numbers are local labels, never a global Item identity.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from eom_catalog_contracts.material_learning import (
    MaterialDiscoveredUnit,
    MaterialDiscoveryResult,
    MaterialDiscoveryWork,
    MaterialPreparedSource,
    SourceRole,
    validate_material_discovery,
)
from eom_identifiers import content_sha256


@dataclass(frozen=True, slots=True)
class MaterialDiscoveryWindow:
    source_role: SourceRole
    first_core_page: int
    last_core_page: int
    first_input_page: int
    last_input_page: int


def material_discovery_windows(
    source_role: SourceRole, page_count: int, *, core_size: int = 4
) -> tuple[MaterialDiscoveryWindow, ...]:
    if source_role not in {"MAIN", "SOLUTIONS"} or not 1 <= page_count <= 2000:
        raise ValueError("MATERIAL_LEARNING_WINDOW_SOURCE_INVALID")
    if not 1 <= core_size <= 8:
        raise ValueError("MATERIAL_LEARNING_WINDOW_SIZE_INVALID")
    return tuple(
        MaterialDiscoveryWindow(
            source_role,
            first,
            min(first + core_size - 1, page_count),
            max(1, first - 1),
            min(first + core_size, page_count),
        )
        for first in range(1, page_count + 1, core_size)
    )


@dataclass(frozen=True, slots=True)
class DiscoveredMaterialRange:
    work: MaterialDiscoveryWork
    result: MaterialDiscoveryResult


@dataclass(frozen=True, slots=True)
class PlannedMaterialUnit:
    unit_key: str
    ordinal: int
    discovery_task_id: str
    source: MaterialPreparedSource
    unit: MaterialDiscoveredUnit
    solution_unit_keys: tuple[str, ...]
    issue_codes: tuple[str, ...]


def material_unit_key(source: MaterialPreparedSource, unit: MaterialDiscoveredUnit) -> str:
    if any(anchor.source_role != source.source_role for anchor in unit.anchors):
        raise ValueError("MATERIAL_LEARNING_UNIT_SOURCE_MISMATCH")
    # A result's prose/local_key can change between explicitly reviewed discovery
    # attempts without turning the same pinned source region into a new Item.
    signature = {
        "document_revision_id": source.document_revision_id,
        "original_sha256": source.original.sha256,
        "source_role": source.source_role,
        "kind": unit.kind,
        "section_path": unit.section_path,
        "printed_label": unit.printed_label,
        "anchors": [anchor.model_dump(mode="json") for anchor in unit.anchors],
    }
    return "materialunit_" + content_sha256(signature).removeprefix("sha256:")[:32]


def plan_material_learning_units(
    ranges: tuple[DiscoveredMaterialRange, ...],
) -> tuple[PlannedMaterialUnit, ...]:
    if not ranges:
        raise ValueError("MATERIAL_LEARNING_DISCOVERY_REQUIRED")
    first = ranges[0].work
    sources = {source.source_role: source for source in first.sources}
    covered: set[tuple[str, int]] = set()
    owned: dict[str, tuple[str, MaterialPreparedSource, MaterialDiscoveredUnit]] = {}
    for discovered in ranges:
        work, result = discovered.work, discovered.result
        if (
            work.material_id != first.material_id
            or work.material_revision_id != first.material_revision_id
            or work.sources != first.sources
            or work.rights_attestation != first.rights_attestation
            or work.additional_instructions != first.additional_instructions
        ):
            raise ValueError("MATERIAL_LEARNING_DISCOVERY_SOURCE_MIXED")
        validate_material_discovery(result, work)
        core = {(page.source_role, page.physical_page) for page in work.core_pages}
        if core.intersection(covered):
            raise ValueError("MATERIAL_LEARNING_DISCOVERY_CORE_OVERLAP")
        covered.update(core)
        for unit in result.units:
            start = unit.anchors[0]
            if (start.source_role, start.physical_page) not in core:
                continue
            source = sources[start.source_role]
            key = material_unit_key(source, unit)
            if key in owned:
                raise ValueError("MATERIAL_LEARNING_DISCOVERY_UNIT_DUPLICATE")
            owned[key] = (work.task_id, source, unit)
    expected = {
        (source.source_role, page)
        for source in first.sources
        for page in range(1, source.page_count + 1)
    }
    if covered != expected:
        raise ValueError("MATERIAL_LEARNING_DISCOVERY_BOOK_COVERAGE_INCOMPLETE")
    source_order = {role: index for index, role in enumerate(sources)}
    ordered = sorted(
        owned.items(),
        key=lambda entry: (
            source_order[entry[1][1].source_role],
            entry[1][2].anchors[0].physical_page,
            entry[1][2].anchors[0].bounding_box.top,
            entry[1][2].anchors[0].bounding_box.left,
            entry[1][2].kind,
            entry[0],
        ),
    )
    # Each source answer contributes only to labels it actually declares. There
    # is no all-questions x all-solutions scan and no fuzzy number-only match.
    answers: dict[tuple[tuple[str, ...], str], list[str]] = defaultdict(list)
    for key, (_, _, unit) in ordered:
        if unit.kind not in {"SOLUTION", "ANSWER_KEY"} or unit.continuation != "COMPLETE":
            continue
        labels = set(unit.related_item_labels)
        if unit.printed_label is not None:
            labels.add(unit.printed_label)
        for label in labels:
            answers[(unit.section_path, label)].append(key)
    output: list[PlannedMaterialUnit] = []
    for ordinal, (key, (task_id, source, unit)) in enumerate(ordered, 1):
        issues: list[str] = []
        matched: tuple[str, ...] = ()
        if unit.continuation != "COMPLETE":
            issues.append("INCOMPLETE_SOURCE_REGION")
        if unit.kind == "QUESTION" and unit.continuation == "COMPLETE":
            if unit.printed_label is not None:
                candidates = tuple(answers.get((unit.section_path, unit.printed_label), ()))
                kinds = Counter(owned[value][2].kind for value in candidates)
                if len(candidates) > 8 or any(count > 1 for count in kinds.values()):
                    issues.append("AMBIGUOUS_SOURCE_SOLUTION")
                else:
                    matched = candidates
            if not matched and not issues:
                issues.append("NO_SOURCE_SOLUTION_INDEPENDENT_SOLUTION_REQUIRED")
        output.append(
            PlannedMaterialUnit(key, ordinal, task_id, source, unit, matched, tuple(issues))
        )
    return tuple(output)
