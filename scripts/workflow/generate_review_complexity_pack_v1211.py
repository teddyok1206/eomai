#!/usr/bin/env python3
"""Create immutable Content Pack 1.20.11 for exact review complexity scoring."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "content/packs/generated-knowledge-item/1.20.10"
TARGET = ROOT / "content/packs/generated-knowledge-item/1.20.11"

REVIEW_RULE = """

### 구조 복잡도 점수의 명시적 합산

PRIMARY 결과를 제출하기 직전에 authoring `output.draft`의 실제 배열·필드를 다시 읽고 다음 여섯
indicator를 각각 0 또는 1로 계산한 뒤 합산한다.

```text
has_visuals       = 1 if len(visuals) > 0 else 0
has_two_visuals   = 1 if len(visuals) == 2 else 0
has_statements    = 1 if len(statements) > 0 else 0
has_inquiry       = 1 if inquiry is not null else 0
has_equations     = 1 if len(equation_sources) > 0 else 0
has_two_blocks    = 1 if len(labeled_blocks) == 2 else 0
score             = min(sum(the six indicators), 10)
```

예를 들어 `visuals`가 1개이고 `statements`가 3개이며 inquiry/equation_sources/labeled_blocks가
없으면 점수는 반드시 2다. statements의 개수 자체를 더하지는 않지만, 하나 이상이면 1점을 반드시
더한다.
기억이나 target 개수로 추측하지 말고 exact draft에서 계산한 값을
`escalation_assessment.structural_complexity_score`에 기록한다.
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
    pack["pack"]["version"] = "1.20.11"
    pack["pack"]["description"] = "Exact-source variation with explicit review complexity scoring"
    pack_path.write_text(
        yaml.safe_dump(pack, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    profile_path = target / "profiles/generated-knowledge-review.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["profile"]["version"] = "12.1.3"
    profile_path.write_text(
        yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    prompt_path = target / "prompt-templates/review.md"
    prompt = prompt_path.read_text(encoding="utf-8")
    marker = "### 구조 복잡도 점수의 명시적 합산"
    if marker in prompt:
        raise ValueError("review complexity rule already exists")
    prompt_path.write_text(prompt.rstrip() + REVIEW_RULE, encoding="utf-8")


def main() -> None:
    if not TARGET.exists():
        _generate(TARGET)
        return
    with tempfile.TemporaryDirectory(prefix="eom-review-complexity-pack-") as temp_dir:
        generated = Path(temp_dir) / "1.20.11"
        _generate(generated)
        if _tree_bytes(TARGET) != _tree_bytes(generated):
            raise ValueError("generated Content Pack 1.20.11 has drifted")


if __name__ == "__main__":
    main()
