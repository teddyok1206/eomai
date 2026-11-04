"""Pure publication order and math spans shared by rendering and output acceptance."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from eom_hwpx_contracts.content_team_equations import project_content_team_equation_script
from eom_hwpx_contracts.native_item import (
    NativeItemEquation,
    NativeItemImage,
    NativeItemParagraph,
    NativeItemRenderRequest,
    NativeItemStatements,
    NativeItemTable,
)

_MATH = re.compile(r"\$\$(?P<display>.+?)\$\$|(?<!\$)\$(?P<inline>[^\n$]+?)\$(?!\$)", re.DOTALL)
_SCORE_SUFFIX = re.compile(r"\[\s*(?P<points>[0-9]{1,3})\s*점\s*\]\s*$")


@dataclass(frozen=True)
class NativeItemText:
    text: str
    role: Literal["stem", "body", "choice", "solution"]
    page_break: bool = False


@dataclass(frozen=True)
class NativeItemSpan:
    kind: Literal["text", "equation"]
    value: str


type NativePublicationElement = (
    NativeItemText | NativeItemEquation | NativeItemImage | NativeItemTable | NativeItemStatements
)


def native_item_spans(text: str) -> tuple[NativeItemSpan, ...]:
    spans = []
    offset = 0
    for match in _MATH.finditer(text):
        if match.start() > offset:
            spans.append(NativeItemSpan("text", text[offset : match.start()]))
        source = match.group("display") or match.group("inline") or ""
        spans.append(NativeItemSpan("equation", project_content_team_equation_script(source)))
        offset = match.end()
    if offset < len(text):
        spans.append(NativeItemSpan("text", text[offset:]))
    if any("$" in span.value for span in spans if span.kind == "text"):
        raise ValueError("native publication math delimiters are malformed")
    return tuple(spans)


def native_item_equation_script(equation: NativeItemEquation) -> str:
    if equation.notation == "hancom-equation-script":
        return equation.source
    return project_content_team_equation_script(equation.source)


def _with_score(text: str, points: int) -> str:
    """Preserve a source score once; never silently resolve conflicting scores."""
    existing = _SCORE_SUFFIX.search(text)
    if existing is not None:
        if int(existing.group("points")) != points:
            raise ValueError("native publication source score differs from Item score")
        return text
    return text + f" [{points}점]" if points else text


def native_item_publication_elements(
    request: NativeItemRenderRequest,
) -> tuple[NativePublicationElement, ...]:
    """Add presentation numbering/answers, never invented data labels or image descriptions."""
    result: list[NativePublicationElement] = []
    first_paragraph = isinstance(request.body[0], NativeItemParagraph)
    if not first_paragraph:
        result.append(NativeItemText(f"{request.item_number}.", "stem"))
    score_index = next(
        (
            index
            for index in range(len(request.body) - 1, -1, -1)
            if isinstance(request.body[index], NativeItemParagraph)
        ),
        None,
    )
    for index, block in enumerate(request.body):
        if isinstance(block, NativeItemParagraph):
            text = (f"{request.item_number}. " if index == 0 else "") + block.text
            if index == score_index:
                text = _with_score(text, request.points)
            result.append(NativeItemText(text, "stem" if block.purpose == "stem" else "body"))
        else:
            result.append(block)
    if score_index is None and request.points:
        result.append(NativeItemText(f"[{request.points}점]", "body"))
    result.extend(
        NativeItemText(f"{choice.label} {choice.text}", "choice") for choice in request.choices
    )
    answer = next(
        (
            choice.label
            for choice in request.choices
            if choice.choice_id == request.correct_choice_id
        ),
        None,
    )
    if answer is None:
        answer = " / ".join(request.accepted_answers)
    result.extend(
        (
            NativeItemText(f"정답 {answer}", "solution", page_break=True),
            NativeItemText("출제 의도", "solution"),
            NativeItemText(request.authoring_intent, "solution"),
            NativeItemText("해설", "solution"),
            NativeItemText(request.explanation, "solution"),
        )
    )
    result.extend(
        NativeItemText(f"{row.label}. {row.text}", "solution")
        for row in request.statement_explanations
    )
    return tuple(result)
