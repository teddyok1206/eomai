"""Deterministic, namespace-aware HWPX package analysis."""

from __future__ import annotations

import posixpath
import re
from pathlib import Path, PurePosixPath
from typing import Any, cast
from urllib.parse import urlparse

from lxml import etree  # type: ignore[import-untyped]

from eom_hwpx_builder.archive import SafePackage, read_package
from eom_hwpx_builder.errors import HwpxError, HwpxErrorCode
from eom_hwpx_builder.models import PackageAnalysis, PackageLimits
from eom_hwpx_builder.xmlsafe import local_name, namespace_uri, parse_xml

MIMETYPE = "application/hwp+zip"
MARKER_PATTERN = re.compile(r"\{\{EOM_[A-Z0-9_]+\}\}|EOM_EQ_PLACEHOLDER")
CORE_PARTS = {
    "mimetype",
    "version.xml",
    "settings.xml",
    "Contents/content.hpf",
    "Contents/header.xml",
    "META-INF/container.xml",
}
ACTIVE_EXTENSIONS = {
    ".exe",
    ".dll",
    ".com",
    ".bat",
    ".cmd",
    ".ps1",
    ".vbs",
    ".js",
    ".jar",
    ".zip",
    ".hwp",
    ".hwpx",
    ".docx",
    ".ole",
}


def _resolve_part(base_part: str, href: str) -> str:
    parent = PurePosixPath(base_part).parent.as_posix()
    value = posixpath.normpath(posixpath.join(parent, href))
    if value.startswith("../") or value == ".." or value.startswith("/"):
        raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_BROKEN, "package reference escaped root")
    return value


def _attribute(element: etree._Element, requested: str) -> str | None:
    for name, value in element.attrib.items():
        if local_name(name).lower() == requested.lower():
            return cast(str, value)
    return None


def _xml_parts(package: SafePackage, limits: PackageLimits) -> dict[str, etree._Element]:
    parsed: dict[str, etree._Element] = {}
    for entry in package.entries:
        name = entry.info.filename
        if name.lower().endswith((".xml", ".hpf")):
            parsed[name] = parse_xml(entry.data, name, limits).root
    return parsed


def _manifest(
    root: etree._Element, part_name: str
) -> tuple[list[dict[str, str]], list[str], list[str], list[dict[str, str]]]:
    items: list[dict[str, str]] = []
    by_id: dict[str, str] = {}
    references: list[dict[str, str]] = []
    for element in root.iter():
        if local_name(element.tag).lower() != "item":
            continue
        identifier = _attribute(element, "id")
        href = _attribute(element, "href")
        media_type = _attribute(element, "media-type") or _attribute(element, "mediatype")
        if not identifier or not href:
            continue
        resolved = _resolve_part(part_name, href)
        item = {"id": identifier, "href": href, "part": resolved}
        if media_type:
            item["media_type"] = media_type
        items.append(item)
        by_id[identifier] = resolved
        references.append({"part": part_name, "attribute": "href", "target": resolved})
    spine: list[str] = []
    sections: list[str] = []
    for element in root.iter():
        if local_name(element.tag).lower() != "itemref":
            continue
        identifier = _attribute(element, "idref")
        if identifier:
            spine.append(identifier)
            if identifier in by_id:
                sections.append(by_id[identifier])
    return items, spine, sections, references


def _rootfile(root: etree._Element) -> str | None:
    for element in root.iter():
        if local_name(element.tag).lower() == "rootfile":
            return _attribute(element, "full-path") or _attribute(element, "fullpath")
    return None


def _is_external(value: str) -> bool:
    parsed = urlparse(value)
    return bool(parsed.scheme and parsed.scheme.lower() not in {"file"}) or value.startswith("//")


def analyze_package(path: Path, limits: PackageLimits | None = None) -> PackageAnalysis:
    actual_limits = limits or PackageLimits()
    package = read_package(path, actual_limits)
    entries = package.by_name()
    xml_parts = _xml_parts(package, actual_limits)
    namespaces = sorted(
        {
            uri
            for root in xml_parts.values()
            for element in root.iter()
            for uri in ([namespace_uri(element.tag)] + [value for value in element.nsmap.values()])
            if uri
        }
    )
    mimetype_entry = entries.get("mimetype")
    mimetype = (
        mimetype_entry.data.decode("ascii", errors="replace")
        if mimetype_entry is not None
        else None
    )
    version_info: dict[str, str] = {}
    root = xml_parts.get("version.xml")
    if root is not None:
        version_info = {local_name(key): value for key, value in sorted(root.attrib.items())}
        version_info["root_namespace"] = namespace_uri(root.tag)
        version_info["root_local_name"] = local_name(root.tag)

    content_part = "Contents/content.hpf"
    manifest_items: list[dict[str, str]] = []
    spine: list[str] = []
    sections: list[str] = []
    references: list[dict[str, str]] = []
    content_root = xml_parts.get(content_part)
    if content_root is not None:
        manifest_items, spine, sections, references = _manifest(content_root, content_part)
    container_rootfile = None
    container = xml_parts.get("META-INF/container.xml")
    if container is not None:
        container_rootfile = _rootfile(container)
        if container_rootfile:
            references.append(
                {
                    "part": "META-INF/container.xml",
                    "attribute": "full-path",
                    "target": container_rootfile,
                }
            )

    marker_locations: list[dict[str, Any]] = []
    equation_candidates: list[dict[str, str]] = []
    active: set[str] = set()
    external: set[str] = set()
    for part_name, root in sorted(xml_parts.items()):
        paragraphs = [element for element in root.iter() if local_name(element.tag) == "p"]
        if not paragraphs:
            paragraphs = [root]
        for paragraph_index, paragraph in enumerate(paragraphs):
            logical_text = "".join(
                element.text or "" for element in paragraph.iter() if local_name(element.tag) == "t"
            )
            for marker in MARKER_PATTERN.findall(logical_text):
                marker_locations.append(
                    {
                        "marker": marker,
                        "part": part_name,
                        "element_local_name": "p",
                        "element_index": paragraph_index,
                        "location": "logical_text",
                    }
                )
        for element_index, element in enumerate(root.iter()):
            lname = local_name(element.tag)
            lower_name = lname.casefold()
            if "script" in lower_name or "macro" in lower_name or lower_name == "ole":
                active.add(f"xml:{part_name}:{lname}")
            if "encrypt" in lower_name:
                active.add(f"encryption:{part_name}:{lname}")
            if "equation" in lower_name or lower_name in {"eq", "equationobject"}:
                candidate = {"part": part_name, "element_local_name": lname}
                object_id = _attribute(element, "id")
                if object_id:
                    candidate["object_id"] = object_id
                equation_candidates.append(candidate)
            for attribute_name, value in element.attrib.items():
                attribute_local = local_name(attribute_name)
                for marker in MARKER_PATTERN.findall(value):
                    marker_locations.append(
                        {
                            "marker": marker,
                            "part": part_name,
                            "element_local_name": lname,
                            "element_index": element_index,
                            "location": "attribute",
                            "attribute_local_name": attribute_local,
                        }
                    )
                if attribute_local.casefold() in {"href", "src", "target", "url"}:
                    if _is_external(value):
                        external.add(f"{part_name}:{attribute_local}")
                    elif value and not value.startswith("#"):
                        try:
                            target = _resolve_part(part_name, value)
                        except HwpxError:
                            target = value
                        references.append(
                            {"part": part_name, "attribute": attribute_local, "target": target}
                        )

    for entry in package.entries:
        name = entry.info.filename
        lower = name.casefold()
        suffix = PurePosixPath(lower).suffix
        if lower.startswith("scripts/") or suffix in ACTIVE_EXTENSIONS:
            active.add(f"entry:{name}")
        if lower.startswith(("_xmlsignatures/", "meta-inf/signatures")):
            active.add(f"signature:{name}")
        if entry.data.startswith(b"PK\x03\x04") and name != path.name:
            active.add(f"embedded-package:{name}")

    image_candidates = [
        item
        for item in manifest_items
        if item.get("media_type", "").startswith("image/")
        or item["part"].casefold().endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp"))
    ]
    bindata = sorted(
        name
        for name in entries
        if name.casefold().startswith("bindata/") and not name.endswith("/")
    )
    known = CORE_PARTS | set(sections) | {item["part"] for item in manifest_items}
    unknown_parts = sorted(
        name
        for name in entries
        if name not in known
        and not name.startswith(("Preview/", "BinData/", "META-INF/"))
        and not name.endswith("/")
    )
    warnings = []
    if any(name.startswith("Preview/") and not name.endswith("/") for name in entries):
        warnings.append("PREVIEW_IMAGE_STALE")
    if container_rootfile and container_rootfile != content_part:
        warnings.append("CONTAINER_ROOTFILE_PROFILE_DIFFERS")
    return PackageAnalysis(
        package_sha256=package.package_sha256,
        entries=package.records(),
        namespaces=tuple(namespaces),
        mimetype=mimetype,
        version_info=version_info,
        manifest_items=tuple(manifest_items),
        spine=tuple(spine),
        sections=tuple(sections),
        bindata=tuple(bindata),
        internal_references=tuple(
            sorted(
                references, key=lambda value: (value["part"], value["attribute"], value["target"])
            )
        ),
        marker_locations=tuple(
            sorted(
                marker_locations,
                key=lambda value: (
                    value["marker"],
                    value["part"],
                    value["element_index"],
                    value["location"],
                ),
            )
        ),
        image_candidates=tuple(image_candidates),
        equation_candidates=tuple(equation_candidates),
        active_content=tuple(sorted(active)),
        external_links=tuple(sorted(external)),
        unknown_parts=tuple(unknown_parts),
        warnings=tuple(warnings),
    )
