"""Fail-closed redline editing for immutable document-review HWPX sources."""

from __future__ import annotations

import copy
import io
import os
import stat
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final, NoReturn, cast
from xml.etree import ElementTree

from eom_catalog_contracts import (
    DocumentReviewHwpxCorrectionPlan,
    DocumentReviewHwpxCorrectionResult,
    DocumentReviewHwpxEdit,
    OfficeDocumentReviewMemberPointer,
    PdfDocumentReviewResultMemberPointer,
    validate_contract,
)
from eom_identifiers import content_sha256, sha256_file

MAX_HWPX_BYTES: Final = 256 * 1024 * 1024
MAX_HWPX_MEMBERS: Final = 4096
MAX_HWPX_MEMBER_BYTES: Final = 256 * 1024 * 1024
MAX_HWPX_UNCOMPRESSED_BYTES: Final = 512 * 1024 * 1024
MAX_HWPX_COMPRESSION_RATIO: Final = 200
MAX_XML_BYTES: Final = 64 * 1024 * 1024
HWPX_MIMETYPE: Final = b"application/hwp+zip"
RED_TEXT_COLOR: Final = "#FF0000"


class DocumentReviewHwpxError(RuntimeError):
    """Stable correction error that never exposes document contents."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class DocumentReviewReplacement:
    finding_id: str
    finding_code: str
    before_text: str
    after_text: str


@dataclass(frozen=True, slots=True)
class _PackageMember:
    info: zipfile.ZipInfo
    payload: bytes


@dataclass(frozen=True, slots=True)
class _TextSegment:
    start: int
    end: int
    run: ElementTree.Element
    text: ElementTree.Element
    source_char_property_id: int


@dataclass(frozen=True, slots=True)
class _Paragraph:
    section_member: str
    ordinal: int
    element: ElementTree.Element
    text: str
    segments: tuple[_TextSegment, ...]


def _fail(code: str, message: str) -> NoReturn:
    raise DocumentReviewHwpxError(code, message)


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
    )


def _attribute(element: ElementTree.Element, name: str) -> str | None:
    for key, value in element.attrib.items():
        if _local_name(key).casefold() == name.casefold():
            return value
    return None


def _set_attribute(element: ElementTree.Element, name: str, value: str) -> None:
    for key in element.attrib:
        if _local_name(key).casefold() == name.casefold():
            element.attrib[key] = value
            return
    element.attrib[name] = value


def _stable_file_bytes(path: Path) -> bytes:
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as exc:
        raise DocumentReviewHwpxError(
            "DOCUMENT_REVIEW_HWPX_SOURCE_UNREADABLE",
            "HWPX source could not be opened safely",
        ) from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 1 <= before.st_size <= MAX_HWPX_BYTES
        ):
            _fail(
                "DOCUMENT_REVIEW_HWPX_SOURCE_UNSAFE",
                "HWPX source is not one bounded regular file",
            )
        payload = bytearray()
        while len(payload) < before.st_size:
            chunk = os.read(descriptor, min(1024 * 1024, before.st_size - len(payload)))
            if not chunk:
                _fail(
                    "DOCUMENT_REVIEW_HWPX_SOURCE_CHANGED",
                    "HWPX source ended before its opened size",
                )
            payload.extend(chunk)
        if os.read(descriptor, 1):
            _fail("DOCUMENT_REVIEW_HWPX_SOURCE_CHANGED", "HWPX source grew while reading")
        after = os.fstat(descriptor)
        if _file_identity(before) != _file_identity(after):
            _fail("DOCUMENT_REVIEW_HWPX_SOURCE_CHANGED", "HWPX source changed while reading")
        return bytes(payload)
    finally:
        os.close(descriptor)


def _safe_member_name(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        bool(name)
        and "\\" not in name
        and not path.is_absolute()
        and ".." not in path.parts
        and not name.startswith("/")
    )


def _load_package(path: Path) -> tuple[_PackageMember, ...]:
    payload = _stable_file_bytes(path)
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except (OSError, zipfile.BadZipFile) as exc:
        raise DocumentReviewHwpxError(
            "DOCUMENT_REVIEW_HWPX_ZIP_INVALID",
            "HWPX source is not a valid ZIP package",
        ) from exc
    with archive:
        infos = archive.infolist()
        if not 1 <= len(infos) <= MAX_HWPX_MEMBERS:
            _fail("DOCUMENT_REVIEW_HWPX_MEMBER_COUNT_INVALID", "HWPX member count is invalid")
        if infos[0].filename != "mimetype" or infos[0].compress_type != zipfile.ZIP_STORED:
            _fail(
                "DOCUMENT_REVIEW_HWPX_MIMETYPE_INVALID",
                "HWPX mimetype must be the first stored member",
            )
        seen: set[str] = set()
        members: list[_PackageMember] = []
        total_size = 0
        for info in infos:
            folded = info.filename.casefold()
            unix_mode = (info.external_attr >> 16) & 0o170000
            if (
                not _safe_member_name(info.filename)
                or info.is_dir()
                or folded in seen
                or unix_mode not in {0, stat.S_IFREG}
            ):
                _fail("DOCUMENT_REVIEW_HWPX_MEMBER_UNSAFE", "HWPX contains an unsafe member")
            seen.add(folded)
            if not 0 <= info.file_size <= MAX_HWPX_MEMBER_BYTES:
                _fail(
                    "DOCUMENT_REVIEW_HWPX_MEMBER_TOO_LARGE",
                    "HWPX contains an oversized member",
                )
            total_size += info.file_size
            if total_size > MAX_HWPX_UNCOMPRESSED_BYTES:
                _fail("DOCUMENT_REVIEW_HWPX_TOO_LARGE", "HWPX expands beyond the safe bound")
            if info.file_size and info.compress_size == 0:
                _fail(
                    "DOCUMENT_REVIEW_HWPX_COMPRESSION_INVALID",
                    "HWPX member compression metadata is invalid",
                )
            if (
                info.compress_size
                and info.file_size / info.compress_size > MAX_HWPX_COMPRESSION_RATIO
            ):
                _fail(
                    "DOCUMENT_REVIEW_HWPX_COMPRESSION_RATIO_EXCEEDED",
                    "HWPX member compression ratio exceeds the safe bound",
                )
            try:
                member_payload = archive.read(info)
            except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                raise DocumentReviewHwpxError(
                    "DOCUMENT_REVIEW_HWPX_MEMBER_UNREADABLE",
                    "HWPX member could not be read safely",
                ) from exc
            if len(member_payload) != info.file_size:
                _fail(
                    "DOCUMENT_REVIEW_HWPX_MEMBER_CHANGED",
                    "HWPX member differs from its ZIP metadata",
                )
            members.append(_PackageMember(info=info, payload=member_payload))
        by_name = {member.info.filename: member.payload for member in members}
        if by_name.get("mimetype") != HWPX_MIMETYPE:
            _fail("DOCUMENT_REVIEW_HWPX_MIMETYPE_INVALID", "HWPX mimetype bytes differ")
        required = {"Contents/header.xml", "Contents/content.hpf", "META-INF/container.xml"}
        if not required.issubset(by_name):
            _fail("DOCUMENT_REVIEW_HWPX_CORE_MISSING", "HWPX core package members are missing")
        if not any(
            name.startswith("Contents/section") and name.endswith(".xml") for name in by_name
        ):
            _fail("DOCUMENT_REVIEW_HWPX_SECTION_MISSING", "HWPX has no section XML")
        return tuple(members)


def _parse_xml(payload: bytes, member_name: str) -> ElementTree.Element:
    if not 1 <= len(payload) <= MAX_XML_BYTES:
        _fail("DOCUMENT_REVIEW_HWPX_XML_INVALID", "HWPX XML member size is invalid")
    upper = payload.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        _fail("DOCUMENT_REVIEW_HWPX_XML_UNSAFE", "HWPX XML declares DTD or entities")
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise DocumentReviewHwpxError(
            "DOCUMENT_REVIEW_HWPX_XML_INVALID",
            f"HWPX XML is malformed: {member_name}",
        ) from exc
    for element in root.iter():
        for value in element.attrib.values():
            lowered = value.strip().casefold()
            if lowered.startswith(("file:", "http:", "https:", "ftp:", "javascript:")):
                _fail(
                    "DOCUMENT_REVIEW_HWPX_EXTERNAL_REFERENCE",
                    "HWPX XML contains an external reference",
                )
    return root


def _section_number(name: str) -> int:
    stem = name.removeprefix("Contents/section").removesuffix(".xml")
    if not stem.isdigit():
        _fail("DOCUMENT_REVIEW_HWPX_SECTION_INVALID", "HWPX section member is invalid")
    return int(stem)


def _paragraphs(
    members: dict[str, bytes],
) -> tuple[dict[str, ElementTree.Element], tuple[_Paragraph, ...]]:
    section_names = sorted(
        (name for name in members if name.startswith("Contents/section") and name.endswith(".xml")),
        key=_section_number,
    )
    if tuple(_section_number(name) for name in section_names) != tuple(range(len(section_names))):
        _fail("DOCUMENT_REVIEW_HWPX_SECTION_INVALID", "HWPX sections are not contiguous")
    roots: dict[str, ElementTree.Element] = {}
    paragraphs: list[_Paragraph] = []
    for section_name in section_names:
        root = _parse_xml(members[section_name], section_name)
        roots[section_name] = root
        ordinal = 0
        for paragraph in root.iter():
            if _local_name(paragraph.tag) != "p":
                continue
            fragments: list[str] = []
            segments: list[_TextSegment] = []
            offset = 0
            for run in list(paragraph):
                if _local_name(run.tag) != "run":
                    continue
                raw_property_id = _attribute(run, "charPrIDRef")
                if raw_property_id is None or not raw_property_id.isdigit():
                    _fail(
                        "DOCUMENT_REVIEW_HWPX_RUN_INVALID",
                        "HWPX text run has no valid character property",
                    )
                property_id = int(raw_property_id)
                for text_element in run.iter():
                    if _local_name(text_element.tag) != "t":
                        continue
                    fragment = "".join(text_element.itertext())
                    fragments.append(fragment)
                    segments.append(
                        _TextSegment(
                            start=offset,
                            end=offset + len(fragment),
                            run=run,
                            text=text_element,
                            source_char_property_id=property_id,
                        )
                    )
                    offset += len(fragment)
            paragraphs.append(
                _Paragraph(
                    section_member=section_name,
                    ordinal=ordinal,
                    element=paragraph,
                    text="".join(fragments),
                    segments=tuple(segments),
                )
            )
            ordinal += 1
    return roots, tuple(paragraphs)


def _eligible_segment(paragraph: _Paragraph, start: int, end: int) -> _TextSegment:
    matching = [
        segment for segment in paragraph.segments if segment.start <= start and end <= segment.end
    ]
    if len(matching) != 1:
        _fail(
            "DOCUMENT_REVIEW_HWPX_EDIT_CROSSES_RUN",
            "Selected replacement crosses an unsupported HWPX run boundary",
        )
    segment = matching[0]
    if (
        len(list(segment.run)) != 1
        or next(iter(segment.run)) is not segment.text
        or len(list(segment.text)) != 0
        or segment.text.text is None
    ):
        _fail(
            "DOCUMENT_REVIEW_HWPX_EDIT_UNSUPPORTED",
            "Selected replacement intersects a control or structured HWPX text node",
        )
    return segment


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def build_document_review_hwpx_correction_plan(
    source: Path,
    *,
    correction_id: str,
    workflow_id: str,
    review_result: PdfDocumentReviewResultMemberPointer,
    base_hwpx: OfficeDocumentReviewMemberPointer,
    replacements: tuple[DocumentReviewReplacement, ...],
) -> DocumentReviewHwpxCorrectionPlan:
    """Resolve review replacements to unique immutable HWPX paragraph addresses."""

    if not 1 <= len(replacements) <= 32:
        _fail(
            "DOCUMENT_REVIEW_HWPX_FINDING_COUNT_INVALID",
            "HWPX correction requires between one and 32 findings",
        )
    finding_ids = tuple(item.finding_id for item in replacements)
    if len(finding_ids) != len(set(finding_ids)):
        _fail("DOCUMENT_REVIEW_HWPX_FINDING_DUPLICATE", "HWPX correction findings repeat")
    if sha256_file(source) != base_hwpx.sha256:
        _fail("DOCUMENT_REVIEW_HWPX_BASE_HASH_MISMATCH", "HWPX base bytes differ")
    package = _load_package(source)
    members = {member.info.filename: member.payload for member in package}
    _, paragraphs = _paragraphs(members)
    edits: list[dict[str, object]] = []
    for replacement in replacements:
        before_text = _normalized(replacement.before_text)
        after_text = _normalized(replacement.after_text)
        if not before_text or not after_text or before_text == after_text:
            _fail(
                "DOCUMENT_REVIEW_HWPX_REPLACEMENT_INVALID",
                "HWPX correction requires different non-empty replacement text",
            )
        occurrences: list[tuple[_Paragraph, int]] = []
        for paragraph in paragraphs:
            normalized_paragraph = _normalized(paragraph.text)
            cursor = 0
            while True:
                start = normalized_paragraph.find(before_text, cursor)
                if start < 0:
                    break
                occurrences.append((paragraph, start))
                cursor = start + max(1, len(before_text))
        if len(occurrences) != 1:
            _fail(
                "DOCUMENT_REVIEW_HWPX_REPLACEMENT_AMBIGUOUS",
                "HWPX replacement text does not resolve to exactly one occurrence",
            )
        paragraph, start = occurrences[0]
        end = start + len(before_text)
        if paragraph.text[start:end] != replacement.before_text:
            _fail(
                "DOCUMENT_REVIEW_HWPX_REPLACEMENT_NORMALIZATION_UNSAFE",
                "HWPX replacement cannot preserve exact Unicode offsets",
            )
        segment = _eligible_segment(paragraph, start, end)
        edits.append(
            {
                "finding_id": replacement.finding_id,
                "finding_code": replacement.finding_code,
                "before_text": replacement.before_text,
                "before_sha256": content_sha256(replacement.before_text),
                "after_text": replacement.after_text,
                "after_sha256": content_sha256(replacement.after_text),
                "address": {
                    "section_member": paragraph.section_member,
                    "paragraph_ordinal": paragraph.ordinal,
                    "paragraph_sha256": content_sha256(paragraph.text),
                    "start_offset": start,
                    "end_offset": end,
                    "source_char_property_id": segment.source_char_property_id,
                },
            }
        )
    edits.sort(
        key=lambda value: (
            str(value["address"]["section_member"]),  # type: ignore[index]
            int(value["address"]["paragraph_ordinal"]),  # type: ignore[index]
            int(value["address"]["start_offset"]),  # type: ignore[index]
        )
    )
    value: dict[str, object] = {
        "schema_version": "document-review-hwpx-correction-plan/1.0",
        "correction_id": correction_id,
        "workflow_id": workflow_id,
        "review_result": review_result.model_dump(mode="json"),
        "base_hwpx": base_hwpx.model_dump(mode="json"),
        "text_color": RED_TEXT_COLOR,
        "edits": edits,
    }
    value["plan_sha256"] = content_sha256(value)
    validate_contract("document-review-hwpx-correction-plan", value)
    return DocumentReviewHwpxCorrectionPlan.model_validate(value)


def _clone_red_character_properties(
    header: ElementTree.Element,
    source_ids: set[int],
) -> dict[int, int]:
    collections = [
        element for element in header.iter() if _local_name(element.tag) == "charProperties"
    ]
    if len(collections) != 1:
        _fail(
            "DOCUMENT_REVIEW_HWPX_CHARACTER_PROPERTIES_INVALID",
            "HWPX character-property collection is missing or ambiguous",
        )
    collection = collections[0]
    properties: dict[int, ElementTree.Element] = {}
    for element in list(collection):
        if _local_name(element.tag) != "charPr":
            continue
        raw_id = _attribute(element, "id")
        if raw_id is None or not raw_id.isdigit() or int(raw_id) in properties:
            _fail(
                "DOCUMENT_REVIEW_HWPX_CHARACTER_PROPERTIES_INVALID",
                "HWPX character-property identity is invalid",
            )
        properties[int(raw_id)] = element
    if not source_ids.issubset(properties):
        _fail(
            "DOCUMENT_REVIEW_HWPX_CHARACTER_PROPERTY_MISSING",
            "HWPX correction references a missing character property",
        )
    next_id = max(properties, default=-1) + 1
    red_ids: dict[int, int] = {}
    for source_id in sorted(source_ids):
        clone = copy.deepcopy(properties[source_id])
        _set_attribute(clone, "id", str(next_id))
        _set_attribute(clone, "textColor", RED_TEXT_COLOR)
        collection.append(clone)
        red_ids[source_id] = next_id
        next_id += 1
    _set_attribute(collection, "itemCnt", str(len(properties) + len(red_ids)))
    return red_ids


def _replace_in_run(
    paragraph: _Paragraph,
    segment: _TextSegment,
    *,
    edits: tuple[tuple[int, int, str, int], ...],
) -> None:
    source_text = segment.text.text
    if source_text is None:
        _fail("DOCUMENT_REVIEW_HWPX_EDIT_UNSUPPORTED", "HWPX text node is empty")
    children = list(paragraph.element)
    try:
        run_index = children.index(segment.run)
    except ValueError:
        _fail("DOCUMENT_REVIEW_HWPX_EDIT_UNSUPPORTED", "HWPX text run is not a paragraph child")
    pieces: list[tuple[str, int]] = []
    cursor = 0
    for start, end, replacement, red_property_id in edits:
        local_start = start - segment.start
        local_end = end - segment.start
        if local_start < cursor or local_end > len(source_text):
            _fail("DOCUMENT_REVIEW_HWPX_EDIT_OVERLAP", "HWPX correction edits overlap")
        pieces.append((source_text[cursor:local_start], segment.source_char_property_id))
        pieces.append((replacement, red_property_id))
        cursor = local_end
    pieces.append((source_text[cursor:], segment.source_char_property_id))
    replacements: list[ElementTree.Element] = []
    for text, property_id in pieces:
        if not text:
            continue
        run = copy.deepcopy(segment.run)
        _set_attribute(run, "charPrIDRef", str(property_id))
        text_element = next(iter(run))
        text_element.text = text
        replacements.append(run)
    paragraph.element.remove(segment.run)
    for offset, run in enumerate(replacements):
        paragraph.element.insert(run_index + offset, run)


def _xml_bytes(root: ElementTree.Element) -> bytes:
    return cast(
        bytes,
        ElementTree.tostring(
            root,
            encoding="utf-8",
            xml_declaration=True,
            short_empty_elements=True,
        ),
    )


def _copy_zip_info(info: zipfile.ZipInfo) -> zipfile.ZipInfo:
    copied = zipfile.ZipInfo(info.filename, date_time=info.date_time)
    copied.compress_type = info.compress_type
    copied.comment = info.comment
    copied.extra = info.extra
    copied.create_system = info.create_system
    copied.create_version = info.create_version
    copied.extract_version = info.extract_version
    copied.flag_bits = info.flag_bits
    copied.internal_attr = info.internal_attr
    copied.external_attr = info.external_attr
    copied.volume = info.volume
    return copied


def apply_document_review_hwpx_correction(
    source: Path,
    output: Path,
    plan: DocumentReviewHwpxCorrectionPlan,
) -> DocumentReviewHwpxCorrectionResult:
    """Apply one validated plan and create a new redline HWPX, never in place."""

    if source.resolve(strict=True) == output.resolve(strict=False):
        _fail("DOCUMENT_REVIEW_HWPX_OUTPUT_INVALID", "HWPX correction cannot overwrite its base")
    if output.exists() or output.is_symlink():
        _fail("DOCUMENT_REVIEW_HWPX_OUTPUT_EXISTS", "HWPX correction output already exists")
    if sha256_file(source) != plan.base_hwpx.sha256:
        _fail("DOCUMENT_REVIEW_HWPX_BASE_HASH_MISMATCH", "HWPX base bytes differ")
    package = _load_package(source)
    members = {member.info.filename: member.payload for member in package}
    header = _parse_xml(members["Contents/header.xml"], "Contents/header.xml")
    section_roots, paragraphs = _paragraphs(members)
    paragraph_map = {(item.section_member, item.ordinal): item for item in paragraphs}
    resolved: list[tuple[DocumentReviewHwpxEdit, _Paragraph, _TextSegment]] = []
    for edit in plan.edits:
        key = (edit.address.section_member, edit.address.paragraph_ordinal)
        paragraph = paragraph_map.get(key)
        if paragraph is None or content_sha256(paragraph.text) != edit.address.paragraph_sha256:
            _fail(
                "DOCUMENT_REVIEW_HWPX_PARAGRAPH_STALE",
                "HWPX correction paragraph differs from the pinned plan",
            )
        if paragraph.text[edit.address.start_offset : edit.address.end_offset] != edit.before_text:
            _fail(
                "DOCUMENT_REVIEW_HWPX_BEFORE_TEXT_MISMATCH",
                "HWPX correction before-text differs from the pinned plan",
            )
        segment = _eligible_segment(
            paragraph,
            edit.address.start_offset,
            edit.address.end_offset,
        )
        if segment.source_char_property_id != edit.address.source_char_property_id:
            _fail(
                "DOCUMENT_REVIEW_HWPX_CHARACTER_PROPERTY_STALE",
                "HWPX correction character property differs from the pinned plan",
            )
        resolved.append((edit, paragraph, segment))
    red_ids = _clone_red_character_properties(
        header,
        {edit.address.source_char_property_id for edit in plan.edits},
    )
    grouped: dict[
        tuple[str, int, int],
        tuple[_Paragraph, _TextSegment, list[tuple[int, int, str, int]]],
    ] = {}
    for edit, paragraph, segment in resolved:
        group_key = (
            paragraph.section_member,
            paragraph.ordinal,
            id(segment.run),
        )
        group = grouped.get(group_key)
        if group is None:
            group = (paragraph, segment, [])
            grouped[group_key] = group
        group[2].append(
            (
                edit.address.start_offset,
                edit.address.end_offset,
                edit.after_text,
                red_ids[edit.address.source_char_property_id],
            )
        )
    for paragraph, segment, edits in reversed(tuple(grouped.values())):
        _replace_in_run(
            paragraph,
            segment,
            edits=tuple(edits),
        )
    changed = {
        "Contents/header.xml": _xml_bytes(header),
        **{name: _xml_bytes(root) for name, root in section_roots.items()},
    }
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(output, mode="x") as archive:
            for member in package:
                archive.writestr(
                    _copy_zip_info(member.info),
                    changed.get(member.info.filename, member.payload),
                )
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        output.unlink(missing_ok=True)
        raise DocumentReviewHwpxError(
            "DOCUMENT_REVIEW_HWPX_WRITE_FAILED",
            "HWPX correction output could not be written",
        ) from exc
    output.chmod(0o600)
    output_hash = sha256_file(output)
    if output_hash == plan.base_hwpx.sha256:
        output.unlink(missing_ok=True)
        _fail("DOCUMENT_REVIEW_HWPX_OUTPUT_UNCHANGED", "HWPX correction did not change bytes")
    _load_package(output)
    value: dict[str, object] = {
        "schema_version": "document-review-hwpx-correction-result/1.0",
        "correction_id": plan.correction_id,
        "workflow_id": plan.workflow_id,
        "plan_sha256": plan.plan_sha256,
        "base_hwpx_sha256": plan.base_hwpx.sha256,
        "output_member": {
            "member_path": "corrected/document-review-redline.hwpx",
            "sha256": output_hash,
            "content_length": output.stat().st_size,
            "media_type": "application/vnd.hancom.hwpx",
        },
        "applied_finding_ids": [edit.finding_id for edit in plan.edits],
        "text_color": RED_TEXT_COLOR,
    }
    value["result_sha256"] = content_sha256(value)
    validate_contract("document-review-hwpx-correction-result", value)
    return DocumentReviewHwpxCorrectionResult.model_validate(value)
