"""Pure parser for the reviewed content-team HwpQuestionEditor Markdown contract."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable
from typing import Literal, NoReturn, cast

from eom_hwpx_contracts.content_team_equations import (
    ContentTeamEquationError,
    assert_content_team_equations_supported,
)
from eom_hwpx_contracts.models import (
    ContentTeamChoice,
    ContentTeamCombinationAnswer,
    ContentTeamDirectChoiceAnswer,
    ContentTeamEditorialDraft,
    ContentTeamEditorialQuestion,
    ContentTeamExplanationSections,
    ContentTeamImageSlot,
    ContentTeamInquiry,
    ContentTeamLabeledBlock,
    ContentTeamStatement,
    ContentTeamTable,
)
from eom_hwpx_contracts.validation import validate_contract

MAX_SOURCE_BYTES = 1024 * 1024
SECTION_LABELS = (
    "[출제의도]",
    "[개념출처]",
    "[풀이 및 정답 해설]",
    "[오답 해설]",
)
CHOICE_NUMBERS = ("①", "②", "③", "④", "⑤")
STATEMENT_LABELS = ("ㄱ", "ㄴ", "ㄷ")
PROCEDURE_LABELS = tuple("가나다라마바사아")

ITEM_LINE = re.compile(r"^(?P<number>[1-9][0-9]{0,2})\.\s*(?P<text>\S.*)$")
SCORE = re.compile(r"\s*\[(?P<score>2(?:\.5)?|3)점\]\s*$")
ANSWER = re.compile(r"^정답 : (?P<number>[①②③④⑤]) \((?P<content>[^\r\n]+)\)$")
STATEMENT_COMBINATION = re.compile(r"^(?:ㄱ(?:, ㄴ)?(?:, ㄷ)?|ㄴ(?:, ㄷ)?|ㄷ)$")
STATEMENT = re.compile(r"(?m)^\s*(?P<label>[ㄱㄴㄷ])[.．]\s*")  # noqa: RUF001
CHOICE = re.compile(r"(?m)^\s*(?P<number>[①②③④⑤])\s+")
INQUIRY_HEADER = re.compile(r"(?m)^\[(?P<kind>탐구|실험) (?P<section>목표|과정|결과)\]\s*$")
IMAGE_MARKER = re.compile(r"^그림(?: (?P<label>\(가\)|\(나\)))?$")
TABLE_LABEL = re.compile(r"^표 (?P<label>\(가\)|\(나\))$")
LABELED_BLOCK = re.compile(r"^(?:<\s*(?P<angle>자료|조건)\s*>|\[\s*(?P<bracket>자료|조건)\s*\])$")
TABLE_SEPARATOR_CELL = re.compile(r"^:?-{3,}:?$")
EQUATION = re.compile(r"\$\$(?P<display>.+?)\$\$|(?<!\$)\$(?P<inline>[^\n$]+?)\$(?!\$)", re.DOTALL)
RAW_HTML = re.compile(r"</?[A-Za-z][^>\n]*>")
LINK_OR_IMAGE = re.compile(r"!?\[[^\]\n]*\]\([^\n)]*\)")
EXTERNAL_REFERENCE = re.compile(r"(?i)(?:https?|ftp|file|data|javascript|mailto):")
WINDOWS_OR_IMAGE_PATH = re.compile(
    r"(?i)(?:[A-Z]:[\\/]|(?:^|\s)(?:\.\.?/|/)[^\s]+|\.(?:png|jpe?g|gif|webp)\b)"
)


class ContentTeamMarkdownError(ValueError):
    """Raised when authoring Markdown is outside the reviewed handoff grammar."""


def _fail(message: str) -> NoReturn:
    raise ContentTeamMarkdownError(message)


def _clean(value: str) -> str:
    lines = [line.strip() for line in value.splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    result: list[str] = []
    for line in lines:
        if line or not result or result[-1]:
            result.append(line)
    return "\n".join(result)


def _validate_surface(value: str) -> None:
    presentation = EQUATION.sub("", value)
    if any(
        re.search(pattern, presentation, re.MULTILINE)
        for pattern in (
            r"^\s*#{1,6}\s+",
            r"^\s*>\s?",
            r"^\s*(?:---+|___+|\*\*\*+)\s*$",
            r"```",
            r"\*\*[^\n]+\*\*",
            r"(?<!\*)\*(?=\S)[^*\n]*?\S\*(?!\*)",
        )
    ):
        _fail("content-team Markdown contains forbidden presentation syntax")
    if RAW_HTML.search(value) or LINK_OR_IMAGE.search(value) or EXTERNAL_REFERENCE.search(value):
        _fail("content-team Markdown contains an external or active reference")
    if WINDOWS_OR_IMAGE_PATH.search(value):
        _fail("content-team Markdown contains a file or image path")
    for forbidden in ("그림 삽입", "[그림 자리]", "[이미지 자리]"):
        if forbidden in value:
            _fail("content-team Markdown contains a noncanonical visual marker")
    if re.search(r"(?m)^\s*(?:표|이미지)\s*$", value):
        _fail("content-team Markdown contains a standalone table/image marker")


def _split_sections(value: str) -> tuple[str, dict[str, str]]:
    positions: list[tuple[str, int, int]] = []
    for label in SECTION_LABELS:
        matches = list(re.finditer(rf"(?m)^{re.escape(label)}\s*$", value))
        if len(matches) != 1:
            _fail(f"content-team Markdown requires exactly one {label} section")
        positions.append((label, matches[0].start(), matches[0].end()))
    if (
        tuple(label for label, _, _ in sorted(positions, key=lambda item: item[1]))
        != SECTION_LABELS
    ):
        _fail("content-team explanation sections are out of order")
    first = positions[0][1]
    sections: dict[str, str] = {}
    for index, (label, _start, end) in enumerate(positions):
        next_start = positions[index + 1][1] if index + 1 < len(positions) else len(value)
        section = _clean(value[end:next_start])
        if not section and label != "[오답 해설]":
            _fail(f"content-team Markdown section {label} is empty")
        sections[label] = section
    return _clean(value[:first]), sections


def _marked_values(
    value: str,
    pattern: re.Pattern[str],
    group: str,
) -> tuple[tuple[str, str], ...]:
    matches = list(pattern.finditer(value))
    result: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(value)
        result.append((match.group(group), _clean(value[match.end() : end])))
    return tuple(result)


def _parse_pipe_row(line: str) -> tuple[str, ...] | None:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    cells = tuple(cell.strip() for cell in stripped[1:-1].split("|"))
    return cells if len(cells) >= 2 and all(cells) else None


def _table_at(lines: list[str], start: int, label: str) -> tuple[ContentTeamTable, int] | None:
    headers = _parse_pipe_row(lines[start])
    if headers is None or start + 2 >= len(lines):
        return None
    separators = _parse_pipe_row(lines[start + 1])
    if (
        separators is None
        or len(headers) != len(separators)
        or not all(TABLE_SEPARATOR_CELL.fullmatch(cell) for cell in separators)
    ):
        _fail("content-team Markdown table separator differs from its header")
    rows: list[tuple[str, ...]] = []
    index = start + 2
    while index < len(lines):
        row = _parse_pipe_row(lines[index])
        if row is None:
            break
        if len(row) != len(headers):
            _fail("content-team Markdown table is not rectangular")
        rows.append(row)
        index += 1
    if not rows:
        _fail("content-team Markdown table requires a body row")
    assert separators is not None
    alignments: list[Literal["default", "left", "right", "center"]] = []
    for cell in separators:
        left, right = cell.startswith(":"), cell.endswith(":")
        alignments.append(
            "center" if left and right else "left" if left else "right" if right else "default"
        )
    return (
        ContentTeamTable(
            label=cast(Literal["", "(가)", "(나)"], label),
            headers=headers,
            rows=tuple(rows),
            alignments=tuple(alignments),
        ),
        index,
    )


def _extract_visuals(value: str) -> tuple[str, tuple[ContentTeamTable | ContentTeamImageSlot, ...]]:
    lines = value.splitlines()
    kept: list[str] = []
    visuals: list[ContentTeamTable | ContentTeamImageSlot] = []
    pending_table_label = ""
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        table_label = TABLE_LABEL.fullmatch(stripped)
        if table_label is not None:
            if pending_table_label:
                _fail("content-team table label is not followed by a table")
            pending_table_label = table_label.group("label")
            index += 1
            while index < len(lines) and not lines[index].strip():
                index += 1
            if index >= len(lines):
                _fail("content-team table label is not followed by a table")
            continue
        image = IMAGE_MARKER.fullmatch(stripped)
        if image is not None:
            if pending_table_label:
                _fail("content-team table label is not followed by a table")
            visuals.append(
                ContentTeamImageSlot(
                    label=cast(Literal["", "(가)", "(나)"], image.group("label") or "")
                )
            )
            index += 1
            continue
        table = _table_at(lines, index, pending_table_label)
        if table is not None:
            block, index = table
            visuals.append(block)
            pending_table_label = ""
            continue
        if pending_table_label:
            _fail("content-team table label is not followed by a table")
        kept.append(lines[index])
        index += 1
    if pending_table_label:
        _fail("content-team table label is not followed by a table")
    if len(visuals) > 2:
        _fail("content-team Markdown supports at most two visual items")
    return _clean("\n".join(kept)), tuple(visuals)


def _extract_labeled_blocks(
    value: str,
) -> tuple[str, tuple[ContentTeamLabeledBlock, ...]]:
    lines = value.splitlines()
    kept: list[str] = []
    blocks: list[ContentTeamLabeledBlock] = []
    index = 0
    while index < len(lines):
        marker = LABELED_BLOCK.fullmatch(lines[index].strip())
        if marker is None:
            kept.append(lines[index])
            index += 1
            continue
        label = marker.group("angle") or marker.group("bracket")
        index += 1
        content: list[str] = []
        while index < len(lines) and lines[index].strip():
            if LABELED_BLOCK.fullmatch(lines[index].strip()) is not None:
                break
            content.append(lines[index].rstrip())
            index += 1
        normalized = _clean("\n".join(content))
        if not normalized:
            _fail("content-team labeled block is empty")
        blocks.append(
            ContentTeamLabeledBlock(
                kind="DATA" if label == "자료" else "CONDITION",
                content=normalized,
            )
        )
    kinds = tuple(block.kind for block in blocks)
    if kinds not in ((), ("DATA",), ("CONDITION",), ("DATA", "CONDITION")):
        _fail("content-team labeled blocks must be unique and DATA precedes CONDITION")
    return _clean("\n".join(kept)), tuple(blocks)


def _extract_inquiry(value: str) -> tuple[str, ContentTeamInquiry | None]:
    matches = list(INQUIRY_HEADER.finditer(value))
    if not matches:
        return value, None
    kinds = {match.group("kind") for match in matches}
    sections = [match.group("section") for match in matches]
    if len(kinds) != 1 or sections not in (["목표", "과정", "결과"], ["과정", "결과"]):
        _fail("content-team inquiry/experiment sections are incomplete or mixed")
    values: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(value)
        body = _clean(value[match.end() : end])
        if not body:
            _fail("content-team inquiry/experiment section is empty")
        values[match.group("section")] = body
    procedure_labels = tuple(
        match.group("label")
        for match in re.finditer(r"(?m)^\s*\((?P<label>[가-아])\)\s+", values["과정"])
    )
    expected = PROCEDURE_LABELS[: len(procedure_labels)]
    if len(procedure_labels) < 3 or procedure_labels != expected:
        _fail("content-team inquiry/experiment procedure requires three ordered steps")
    leading = _clean(value[: matches[0].start()])
    return (
        leading,
        ContentTeamInquiry(
            kind=cast(Literal["탐구", "실험"], next(iter(kinds))),
            goal=values.get("목표"),
            procedure=values["과정"],
            result=values["결과"],
        ),
    )


def _equations(value: str) -> tuple[str, ...]:
    sources: list[str] = []
    for match in EQUATION.finditer(value):
        source = _clean(match.group("display") or match.group("inline") or "")
        if not source or len(source) > 500:
            _fail("content-team equation source length is invalid")
        sources.append(source)
    if value.count("$") != sum(
        4 if match.group("display") is not None else 2 for match in EQUATION.finditer(value)
    ):
        _fail("content-team equation delimiters are malformed")
    return tuple(sources)


def _labels_in_explanation(value: str) -> tuple[str, ...]:
    return tuple(match.group("label") for match in STATEMENT.finditer(value))


def parse_content_team_markdown(data: bytes) -> ContentTeamEditorialQuestion:
    """Parse exactly one reviewed prompt/program-compatible Markdown item."""

    if not data or len(data) > MAX_SOURCE_BYTES:
        _fail("content-team Markdown size is outside the profile")
    try:
        decoded = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContentTeamMarkdownError("content-team Markdown must be UTF-8") from exc
    value = unicodedata.normalize("NFC", decoded.replace("\r\n", "\n").replace("\r", "\n"))
    _validate_surface(value)
    main, sections = _split_sections(value)

    answer_matches = [
        (index, ANSWER.fullmatch(line.strip())) for index, line in enumerate(main.splitlines())
    ]
    answer_matches = [(index, match) for index, match in answer_matches if match is not None]
    if len(answer_matches) != 1:
        _fail("content-team Markdown requires one exact answer line")
    answer_index, answer_match = answer_matches[0]
    assert answer_match is not None
    main_lines = main.splitlines()
    pre_answer = _clean("\n".join(main_lines[:answer_index]))
    if _clean("\n".join(main_lines[answer_index + 1 :])):
        _fail("content-team answer line must end the item body")

    choice_values = _marked_values(pre_answer, CHOICE, "number")
    if tuple(number for number, _ in choice_values) != CHOICE_NUMBERS:
        _fail("content-team Markdown requires ordered choices ① through ⑤")
    first_choice = CHOICE.search(pre_answer)
    assert first_choice is not None
    before_choices = _clean(pre_answer[: first_choice.start()])
    view = list(re.finditer(r"(?m)^\s*<\s*보\s*기\s*>\s*$", before_choices))
    if len(view) > 1:
        _fail("content-team Markdown allows at most one <보기> marker")
    if view:
        statement_text = _clean(before_choices[view[0].end() :])
        statement_values = _marked_values(statement_text, STATEMENT, "label")
        if tuple(label for label, _ in statement_values) != STATEMENT_LABELS:
            _fail("content-team Markdown requires ordered ㄱ/ㄴ/ㄷ statements")
        content = _clean(before_choices[: view[0].start()])
    else:
        statement_values = ()
        content = before_choices

    score_matches = list(SCORE.finditer(content))
    if len(score_matches) != 1:
        _fail("content-team Markdown requires one supported score display")
    score_match = score_matches[0]
    paragraph_start = content.rfind("\n\n", 0, score_match.start()) + 2
    bottom_stem = _clean(content[paragraph_start : score_match.start()])
    if not bottom_stem:
        _fail("content-team Markdown requires a bottom stem before its score")
    upper = _clean(content[:paragraph_start])
    first_line, separator, remainder = upper.partition("\n")
    item = ITEM_LINE.fullmatch(first_line.strip())
    if item is None:
        _fail("content-team Markdown must start with one numbered item")
    upper = _clean("\n".join((item.group("text"), remainder)) if separator else item.group("text"))
    upper, inquiry = _extract_inquiry(upper)
    upper, labeled_blocks = _extract_labeled_blocks(upper)
    if inquiry is None:
        stem, visuals = _extract_visuals(upper)
        kinds = tuple(visual.kind for visual in visuals)
        visual_layout = {
            (): "NONE",
            ("IMAGE",): "IMAGE_ONLY",
            ("TABLE",): "TABLE_ONLY",
            ("IMAGE", "TABLE"): "IMAGE_TABLE",
            ("TABLE", "IMAGE"): "TABLE_IMAGE",
            ("IMAGE", "IMAGE"): "IMAGE_IMAGE",
            ("TABLE", "TABLE"): "TABLE_TABLE",
        }.get(kinds)
        if visual_layout is None:
            _fail("content-team Markdown visual layout is not canonical")
    else:
        stem, visuals, visual_layout = upper, (), "INQUIRY_BOX"

    answer_content = answer_match.group("content")
    if statement_values:
        if STATEMENT_COMBINATION.fullmatch(answer_content) is None:
            _fail("content-team combination answer must name ㄱ/ㄴ/ㄷ statements")
        answer_kind: Literal["STATEMENT_COMBINATION", "DIRECT_CHOICE"] = "STATEMENT_COMBINATION"
        answer_labels = cast(
            tuple[Literal["ㄱ", "ㄴ", "ㄷ"], ...],
            tuple(answer_content.split(", ")),
        )
        selected_choice_text = dict(choice_values)[answer_match.group("number")]
        selected_choice_labels = tuple(
            label for label in STATEMENT_LABELS if label in selected_choice_text
        )
        if selected_choice_labels != answer_labels:
            _fail("content-team answer combination differs from the selected choice")
        correct_labels = _labels_in_explanation(sections["[풀이 및 정답 해설]"])
        wrong_labels = _labels_in_explanation(sections["[오답 해설]"])
        if correct_labels != answer_labels or wrong_labels != tuple(
            label for label in STATEMENT_LABELS if label not in answer_labels
        ):
            _fail("content-team correct/wrong explanations do not partition ㄱ/ㄴ/ㄷ")
    else:
        answer_kind = "DIRECT_CHOICE"
        answer_labels = ()

    equation_sources = _equations(value)
    try:
        assert_content_team_equations_supported(equation_sources)
    except ContentTeamEquationError as exc:
        raise ContentTeamMarkdownError(str(exc)) from exc

    document = ContentTeamEditorialQuestion(
        source_sha256=f"sha256:{hashlib.sha256(data).hexdigest()}",
        item_number=int(item.group("number")),
        score_display=cast(Literal["2", "2.5", "3"], score_match.group("score")),
        stem=stem,
        bottom_stem=bottom_stem,
        inquiry=inquiry,
        labeled_blocks=labeled_blocks,
        visuals=visuals,
        visual_layout=cast(
            Literal[
                "NONE",
                "IMAGE_ONLY",
                "TABLE_ONLY",
                "IMAGE_TABLE",
                "TABLE_IMAGE",
                "IMAGE_IMAGE",
                "TABLE_TABLE",
                "INQUIRY_BOX",
            ],
            visual_layout,
        ),
        statements=cast(
            tuple[()] | tuple[ContentTeamStatement, ContentTeamStatement, ContentTeamStatement],
            tuple(
                ContentTeamStatement(label=cast(Literal["ㄱ", "ㄴ", "ㄷ"], label), text=text)
                for label, text in statement_values
            ),
        ),
        choices=tuple(
            ContentTeamChoice(number=cast(Literal["①", "②", "③", "④", "⑤"], number), text=text)
            for number, text in choice_values
        ),
        answer=(
            ContentTeamCombinationAnswer(
                number=cast(Literal["①", "②", "③", "④", "⑤"], answer_match.group("number")),
                statement_labels=answer_labels,
                answer_content=answer_content,
                raw_line=main_lines[answer_index].strip(),
            )
            if answer_kind == "STATEMENT_COMBINATION"
            else ContentTeamDirectChoiceAnswer(
                number=cast(Literal["①", "②", "③", "④", "⑤"], answer_match.group("number")),
                statement_labels=(),
                answer_content=answer_content,
                raw_line=main_lines[answer_index].strip(),
            )
        ),
        explanations=ContentTeamExplanationSections(
            authoring_intent=sections["[출제의도]"],
            concept_source=sections["[개념출처]"],
            correct_answer=sections["[풀이 및 정답 해설]"],
            wrong_answer=sections["[오답 해설]"],
        ),
        equation_sources=equation_sources,
    )
    validate_contract("content-team-editorial-question", document.model_dump(mode="json"))
    return document


def statement_texts(values: Iterable[ContentTeamStatement]) -> dict[str, str]:
    """Return O(1) label lookup without repeated ordered-list scans."""

    return {value.label: value.text for value in values}


def _table_markdown(table: ContentTeamTable) -> tuple[str, ...]:
    alignment = {
        "default": "---",
        "left": ":---",
        "right": "---:",
        "center": ":---:",
    }
    rows = (
        "| " + " | ".join(table.headers) + " |",
        "| " + " | ".join(alignment[value] for value in table.alignments) + " |",
        *("| " + " | ".join(row) + " |" for row in table.rows),
    )
    if table.label:
        return (f"표 {table.label}", "", *rows)
    return rows


def serialize_content_team_markdown(draft: ContentTeamEditorialDraft) -> bytes:
    """Materialize the one canonical Markdown spelling and prove its lossless round trip."""

    lines: list[str] = [f"{draft.item_number}. {draft.stem}", ""]
    for block in draft.labeled_blocks:
        lines.extend(("<자료>" if block.kind == "DATA" else "<조건>", block.content, ""))
    if draft.inquiry is not None:
        prefix = draft.inquiry.kind
        if draft.inquiry.goal is not None:
            lines.extend((f"[{prefix} 목표]", "", draft.inquiry.goal, ""))
        lines.extend(
            (
                f"[{prefix} 과정]",
                "",
                draft.inquiry.procedure,
                "",
                f"[{prefix} 결과]",
                "",
                draft.inquiry.result,
                "",
            )
        )
    else:
        for visual in draft.visuals:
            if isinstance(visual, ContentTeamImageSlot):
                lines.extend(("그림" + (f" {visual.label}" if visual.label else ""), ""))
            else:
                lines.extend((*_table_markdown(visual), ""))
    lines.extend((f"{draft.bottom_stem} [{draft.score_display}점]", ""))
    if draft.statements:
        lines.extend(("<보기>", ""))
        for statement in draft.statements:
            lines.extend((f"{statement.label}. {statement.text}", ""))
    for choice in draft.choices:
        lines.append(f"{choice.number} {choice.text}")
    lines.extend(("", draft.answer.raw_line, ""))
    for label, section in (
        ("[출제의도]", draft.explanations.authoring_intent),
        ("[개념출처]", draft.explanations.concept_source),
        ("[풀이 및 정답 해설]", draft.explanations.correct_answer),
        ("[오답 해설]", draft.explanations.wrong_answer),
    ):
        lines.extend((label, "", section, ""))
    data = ("\n".join(lines).rstrip() + "\n").encode("utf-8")
    reparsed = parse_content_team_markdown(data)
    expected = ContentTeamEditorialDraft.model_validate(
        draft.model_dump(mode="json", exclude={"schema_version", "source_sha256"})
    ).model_dump(mode="json")
    actual = reparsed.model_dump(mode="json", exclude={"schema_version", "source_sha256"})
    if actual != expected:
        raise ContentTeamMarkdownError("content-team Markdown round trip changed the typed draft")
    return data
