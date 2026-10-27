"""Verify and remap source-to-candidate image references in curated HWPX assemblies.

This corrects a candidate's manifest-ID collisions; it does not certify text,
styles, page geometry, or editability. Those remain separate delivery gates.
"""

from __future__ import annotations

import os
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from lxml import etree  # type: ignore[import-untyped]

from eom_hwpx_builder.analyzer import resolve_part
from eom_hwpx_builder.archive import FIXED_ZIP_TIMESTAMP, SafePackage, read_package
from eom_hwpx_builder.errors import HwpxError, HwpxErrorCode
from eom_hwpx_builder.util import sha256_bytes
from eom_hwpx_builder.xmlsafe import ParsedXml, local_name, parse_xml, serialize_xml

_CONTENT = "Contents/content.hpf"


@dataclass(frozen=True)
class BinaryReferenceChange:
    position: int
    reference_ordinal: int
    source_binary_sha256: str
    previous_manifest_id: str
    corrected_manifest_id: str


def _attribute(element: etree._Element, name: str) -> str | None:
    return next(
        (str(value) for key, value in element.attrib.items() if local_name(key).casefold() == name),
        None,
    )


def _manifest(package: SafePackage) -> tuple[dict[str, tuple[str, str]], tuple[str, ...]]:
    entries = package.by_name()
    content = entries.get(_CONTENT)
    if content is None:
        raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_BROKEN, "package manifest is missing")
    root = parse_xml(content.data, _CONTENT).root
    manifest = next((node for node in root.iter() if local_name(node.tag) == "manifest"), None)
    spine = next((node for node in root.iter() if local_name(node.tag) == "spine"), None)
    if manifest is None or spine is None:
        raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_BROKEN, "package spine is missing")
    by_id: dict[str, str] = {}
    binary_identity: dict[str, tuple[str, str]] = {}
    for item in manifest:
        if local_name(item.tag) != "item":
            continue
        identifier, href = _attribute(item, "id"), _attribute(item, "href")
        if not identifier or not href or identifier in by_id:
            raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_BROKEN, "manifest identity is invalid")
        member = resolve_part(_CONTENT, href)
        by_id[identifier] = member
        if member.startswith("BinData/"):
            entry = entries.get(member)
            media_type = _attribute(item, "media-type")
            if entry is None or not media_type:
                raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_BROKEN, "binary member is missing")
            binary_identity[identifier] = (sha256_bytes(entry.data), media_type)
    sections: list[str] = []
    for itemref in spine:
        if local_name(itemref.tag) != "itemref":
            continue
        identifier = _attribute(itemref, "idref")
        spine_member = by_id.get(identifier or "")
        if spine_member is None:
            raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_BROKEN, "spine target is missing")
        if spine_member.startswith("Contents/section") and spine_member.endswith(".xml"):
            if spine_member not in entries or spine_member in sections:
                raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_BROKEN, "section is invalid")
            sections.append(spine_member)
    if not sections:
        raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_BROKEN, "package has no sections")
    return binary_identity, tuple(sections)


def _references(section: etree._Element) -> tuple[tuple[str, etree._Element, str, str], ...]:
    result: list[tuple[str, etree._Element, str, str]] = []
    for element in section.iter():
        for key, value in element.attrib.items():
            if local_name(key).casefold() == "binaryitemidref" and value:
                result.append((local_name(element.tag), element, key, str(value)))
    return tuple(result)


def remap_curated_binary_lineage(
    sources: tuple[Path, ...], candidate: Path, output: Path
) -> tuple[BinaryReferenceChange, ...]:
    """Produce a separate candidate with source-image bytes bound to each section.

    Each source must contain exactly one section. Reference node count and element
    names must agree with the corresponding candidate section; any other shape
    requires a different, explicitly reviewed merger. A successful result is
    only a media-lineage candidate, not publishable HWPX acceptance.
    """

    if not sources or len(sources) > 200 or output.exists() or output == candidate:
        raise HwpxError(HwpxErrorCode.HWPX_PACKAGE_BUILD_FAILED, "curated inputs are invalid")
    merged = read_package(candidate)
    merged_identity, merged_sections = _manifest(merged)
    if len(merged_sections) != len(sources):
        raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_BROKEN, "section count differs")
    ids_by_identity: dict[tuple[str, str], list[str]] = defaultdict(list)
    for identifier, identity in merged_identity.items():
        ids_by_identity[identity].append(identifier)
    for identifiers in ids_by_identity.values():
        identifiers.sort()

    replacements: dict[str, bytes] = {}
    changes: list[BinaryReferenceChange] = []
    expected_lineages: list[tuple[tuple[str, str], ...]] = []
    merged_entries = merged.by_name()
    for position, (source_path, section_name) in enumerate(
        zip(sources, merged_sections, strict=True), start=1
    ):
        source = read_package(source_path)
        source_identity, source_sections = _manifest(source)
        if len(source_sections) != 1:
            raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_BROKEN, "source is not one section")
        source_root = parse_xml(source.by_name()[source_sections[0]].data, source_sections[0]).root
        candidate_entry = merged_entries[section_name]
        candidate_xml = parse_xml(candidate_entry.data, section_name)
        original_refs = _references(source_root)
        candidate_refs = _references(candidate_xml.root)
        if len(original_refs) != len(candidate_refs) or tuple(
            name for name, *_rest in original_refs
        ) != tuple(name for name, *_rest in candidate_refs):
            raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_BROKEN, "binary reference order differs")
        expected_for_section: list[tuple[str, str]] = []
        for ordinal, ((_, _, _, source_id), (_, element, key, candidate_id)) in enumerate(
            zip(original_refs, candidate_refs, strict=True), start=1
        ):
            source_binary_identity = source_identity.get(source_id)
            if source_binary_identity is None:
                raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_BROKEN, "source binary is missing")
            expected_for_section.append(source_binary_identity)
            matching_ids = ids_by_identity.get(source_binary_identity)
            if not matching_ids:
                raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_BROKEN, "source media is not embedded")
            corrected_id = matching_ids[0]
            if candidate_id != corrected_id:
                element.attrib[key] = corrected_id
                changes.append(
                    BinaryReferenceChange(
                        position=position,
                        reference_ordinal=ordinal,
                        source_binary_sha256=source_binary_identity[0],
                        previous_manifest_id=candidate_id,
                        corrected_manifest_id=corrected_id,
                    )
                )
        expected_lineages.append(tuple(expected_for_section))
        replacements[section_name] = serialize_xml(
            ParsedXml(
                root=candidate_xml.root,
                declaration=candidate_xml.declaration,
                newline=candidate_xml.newline,
                bom=candidate_xml.bom,
            )
        )

    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    if temporary.exists():
        raise HwpxError(HwpxErrorCode.HWPX_PACKAGE_BUILD_FAILED, "temporary output exists")
    try:
        with zipfile.ZipFile(temporary, "x", allowZip64=False) as archive:
            for entry in merged.entries:
                name = entry.info.filename
                info = zipfile.ZipInfo(name, FIXED_ZIP_TIMESTAMP)
                info.compress_type = entry.info.compress_type
                info.external_attr = 0o100600 << 16
                archive.writestr(info, replacements.get(name, entry.data))
        temporary.chmod(0o600)
        # The candidate is immutable: a concurrent writer must not be replaced.
        os.link(temporary, output)
        temporary.unlink()
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    try:
        repaired = read_package(output)
        repaired_identity, repaired_sections = _manifest(repaired)
        if repaired_sections != merged_sections:
            raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_BROKEN, "section order differs")
        for expected, section_name in zip(expected_lineages, repaired_sections, strict=True):
            repaired_refs = _references(
                parse_xml(repaired.by_name()[section_name].data, section_name).root
            )
            actual = tuple(repaired_identity.get(ref) for _, _, _, ref in repaired_refs)
            if actual != expected:
                raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_BROKEN, "binary lineage differs")
    except Exception:
        output.unlink(missing_ok=True)
        raise
    return tuple(changes)
