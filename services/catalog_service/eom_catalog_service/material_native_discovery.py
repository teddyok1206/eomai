"""Pure native inventory/pair checks shared by execution and selective reanalysis."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import TYPE_CHECKING

from eom_catalog_contracts.material_native_files import (
    material_native_printed_number,
    material_native_solution_number,
)
from eom_catalog_contracts.material_native_intake import MaterialNativeExamBundle
from eom_workflow.material_learning_plan import PlannedMaterialUnit

if TYPE_CHECKING:
    from eom_catalog_service.material_learning_coordinator import MaterialDiscoveryPlan


@dataclass(frozen=True, slots=True)
class NativeMaterialDiscoveryPairs:
    questions: Mapping[int, PlannedMaterialUnit]
    solutions: Mapping[int, PlannedMaterialUnit]


def native_material_discovery_pairs(
    plan: MaterialDiscoveryPlan, bundle: MaterialNativeExamBundle
) -> NativeMaterialDiscoveryPairs:
    """Validate exact identity/number coverage without declaring any region complete."""
    expected = {item.item_number for item in bundle.items}
    questions: dict[int, PlannedMaterialUnit] = {}
    solutions: dict[int, PlannedMaterialUnit] = {}
    originals = {"MAIN": bundle.main_original, "SOLUTIONS": bundle.solutions_original}
    for planned in plan.by_unit.values():
        unit = planned.unit
        if unit.kind not in {"QUESTION", "SOLUTION"}:
            continue
        role = "MAIN" if unit.kind == "QUESTION" else "SOLUTIONS"
        if planned.source.source_role != role:
            raise ValueError("MATERIAL_NATIVE_DISCOVERY_ROLE_MISMATCH")
        if planned.source.original != originals[role]:
            raise ValueError("MATERIAL_NATIVE_DISCOVERY_SOURCE_MISMATCH")
        try:
            number = (
                material_native_printed_number(unit.printed_label)
                if unit.kind == "QUESTION"
                else material_native_solution_number(unit.printed_label)
            )
        except ValueError as exc:
            raise ValueError("MATERIAL_NATIVE_DISCOVERY_NUMBER_INVALID") from exc
        selected = questions if unit.kind == "QUESTION" else solutions
        if number in selected:
            raise ValueError("MATERIAL_NATIVE_DISCOVERY_NUMBER_DUPLICATED")
        selected[number] = planned
    if set(questions) != expected or set(solutions) != expected:
        raise ValueError("MATERIAL_NATIVE_DISCOVERY_COVERAGE_MISMATCH")
    return NativeMaterialDiscoveryPairs(MappingProxyType(questions), MappingProxyType(solutions))


def bind_native_material_discovery_plan(
    plan: MaterialDiscoveryPlan, bundle: MaterialNativeExamBundle
) -> MaterialDiscoveryPlan:
    """Native file/Excel numbers constrain discovery; they never invent model regions."""
    pairs = native_material_discovery_pairs(plan, bundle)
    if any(
        value.unit.continuation != "COMPLETE"
        for values in (pairs.questions, pairs.solutions)
        for value in values.values()
    ):
        raise ValueError("MATERIAL_NATIVE_DISCOVERY_REGION_INCOMPLETE")
    units = dict(plan.by_unit)
    for number, question in pairs.questions.items():
        units[question.unit_key] = replace(
            question,
            solution_unit_keys=(pairs.solutions[number].unit_key,),
            issue_codes=tuple(
                code
                for code in question.issue_codes
                if code
                not in {
                    "NO_SOURCE_SOLUTION_INDEPENDENT_SOLUTION_REQUIRED",
                    "AMBIGUOUS_SOURCE_SOLUTION",
                }
            ),
        )
    return replace(plan, by_unit=MappingProxyType(units))


def incomplete_native_discovery_tasks(
    plan: MaterialDiscoveryPlan, bundle: MaterialNativeExamBundle
) -> frozenset[str]:
    """Select only source-proven incomplete owners; never repair accepted model output."""
    pairs = native_material_discovery_pairs(plan, bundle)
    selected = frozenset(
        value.discovery_task_id
        for values in (pairs.questions, pairs.solutions)
        for value in values.values()
        if value.unit.continuation != "COMPLETE"
    )
    if not selected:
        raise ValueError("MATERIAL_NATIVE_DISCOVERY_REANALYSIS_NOT_REQUIRED")
    return selected
