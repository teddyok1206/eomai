from __future__ import annotations

import pytest
from eom_hwpx_contracts.content_team_equations import (
    ContentTeamEquationError,
    classify_content_team_equation,
)


@pytest.mark.parametrize(
    "source",
    [
        "3",
        "x",
        r"\frac{3}{2}",
        "v_{0}",
        "x^{2}",
        "x_{0}^{2}",
        "H_{2}O",
        "SO_{4}^{2-}",
        "x'",
        "a:b=2:3",
        "5>3",
        "300k",
        "+5",
        "a+b-c",
        "y=20+15t-5t^{2}",
        "v_{y}=15-10t",
        "v_{y}=-5",
        "x=20t",
        r"s=ut+\frac{1}{2}at^{2}",
        r"2.0\times10^{-3}",
        r"\frac{3}{2}\times\frac{240}{1.20}k=300k",
    ],
)
def test_documented_equation_families_are_subject_neutral(source: str) -> None:
    assert classify_content_team_equation(source)


@pytest.mark.parametrize(
    "source",
    [
        "",
        "한글수식",
        r"\sqrt{2}",
        "8--5",
        "x=y=z",
        "a+",
        "../x",
        "<script>",
        "x{",
    ],
)
def test_unsupported_or_ambiguous_equations_fail_before_render(source: str) -> None:
    with pytest.raises(ContentTeamEquationError):
        classify_content_team_equation(source)
