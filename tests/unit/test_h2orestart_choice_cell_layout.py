"""Exercise the actual bounded Java layout rule, not a Python reimplementation."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def java_layout(tmp_path_factory):
    if shutil.which("java") is None:
        pytest.skip("installed Java compiler module is required")
    target = tmp_path_factory.mktemp("choice-cell-java")
    subprocess.run(
        [
            "java",
            "-m",
            "jdk.compiler/com.sun.tools.javac.Main",
            "-source",
            "8",
            "-target",
            "8",
            "-encoding",
            "UTF-8",
            "-d",
            str(target),
            str(ROOT / "third_party/h2orestart/0.7.14-eom.3/HancomChoiceCellLayout.java"),
            str(ROOT / "tests/fixtures/h2orestart/ChoiceCellCases.java"),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return target


@pytest.mark.parametrize(
    ("text", "width", "height", "left", "right", "indent", "expected"),
    [
        ("①", 1252, 1150, 2300, 0, 0, 204),
        ("②", 1252, 1150, 2300, 0, 0, 204),
        ("③", 1252, 1150, 2300, 0, 0, 204),
        ("④", 1252, 1150, 2300, 0, 0, 204),
        ("⑤\r", 1252, 1150, 2300, 0, 0, 204),
        ("①", 1252, 1150, 100, 0, 0, 100),
        ("①", 1252, 1150, 2300, 100, 0, 104),
        ("①", 1000, 1150, 2300, 0, 0, 0),
        ("①", 1252, 1150, 2300, 0, 200, 2300),
        ("①", 1252, 1150, -200, 0, 0, -200),
        ("① A", 1252, 1150, 2300, 0, 0, 2300),
        ("1", 1252, 1150, 2300, 0, 0, 2300),
        ("⑥", 1252, 1150, 2300, 0, 0, 2300),
        ("자료", 1252, 1150, 2300, 0, 0, 2300),
        ("", 1252, 1150, 2300, 0, 0, 2300),
        ("①", 0, 1150, 2300, 0, 0, 2300),
        ("①", 1252, 0, 2300, 0, 0, 2300),
        ("①", 2147483647, 1150, 2300, 0, 0, 2300),
    ],
)
def test_actual_java_choice_spacing(
    java_layout, text, width, height, left, right, indent, expected
):
    done = subprocess.run(
        [
            "java",
            "-cp",
            str(java_layout),
            "ChoiceCellCases",
            text,
            *(str(n) for n in (width, height, left, right, indent)),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert int(done.stdout) == expected
