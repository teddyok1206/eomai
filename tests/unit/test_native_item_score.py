"""Native score observations never select a guessed marker or alter source bytes."""

from decimal import Decimal

import pytest
from eom_hwpx_contracts.native_item_score import observe_native_printed_score

PREFIX = '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'


def section(body):
    return (PREFIX + body + "</hs:sec>").encode()


def paragraph(text):
    return "<hp:p><hp:run><hp:t>" + text + "</hp:t></hp:run></hp:p>"


@pytest.mark.parametrize(
    "value", ["0", "1.5", "2", "2.5", "2.50", "0.25", "100", "\uff11\uff0e\uff15"]
)
def test_exact_value_and_original_literal_are_distinct(value):
    payload = section(paragraph("원문 [" + value + "점]"))
    before = payload[:]
    result = observe_native_printed_score(payload)
    assert result.state == "MATCHED" and len(result.candidates) == 1
    assert result.candidates[0].printed_literal == value
    assert result.candidates[0].points == Decimal("1.5" if value == "\uff11\uff0e\uff15" else value)
    assert payload == before


def test_runs_join_but_unrelated_paragraphs_never_form_a_score():
    runs = "<hp:p><hp:run><hp:t>[1.</hp:t></hp:run><hp:run><hp:t>5점]</hp:t></hp:run></hp:p>"
    assert observe_native_printed_score(section(runs)).candidates[0].points == Decimal("1.5")
    assert (
        observe_native_printed_score(section(paragraph("[1.5") + paragraph("점]"))).state
        == "ABSENT"
    )
    nested = (
        "<hp:p><hp:run><hp:tbl><hp:tr><hp:tc>"
        + paragraph("[2.5점]")
        + "</hp:tc></hp:tr></hp:tbl></hp:run></hp:p>"
    )
    observed = observe_native_printed_score(section(nested))
    assert observed.state == "MATCHED" and len(observed.candidates) == 1


def test_absence_is_not_a_zero_claim_and_equal_repeated_markers_stay_ambiguous():
    assert observe_native_printed_score(section(paragraph("배점 표시 없음"))).candidates == ()
    for text in ("[2점] [2점]", "[1.5점] [2.5점]"):
        result = observe_native_printed_score(section(paragraph(text)))
        assert result.state == "AMBIGUOUS" and len(result.candidates) == 2


def test_native_space_controls_preserve_text_but_line_breaks_do_not_join_paragraphs():
    text = "[<hp:fwSpace/>1.5<hp:nbSpace/>점]"
    assert observe_native_printed_score(section(paragraph(text))).candidates[0].points == Decimal(
        "1.5"
    )
    assert (
        observe_native_printed_score(section(paragraph("[1.5<hp:lineBreak/>점]"))).state == "ABSENT"
    )
    with pytest.raises(ValueError, match="TEXT_UNSUPPORTED"):
        observe_native_printed_score(section(paragraph("<hp:unknown/>[2점]")))


@pytest.mark.parametrize("value", ["-1", "NaN", "1e2", "100.5", "101", "1.1234567"])
def test_invalid_printed_markers_are_not_reinterpreted_as_unprinted(value):
    with pytest.raises(ValueError, match="PRINTED_SCORE_INVALID"):
        observe_native_printed_score(section(paragraph("[" + value + "점]")))


@pytest.mark.parametrize(
    "payload",
    [b"<!DOCTYPE a><a/>", b'<!ENTITY a "x">', b"\x00", b"\xff", b"<foreign/>", b"<broken"],
)
def test_unsafe_xml_fails_before_observing_a_score(payload):
    with pytest.raises(ValueError, match="SCORE_XML_INVALID"):
        observe_native_printed_score(payload)


def test_depth_and_candidate_bounds_are_closed():
    with pytest.raises(ValueError, match="SCORE_XML_LIMIT"):
        observe_native_printed_score(section("<hp:p>" * 130 + "</hp:p>" * 130))
    with pytest.raises(ValueError, match="CANDIDATE_LIMIT"):
        observe_native_printed_score(section(paragraph("[2점] " * 65)))
