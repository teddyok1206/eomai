from __future__ import annotations

import pytest
from eom_hwpx_contracts.content_team_equations import (
    ContentTeamEquationError,
    classify_content_team_equation,
    project_content_team_equation_script,
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
        r"v=\frac{l}{t}=0.30",
        "v=3+4=7",
        "v=l/t=0.30",
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
        "v=x=0.30",
        "v=3=3",
        "a+",
        "../x",
        "<script>",
        "x{",
    ],
)
def test_unsupported_or_ambiguous_equations_fail_before_render(source: str) -> None:
    with pytest.raises(ContentTeamEquationError):
        classify_content_team_equation(source)


@pytest.mark.parametrize(
    ("source", "script"),
    [
        ("3", "3"),
        ("x", "x"),
        (r"\frac{3}{2}", "{3} over {2}"),
        ("v_{0}", "v _{0}"),
        ("x^{2}", "x ^{2}"),
        ("x_{0}^{2}", "x _{0}^{2}"),
        ("H_{2}O", "rmH _{2} O"),
        ("SO_{4}^{2-}", "rmSO _{4}^{2-}"),
        ("x'", "x prime"),
        ("a:b=2:3", "a`:`b`=`2`:`3"),
        ("5 > 3", "5>3"),
        ("300k", "300k"),
        ("+5", "+5"),
        ("a + b - c", "a+b-c"),
        ("y=20+15t-5t^{2}", "y=20+15t-5t^{2}"),
        (r"s=ut+\frac{1}{2}at^{2}", "s=ut+{1} over {2} at ^{2}"),
        (r"v=\frac{l}{t}=0.30", "v={l} over {t}=0.30"),
        ("v=3+4=7", "v=3+4=7"),
        ("v=l/t=0.30", "v=l/t=0.30"),
        (r"2.0\times10^{-3}", "2.0times10^{-3}"),
        (
            r"\frac{3}{2}\times\frac{240}{1.20}k=300k",
            "{3} over {2}times{240} over {1.20} k=300k",
        ),
    ],
)
def test_supported_equations_have_deterministic_hancom_scripts(source: str, script: str) -> None:
    assert project_content_team_equation_script(source) == script


def test_equation_projection_rejects_the_same_unsupported_grammar() -> None:
    with pytest.raises(ContentTeamEquationError):
        project_content_team_equation_script(r"\sqrt{2}")
