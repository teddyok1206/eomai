"""Source-preserving native HWPX merge; never rasterizes or round-trips source XML."""

from __future__ import annotations

import copy
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from eom_hwpx_contracts.curated_document import CuratedHwpxWarning
from lxml import etree  # type: ignore[import-untyped]

from eom_hwpx_builder.analyzer import analyze_package, resolve_part
from eom_hwpx_builder.archive import FIXED_ZIP_TIMESTAMP, SafePackage, read_package
from eom_hwpx_builder.curated_resources import (
    OBJECTS,
    NativeMergeProfile,
    ObjectRelocation,
    ResourceRelocation,
    attribute,
    fail,
    merge_resources,
    relocate_tree,
    set_attribute,
    tree_value,
    verify_resource_relocation,
)
from eom_hwpx_builder.errors import HwpxError, HwpxErrorCode
from eom_hwpx_builder.models import PackageLimits
from eom_hwpx_builder.util import sha256_bytes, sha256_file
from eom_hwpx_builder.xmlsafe import local_name, parse_xml

HEADER = "Contents/header.xml"
CONTENT = "Contents/content.hpf"
SECTION = re.compile(r"^Contents/section[0-9]+\.xml$")
GLOBAL_PARTS = frozenset(
    (
        "mimetype",
        "version.xml",
        "settings.xml",
        CONTENT,
        HEADER,
        "META-INF/container.xml",
        "META-INF/container.rdf",
        "META-INF/manifest.xml",
    )
)
MAX_TOTAL_BYTES = 256 * 1024 * 1024
OUTPUT_LIMITS = PackageLimits(
    max_package_bytes=MAX_TOTAL_BYTES, max_entries=10000, max_uncompressed_bytes=MAX_TOTAL_BYTES
)


@dataclass(frozen=True)
class NativeDocument:
    package: SafePackage
    content: etree._Element
    manifest: etree._Element
    spine: etree._Element
    header: etree._Element
    sections: tuple[tuple[str, etree._Element], ...]
    binaries: dict[str, tuple[str, str]]


@dataclass(frozen=True)
class CuratedMergeReport:
    source_sha256: tuple[str, ...]
    section_source_positions: tuple[int, ...]
    binary_count: int
    output_sha256: str
    warnings: tuple[CuratedHwpxWarning, ...] = ()


def _xml(root: etree._Element) -> bytes:
    return cast(
        bytes, etree.tostring(root, encoding="utf-8", xml_declaration=True, standalone=True)
    )


def parse_native_document(package: SafePackage) -> NativeDocument:
    entries = package.by_name()
    for name in entries:
        if name not in GLOBAL_PARTS and not (
            SECTION.fullmatch(name) or name.startswith("BinData/") or name.startswith("Preview/")
        ):
            fail("curated package contains an unsupported part")
    if HEADER not in entries or CONTENT not in entries:
        fail("curated document header/manifest is missing")
    content = parse_xml(entries[CONTENT].data, CONTENT).root
    manifests = [node for node in content.iter() if local_name(node.tag) == "manifest"]
    spines = [node for node in content.iter() if local_name(node.tag) == "spine"]
    if len(manifests) != 1 or len(spines) != 1:
        fail("curated document manifest/spine is invalid")
    manifest, spine = manifests[0], spines[0]
    members: dict[str, str] = {}
    binaries: dict[str, tuple[str, str]] = {}
    for node in manifest:
        identifier, href = attribute(node, "id"), attribute(node, "href")
        if local_name(node.tag) != "item" or not identifier or not href or identifier in members:
            fail("curated manifest identity is missing or duplicated")
        member = resolve_part(CONTENT, href)
        if member not in entries:
            fail("curated manifest target is missing")
        members[identifier] = member
        if member.startswith("BinData/"):
            media = attribute(node, "media-type")
            if not media or not media.startswith(("image/", "font/", "application/x-font")):
                fail("curated embedded media type is not supported")
            binaries[identifier] = (member, media)
    sections = []
    names = set()
    for node in spine:
        target = members.get(attribute(node, "idref") or "")
        if target is None or local_name(node.tag) != "itemref":
            fail("curated spine target is missing")
        if SECTION.fullmatch(target):
            if target in names:
                fail("curated spine repeats a section")
            names.add(target)
            sections.append((target, parse_xml(entries[target].data, target).root))
        elif target != HEADER:
            fail("curated spine contains an unsupported target")
    if not sections:
        fail("curated document has no ordered sections")
    if {name for name in entries if SECTION.fullmatch(name)} != names:
        fail("curated document has unordered sections")
    if {name for name in entries if name.startswith("BinData/") and not name.endswith("/")} != {
        member for member, _media in binaries.values()
    }:
        fail("curated document has unlisted binary members")
    if list(members.values()).count(HEADER) != 1:
        fail("curated manifest must contain exactly one header")
    return NativeDocument(
        package,
        content,
        manifest,
        spine,
        parse_xml(entries[HEADER].data, HEADER).root,
        tuple(sections),
        binaries,
    )


def _settings_identity(
    document: NativeDocument,
    member: str,
    profile: NativeMergeProfile = NativeMergeProfile.STRICT_V1,
) -> tuple[object, ...] | None:
    entry = document.package.by_name().get(member)
    if entry is None:
        return None
    root = parse_xml(entry.data, member).root
    if member == "settings.xml":
        for node in tuple(root):
            if local_name(node.tag) == "CaretPosition":
                root.remove(node)
            elif profile == NativeMergeProfile.EDITABLE_V2 and _default_print_settings(node):
                # A package has one application print setting, not one per section.
                # Only the known neutral settings may be absent in another source.
                root.remove(node)
    else:
        # Producer version is document metadata, not a resource/layout definition.
        for name in ("application", "appVersion"):
            root.attrib.pop(name, None)
        if profile == NativeMergeProfile.EDITABLE_V2 and local_name(root.tag) == "HCFVersion":
            if root.get("xmlVersion") not in {"1.4", "1.5"} or (
                root.get("major"),
                root.get("minor"),
            ) != ("5", "1"):
                fail("curated document format version is unsupported")
            root.attrib.update({"xmlVersion": "1.5", "micro": "1", "buildNumber": "0"})
            # Windows/Mac is producer metadata like appVersion. Font resources,
            # section geometry and actual layout compatibility remain verified.
            root.attrib.pop("os", None)
    return tree_value(root)


def _default_print_settings(root: etree._Element) -> bool:
    config = "{urn:oasis:names:tc:opendocument:xmlns:config:1.0}"
    if root.tag != config + "config-item-set" or dict(root.attrib) != {"name": "PrintInfo"}:
        return False
    defaults = {
        "PrintAutoFootNote": ("boolean", "false"),
        "PrintAutoHeadNote": ("boolean", "false"),
        "PrintMethod": ("short", "0"),
        "OverlapSize": ("short", "0"),
        "PrintCropMark": ("short", "0"),
        "BinderHoleType": ("short", "0"),
        "ZoomX": ("short", "100"),
        "ZoomY": ("short", "100"),
    }
    seen: set[str] = set()
    for child in root:
        name, kind = child.get("name"), child.get("type")
        if (
            child.tag != config + "config-item"
            or name is None
            or name in seen
            or set(child.attrib) != {"name", "type"}
            or len(child)
            or defaults.get(name) != (kind, child.text or "")
        ):
            return False
        seen.add(name)
    return True


def _object_maps(
    documents: tuple[NativeDocument, ...], profile: NativeMergeProfile
) -> tuple[ObjectRelocation, ...]:
    next_id = 1
    result = []
    for document in documents:
        mapping = {}
        anonymous = {}
        attributes = {}
        for section_ordinal, (_name, section) in enumerate(document.sections):
            anonymous_ordinal = 0
            for node in section.iter():
                if local_name(node.tag) in {"ole", "video"}:
                    fail("active/compound objects require a successor merge profile")
                if local_name(node.tag) not in OBJECTS:
                    continue
                identifier = attribute(node, "id")
                if identifier:
                    if (
                        identifier == "0"
                        and local_name(node.tag) != "fieldBegin"
                        and profile == NativeMergeProfile.EDITABLE_V2
                    ):
                        # Native converters use zero for anonymous grouped shapes.
                        # A zero is not a resolvable field/link target. Preserve
                        # every use separately, never collapse them into one ID.
                        replacement = str(next_id)
                        anonymous[section_ordinal, anonymous_ordinal] = replacement
                        anonymous_ordinal += 1
                        next_id += 1
                    else:
                        if identifier in mapping:
                            fail("curated source repeats a document object ID")
                        replacement = str(next_id)
                        mapping[identifier] = replacement
                        next_id += 1
                    if profile == NativeMergeProfile.EDITABLE_V2:
                        for name, value in node.attrib.items():
                            alias = local_name(name).casefold()
                            if alias in {"instid", "fieldid"}:
                                attributes[alias, identifier, replacement] = (value, replacement)
        result.append(ObjectRelocation(mapping, anonymous, attributes))
    return tuple(result)


def write_native_package(payloads: dict[str, bytes], output: Path) -> None:
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if output.exists() or output.is_symlink():
        fail("curated output already exists")
    descriptor, name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            with zipfile.ZipFile(stream, "w", allowZip64=False) as archive:
                for name in ("mimetype", *sorted(set(payloads) - {"mimetype"})):
                    info = zipfile.ZipInfo(name, FIXED_ZIP_TIMESTAMP)
                    info.compress_type = (
                        zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED
                    )
                    info.external_attr = 0o100600 << 16
                    archive.writestr(info, payloads[name])
            stream.flush()
            os.fsync(stream.fileno())
        # Concurrent writers never replace a committed output, even after an existence check.
        os.link(temporary, output)
    finally:
        temporary.unlink()


def merge_native_hwpx(
    sources: tuple[Path, ...],
    output: Path,
    *,
    profile: NativeMergeProfile = NativeMergeProfile.STRICT_V1,
) -> CuratedMergeReport:
    if not 1 <= len(sources) <= 200 or output.exists() or output.is_symlink():
        fail("curated input count or output is invalid")
    documents_list = []
    remaining = MAX_TOTAL_BYTES
    for path in sources:
        if path.is_symlink() or not path.is_file():
            fail("curated source must be a regular local file")
        package = read_package(path, PackageLimits(max_uncompressed_bytes=remaining))
        remaining -= sum(len(entry.data) for entry in package.entries)
        if remaining <= 0:
            fail("curated input byte budget exceeded")
        documents_list.append(parse_native_document(package))
    documents = tuple(documents_list)
    first = documents[0]
    for member in ("settings.xml", "version.xml"):
        if any(
            _settings_identity(document, member, profile)
            != _settings_identity(first, member, profile)
            for document in documents[1:]
        ):
            fail("curated document global settings differ: " + member)
    payloads = {
        entry.info.filename: entry.data
        for entry in first.package.entries
        if entry.info.filename in GLOBAL_PARTS and entry.info.filename not in {HEADER, CONTENT}
    }
    binary_maps = []
    for position, document in enumerate(documents, start=1):
        entries = document.package.by_name()
        mapping = {}
        for ordinal, (identifier, (member, _media)) in enumerate(document.binaries.items()):
            new_id = f"curated{position:03d}Binary{ordinal:04d}"
            suffix = Path(member).suffix.lower()
            new_member = f"BinData/curated-{position:03d}-{ordinal:04d}{suffix}"
            mapping[identifier] = new_id
            payloads[new_member] = entries[member].data
        binary_maps.append(mapping)
    object_maps = _object_maps(documents, profile)
    header, plans = merge_resources(
        tuple(document.header for document in documents),
        tuple(binary_maps),
        object_maps,
        profile=profile,
    )
    content = copy.deepcopy(first.content)
    manifest = next(node for node in content.iter() if local_name(node.tag) == "manifest")
    spine = next(node for node in content.iter() if local_name(node.tag) == "spine")
    template_item = first.manifest[0]
    for node in tuple(manifest):
        member = resolve_part(CONTENT, attribute(node, "href") or "")
        if member.startswith("BinData/") or SECTION.fullmatch(member):
            manifest.remove(node)
    for node in tuple(spine):
        spine.remove(node)

    def add_item(identifier: str, href: str, media: str) -> None:
        node = etree.Element(template_item.tag)
        node.attrib.update({"id": identifier, "href": href, "media-type": media})
        if href.startswith("BinData/"):
            node.attrib["isEmbeded"] = "1"
        manifest.append(node)

    # Header spine references are explicit; header is not a document section.
    for node in manifest:
        if resolve_part(CONTENT, attribute(node, "href") or "") == HEADER:
            ref = etree.SubElement(spine, f"{{{etree.QName(spine).namespace}}}itemref")
            ref.attrib.update({"idref": attribute(node, "id"), "linear": "yes"})
    section_positions: list[int] = []
    expected_sections = []
    for position, (document, plan) in enumerate(zip(documents, plans, strict=True), start=1):
        for ordinal, (identifier, (member, media)) in enumerate(document.binaries.items()):
            new_member = (
                f"BinData/curated-{position:03d}-{ordinal:04d}{Path(member).suffix.lower()}"
            )
            add_item(plan.binaries[identifier], new_member, media)
        for section_ordinal, (_original_name, original) in enumerate(document.sections):
            section = copy.deepcopy(original)
            relocate_tree(section, plan, section_ordinal=section_ordinal)
            identifier = f"section{len(section_positions)}"
            member = f"Contents/{identifier}.xml"
            payloads[member] = _xml(section)
            add_item(identifier, member, "application/xml")
            ref = etree.SubElement(spine, f"{{{etree.QName(spine).namespace}}}itemref")
            ref.attrib.update({"idref": identifier, "linear": "yes"})
            section_positions.append(position)
            expected_sections.append((original, plan))
    set_attribute(header, "secCnt", str(len(section_positions)))
    payloads[HEADER] = _xml(header)
    payloads[CONTENT] = _xml(content)
    if profile == NativeMergeProfile.EDITABLE_V2 and "version.xml" in payloads:
        version = parse_xml(payloads["version.xml"], "version.xml").root
        if local_name(version.tag) == "HCFVersion":
            version.attrib.update({"xmlVersion": "1.5", "micro": "1", "buildNumber": "0"})
            payloads["version.xml"] = _xml(version)
    payloads["Preview/PrvText.txt"] = b"\n".join(
        document.package.by_name()["Preview/PrvText.txt"].data
        for document in documents
        if "Preview/PrvText.txt" in document.package.by_name()
    )
    _rebuild_section_rdf(payloads, len(section_positions))
    if sum(map(len, payloads.values())) > MAX_TOTAL_BYTES:
        fail("curated output byte budget exceeded")
    write_native_package(payloads, output)
    try:
        candidate = parse_native_document(read_package(output, OUTPUT_LIMITS))
        verify_resource_relocation(
            tuple(document.header for document in documents), candidate.header, plans
        )
        if len(candidate.sections) != len(expected_sections):
            fail("curated output section order/count differs")
        for (original, plan), (_member, observed) in zip(
            expected_sections, candidate.sections, strict=True
        ):
            clone = copy.deepcopy(observed)
            relocate_tree(clone, plan.inverse())
            if tree_value(clone) != tree_value(original):
                raise HwpxError(
                    HwpxErrorCode.HWPX_SEMANTIC_MISMATCH,
                    "curated section text/table/equation/geometry differs",
                )
        candidate_entries = candidate.package.by_name()
        for document, plan in zip(documents, plans, strict=True):
            source_entries = document.package.by_name()
            for identifier, (member, media) in document.binaries.items():
                merged_member, merged_media = candidate.binaries[plan.binaries[identifier]]
                if media != merged_media or sha256_bytes(
                    source_entries[member].data
                ) != sha256_bytes(candidate_entries[merged_member].data):
                    fail("curated media lineage differs")
        analysis = analyze_package(output, OUTPUT_LIMITS)
        if (
            analysis.mimetype != "application/hwp+zip"
            or analysis.active_content
            or analysis.external_links
            or any(ref["target"] not in candidate_entries for ref in analysis.internal_references)
        ):
            fail("curated output core/internal references are invalid")
    except Exception:
        output.unlink(missing_ok=True)
        raise
    return CuratedMergeReport(
        tuple(document.package.package_sha256 for document in documents),
        tuple(section_positions),
        sum(map(len, binary_maps)),
        sha256_file(output),
        _merge_warnings(documents, plans, profile),
    )


def _merge_warnings(
    documents: tuple[NativeDocument, ...],
    plans: tuple[ResourceRelocation, ...],
    profile: NativeMergeProfile,
) -> tuple[CuratedHwpxWarning, ...]:
    if profile == NativeMergeProfile.STRICT_V1:
        return ()
    warnings: list[CuratedHwpxWarning] = []
    if any(
        _settings_identity(document, "settings.xml")
        != _settings_identity(documents[0], "settings.xml")
        for document in documents[1:]
    ):
        warnings.append("FIRST_DOCUMENT_PRINT_SETTINGS")
    if any(plan.style_names for plan in plans):
        warnings.append("STYLE_NAMES_RELOCATED")
    return tuple(warnings)


def _rebuild_section_rdf(payloads: dict[str, bytes], count: int) -> None:
    member = "META-INF/container.rdf"
    if member not in payloads:
        return
    root = parse_xml(payloads[member], member).root
    rdf = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    package = "http://www.hancom.co.kr/hwpml/2016/meta/pkg#"
    for node in tuple(root):
        if SECTION.fullmatch(node.attrib.get(f"{{{rdf}}}about", "")) or any(
            SECTION.fullmatch(child.attrib.get(f"{{{rdf}}}resource", "")) for child in node
        ):
            root.remove(node)
    for index in range(count):
        path = f"Contents/section{index}.xml"
        parent = etree.SubElement(root, f"{{{rdf}}}Description", {f"{{{rdf}}}about": ""})
        etree.SubElement(parent, f"{{{package}}}hasPart", {f"{{{rdf}}}resource": path})
        parent = etree.SubElement(root, f"{{{rdf}}}Description", {f"{{{rdf}}}about": path})
        etree.SubElement(parent, f"{{{rdf}}}type", {f"{{{rdf}}}resource": package + "SectionFile"})
    payloads[member] = _xml(root)
