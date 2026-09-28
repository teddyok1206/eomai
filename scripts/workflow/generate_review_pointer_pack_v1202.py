#!/usr/bin/env python3
"""Create immutable Content Pack 1.20.2 for canonical review draft pointers."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "content/packs/generated-knowledge-item/1.20.1"
TARGET = ROOT / "content/packs/generated-knowledge-item/1.20.2"

REVIEW_POLICY = r"""

## Canonical semantic draft pointer policy

`draft_json_paths`는 authoring `output.draft` 안의 의미 내용만 가리킨다. 허용되는 첫 경로
segment는 정확히 `answer`, `bottom_stem`, `choices`, `explanations`, `inquiry`, `labeled_blocks`,
`statements`, `stem`, `visuals` 중 하나다. `metadata`, `schema_version`, `item_number`,
`score_display`, `renderer_profile`, `visual_layout`, provenance 및 hash 필드는 검토 근거 경로로
사용하지 마라. 특히 교과 범위 검토에서도 `/metadata/subject`를 만들지 말고, 실제 판단 대상인
`/stem`, `/statements/0/text`, `/choices/0/text`, `/inquiry/procedure`,
`/explanations/correct_answer` 같은 존재하는 primitive scalar leaf를 사용한다.

경로를 추측하지 마라. authoring draft를 먼저 읽고 실제 존재하는 key와 배열 index만 선택한다.
object, array, null을 끝값으로 갖는 경로와 허용 루트 밖의 경로가 하나라도 필요하면 VERIFIED 또는
review_pass를 만들지 말고 역할 실행을 실패시킨다.

각 verification target의 `required_source_classes`는 그 target에서 실제 선택한 모든
`selected_evidence_ids`가 manifest에 선언한 `source.source_class`의 정렬·중복 제거된 집합과 정확히
같아야 한다. 선택하지 않은 source class를 요구하거나, required 목록에 없는 class의 evidence를
선택하지 마라. 필요한 source class가 핀된 manifest에 없으면 다른 class로 대신하지 말고
`evidence_status=INSUFFICIENT`로 두며 selected evidence를 근거 있는 범위로만 제한한다.
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
    pack["pack"]["version"] = "1.20.2"
    pack["pack"]["description"] = "Graph-grounded review with canonical semantic draft pointers"
    pack_path.write_text(
        yaml.safe_dump(pack, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    profile_path = target / "profiles/generated-knowledge-review.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["profile"]["version"] = "12.0.1"
    profile_path.write_text(
        yaml.safe_dump(profile, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    review_path = target / "prompt-templates/review.md"
    review_path.write_text(
        review_path.read_text(encoding="utf-8").rstrip() + "\n" + REVIEW_POLICY,
        encoding="utf-8",
    )


def main() -> None:
    if not TARGET.exists():
        _generate(TARGET)
        return
    with tempfile.TemporaryDirectory(prefix="eom-review-pointer-pack-") as temp_dir:
        generated = Path(temp_dir) / "1.20.2"
        _generate(generated)
        if _tree_bytes(TARGET) != _tree_bytes(generated):
            raise ValueError("generated Content Pack 1.20.2 has drifted")


if __name__ == "__main__":
    main()
