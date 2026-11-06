"""Exercise the shipped Java translator itself, without LibreOffice, DB or model usage."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STYLE = ROOT / "third_party/h2orestart/0.7.14-eom.2/HancomEquationStyle.java"


@pytest.fixture(scope="module")
def java_classes(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if shutil.which("java") is None:
        pytest.skip("Java runtime/compiler module is required for the real vendor translation test")
    output = tmp_path_factory.mktemp("equation-java")
    subprocess.run(
        [
            "java",
            "-m",
            "jdk.compiler/com.sun.tools.javac.Main",
            "-source",
            "8",
            "-target",
            "8",
            "-d",
            str(output),
            str(STYLE),
            str(ROOT / "tests/fixtures/h2orestart/EquationStyleCases.java"),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return output


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("rmA", "nitalic { A }"),
        ("rm A", "nitalic {  A }"),
        ("rmDNA", "nitalic { DNA }"),
        ("rm 4`A", "nitalic {  4`A }"),
        ("rm12", "nitalic { 12 }"),
        ("rm rmX", "nitalic {  nitalic { X } }"),
        ("RMX", "nitalic { X }"),
        ("rmbold A", "nitalic { bold {  A } }"),
        ("{rmA+B}+C", "{nitalic { A+B }}+C"),
        ("rm A+B it C", "nitalic {  A+B italic {  C } }"),
        ("x_{rmmax}", "x_{nitalic { max }}"),
        ('"rmA"', '"rmA"'),
        ('"DNA" + rmB', '"DNA" + nitalic { B }'),
        ("thermal + item + norm", "thermal + item + norm"),
        ("rmA over rmB", "nitalic { A over nitalic { B } }"),
        ("{a+b} over {c+d}", "{a+b} over {c+d}"),
        ("x_1^2 + alpha", "x_1^2 + alpha"),
        ("MATRIX {a & b # c & d}", "MATRIX {a & b # c & d}"),
        ("TIMES", '"\u00d7"'),
        ("TIMES ", '"\u00d7"'),
        ("-", '"\u2212"'),
        ("+", '"+"'),
        ("=", '"="'),
        ("rm TIMES", '"\u00d7"'),
        ("{TIMES}", '"\u00d7"'),
        ("a TIMES b", "a TIMES b"),
        ("-x", "-x"),
        ("a-b", "a-b"),
        ("``+``", "``+``"),
        ('"-"', '"-"'),
        ("rmNa^+", 'nitalic { Na^{"+"} }'),
        ("rmCl^-", 'nitalic { Cl^{"\u2212"} }'),
        ("rmCu^{2+}", 'nitalic { Cu^{"2+"} }'),
        ("rmSO_4^{2-}", 'nitalic { SO_4^{"2\u2212"} }'),
        ("10^{-3}", "10^{-3}"),
        ("x^{2+y}", "x^{2+y}"),
    ],
)
def test_real_java_translation(java_classes: Path, script: str, expected: str) -> None:
    result = subprocess.run(
        ["java", "-cp", str(java_classes), "EquationStyleCases", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.stdout == expected


@pytest.mark.parametrize(
    "script",
    ['"unterminated', "{rmA", "rmA}", "{" * 129 + "A" + "}" * 129, "A" * 65537],
    ids=["quote", "opening", "closing", "depth", "length"],
)
def test_real_java_rejects_unsafe_bounds(java_classes: Path, script: str) -> None:
    result = subprocess.run(
        ["java", "-cp", str(java_classes), "EquationStyleCases", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert "IllegalArgumentException" in result.stderr
