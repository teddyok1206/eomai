#!/usr/bin/env python3
"""Create immutable Content Pack 1.20.10 for review pointer-root closure."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "content/packs/generated-knowledge-item/1.20.9"
TARGET = ROOT / "content/packs/generated-knowledge-item/1.20.10"

REVIEW_RULE = """

### 검토 결과 전체의 semantic pointer 최종 검사

결과 JSON을 제출하기 직전에 `output` 아래의 모든 `draft_json_paths` 배열을 재귀적으로 모아 각
pointer의 첫 segment를 검사한다. 허용되는 첫 segment는 정확히 `answer`, `bottom_stem`, `choices`,
`explanations`, `inquiry`, `labeled_blocks`, `statements`, `stem`, `visuals`뿐이다. 이 검사는
answer/choice/statement 진단, assessment, verification target, candidate finding, citation을 모두
포함한다.

특히 `equation_sources`는 draft에 실제 문자열 leaf가 있어도 검토용 semantic root가 아니므로 절대
가리키지 마라. 수식 판단은 그 식을 학생에게 제시하거나 해설하는 `statements/*/text`,
`labeled_blocks/*/content`, `explanations/*` 등의 실제 semantic scalar leaf를 가리킨다. 허용 목록
밖의 root가 하나라도 있으면 그 pointer를 허용 leaf로 고치기 전에는 결과를 제출하지 마라.
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
    pack["pack"]["version"] = "1.20.10"
    pack["pack"]["description"] = "Exact-source variation with closed semantic review pointer roots"
    pack_path.write_text(
        yaml.safe_dump(pack, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    profile_path = target / "profiles/generated-knowledge-review.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["profile"]["version"] = "12.1.2"
    profile_path.write_text(
        yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    prompt_path = target / "prompt-templates/review.md"
    prompt = prompt_path.read_text(encoding="utf-8")
    marker = "### 검토 결과 전체의 semantic pointer 최종 검사"
    if marker in prompt:
        raise ValueError("review pointer-root rule already exists")
    prompt_path.write_text(prompt.rstrip() + REVIEW_RULE, encoding="utf-8")


def main() -> None:
    if not TARGET.exists():
        _generate(TARGET)
        return
    with tempfile.TemporaryDirectory(prefix="eom-variation-review-pointer-pack-") as temp_dir:
        generated = Path(temp_dir) / "1.20.10"
        _generate(generated)
        if _tree_bytes(TARGET) != _tree_bytes(generated):
            raise ValueError("generated Content Pack 1.20.10 has drifted")


if __name__ == "__main__":
    main()
