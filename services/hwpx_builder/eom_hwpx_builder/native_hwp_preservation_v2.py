"""Independent V2 check includes every native master page and memo body."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from eom_hwpx_contracts.native_conversion_v2 import NativeHwpConversionEvidenceV2
from eom_hwpx_contracts.validation import parse_json_object, validate_contract

from eom_hwpx_builder.archive import read_package
from eom_hwpx_builder.curated_resources import attribute, fail
from eom_hwpx_builder.native_hwp_preservation import native_hwp_content_fingerprints
from eom_hwpx_builder.xmlsafe import local_name, parse_xml


def verify_native_hwp_candidate_v2(
    candidate: Path, evidence_payload: bytes, *, source_sha256: str
) -> NativeHwpConversionEvidenceV2:
    value = parse_json_object(evidence_payload)
    validate_contract("native-hwp-evidence-v2", value)
    evidence = NativeHwpConversionEvidenceV2.model_validate(value)
    package = read_package(candidate)
    if (
        evidence.source_sha256 != source_sha256
        or evidence.candidate_sha256 != package.package_sha256
    ):
        fail("native HWP V2 source/candidate identity differs")
    entries = package.by_name()
    sections = frozenset(
        name for name in entries if re.fullmatch(r"Contents/section[0-9]+\.xml", name)
    )
    masters = frozenset(
        name for name in entries if re.fullmatch(r"Contents/masterpage[0-9]+\.xml", name)
    )
    observed = native_hwp_content_fingerprints(package, content_members=sections | masters)
    memo_count = sum(
        1
        for member in sections | masters
        for node in parse_xml(entries[member].data, member).root.iter()
        if local_name(node.tag) == "fieldBegin" and attribute(node, "type") == "MEMO"
    )
    if (
        len(sections) != evidence.section_count
        or len(masters) != evidence.masterpage_count
        or memo_count != evidence.memo_count
        or any(page.member_path not in masters for page in evidence.auxiliary_master_pages)
        or Counter(observed.paragraphs) != Counter(evidence.paragraph_sha256)
        or Counter(observed.tables) != Counter(evidence.table_sha256)
        or Counter(observed.equations) != Counter(evidence.equation_sha256)
        or Counter(observed.binaries) != Counter(evidence.binary_sha256)
        or observed.shape_counts != evidence.shape_counts
    ):
        fail("native HWP V2 changed editable source content, master pages, memos or binaries")
    return evidence
