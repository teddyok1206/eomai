"""Deterministic whole-exam renderer built from reviewed content-team item layouts."""

from __future__ import annotations

import copy
import json
import os
import stat
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, cast

from eom_hwpx_contracts import (
    ContentTeamExamBuildResult,
    ContentTeamExamBuildResultContract,
    ContentTeamExamBuildResultV2,
    ContentTeamExamBuildResultV3,
    ContentTeamExamImageSource,
    ContentTeamExamItemSourceV2,
    ContentTeamExamItemSourceV3,
    ContentTeamExamRenderRequest,
    ContentTeamExamRenderRequestContract,
    ContentTeamExamRenderRequestV2,
    ContentTeamExamRenderRequestV3,
    ContentTeamImageSource,
    content_team_exam_item_set_projection,
    content_team_exam_render_plan_projection,
    parse_content_team_markdown,
    parse_content_team_markdown_v2,
    serialize_content_team_markdown,
    validate_contract,
)
from lxml import etree  # type: ignore[import-untyped]
from pydantic import ValidationError

from eom_hwpx_builder.analyzer import analyze_package, resolve_part
from eom_hwpx_builder.archive import FIXED_ZIP_TIMESTAMP, SafePackage, read_package
from eom_hwpx_builder.content_team_handoff import (
    EXPECTED_MEMBER_HASHES,
    inspect_content_team_handoff,
)
from eom_hwpx_builder.content_team_images import inject_content_team_images
from eom_hwpx_builder.content_team_renderer import (
    MAX_IMAGE_BYTES,
    MAX_JSON_BYTES,
    MAX_MARKDOWN_BYTES,
    _external_render,
    _extract_runtime,
    _load_draft,
    _read_regular,
    _workspace_path,
)
from eom_hwpx_builder.errors import HwpxError, HwpxErrorCode
from eom_hwpx_builder.handoff import (
    finalize_failure_result,
    finalize_success_handoff,
    prepare_private_handoff_file,
    write_private_json,
)
from eom_hwpx_builder.util import canonical_json_bytes, sha256_bytes, sha256_file
from eom_hwpx_builder.xmlsafe import ParsedXml, local_name, parse_xml, serialize_xml

EXAM_RENDERER_VERSION = "1.0.0"
EXAM_RENDERER_VERSION_V2 = "2.0.0"
EXAM_RENDERER_VERSION_V3 = "3.0.0"
MAX_EXAM_PACKAGE_BYTES = 64 * 1024 * 1024
MAX_HANDOFF_BYTES = 64 * 1024 * 1024

_PLANNED_SCORE_DISPLAY = {1500: "1.5", 2000: "2", 2500: "2.5", 3000: "3"}

_HEADER_RESOURCE_CATALOGS = (
    "tabProperties",
    "charProperties",
    "paraProperties",
    "styles",
)
_SECTION_RESOURCE_REFERENCES = {
    "tabpridref": "tabProperties",
    "charpridref": "charProperties",
    "parapridref": "paraProperties",
    "styleidref": "styles",
    "charstyleidref": "styles",
}


def _load_exam_request(raw: dict[str, Any]) -> ContentTeamExamRenderRequestContract:
    if raw.get("schema_version") == "content-team-exam-render-request/3.0":
        validate_contract("content-team-exam-render-request-v3", raw)
        return ContentTeamExamRenderRequestV3.model_validate(raw)
    if raw.get("schema_version") == "content-team-exam-render-request/2.0":
        validate_contract("content-team-exam-render-request-v2", raw)
        return ContentTeamExamRenderRequestV2.model_validate(raw)
    validate_contract("content-team-exam-render-request", raw)
    return ContentTeamExamRenderRequest.model_validate(raw)


def _item_set_sha256(request: ContentTeamExamRenderRequestContract) -> str:
    return sha256_bytes(canonical_json_bytes(content_team_exam_item_set_projection(request)))


def _render_plan_sha256(
    request: ContentTeamExamRenderRequestV2 | ContentTeamExamRenderRequestV3,
) -> str:
    return sha256_bytes(canonical_json_bytes(content_team_exam_render_plan_projection(request)))


def _read_request(path: Path) -> bytes:
    """Capture one bounded regular request through a stable no-follow descriptor."""

    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSAFE, "request cannot be opened") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= 4 * 1024 * 1024:
            raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSAFE, "request metadata is unsafe")
        payload = bytearray()
        while len(payload) < before.st_size:
            chunk = os.read(descriptor, min(before.st_size - len(payload), 1024 * 1024))
            if not chunk:
                raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSAFE, "request was truncated")
            payload.extend(chunk)
        if os.read(descriptor, 1):
            raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSAFE, "request grew while reading")
        after = os.fstat(descriptor)
        before_identity = (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_nlink,
            before.st_size,
            before.st_mtime_ns,
        )
        after_identity = (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_nlink,
            after.st_size,
            after.st_mtime_ns,
        )
        if before_identity != after_identity:
            raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSAFE, "request changed while reading")
        return bytes(payload)
    finally:
        os.close(descriptor)


def _attribute(element: etree._Element, name: str) -> str | None:
    for key, value in element.attrib.items():
        if local_name(key).casefold() == name.casefold():
            return str(value)
    return None


def _set_attribute(element: etree._Element, name: str, value: str) -> None:
    for key in element.attrib:
        if local_name(key).casefold() == name.casefold():
            element.attrib[key] = value
            return
    element.attrib[name] = value


def _serialize_like(original: bytes, part_name: str, root: etree._Element) -> bytes:
    parsed = parse_xml(original, part_name)
    return serialize_xml(
        ParsedXml(
            root=root,
            declaration=parsed.declaration,
            newline=parsed.newline,
            bom=parsed.bom,
        )
    )


def _manifest_parts(
    package: SafePackage,
) -> tuple[etree._Element, etree._Element, etree._Element, etree._Element]:
    entries = package.by_name()
    try:
        content = parse_xml(entries["Contents/content.hpf"].data, "Contents/content.hpf").root
    except KeyError as exc:
        raise HwpxError(
            HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
            "content-team item has no package manifest",
        ) from exc
    manifest = next(
        (element for element in content.iter() if local_name(element.tag) == "manifest"), None
    )
    spine = next(
        (element for element in content.iter() if local_name(element.tag) == "spine"), None
    )
    if manifest is None or spine is None:
        raise HwpxError(
            HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
            "content-team item manifest is incomplete",
        )
    items = [element for element in manifest if local_name(element.tag) == "item"]
    section_items = [
        element
        for element in items
        if (_attribute(element, "href") or "").rsplit("/", 1)[-1].startswith("section")
    ]
    if len(section_items) != 1:
        raise HwpxError(
            HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
            "content-team item must expose exactly one section",
        )
    return content, manifest, spine, section_items[0]


def _binary_manifest_items(
    package: SafePackage, manifest: etree._Element
) -> tuple[tuple[etree._Element, str], ...]:
    names = package.by_name()
    result: list[tuple[etree._Element, str]] = []
    for element in manifest:
        if local_name(element.tag) != "item":
            continue
        href = _attribute(element, "href")
        if href is None:
            continue
        resolved = resolve_part("Contents/content.hpf", href)
        if resolved.startswith("BinData/"):
            if resolved not in names:
                raise HwpxError(
                    HwpxErrorCode.HWPX_REFERENCE_BROKEN,
                    "content-team item binary manifest target is missing",
                )
            result.append((element, resolved))
    return tuple(result)


def _remove_attribute(element: etree._Element, name: str) -> None:
    for key in tuple(element.attrib):
        if local_name(key).casefold() == name.casefold():
            del element.attrib[key]


def _header_catalog(root: etree._Element, name: str) -> etree._Element | None:
    matches = tuple(element for element in root.iter() if local_name(element.tag) == name)
    if len(matches) > 1:
        raise HwpxError(
            HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
            "content-team header resource catalog is ambiguous",
        )
    return matches[0] if matches else None


def _catalog_rows(
    catalog: etree._Element | None,
) -> tuple[tuple[str, etree._Element], ...]:
    if catalog is None:
        return ()
    if catalog.text is not None and catalog.text.strip():
        raise HwpxError(
            HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
            "content-team header resource catalog contains unexpected text",
        )
    count = _attribute(catalog, "itemCnt")
    if count is None:
        if len(catalog):
            raise HwpxError(
                HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
                "content-team header resource count is missing",
            )
    else:
        try:
            valid_count = int(count) == len(catalog)
        except ValueError:
            valid_count = False
        if not valid_count:
            raise HwpxError(
                HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
                "content-team header resource count differs",
            )
    rows: list[tuple[str, etree._Element]] = []
    identifiers: set[int] = set()
    for child in catalog:
        identifier = _attribute(child, "id")
        if identifier is None:
            raise HwpxError(
                HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
                "content-team header resource identity is invalid",
            )
        try:
            numeric_id = int(identifier)
        except ValueError as exc:
            raise HwpxError(
                HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
                "content-team header resource identity is invalid",
            ) from exc
        if numeric_id < 0 or numeric_id in identifiers:
            raise HwpxError(
                HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
                "content-team header resource identity is invalid",
            )
        identifiers.add(numeric_id)
        rows.append((identifier, child))
    return tuple(rows)


def _header_skeleton(root: etree._Element) -> bytes:
    skeleton = copy.deepcopy(root)
    _remove_attribute(skeleton, "secCnt")
    for name in _HEADER_RESOURCE_CATALOGS:
        catalog = _header_catalog(skeleton, name)
        _catalog_rows(catalog)
        if catalog is None:
            continue
        for child in tuple(catalog):
            catalog.remove(child)
        catalog.text = None
        _remove_attribute(catalog, "itemCnt")
    return cast(bytes, etree.tostring(skeleton, encoding="utf-8", with_tail=False))


def _definition_key(element: etree._Element, catalog_name: str) -> bytes:
    clone = copy.deepcopy(element)
    identifier = _attribute(clone, "id")
    _remove_attribute(clone, "id")
    clone.tail = None
    if catalog_name == "styles":
        next_style = _attribute(clone, "nextStyleIDRef")
        if next_style is not None and next_style == identifier:
            _set_attribute(clone, "nextStyleIDRef", "__SELF__")
    return cast(bytes, etree.tostring(clone, encoding="utf-8", with_tail=False))


def _remap_attributes(
    element: etree._Element,
    attributes: dict[str, tuple[dict[str, str], bool]],
) -> None:
    for node in element.iter():
        for key, value in tuple(node.attrib.items()):
            target = attributes.get(local_name(key).casefold())
            if target is None:
                continue
            mapping, catalog_exists = target
            if not catalog_exists:
                continue
            replacement = mapping.get(str(value))
            if replacement is None:
                raise HwpxError(
                    HwpxErrorCode.HWPX_REFERENCE_BROKEN,
                    "content-team header resource reference is missing",
                )
            node.attrib[key] = replacement


def _next_resource_id(used: set[int], preferred: str, next_candidate: int) -> tuple[str, int]:
    numeric = int(preferred)
    if numeric not in used:
        used.add(numeric)
        return str(numeric), max(next_candidate, numeric + 1)
    allocated = next_candidate
    while allocated in used:
        allocated += 1
    used.add(allocated)
    return str(allocated), allocated + 1


def _validate_header_resource_references(
    rows: dict[str, tuple[tuple[str, etree._Element], ...]],
    mappings: dict[str, dict[str, str]],
    catalog_names: frozenset[str],
) -> None:
    for _source_id, source in rows["paraProperties"]:
        _remap_attributes(
            copy.deepcopy(source),
            {
                "tabpridref": (
                    mappings.get("tabProperties", {}),
                    "tabProperties" in catalog_names,
                )
            },
        )
    for _source_id, source in rows["styles"]:
        _remap_attributes(
            copy.deepcopy(source),
            {
                "charpridref": (
                    mappings.get("charProperties", {}),
                    "charProperties" in catalog_names,
                ),
                "parapridref": (
                    mappings.get("paraProperties", {}),
                    "paraProperties" in catalog_names,
                ),
                "nextstyleidref": (
                    mappings.get("styles", {}),
                    "styles" in catalog_names,
                ),
            },
        )


def _merge_header_resources(
    roots: tuple[etree._Element, ...],
) -> tuple[
    etree._Element,
    tuple[dict[str, dict[str, str]], ...],
    frozenset[str],
]:
    if not roots:
        raise HwpxError(
            HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
            "content-team exam has no header resources",
        )
    expected_skeleton = _header_skeleton(roots[0])
    if any(_header_skeleton(root) != expected_skeleton for root in roots[1:]):
        raise HwpxError(
            HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
            "content-team item header changed outside renderer-owned resources",
        )

    merged = copy.deepcopy(roots[0])
    merged_catalogs = {name: _header_catalog(merged, name) for name in _HEADER_RESOURCE_CATALOGS}
    catalog_names = frozenset(name for name, value in merged_catalogs.items() if value is not None)
    indexes: dict[str, dict[bytes, str]] = {}
    used_ids: dict[str, set[int]] = {}
    next_ids: dict[str, int] = {}
    first_mapping: dict[str, dict[str, str]] = {}
    first_rows: dict[str, tuple[tuple[str, etree._Element], ...]] = {}
    for name, catalog in merged_catalogs.items():
        rows = _catalog_rows(catalog)
        first_rows[name] = rows
        identity_mapping = {identifier: identifier for identifier, _child in rows}
        first_mapping[name] = identity_mapping
        indexes[name] = {}
        used_ids[name] = {int(identifier) for identifier in identity_mapping}
        next_ids[name] = max(used_ids[name], default=-1) + 1
        for identifier, child in rows:
            indexes[name].setdefault(_definition_key(child, name), identifier)
    _validate_header_resource_references(first_rows, first_mapping, catalog_names)

    all_mappings: list[dict[str, dict[str, str]]] = [first_mapping]
    for root in roots[1:]:
        source_catalogs = {name: _header_catalog(root, name) for name in _HEADER_RESOURCE_CATALOGS}
        if (
            frozenset(name for name, value in source_catalogs.items() if value is not None)
            != catalog_names
        ):
            raise HwpxError(
                HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
                "content-team item header resource catalogs differ",
            )
        source_rows = {name: _catalog_rows(catalog) for name, catalog in source_catalogs.items()}
        mappings: dict[str, dict[str, str]] = {}
        for name in ("tabProperties", "charProperties", "paraProperties"):
            mapping: dict[str, str] = {}
            target = merged_catalogs[name]
            for source_id, source in source_rows[name]:
                clone = copy.deepcopy(source)
                if name == "paraProperties":
                    _remap_attributes(
                        clone,
                        {
                            "tabpridref": (
                                mappings.get("tabProperties", {}),
                                "tabProperties" in catalog_names,
                            )
                        },
                    )
                key = _definition_key(clone, name)
                output_id = indexes[name].get(key)
                if output_id is None:
                    if target is None:
                        raise HwpxError(
                            HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
                            "content-team header resource target is missing",
                        )
                    output_id, next_ids[name] = _next_resource_id(
                        used_ids[name], source_id, next_ids[name]
                    )
                    _set_attribute(clone, "id", output_id)
                    target.append(clone)
                    indexes[name][key] = output_id
                mapping[source_id] = output_id
            mappings[name] = mapping

        style_mapping: dict[str, str] = {}
        pending_styles: list[tuple[str, str, etree._Element]] = []
        style_target = merged_catalogs["styles"]
        for source_id, source in source_rows["styles"]:
            clone = copy.deepcopy(source)
            _remap_attributes(
                clone,
                {
                    "charpridref": (
                        mappings.get("charProperties", {}),
                        "charProperties" in catalog_names,
                    ),
                    "parapridref": (
                        mappings.get("paraProperties", {}),
                        "paraProperties" in catalog_names,
                    ),
                },
            )
            key = _definition_key(clone, "styles")
            output_id = indexes["styles"].get(key)
            if output_id is None:
                if style_target is None:
                    raise HwpxError(
                        HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
                        "content-team header style target is missing",
                    )
                output_id, next_ids["styles"] = _next_resource_id(
                    used_ids["styles"], source_id, next_ids["styles"]
                )
                indexes["styles"][key] = output_id
                pending_styles.append((source_id, output_id, clone))
            style_mapping[source_id] = output_id
        mappings["styles"] = style_mapping
        for source_id, output_id, clone in pending_styles:
            next_style = _attribute(clone, "nextStyleIDRef")
            if next_style is not None:
                replacement = style_mapping.get(next_style)
                if replacement is None:
                    raise HwpxError(
                        HwpxErrorCode.HWPX_REFERENCE_BROKEN,
                        "content-team next-style reference is missing",
                    )
                if next_style != source_id and replacement != next_style:
                    raise HwpxError(
                        HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
                        "content-team cross-style remapping is unsupported",
                    )
                _set_attribute(clone, "nextStyleIDRef", replacement)
            _set_attribute(clone, "id", output_id)
            if style_target is None:  # pragma: no cover - guarded above
                raise AssertionError("style target disappeared")
            style_target.append(clone)
        for source_id, source in source_rows["styles"]:
            next_style = _attribute(source, "nextStyleIDRef")
            if next_style is None or next_style == source_id:
                continue
            replacement = style_mapping.get(next_style)
            if replacement is None or replacement != next_style:
                raise HwpxError(
                    HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
                    "content-team cross-style remapping is unsupported",
                )
        _validate_header_resource_references(source_rows, mappings, catalog_names)
        all_mappings.append(mappings)

    for catalog in merged_catalogs.values():
        if catalog is not None and (_attribute(catalog, "itemCnt") is not None or len(catalog)):
            _set_attribute(catalog, "itemCnt", str(len(catalog)))
    merged_rows = {name: _catalog_rows(catalog) for name, catalog in merged_catalogs.items()}
    merged_identity = {
        name: {identifier: identifier for identifier, _child in rows}
        for name, rows in merged_rows.items()
    }
    _validate_header_resource_references(merged_rows, merged_identity, catalog_names)
    return merged, tuple(all_mappings), catalog_names


def _rewrite_section_resource_references(
    section: etree._Element,
    mappings: dict[str, dict[str, str]],
    catalog_names: frozenset[str],
) -> None:
    attributes = {
        name: (mappings.get(catalog, {}), catalog in catalog_names)
        for name, catalog in _SECTION_RESOURCE_REFERENCES.items()
    }
    _remap_attributes(section, attributes)


def _merge_item_packages(items: tuple[Path, ...], output: Path) -> dict[str, Any]:
    if not items or len(items) > 200:
        raise HwpxError(HwpxErrorCode.HWPX_PACKAGE_BUILD_FAILED, "exam item set is invalid")
    packages = tuple(read_package(path) for path in items)
    first = packages[0]
    first_entries = first.by_name()
    first_content, first_manifest, first_spine, first_section_item = _manifest_parts(first)
    header_entries = []
    header_roots = []
    for package in packages:
        header = package.by_name().get("Contents/header.xml")
        if header is None:
            raise HwpxError(
                HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
                "content-team item has no shared header",
            )
        header_entries.append(header)
        header_roots.append(parse_xml(header.data, "Contents/header.xml").root)
    merged_header, header_mappings, header_catalog_names = _merge_header_resources(
        tuple(header_roots)
    )

    header_manifest_items = tuple(
        child
        for child in first_manifest
        if local_name(child.tag) == "item"
        and (href := _attribute(child, "href")) is not None
        and resolve_part("Contents/content.hpf", href) == "Contents/header.xml"
    )
    if len(header_manifest_items) != 1:
        raise HwpxError(
            HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
            "content-team item manifest has no unique shared header",
        )
    header_manifest_id = _attribute(header_manifest_items[0], "id")
    if header_manifest_id is None:
        raise HwpxError(
            HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
            "content-team item header identity is missing",
        )
    # Reviewed Hancom-authored packages and compatibility readers use archive-root
    # HPF hrefs. Keep renderer-owned entries root-qualified even though our bounded
    # reader also accepts OPF-relative spelling.
    _set_attribute(header_manifest_items[0], "href", "Contents/header.xml")

    section_manifest_ids = {
        identifier
        for child in first_manifest
        if local_name(child.tag) == "item"
        and (href := _attribute(child, "href")) is not None
        and PurePosixPath(resolve_part("Contents/content.hpf", href)).name.startswith("section")
        and (identifier := _attribute(child, "id")) is not None
    }
    for child in tuple(first_spine):
        if (
            local_name(child.tag) == "itemref"
            and _attribute(child, "idref") in section_manifest_ids
        ):
            first_spine.remove(child)
    header_spine_items = tuple(
        child
        for child in first_spine
        if local_name(child.tag) == "itemref" and _attribute(child, "idref") == header_manifest_id
    )
    if len(header_spine_items) > 1:
        raise HwpxError(
            HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
            "content-team item spine has duplicate shared header references",
        )
    if not header_spine_items:
        namespace = etree.QName(first_spine).namespace
        header_ref = etree.Element(f"{{{namespace}}}itemref" if namespace else "itemref")
        _set_attribute(header_ref, "idref", header_manifest_id)
        _set_attribute(header_ref, "linear", "yes")
        first_spine.insert(0, header_ref)
    for child in tuple(first_manifest):
        href = _attribute(child, "href") if local_name(child.tag) == "item" else None
        if href is not None and (
            resolve_part("Contents/content.hpf", href).startswith("BinData/")
            or (href.rsplit("/", 1)[-1].startswith("section"))
        ):
            first_manifest.remove(child)

    shared_payloads: dict[str, tuple[bytes, int]] = {}
    for entry in first.entries:
        name = entry.info.filename
        if (
            name == "Contents/content.hpf"
            or name == "Contents/header.xml"
            or name.startswith("Contents/section")
            or name.startswith("BinData/")
            or name.startswith("Preview/")
        ):
            continue
        shared_payloads[name] = (entry.data, entry.info.compress_type)
    payloads = dict(shared_payloads)

    item_reports: list[dict[str, Any]] = []
    for index, (path, package) in enumerate(zip(items, packages, strict=True)):
        actual_shared = {
            entry.info.filename: (entry.data, entry.info.compress_type)
            for entry in package.entries
            if entry.info.filename != "Contents/content.hpf"
            and entry.info.filename != "Contents/header.xml"
            and not entry.info.filename.startswith("Contents/section")
            and not entry.info.filename.startswith("BinData/")
            and not entry.info.filename.startswith("Preview/")
        }
        if actual_shared != shared_payloads:
            raise HwpxError(
                HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
                "exam item package has a different reviewed template runtime",
            )
        _content, manifest, _spine, section_item = _manifest_parts(package)
        entries = package.by_name()
        section_href = _attribute(section_item, "href")
        section_id = _attribute(section_item, "id")
        if section_href is None or section_id is None:
            raise HwpxError(
                HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
                "exam item section manifest is incomplete",
            )
        section_name = resolve_part("Contents/content.hpf", section_href)
        section_entry = entries.get(section_name)
        if section_entry is None:
            raise HwpxError(
                HwpxErrorCode.HWPX_REFERENCE_BROKEN,
                "exam item section target is missing",
            )
        section = parse_xml(section_entry.data, section_name).root
        _rewrite_section_resource_references(
            section,
            header_mappings[index],
            header_catalog_names,
        )
        binary_items = _binary_manifest_items(package, manifest)
        binary_id_map: dict[str, str] = {}
        for binary_number, (binary_item, binary_name) in enumerate(binary_items):
            old_id = _attribute(binary_item, "id")
            if old_id is None:
                raise HwpxError(
                    HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
                    "exam item binary identity is missing",
                )
            new_id = f"eomExam{index + 1:03d}Binary{binary_number:03d}"
            suffix = Path(binary_name).suffix.lower()
            new_name = f"BinData/item-{index + 1:03d}-{binary_number:03d}{suffix}"
            binary_id_map[old_id] = new_id
            cloned_binary = copy.deepcopy(binary_item)
            _set_attribute(cloned_binary, "id", new_id)
            _set_attribute(cloned_binary, "href", new_name)
            _set_attribute(cloned_binary, "isEmbeded", "1")
            first_manifest.append(cloned_binary)
            payloads[new_name] = (
                entries[binary_name].data,
                entries[binary_name].info.compress_type,
            )
        for element in section.iter():
            for key, value in tuple(element.attrib.items()):
                if local_name(key).casefold() == "binaryitemidref":
                    replacement = binary_id_map.get(str(value))
                    if replacement is None:
                        raise HwpxError(
                            HwpxErrorCode.HWPX_REFERENCE_BROKEN,
                            "section references an undeclared binary item",
                        )
                    element.attrib[key] = replacement
        new_section_id = f"section{index}"
        new_section_name = f"Contents/section{index}.xml"
        cloned_section = copy.deepcopy(first_section_item if index == 0 else section_item)
        _set_attribute(cloned_section, "id", new_section_id)
        _set_attribute(cloned_section, "href", new_section_name)
        first_manifest.append(cloned_section)
        itemref = etree.Element(first_spine[0].tag if len(first_spine) else cloned_section.tag)
        if local_name(itemref.tag) != "itemref":
            namespace = etree.QName(first_spine).namespace
            itemref = etree.Element(f"{{{namespace}}}itemref" if namespace else "itemref")
        _set_attribute(itemref, "idref", new_section_id)
        first_spine.append(itemref)
        payloads[new_section_name] = (
            _serialize_like(section_entry.data, section_name, section),
            section_entry.info.compress_type,
        )
        item_reports.append(
            {
                "position": index + 1,
                "source_file": path.name,
                "section": new_section_name,
                "binary_count": len(binary_items),
            }
        )

    _set_attribute(merged_header, "secCnt", str(len(items)))
    selected_header = header_entries[0]
    payloads["Contents/header.xml"] = (
        _serialize_like(selected_header.data, "Contents/header.xml", merged_header),
        selected_header.info.compress_type,
    )
    content_entry = first_entries["Contents/content.hpf"]
    payloads["Contents/content.hpf"] = (
        _serialize_like(content_entry.data, "Contents/content.hpf", first_content),
        content_entry.info.compress_type,
    )
    payloads["Preview/PrvText.txt"] = (
        f"EOM 통합과학 모의고사 · {len(items)}문항\n".encode(),
        zipfile.ZIP_DEFLATED,
    )

    output.parent.mkdir(mode=0o700, parents=True, exist_ok=False)
    temporary = output.with_name(f".{output.name}.tmp")
    total = 0
    try:
        with zipfile.ZipFile(temporary, "x", allowZip64=False) as archive:
            ordered_names = [
                "mimetype",
                *sorted(name for name in payloads if name != "mimetype"),
            ]
            for name in ordered_names:
                data, compression = payloads[name]
                total += len(data)
                if total > MAX_EXAM_PACKAGE_BYTES:
                    raise HwpxError(
                        HwpxErrorCode.HWPX_ZIP_BOMB_DETECTED,
                        "assembled exam exceeds its package limit",
                    )
                info = zipfile.ZipInfo(name, FIXED_ZIP_TIMESTAMP)
                info.compress_type = zipfile.ZIP_STORED if name == "mimetype" else compression
                info.external_attr = 0o100600 << 16
                archive.writestr(info, data)
        temporary.chmod(0o600)
        os.replace(temporary, output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    analysis = analyze_package(output)
    manifest_by_id = {item["id"]: item for item in analysis.manifest_items if "id" in item}
    expected_section_ids = tuple(f"section{i}" for i in range(len(items)))
    owned_manifest_ids = (header_manifest_id, *expected_section_ids)
    owned_manifest_paths = (
        "Contents/header.xml",
        *(f"Contents/section{i}.xml" for i in range(len(items))),
    )
    manifest_is_hancom_compatible = (
        len(manifest_by_id) == len(analysis.manifest_items)
        and analysis.spine == owned_manifest_ids
        and all(
            manifest_by_id.get(identifier, {}).get("href") == path
            and manifest_by_id.get(identifier, {}).get("part") == path
            for identifier, path in zip(owned_manifest_ids, owned_manifest_paths, strict=True)
        )
        and all(
            item.get("href") == item.get("part")
            for item in analysis.manifest_items
            if item.get("part", "").startswith("BinData/")
        )
    )
    if (
        analysis.mimetype != "application/hwp+zip"
        or analysis.active_content
        or analysis.external_links
        or analysis.sections != tuple(f"Contents/section{i}.xml" for i in range(len(items)))
        or not manifest_is_hancom_compatible
    ):
        raise HwpxError(
            HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED,
            "assembled exam package failed structural validation",
        )
    return {
        "status": "PASS",
        "section_count": len(analysis.sections),
        "binary_count": len(analysis.bindata),
        "items": item_reports,
        "entries": [entry.model_dump(mode="json") for entry in analysis.entries],
        "warnings": list(analysis.warnings),
    }


def _as_item_image(value: ContentTeamExamImageSource) -> ContentTeamImageSource:
    return ContentTeamImageSource(
        visual_ordinal=value.visual_ordinal,
        label=value.label,
        artifact_id=value.artifact_id,
        artifact_revision_id=value.artifact_revision_id,
        artifact_member=value.artifact_member,
        sha256=value.sha256,
        schema_ref=value.schema_ref,
        media_type=value.media_type,
        width_px=value.width_px,
        height_px=value.height_px,
        alt_text=value.alt_text,
        file_name=f"input/visual-{value.visual_ordinal}.png",
    )


def render_content_team_exam_workspace(
    request_path: Path, result_path: Path
) -> ContentTeamExamBuildResultContract:
    started = datetime.now(UTC)
    workspace = request_path.parent.resolve(strict=True)
    if result_path.resolve(strict=False).parent != workspace or result_path.name != "result.json":
        raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSAFE, "result path escaped workspace")
    try:
        request_bytes = _read_request(request_path)
        request_raw: object = json.loads(request_bytes.decode("utf-8"))
        if not isinstance(request_raw, dict):
            raise ValueError("request is not an object")
        request = _load_exam_request(request_raw)
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise HwpxError(
            HwpxErrorCode.HWPX_REFERENCE_UNSAFE,
            "exam render request is invalid",
        ) from exc

    handoff_archive = _workspace_path(workspace, request.handoff.archive_file)
    _read_regular(
        handoff_archive,
        max_bytes=MAX_HANDOFF_BYTES,
        expected_sha256=request.handoff.archive_sha256,
    )
    evidence = inspect_content_team_handoff(handoff_archive)
    if (
        evidence.entry_count != request.handoff.entry_count
        or evidence.uncompressed_bytes != request.handoff.uncompressed_bytes
        or tuple((row.purpose, row.sha256, row.size) for row in evidence.members)
        != tuple((row.purpose, row.sha256, row.size) for row in request.handoff.members)
        or {row.purpose: row.sha256 for row in evidence.members} != dict(EXPECTED_MEMBER_HASHES)
    ):
        raise HwpxError(
            HwpxErrorCode.HWPX_TEMPLATE_HASH_MISMATCH,
            "content-team handoff evidence differs from the exam request",
        )
    runtime = _workspace_path(workspace, "runtime", must_exist=False)
    template = _extract_runtime(handoff_archive, evidence, runtime)
    item_output_root = _workspace_path(workspace, "item-output", must_exist=False)
    item_output_root.mkdir(mode=0o700)
    item_outputs: list[Path] = []
    total_equations = 0
    total_tables = 0
    total_visuals = 0
    item_reports: list[dict[str, Any]] = []
    for item in request.items:
        json_bytes = _read_regular(
            _workspace_path(workspace, item.json_file),
            max_bytes=MAX_JSON_BYTES,
            expected_sha256=item.source_json_sha256,
        )
        markdown_bytes = _read_regular(
            _workspace_path(workspace, item.markdown_file),
            max_bytes=MAX_MARKDOWN_BYTES,
            expected_sha256=item.source_markdown_sha256,
        )
        source_schema_ref = (
            item.source_schema_ref
            if isinstance(item, ContentTeamExamItemSourceV3)
            else "eom.assessment.item-content/2.0"
        )
        draft = _load_draft(json_bytes, source_schema_ref=source_schema_ref)
        if serialize_content_team_markdown(draft) != markdown_bytes:
            raise HwpxError(
                HwpxErrorCode.HWPX_TEMPLATE_HASH_MISMATCH,
                "exam item JSON and Markdown differ",
            )
        parsed = (
            parse_content_team_markdown_v2(markdown_bytes)
            if isinstance(item, ContentTeamExamItemSourceV3)
            else parse_content_team_markdown(markdown_bytes)
        )
        if parsed.source_sha256 != item.source_markdown_sha256:
            raise HwpxError(
                HwpxErrorCode.HWPX_TEMPLATE_HASH_MISMATCH,
                "exam item Markdown identity differs",
            )
        rendered_score_display: str = draft.score_display
        if isinstance(item, ContentTeamExamItemSourceV3):
            if draft.score_display != _PLANNED_SCORE_DISPLAY[item.points_milli]:
                raise HwpxError(
                    HwpxErrorCode.HWPX_SEMANTIC_MISMATCH,
                    "V3 exam item source score differs from its exact placement score",
                )
        elif isinstance(item, ContentTeamExamItemSourceV2):
            rendered_score_display = _PLANNED_SCORE_DISPLAY[item.points_milli]
        output = item_output_root / f"item-{item.position:03d}.hwpx"
        report = _external_render(
            runtime,
            template,
            markdown_bytes,
            output,
            draft,
            item_number_override=item.position,
            score_display_override=rendered_score_display,
        )
        expected_slots = tuple(
            (ordinal, visual.label)
            for ordinal, visual in enumerate(draft.visuals)
            if visual.kind == "IMAGE"
        )
        actual_slots = tuple((image.visual_ordinal, image.label) for image in item.images)
        if actual_slots != expected_slots:
            raise HwpxError(
                HwpxErrorCode.HWPX_IMAGE_BINDING_FAILED,
                "exam item image pointers differ from its editorial visual slots",
            )
        images = tuple(
            (
                _as_item_image(image),
                _read_regular(
                    _workspace_path(workspace, image.file_name),
                    max_bytes=MAX_IMAGE_BYTES,
                    expected_sha256=image.sha256,
                ),
            )
            for image in item.images
        )
        inject_content_team_images(output, images)
        item_outputs.append(output)
        total_equations += int(report["equation_count"])
        total_tables += int(report["table_count"])
        total_visuals += int(report["visual_count"])
        item_report: dict[str, Any] = {
            "position": item.position,
            "placement_id": item.placement_id,
            "item_id": item.item_id,
            "item_revision_id": item.item_revision_id,
            "item_manifest_sha256": item.item_manifest_sha256,
            "source_artifact_revision_id": item.source_artifact_revision_id,
            "source_json_sha256": item.source_json_sha256,
            "source_markdown_sha256": item.source_markdown_sha256,
            "source_item_number": draft.item_number,
            "rendered_item_number": int(report["rendered_item_number"]),
            "equation_count": int(report["equation_count"]),
            "table_count": int(report["table_count"]),
            "visual_count": int(report["visual_count"]),
        }
        if isinstance(item, ContentTeamExamItemSourceV2):
            item_report.update(
                display_number=item.display_number,
                points_milli=item.points_milli,
                source_score_display=draft.score_display,
                rendered_score_display=str(report["rendered_score_display"]),
            )
        item_reports.append(item_report)

    output = _workspace_path(workspace, "output/content-team-exam.hwpx", must_exist=False)
    merge_report = _merge_item_packages(tuple(item_outputs), output)
    item_set_sha256 = _item_set_sha256(request)
    render_plan_sha256 = (
        _render_plan_sha256(request)
        if isinstance(request, ContentTeamExamRenderRequestV2 | ContentTeamExamRenderRequestV3)
        else None
    )
    renderer_version = (
        EXAM_RENDERER_VERSION_V3
        if isinstance(request, ContentTeamExamRenderRequestV3)
        else (
            EXAM_RENDERER_VERSION_V2
            if isinstance(request, ContentTeamExamRenderRequestV2)
            else EXAM_RENDERER_VERSION
        )
    )
    report = {
        "status": "PASS",
        "renderer_profile": request.renderer_profile,
        "renderer_version": renderer_version,
        "assessment_assembly_revision_id": request.assembly.assessment_assembly_revision_id,
        "assembly_manifest_sha256": request.assembly.manifest_sha256,
        "item_set_sha256": item_set_sha256,
        "item_count": len(request.items),
        "equation_count": total_equations,
        "table_count": total_tables,
        "visual_count": total_visuals,
        "items": item_reports,
        "package": merge_report,
    }
    if render_plan_sha256 is not None:
        report["render_plan_sha256"] = render_plan_sha256
    output_dir = output.parent
    write_private_json(output_dir / "content-team-exam-validation.json", report)
    package_manifest: dict[str, Any] = {
        "manifest_version": (
            "content-team-exam-hwpx/3.0"
            if isinstance(request, ContentTeamExamRenderRequestV3)
            else (
                "content-team-exam-hwpx/2.0"
                if isinstance(request, ContentTeamExamRenderRequestV2)
                else "content-team-exam-hwpx/1.0"
            )
        ),
        "renderer_profile": request.renderer_profile,
        "renderer_version": renderer_version,
        "assembly": request.assembly.model_dump(mode="json"),
        "handoff": request.handoff.model_dump(mode="json"),
        "item_set_sha256": item_set_sha256,
        "file_name": output.name,
        "media_type": "application/hwp+zip",
        "package_sha256": sha256_file(output),
        "renderer_report": report,
    }
    if render_plan_sha256 is not None:
        package_manifest["render_plan_sha256"] = render_plan_sha256
    write_private_json(output_dir / "package-manifest.json", package_manifest)
    prepare_private_handoff_file(output)
    result_values: dict[str, Any] = {
        "build_id": request.build_id,
        "assessment_assembly_revision_id": request.assembly.assessment_assembly_revision_id,
        "assembly_manifest_sha256": request.assembly.manifest_sha256,
        "item_set_sha256": item_set_sha256,
        "handoff_archive_sha256": request.handoff.archive_sha256,
        "status": "SUCCEEDED",
        "output_file": "output/content-team-exam.hwpx",
        "output_sha256": sha256_file(output),
        "package_manifest_file": "output/package-manifest.json",
        "renderer_report_file": "output/content-team-exam-validation.json",
        "item_count": len(request.items),
        "section_count": int(merge_report["section_count"]),
        "equation_count": total_equations,
        "table_count": total_tables,
        "visual_count": total_visuals,
        "warnings": (),
        "errors": (),
        "started_at": started,
        "completed_at": datetime.now(UTC),
    }
    result: ContentTeamExamBuildResultContract
    if isinstance(request, ContentTeamExamRenderRequestV3):
        assert render_plan_sha256 is not None
        result = ContentTeamExamBuildResultV3(
            **result_values,
            render_plan_sha256=render_plan_sha256,
        )
        result_contract = "content-team-exam-build-result-v3"
    elif isinstance(request, ContentTeamExamRenderRequestV2):
        assert render_plan_sha256 is not None
        result = ContentTeamExamBuildResultV2(
            **result_values,
            render_plan_sha256=render_plan_sha256,
        )
        result_contract = "content-team-exam-build-result-v2"
    else:
        result = ContentTeamExamBuildResult(**result_values)
        result_contract = "content-team-exam-build-result"
    validate_contract(result_contract, result.model_dump(mode="json"))
    write_private_json(result_path, result.model_dump(mode="json"))
    finalize_success_handoff(
        workspace,
        result_path,
        output_file_names=(
            "content-team-exam.hwpx",
            "content-team-exam-validation.json",
            "package-manifest.json",
        ),
    )
    return result


def failed_content_team_exam_result(
    request_path: Path, result_path: Path, started: datetime, error: Exception
) -> ContentTeamExamBuildResultContract | None:
    try:
        raw: object = json.loads(_read_request(request_path).decode("utf-8"))
        if not isinstance(raw, dict):
            return None
        request = _load_exam_request(raw)
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError, ValueError):
        return None
    code = (
        error.code.value if isinstance(error, HwpxError) else "HWPX_CONTENT_TEAM_EXAM_RENDER_FAILED"
    )
    result_values: dict[str, Any] = {
        "build_id": request.build_id,
        "assessment_assembly_revision_id": request.assembly.assessment_assembly_revision_id,
        "assembly_manifest_sha256": request.assembly.manifest_sha256,
        "item_set_sha256": _item_set_sha256(request),
        "handoff_archive_sha256": request.handoff.archive_sha256,
        "status": "FAILED",
        "output_file": None,
        "output_sha256": None,
        "package_manifest_file": None,
        "renderer_report_file": None,
        "item_count": 0,
        "section_count": 0,
        "equation_count": 0,
        "table_count": 0,
        "visual_count": 0,
        "warnings": (),
        "errors": (code,),
        "started_at": started,
        "completed_at": datetime.now(UTC),
    }
    result: ContentTeamExamBuildResultContract
    if isinstance(request, ContentTeamExamRenderRequestV3):
        result = ContentTeamExamBuildResultV3(
            **result_values,
            render_plan_sha256=_render_plan_sha256(request),
        )
        result_contract = "content-team-exam-build-result-v3"
    elif isinstance(request, ContentTeamExamRenderRequestV2):
        result = ContentTeamExamBuildResultV2(
            **result_values,
            render_plan_sha256=_render_plan_sha256(request),
        )
        result_contract = "content-team-exam-build-result-v2"
    else:
        result = ContentTeamExamBuildResult(**result_values)
        result_contract = "content-team-exam-build-result"
    validate_contract(result_contract, result.model_dump(mode="json"))
    write_private_json(result_path, result.model_dump(mode="json"))
    finalize_failure_result(request_path.parent.resolve(strict=True), result_path)
    return result
