#!/usr/bin/env python3
"""Create immutable Content Pack 1.20.1 for simplified morphology conditioning."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "content/packs/generated-knowledge-item/1.20.0"
TARGET = ROOT / "content/packs/generated-knowledge-item/1.20.1"

IMAGE_POLICY = r"""

## Minimal reference-conditioned line-art policy

이 후속 정책은 위 팀장 원문 두 개와 KICE 삽화 가이드를 바꾸지 않는다. 로컬 GPU에 전달되는 파생
표현만 더 제한한다. 승인된 참조가 있으면 참조의 대상 개수, 실루엣, 자세, 시점, 상대 위치, 겹침,
크기와 framing을 그대로 보존하고 스타일만 시험지용 선화로 바꾼다. 대상을 추가·삭제·복제하거나
시점을 바꾸지 마라.

GPU raster는 대상의 비권위 형태만 담당한다. 잔털·피부·금속·천·암석의 미세 질감, 촘촘한 해칭,
교차 해칭, 점묘, 긁힘, 극적인 명암과 복잡한 배경을 만들지 않는다. 큰 외곽선과 식별에 필요한 큰
내부 윤곽선만 남기고, 연회색은 넓은 면에 드물게 사용한다. 글자·숫자·축·화살표·눈금·정확한 개수와
정답을 좌우하는 기하 관계는 계속 deterministic SVG overlay가 담당한다.

비커나 자동차처럼 사물의 외형을 참조할 수는 있지만, 액면 높이·연결관·가열 위치·힘의 방향처럼
정답을 좌우하는 정보가 있는 장치 조립도는 `DETERMINISTIC_SVG`로 작성한다. 참조를 단순화해도 권위
구조를 안전하게 분리할 수 없으면 HYBRID로 우회하지 말고 작업을 실패시킨다.
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
    pack["pack"]["version"] = "1.20.1"
    pack["pack"]["description"] = (
        "Graph-grounded review with simplified morphology reference conditioning"
    )
    pack_path.write_text(
        yaml.safe_dump(pack, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    profile_path = target / "profiles/generated-stimulus-drawing.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["profile"]["version"] = "12.2.1"
    profile_path.write_text(
        yaml.safe_dump(profile, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    image_path = target / "prompt-templates/image.md"
    image_path.write_text(
        image_path.read_text(encoding="utf-8").rstrip() + "\n" + IMAGE_POLICY,
        encoding="utf-8",
    )


def main() -> None:
    if not TARGET.exists():
        _generate(TARGET)
        return
    with tempfile.TemporaryDirectory(prefix="eom-minimal-line-art-pack-") as temp_dir:
        generated = Path(temp_dir) / "1.20.1"
        _generate(generated)
        if _tree_bytes(TARGET) != _tree_bytes(generated):
            raise ValueError("generated Content Pack 1.20.1 has drifted")


if __name__ == "__main__":
    main()
