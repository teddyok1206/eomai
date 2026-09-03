"""Pure equation grammar contract for the reviewed content-team profile."""

from __future__ import annotations

import re
from typing import Literal

ContentTeamEquationFamily = Literal[
    "PLAIN_NUMBER",
    "VARIABLE",
    "FRACTION",
    "SUBSCRIPT",
    "SUPERSCRIPT",
    "SUBSCRIPT_SUPERSCRIPT",
    "CHEMICAL_OR_ION",
    "PRIME",
    "RATIO",
    "COMPARISON",
    "COEFFICIENT_VARIABLE",
    "SIGNED_SCALAR",
    "ADD_SUB_EXPRESSION",
    "MULTIPLICATIVE_EXPRESSION",
]

SUPPORTED_COMMANDS = frozenset({"frac", "max", "prime", "times"})
ALLOWED_SOURCE = re.compile(r"^[A-Za-z0-9\s.+'_:<>=+\-*/(){}\\^]+$")
NUMBER = re.compile(r"^\d+(?:\.\d+)?$")
VARIABLE = re.compile(r"^[A-Za-z]$")
SIGNED_ATOM = re.compile(r"^[+-](?:\d+(?:\.\d+)?|[A-Za-z])$")
COEFFICIENT_VARIABLE = re.compile(r"^\d+(?:\.\d+)?[A-Za-z]$")
PRIME = re.compile(r"^[A-Za-z](?:'|\^\{\\prime(?:\\prime)?\})$")
INDEX = r"(?:[A-Za-z0-9]+|\\max)"
EXPONENT = r"(?:[A-Za-z0-9]+|[0-9]+[+-]|[+-][0-9]+|[+-]|\\prime(?:\\prime)?)"
DECORATED = re.compile(
    rf"^(?P<base>\d+(?:\.\d+)?|[A-Za-z])"
    rf"(?P<sub>_(?:\{{{INDEX}\}}|[A-Za-z0-9]))?"
    rf"(?P<sup>\^(?:\{{{EXPONENT}\}}|[A-Za-z0-9]))?$"
)
CHEMICAL = re.compile(
    rf"^(?:[A-Z][a-z]?(?:_(?:\{{{INDEX}\}}|[0-9]))?)+"
    rf"(?:\^(?:\{{{EXPONENT}\}}|[A-Za-z0-9+\-]))?$"
)


class ContentTeamEquationError(ValueError):
    """An equation cannot be represented by the reviewed prototype families."""


def _balanced(value: str) -> bool:
    stack: list[str] = []
    pairs = {"}": "{", ")": "("}
    for character in value:
        if character in "{(":
            stack.append(character)
        elif character in "})" and (not stack or stack.pop() != pairs[character]):
            return False
    return not stack


def _braced(value: str, start: int) -> tuple[str, int] | None:
    if start >= len(value) or value[start] != "{":
        return None
    depth = 0
    for index in range(start, len(value)):
        if value[index] == "{":
            depth += 1
        elif value[index] == "}":
            depth -= 1
            if depth == 0:
                return value[start + 1 : index], index + 1
    return None


def _fraction(value: str) -> tuple[str, str, str] | None:
    if not value.startswith(r"\frac"):
        return None
    numerator = _braced(value, len(r"\frac"))
    if numerator is None:
        return None
    denominator = _braced(value, numerator[1])
    if denominator is None:
        return None
    return numerator[0], denominator[0], value[denominator[1] :]


def _top_level_parts(value: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    parts: list[str] = []
    operators: list[str] = []
    start = 0
    brace_depth = 0
    parenthesis_depth = 0
    index = 0
    while index < len(value):
        character = value[index]
        if character == "{":
            brace_depth += 1
        elif character == "}":
            brace_depth -= 1
        elif character == "(":
            parenthesis_depth += 1
        elif character == ")":
            parenthesis_depth -= 1
        elif brace_depth == 0 and parenthesis_depth == 0:
            if value.startswith(r"\times", index):
                parts.append(value[start:index])
                operators.append("times")
                index += len(r"\times")
                start = index
                continue
            if character in "+-=<>:/":
                # A leading sign is part of one scalar.  A sign immediately after
                # another top-level operator is ambiguous for the reviewed HWPX
                # prototypes and must not be accepted as an implicit rewrite.
                if character in "+-" and index == start and start == 0:
                    index += 1
                    continue
                parts.append(value[start:index])
                operators.append(character)
                start = index + 1
        index += 1
    parts.append(value[start:])
    return tuple(parts), tuple(operators)


def _decorated_family(value: str) -> ContentTeamEquationFamily | None:
    match = DECORATED.fullmatch(value)
    if match is None or (match.group("sub") is None and match.group("sup") is None):
        return None
    if match.group("sub") is not None and match.group("sup") is not None:
        return "SUBSCRIPT_SUPERSCRIPT"
    return "SUBSCRIPT" if match.group("sub") is not None else "SUPERSCRIPT"


def _term_supported(value: str) -> bool:
    value = value.strip()
    if not value:
        return False
    if value.startswith("(") and value.endswith(")") and _balanced(value[1:-1]):
        return _expression_family(value[1:-1]) is not None
    if (
        any(
            pattern.fullmatch(value)
            for pattern in (NUMBER, VARIABLE, SIGNED_ATOM, COEFFICIENT_VARIABLE, PRIME, CHEMICAL)
        )
        or _decorated_family(value) is not None
    ):
        return True
    fraction = _fraction(value)
    if fraction is None:
        return False
    numerator, denominator, suffix = fraction
    return (
        _expression_family(numerator) is not None
        and _expression_family(denominator) is not None
        and (not suffix or VARIABLE.fullmatch(suffix) is not None)
    )


def _expression_family(value: str) -> ContentTeamEquationFamily | None:
    compact = re.sub(r"\s+", "", value)
    if not compact:
        return None
    if NUMBER.fullmatch(compact):
        return "PLAIN_NUMBER"
    if VARIABLE.fullmatch(compact):
        return "VARIABLE"
    if SIGNED_ATOM.fullmatch(compact):
        return "SIGNED_SCALAR"
    if COEFFICIENT_VARIABLE.fullmatch(compact):
        return "COEFFICIENT_VARIABLE"
    if PRIME.fullmatch(compact):
        return "PRIME"
    if CHEMICAL.fullmatch(compact) and ("_" in compact or "^" in compact):
        return "CHEMICAL_OR_ION"
    decorated = _decorated_family(compact)
    if decorated is not None:
        return decorated
    fraction = _fraction(compact)
    if fraction is not None and _term_supported(compact):
        return "FRACTION"

    parts, operators = _top_level_parts(compact)
    if not operators or any(not _term_supported(part) for part in parts):
        return None
    if ":" in operators:
        if set(operators) <= {":", "="} and operators.count("=") <= 1:
            return "RATIO"
        return None
    if any(operator in {"<", ">"} for operator in operators):
        return "COMPARISON" if set(operators) <= {"<", ">", "="} else None
    if any(operator in {"times", "/"} for operator in operators):
        return "MULTIPLICATIVE_EXPRESSION"
    if any(operator in {"+", "-"} for operator in operators):
        return "ADD_SUB_EXPRESSION" if operators.count("=") <= 1 else None
    if operators == ("=",):
        return "COMPARISON"
    return None


def classify_content_team_equation(source: str) -> ContentTeamEquationFamily:
    """Classify one bounded source without generating or guessing HWPX XML."""

    if not source or len(source) > 500 or ALLOWED_SOURCE.fullmatch(source) is None:
        raise ContentTeamEquationError("content-team equation contains unsupported characters")
    if not _balanced(source):
        raise ContentTeamEquationError("content-team equation grouping is malformed")
    commands = set(re.findall(r"\\([A-Za-z]+)", source))
    if commands - SUPPORTED_COMMANDS:
        raise ContentTeamEquationError("content-team equation command is unsupported")
    family = _expression_family(source)
    if family is None:
        raise ContentTeamEquationError("content-team equation is outside the prototype grammar")
    return family


def assert_content_team_equations_supported(sources: tuple[str, ...]) -> None:
    """Fail before rendering when any source lacks a reviewed prototype family."""

    for source in sources:
        try:
            classify_content_team_equation(source)
        except ContentTeamEquationError as exc:
            raise ContentTeamEquationError(
                f"unsupported content-team equation: {source!r}"
            ) from exc
