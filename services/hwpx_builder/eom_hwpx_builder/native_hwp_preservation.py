"""Compare native source evidence with the candidate's editable HWPX structures."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from eom_hwpx_contracts.native_conversion import (
    NativeHwpConversionEvidence,
    NativeHwpShapeCounts,
)
from eom_hwpx_contracts.validation import parse_json_object, validate_contract

from eom_hwpx_builder.archive import SafePackage, read_package
from eom_hwpx_builder.curated_resources import fail
from eom_hwpx_builder.util import sha256_bytes
from eom_hwpx_builder.xmlsafe import local_name, parse_xml

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


@dataclass(frozen=True)
class NativeHwpContentFingerprints:
    paragraphs: tuple[str, ...]
    tables: tuple[str, ...]
    equations: tuple[str, ...]
    binaries: tuple[str, ...]
    shape_counts: NativeHwpShapeCounts


def native_hwp_content_fingerprints(
    package: SafePackage, *, content_members: frozenset[str]
) -> NativeHwpContentFingerprints:
    """Fingerprint exact declared native roots, keeping V1 section-only scope unchanged."""
    paragraphs: list[str] = []
    tables: list[str] = []
    equations: list[str] = []
    binaries: list[str] = []
    shapes: Counter[str] = Counter()
    for entry in package.entries:
        member = entry.info.filename
        if member.startswith("BinData/"):
            binaries.append(sha256_bytes(entry.data))
        if member not in content_members:
            continue
        root = parse_xml(entry.data, member).root
        for node in root.iter():
            name = local_name(node.tag)
            if name in NativeHwpShapeCounts.model_fields:
                shapes[name] += 1
            if node.tag == HP + "p":
                # Each nested paragraph owns its direct runs, including memo subLists.
                text = "".join(
                    "".join(text.itertext())
                    for run in node.findall(HP + "run")
                    for text in run.findall(HP + "t")
                )
                paragraphs.append(
                    sha256_bytes("".join(c for c in text if not c.isspace()).encode("utf-8"))
                )
            elif node.tag == HP + "equation":
                equations.append(sha256_bytes((node.findtext(HP + "script") or "").encode()))
            elif node.tag == HP + "tbl":
                dimensions = (node.get("rowCnt"), node.get("colCnt"))
                if any(value is None for value in dimensions):
                    fail("native HWP conversion table dimensions are absent")
                cells = []
                for row in node.findall(HP + "tr"):
                    for cell in row.findall(HP + "tc"):
                        address = cell.find(HP + "cellAddr")
                        span = cell.find(HP + "cellSpan")
                        size = cell.find(HP + "cellSz")
                        if address is None or span is None or size is None:
                            fail("native HWP conversion cell geometry is absent")
                        values = (
                            address.get("colAddr"),
                            address.get("rowAddr"),
                            span.get("colSpan"),
                            span.get("rowSpan"),
                            size.get("width"),
                            size.get("height"),
                        )
                        if any(value is None for value in values):
                            fail("native HWP conversion cell geometry is incomplete")
                        cells.append(",".join(str(value) for value in values) + ";")
                descriptor = ",".join(str(value) for value in dimensions) + ";" + "".join(cells)
                tables.append(sha256_bytes(descriptor.encode("utf-8")))
    return NativeHwpContentFingerprints(
        tuple(paragraphs),
        tuple(tables),
        tuple(equations),
        tuple(binaries),
        NativeHwpShapeCounts(**{name: shapes[name] for name in NativeHwpShapeCounts.model_fields}),
    )


def verify_native_hwp_candidate(
    candidate: Path, evidence_payload: bytes, *, source_sha256: str
) -> NativeHwpConversionEvidence:
    """Multiset text/structure checks do not claim to prove paragraph reading order."""
    value = parse_json_object(evidence_payload)
    validate_contract("native-hwp-evidence", value)
    evidence = NativeHwpConversionEvidence.model_validate(value)
    package = read_package(candidate)
    if (
        evidence.source_sha256 != source_sha256
        or evidence.candidate_sha256 != package.package_sha256
    ):
        fail("native HWP conversion source/candidate identity differs")
    sections = frozenset(
        entry.info.filename
        for entry in package.entries
        if entry.info.filename.startswith("Contents/section")
        and entry.info.filename.endswith(".xml")
    )
    observed = native_hwp_content_fingerprints(package, content_members=sections)
    if (
        len(sections) != evidence.section_count
        or Counter(observed.paragraphs) != Counter(evidence.paragraph_sha256)
        or Counter(observed.tables) != Counter(evidence.table_sha256)
        or Counter(observed.equations) != Counter(evidence.equation_sha256)
        or Counter(observed.binaries) != Counter(evidence.binary_sha256)
        or observed.shape_counts != evidence.shape_counts
    ):
        fail("native HWP conversion changed editable source content or binary members")
    return evidence
