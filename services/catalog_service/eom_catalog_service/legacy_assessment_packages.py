"""Bounded structural inspection for staged untrusted HWPX assessment sources."""

from __future__ import annotations

import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

MAX_HWPX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_HWPX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_HWPX_XML_BYTES = 16 * 1024 * 1024
MAX_HWPX_EXPANDED_BYTES = 512 * 1024 * 1024
MAX_HWPX_MEMBERS = 20_000
_ALLOWED_COMPRESSION = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})
_REQUIRED_MEMBERS = frozenset(
    {
        "mimetype",
        "version.xml",
        "Contents/header.xml",
        "Contents/section0.xml",
        "Contents/content.hpf",
        "META-INF/container.xml",
        "META-INF/manifest.xml",
    }
)


class LegacyAssessmentPackageError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class HwpxPackageObservation:
    member_count: int
    expanded_bytes: int
    xml_member_count: int
    media_member_count: int
    section_count: int


def inspect_hwpx_package(path: Path) -> HwpxPackageObservation:
    """Inspect package topology without executing, converting, or returning document content."""

    metadata = path.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or not 0 < metadata.st_size <= MAX_HWPX_ARCHIVE_BYTES
    ):
        raise LegacyAssessmentPackageError("LEGACY_ASSESSMENT_HWPX_FILE_INVALID")
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if not 0 < len(infos) <= MAX_HWPX_MEMBERS:
                raise LegacyAssessmentPackageError("LEGACY_ASSESSMENT_HWPX_PACKAGE_INVALID")
            names: set[str] = set()
            folded_names: set[str] = set()
            expanded_bytes = 0
            xml_members = 0
            media_members = 0
            sections = 0
            for info in infos:
                _validate_member(info, names=names, folded_names=folded_names)
                names.add(info.filename)
                folded_names.add(info.filename.casefold())
                expanded_bytes += info.file_size
                if expanded_bytes > MAX_HWPX_EXPANDED_BYTES:
                    raise LegacyAssessmentPackageError("LEGACY_ASSESSMENT_HWPX_EXPANSION_LIMIT")
                if info.filename.endswith((".xml", ".hpf", ".rdf")):
                    xml_members += 1
                    _validate_xml_member(archive, info)
                if info.filename.startswith("BinData/"):
                    media_members += 1
                if info.filename.startswith("Contents/section") and info.filename.endswith(".xml"):
                    sections += 1
            if not _REQUIRED_MEMBERS.issubset(names) or sections < 1:
                raise LegacyAssessmentPackageError("LEGACY_ASSESSMENT_HWPX_PACKAGE_INCOMPLETE")
            if archive.read("mimetype") != b"application/hwp+zip":
                raise LegacyAssessmentPackageError("LEGACY_ASSESSMENT_HWPX_MIMETYPE_INVALID")
            return HwpxPackageObservation(
                member_count=len(infos),
                expanded_bytes=expanded_bytes,
                xml_member_count=xml_members,
                media_member_count=media_members,
                section_count=sections,
            )
    except zipfile.BadZipFile as exc:
        raise LegacyAssessmentPackageError("LEGACY_ASSESSMENT_HWPX_PACKAGE_INVALID") from exc


def _validate_member(info: zipfile.ZipInfo, *, names: set[str], folded_names: set[str]) -> None:
    name = info.filename
    member = PurePosixPath(name)
    unix_mode = info.external_attr >> 16
    if (
        name in names
        or name.casefold() in folded_names
        or "\\" in name
        or member.is_absolute()
        or any(part in {"", ".", ".."} for part in member.parts)
        or name.endswith("/")
        or (unix_mode != 0 and stat.S_ISLNK(unix_mode))
        or info.flag_bits & 0x1
        or info.compress_type not in _ALLOWED_COMPRESSION
        or not 0 <= info.file_size <= MAX_HWPX_MEMBER_BYTES
    ):
        raise LegacyAssessmentPackageError("LEGACY_ASSESSMENT_HWPX_MEMBER_UNSAFE")


def _validate_xml_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> None:
    if info.file_size > MAX_HWPX_XML_BYTES:
        raise LegacyAssessmentPackageError("LEGACY_ASSESSMENT_HWPX_XML_LIMIT")
    payload = archive.read(info)
    lowered = payload.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise LegacyAssessmentPackageError("LEGACY_ASSESSMENT_HWPX_XML_UNSAFE")
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise LegacyAssessmentPackageError("LEGACY_ASSESSMENT_HWPX_XML_INVALID") from exc
    for element in root.iter():
        for key, value in element.attrib.items():
            if key.rsplit("}", 1)[-1].casefold() == "targetmode" and value.casefold() == "external":
                raise LegacyAssessmentPackageError("LEGACY_ASSESSMENT_HWPX_EXTERNAL_LINK")
