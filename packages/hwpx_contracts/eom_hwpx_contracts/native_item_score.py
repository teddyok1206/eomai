"""Bounded pure score observation in an already selected Native question section.

The caller owns question selection, pointer/hash/permission checks and publication.
An absent text marker is not proof of an unprinted score (it may be in an image).
Multiple markers remain ambiguous, including repeated equal values.
"""

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal
from xml.etree import ElementTree as ET

_HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
_SECTION = "{http://www.hancom.co.kr/hwpml/2011/section}sec"
_MARKER = re.compile(r"\[[^\S\r\n]*(?P<value>[^\[\]\r\n]{1,32}?)[^\S\r\n]*점[^\S\r\n]*\]")
_NUMBER = re.compile(r"[0-9]{1,3}(?:\.[0-9]{1,6})?\Z")
_TEXT_CONTROLS = {
    _HP + "lineBreak": "\n",
    _HP + "tab": "\t",
    _HP + "fwSpace": "\u3000",
    _HP + "nbSpace": "\u00a0",
}


@dataclass(frozen=True, slots=True)
class NativePrintedScore:
    printed_literal: str
    points: Decimal


@dataclass(frozen=True, slots=True)
class NativePrintedScoreObservation:
    candidates: tuple[NativePrintedScore, ...]

    @property
    def state(self) -> Literal["MATCHED", "ABSENT", "AMBIGUOUS"]:
        return (
            "MATCHED" if len(self.candidates) == 1 else "AMBIGUOUS" if self.candidates else "ABSENT"
        )


def observe_native_printed_score(section_xml: bytes) -> NativePrintedScoreObservation:
    if (
        not isinstance(section_xml, bytes)
        or len(section_xml) > 16 * 1024 * 1024
        or b"\x00" in section_xml
        or any(token in section_xml.upper() for token in (b"<!DOCTYPE", b"<!ENTITY"))
    ):
        raise ValueError("NATIVE_ITEM_SCORE_XML_INVALID")
    try:
        section_xml.decode("utf-8", errors="strict")
        root = ET.fromstring(section_xml)
    except (UnicodeDecodeError, ET.ParseError) as error:
        raise ValueError("NATIVE_ITEM_SCORE_XML_INVALID") from error
    if root.tag != _SECTION:
        raise ValueError("NATIVE_ITEM_SCORE_XML_INVALID")
    text_parts: list[str] = []
    characters = 0
    nodes = 0

    def append(value: str) -> None:
        nonlocal characters
        characters += len(value)
        if characters > 4 * 1024 * 1024:
            raise ValueError("NATIVE_ITEM_SCORE_TEXT_LIMIT")
        text_parts.append(value)

    def visit(node: ET.Element, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if depth > 128 or nodes > 200_000:
            raise ValueError("NATIVE_ITEM_SCORE_XML_LIMIT")
        if node.tag == _HP + "t":
            nodes += len(node)
            if nodes > 200_000:
                raise ValueError("NATIVE_ITEM_SCORE_XML_LIMIT")
            append(node.text or "")
            for child in node:
                if child.tag not in _TEXT_CONTROLS or len(child) or child.text:
                    raise ValueError("NATIVE_ITEM_SCORE_TEXT_UNSUPPORTED")
                append(_TEXT_CONTROLS[child.tag])
                append(child.tail or "")
            return
        if node.tag == _HP + "p":
            append("\n")
        for child in node:
            visit(child, depth + 1)
        if node.tag == _HP + "p":
            append("\n")

    visit(root, 0)
    candidates = []
    for match in _MARKER.finditer("".join(text_parts)):
        literal = match.group("value").strip()
        normalized = unicodedata.normalize("NFKC", literal)
        if _NUMBER.fullmatch(normalized) is None:
            raise ValueError("NATIVE_ITEM_PRINTED_SCORE_INVALID")
        points = Decimal(normalized)
        if points > 100:
            raise ValueError("NATIVE_ITEM_PRINTED_SCORE_INVALID")
        candidates.append(NativePrintedScore(literal, points))
        if len(candidates) > 64:
            raise ValueError("NATIVE_ITEM_SCORE_CANDIDATE_LIMIT")
    return NativePrintedScoreObservation(tuple(candidates))
