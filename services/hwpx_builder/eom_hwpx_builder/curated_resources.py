"""Native HWPX resource relocation; allocate identities before following style cycles."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import StrEnum
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


class NativeMergeProfile(StrEnum):
    STRICT_V1 = "NATIVE_EDITABLE_PRESERVATION_V1"
    EDITABLE_V2 = "NATIVE_EDITABLE_PRESERVATION_V2"


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
class ObjectRelocation:
    identifiers: dict[str, str]
    anonymous: dict[tuple[int, int], str] = field(default_factory=dict)
    attributes: dict[tuple[str, str, str], tuple[str, str]] = field(default_factory=dict)

    def inverse(self) -> ObjectRelocation:
        return ObjectRelocation(
            {
                **{new: old for old, new in self.identifiers.items()},
                **{identifier: "0" for identifier in self.anonymous.values()},
            },
            attributes={
                (name, new_id, old_id): (new, old)
                for (name, old_id, new_id), (old, new) in self.attributes.items()
            },
        )


@dataclass(frozen=True)
class ResourceRelocation:
    resources: dict[str, dict[str, str]]
    binaries: dict[str, str]
    objects: ObjectRelocation
    style_names: dict[tuple[str, str], tuple[str, str]] = field(default_factory=dict)

    def inverse(self) -> ResourceRelocation:
        return ResourceRelocation(
            {
                name: {new: old for old, new in rows.items()}
                for name, rows in self.resources.items()
            },
            {new: old for old, new in self.binaries.items()},
            self.objects.inverse(),
            {
                (self.resources["styles"][identifier], name): (new, old)
                for (identifier, name), (old, new) in self.style_names.items()
            },
        )


def relocate_tree(
    root: etree._Element,
    relocation: ResourceRelocation,
    *,
    section_ordinal: int | None = None,
) -> None:
    anonymous_ordinal = 0
    for node in root.iter():
        tag = local_name(node.tag)
        if tag == "style" and (style_id := attribute(node, "id")) is not None:
            for key, current in tuple(node.attrib.items()):
                renamed = relocation.style_names.get((style_id, local_name(key)))
                if renamed is not None:
                    if current != renamed[0]:
                        fail("curated style name differs from its relocation plan")
                    node.attrib[key] = renamed[1]
        if tag in OBJECTS and (identifier := attribute(node, "id")):
            if (
                identifier == "0"
                and tag != "fieldBegin"
                and section_ordinal is not None
                and relocation.objects.anonymous
            ):
                replacement = relocation.objects.anonymous.get((section_ordinal, anonymous_ordinal))
                anonymous_ordinal += 1
            else:
                replacement = relocation.objects.identifiers.get(identifier)
            if replacement is None:
                fail("curated object identity is missing")
            for key, value in tuple(node.attrib.items()):
                renamed = relocation.objects.attributes.get(
                    (local_name(key).casefold(), identifier, replacement)
                )
                if renamed is not None:
                    if value != renamed[0]:
                        fail("curated object instance differs from its relocation plan")
                    node.attrib[key] = renamed[1]
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
                replacement = relocation.objects.identifiers.get(value)
                if replacement is None:
                    fail("curated field reference is missing")
                node.attrib[key] = replacement
            elif name in {"linklistidref", "linklistnextidref"}:
                if value not in {"0", "-1", ""}:
                    fail("linked text-frame IDs require a successor merge profile")
            elif name.endswith("idref") and value not in {"0", "-1", ""}:
                fail("unknown curated reference attribute: " + name)


def header_skeleton(
    header: etree._Element, profile: NativeMergeProfile = NativeMergeProfile.STRICT_V1
) -> tuple[object, ...]:
    clone = copy.deepcopy(header)
    clone.attrib.pop("secCnt", None)
    if profile == NativeMergeProfile.EDITABLE_V2:
        version = clone.attrib.get("version")
        if version is not None:
            if version not in {"1.4", "1.5"}:
                fail("curated header version is not supported by the editable profile")
            clone.attrib["version"] = "1.5"
    for node in tuple(clone):
        default_tracking = (
            profile == NativeMergeProfile.EDITABLE_V2
            and local_name(node.tag) == "trackchageConfig"
            and dict(node.attrib) == {"flags": "56"}
            and len(node) == 0
            and not (node.text or "").strip()
        )
        if local_name(node.tag) == "refList" or default_tracking:
            clone.remove(node)
    return tree_value(clone)


def merge_resources(
    headers: tuple[etree._Element, ...],
    binary_maps: tuple[dict[str, str], ...],
    object_maps: tuple[ObjectRelocation, ...],
    *,
    profile: NativeMergeProfile = NativeMergeProfile.STRICT_V1,
) -> tuple[etree._Element, tuple[ResourceRelocation, ...]]:
    if not headers:
        fail("curated header inputs are empty")
    skeleton = header_skeleton(headers[0], profile)
    if any(header_skeleton(header, profile) != skeleton for header in headers[1:]):
        fail("curated document options differ outside resource catalogs")
    merged = copy.deepcopy(headers[0])
    if profile == NativeMergeProfile.EDITABLE_V2 and "version" in merged.attrib:
        merged.set("version", "1.5")
    targets = resource_catalogs(merged)
    source_rows = tuple(catalog_rows(header) for header in headers)
    if profile == NativeMergeProfile.STRICT_V1:
        if any(set(rows) != set(targets) for rows in source_rows):
            fail("curated resource catalog sets differ")
    else:
        _include_missing_catalogs(merged, headers)
        targets = resource_catalogs(merged)
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
    if profile == NativeMergeProfile.EDITABLE_V2:
        _plan_unique_style_names(source_rows, plans)
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


def _include_missing_catalogs(merged: etree._Element, headers: tuple[etree._Element, ...]) -> None:
    """Union missing catalogs without inventing definitions for dangling references."""
    references = next(child for child in merged if local_name(child.tag) == "refList")
    for header in headers[1:]:
        targets = resource_catalogs(merged)
        for name, catalog in resource_catalogs(header).items():
            if name in targets:
                continue
            clone = copy.deepcopy(catalog)
            if name.startswith("font:"):
                fonts = next(
                    (child for child in references if local_name(child.tag) == "fontfaces"), None
                )
                if fonts is None:
                    fonts = etree.SubElement(
                        references, f"{{{etree.QName(catalog).namespace}}}fontfaces"
                    )
                fonts.append(clone)
                set_attribute(fonts, "itemCnt", str(len(fonts)))
            else:
                references.append(clone)


def _plan_unique_style_names(
    rows: tuple[dict[str, dict[str, etree._Element]], ...], plans: list[ResourceRelocation]
) -> None:
    # Importers may coalesce equal style names even when numeric IDs differ.
    # Preserve the first name and namespace subsequent collisions; inversion
    # still proves every original name and resource definition exactly.
    reserved = {
        (local_name(key), value)
        for catalogs in rows
        for style in catalogs.get("styles", {}).values()
        for key, value in style.attrib.items()
        if local_name(key) in {"name", "engName"} and value
    }
    seen: set[tuple[str, str]] = set()
    for position, (catalogs, plan) in enumerate(zip(rows, plans, strict=True), start=1):
        for identifier, style in catalogs.get("styles", {}).items():
            for key, value in style.attrib.items():
                name = local_name(key)
                if name not in {"name", "engName"} or not value:
                    continue
                identity = (name, value)
                if identity in seen:
                    candidate = f"EOM-{position:03d}-{plan.resources['styles'][identifier]}"
                    while (name, candidate) in reserved:
                        candidate += "-"
                    plan.style_names[identifier, name] = (value, candidate)
                    reserved.add((name, candidate))
                seen.add(identity)


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
