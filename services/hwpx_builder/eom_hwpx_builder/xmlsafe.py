"""Hardened XML parsing with no DTD, entity, XInclude, recovery, or network access."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import cast

from lxml import etree  # type: ignore[import-untyped]

from eom_hwpx_builder.errors import HwpxError, HwpxErrorCode
from eom_hwpx_builder.models import PackageLimits

XML_DECLARATION = re.compile(rb"^(?:\xef\xbb\xbf)?(<\?xml[^?]*\?>)(\r\n|\n|\r)?")


@dataclass(frozen=True)
class ParsedXml:
    root: etree._Element
    declaration: bytes
    newline: bytes
    bom: bytes


def local_name(value: str) -> str:
    return cast(str, etree.QName(value).localname)


def namespace_uri(value: str) -> str:
    return etree.QName(value).namespace or ""


def parse_xml(data: bytes, part_name: str, limits: PackageLimits | None = None) -> ParsedXml:
    actual_limits = limits or PackageLimits()
    if len(data) > actual_limits.max_xml_bytes:
        raise HwpxError(HwpxErrorCode.HWPX_XML_UNSAFE, "XML part size limit exceeded")
    upper = data.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise HwpxError(HwpxErrorCode.HWPX_XML_UNSAFE, "DTD or entity declaration rejected")
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        recover=False,
        huge_tree=False,
        remove_blank_text=False,
        remove_comments=False,
        strip_cdata=False,
    )
    try:
        root = etree.fromstring(data, parser=parser, base_url=None)
    except (etree.XMLSyntaxError, ValueError) as exc:
        raise HwpxError(HwpxErrorCode.HWPX_XML_INVALID, "malformed XML part") from exc
    if root.getroottree().docinfo.doctype:
        raise HwpxError(HwpxErrorCode.HWPX_XML_UNSAFE, "DOCTYPE rejected")
    for element in root.iter():
        depth = len(element.xpath("ancestor::*"))
        if depth > actual_limits.max_xml_depth:
            raise HwpxError(HwpxErrorCode.HWPX_XML_UNSAFE, "XML depth limit exceeded")
        if local_name(element.tag).lower() == "include" and namespace_uri(element.tag) == (
            "http://www.w3.org/2001/XInclude"
        ):
            raise HwpxError(HwpxErrorCode.HWPX_XML_UNSAFE, "XInclude rejected")
    match = XML_DECLARATION.match(data)
    bom = b"\xef\xbb\xbf" if data.startswith(b"\xef\xbb\xbf") else b""
    declaration = match.group(1) if match else b""
    newline = match.group(2) if match and match.group(2) else b""
    return ParsedXml(root=root, declaration=declaration, newline=newline, bom=bom)


def serialize_xml(parsed: ParsedXml) -> bytes:
    body = cast(bytes, etree.tostring(parsed.root, encoding="utf-8", xml_declaration=False))
    if parsed.declaration:
        return parsed.bom + parsed.declaration + parsed.newline + body
    return parsed.bom + body
