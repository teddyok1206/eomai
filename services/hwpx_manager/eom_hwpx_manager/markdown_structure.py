"""Protocol-level native structure inventory for already validated bounded Markdown."""

from __future__ import annotations

import re
from dataclasses import dataclass

from eom_hwpx_manager.errors import HwpxManagerError, HwpxManagerErrorCode

MAX_MARKDOWN_BYTES = 1024 * 1024
DISPLAY_EQUATION = re.compile(rb"(?m)^\s*\$\$.+\$\$\s*$")
TABLE_SEPARATOR = re.compile(rb"(?m)^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")


@dataclass(frozen=True)
class MarkdownStructure:
    native_equation_count: int
    native_table_count: int


def inspect_markdown_structure(data: bytes) -> MarkdownStructure:
    if not data or len(data) > MAX_MARKDOWN_BYTES:
        raise HwpxManagerError(
            HwpxManagerErrorCode.HWPX_KORDOC_SOURCE_INVALID,
            "Markdown size is outside the renderer contract",
        )
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HwpxManagerError(
            HwpxManagerErrorCode.HWPX_KORDOC_SOURCE_INVALID,
            "Markdown must use UTF-8",
        ) from exc
    equations = len(DISPLAY_EQUATION.findall(data))
    tables = len(TABLE_SEPARATOR.findall(data))
    if equations > 32 or tables > 20:
        raise HwpxManagerError(
            HwpxManagerErrorCode.HWPX_KORDOC_SOURCE_INVALID,
            "Markdown structure exceeds the renderer contract",
        )
    return MarkdownStructure(equations, tables)
