"""Independent, bounded acceptance of content-team HWPX bytes.

This adapter intentionally does not import the HWPX Builder. Builder reports are diagnostics; the
approved Item and the stable-open package bytes are the two authoritative inputs.
"""

from __future__ import annotations

import hashlib
import io
import os
import posixpath
import re
import stat
import unicodedata
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import NoReturn
from urllib.parse import urlparse
from xml.etree import ElementTree

from eom_hwpx_contracts import (
    ContentTeamAcceptedImageV1,
    ContentTeamAcceptedItemV1,
    ContentTeamAcceptedTableV1,
    ContentTeamEditorialDraftContract,
    ContentTeamImageSource,
    ContentTeamOutputAcceptanceV1,
    ContentTeamTable,
    project_content_team_equation_script,
    validate_content_team_image_bindings,
)
from eom_identifiers import content_sha256

from eom_hwpx_manager.errors import HwpxManagerError, HwpxManagerErrorCode

MAX_PACKAGE_BYTES = 64 * 1024 * 1024
MAX_ENTRY_COUNT = 2000
MAX_MEMBER_BYTES = 25 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100
MAX_FILENAME_LENGTH = 240
MAX_XML_BYTES = 10 * 1024 * 1024
MAX_XML_DEPTH = 128
MIMETYPE = b"application/hwp+zip"
CORE_MEMBERS = frozenset(
    {
        "mimetype",
        "version.xml",
        "settings.xml",
        "Contents/content.hpf",
        "Contents/header.xml",
        "META-INF/container.xml",
    }
)
ACTIVE_SUFFIXES = frozenset(
    {
        ".bat",
        ".cmd",
        ".com",
        ".dll",
        ".docx",
        ".exe",
        ".hwp",
        ".hwpx",
        ".jar",
        ".js",
        ".ole",
        ".ps1",
        ".vbs",
        ".zip",
    }
)
INLINE_EQUATION = re.compile(
    r"\$\$(?P<display>.+?)\$\$|(?<!\$)\$(?P<inline>[^\n$]+?)\$(?!\$)",
    re.DOTALL,
)


@dataclass(frozen=True)
class ContentTeamOutputExpectation:
    """One immutable Item Revision expected in one ordered HWPX section."""

    position: int
    item_revision_id: str
    draft: ContentTeamEditorialDraftContract
    images: tuple[ContentTeamImageSource, ...]


@dataclass(frozen=True)
class _PackageSnapshot:
    members: dict[str, bytes]
    names: tuple[str, ...]
    output_sha256: str
    uncompressed_bytes: int


_CellToken = tuple[str, str]
_CellTokens = tuple[_CellToken, ...]
_TableCells = tuple[tuple[_CellTokens, ...], ...]


@dataclass(frozen=True)
class _TableProjection:
    column_count: int
    row_count: int
    cells: _TableCells
    alignments: tuple[str, ...]

    def hash_value(self) -> dict[str, object]:
        return {
            "column_count": self.column_count,
            "row_count": self.row_count,
            "cells": self.cells,
            "alignments": self.alignments,
        }

    def is_layout_only(self) -> bool:
        tokens = tuple(token for row in self.cells for cell in row for token in cell)
        return not tokens or all(
            kind == "TEXT" and value in {"(가)", "(나)"} for kind, value in tokens
        )


def _fail(message: str) -> NoReturn:
    raise HwpxManagerError(HwpxManagerErrorCode.HWPX_RESULT_INVALID, message)


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
    )


def _stable_bytes(path: Path, expected_sha256: str) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        _fail("content-team HWPX output cannot be opened safely")
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= MAX_PACKAGE_BYTES
        ):
            _fail("content-team HWPX output metadata is unsafe")
        payload = bytearray()
        while len(payload) < before.st_size:
            chunk = os.read(descriptor, min(1024 * 1024, before.st_size - len(payload)))
            if not chunk:
                _fail("content-team HWPX output was truncated")
            payload.extend(chunk)
        if os.read(descriptor, 1):
            _fail("content-team HWPX output grew while reading")
        after = os.fstat(descriptor)
        if _stat_identity(before) != _stat_identity(after):
            _fail("content-team HWPX output changed while reading")
        actual_sha256 = f"sha256:{hashlib.sha256(payload).hexdigest()}"
        if actual_sha256 != expected_sha256:
            _fail("content-team HWPX output hash differs from the Builder result")
        return bytes(payload)
    finally:
        os.close(descriptor)


def _safe_member_name(name: str) -> None:
    path = PurePosixPath(name)
    if (
        not name
        or len(name) > MAX_FILENAME_LENGTH
        or "\x00" in name
        or "\\" in name
        or path.is_absolute()
        or ".." in path.parts
        or name.startswith("/")
    ):
        _fail("content-team HWPX contains an unsafe member name")


def _read_package(payload: bytes, expected_sha256: str) -> _PackageSnapshot:
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except (OSError, zipfile.BadZipFile):
        _fail("content-team HWPX is not a valid ZIP package")
    with archive:
        infos = archive.infolist()
        if not 6 <= len(infos) <= MAX_ENTRY_COUNT:
            _fail("content-team HWPX entry count is outside the bounded profile")
        names: set[str] = set()
        folded: set[str] = set()
        members: dict[str, bytes] = {}
        total = 0
        for info in infos:
            _safe_member_name(info.filename)
            if info.filename in names or info.filename.casefold() in folded:
                _fail("content-team HWPX contains duplicate or case-colliding members")
            names.add(info.filename)
            folded.add(info.filename.casefold())
            mode = info.external_attr >> 16
            file_type = stat.S_IFMT(mode)
            if file_type not in {0, stat.S_IFREG, stat.S_IFDIR} or stat.S_ISLNK(mode):
                _fail("content-team HWPX contains a special archive member")
            if info.file_size > MAX_MEMBER_BYTES:
                _fail("content-team HWPX member exceeds its size limit")
            total += info.file_size
            if total > MAX_UNCOMPRESSED_BYTES:
                _fail("content-team HWPX exceeds its uncompressed size limit")
            if info.file_size > 1024 and info.file_size / max(info.compress_size, 1) > (
                MAX_COMPRESSION_RATIO
            ):
                _fail("content-team HWPX exceeds its compression-ratio limit")
            try:
                data = b"" if info.is_dir() else archive.read(info)
            except (OSError, RuntimeError, zipfile.BadZipFile):
                _fail("content-team HWPX member cannot be read")
            members[info.filename] = data
        if not CORE_MEMBERS.issubset(names):
            _fail("content-team HWPX core package members are missing")
        if infos[0].filename != "mimetype" or infos[0].compress_type != zipfile.ZIP_STORED:
            _fail("content-team HWPX mimetype must be the first stored member")
        if members["mimetype"] != MIMETYPE:
            _fail("content-team HWPX mimetype differs from application/hwp+zip")
        actual_sha256 = f"sha256:{hashlib.sha256(payload).hexdigest()}"
        if actual_sha256 != expected_sha256:
            _fail("content-team HWPX snapshot hash changed during package parsing")
        return _PackageSnapshot(
            members=members,
            names=tuple(info.filename for info in infos),
            output_sha256=actual_sha256,
            uncompressed_bytes=total,
        )


def _parse_xml(data: bytes, member_name: str) -> ElementTree.Element:
    if not data or len(data) > MAX_XML_BYTES:
        _fail("content-team HWPX XML member size is invalid")
    upper = data.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        _fail("content-team HWPX XML declares DTD or entities")
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        _fail(f"content-team HWPX XML is malformed: {member_name}")
    stack: list[tuple[ElementTree.Element, int]] = [(root, 1)]
    while stack:
        element, depth = stack.pop()
        if depth > MAX_XML_DEPTH:
            _fail("content-team HWPX XML depth exceeds the bounded profile")
        stack.extend((child, depth + 1) for child in element)
    return root


def _resolve_member(base: str, reference: str) -> str:
    if not reference or reference.startswith("#"):
        return ""
    parsed = urlparse(reference)
    if parsed.scheme or parsed.netloc or reference.startswith("//"):
        _fail("content-team HWPX contains an external reference")
    root_names = {"BinData", "Contents", "META-INF", "Preview", "Scripts"}
    first = PurePosixPath(reference).parts[0] if PurePosixPath(reference).parts else ""
    resolved = (
        posixpath.normpath(reference)
        if first in root_names or reference in {"mimetype", "settings.xml", "version.xml"}
        else posixpath.normpath(posixpath.join(PurePosixPath(base).parent.as_posix(), reference))
    )
    if resolved.startswith("../") or resolved in {"..", "."} or resolved.startswith("/"):
        _fail("content-team HWPX reference escapes the package")
    return resolved


def _validate_xml_and_references(
    snapshot: _PackageSnapshot,
) -> tuple[dict[str, ElementTree.Element], tuple[str, ...], dict[str, str]]:
    roots: dict[str, ElementTree.Element] = {}
    names = set(snapshot.names)
    for name, data in snapshot.members.items():
        lower = name.casefold()
        suffix = PurePosixPath(lower).suffix
        if lower.startswith("scripts/") or lower.startswith(
            ("_xmlsignatures/", "meta-inf/signatures")
        ):
            _fail("content-team HWPX contains executable or signed content")
        if suffix in ACTIVE_SUFFIXES or (data.startswith(b"PK\x03\x04") and name != "mimetype"):
            _fail("content-team HWPX contains active or embedded package content")
        if lower.endswith((".xml", ".hpf")):
            roots[name] = _parse_xml(data, name)

    for name, root in roots.items():
        stack: list[tuple[ElementTree.Element, tuple[str, ...]]] = [(root, ())]
        while stack:
            element, ancestors = stack.pop()
            local = _local_name(element.tag).casefold()
            equation_script = local == "script" and "equation" in ancestors
            if ("script" in local and not equation_script) or "macro" in local or local == "ole":
                _fail("content-team HWPX XML contains active content")
            if "encrypt" in local:
                _fail("content-team HWPX XML contains encrypted content")
            for key, value in element.attrib.items():
                if _local_name(key).casefold() not in {
                    "full-path",
                    "fullpath",
                    "href",
                    "src",
                    "target",
                    "url",
                }:
                    continue
                target = _resolve_member(name, value)
                if target and target not in names:
                    _fail("content-team HWPX contains a dangling member reference")
            stack.extend((child, (*ancestors, local)) for child in element)

    content = roots.get("Contents/content.hpf")
    container = roots.get("META-INF/container.xml")
    if content is None or container is None:
        _fail("content-team HWPX package graph is incomplete")
    rootfiles = [
        next(
            (
                value
                for key, value in element.attrib.items()
                if _local_name(key).casefold() in {"full-path", "fullpath"}
            ),
            None,
        )
        for element in container.iter()
        if _local_name(element.tag).casefold() == "rootfile"
    ]
    if not rootfiles or rootfiles[0] != "Contents/content.hpf":
        _fail("content-team HWPX container rootfile differs")
    manifest_by_id: dict[str, str] = {}
    for element in content.iter():
        if _local_name(element.tag).casefold() != "item":
            continue
        attributes = {_local_name(key).casefold(): value for key, value in element.attrib.items()}
        identifier = attributes.get("id")
        reference = attributes.get("href")
        if not identifier or not reference or identifier in manifest_by_id:
            _fail("content-team HWPX package manifest identity is invalid")
        target = _resolve_member("Contents/content.hpf", reference)
        if target not in names:
            _fail("content-team HWPX package manifest target is missing")
        manifest_by_id[identifier] = target
    spine_ids = [
        next(
            (
                value
                for key, value in element.attrib.items()
                if _local_name(key).casefold() == "idref"
            ),
            None,
        )
        for element in content.iter()
        if _local_name(element.tag).casefold() == "itemref"
    ]
    if not spine_ids or any(value is None or value not in manifest_by_id for value in spine_ids):
        _fail("content-team HWPX spine contains an unresolved section")
    sections = tuple(
        target
        for value in spine_ids
        if (target := manifest_by_id[str(value)]).startswith("Contents/section")
        and target.endswith(".xml")
    )
    if sections != tuple(f"Contents/section{index}.xml" for index in range(len(sections))):
        _fail("content-team HWPX sections are not contiguous and ordered")
    if any(section not in roots for section in sections):
        _fail("content-team HWPX section XML is missing")
    return roots, sections, manifest_by_id


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", value)).strip()


def _normalized_equation(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", value))


def _compact_visible_text(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", value))


def _source_text_fragments(value: str) -> tuple[str, ...]:
    fragments: list[str] = []
    cursor = 0
    for match in INLINE_EQUATION.finditer(value):
        fragment = _compact_visible_text(value[cursor : match.start()])
        if fragment:
            fragments.append(fragment)
        cursor = match.end()
    fragment = _compact_visible_text(value[cursor:])
    if fragment:
        fragments.append(fragment)
    return tuple(fragments)


def _semantic_source_projection(
    draft: ContentTeamEditorialDraftContract,
) -> dict[str, object]:
    return {
        "stem": draft.stem,
        "bottom_stem": draft.bottom_stem,
        "inquiry": None if draft.inquiry is None else draft.inquiry.model_dump(mode="json"),
        "labeled_blocks": [value.model_dump(mode="json") for value in draft.labeled_blocks],
        "statements": [value.model_dump(mode="json") for value in draft.statements],
        "choices": [value.model_dump(mode="json") for value in draft.choices],
        "answer": draft.answer.model_dump(mode="json"),
        "explanations": draft.explanations.model_dump(mode="json"),
    }


def _semantic_text_values(draft: ContentTeamEditorialDraftContract) -> tuple[str, ...]:
    values: list[str] = [draft.stem, draft.bottom_stem]
    if draft.inquiry is not None:
        values.extend(
            value
            for value in (
                draft.inquiry.goal,
                draft.inquiry.procedure,
                draft.inquiry.result,
            )
            if value is not None
        )
    values.extend(block.content for block in draft.labeled_blocks)
    values.extend(statement.text for statement in draft.statements)
    values.extend(choice.text for choice in draft.choices)
    values.extend(
        (
            draft.explanations.authoring_intent,
            draft.explanations.concept_source,
            draft.explanations.correct_answer,
            draft.explanations.wrong_answer,
        )
    )
    return tuple(value for value in values if value)


def _source_cell_tokens(value: str) -> tuple[tuple[str, str], ...]:
    tokens: list[tuple[str, str]] = []
    cursor = 0
    for match in INLINE_EQUATION.finditer(value):
        text = _compact_visible_text(value[cursor : match.start()])
        if text:
            tokens.append(("TEXT", text))
        equation = match.group("display") or match.group("inline") or ""
        tokens.append(
            ("EQUATION", _normalized_equation(project_content_team_equation_script(equation)))
        )
        cursor = match.end()
    text = _compact_visible_text(value[cursor:])
    if text:
        tokens.append(("TEXT", text))
    return tuple(tokens)


def _output_cell_tokens(cell: ElementTree.Element) -> tuple[tuple[str, str], ...]:
    values: list[tuple[str, str]] = []
    stack: list[tuple[ElementTree.Element, tuple[str, ...]]] = [(cell, ())]
    ordered: list[tuple[ElementTree.Element, tuple[str, ...]]] = []
    while stack:
        element, ancestors = stack.pop()
        ordered.append((element, ancestors))
        local = _local_name(element.tag).casefold()
        stack.extend((child, (*ancestors, local)) for child in reversed(tuple(element)))
    for element, ancestors in ordered:
        local = _local_name(element.tag).casefold()
        if local == "t":
            # HWPX represents horizontally tabbed choices and some table text as
            # mixed XML content: text after ``hp:tab`` lives in the child tail,
            # not in ``hp:t.text``.  ``itertext`` is the XML-defined visible-text
            # order and keeps this verifier independent from Builder internals.
            text = _compact_visible_text("".join(element.itertext()))
            if text:
                if values and values[-1][0] == "TEXT":
                    values[-1] = ("TEXT", values[-1][1] + text)
                else:
                    values.append(("TEXT", text))
        elif local == "script" and "equation" in ancestors:
            values.append(("EQUATION", _normalized_equation(element.text or "")))
    return tuple(values)


def _direct_children(element: ElementTree.Element, local: str) -> tuple[ElementTree.Element, ...]:
    return tuple(child for child in element if _local_name(child.tag).casefold() == local)


def _paragraph_alignments(header: ElementTree.Element) -> dict[str, str]:
    result: dict[str, str] = {}
    for element in header.iter():
        if _local_name(element.tag).casefold() != "parapr":
            continue
        identifier = next(
            (value for key, value in element.attrib.items() if _local_name(key) == "id"), None
        )
        alignment = next(
            (
                next(
                    (
                        value
                        for key, value in child.attrib.items()
                        if _local_name(key).casefold() == "horizontal"
                    ),
                    None,
                )
                for child in element
                if _local_name(child.tag).casefold() == "align"
            ),
            None,
        )
        if identifier and alignment:
            result[identifier] = alignment.upper()
    return result


def _table_projection(
    table: ElementTree.Element,
    alignment_by_id: dict[str, str],
) -> _TableProjection | None:
    if any(
        descendant is not table and _local_name(descendant.tag).casefold() == "tbl"
        for descendant in table.iter()
    ):
        return None
    attributes = {_local_name(key): value for key, value in table.attrib.items()}
    try:
        row_count = int(attributes.get("rowCnt", ""))
        column_count = int(attributes.get("colCnt", ""))
    except ValueError:
        return None
    rows = _direct_children(table, "tr")
    if len(rows) != row_count or not 2 <= column_count <= 5 or not 2 <= row_count <= 101:
        return None
    values: list[tuple[tuple[tuple[str, str], ...], ...]] = []
    alignments: list[str] = []
    for row_index, row in enumerate(rows):
        cells = _direct_children(row, "tc")
        if len(cells) != column_count:
            return None
        values.append(tuple(_output_cell_tokens(cell) for cell in cells))
        for column, cell in enumerate(cells):
            paragraph = next(
                (item for item in cell.iter() if _local_name(item.tag).casefold() == "p"), None
            )
            if paragraph is None:
                return None
            paragraph_id = next(
                (
                    value
                    for key, value in paragraph.attrib.items()
                    if _local_name(key).casefold() == "parapridref"
                ),
                None,
            )
            actual = alignment_by_id.get(paragraph_id or "")
            if actual is None:
                return None
            if row_index == 0:
                alignments.append(actual)
            elif actual != alignments[column]:
                return None
    return _TableProjection(
        column_count=column_count,
        row_count=row_count,
        cells=tuple(values),
        alignments=tuple(alignments),
    )


def _source_table_projection(table: ContentTeamTable) -> _TableProjection:
    headers = tuple(table.headers)
    rows = tuple(tuple(row) for row in table.rows)
    alignments = tuple(table.alignments)
    alignment_map = {"default": "CENTER", "center": "CENTER", "left": "LEFT", "right": "RIGHT"}
    return _TableProjection(
        column_count=len(headers),
        row_count=1 + len(rows),
        cells=tuple(tuple(_source_cell_tokens(cell) for cell in row) for row in (headers, *rows)),
        alignments=tuple(alignment_map[value] for value in alignments),
    )


def _labeled_block_projection(
    table: ElementTree.Element,
) -> tuple[str, _CellTokens] | None:
    attributes = {_local_name(key).casefold(): value for key, value in table.attrib.items()}
    if attributes.get("rowcnt") != "2" or attributes.get("colcnt") != "1":
        return None
    rows = _direct_children(table, "tr")
    if len(rows) != 2:
        return None
    cells = tuple(_direct_children(row, "tc") for row in rows)
    if any(len(row_cells) != 1 for row_cells in cells):
        return None
    label_tokens = _output_cell_tokens(cells[0][0])
    if label_tokens not in (
        (("TEXT", "<자료>"),),
        (("TEXT", "<조건>"),),
    ):
        return None
    return label_tokens[0][1], _output_cell_tokens(cells[1][0])


def _binary_references(
    section: ElementTree.Element,
    manifest_by_id: dict[str, str],
    members: dict[str, bytes],
    expected_images: tuple[ContentTeamImageSource, ...],
) -> tuple[str, ...]:
    image_nodes: list[ElementTree.Element] = []
    identifiers: list[str] = []
    for element in section.iter():
        if _local_name(element.tag).casefold() != "img":
            continue
        for key, value in element.attrib.items():
            if _local_name(key).casefold() == "binaryitemidref":
                image_nodes.append(element)
                identifiers.append(value)
    if len(identifiers) != len(set(identifiers)):
        _fail("content-team HWPX section repeats a generated image reference")
    hashes: list[str] = []
    for identifier in identifiers:
        member = manifest_by_id.get(identifier)
        if member is None or member not in members:
            _fail("content-team HWPX image reference is dangling")
        hashes.append(f"sha256:{hashlib.sha256(members[member]).hexdigest()}")
    if len(image_nodes) != len(expected_images):
        _fail("content-team HWPX generated image count differs from the approved Item")
    if not image_nodes:
        return tuple(hashes)
    parent_by_child = {child: parent for parent in section.iter() for child in tuple(parent)}

    def ancestor(element: ElementTree.Element, name: str) -> ElementTree.Element:
        current = element
        while current in parent_by_child:
            current = parent_by_child[current]
            if _local_name(current.tag).casefold() == name:
                return current
        _fail("content-team HWPX generated image is outside its visual table")

    def address(cell: ElementTree.Element) -> tuple[int, int]:
        address_nodes = _direct_children(cell, "celladdr")
        if len(address_nodes) != 1:
            _fail("content-team HWPX generated image cell address is invalid")
        attributes = {
            _local_name(key).casefold(): value for key, value in address_nodes[0].attrib.items()
        }
        try:
            return int(attributes["rowaddr"]), int(attributes["coladdr"])
        except (KeyError, ValueError):
            _fail("content-team HWPX generated image cell address is invalid")

    image_tables = tuple(ancestor(node, "tbl") for node in image_nodes)
    image_cells = tuple(ancestor(node, "tc") for node in image_nodes)
    if len(set(image_tables)) != 1:
        _fail("content-team HWPX generated images are split across visual tables")
    visual_table = image_tables[0]
    expected_addresses = tuple((0, image.visual_ordinal) for image in expected_images)
    if tuple(address(cell) for cell in image_cells) != expected_addresses:
        _fail("content-team HWPX generated image placement differs")
    rows = _direct_children(visual_table, "tr")
    labels = tuple(image.label for image in expected_images)
    if len(expected_images) == 1:
        if labels != ("",) or len(rows) != 1:
            _fail("content-team HWPX single image must not have a panel label")
    else:
        if labels != ("(가)", "(나)") or len(rows) != 2:
            _fail("content-team HWPX paired image labels differ from the approved Item")
        label_cells = _direct_children(rows[1], "tc")
        if len(label_cells) != 2:
            _fail("content-team HWPX paired image label row is invalid")
        observed_labels = tuple(
            _normalized_text(
                "".join(
                    element.text or ""
                    for element in cell.iter()
                    if _local_name(element.tag).casefold() == "t"
                )
            )
            for cell in label_cells
        )
        if observed_labels != labels:
            _fail("content-team HWPX paired image labels are not editable text")
    return tuple(hashes)


def _accept_item(
    *,
    section: ElementTree.Element,
    header: ElementTree.Element,
    manifest_by_id: dict[str, str],
    members: dict[str, bytes],
    expectation: ContentTeamOutputExpectation,
) -> ContentTeamAcceptedItemV1:
    draft = expectation.draft
    try:
        validate_content_team_image_bindings(draft, expectation.images)
    except ValueError:
        _fail("content-team output expectation image bindings are invalid")
    alignment_by_id = _paragraph_alignments(header)
    observed_tables = tuple(
        (element, candidate)
        for element in section.iter()
        if _local_name(element.tag).casefold() == "tbl"
        and (candidate := _table_projection(element, alignment_by_id)) is not None
    )
    accepted_tables: list[ContentTeamAcceptedTableV1] = []
    matched_table_indexes: set[int] = set()
    matched_table_elements: list[ElementTree.Element] = []
    search_start = 0
    for visual_ordinal, visual in enumerate(draft.visuals):
        if visual.kind != "TABLE":
            continue
        expected = _source_table_projection(visual)
        match_index = next(
            (
                index
                for index in range(search_start, len(observed_tables))
                if observed_tables[index][1] == expected
            ),
            None,
        )
        if match_index is None:
            _fail("content-team HWPX native table differs from the approved Item")
        matched_table_indexes.add(match_index)
        matched_table_elements.append(observed_tables[match_index][0])
        search_start = match_index + 1
        accepted_tables.append(
            ContentTeamAcceptedTableV1(
                visual_ordinal=visual_ordinal,
                label=visual.label,
                column_count=len(visual.headers),
                row_count=1 + len(visual.rows),
                table_sha256=content_sha256(expected.hash_value()),
            )
        )
    if any(
        index not in matched_table_indexes and not table.is_layout_only()
        for index, (_element, table) in enumerate(observed_tables)
    ):
        _fail("content-team HWPX contains an unbound native table")
    if len(matched_table_elements) == 2:
        parent_by_child = {child: parent for parent in section.iter() for child in tuple(parent)}

        def ancestor(element: ElementTree.Element, name: str) -> ElementTree.Element:
            current = element
            while current in parent_by_child:
                current = parent_by_child[current]
                if _local_name(current.tag).casefold() == name:
                    return current
            _fail("content-team HWPX paired native table has no visual container")

        containers = tuple(ancestor(table, "tbl") for table in matched_table_elements)
        cells = tuple(ancestor(table, "tc") for table in matched_table_elements)
        if len(set(containers)) != 1:
            _fail("content-team HWPX paired native tables use different visual containers")
        rows = _direct_children(containers[0], "tr")
        if len(rows) != 2 or any(len(_direct_children(row, "tc")) != 2 for row in rows):
            _fail("content-team HWPX paired native table layout is invalid")

        def cell_address(cell: ElementTree.Element) -> tuple[int, int]:
            nodes = _direct_children(cell, "celladdr")
            if len(nodes) != 1:
                _fail("content-team HWPX paired native table cell address is invalid")
            attributes = {
                _local_name(key).casefold(): value for key, value in nodes[0].attrib.items()
            }
            try:
                return int(attributes["rowaddr"]), int(attributes["coladdr"])
            except (KeyError, ValueError):
                _fail("content-team HWPX paired native table cell address is invalid")

        if tuple(cell_address(cell) for cell in cells) != ((0, 0), (0, 1)):
            _fail("content-team HWPX paired native table order differs")
        label_cells = _direct_children(rows[1], "tc")
        observed_labels = tuple(
            _normalized_text(
                "".join(
                    element.text or ""
                    for element in cell.iter()
                    if _local_name(element.tag).casefold() == "t"
                )
            )
            for cell in label_cells
        )
        if observed_labels != ("(가)", "(나)"):
            _fail("content-team HWPX paired native table labels are not editable text")

    expected_images = tuple(image.sha256 for image in expectation.images)
    actual_images = _binary_references(
        section,
        manifest_by_id,
        members,
        expectation.images,
    )
    if actual_images != expected_images:
        _fail("content-team HWPX generated image bytes differ from the pinned Item images")
    accepted_images = tuple(
        ContentTeamAcceptedImageV1(
            visual_ordinal=image.visual_ordinal,
            label=image.label,
            sha256=image.sha256,
        )
        for image in expectation.images
    )
    observed_labeled_blocks = tuple(
        labeled_projection
        for table in section.iter()
        if _local_name(table.tag).casefold() == "tbl"
        and (labeled_projection := _labeled_block_projection(table)) is not None
    )
    expected_labeled_blocks = tuple(
        (
            "<자료>" if block.kind == "DATA" else "<조건>",
            _source_cell_tokens(block.content),
        )
        for block in draft.labeled_blocks
    )
    if observed_labeled_blocks != expected_labeled_blocks:
        _fail("content-team HWPX labeled material differs from the approved Item")
    section_text = _normalized_text(
        " ".join(
            "".join(element.itertext())
            for element in section.iter()
            if _local_name(element.tag).casefold() == "t"
        )
    )
    if "그림 삽입" in section_text:
        _fail("content-team HWPX still contains an image placeholder")
    compact_section_text = _compact_visible_text(section_text)
    if any(
        fragment not in compact_section_text
        for value in _semantic_text_values(draft)
        for fragment in _source_text_fragments(value)
    ):
        _fail("content-team HWPX visible text differs from the approved Item")
    equation_nodes = tuple(
        element for element in section.iter() if _local_name(element.tag).casefold() == "equation"
    )
    observed_equations = tuple(
        _normalized_equation(script.text or "")
        for equation in equation_nodes
        for script in equation.iter()
        if _local_name(script.tag).casefold() == "script"
    )
    if len(observed_equations) != len(equation_nodes):
        _fail("content-team HWPX equation script cardinality is invalid")
    expected_equations = tuple(
        _normalized_equation(project_content_team_equation_script(value))
        for value in draft.equation_sources
    )
    equation_count = len(equation_nodes)
    if equation_count != len(draft.equation_sources):
        _fail("content-team HWPX equation count differs from the approved Item")
    if Counter(observed_equations) != Counter(expected_equations):
        _fail("content-team HWPX equations differ from the approved Item")
    tables = tuple(accepted_tables)
    semantic_text_sha256 = content_sha256(_semantic_source_projection(draft))
    structure_projection = {
        "position": expectation.position,
        "item_revision_id": expectation.item_revision_id,
        "visual_layout": draft.visual_layout,
        "tables": [value.model_dump(mode="json") for value in tables],
        "images": [value.model_dump(mode="json") for value in accepted_images],
        "equation_count": equation_count,
        "labeled_block_count": len(draft.labeled_blocks),
        "semantic_text_sha256": semantic_text_sha256,
    }
    return ContentTeamAcceptedItemV1(
        position=expectation.position,
        item_revision_id=expectation.item_revision_id,
        visual_layout=draft.visual_layout,
        tables=tables,
        images=accepted_images,
        equation_count=equation_count,
        labeled_block_count=len(draft.labeled_blocks),
        semantic_text_sha256=semantic_text_sha256,
        structure_sha256=content_sha256(structure_projection),
    )


def verify_content_team_output(
    path: Path,
    *,
    expected_sha256: str,
    expectations: tuple[ContentTeamOutputExpectation, ...],
) -> ContentTeamOutputAcceptanceV1:
    """Validate stable HWPX bytes against ordered approved Item expectations."""

    if not expectations or len(expectations) > 200:
        _fail("content-team output expectation cardinality is invalid")
    if tuple(value.position for value in expectations) != tuple(range(1, len(expectations) + 1)):
        _fail("content-team output expectations must be contiguous and ordered")
    payload = _stable_bytes(path, expected_sha256)
    snapshot = _read_package(payload, expected_sha256)
    roots, sections, manifest_by_id = _validate_xml_and_references(snapshot)
    if len(sections) != len(expectations):
        _fail("content-team HWPX section count differs from the approved Item set")
    header = roots["Contents/header.xml"]
    items = tuple(
        _accept_item(
            section=roots[section_name],
            header=header,
            manifest_by_id=manifest_by_id,
            members=snapshot.members,
            expectation=expectation,
        )
        for section_name, expectation in zip(sections, expectations, strict=True)
    )
    projection = {
        "schema_version": "content-team-output-acceptance/1.0",
        "output_sha256": snapshot.output_sha256,
        "package_entry_count": len(snapshot.names),
        "uncompressed_bytes": snapshot.uncompressed_bytes,
        "section_names": sections,
        "items": [item.model_dump(mode="json") for item in items],
    }
    receipt = ContentTeamOutputAcceptanceV1(
        output_sha256=snapshot.output_sha256,
        package_entry_count=len(snapshot.names),
        uncompressed_bytes=snapshot.uncompressed_bytes,
        section_names=sections,
        items=items,
        acceptance_sha256=content_sha256(projection),
    )
    return receipt
