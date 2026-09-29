#!/usr/bin/env python3
"""Create immutable Content Pack 1.20.7 with one-source IMAGE presentation rules."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "content/packs/generated-knowledge-item/1.20.6"
TARGET = ROOT / "content/packs/generated-knowledge-item/1.20.7"

AUTHORING_RULE = """

### IMAGE 자료의 단일 제시 규칙

IMAGE의 DATA block과 ordered IMAGE slot은 서로 다른 두 자료가 아니라 하나의 학생 공개 자료다.
stem에서 이를 `자료와 그림`, `그림과 자료`, `<자료>와 그림`처럼 병렬로 두 번 지칭하지 마라.
대상과 상황을 한 번만 자연스럽게 소개하고, DATA에는 같은 그림을 해석하는 데 필요한 사실만 둔다.
`<자료>`, `[자료]`, `<조건>`, `[조건]`은 deterministic Markdown serializer가 block kind로부터 만드는
구조 marker이므로 stem이나 bottom_stem 문자열에 직접 쓰지 마라. IMAGE 한 개는 하나의 표제 없는
자료 박스 안에 DATA와 그림을 함께 제시하는 양식이며, 빈 두 번째 칸이나 `(가)/(나)`를 만들지 않는다.
IMAGE 두 개일 때만 같은 자료 박스 안에서 두 칸과 editable `(가)`, `(나)` label을 사용한다.
"""

REVIEW_RULE = """

### IMAGE 자료 표현 중복 검토

IMAGE의 DATA block과 IMAGE slot은 하나의 복합 자료다. stem이나 bottom_stem이 이를 `자료와 그림`,
`그림과 자료`, `<자료>와 그림`처럼 두 독립 자료로 중복 지칭하거나 literal `<자료>`, `[자료]`,
`<조건>`, `[조건]` marker를 문장 안에 포함하면 `MATERIAL_PRESENTATION_REDUNDANT` blocking
finding으로 반환한다. IMAGE 한 개에 `(가)/(나)` 또는 빈 두 번째 칸을 요구하는 표현도 같은
finding이다. 이는 authoring 문구와 layout으로 고칠 수 있는 finding이며 과학 내용이나 근거를 임의로
바꾸라는 뜻이 아니다.
IMAGE 두 개의 ordered `(가)/(나)`와 standalone DATA/CONDITION block의 정식 표제는 차단하지 않는다.
"""


def _tree_bytes(root: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(root): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _generate(target: Path) -> None:
    if target.exists():
        raise FileExistsError(target)
    shutil.copytree(SOURCE, target)

    pack_path = target / "pack.yaml"
    pack = yaml.safe_load(pack_path.read_text(encoding="utf-8"))
    pack["pack"]["version"] = "1.20.7"
    pack["pack"]["description"] = (
        "Graph-grounded review and assessment line art with single-source IMAGE presentation"
    )
    pack_path.write_text(
        yaml.safe_dump(pack, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    for relative, version in (
        ("profiles/generated-knowledge-authoring.yaml", "12.0.1"),
        ("profiles/generated-knowledge-review.yaml", "12.0.3"),
    ):
        profile_path = target / relative
        profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
        profile["profile"]["version"] = version
        profile_path.write_text(
            yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

    for relative, rule, marker in (
        (
            "prompt-templates/authoring.md",
            AUTHORING_RULE,
            "### IMAGE 자료의 단일 제시 규칙",
        ),
        (
            "prompt-templates/review.md",
            REVIEW_RULE,
            "### IMAGE 자료 표현 중복 검토",
        ),
    ):
        prompt_path = target / relative
        prompt = prompt_path.read_text(encoding="utf-8")
        if marker in prompt:
            raise ValueError(f"presentation rule already exists in {relative}")
        prompt_path.write_text(prompt.rstrip() + rule, encoding="utf-8")


def main() -> None:
    if not TARGET.exists():
        _generate(TARGET)
        return
    with tempfile.TemporaryDirectory(prefix="eom-material-presentation-pack-") as temp_dir:
        generated = Path(temp_dir) / "1.20.7"
        _generate(generated)
        if _tree_bytes(TARGET) != _tree_bytes(generated):
            raise ValueError("generated Content Pack 1.20.7 has drifted")


if __name__ == "__main__":
    main()
