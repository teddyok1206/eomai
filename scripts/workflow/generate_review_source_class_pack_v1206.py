#!/usr/bin/env python3
"""Create immutable Content Pack 1.20.6 with literal review source-class binding."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "content/packs/generated-knowledge-item/1.20.5"
TARGET = ROOT / "content/packs/generated-knowledge-item/1.20.6"

REVIEW_RULE = """

### Literal source-class binding

`required_source_classes`의 값은 검토 target의 의미를 해석해서 만들지 않는다. 각
`selected_evidence_ids`를 `references/evidence/manifest.json`에서 exact ID로 찾고, 그 entry의
`source.source_class` literal을 한 글자도 바꾸지 않고 복사한 뒤 사전순 정렬하고 중복 제거한다.
`CURRICULUM_SCOPE` target이라고 해서 source class가 `CURRICULUM`인 것은 아니다. manifest가
`TEXTBOOK`이라고 선언하면 반드시 `TEXTBOOK`으로 기록한다. 예를 들어 선택한 두 entry의 literal
class가 `PAST_EXAM`과 `TEXTBOOK`이면 required 값은 정확히 `["PAST_EXAM", "TEXTBOOK"]`이다.
target 이름, purpose, 교육과정 판단 의미를 source-class enum으로 번역하지 마라. 제출 직전에
모든 target에 대해 selected ID -> manifest entry -> exact literal class를 다시 대조하고,
일치시킬 수 없으면 역할 실행을 실패시킨다.
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
    pack["pack"]["version"] = "1.20.6"
    pack["pack"]["description"] = (
        "Graph-grounded review with literal Evidence source-class binding and assessment line art"
    )
    pack_path.write_text(
        yaml.safe_dump(pack, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    profile_path = target / "profiles/generated-knowledge-review.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["profile"]["version"] = "12.0.2"
    profile_path.write_text(
        yaml.safe_dump(profile, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    prompt_path = target / "prompt-templates/review.md"
    prompt = prompt_path.read_text(encoding="utf-8")
    if "### Literal source-class binding" in prompt:
        raise ValueError("literal source-class rule already exists")
    prompt_path.write_text(prompt.rstrip() + REVIEW_RULE, encoding="utf-8")


def main() -> None:
    if not TARGET.exists():
        _generate(TARGET)
        return
    with tempfile.TemporaryDirectory(prefix="eom-review-source-class-pack-") as temp_dir:
        generated = Path(temp_dir) / "1.20.6"
        _generate(generated)
        if _tree_bytes(TARGET) != _tree_bytes(generated):
            raise ValueError("generated Content Pack 1.20.6 has drifted")


if __name__ == "__main__":
    main()
