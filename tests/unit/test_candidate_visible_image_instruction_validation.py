from __future__ import annotations

import pytest
from eom_catalog_contracts import candidate_visible_image_instruction_paths


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (
            "그림에는 O, P, Q, 지면, x축, y축 및 포물선 궤적을 표시한다.",
            ("/labeled_blocks/0/content",),
        ),
        ("순백 배경의 흑백 선화로 만든다.", ("/labeled_blocks/0/content",)),
        (
            "800\N{MULTIPLICATION SIGN}500 픽셀의 SVG로 렌더링한다.",
            ("/labeled_blocks/0/content",),
        ),
        (
            "그림의 P와 Q는 각각 t=1 s와 t=2 s인 공의 위치이다.",
            (),
        ),
        ("그림에는 O, P, Q가 표시되어 있다.", ()),
    ],
)
def test_candidate_data_instruction_detection_is_narrow_and_stable(
    content: str, expected: tuple[str, ...]
) -> None:
    assert (
        candidate_visible_image_instruction_paths(
            {
                "stem": "그림은 공의 운동을 나타낸다.",
                "bottom_stem": "옳은 것은?",
                "labeled_blocks": [{"kind": "DATA", "content": content}],
                "statements": [],
                "choices": [],
            }
        )
        == expected
    )


def test_inquiry_may_direct_candidate_to_draw_a_graph_without_becoming_a_render_prompt() -> None:
    assert (
        candidate_visible_image_instruction_paths(
            {
                "stem": "다음 탐구를 수행한다.",
                "bottom_stem": "옳은 것은?",
                "labeled_blocks": [],
                "inquiry": {
                    "goal": "운동을 분석한다.",
                    "procedure": "(가) 측정한다.\n(나) 그래프를 그린다.\n(다) 비교한다.",
                    "result": "속력이 증가하였다.",
                },
                "statements": [],
                "choices": [],
            }
        )
        == ()
    )


def test_technical_image_prompt_vocabulary_is_rejected_in_any_candidate_field() -> None:
    assert candidate_visible_image_instruction_paths(
        {
            "stem": "그림은 공의 운동을 나타낸다.",
            "bottom_stem": "옳은 것은?",
            "labeled_blocks": [],
            "statements": [{"label": "ㄱ", "text": "required_labels에 O를 추가한다."}],
            "choices": [{"number": "①", "text": "옳다"}],
        }
    ) == ("/statements/0/text",)
