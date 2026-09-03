from __future__ import annotations

from copy import deepcopy

import pytest
from eom_hwpx_contracts import ContentTeamEditorialQuestion, validate_contract
from eom_hwpx_contracts.content_team_markdown import (
    ContentTeamMarkdownError,
    parse_content_team_markdown,
    serialize_content_team_markdown,
    statement_texts,
)
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

GENERAL_ITEM = """1. 그림과 표는 두 대상의 측정 결과를 나타낸 것이다.

그림

| 구간 | 속력 | 방향 |
|---|---:|:---:|
| A | $3$ | 동 |
| B | $5$ | 서 |

이에 대한 설명으로 옳은 것만을 <보기>에서 있는 대로 고른 것은? [2.5점]

<보기>

ㄱ. A의 속력은 $3$이다.

ㄴ. B는 동쪽으로 운동한다.

ㄷ. B의 속력은 A보다 크다.

① ㄱ
② ㄴ
③ ㄱ, ㄷ
④ ㄴ, ㄷ
⑤ ㄱ, ㄴ, ㄷ

정답 : ③ (ㄱ, ㄷ)

[출제의도]

ㄱ. 표에서 속력을 읽는다.
ㄴ. 운동 방향을 구분한다.
ㄷ. 두 속력을 비교한다.

[개념출처]

이 문항은 주어진 측정 자료를 해석하는 문항입니다.

[풀이 및 정답 해설]

두 물체의 속력과 방향을 각각 읽는다.
ㄱ. A의 속력은 $3$이므로 옳다.
ㄷ. $5>3$이므로 옳다.

[오답 해설]

ㄴ. B의 방향은 서쪽이므로 틀리다.
"""


INQUIRY_ITEM = """2. 물질의 온도 변화 실험을 수행하였다.

[실험 과정]

(가) 같은 양의 물을 두 비커에 넣는다.
(나) 한 비커만 가열한다.
(다) 같은 시간에 온도를 측정한다.

[실험 결과]

| 비커 | 온도 변화 |
|---|---:|
| A | $+5$ |
| B | $0$ |

이에 대한 설명으로 옳은 것만을 <보기>에서 있는 대로 고른 것은? [2점]

<보기>

ㄱ. A를 가열하였다.
ㄴ. B의 온도는 변하지 않았다.
ㄷ. A의 온도 변화는 B보다 작다.

① ㄱ
② ㄴ
③ ㄱ, ㄴ
④ ㄴ, ㄷ
⑤ ㄱ, ㄴ, ㄷ

정답 : ③ (ㄱ, ㄴ)

[출제의도]

실험 결과를 해석한다.

[개념출처]

이 문항은 환경과 에너지 단원 중 열에 대한 문항입니다.

[풀이 및 정답 해설]

ㄱ. A의 온도만 증가했으므로 옳다.
ㄴ. B의 온도 변화가 $0$이므로 옳다.

[오답 해설]

ㄷ. $+5$는 $0$보다 크므로 틀리다.
"""


LABELED_BLOCK_ITEM = """7. 다음은 관측 대상 X에 대한 자료이다.

<자료>
대상 X에서 특성 P가 관측되었다.

[조건]
관측 과정에서 외부 조건은 일정하였다.

이에 대한 설명으로 옳은 것만을 <보기>에서 있는 대로 고른 것은? [3점]

<보기>

ㄱ. 자료에서 대상 X의 특성 P를 확인할 수 있다.
ㄴ. 관측 중 외부 조건이 변하였다.
ㄷ. 자료와 조건을 함께 사용하여 판단할 수 있다.

① ㄱ
② ㄴ
③ ㄱ, ㄷ
④ ㄴ, ㄷ
⑤ ㄱ, ㄴ, ㄷ

정답 : ③ (ㄱ, ㄷ)

[출제의도]

자료와 조건의 관계를 해석한다.

[개념출처]

이 문항은 자료와 조건을 함께 해석하는 형식 예시입니다.

[풀이 및 정답 해설]

ㄱ. 자료에 특성 P가 명시되어 있으므로 옳다.
ㄷ. 두 블록을 함께 사용하여 판단할 수 있으므로 옳다.

[오답 해설]

ㄴ. 조건에 외부 조건이 일정하다고 제시되어 있으므로 틀리다.
"""


DIRECT_CHOICE_ITEM = """8. 다음은 요청에서 주어진 분류 자료이다.

자료에 대한 설명으로 알맞은 것은? [2점]

① 첫 번째 설명
② 두 번째 설명
③ 세 번째 설명
④ 네 번째 설명
⑤ 다섯 번째 설명

정답 : ② (두 번째 설명)

[출제의도]

주어진 자료의 분류 기준을 적용한다.

[개념출처]

요청에 고정된 근거를 사용한다.

[풀이 및 정답 해설]

분류 기준에 따르면 두 번째 설명이 알맞다.

[오답 해설]

나머지 설명은 주어진 분류 기준과 일치하지 않는다.
"""


def test_general_prompt_markdown_projects_exact_handoff_layout() -> None:
    document = parse_content_team_markdown(GENERAL_ITEM.encode())
    raw = document.model_dump(mode="json")

    validate_contract("content-team-editorial-question", raw)
    assert ContentTeamEditorialQuestion.model_validate(raw) == document
    assert document.score_display == "2.5"
    assert document.visual_layout == "IMAGE_TABLE"
    assert tuple(visual.kind for visual in document.visuals) == ("IMAGE", "TABLE")
    assert document.answer.raw_line == "정답 : ③ (ㄱ, ㄷ)"
    assert document.answer.statement_labels == ("ㄱ", "ㄷ")
    assert statement_texts(document.statements)["ㄴ"] == "B는 동쪽으로 운동한다."
    assert document.equation_sources == ("3", "5", "3", "3", "5>3")


def test_inquiry_table_stays_inside_inquiry_box() -> None:
    document = parse_content_team_markdown(INQUIRY_ITEM.encode())

    assert document.visual_layout == "INQUIRY_BOX"
    assert document.visuals == ()
    assert document.inquiry is not None
    assert document.inquiry.kind == "실험"
    assert document.inquiry.goal is None
    assert "| 비커 | 온도 변화 |" in document.inquiry.result
    assert document.equation_sources == ("+5", "0", "0", "+5", "0")


def test_labeled_blocks_preserve_arbitrary_subject_content_without_defaults() -> None:
    document = parse_content_team_markdown(LABELED_BLOCK_ITEM.encode())

    assert document.item_number == 7
    assert document.score_display == "3"
    assert document.visual_layout == "NONE"
    assert tuple(block.kind for block in document.labeled_blocks) == ("DATA", "CONDITION")
    assert document.labeled_blocks[0].content == "대상 X에서 특성 P가 관측되었다."
    assert document.labeled_blocks[1].content == "관측 과정에서 외부 조건은 일정하였다."


def test_direct_choice_form_from_source_prompt_and_program_round_trips() -> None:
    document = parse_content_team_markdown(DIRECT_CHOICE_ITEM.encode())

    assert document.statements == ()
    assert document.answer.answer_kind == "DIRECT_CHOICE"
    assert document.answer.statement_labels == ()
    assert document.answer.answer_content == "두 번째 설명"
    assert document.answer.raw_line == "정답 : ② (두 번째 설명)"
    assert serialize_content_team_markdown(document) == DIRECT_CHOICE_ITEM.encode()


@pytest.mark.parametrize(
    "source,match",
    [
        (GENERAL_ITEM.replace("1. 그림과", "# 1. 그림과"), "presentation syntax"),
        (GENERAL_ITEM.replace("두 대상", "*두 대상*"), "presentation syntax"),
        (GENERAL_ITEM.replace("그림\n", "[그림 자리]\n", 1), "noncanonical visual marker"),
        (GENERAL_ITEM.replace("③ ㄱ, ㄷ", "③ ㄱ, ㄴ", 1), "answer combination"),
        (GENERAL_ITEM.replace("ㄴ. B의 방향은 서쪽이므로 틀리다.", "ㄷ. 틀리다."), "partition"),
        (INQUIRY_ITEM.replace("(다) 같은 시간에 온도를 측정한다.\n", ""), "three ordered"),
        (
            LABELED_BLOCK_ITEM.replace("<자료>\n", "<조건>\n", 1),
            "unique and DATA precedes CONDITION",
        ),
    ],
)
def test_prompt_program_contract_fails_closed(source: str, match: str) -> None:
    with pytest.raises(ContentTeamMarkdownError, match=match):
        parse_content_team_markdown(source.encode())


def test_json_schema_and_pydantic_both_reject_layout_drift() -> None:
    value = parse_content_team_markdown(GENERAL_ITEM.encode()).model_dump(mode="json")
    forged = deepcopy(value)
    forged["visuals"][0]["label"] = "(가)"

    with pytest.raises(ValidationError, match="canonical layout"):
        ContentTeamEditorialQuestion.model_validate(forged)
    forged["visuals"][0]["label"] = "(다)"
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("content-team-editorial-question", forged)


def test_decimal_score_is_preserved_not_rounded() -> None:
    document = parse_content_team_markdown(GENERAL_ITEM.encode())

    assert document.score_display == "2.5"
    assert document.model_dump(mode="json")["score_display"] == "2.5"


@pytest.mark.parametrize(
    "source", [GENERAL_ITEM, INQUIRY_ITEM, LABELED_BLOCK_ITEM, DIRECT_CHOICE_ITEM]
)
def test_typed_draft_has_one_lossless_canonical_markdown_materialization(source: str) -> None:
    parsed = parse_content_team_markdown(source.encode())

    materialized = serialize_content_team_markdown(parsed)
    reparsed = parse_content_team_markdown(materialized)

    assert reparsed.model_dump(mode="json", exclude={"source_sha256"}) == parsed.model_dump(
        mode="json", exclude={"source_sha256"}
    )
