"""Independent Manager acceptance of ordered native publication and resource relocation.

The Builder's ID allocator is deliberately not imported. Correspondences come
from the observed ordered resource rows and section trees, then every value is
compared. Only declared identity relocation and style-name collision repair may
differ. Runtime is linear in bounded package bytes and XML nodes.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import NoReturn
from xml.etree import ElementTree as ET

from eom_hwpx_contracts.curated_mixed import (
    CuratedMixedRenderResult,
    CuratedNativeSegment,
)
from eom_hwpx_contracts.curated_occurrences import CuratedOccurrenceRenderRequest
from eom_hwpx_contracts.native_item_semantics import (
    expected_native_item_events,
    native_item_section_events,
)
from eom_hwpx_contracts.native_resource_rules import (
    CATALOGS,
    FONT_LANGUAGES,
    OBJECTS,
    REFERENCES,
    ZERO_SENTINELS,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes

from eom_hwpx_manager.content_team_output_acceptance import (
    CURATED_PUBLICATION_LIMITS,
    PublicationPackageSnapshot,
    PublicationProfile,
    read_publication_package,
    validate_publication_package,
    verify_content_team_output,
)
from eom_hwpx_manager.curated_materialization import CuratedMaterialization
from eom_hwpx_manager.errors import HwpxManagerError, HwpxManagerErrorCode


def _fail(message: str) -> NoReturn:
    raise HwpxManagerError(HwpxManagerErrorCode.HWPX_RESULT_INVALID, message)


def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def _attr(node: ET.Element, name: str) -> str:
    return next((value for key, value in node.attrib.items() if _local(key) == name), "")


def _header_options(header: ET.Element) -> tuple[object, ...]:
    attributes = dict(header.attrib)
    attributes.pop("secCnt", None)
    if "version" in attributes:
        if attributes["version"] not in {"1.4", "1.5"}:
            _fail("curated header version differs from the supported native profile")
        attributes["version"] = "1.5"
    children = tuple(
        node
        for node in header
        if not (
            _local(node.tag) == "refList"
            or (
                _local(node.tag) == "trackchageConfig"
                and node.attrib == {"flags": "56"}
                and not len(node)
                and not (node.text or "").strip()
            )
        )
    )

    def value(node: ET.Element) -> tuple[object, ...]:
        return (
            node.tag,
            tuple(sorted(node.attrib.items())),
            node.text or "",
            node.tail or "",
            tuple(value(child) for child in node),
        )

    return (
        header.tag,
        tuple(sorted(attributes.items())),
        header.text or "",
        header.tail or "",
        tuple(value(child) for child in children),
    )


def _catalogs(header: ET.Element) -> dict[str, tuple[ET.Element, ...]]:
    lists = tuple(node for node in header if _local(node.tag) == "refList")
    if len(lists) != 1:
        _fail("curated header resource list is missing or repeated")
    result: dict[str, tuple[ET.Element, ...]] = {}
    for node in lists[0]:
        name = _local(node.tag)
        entries = (
            tuple(("font:" + _attr(face, "lang"), face) for face in node)
            if name == "fontfaces"
            else ((name, node),)
        )
        for key, catalog in entries:
            if key not in CATALOGS and key not in {"font:" + x for x in FONT_LANGUAGES.values()}:
                if len(catalog):
                    _fail("curated header has an unsupported resource catalog")
                continue
            rows = tuple(catalog)
            ids = tuple(_attr(row, "id") for row in rows)
            if key in result or len(set(ids)) != len(ids) or any(not x.isdecimal() for x in ids):
                _fail("curated resource identities are missing or repeated")
            result[key] = rows
    return result


@dataclass(frozen=True)
class _Document:
    package: PublicationPackageSnapshot
    roots: dict[str, ET.Element]
    sections: tuple[str, ...]
    binaries: tuple[tuple[str, str, str], ...]
    catalogs: dict[str, tuple[ET.Element, ...]]


def _document(path: Path, sha256: str, *, aggregate_xml_bytes: int = 10 * 1024**2) -> _Document:
    limits = replace(
        CURATED_PUBLICATION_LIMITS,
        max_member_bytes=max(CURATED_PUBLICATION_LIMITS.max_member_bytes, aggregate_xml_bytes),
    )
    package = read_publication_package(path, sha256, limits=limits)
    roots, sections, manifest = validate_publication_package(
        package,
        profile=PublicationProfile.NATIVE,
        max_xml_bytes=aggregate_xml_bytes,
    )
    if not sections or set(sections) != {
        name for name in roots if re.fullmatch(r"Contents/section[0-9]+\.xml", name)
    }:
        _fail("curated package has missing or unordered sections")
    binaries = []
    for row in roots["Contents/content.hpf"].iter():
        if _local(row.tag) != "item":
            continue
        identity = _attr(row, "id")
        target = manifest[identity]
        if target.startswith("BinData/"):
            media = _attr(row, "media-type")
            if not media.startswith(("image/", "font/", "application/x-font")):
                _fail("curated embedded member media type is unsupported")
            binaries.append((identity, target, media))
    if {member for _, member, _ in binaries} != {
        name for name in package.names if name.startswith("BinData/") and not name.endswith("/")
    }:
        _fail("curated package has unlisted binary members")
    return _Document(
        package, roots, sections, tuple(binaries), _catalogs(roots["Contents/header.xml"])
    )


def _compare(
    source: ET.Element,
    target: ET.Element,
    *,
    resources: dict[str, dict[str, str]],
    binaries: dict[str, str],
    objects: dict[str, str],
    position: int,
    row_id: str | None = None,
) -> None:
    pairs = [(source, target, row_id)]
    while pairs:
        left, right, own_id = pairs.pop()
        if (left.tag, left.text or "", left.tail or "", len(left)) != (
            right.tag,
            right.text or "",
            right.tail or "",
            len(right),
        ):
            _fail("curated text, equation, element order or geometry differs from its source")
        values = dict(left.attrib)
        tag = _local(left.tag)
        object_id = _attr(right, "id") if tag in OBJECTS and _attr(left, "id") else ""
        for key, value in tuple(values.items()):
            name = _local(key).casefold()
            catalog = REFERENCES.get(name)
            if tag == "fontRef" and name in FONT_LANGUAGES:
                catalog = "font:" + FONT_LANGUAGES[name]
            elif tag == "heading" and name == "idref":
                catalog = {"NUMBER": "numberings", "BULLET": "bullets"}.get(_attr(left, "type"))
            if catalog:
                if tag == "paraHead" and name == "charpridref" and value == "4294967295":
                    continue
                mapped = resources.get(catalog, {}).get(value)
                if mapped is None and value == "0" and catalog in ZERO_SENTINELS:
                    continue
                if mapped is None:
                    _fail("curated resource reference is dangling")
                values[key] = mapped
            elif name == "binaryitemidref" and value:
                if value not in binaries:
                    _fail("curated binary reference is dangling")
                values[key] = binaries[value]
            elif name == "beginidref":
                if value not in objects:
                    _fail("curated field reference is dangling")
                values[key] = objects[value]
            elif object_id and name in {"id", "instid", "fieldid"}:
                values[key] = object_id
            elif own_id is not None and name == "id":
                values[key] = own_id
            elif tag == "style" and name in {"name", "engname"} and value != right.get(key):
                # Only the documented collision namespace may change a style's name.
                if not re.fullmatch(
                    rf"EOM-{position:03d}-{re.escape(_attr(right, 'id'))}-*", right.get(key, "")
                ):
                    _fail("curated style name changed outside collision repair")
                values[key] = right.attrib[key]
        if values != right.attrib:
            _fail("curated native formatting or reference differs from its source")
        pairs.extend((a, b, None) for a, b in zip(left, right, strict=True))


@dataclass(frozen=True)
class CuratedOutputAcceptance:
    sha256: str
    size_bytes: int
    section_count: int
    binary_count: int
    table_count: int
    equation_count: int


def verify_curated_output(
    workspace: Path,
    materialization: CuratedMaterialization,
    result: CuratedMixedRenderResult,
) -> CuratedOutputAcceptance:
    request = materialization.request
    source_hashes = tuple(
        row.sha256 if isinstance(row, CuratedNativeSegment) else row.source_sha256
        for row in request.segments
    )
    if (
        result.status != "SUCCEEDED"
        or result.profile != request.profile
        or result.build_id != request.build_id
        or result.assembly_revision_id != request.assembly_revision_id
        or result.assembly_manifest_sha256 != request.assembly_manifest_sha256
        or result.input_plan_sha256 != request.input_plan_sha256
        or result.request_sha256
        != sha256_bytes(canonical_json_bytes(request.model_dump(mode="json")))
        or result.source_sha256 != source_hashes
        or result.converter_bundle_sha256
        != (request.converter.bundle_sha256 if request.converter else None)
    ):
        _fail("curated Builder result differs from its pinned request")
    assert result.output_sha256 is not None
    final_path = workspace / "output/assembled.hwpx"
    final = _document(
        final_path,
        result.output_sha256,
        aggregate_xml_bytes=256 * 1024**2
        if isinstance(request, CuratedOccurrenceRenderRequest)
        else 10 * 1024**2,
    )
    if final.sections != tuple(f"Contents/section{i}.xml" for i in range(len(final.sections))):
        _fail("curated final section order is not contiguous")
    offsets: Counter[str] = Counter()
    section_offset = binary_offset = 0
    positions: list[int] = []
    seen_objects: set[str] = set()
    canonical = {item.item_number: item for item in materialization.canonical_items}
    editorial = {item.position: item for item in materialization.editorial_items}
    # Resource relocation enlarges the final header with every occurrence. Its
    # non-resource options are immutable, so inspecting them once avoids quadratic work.
    final_options = _header_options(final.roots["Contents/header.xml"])
    # Hash each immutable embedded member once, not once per canonical Item.
    binary_hashes = (
        {
            identity: sha256_bytes(final.package.members[name])
            for identity, name, _media in final.binaries
        }
        if canonical
        else {}
    )
    for segment, segment_sha in zip(request.segments, result.segment_sha256, strict=True):
        position = segment.position
        path = (
            workspace / segment.local_file
            if isinstance(segment, CuratedNativeSegment) and segment.source_format == "HWPX"
            else workspace / f"output/segment-{position:03d}.hwpx"
        )
        if (
            isinstance(segment, CuratedNativeSegment)
            and segment.source_format == "HWPX"
            and segment.sha256 != segment_sha
        ):
            _fail("curated native HWPX source hash changed")
        source = _document(path, segment_sha)
        if _header_options(source.roots["Contents/header.xml"]) != final_options:
            _fail("curated document options changed outside resource relocation")
        rows: dict[str, dict[str, str]] = {}
        targets: dict[str, tuple[ET.Element, ...]] = {}
        for name, definitions in source.catalogs.items():
            end = offsets[name] + len(definitions)
            targets[name] = final.catalogs.get(name, ())[offsets[name] : end]
            if len(targets[name]) != len(definitions):
                _fail("curated resource definitions were lost")
            rows[name] = {
                _attr(a, "id"): _attr(b, "id")
                for a, b in zip(definitions, targets[name], strict=True)
            }
            offsets[name] = end
        actual_binaries = final.binaries[binary_offset : binary_offset + len(source.binaries)]
        if len(actual_binaries) != len(source.binaries):
            _fail("curated embedded images were lost")
        binaries = {}
        for (identity, name, media), (new_id, new_name, new_media) in zip(
            source.binaries, actual_binaries, strict=True
        ):
            if (
                media != new_media
                or source.package.members[name] != final.package.members[new_name]
            ):
                _fail("curated embedded image or font bytes changed")
            binaries[identity] = new_id
        binary_offset += len(source.binaries)
        actual_sections = final.sections[section_offset : section_offset + len(source.sections)]
        if len(actual_sections) != len(source.sections):
            _fail("curated native sections were lost")
        objects = {}
        for name, new_name in zip(source.sections, actual_sections, strict=True):
            left = [
                node
                for node in source.roots[name].iter()
                if _local(node.tag) in OBJECTS and _attr(node, "id")
            ]
            right = [
                node
                for node in final.roots[new_name].iter()
                if _local(node.tag) in OBJECTS and _attr(node, "id")
            ]
            if len(left) != len(right):
                _fail("curated native object count changed")
            for a, b in zip(left, right, strict=True):
                old_id, new_id = _attr(a, "id"), _attr(b, "id")
                if not new_id.isdecimal() or new_id in seen_objects:
                    _fail("curated final object identity is missing or repeated")
                seen_objects.add(new_id)
                if old_id != "0" or _local(a.tag) == "fieldBegin":
                    if old_id in objects:
                        _fail("curated source object identity is repeated")
                    objects[old_id] = new_id
        for name, definitions in source.catalogs.items():
            for a, b in zip(definitions, targets[name], strict=True):
                _compare(
                    a,
                    b,
                    resources=rows,
                    binaries=binaries,
                    objects=objects,
                    position=position,
                    row_id=_attr(b, "id"),
                )
        for name, new_name in zip(source.sections, actual_sections, strict=True):
            _compare(
                source.roots[name],
                final.roots[new_name],
                resources=rows,
                binaries=binaries,
                objects=objects,
                position=position,
            )
        if position in canonical:
            if len(actual_sections) != 1:
                _fail("curated canonical Item must occupy one section")
            if native_item_section_events(
                final.package.members[actual_sections[0]], binary_hashes
            ) != expected_native_item_events(canonical[position]):
                _fail("curated canonical content differs from the approved Item")
        if position in editorial:
            verify_content_team_output(
                path,
                expected_sha256=segment_sha,
                expectations=(replace(editorial[position], position=1),),
            )
        positions.extend([position] * len(source.sections))
        section_offset += len(source.sections)
    counts = Counter(
        _local(node.tag) for name in final.sections for node in final.roots[name].iter()
    )
    size = final_path.stat().st_size
    if (
        tuple(positions) != result.section_source_positions
        or section_offset != len(final.sections)
        or binary_offset != len(final.binaries)
        or any(offsets[name] != len(definitions) for name, definitions in final.catalogs.items())
        or result.binary_count != binary_offset
        or result.native_equation_count != counts["equation"]
        or result.native_table_count != counts["tbl"]
        or result.output_size_bytes != size
    ):
        _fail("curated preservation report counts differ from the actual package")
    return CuratedOutputAcceptance(
        result.output_sha256, size, section_offset, binary_offset, counts["tbl"], counts["equation"]
    )
