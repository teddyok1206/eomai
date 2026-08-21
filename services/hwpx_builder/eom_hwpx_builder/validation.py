"""Structural validation for the bounded HWPX POC profile."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Literal, cast

from eom_hwpx_builder.analyzer import CORE_PARTS, MIMETYPE, analyze_package
from eom_hwpx_builder.archive import read_package
from eom_hwpx_builder.bindings import TEXT_MARKERS
from eom_hwpx_builder.models import (
    BindingManifest,
    CheckStatus,
    PackageLimits,
    StructuralValidationReport,
    TemplateBinding,
    ValidationCheck,
)
from eom_hwpx_builder.util import sha256_bytes
from eom_hwpx_builder.xmlsafe import local_name, parse_xml


def _check(
    check_id: str,
    passed: bool,
    message: str,
    *,
    part: str | None = None,
    warning: bool = False,
    evidence: bytes | None = None,
) -> ValidationCheck:
    status = CheckStatus.PASS if passed else (CheckStatus.WARN if warning else CheckStatus.FAIL)
    severity: Literal["INFO", "WARNING", "ERROR"] = (
        "INFO" if passed else ("WARNING" if warning else "ERROR")
    )
    return ValidationCheck(
        check_id=check_id,
        status=status,
        severity=severity,
        message=message,
        part=part,
        evidence_hash=sha256_bytes(evidence) if evidence is not None else None,
    )


UNIQUE_OBJECT_ID_ELEMENTS = {
    "arc",
    "container",
    "curve",
    "ellipse",
    "equation",
    "line",
    "ole",
    "pic",
    "polygon",
    "rect",
    "textart",
    "tbl",
}


def _duplicate_ids(package_path: Path, limits: PackageLimits) -> list[str]:
    package = read_package(package_path, limits)
    duplicates: list[str] = []
    global_xml_ids: Counter[str] = Counter()
    for entry in package.entries:
        if not entry.info.filename.lower().endswith((".xml", ".hpf")):
            continue
        root = parse_xml(entry.data, entry.info.filename, limits).root
        object_ids: Counter[str] = Counter()
        for element in root.iter():
            for attribute_name, value in element.attrib.items():
                if (
                    local_name(attribute_name) == "id"
                    and value
                    and local_name(element.tag).casefold() in UNIQUE_OBJECT_ID_ELEMENTS
                ):
                    object_ids[value] += 1
                if attribute_name == "{http://www.w3.org/XML/1998/namespace}id":
                    global_xml_ids[value] += 1
        duplicates.extend(
            f"{entry.info.filename}:{identifier}"
            for identifier, count in object_ids.items()
            if count > 1
        )
    duplicates.extend(
        f"xml:id:{identifier}" for identifier, count in global_xml_ids.items() if count > 1
    )
    return sorted(duplicates)


def validate_structure(
    path: Path,
    *,
    bindings: BindingManifest | None = None,
    expected_image_sha256: str | None = None,
    expected_equation_source: str | None = None,
    require_markers_removed: bool = False,
    limits: PackageLimits | None = None,
) -> StructuralValidationReport:
    actual_limits = limits or PackageLimits()
    package = read_package(path, actual_limits)
    by_name = package.by_name()
    analysis = analyze_package(path, actual_limits)
    checks: list[ValidationCheck] = []
    names = set(by_name)
    checks.append(_check("valid_zip", True, "bounded ZIP package parsed"))
    checks.append(
        _check(
            "required_core_parts",
            CORE_PARTS.issubset(names) and bool(analysis.sections),
            "required package parts and at least one section exist",
        )
    )
    checks.append(
        _check(
            "mimetype",
            analysis.mimetype == MIMETYPE,
            "mimetype is application/hwp+zip",
            part="mimetype",
            evidence=by_name["mimetype"].data if "mimetype" in by_name else None,
        )
    )
    checks.append(
        _check(
            "mimetype_first",
            bool(package.entries) and package.entries[0].info.filename == "mimetype",
            "mimetype is the first ZIP entry",
            warning=True,
        )
    )
    checks.append(
        _check("xml_well_formed_and_safe", True, "all XML parts passed the hardened parser")
    )
    rootfile_targets = [
        reference["target"]
        for reference in analysis.internal_references
        if reference["part"] == "META-INF/container.xml"
    ]
    checks.append(
        _check(
            "container_rootfile",
            rootfile_targets == ["Contents/content.hpf"]
            and all(target in names for target in rootfile_targets),
            "container rootfile resolves to Contents/content.hpf",
            part="META-INF/container.xml",
        )
    )
    missing_manifest = sorted(
        item["part"] for item in analysis.manifest_items if item["part"] not in names
    )
    checks.append(
        _check(
            "manifest_references",
            bool(analysis.manifest_items) and not missing_manifest,
            "manifest items resolve to package parts",
            part="Contents/content.hpf",
        )
    )
    manifest_ids = {item["id"] for item in analysis.manifest_items}
    checks.append(
        _check(
            "spine",
            bool(analysis.spine)
            and all(identifier in manifest_ids for identifier in analysis.spine)
            and all(section in names for section in analysis.sections),
            "ordered spine identifiers resolve to section parts",
            part="Contents/content.hpf",
        )
    )
    checks.append(_check("header", "Contents/header.xml" in names, "header part exists"))
    image_parts = {item["part"] for item in analysis.image_candidates}
    checks.append(
        _check(
            "bindata_references",
            bool(image_parts) and image_parts.issubset(names),
            "image manifest entries resolve to embedded binary parts",
        )
    )
    duplicate_ids = _duplicate_ids(path, actual_limits)
    checks.append(_check("xml_ids", not duplicate_ids, "XML IDs are unique in supported scope"))
    checks.append(
        _check(
            "active_content",
            not analysis.active_content and not analysis.external_links,
            "scripts, macros, OLE, encryption, signatures, embedded packages, "
            "and external links absent",
        )
    )
    markers = {location["marker"] for location in analysis.marker_locations}
    required_markers = set(TEXT_MARKERS.values())
    marker_ok = (
        not markers
        if require_markers_removed
        else required_markers.issubset(markers)
        and bool({"EOM_EQ_PLACEHOLDER", "{{EOM_EQUATION_ANCHOR}}"} & markers)
    )
    checks.append(
        _check(
            "marker_state",
            marker_ok,
            "template markers present" if not require_markers_removed else "all markers removed",
        )
    )
    if bindings is not None:
        checks.append(
            _check(
                "template_binding_hash",
                bindings.template_sha256 == package.package_sha256
                if not require_markers_removed
                else True,
                "binding manifest is tied to template revision",
            )
        )
        image_binding = next(
            (binding for binding in bindings.bindings if binding.field_name == "item.image"), None
        )
        image_part = image_binding.binary_part if image_binding else None
        image_ok = bool(
            image_part
            and image_part in by_name
            and (
                expected_image_sha256 is None
                or sha256_bytes(by_name[image_part].data) == expected_image_sha256
            )
        )
        checks.append(_check("image_binary", image_ok, "bound PNG exists with expected hash"))
        equation_binding = next(
            (
                binding
                for binding in bindings.bindings
                if binding.field_name == "item.equation.source"
            ),
            None,
        )
        equation_ok = equation_binding is not None
        if equation_binding is not None and expected_equation_source is not None:
            equation_ok = (
                _equation_value(path, equation_binding, actual_limits) == expected_equation_source
            )
        checks.append(
            _check("equation_binding", equation_ok, "bound equation source is extractable")
        )
    preview_present = any(name.startswith("Preview/") for name in names)
    checks.append(
        ValidationCheck(
            check_id="preview",
            status=CheckStatus.WARN if preview_present else CheckStatus.NOT_APPLICABLE,
            severity="WARNING" if preview_present else "INFO",
            message=(
                "PREVIEW_IMAGE_STALE: reference Preview is preserved"
                if preview_present
                else "no Preview part"
            ),
        )
    )
    passed = not any(check.status == CheckStatus.FAIL for check in checks)
    return StructuralValidationReport(
        status="PASS" if passed else "FAIL",
        package_sha256=package.package_sha256,
        checks=tuple(checks),
    )


def _equation_value(path: Path, binding: TemplateBinding, limits: PackageLimits) -> str | None:
    package = read_package(path, limits)
    entry = package.by_name().get(binding.part_name)
    if entry is None:
        return None
    root = parse_xml(entry.data, binding.part_name, limits).root
    try:
        element = list(root.iter())[int(binding.locator["element_index"])]
    except (IndexError, KeyError, TypeError, ValueError):
        return None
    if binding.locator.get("value_location") == "text":
        return cast(str | None, element.text)
    requested = binding.locator.get("attribute_local_name")
    return next(
        (value for key, value in element.attrib.items() if local_name(key) == requested), None
    )


def validate_kordoc_structure(
    path: Path,
    *,
    expected_equation_count: int,
    expected_table_count: int,
    limits: PackageLimits | None = None,
) -> StructuralValidationReport:
    """Validate generated Kordoc output without applying template-only invariants."""

    actual_limits = limits or PackageLimits()
    base = validate_structure(path, require_markers_removed=True, limits=actual_limits)
    checks = [
        check
        for check in base.checks
        if check.check_id not in {"bindata_references", "required_core_parts"}
    ]
    names = set(read_package(path, actual_limits).by_name())
    generated_core = {
        "mimetype",
        "META-INF/container.xml",
        "Contents/content.hpf",
        "Contents/header.xml",
    }
    checks.append(
        _check(
            "required_generated_core_parts",
            generated_core.issubset(names)
            and any(
                name.startswith("Contents/section") and name.endswith(".xml") for name in names
            ),
            "generated profile core parts and at least one section exist",
        )
    )
    equation_count, table_count = kordoc_native_structure_counts(path, actual_limits)
    checks.extend(
        (
            _check(
                "renderer_profile",
                True,
                "kordoc-markdown-v1 uses common package checks without template bindings",
            ),
            _check(
                "native_equation_count",
                equation_count == expected_equation_count,
                "native equation count matches the validated Markdown contract",
            ),
            _check(
                "native_table_count",
                table_count == expected_table_count,
                "native table count matches the validated Markdown contract",
            ),
        )
    )
    passed = not any(check.status == CheckStatus.FAIL for check in checks)
    return StructuralValidationReport(
        status="PASS" if passed else "FAIL",
        package_sha256=base.package_sha256,
        checks=tuple(checks),
    )


def kordoc_native_structure_counts(
    path: Path, limits: PackageLimits | None = None
) -> tuple[int, int]:
    """Return equation/table counts after the same bounded package/XML parsing."""

    actual_limits = limits or PackageLimits()
    package = read_package(path, actual_limits)
    equations = 0
    tables = 0
    for entry in package.entries:
        name = entry.info.filename
        suffix = name.removeprefix("Contents/section").removesuffix(".xml")
        if (
            not name.startswith("Contents/section")
            or not name.endswith(".xml")
            or not suffix.isdigit()
        ):
            continue
        root = parse_xml(entry.data, name, actual_limits).root
        for element in root.iter():
            element_name = local_name(element.tag).casefold()
            equations += element_name == "equation"
            tables += element_name == "tbl"
    return equations, tables
