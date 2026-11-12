"""Project validated editorial fields into the immutable handoff's public input model.

The handoff parser serves free-form paste input. EOM already owns typed question boundaries,
so reparsing that input would let ordinary Korean phrases or an inline ① redefine them.
Only the general structured body uses canonical Markdown; the remaining fields map directly.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from eom_hwpx_contracts import ContentTeamEditorialDraftContract, serialize_content_team_markdown

from eom_hwpx_builder.errors import HwpxError, HwpxErrorCode

_SOLUTION_MARKER = re.compile(r"(?m)^([ㄱㄴㄷ])\.\s+")
_OPTION_FIELDS = {"ㄱ": "option_ga", "ㄴ": "option_na", "ㄷ": "option_da"}
_SOLUTION_FIELDS = {"ㄱ": "solution_ga", "ㄴ": "solution_na", "ㄷ": "solution_da"}


def _single_line_slot(value: str) -> str:
    """The frozen bottom/option/choice slots wrap text, but reject explicit line breaks."""
    if "\n" not in value and "\r" not in value:
        return value
    return " ".join(line.strip(" \t") for line in value.splitlines() if line.strip(" \t"))


def project_content_team_question(
    draft: ContentTeamEditorialDraftContract,
    *,
    question_type: Callable[..., Any],
    item_number: int,
    score_display: str,
) -> tuple[Any, bytes]:
    """Keep canonical round-trip validation and project one already-authorized presentation."""
    canonical = serialize_content_team_markdown(draft).decode("utf-8")
    prefix = f"{draft.item_number}. "
    marker = f"\n\n{draft.bottom_stem} [{draft.score_display}점]\n\n"
    if not canonical.startswith(prefix) or canonical.count(marker) != 1:
        raise HwpxError(
            HwpxErrorCode.HWPX_REFERENCE_UNSAFE,
            "canonical question boundary is ambiguous",
        )
    main, tail = canonical.split(marker, 1)
    main = f"{item_number}. " + main[len(prefix) :]
    rendered_bottom = f"{draft.bottom_stem} [{score_display}점]"
    markdown = f"{main}\n\n{rendered_bottom}\n\n{tail}".encode()
    values: dict[str, Any] = {
        "question_name": f"item-{item_number}",
        "stem": main,
        "bottom_stem": _single_line_slot(rendered_bottom),
        "is_inquiry_experiment": draft.inquiry is not None,
        "answer": draft.answer.number,
        "answer_combination": draft.answer.statement_labels,
        "answer_combination_explicit": draft.answer.answer_kind == "STATEMENT_COMBINATION",
        "answer_raw": draft.answer.raw_line.removeprefix("정답 : "),
        "intent": draft.explanations.authoring_intent,
        "concept": draft.explanations.concept_source,
        "solution": draft.explanations.correct_answer,
        "wrong_answer": draft.explanations.wrong_answer,
        "raw_text": markdown.decode("utf-8"),
    }
    if draft.inquiry is not None:
        inquiry = draft.inquiry
        first_section = "목표" if inquiry.goal is not None else "과정"
        first_marker = f"\n\n[{inquiry.kind} {first_section}]\n\n"
        if main.count(first_marker) != 1:
            raise HwpxError(
                HwpxErrorCode.HWPX_REFERENCE_UNSAFE,
                "canonical inquiry boundary is ambiguous",
            )
        values["stem"] = main.split(first_marker, 1)[0]
        values.update(
            inquiry_goal_heading=f"[{inquiry.kind} 목표]" if inquiry.goal is not None else "",
            inquiry_goal=inquiry.goal or "",
            inquiry_procedure_heading=f"[{inquiry.kind} 과정]",
            inquiry_procedure=inquiry.procedure,
            inquiry_result_heading=f"[{inquiry.kind} 결과]",
            inquiry_result=inquiry.result,
        )
    values.update(
        (_OPTION_FIELDS[statement.label], _single_line_slot(statement.text))
        for statement in draft.statements
    )
    values.update(
        (f"choice{position}", _single_line_slot(choice.text))
        for position, choice in enumerate(draft.choices, start=1)
    )
    solution = draft.explanations.correct_answer
    markers = tuple(_SOLUTION_MARKER.finditer(solution)) if draft.statements else ()
    values["solution_overall"] = solution[: markers[0].start()].strip() if markers else solution
    for index, match in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(solution)
        values[_SOLUTION_FIELDS[match.group(1)]] = solution[match.end() : end].strip()
    return question_type(**values), markdown
