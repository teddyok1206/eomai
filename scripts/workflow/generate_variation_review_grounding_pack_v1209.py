#!/usr/bin/env python3
"""Create immutable Content Pack 1.20.9 for review evidence-axis binding."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "content/packs/generated-knowledge-item/1.20.8"
TARGET = ROOT / "content/packs/generated-knowledge-item/1.20.9"

REVIEW_RULE = """

### Graph 근거의 판정 필드 결속

`knowledge_source_mode=graph_grounded`이면 evidence reference를 선언하는 것만으로는 충분하지 않다.
제출 직전에 다음을 기계적으로 다시 확인한다.

1. `answer_review.claims`, `choice_diagnostics`, `statement_diagnostics` 중 실제 과학 판단을 담은
   항목 하나 이상에 non-empty `evidence_ids`가 있어야 한다. 선택한 각 ID의 evidence reference에는
   `SCIENTIFIC_VALIDATION` purpose가 있어야 한다.
2. `curriculum_assessment.evidence_ids`는 non-empty여야 한다. 선택한 각 ID의 evidence reference에는
   `CURRICULUM_SCOPE` purpose가 있어야 한다.
3. 같은 manifest entry가 두 판단에 실제로 유효하면 같은 evidence ID를 두 위치에서 재사용할 수 있다.
   그러나 reference에 purpose만 나열하고 판정 필드의 `evidence_ids`를 빈 배열로 두지 마라.
4. 모든 evidence ID는 핀된 manifest/context 또는 연결된 solution report에서 실제 판단을 뒷받침해야
   한다. 근거가 없다면 임의 ID를 채우지 말고 역할 실행을 실패시켜라.

이 결속은 독창성·시각 검토의 evidence 필드와 별개이며, 기존 exact source Item Revision 및
`STRUCTURE_PATTERN` 검증을 완화하지 않는다.
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
    pack["pack"]["version"] = "1.20.9"
    pack["pack"]["description"] = (
        "Exact-source variation with explicit scientific and curriculum review evidence binding"
    )
    pack_path.write_text(
        yaml.safe_dump(pack, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    profile_path = target / "profiles/generated-knowledge-review.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["profile"]["version"] = "12.1.1"
    profile_path.write_text(
        yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    prompt_path = target / "prompt-templates/review.md"
    prompt = prompt_path.read_text(encoding="utf-8")
    marker = "### Graph 근거의 판정 필드 결속"
    if marker in prompt:
        raise ValueError("review evidence-axis rule already exists")
    prompt_path.write_text(prompt.rstrip() + REVIEW_RULE, encoding="utf-8")


def main() -> None:
    if not TARGET.exists():
        _generate(TARGET)
        return
    with tempfile.TemporaryDirectory(prefix="eom-variation-review-pack-") as temp_dir:
        generated = Path(temp_dir) / "1.20.9"
        _generate(generated)
        if _tree_bytes(TARGET) != _tree_bytes(generated):
            raise ValueError("generated Content Pack 1.20.9 has drifted")


if __name__ == "__main__":
    main()
