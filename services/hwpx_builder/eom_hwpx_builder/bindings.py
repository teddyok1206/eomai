"""Compile and apply template-hash-bound marker and object bindings."""

from __future__ import annotations

import io
import posixpath
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lxml import etree  # type: ignore[import-untyped]
from PIL import Image

from eom_hwpx_builder.archive import SafePackage, read_package
from eom_hwpx_builder.errors import HwpxError, HwpxErrorCode
from eom_hwpx_builder.models import (
    BindingKind,
    BindingManifest,
    PackageLimits,
    TemplateBinding,
)
from eom_hwpx_builder.util import canonical_json_bytes, sha256_bytes
from eom_hwpx_builder.xmlsafe import local_name, namespace_uri, parse_xml

TEXT_MARKERS: dict[str, str] = {
    "document_title": "{{EOM_DOCUMENT_TITLE}}",
    "item.item_number": "{{EOM_ITEM_NUMBER}}",
    "item.upper_stem": "{{EOM_UPPER_STEM}}",
    "item.lower_stem": "{{EOM_LOWER_STEM}}",
    "item.points": "{{EOM_POINTS}}",
    "item.table.rows.0.0": "{{EOM_TABLE_R1C1}}",
    "item.table.rows.0.1": "{{EOM_TABLE_R1C2}}",
    "item.table.rows.0.2": "{{EOM_TABLE_R1C3}}",
    "item.table.rows.1.0": "{{EOM_TABLE_R2C1}}",
    "item.table.rows.1.1": "{{EOM_TABLE_R2C2}}",
    "item.table.rows.1.2": "{{EOM_TABLE_R2C3}}",
    "item.statements.giyeok": "{{EOM_STATEMENT_GIYEOK}}",
    "item.statements.nieun": "{{EOM_STATEMENT_NIEUN}}",
    "item.statements.digeut": "{{EOM_STATEMENT_DIGEUT}}",
    "item.choices.0": "{{EOM_CHOICE_1}}",
    "item.choices.1": "{{EOM_CHOICE_2}}",
    "item.choices.2": "{{EOM_CHOICE_3}}",
    "item.choices.3": "{{EOM_CHOICE_4}}",
    "item.choices.4": "{{EOM_CHOICE_5}}",
    "solution.answer": "{{EOM_ANSWER}}",
    "solution.authoring_intent": "{{EOM_AUTHORING_INTENT}}",
    "solution.overview": "{{EOM_SOLUTION_OVERVIEW}}",
    "solution.statement_explanations.giyeok": "{{EOM_EXPLANATION_GIYEOK}}",
    "solution.statement_explanations.nieun": "{{EOM_EXPLANATION_NIEUN}}",
    "solution.statement_explanations.digeut": "{{EOM_EXPLANATION_DIGEUT}}",
}


@dataclass(frozen=True)
class TextOccurrence:
    part_name: str
    paragraph_index: int
    first_node_index: int
    last_node_index: int
    first_offset: int
    last_offset: int
    prefix: str
    suffix: str
    split: bool
    namespace: str
    local_name: str
    structure_fingerprint: str


def _fingerprint(element: etree._Element) -> str:
    chain = []
    current: etree._Element | None = element
    for _ in range(4):
        if current is None:
            break
        chain.append(
            {
                "namespace": namespace_uri(current.tag),
                "local_name": local_name(current.tag),
                "attributes": sorted(
                    (local_name(key), value) for key, value in current.attrib.items()
                ),
            }
        )
        current = current.getparent()
    return sha256_bytes(canonical_json_bytes(chain))


def _text_occurrences(root: etree._Element, part_name: str, marker: str) -> list[TextOccurrence]:
    all_text_nodes = [element for element in root.iter() if local_name(element.tag) == "t"]
    paragraphs = [element for element in root.iter() if local_name(element.tag) == "p"]
    if not paragraphs:
        paragraphs = [root]
    occurrences: list[TextOccurrence] = []
    for paragraph_index, paragraph in enumerate(paragraphs):
        nodes = [element for element in paragraph.iter() if local_name(element.tag) == "t"]
        combined = "".join(element.text or "" for element in nodes)
        search_from = 0
        while (start := combined.find(marker, search_from)) >= 0:
            end = start + len(marker)
            offsets: list[tuple[int, int, int]] = []
            cursor = 0
            for local_index, node in enumerate(nodes):
                length = len(node.text or "")
                offsets.append((local_index, cursor, cursor + length))
                cursor += length
            first_local = next(index for index, begin, finish in offsets if begin <= start < finish)
            last_local = next(index for index, begin, finish in offsets if begin < end <= finish)
            first_begin = offsets[first_local][1]
            last_begin = offsets[last_local][1]
            first_text = nodes[first_local].text or ""
            last_text = nodes[last_local].text or ""
            first_offset = start - first_begin
            last_offset = end - last_begin
            occurrences.append(
                TextOccurrence(
                    part_name=part_name,
                    paragraph_index=paragraph_index,
                    first_node_index=all_text_nodes.index(nodes[first_local]),
                    last_node_index=all_text_nodes.index(nodes[last_local]),
                    first_offset=first_offset,
                    last_offset=last_offset,
                    prefix=first_text[:first_offset],
                    suffix=last_text[last_offset:],
                    split=first_local != last_local,
                    namespace=namespace_uri(nodes[first_local].tag),
                    local_name=local_name(nodes[first_local].tag),
                    structure_fingerprint=_fingerprint(nodes[first_local]),
                )
            )
            search_from = end
    return occurrences


def _xml_roots(package: SafePackage, limits: PackageLimits) -> dict[str, etree._Element]:
    return {
        entry.info.filename: parse_xml(entry.data, entry.info.filename, limits).root
        for entry in package.entries
        if entry.info.filename.lower().endswith((".xml", ".hpf"))
    }


def _unique_text_binding(
    roots: dict[str, etree._Element], field_name: str, marker: str
) -> TemplateBinding:
    occurrences = [
        occurrence
        for part_name, root in roots.items()
        for occurrence in _text_occurrences(root, part_name, marker)
    ]
    if not occurrences:
        raise HwpxError(
            HwpxErrorCode.HWPX_TEMPLATE_MARKER_MISSING, f"required marker missing: {field_name}"
        )
    if len(occurrences) != 1:
        raise HwpxError(
            HwpxErrorCode.HWPX_TEMPLATE_MARKER_DUPLICATE,
            f"required marker is not unique: {field_name}",
        )
    occurrence = occurrences[0]
    kind = (
        BindingKind.TABLE_CELL_MARKER
        if field_name.startswith("item.table.")
        else BindingKind.TEXT_MARKER
    )
    locator = {
        "namespace_uri": occurrence.namespace,
        "local_name": occurrence.local_name,
        "paragraph_index": occurrence.paragraph_index,
        "first_text_node_index": occurrence.first_node_index,
        "last_text_node_index": occurrence.last_node_index,
        "first_offset": occurrence.first_offset,
        "last_offset": occurrence.last_offset,
        "structure_fingerprint": occurrence.structure_fingerprint,
    }
    constraints: dict[str, Any] = {
        "split_across_text_nodes": occurrence.split,
        "prefix": occurrence.prefix,
        "suffix": occurrence.suffix,
        "preserve_first_run_style": True,
    }
    if kind == BindingKind.TABLE_CELL_MARKER:
        root = roots[occurrence.part_name]
        text_nodes = [element for element in root.iter() if local_name(element.tag) == "t"]
        bound_node = text_nodes[occurrence.first_node_index]
        ancestor_tables = [
            element for element in bound_node.iterancestors() if local_name(element.tag) == "tbl"
        ]
        ancestor_cells = [
            element
            for element in bound_node.iterancestors()
            if local_name(element.tag) in {"tc", "cell"}
        ]
        if len(ancestor_tables) != 1 or len(ancestor_cells) != 1:
            raise HwpxError(
                HwpxErrorCode.HWPX_TEMPLATE_BINDING_FAILED,
                f"table marker is not in one non-nested cell: {field_name}",
            )
        table = ancestor_tables[0]
        cell = ancestor_cells[0]
        cells = [
            candidate
            for candidate in table.iter()
            if local_name(candidate.tag) in {"tc", "cell"}
            and next(
                (
                    ancestor
                    for ancestor in candidate.iterancestors()
                    if local_name(ancestor.tag) == "tbl"
                ),
                None,
            )
            is table
        ]
        expected_row = int(field_name.split(".")[-2])
        expected_column = int(field_name.split(".")[-1])
        expected_index = expected_row * 3 + expected_column
        if len(cells) != 6 or cells.index(cell) != expected_index:
            raise HwpxError(
                HwpxErrorCode.HWPX_TEMPLATE_BINDING_FAILED,
                f"table marker is outside the fixed 2x3 position: {field_name}",
            )
        locator["table_fingerprint"] = _fingerprint(table)
        locator["cell_index"] = expected_index
        constraints.update({"rows": 2, "columns": 3, "nested_table": False})
    return TemplateBinding(
        field_name=field_name,
        part_name=occurrence.part_name,
        binding_kind=kind,
        locator=locator,
        expected_original_value=marker,
        constraints=constraints,
    )


def _image_binding(
    package: SafePackage,
    roots: dict[str, etree._Element],
    reference_image_sha256: str,
) -> TemplateBinding:
    matches = [
        entry
        for entry in package.entries
        if entry.info.filename.casefold().startswith("bindata/")
        and sha256_bytes(entry.data) == reference_image_sha256
    ]
    if len(matches) != 1:
        raise HwpxError(
            HwpxErrorCode.HWPX_IMAGE_BINDING_FAILED,
            "reference PNG hash does not identify one embedded binary",
        )
    entry = matches[0]
    try:
        with Image.open(io.BytesIO(entry.data)) as image:
            image.verify()
        with Image.open(io.BytesIO(entry.data)) as image:
            width, height = image.size
            mode = image.mode
            file_format = image.format
    except Exception as exc:
        raise HwpxError(HwpxErrorCode.HWPX_IMAGE_BINDING_FAILED, "bound image is invalid") from exc
    if file_format != "PNG" or mode not in {"RGB", "RGBA"}:
        raise HwpxError(HwpxErrorCode.HWPX_IMAGE_BINDING_FAILED, "bound image is not RGB/RGBA PNG")
    manifest_ids: list[str] = []
    content_root = roots.get("Contents/content.hpf")
    if content_root is not None:
        for element in content_root.iter():
            if local_name(element.tag).casefold() != "item":
                continue
            attributes = {
                local_name(key).casefold(): value for key, value in element.attrib.items()
            }
            href = attributes.get("href")
            identifier = attributes.get("id")
            if not href or not identifier:
                continue
            resolved = posixpath.normpath(posixpath.join("Contents", href))
            if resolved == entry.info.filename:
                manifest_ids.append(identifier)
    if len(manifest_ids) != 1:
        raise HwpxError(
            HwpxErrorCode.HWPX_IMAGE_BINDING_FAILED,
            "bound PNG does not have one manifest identifier",
        )
    manifest_id = manifest_ids[0]
    object_matches: list[etree._Element] = []
    for part_name, root in roots.items():
        if part_name == "Contents/content.hpf":
            continue
        for element in root.iter():
            if any(value == manifest_id for value in element.attrib.values()):
                object_matches.append(element)
    if len(object_matches) != 1:
        raise HwpxError(
            HwpxErrorCode.HWPX_IMAGE_BINDING_FAILED,
            "manifest image identifier does not resolve to one object",
        )
    image_object = object_matches[0]
    object_id = next(
        (value for key, value in image_object.attrib.items() if local_name(key) == "id"), None
    )
    return TemplateBinding(
        field_name="item.image",
        part_name=entry.info.filename,
        binding_kind=BindingKind.IMAGE_BINARY,
        locator={
            "binary_sha256": reference_image_sha256,
            "manifest_id": manifest_id,
            "object_namespace_uri": namespace_uri(image_object.tag),
            "object_local_name": local_name(image_object.tag),
            "object_fingerprint": _fingerprint(image_object),
        },
        expected_original_value=reference_image_sha256,
        object_id=object_id,
        binary_part=entry.info.filename,
        reference_ids=(manifest_id,),
        constraints={
            "width_px": width,
            "height_px": height,
            "mode": mode,
            "media_type": "image/png",
        },
    )


def _equation_binding(roots: dict[str, etree._Element]) -> TemplateBinding:
    matches: list[tuple[str, int, etree._Element, str | None]] = []
    for part_name, root in roots.items():
        for element_index, element in enumerate(root.iter()):
            if "EOM_EQ_PLACEHOLDER" in (element.text or ""):
                matches.append((part_name, element_index, element, None))
            for attribute_name, value in element.attrib.items():
                if "EOM_EQ_PLACEHOLDER" in value:
                    matches.append((part_name, element_index, element, attribute_name))
    anchor_locator: dict[str, Any] | None = None
    expected_equation = "EOM_EQ_PLACEHOLDER"
    binding_kind = BindingKind.EQUATION_SCRIPT
    if not matches:
        anchors = [
            occurrence
            for part, root in roots.items()
            for occurrence in _text_occurrences(root, part, "{{EOM_EQUATION_ANCHOR}}")
        ]
        candidates: list[tuple[str, int, etree._Element, str | None]] = []
        for part_name, root in roots.items():
            for element_index, element in enumerate(root.iter()):
                if (
                    "equation" not in local_name(element.tag).casefold()
                    and local_name(element.tag).casefold() != "eq"
                ):
                    continue
                for attribute_name, value in element.attrib.items():
                    if (
                        local_name(attribute_name).casefold()
                        in {
                            "script",
                            "value",
                            "text",
                            "equation",
                        }
                        and value
                    ):
                        candidates.append((part_name, element_index, element, attribute_name))
                if element.text and element.text.strip():
                    candidates.append((part_name, element_index, element, None))
        if len(anchors) != 1 or len(candidates) != 1 or anchors[0].part_name != candidates[0][0]:
            raise HwpxError(
                HwpxErrorCode.HWPX_EQUATION_BINDING_FAILED,
                "equation anchor does not resolve to one observed equation source",
            )
        anchor = anchors[0]
        anchor_locator = {
            "namespace_uri": anchor.namespace,
            "local_name": anchor.local_name,
            "first_text_node_index": anchor.first_node_index,
            "last_text_node_index": anchor.last_node_index,
            "first_offset": anchor.first_offset,
            "last_offset": anchor.last_offset,
            "structure_fingerprint": anchor.structure_fingerprint,
            "prefix": anchor.prefix,
            "suffix": anchor.suffix,
        }
        matches = [candidates[0]]
        candidate_element = candidates[0][2]
        candidate_attribute = candidates[0][3]
        expected_equation = (
            candidate_element.attrib[candidate_attribute]
            if candidate_attribute
            else candidate_element.text or ""
        )
        binding_kind = BindingKind.EQUATION_ANCHOR
    if len(matches) != 1:
        raise HwpxError(HwpxErrorCode.HWPX_EQUATION_BINDING_FAILED, "equation marker is not unique")
    part_name, element_index, element, attribute_name = matches[0]
    object_id = next(
        (value for key, value in element.attrib.items() if local_name(key).lower() == "id"), None
    )
    locator: dict[str, Any] = {
        "namespace_uri": namespace_uri(element.tag),
        "local_name": local_name(element.tag),
        "element_index": element_index,
        "structure_fingerprint": _fingerprint(element),
        "value_location": "attribute" if attribute_name else "text",
    }
    if attribute_name:
        locator["attribute_namespace_uri"] = namespace_uri(attribute_name)
        locator["attribute_local_name"] = local_name(attribute_name)
    constraints: dict[str, Any] = {
        "allowed_pattern": r"^[A-Za-z0-9+\-*/=() ._^]+$",
        "max_length": 200,
    }
    if anchor_locator is not None:
        constraints["anchor_text_locator"] = anchor_locator
    return TemplateBinding(
        field_name="item.equation.source",
        part_name=part_name,
        binding_kind=binding_kind,
        locator=locator,
        expected_original_value=expected_equation,
        object_id=object_id,
        constraints=constraints,
    )


def compile_bindings(
    template: Path,
    *,
    template_id: str,
    template_revision_id: str,
    reference_image_sha256: str,
    limits: PackageLimits | None = None,
) -> BindingManifest:
    actual_limits = limits or PackageLimits()
    package = read_package(template, actual_limits)
    roots = _xml_roots(package, actual_limits)
    bindings = [
        _unique_text_binding(roots, field_name, marker)
        for field_name, marker in TEXT_MARKERS.items()
    ]
    bindings.append(_image_binding(package, roots, reference_image_sha256))
    bindings.append(_equation_binding(roots))
    warnings = tuple(
        f"SPLIT_MARKER_NORMALIZED:{binding.field_name}"
        for binding in bindings
        if binding.constraints.get("split_across_text_nodes") is True
    )
    payload = {
        "manifest_version": "1.0",
        "template_id": template_id,
        "template_revision_id": template_revision_id,
        "template_sha256": package.package_sha256,
        "bindings": [binding.model_dump(mode="json") for binding in bindings],
        "warnings": list(warnings),
    }
    manifest_hash = sha256_bytes(canonical_json_bytes(payload))
    return BindingManifest(
        manifest_version="1.0",
        template_id=template_id,
        template_revision_id=template_revision_id,
        template_sha256=package.package_sha256,
        binding_manifest_sha256=manifest_hash,
        bindings=tuple(bindings),
        warnings=warnings,
    )


def replace_text_binding(root: etree._Element, binding: TemplateBinding, replacement: str) -> bool:
    nodes = [element for element in root.iter() if local_name(element.tag) == "t"]
    try:
        first_index = int(binding.locator["first_text_node_index"])
        last_index = int(binding.locator["last_text_node_index"])
        first = nodes[first_index]
        last = nodes[last_index]
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise HwpxError(
            HwpxErrorCode.HWPX_TEXT_REPLACEMENT_FAILED, "text binding locator no longer resolves"
        ) from exc
    if _fingerprint(first) != binding.locator.get("structure_fingerprint"):
        raise HwpxError(
            HwpxErrorCode.HWPX_TEMPLATE_BINDING_FAILED, "text binding structure changed"
        )
    first_offset = int(binding.locator["first_offset"])
    last_offset = int(binding.locator["last_offset"])
    first_text = first.text or ""
    last_text = last.text or ""
    observed = (
        first_text[first_offset:last_offset]
        if first is last
        else first_text[first_offset:]
        + "".join((node.text or "") for node in nodes[first_index + 1 : last_index])
        + last_text[:last_offset]
    )
    if observed != binding.expected_original_value:
        raise HwpxError(HwpxErrorCode.HWPX_TEMPLATE_HASH_MISMATCH, "bound marker value changed")
    prefix = first_text[:first_offset]
    suffix = last_text[last_offset:]
    first.text = prefix + replacement + suffix
    for node in nodes[first_index + 1 : last_index + 1]:
        node.text = ""
    return first_index != last_index
