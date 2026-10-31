"""Native HWPX resource relocation; allocate identities before following style cycles."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import NoReturn

from lxml import etree  # type: ignore[import-untyped]

from eom_hwpx_builder.errors import HwpxError, HwpxErrorCode
from eom_hwpx_builder.xmlsafe import local_name

CATALOGS = frozenset(
    (
        "borderFills",
        "charProperties",
        "tabProperties",
        "numberings",
        "bullets",
        "paraProperties",
        "styles",
        "memoProperties",
    )
)
REFERENCES = {
    "borderfillidref": "borderFills",
    "charpridref": "charProperties",
    "parapridref": "paraProperties",
    "tabpridref": "tabProperties",
    "styleidref": "styles",
    "charstyleidref": "styles",
    "nextstyleidref": "styles",
    "outlineshapeidref": "numberings",
    "memoshapeidref": "memoProperties",
}
FONT_LANGUAGES = {
    name.casefold(): name
    for name in ("HANGUL", "LATIN", "HANJA", "JAPANESE", "OTHER", "SYMBOL", "USER")
}
ZERO_SENTINELS = frozenset(("borderFills", "numberings", "bullets", "memoProperties"))
OBJECTS = frozenset(
    (
        "tbl",
        "pic",
        "line",
        "rect",
        "ellipse",
        "arc",
        "polygon",
        "curve",
        "ole",
        "container",
        "equation",
        "video",
        "connectLine",
        "fieldBegin",
    )
)


def fail(message: str) -> NoReturn:
    raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSUPPORTED, message)


def attribute(node: etree._Element, name: str) -> str | None:
    return next(
        (
            str(value)
            for key, value in node.attrib.items()
            if local_name(key).casefold() == name.casefold()
        ),
        None,
    )


def set_attribute(node: etree._Element, name: str, value: str) -> None:
    key = next((key for key in node.attrib if local_name(key).casefold() == name.casefold()), name)
    node.attrib[key] = value


def tree_value(node: etree._Element) -> tuple[object, ...]:
    """Compare XML meaning without namespace-prefix/attribute-order serialization noise."""
    return (
        node.tag,
        tuple(sorted(node.attrib.items())),
        node.text or "",
        node.tail or "",
        tuple(tree_value(child) for child in node if isinstance(child.tag, str)),
    )


def resource_catalogs(header: etree._Element) -> dict[str, etree._Element]:
    ref_lists = [child for child in header if local_name(child.tag) == "refList"]
    if len(ref_lists) != 1:
        fail("curated header must contain one resource list")
    result = {}
    for catalog in ref_lists[0]:
        name = local_name(catalog.tag)
        if name == "fontfaces":
            for face in catalog:
                lang = attribute(face, "lang")
                key = "font:" + (lang or "")
                if lang not in FONT_LANGUAGES.values() or key in result:
                    fail("curated font language is missing or repeated")
                result[key] = face
        elif name in CATALOGS:
            if name in result:
                fail("curated resource catalog is repeated")
            result[name] = catalog
        elif len(catalog):
            fail("curated header resource catalog is not yet supported: " + name)
    return result


def catalog_rows(header: etree._Element) -> dict[str, dict[str, etree._Element]]:
    result = {}
    for name, catalog in resource_catalogs(header).items():
        rows = {}
        for row in catalog:
            identifier = attribute(row, "id")
            if (
                identifier is None
                or not identifier.isascii()
                or not identifier.isdecimal()
                or identifier in rows
            ):
                fail("curated header resource ID is missing or repeated")
            rows[identifier] = row
        result[name] = rows
    return result


@dataclass(frozen=True)
class ResourceRelocation:
    resources: dict[str, dict[str, str]]
    binaries: dict[str, str]
    objects: dict[str, str]

    def inverse(self) -> ResourceRelocation:
        return ResourceRelocation(
            {
                name: {new: old for old, new in rows.items()}
                for name, rows in self.resources.items()
            },
            {new: old for old, new in self.binaries.items()},
            {new: old for old, new in self.objects.items()},
        )


def relocate_tree(root: etree._Element, relocation: ResourceRelocation) -> None:
    for node in root.iter():
        tag = local_name(node.tag)
        if tag in OBJECTS and (identifier := attribute(node, "id")):
            replacement = relocation.objects.get(identifier)
            if replacement is None:
                fail("curated object identity is missing")
            set_attribute(node, "id", replacement)
        for key, raw in tuple(node.attrib.items()):
            name, value = local_name(key).casefold(), str(raw)
            catalog = REFERENCES.get(name)
            if tag == "fontRef" and name in FONT_LANGUAGES:
                catalog = "font:" + FONT_LANGUAGES[name]
            elif tag == "heading" and name == "idref":
                catalog = {"NUMBER": "numberings", "BULLET": "bullets"}.get(
                    attribute(node, "type") or ""
                )
            if catalog:
                # Hancom numbering definitions use the all-bits-set marker rather
                # than a charProperties row. Preserve this exact source field only.
                if tag == "paraHead" and name == "charpridref" and value == "4294967295":
                    continue
                mapping = relocation.resources.get(catalog, {})
                replacement = mapping.get(value)
                if replacement is None:
                    if value == "0" and catalog in ZERO_SENTINELS:
                        continue
                    fail("curated resource reference is missing: " + catalog)
                node.attrib[key] = replacement
            elif name == "binaryitemidref":
                if not value and tag != "img":
                    continue
                replacement = relocation.binaries.get(value)
                if replacement is None:
                    fail("curated image/font binary reference is missing")
                node.attrib[key] = replacement
            elif name == "beginidref":
                replacement = relocation.objects.get(value)
                if replacement is None:
                    fail("curated field reference is missing")
                node.attrib[key] = replacement
            elif name in {"linklistidref", "linklistnextidref"}:
                if value not in {"0", "-1", ""}:
                    fail("linked text-frame IDs require a successor merge profile")
            elif name.endswith("idref") and value not in {"0", "-1", ""}:
                fail("unknown curated reference attribute: " + name)


def header_skeleton(header: etree._Element) -> tuple[object, ...]:
    clone = copy.deepcopy(header)
    clone.attrib.pop("secCnt", None)
    for node in tuple(clone):
        if local_name(node.tag) == "refList":
            clone.remove(node)
    return tree_value(clone)


def merge_resources(
    headers: tuple[etree._Element, ...],
    binary_maps: tuple[dict[str, str], ...],
    object_maps: tuple[dict[str, str], ...],
) -> tuple[etree._Element, tuple[ResourceRelocation, ...]]:
    if not headers:
        fail("curated header inputs are empty")
    if any(header_skeleton(header) != header_skeleton(headers[0]) for header in headers[1:]):
        fail("curated document options differ outside resource catalogs")
    merged = copy.deepcopy(headers[0])
    targets = resource_catalogs(merged)
    source_rows = tuple(catalog_rows(header) for header in headers)
    if any(set(rows) != set(targets) for rows in source_rows):
        fail("curated resource catalog sets differ")
    for target in targets.values():
        for row in tuple(target):
            target.remove(row)
    next_ids = {name: (1 if name in ZERO_SENTINELS else 0) for name in targets}
    plans = []
    # Allocate every definition first. Forward next-style links and cycles are ordinary edges.
    for rows, binaries, objects in zip(source_rows, binary_maps, object_maps, strict=True):
        maps: dict[str, dict[str, str]] = {}
        for name, definitions in rows.items():
            maps[name] = {}
            for identifier in definitions:
                maps[name][identifier] = str(next_ids[name])
                next_ids[name] += 1
        plans.append(ResourceRelocation(maps, binaries, objects))
    for rows, plan in zip(source_rows, plans, strict=True):
        for name, definitions in rows.items():
            for identifier, original in definitions.items():
                clone = copy.deepcopy(original)
                relocate_tree(clone, plan)
                set_attribute(clone, "id", plan.resources[name][identifier])
                targets[name].append(clone)
    for name, target in targets.items():
        set_attribute(
            target, "fontCnt" if name.startswith("font:") else "itemCnt", str(len(target))
        )
    return merged, tuple(plans)


def verify_resource_relocation(
    headers: tuple[etree._Element, ...],
    output: etree._Element,
    plans: tuple[ResourceRelocation, ...],
) -> None:
    actual = catalog_rows(output)
    for source, plan in zip(headers, plans, strict=True):
        inverse = plan.inverse()
        for name, definitions in catalog_rows(source).items():
            for identifier, expected in definitions.items():
                new_id = plan.resources[name][identifier]
                observed = actual.get(name, {}).get(new_id)
                if observed is None:
                    fail("curated output resource definition disappeared")
                clone = copy.deepcopy(observed)
                relocate_tree(clone, inverse)
                set_attribute(clone, "id", identifier)
                if tree_value(clone) != tree_value(expected):
                    raise HwpxError(
                        HwpxErrorCode.HWPX_SEMANTIC_MISMATCH,
                        "curated output resource differs from the source definition",
                    )
