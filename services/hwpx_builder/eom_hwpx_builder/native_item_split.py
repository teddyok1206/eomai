"""Split pinned direct paragraph ranges without rewriting editable native content.

The original package is parsed once per exam. Small style definitions remain shared
by value inside each independent output; only referenced binary members are copied.
No PDF, model, DB, network or NAS adapter is involved.
"""

from __future__ import annotations

import copy
import os
import re
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

from eom_hwpx_contracts.native_item_split import (
    NativeItemCounts,
    NativeItemSelection,
    NativeItemSplitPlan,
    NativeItemSplitResult,
    NativeParagraphRange,
    SourceRole,
    native_split_contract_sha256,
)
from eom_hwpx_contracts.native_resource_rules import FONT_LANGUAGES, REFERENCES, ZERO_SENTINELS
from lxml import etree  # type: ignore[import-untyped]

from eom_hwpx_builder.analyzer import analyze_package, resolve_part
from eom_hwpx_builder.archive import FIXED_ZIP_TIMESTAMP, read_package
from eom_hwpx_builder.curated_package_merge import (
    MASTERPAGE,
    NativeDocument,
    NativeDocumentReadProfile,
    parse_native_document,
)
from eom_hwpx_builder.curated_resources import attribute, catalog_rows, tree_value
from eom_hwpx_builder.util import sha256_bytes, sha256_file
from eom_hwpx_builder.xmlsafe import local_name

_NUMBER = re.compile(r"^\s*([1-9][0-9]{0,4})\.(?:\s|$)")
_SECTION = re.compile(r"^Contents/section[0-9]+\.xml$")
_CONTENT = "Contents/content.hpf"
_HEADER = "Contents/header.xml"


class NativeItemSplitError(ValueError):
    """Stable local adapter error, with no untrusted source text in its message."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise NativeItemSplitError(code)


def _xml(root: etree._Element) -> bytes:
    return cast(bytes, etree.tostring(root, encoding="utf-8", xml_declaration=True))


def _subtree_hash(nodes: tuple[etree._Element, ...]) -> str:
    return native_split_contract_sha256(tuple(tree_value(node) for node in nodes))


def _direct_text(paragraph: etree._Element) -> str:
    # A table/text-box paragraph owns its own text. Its numbers are never headings.
    return "".join(
        "".join(text.itertext())
        for run in paragraph
        if local_name(run.tag) == "run"
        for text in run
        if local_name(text.tag) == "t"
    )


def _paragraphs(document: NativeDocument) -> dict[str, tuple[etree._Element, ...]]:
    result = {}
    for member, root in document.sections:
        children = tuple(root)
        if any(local_name(child.tag) != "p" for child in children):
            _fail("NATIVE_ITEM_SPLIT_SECTION_CHILD_UNSUPPORTED")
        result[member] = children
    return result


def _load(source: Path, expected_sha256: str) -> NativeDocument:
    if source.is_symlink() or not source.is_file() or sha256_file(source) != expected_sha256:
        _fail("NATIVE_ITEM_SPLIT_SOURCE_CHANGED")
    package = read_package(source)
    if package.package_sha256 != expected_sha256 or sha256_file(source) != expected_sha256:
        _fail("NATIVE_ITEM_SPLIT_SOURCE_CHANGED")
    mimetype = package.by_name().get("mimetype")
    if mimetype is None or mimetype.data != b"application/hwp+zip":
        _fail("NATIVE_ITEM_SPLIT_SOURCE_FORMAT_INVALID")
    document = parse_native_document(package, profile=NativeDocumentReadProfile.NATIVE_SPLIT_V1)
    _require_safe_references((*[root for _, root in document.sections], document.header), document)
    return document


def _require_safe_references(
    roots: tuple[etree._Element, ...], document: NativeDocument
) -> set[str]:
    """Use the existing native reference vocabulary, without relocating original IDs."""
    masterpages = {attribute(root, "id"): (member, root) for member, root in document.masterpages}
    roots = (*roots, *(root for _, root in _selected_masterpages(roots, document)))
    resources = catalog_rows(document.header)
    objects = {
        value
        for root in roots
        for node in root.iter()
        if (value := attribute(node, "id")) is not None
    }
    field_beginnings = {
        value
        for root in roots
        for node in root.iter()
        if local_name(node.tag) == "fieldBegin" and (value := attribute(node, "id")) is not None
    }
    used: set[str] = set()
    entries = document.package.by_name()
    excluded_members = {part.member_path for part in document.excluded_parts}
    binary_members = {member: identifier for identifier, (member, _) in document.binaries.items()}
    for root in roots:
        for node in root.iter():
            tag = local_name(node.tag)
            if tag.casefold() == "ole" or "macro" in tag.casefold():
                _fail("NATIVE_ITEM_SPLIT_ACTIVE_CONTENT")
            if "script" in tag.casefold() and not any(
                local_name(parent.tag) == "equation" for parent in node.iterancestors()
            ):
                _fail("NATIVE_ITEM_SPLIT_ACTIVE_CONTENT")
            for key, value in node.attrib.items():
                name = local_name(key).casefold()
                catalog = REFERENCES.get(name)
                if tag == "fontRef" and name in FONT_LANGUAGES:
                    catalog = "font:" + FONT_LANGUAGES[name]
                elif tag == "heading" and name == "idref":
                    catalog = {"NUMBER": "numberings", "BULLET": "bullets"}.get(
                        attribute(node, "type") or ""
                    )
                if catalog:
                    if tag == "paraHead" and name == "charpridref" and value == "4294967295":
                        continue
                    if value not in resources.get(catalog, {}) and not (
                        value == "0" and catalog in ZERO_SENTINELS
                    ):
                        _fail("NATIVE_ITEM_SPLIT_RESOURCE_REFERENCE_MISSING")
                elif name == "binaryitemidref":
                    if not value and tag != "img":
                        continue
                    if value not in document.binaries:
                        _fail("NATIVE_ITEM_SPLIT_BINARY_REFERENCE_MISSING")
                    used.add(value)
                elif name == "beginidref":
                    if value not in field_beginnings:
                        _fail("NATIVE_ITEM_SPLIT_FIELD_REFERENCE_MISSING")
                elif tag == "masterPage" and name == "idref":
                    if value not in masterpages:
                        _fail("NATIVE_ITEM_SPLIT_MASTERPAGE_REFERENCE_MISSING")
                elif name in {"linklistidref", "linklistnextidref"}:
                    if value not in {"0", "-1", ""}:
                        _fail("NATIVE_ITEM_SPLIT_LINKED_FRAME_UNSUPPORTED")
                elif name.endswith("idref") and value not in {"0", "-1", ""}:
                    _fail("NATIVE_ITEM_SPLIT_REFERENCE_UNSUPPORTED")
                if name in {"href", "src", "target", "url"} and value:
                    parsed = urlsplit(value)
                    if parsed.scheme or parsed.netloc or value.startswith(("/", "\\")):
                        _fail("NATIVE_ITEM_SPLIT_EXTERNAL_REFERENCE")
                    if value.startswith("#"):
                        if value[1:] not in objects:
                            _fail("NATIVE_ITEM_SPLIT_FIELD_REFERENCE_MISSING")
                    else:
                        target = resolve_part(
                            _HEADER if root is document.header else "Contents/section0.xml", value
                        )
                        if target not in entries:
                            _fail("NATIVE_ITEM_SPLIT_PACKAGE_REFERENCE_MISSING")
                        if target in excluded_members:
                            _fail("NATIVE_ITEM_SPLIT_EMPTY_SCRIPT_REFERENCED_BY_CONTENT")
                        binary = binary_members.get(target)
                        if binary is not None:
                            used.add(binary)
    return used


def _selected_masterpages(
    roots: tuple[etree._Element, ...], document: NativeDocument
) -> tuple[tuple[str, etree._Element], ...]:
    """One indexed closure, retaining source order and the original auxiliary XML bytes."""
    by_id = {attribute(root, "id"): (member, root) for member, root in document.masterpages}
    selected: set[str] = set()
    pending = list(roots)
    for root in pending:
        for node in root.iter():
            if local_name(node.tag) != "masterPage" or attribute(node, "idref") is None:
                continue
            key = attribute(node, "idref") or ""
            if key not in by_id:
                _fail("NATIVE_ITEM_SPLIT_MASTERPAGE_REFERENCE_MISSING")
            if key not in selected:
                selected.add(key)
                pending.append(by_id[key][1])
    return tuple(
        (member, root) for member, root in document.masterpages if attribute(root, "id") in selected
    )


def _discover(
    document: NativeDocument, *, source_role: SourceRole, expected_numbers: tuple[int, ...]
) -> NativeItemSplitPlan:
    if (
        not expected_numbers
        or len(set(expected_numbers)) != len(expected_numbers)
        or expected_numbers != tuple(sorted(expected_numbers))
        or any(type(number) is not int or not 1 <= number <= 10000 for number in expected_numbers)
    ):
        _fail("NATIVE_ITEM_SPLIT_EXPECTED_NUMBERS_INVALID")
    paragraphs = _paragraphs(document)
    flattened = tuple(
        (member, index, paragraph)
        for member, _ in document.sections
        for index, paragraph in enumerate(paragraphs[member])
    )
    headings = tuple(
        (int(match.group(1)), position)
        for position, (_, _, paragraph) in enumerate(flattened)
        if (match := _NUMBER.match(_direct_text(paragraph))) is not None
    )
    if tuple(number for number, _ in headings) != expected_numbers:
        _fail("NATIVE_ITEM_SPLIT_NUMBER_COVERAGE_INVALID")
    items = []
    for ordinal, (number, start) in enumerate(headings):
        end = headings[ordinal + 1][1] if ordinal + 1 < len(headings) else len(flattened)
        grouped: dict[str, list[int]] = {}
        for member, index, _ in flattened[start:end]:
            grouped.setdefault(member, []).append(index)
        ranges = tuple(
            NativeParagraphRange(
                section_member=member,
                start_paragraph=indices[0],
                end_paragraph=indices[-1] + 1,
                subtree_sha256=_subtree_hash(paragraphs[member][indices[0] : indices[-1] + 1]),
            )
            for member, indices in grouped.items()
        )
        items.append(NativeItemSelection(item_number=number, ranges=ranges))
    value = {
        "schema_version": "native-item-split-plan/1.0",
        "profile": "DIRECT_NATIVE_PARAGRAPHS_V1",
        "source_sha256": document.package.package_sha256,
        "source_role": source_role,
        "items": [item.model_dump(mode="json") for item in items],
    }
    return NativeItemSplitPlan.model_validate(
        {**value, "plan_sha256": native_split_contract_sha256(value)}
    )


def discover_native_item_split(
    source: Path,
    *,
    expected_source_sha256: str,
    source_role: SourceRole,
    expected_numbers: tuple[int, ...] = tuple(range(1, 26)),
) -> NativeItemSplitPlan:
    return _discover(
        _load(source, expected_source_sha256),
        source_role=source_role,
        expected_numbers=expected_numbers,
    )


def _section_contexts(
    paragraphs: tuple[etree._Element, ...], starts: set[int]
) -> dict[int, etree._Element | None]:
    """One ordered scan carries geometry to all requested boundaries, not I * N scans."""
    controls: dict[str, tuple[etree._Element, etree._Element, etree._Element]] = {}
    result: dict[int, etree._Element | None] = {}
    for index, paragraph in enumerate(paragraphs):
        own: set[str] = set()
        for run in paragraph:
            if local_name(run.tag) != "run":
                continue
            for node in run:
                if local_name(node.tag) in {"secPr", "colPr"}:
                    controls[local_name(node.tag)] = (paragraph, run, node)
                    own.add(local_name(node.tag))
                elif local_name(node.tag) == "ctrl":
                    for child in node:
                        if local_name(child.tag) == "colPr":
                            own.add("colPr")
                            # Retain the ctrl shell so the original geometry remains valid.
                            wrapper = copy.deepcopy(node)
                            for sibling in tuple(wrapper):
                                if local_name(sibling.tag) != "colPr":
                                    wrapper.remove(sibling)
                            controls["colPr"] = (paragraph, run, wrapper)
        if index not in starts:
            continue
        needed = [entry for name, entry in controls.items() if name not in own]
        context = None
        if needed:
            original = needed[0][0]
            context = etree.Element(
                original.tag, attrib=dict(original.attrib), nsmap=original.nsmap
            )
            # Paragraph IDs are local layout identities, not logical Item/revision IDs.
            context.set("id", "0")
            for _, source_run, node in needed:
                run = etree.SubElement(context, source_run.tag, attrib=dict(source_run.attrib))
                run.append(copy.deepcopy(node))
        result[index] = context
    return result


def _write_package(payloads: dict[str, bytes], output: Path) -> None:
    if output.exists() or output.is_symlink() or output.parent.is_symlink():
        _fail("NATIVE_ITEM_SPLIT_OUTPUT_EXISTS")
    with tempfile.NamedTemporaryFile(
        prefix=".native-split-", dir=output.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
    try:
        with zipfile.ZipFile(temporary, "w", allowZip64=False) as archive:
            for member in ("mimetype", *sorted(set(payloads) - {"mimetype"})):
                info = zipfile.ZipInfo(member, FIXED_ZIP_TIMESTAMP)
                info.compress_type = (
                    zipfile.ZIP_STORED if member == "mimetype" else zipfile.ZIP_DEFLATED
                )
                info.external_attr = 0o600 << 16
                info.create_system = 3
                archive.writestr(info, payloads[member])
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.link(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def _split_item(
    document: NativeDocument,
    paragraphs: dict[str, tuple[etree._Element, ...]],
    section_contexts: dict[str, dict[int, etree._Element | None]],
    item: NativeItemSelection,
    plan: NativeItemSplitPlan,
    output: Path,
) -> NativeItemSplitResult:
    selected: list[etree._Element] = []
    contexts = []
    sections = []
    originals = dict(document.sections)
    for part in item.ranges:
        source_paragraphs = paragraphs[part.section_member]
        nodes = source_paragraphs[part.start_paragraph : part.end_paragraph]
        if not nodes or _subtree_hash(nodes) != part.subtree_sha256:
            _fail("NATIVE_ITEM_SPLIT_RANGE_CHANGED")
        selected.extend(nodes)
        section = copy.deepcopy(originals[part.section_member])
        for child in tuple(section):
            section.remove(child)
        context = section_contexts[part.section_member][part.start_paragraph]
        if context is not None:
            section.append(copy.deepcopy(context))
            contexts.append(context)
        for paragraph in nodes:
            section.append(copy.deepcopy(paragraph))
        sections.append((part.section_member, section))
    header = copy.deepcopy(document.header)
    header.set("secCnt", str(len(sections)))
    roots = tuple(root for _, root in sections)
    masterpages = _selected_masterpages((*roots, header), document)
    selected_master_members = {member for member, _ in masterpages}
    used = _require_safe_references((*roots, header), document)
    entries = document.package.by_name()
    excluded_members = {part.member_path for part in document.excluded_parts}
    payloads = {
        name: entry.data
        for name, entry in entries.items()
        if not (
            name.startswith(("BinData/", "Preview/"))
            or _SECTION.fullmatch(name)
            or MASTERPAGE.fullmatch(name)
            or name in excluded_members
            or name in {_HEADER, _CONTENT, "META-INF/container.rdf", "META-INF/manifest.xml"}
        )
    }
    content = copy.deepcopy(document.content)
    manifest = next(node for node in content.iter() if local_name(node.tag) == "manifest")
    spine = next(node for node in content.iter() if local_name(node.tag) == "spine")
    selected_sections = {member for member, _ in sections}
    kept_ids: set[str] = set()
    for node in tuple(manifest):
        identifier = attribute(node, "id") or ""
        member = resolve_part(_CONTENT, attribute(node, "href") or "")
        keep = not member.startswith("Preview/")
        if member in excluded_members:
            keep = False
        if member.startswith("BinData/"):
            keep = identifier in used
        elif _SECTION.fullmatch(member):
            keep = member in selected_sections
        elif MASTERPAGE.fullmatch(member):
            keep = member in selected_master_members
        if keep:
            kept_ids.add(identifier)
        else:
            manifest.remove(node)
    for node in tuple(spine):
        if attribute(node, "idref") not in kept_ids:
            spine.remove(node)
    payloads[_CONTENT], payloads[_HEADER] = _xml(content), _xml(header)
    for member, section in sections:
        payloads[member] = _xml(section)
    for member, _ in masterpages:
        payloads[member] = entries[member].data
    binaries = []
    for identifier in sorted(used):
        member, _ = document.binaries[identifier]
        payloads[member] = entries[member].data
        binaries.append(sha256_bytes(entries[member].data))
    _write_package(payloads, output)
    try:
        actual = parse_native_document(
            read_package(output), profile=NativeDocumentReadProfile.NATIVE_SPLIT_V1
        )
        actual_entries = actual.package.by_name()
        if any(name.startswith("Scripts/") for name in actual_entries):
            _fail("NATIVE_ITEM_SPLIT_SCRIPT_EXCLUSION_FAILED")
        if {member for member, _ in actual.masterpages} != selected_master_members or any(
            actual_entries[member].data != entries[member].data
            for member in selected_master_members
        ):
            _fail("NATIVE_ITEM_SPLIT_MASTERPAGE_PRESERVATION_FAILED")
        actual_paragraphs: list[etree._Element] = []
        actual_contexts = []
        for index, (_, root) in enumerate(actual.sections):
            part = item.ranges[index]
            expected_context = section_contexts[part.section_member][part.start_paragraph]
            children = tuple(root)
            if expected_context is not None:
                actual_contexts.append(children[0])
                children = children[1:]
            actual_paragraphs.extend(children)
        if tuple(_subtree_hash((node,)) for node in actual_paragraphs) != tuple(
            _subtree_hash((node,)) for node in selected
        ) or tuple(_subtree_hash((node,)) for node in actual_contexts) != tuple(
            _subtree_hash((node,)) for node in contexts
        ):
            _fail("NATIVE_ITEM_SPLIT_PRESERVATION_FAILED")
        _require_safe_references((*[root for _, root in actual.sections], actual.header), actual)
        analysis = analyze_package(output)
        if analysis.external_links or analysis.active_content:
            _fail("NATIVE_ITEM_SPLIT_EXTERNAL_OR_ACTIVE_CONTENT")
        if any(ref["target"] not in payloads for ref in analysis.internal_references):
            _fail("NATIVE_ITEM_SPLIT_PACKAGE_REFERENCE_MISSING")
        counts = Counter(
            local_name(node.tag) for paragraph in selected for node in paragraph.iter()
        )
        return NativeItemSplitResult(
            source_sha256=plan.source_sha256,
            plan_sha256=plan.plan_sha256,
            source_role=plan.source_role,
            item_number=item.item_number,
            ranges=item.ranges,
            paragraph_sha256=tuple(_subtree_hash((node,)) for node in selected),
            context_sha256=tuple(_subtree_hash((node,)) for node in contexts),
            binary_sha256=tuple(binaries),
            excluded_source_parts=document.excluded_parts,
            counts=NativeItemCounts(
                paragraphs=counts["p"],
                tables=counts["tbl"],
                equations=counts["equation"],
                pictures=counts["pic"],
            ),
            output_sha256=actual.package.package_sha256,
            output_size_bytes=output.stat().st_size,
        )
    except BaseException:
        # Only this invocation's exclusively-created, not-yet-accepted output is removed.
        output.unlink(missing_ok=True)
        raise


def split_native_exam(
    source: Path, output_directory: Path, *, plan: NativeItemSplitPlan
) -> tuple[NativeItemSplitResult, ...]:
    """Materialize each selected Item as a new editable package; never overwrite files."""
    plan = NativeItemSplitPlan.model_validate(plan.model_dump(mode="json"))
    document = _load(source, plan.source_sha256)
    current = _discover(
        document,
        source_role=plan.source_role,
        expected_numbers=tuple(item.item_number for item in plan.items),
    )
    if current != plan:
        _fail("NATIVE_ITEM_SPLIT_PLAN_CHANGED")
    output_directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    paragraphs = _paragraphs(document)
    starts: dict[str, set[int]] = {member: set() for member in paragraphs}
    for item in plan.items:
        for part in item.ranges:
            starts[part.section_member].add(part.start_paragraph)
    contexts = {
        member: _section_contexts(nodes, starts[member]) for member, nodes in paragraphs.items()
    }
    results = tuple(
        _split_item(
            document,
            paragraphs,
            contexts,
            item,
            plan,
            output_directory / f"{item.item_number:03d}.hwpx",
        )
        for item in plan.items
    )
    if sha256_file(source) != plan.source_sha256:
        _fail("NATIVE_ITEM_SPLIT_SOURCE_CHANGED")
    return results
