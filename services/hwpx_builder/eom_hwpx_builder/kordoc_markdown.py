"""Bounded Markdown profile accepted by the Kordoc renderer."""

from __future__ import annotations

import re
from dataclasses import dataclass

from eom_hwpx_builder.errors import HwpxError, HwpxErrorCode

MAX_MARKDOWN_BYTES = 1024 * 1024
MAX_LINE_LENGTH = 4000
MAX_TABLE_COLUMNS = 20
MAX_TABLE_ROWS = 100
MAX_EQUATIONS = 32
MAX_TABLES = 20

DISPLAY_EQUATION = re.compile(r"^\s*\$\$(?P<source>.+)\$\$\s*$")
TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
RAW_HTML = re.compile(r"</?[A-Za-z][^>\n]*>")
IMAGE = re.compile(r"!\[[^\]]*\]")
LINK = re.compile(r"\[[^\]]+\]\([^)]*\)")
EXTERNAL_REFERENCE = re.compile(r"(?i)(?:https?|ftp|file|data|javascript|mailto):")
TEX_COMMAND = re.compile(r"\\([A-Za-z]+)")
TEX_SOURCE = re.compile(r"^[A-Za-z0-9\\{}\[\]()+\-*/=^_.,&|:;! <>]+$")
TEX_ENVIRONMENT = re.compile(r"\\(begin|end)\{([^{}]+)\}")

ALLOWED_TEX_COMMANDS = frozenset(
    {
        "Delta",
        "Gamma",
        "Lambda",
        "Leftarrow",
        "Leftrightarrow",
        "Omega",
        "Phi",
        "Pi",
        "Psi",
        "Rightarrow",
        "Sigma",
        "Theta",
        "Upsilon",
        "Xi",
        "alpha",
        "approx",
        "arccos",
        "arcsin",
        "arctan",
        "bar",
        "begin",
        "beta",
        "bigcap",
        "bigcup",
        "cap",
        "cdot",
        "cdots",
        "chi",
        "cong",
        "cos",
        "cosh",
        "cup",
        "delta",
        "div",
        "downarrow",
        "emptyset",
        "end",
        "epsilon",
        "equiv",
        "eta",
        "exp",
        "exists",
        "forall",
        "frac",
        "gamma",
        "ge",
        "geq",
        "gets",
        "hat",
        "iint",
        "iiint",
        "in",
        "infty",
        "int",
        "iota",
        "kappa",
        "lambda",
        "le",
        "left",
        "leftarrow",
        "leftrightarrow",
        "leq",
        "lim",
        "liminf",
        "limsup",
        "ln",
        "log",
        "longleftarrow",
        "longmapsto",
        "longrightarrow",
        "mapsto",
        "max",
        "min",
        "mp",
        "mathrm",
        "mu",
        "nabla",
        "ne",
        "neq",
        "nexists",
        "notin",
        "nu",
        "oint",
        "omega",
        "omicron",
        "overline",
        "parallel",
        "partial",
        "perp",
        "phi",
        "pi",
        "pmatrix",
        "pm",
        "prod",
        "propto",
        "psi",
        "rho",
        "right",
        "rightarrow",
        "sigma",
        "sim",
        "sin",
        "sinh",
        "simeq",
        "sqrt",
        "subset",
        "subseteq",
        "sum",
        "supset",
        "supseteq",
        "tan",
        "tanh",
        "tau",
        "text",
        "theta",
        "tilde",
        "times",
        "to",
        "underline",
        "uparrow",
        "upsilon",
        "varepsilon",
        "varnothing",
        "varphi",
        "varpi",
        "varrho",
        "varsigma",
        "vartheta",
        "vec",
        "widehat",
        "widetilde",
        "xi",
        "zeta",
    }
)
ALLOWED_TEX_ENVIRONMENTS = frozenset(
    {
        "Bmatrix",
        "align",
        "align*",
        "aligned",
        "bmatrix",
        "cases",
        "matrix",
        "pmatrix",
        "vmatrix",
    }
)


@dataclass(frozen=True)
class KordocMarkdownProfile:
    byte_count: int
    display_equation_count: int
    table_count: int


def _reject(message: str) -> None:
    raise HwpxError(HwpxErrorCode.HWPX_KORDOC_MARKDOWN_UNSAFE, message)


def _validate_xml_text(value: str) -> None:
    for character in value:
        codepoint = ord(character)
        if not (
            codepoint in {0x9, 0xA, 0xD}
            or 0x20 <= codepoint <= 0xD7FF
            or 0xE000 <= codepoint <= 0xFFFD
            or 0x10000 <= codepoint <= 0x10FFFF
        ):
            _reject("Markdown contains a character forbidden by XML 1.0")


def _table_columns(line: str) -> int:
    cells = line.strip().strip("|").split("|")
    return len(cells)


def _validate_equation_environments(source: str) -> None:
    stack: list[str] = []
    for action, name in TEX_ENVIRONMENT.findall(source):
        if name not in ALLOWED_TEX_ENVIRONMENTS:
            _reject("display equation contains an unsupported environment")
        if action == "begin":
            stack.append(name)
        elif not stack or stack.pop() != name:
            _reject("display equation environments are unbalanced")
    if stack:
        _reject("display equation environments are unbalanced")


def inspect_kordoc_markdown(data: bytes) -> KordocMarkdownProfile:
    if not data or len(data) > MAX_MARKDOWN_BYTES:
        _reject("Markdown size is outside the renderer contract")
    try:
        value = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HwpxError(
            HwpxErrorCode.HWPX_KORDOC_MARKDOWN_UNSAFE, "Markdown must be UTF-8"
        ) from exc
    _validate_xml_text(value)
    if RAW_HTML.search(value):
        _reject("raw HTML is outside the Kordoc V0 grammar")
    if IMAGE.search(value):
        _reject("Markdown images are outside the Kordoc V0 grammar")
    if LINK.search(value) or EXTERNAL_REFERENCE.search(value):
        _reject("external references are outside the Kordoc V0 grammar")

    lines = value.splitlines()
    if any(len(line) > MAX_LINE_LENGTH for line in lines):
        _reject("Markdown line length exceeds the renderer contract")

    equations: list[str] = []
    table_separators: list[int] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "$$":
            _reject("multiline display equations are outside the Kordoc V0 grammar")
        equation = DISPLAY_EQUATION.fullmatch(line)
        if equation is not None:
            source = equation.group("source").strip()
            if len(source) > 500 or not TEX_SOURCE.fullmatch(source):
                _reject("display equation is outside the Kordoc V0 LaTeX subset")
            unsupported = sorted(set(TEX_COMMAND.findall(source)) - ALLOWED_TEX_COMMANDS)
            if unsupported:
                _reject("display equation contains an unsupported command")
            _validate_equation_environments(source)
            equations.append(source)
        if TABLE_SEPARATOR.fullmatch(line):
            if index == 0 or index + 1 >= len(lines):
                _reject("GFM table separator has no header or body")
            columns = _table_columns(line)
            if columns < 2 or columns > MAX_TABLE_COLUMNS:
                _reject("GFM table column count is outside the renderer contract")
            if _table_columns(lines[index - 1]) != columns:
                _reject("GFM table header width does not match its separator")
            row_count = 0
            for body_line in lines[index + 1 :]:
                if "|" not in body_line or not body_line.strip():
                    break
                if _table_columns(body_line) != columns:
                    _reject("GFM table row width does not match its separator")
                row_count += 1
            if row_count == 0 or row_count > MAX_TABLE_ROWS:
                _reject("GFM table row count is outside the renderer contract")
            table_separators.append(index)

    if len(equations) > MAX_EQUATIONS or len(table_separators) > MAX_TABLES:
        _reject("Markdown structure exceeds the renderer contract")
    return KordocMarkdownProfile(
        byte_count=len(data),
        display_equation_count=len(equations),
        table_count=len(table_separators),
    )
