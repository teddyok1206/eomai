"""Binding-based semantic extraction and narrowly normalized comparison."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from eom_hwpx_builder.archive import read_package
from eom_hwpx_builder.models import (
    BindingKind,
    BindingManifest,
    PackageLimits,
    SemanticComparison,
    SemanticValidationReport,
    TemplateBinding,
)
from eom_hwpx_builder.util import canonical_json_bytes, sha256_bytes
from eom_hwpx_builder.validation import _equation_value
from eom_hwpx_builder.xmlsafe import local_name, parse_xml


def flatten_document(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "document_title": document["document_title"],
        "item.item_number": document["item"]["item_number"],
        "item.upper_stem": document["item"]["upper_stem"],
        "item.lower_stem": document["item"]["lower_stem"],
        "item.points": document["item"]["points"],
        **{
            f"item.table.rows.{row}.{column}": document["item"]["table"]["rows"][row][column]
            for row in range(2)
            for column in range(3)
        },
        **{
            f"item.statements.{key}": document["item"]["statements"][key]
            for key in ("giyeok", "nieun", "digeut")
        },
        **{
            f"item.choices.{index}": value
            for index, value in enumerate(document["item"]["choices"])
        },
        "solution.answer": document["solution"]["answer"],
        "solution.authoring_intent": document["solution"]["authoring_intent"],
        "solution.overview": document["solution"]["overview"],
        **{
            f"solution.statement_explanations.{key}": document["solution"][
                "statement_explanations"
            ][key]
            for key in ("giyeok", "nieun", "digeut")
        },
        "item.image.sha256": document["item"]["image"]["sha256"],
        "item.equation.source": document["item"]["equation"]["source"],
    }


def _text_value(root: Any, binding: TemplateBinding) -> str | None:
    nodes = [element for element in root.iter() if local_name(element.tag) == "t"]
    try:
        node = nodes[int(binding.locator["first_text_node_index"])]
    except (IndexError, KeyError, TypeError, ValueError):
        return None
    value = node.text or ""
    prefix = str(binding.constraints.get("prefix", ""))
    suffix = str(binding.constraints.get("suffix", ""))
    if prefix and not value.startswith(prefix):
        return None
    if suffix and not value.endswith(suffix):
        return None
    start = len(prefix)
    end = len(value) - len(suffix) if suffix else len(value)
    return value[start:end]


def extract_semantic(
    path: Path, bindings: BindingManifest, limits: PackageLimits | None = None
) -> dict[str, Any]:
    actual_limits = limits or PackageLimits()
    package = read_package(path, actual_limits)
    by_name = package.by_name()
    roots: dict[str, Any] = {}
    values: dict[str, Any] = {}
    for binding in bindings.bindings:
        if binding.binding_kind in {BindingKind.TEXT_MARKER, BindingKind.TABLE_CELL_MARKER}:
            if binding.part_name not in roots:
                entry = by_name.get(binding.part_name)
                if entry is None:
                    values[binding.field_name] = None
                    continue
                roots[binding.part_name] = parse_xml(
                    entry.data, binding.part_name, actual_limits
                ).root
            values[binding.field_name] = _text_value(roots[binding.part_name], binding)
        elif binding.binding_kind == BindingKind.IMAGE_BINARY:
            entry = by_name.get(binding.binary_part or "")
            values["item.image.sha256"] = sha256_bytes(entry.data) if entry else None
        elif binding.binding_kind in {BindingKind.EQUATION_SCRIPT, BindingKind.EQUATION_ANCHOR}:
            values[binding.field_name] = _equation_value(path, binding, actual_limits)
    section_parts = [
        entry
        for entry in package.entries
        if entry.info.filename in {item.part_name for item in bindings.bindings}
    ]
    paragraph_count = 0
    for entry in section_parts:
        if entry.info.filename.lower().endswith((".xml", ".hpf")):
            root = parse_xml(entry.data, entry.info.filename, actual_limits).root
            paragraph_count += sum(local_name(element.tag) == "p" for element in root.iter())
    values["section_count"] = len(
        {
            binding.part_name
            for binding in bindings.bindings
            if "section" in binding.part_name.casefold()
        }
    )
    values["paragraph_count"] = paragraph_count
    return values


def _normalize(value: Any) -> Any:
    return value.replace("\r\n", "\n").replace("\r", "\n") if isinstance(value, str) else value


def compare_semantic(
    expected_document: dict[str, Any],
    actual_path: Path,
    bindings: BindingManifest,
    limits: PackageLimits | None = None,
) -> SemanticValidationReport:
    expected = flatten_document(expected_document)
    actual = extract_semantic(actual_path, bindings, limits)
    comparisons: dict[str, SemanticComparison] = {}
    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        if actual_value is None:
            comparisons[key] = SemanticComparison.NOT_EXTRACTABLE
        elif actual_value == expected_value:
            comparisons[key] = SemanticComparison.EXACT_MATCH
        elif _normalize(actual_value) == _normalize(expected_value):
            comparisons[key] = SemanticComparison.NORMALIZED_MATCH
        else:
            comparisons[key] = SemanticComparison.MISMATCH
    passed = all(
        status in {SemanticComparison.EXACT_MATCH, SemanticComparison.NORMALIZED_MATCH}
        for status in comparisons.values()
    )
    semantic_hash = sha256_bytes(canonical_json_bytes(actual))
    return SemanticValidationReport(
        status="PASS" if passed else "FAIL",
        semantic_hash=semantic_hash,
        fields=comparisons,
        extracted=actual,
    )
